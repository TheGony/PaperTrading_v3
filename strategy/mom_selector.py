import asyncio
import math
from api.ranking import fn_ka10030, fn_ka10032, fn_ka10023
from api.foreign import fn_ka90009
from api.account import fn_kt00004
from util.get_setting import get_setting
from util.tel_send import tel_send
from util.logger import get_logger


class StockSelectorMixin:
	EXCLUDE_KEYWORDS = [
		'ETF', 'ETN', '레버리지', '인버스',
		'2X', '3X', '선물', '채권', 'TR',
		'액티브', '합성', '커버드콜',
		'스팩', 'SPAC', '미국', '차이나',
		'KODEX', 'TIGER', 'ARIRANG',
		'RISE', 'KBSTAR', 'SOL', 'HANARO', 'ACE',
	]

	STOCK_REFRESH_INTERVAL = 5 * 60  # MOMENTUM 종목 갱신 주기: 5분

	def _is_excluded(self, stk_nm):
		return any(kw in stk_nm for kw in self.EXCLUDE_KEYWORDS)

	def _fmt_stocks(self, stock_codes):
		"""종목 코드 리스트를 '종목명(코드)' 형식의 문자열로 변환"""
		return ', '.join(
			f"{self.selected_stocks_names.get(c, c)}({c})" for c in stock_codes
		)

	async def _get_exclusion_set(self):
		"""보유 종목 + 당일 2회 이상 손절 종목 코드 set 반환"""
		excluded = {cd for cd, cnt in self.daily_loss_count.items() if cnt >= 2}
		try:
			my_stk, _, _ = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt00004, False, 'N', '', self.token
			)
			if my_stk:
				for s in my_stk:
					cd = s.get('stk_cd', '').replace('A', '').strip()
					if cd:
						excluded.add(cd)
		except Exception:
			pass
		return excluded

	async def _fetch_momentum_stocks(self):
		"""MOMENTUM 전략 종목 선정: ka10030(주) + ka10023(보조), ka90009(수급)"""
		stock_count = get_setting('stock_count', 10)
		chart_long  = get_setting('chart_long', 20)
		rsi_period  = 14
		needed      = max(chart_long + 1, rsi_period + 2)

		# ── 1. API 조회 (ka10030 거래량 상위 + ka10023 급증 보조 병합) ──
		raw_vol, raw_surge = await asyncio.gather(
			asyncio.get_event_loop().run_in_executor(None, fn_ka10030, 30, 'N', '', self.token),
			asyncio.get_event_loop().run_in_executor(None, fn_ka10023, 30, 'N', '', self.token),
		)
		seen = {}
		for s in (raw_vol or []) + (raw_surge or []):
			cd = s.get('stk_cd', '')
			if cd and cd not in seen:
				seen[cd] = s
		raw = list(seen.values())
		if not raw:
			return []

		# ── 2. ETF/ETN 제거 + 과열 제외 ─────────────────────
		raw = [s for s in raw if not self._is_excluded(s.get('stk_nm', ''))]
		raw = [s for s in raw if s.get('flu_rt', 0) <= 23]

		# ── 3. 1차 필터: 등락률 ≥ +0.3%, 거래대금 ≥ 10억 ──────
		filtered = [
			s for s in raw
			if s.get('flu_rt', 0) >= 0.3
			and s.get('trde_amt', 0) >= 1000
		]
		pool = filtered if filtered else raw

		# 거래대금 순위
		amt_sorted = sorted(pool, key=lambda s: s.get('trde_amt', 0), reverse=True)
		amt_rank   = {s['stk_cd']: i + 1 for i, s in enumerate(amt_sorted)}

		# ── 4. 기관/외인 조회 ────────────────────────────────
		buy_stocks = await asyncio.get_event_loop().run_in_executor(
			None, fn_ka90009, 'N', '', self.token
		)

		# ── 5. 차트 필터 → 후보 수집 (병렬, 공유 캐시) ──────────
		async def _fetch(s):
			prices, *_ = await self._get_chart(s['stk_cd'], needed)
			if not prices or len(prices) < needed:
				return None
			rsi = self._calc_rsi(prices, rsi_period)
			return {
				**s,
				'trde_amt_rank': amt_rank.get(s['stk_cd'], len(pool)),
				'rsi_val':       rsi if rsi is not None else 50.0,
				'is_foreign':    bool(buy_stocks and s['stk_cd'] in buy_stocks),
				'strategy':      'MOMENTUM',
			}

		results    = await asyncio.gather(*[_fetch(s) for s in pool], return_exceptions=True)
		candidates = []
		failed_stk = []
		for s, r in zip(pool, results):
			if r is not None and not isinstance(r, Exception):
				candidates.append(r)
			else:
				failed_stk.append(s)

		# ── 6. 로그 정규화 후 스코어 계산 ──────────────────────
		# score = volume*0.30 + flu*0.25 + rsi*0.20 + foreign*0.15 + sdnin*0.10
		scored = []
		if candidates:
			amt_list   = [c.get('trde_amt', 0)  for c in candidates]
			flu_list   = [c.get('flu_rt', 0)    for c in candidates]
			sdnin_list = [c.get('sdnin_rt', 0)  for c in candidates]
			max_amt    = max(amt_list) or 1
			max_flu    = max(flu_list)
			min_flu    = min(flu_list)
			flu_range  = (max_flu - min_flu) or 1
			max_sdnin  = max(sdnin_list) or 1

			for c in candidates:
				volume_norm   = math.log(max(c.get('trde_amt', 1), 1)) / math.log(max(max_amt, 2))
				flu_norm      = (c.get('flu_rt', 0) - min_flu) / flu_range
				rsi_norm      = c['rsi_val'] / 100
				foreign_score = 1.0 if c['is_foreign'] else 0.0
				sdnin_norm    = c.get('sdnin_rt', 0) / max_sdnin

				score = (
					volume_norm   * 0.30 +
					flu_norm      * 0.25 +
					rsi_norm      * 0.20 +
					foreign_score * 0.15 +
					sdnin_norm    * 0.10
				)
				scored.append({
					**{k: v for k, v in c.items() if k not in ('rsi_val',)},
					'score': score,
					'rsi':   round(c['rsi_val'], 1),
				})

		scored.sort(key=lambda x: x['score'], reverse=True)

		# fallback: 차트 미통과 종목을 거래대금+등락률 기준으로 보충
		if len(scored) < stock_count:
			scored_cds = {s['stk_cd'] for s in scored}
			fb_pool = [s for s in pool if s['stk_cd'] not in scored_cds and s.get('flu_rt', 0) > 0]
			if fb_pool:
				fb_amt       = [s.get('trde_amt', 0) for s in fb_pool]
				fb_flu       = [s.get('flu_rt', 0)   for s in fb_pool]
				fb_max_amt   = max(fb_amt) or 1
				fb_max_flu   = max(fb_flu)
				fb_min_flu   = min(fb_flu)
				fb_flu_range = (fb_max_flu - fb_min_flu) or 1
				fb = []
				for s in fb_pool:
					volume_norm = math.log(max(s.get('trde_amt', 1), 1)) / math.log(max(fb_max_amt, 2))
					flu_norm    = (s.get('flu_rt', 0) - fb_min_flu) / fb_flu_range
					score = volume_norm * 0.6 + flu_norm * 0.4
					fb.append({
						**s,
						'trde_amt_rank': amt_rank.get(s['stk_cd'], len(pool)),
						'score':         score,
						'strategy':      'MOMENTUM',
					})
				fb.sort(key=lambda x: x['score'], reverse=True)
				scored += fb[:stock_count - len(scored)]

		# ── 7. candidate_log 기록 ────────────────────────────────
		if hasattr(self, '_log_candidates'):
			selected_cds = {s['stk_cd'] for s in scored[:stock_count]}
			log_entries  = []
			for s in failed_stk:
				log_entries.append({'stock': s, 'selected': False, 'reason': '데이터 부족', 'rank': None, 'score': None, 'rsi': None})
			for i, c in enumerate(scored):
				is_sel = c['stk_cd'] in selected_cds
				log_entries.append({
					'stock':    c,
					'selected': is_sel,
					'reason':   '' if is_sel else '점수 낮음',
					'rank':     i + 1 if is_sel else None,
					'score':    c.get('score'),
					'rsi':      c.get('rsi'),
				})
			self._log_candidates(log_entries)

		return scored[:stock_count]

	async def _select_initial_stocks(self):
		"""MOMENTUM 전략 초기 종목 선정"""
		ranked_stocks = await self._fetch_momentum_stocks()
		if not ranked_stocks:
			tel_send("⚠️ [MOMENTUM] 종목 선정 실패 - 다음 갱신 주기에 재시도합니다")
			return False

		exclusion_set = await self._get_exclusion_set()
		if exclusion_set:
			before = len(ranked_stocks)
			ranked_stocks = [s for s in ranked_stocks if s['stk_cd'] not in exclusion_set]
			if len(ranked_stocks) < before:
				get_logger().info(f'[종목선정] 제외: {exclusion_set} ({before}→{len(ranked_stocks)}개)')

		self.selected_stocks       = [s['stk_cd'] for s in ranked_stocks]
		self.selected_stocks_names = {s['stk_cd']: s.get('stk_nm', s['stk_cd']) for s in ranked_stocks}
		self.selected_stocks_meta  = {
			s['stk_cd']: {
				'flu_rt':        s.get('flu_rt', 0),
				'score':         s.get('score', 0),
				'is_foreign':    s.get('is_foreign', False),
				'trde_amt':      s.get('trde_amt', None),
				'trde_amt_rank': s.get('trde_amt_rank', None),
				'strategy':      'MOMENTUM',
				'rank':          i + 1,
				'rsi':           s.get('rsi', None),
			} for i, s in enumerate(ranked_stocks)
		}

		tel_send(
			f"✅ [MOMENTUM] 초기 종목 선정 완료\n"
			f"   전략: 직전 5봉 고점 돌파 확인(3초) + RSI 45~70 + RSI상승\n"
			f"   종목: {self._fmt_stocks(self.selected_stocks)}"
		)
		return True

	async def _refresh_selected_stocks(self):
		"""MOMENTUM 종목 갱신 (5분 주기 또는 즉시 보충) — 점수 비교 후 선택적 교체"""
		try:
			ranked_stocks = await self._fetch_momentum_stocks()
			if not ranked_stocks:
				tel_send("⚠️ [MOMENTUM] 종목 갱신 실패 - 기존 종목 유지")
				return

			exclusion_set = await self._get_exclusion_set()
			stock_count   = get_setting('stock_count', 10)

			# 새로 조회된 후보 맵 (제외 종목 필터링)
			new_map = {s['stk_cd']: s for s in ranked_stocks if s['stk_cd'] not in exclusion_set}

			# ── 점수 비교 기반 병합 ─────────────────────────────────
			merged_pool = {}
			for cd in self.selected_stocks:
				if cd in exclusion_set:
					continue
				if cd in new_map:
					merged_pool[cd] = new_map[cd]
				else:
					old = self.selected_stocks_meta.get(cd, {})
					merged_pool[cd] = {
						'stk_cd':     cd,
						'stk_nm':     self.selected_stocks_names.get(cd, cd),
						'score':      old.get('score', 0),
						'flu_rt':     old.get('flu_rt', 0),
						'is_foreign': old.get('is_foreign', False),
						'strategy':   'MOMENTUM',
					}

			for cd, s in new_map.items():
				if cd not in merged_pool:
					merged_pool[cd] = s

			final_stocks = sorted(merged_pool.values(), key=lambda x: x['score'], reverse=True)[:stock_count]
			new_stocks   = [s['stk_cd'] for s in final_stocks]
			new_names    = {s['stk_cd']: s.get('stk_nm', s['stk_cd']) for s in final_stocks}
			new_meta     = {
				s['stk_cd']: {
					'flu_rt':        s.get('flu_rt', 0),
					'score':         s.get('score', 0),
					'is_foreign':    s.get('is_foreign', False),
					'trde_amt':      s.get('trde_amt', None),
					'trde_amt_rank': s.get('trde_amt_rank', None),
					'strategy':      'MOMENTUM',
					'rank':          i + 1,
					'rsi':           s.get('rsi', None),
				} for i, s in enumerate(final_stocks)
			}

			added   = [s for s in new_stocks if s not in self.selected_stocks]
			removed = [s for s in self.selected_stocks if s not in new_stocks]

			self.selected_stocks_names.update(new_names)
			final_map = {s['stk_cd']: s for s in final_stocks}

			def _with_score(codes, src):
				parts = []
				for cd in codes:
					nm    = src.get(cd, {}).get('stk_nm') or self.selected_stocks_names.get(cd, cd)
					score = src.get(cd, {}).get('score', 0)
					parts.append(f"{nm}({cd}, {score:.2f})")
				return ', '.join(parts)

			if added or removed:
				msg = "🔄 [MOMENTUM] 종목 갱신\n"
				if added:
					msg += f"   신규 편입: {_with_score(added, final_map)}\n"
				if removed:
					msg += f"   편출: {_with_score(removed, self.selected_stocks_meta)}\n"
				msg += f"   현재 선정: {self._fmt_stocks(new_stocks)}"
			else:
				msg = f"🔄 [MOMENTUM] 종목 유지 (점수 기준 변경 없음)\n   선정 종목: {self._fmt_stocks(new_stocks)}"

			self.selected_stocks_meta = new_meta
			self.selected_stocks      = new_stocks
			tel_send(msg)

		except Exception as e:
			print(f"종목 갱신 오류: {e}")
			tel_send(f"⚠️ 종목 갱신 중 오류: {e} - 기존 종목 유지")
