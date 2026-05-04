import asyncio
import math
from api.chart import fn_ka10080_full
from api.ranking import fn_ka10032, fn_ka10030
from util.tel_send import tel_send
from util.logger import get_logger


class OrbSelectorMixin:
	ORB_CANDIDATES_MAX = 7
	ORB_MIN_CANDIDATES = 5

	async def _get_orb_candidates(self, is_refresh=False):
		"""ORB 전용 후보 선정. 결과를 self.orb_candidates에 저장."""
		log = get_logger()

		# ── 1. 병렬 API 조회 ────────────────────────────────────
		raw_trde, raw_vol = await asyncio.gather(
			asyncio.get_event_loop().run_in_executor(None, fn_ka10032, 30, 'N', '', self.token),  # 거래대금 상위
			asyncio.get_event_loop().run_in_executor(None, fn_ka10030, 30, 'N', '', self.token),  # 당일 거래량 상위
		)

		if not raw_trde and not raw_vol:
			tel_send("⚠️ [ORB] 후보 조회 실패 (거래대금/거래량 API 응답 없음)")
			self.orb_candidates = []
			return []

		# ── 2. 보조 데이터 맵 구축 ───────────────────────────────
		# ka10030: 당일 거래량 (trde_qty) 맵
		vol_map      = {s['stk_cd']: s.get('trde_qty', 0) for s in (raw_vol or [])}
		trde_amt_map = {s['stk_cd']: s.get('trde_amt', 0) for s in (raw_vol or [])}

		# ── 3. 유동성 풀 구성 (ka10032 + ka10030 병합, ETF/ETN 제거) ──
		seen = {}
		for s in (raw_trde or []) + (raw_vol or []):
			cd = s.get('stk_cd', '')
			if cd and cd not in seen:
				seen[cd] = s
		pool = [s for s in seen.values()
				if not self._is_excluded(s.get('stk_nm', ''))
				and s.get('flu_rt', 0) < 23]

		if not pool:
			tel_send("⚠️ [ORB] ETF/ETN 제거 후 후보 없음")
			self.orb_candidates = []
			return []

		# ── 4. 캔들 필터 (09:00~09:10) ───────────────────────────
		def _hhmm(t):
			t = str(t).strip()
			return t[8:12] if len(t) >= 14 else t[0:4]

		candidates = []
		for s in pool:
			stk_cd  = s['stk_cd']
			candles = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka10080_full, stk_cd, 20, 'N', '', self.token
			)
			await asyncio.sleep(0.2)
			if not candles:
				continue

			# 09:00~09:10 1분봉 추출 (최대 10개)
			open_candles = [c for c in candles if '0900' <= _hhmm(c['cntr_tm']) <= '0910']
			if not open_candles:
				continue

			# 갭 계산: (당일 시가 - 전일 종가) / 전일 종가 * 100
			first      = open_candles[-1]  # 09:00봉 (가장 오래된)
			day_open   = first['open_pric']
			prev_close = first['cur_prc'] - first['pred_pre']
			if prev_close <= 0 or day_open <= 0:
				continue
			gap = (day_open - prev_close) / prev_close * 100

			cur_prc = candles[0]['cur_prc']

			# 갭 하락 처리: -1% 미만은 제외, -1~0% 구간은 현재가가 시가 회복 시만 허용
			if gap < -1.0:
				continue
			if gap <= 0 and cur_prc <= day_open:
				continue

			# 시가 대비 -2% 이상 눌림 제외
			if cur_prc < day_open * 0.98:
				continue

			# ── 1분봉 세부 분석 ─────────────────────────────────────
			latest_high      = candles[0]['high_pric']
			upper_tail_ratio = (latest_high - cur_prc) / latest_high if latest_high > 0 else 0
			bearish_count    = sum(1 for c in open_candles if c['cur_prc'] < c['open_pric'])

			# 10분 구간 최고가 대비 현재가 위치 (1에 가까울수록 고점 유지)
			max_high_10    = max((c['high_pric'] for c in open_candles), default=cur_prc)
			price_position = cur_prc / max_high_10 if max_high_10 > 0 else 1.0

			# 연속 양봉 여부: 가장 최근 3봉이 모두 양봉이면 True
			recent_3      = open_candles[:3]  # open_candles는 최신순
			consec_bull   = len(recent_3) == 3 and all(c['cur_prc'] >= c['open_pric'] for c in recent_3)

			# 최근 3분 거래량 합계 (모멘텀 보조 지표)
			vol_3m = sum(c.get('trde_qty', 0) for c in candles[:3])

			# ── 소프트 패널티 계산 ───────────────────────────────────
			penalty = 0.0
			if not (1.5 <= gap <= 8.0):
				penalty += 0.2
			if upper_tail_ratio > 0.05:
				penalty += 0.2
			if bearish_count >= 4:    # 강화: 4개 이상이면 패널티 가중
				penalty += 0.4
			elif bearish_count >= 2:
				penalty += 0.2
			if price_position < 0.92:  # 10분 고점 대비 8% 이상 밀림
				penalty += 0.3
			elif price_position < 0.95:
				penalty += 0.15
			if consec_bull:            # 연속 양봉 보너스
				penalty -= 0.1

			# ORB 범위 데이터: 09:00~09:04 봉으로 사전 계산 (_try_orb_entry 재활용)
			orb_sub      = [c for c in open_candles if _hhmm(c['cntr_tm']) <= '0904']
			orb_candle_n = len(orb_sub)
			if orb_sub:
				orb_high_pre = max(c['high_pric'] for c in orb_sub)
				orb_low_pre  = min(c['low_pric']  for c in orb_sub)
			else:
				orb_high_pre = None
				orb_low_pre  = None
			gap_up = gap > 0 or (gap >= -1.0 and cur_prc > day_open)

			# 거래대금: ka10032 우선, 없으면 ka10030 값 사용
			trde_prica = s.get('trde_prica', 0) or trde_amt_map.get(stk_cd, 0)

			candidates.append({
				'stk_cd':        stk_cd,
				'stk_nm':        s.get('stk_nm', stk_cd),
				'gap':           round(gap, 2),
				'flu_rt':        s.get('flu_rt', 0),
				'trde_prica':    trde_prica,
				'trde_qty':      vol_map.get(stk_cd, 0),
				'vol_3m':        vol_3m,
				'price_position': round(price_position, 3),
				'consec_bull':   consec_bull,
				'penalty':       penalty,
				'strategy':      'ORB',
				# ORB 범위 캐시 (_try_orb_entry 중복 API 호출 방지)
				'orb_high':      orb_high_pre,
				'orb_low':       orb_low_pre,
				'gap_up':        gap_up,
				'day_open':      day_open,
				'orb_candle_n':  orb_candle_n,
			})

		# ── 5. 스코어링 ───────────────────────────────────────────
		# score = trde_amt_norm*0.50 + today_volume_norm*0.20 + flu_rt_norm*0.30 - penalty
		if candidates:
			max_trde = max(c['trde_prica'] for c in candidates) or 1
			max_vol  = max(c['trde_qty']   for c in candidates) or 1
			max_flu  = max((c['flu_rt']     for c in candidates if c['flu_rt'] > 0), default=1) or 1

			for c in candidates:
				trde_amt_norm     = math.log(max(c['trde_prica'], 1)) / math.log(max(max_trde, 2))
				today_volume_norm = math.log(max(c['trde_qty'],   1)) / math.log(max(max_vol,  2))
				flu_rt_norm       = max(c['flu_rt'], 0) / max_flu

				c['score'] = (
					trde_amt_norm     * 0.50 +
					today_volume_norm * 0.20 +
					flu_rt_norm       * 0.30
					- c['penalty']
				)
			candidates.sort(key=lambda x: x['score'], reverse=True)

		# ── 6. 최소 후보 보충 (캔들 필터 미통과 종목, 거래대금 순) ──
		if len(candidates) < self.ORB_MIN_CANDIDATES:
			existing = {c['stk_cd'] for c in candidates}
			before   = len(candidates)
			for s in pool:
				if len(candidates) >= self.ORB_MIN_CANDIDATES:
					break
				if s['stk_cd'] in existing:
					continue
				trde_prica = s.get('trde_prica', 0) or trde_amt_map.get(s['stk_cd'], 0)
				candidates.append({
					'stk_cd':     s['stk_cd'],
					'stk_nm':     s.get('stk_nm', s['stk_cd']),
					'gap':        None,
					'flu_rt':     s.get('flu_rt', 0),
					'trde_prica': trde_prica,
					'trde_qty':   vol_map.get(s['stk_cd'], 0),
					'score':      -0.5,
					'penalty':    0.0,
					'strategy':   'ORB',
				})
				existing.add(s['stk_cd'])
			added = len(candidates) - before
			if added > 0:
				tel_send(f"⚠️ [ORB] 후보 부족 → 거래대금 상위 {added}종목 보충 (총 {len(candidates)}종목)")

		if not candidates:
			label = "2차 갱신" if is_refresh else "선정"
			tel_send(f"⚠️ [ORB] 조건을 충족하는 후보 없음 ({label})")
			self.orb_candidates = []
			return []

		candidates.sort(key=lambda x: x['score'], reverse=True)
		self.orb_candidates = candidates[:self.ORB_CANDIDATES_MAX]

		# ── orb_data 선제 구축: _try_orb_entry의 fn_ka10080_full 중복 호출 방지 ──
		for c in self.orb_candidates:
			cd = c['stk_cd']
			if cd not in self.orb_data and c.get('orb_high') is not None:
				self.orb_data[cd] = {
					'high':     c['orb_high'],
					'low':      c['orb_low'],
					'gap_up':   c['gap_up'],
					'day_open': c['day_open'],
				}
				log.info(f'[ORB] {cd} orb_data 선제 구축: high={c["orb_high"]:.0f} low={c["orb_low"]:.0f}')

		names = ', '.join(
			f"{c['stk_nm']}({c['stk_cd']}) gap={c['gap']:+.1f}%" if c['gap'] is not None
			else f"{c['stk_nm']}({c['stk_cd']}) gap=N/A"
			for c in self.orb_candidates
		)
		label = "2차 갱신" if is_refresh else "선정"
		tel_send(f"✅ [ORB] 후보 {len(self.orb_candidates)}종목 {label}\n   {names}")
		log.info(f'[ORB 선정] {names}')
		return self.orb_candidates
