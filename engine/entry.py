import asyncio
import datetime
from api.chart import fn_ka10080, fn_ka10080_full
from api.account import fn_kt00004, fn_kt00001, fn_kt00002
from api.order import fn_kt10000
from api.market import fn_ka10001, fn_get_market_index
from util.market_hour import MarketHour
from util.get_setting import get_setting
from util.tel_send import tel_send
from util.logger import get_logger


class EntryMixin:
	_CHART_CACHE_TTL = 55  # 초 (1분봉 갱신 주기보다 짧게, 실전 시 0으로 설정하면 캐시 비활성화)

	async def _get_chart(self, stk_cd, needed):
		"""ka10080 조회 with 캐시. 캐시 TTL 내 동일 종목 재요청 시 API 호출 생략."""
		now    = datetime.datetime.now()
		cached = self._chart_cache.get(stk_cd)
		if cached and (now - cached['ts']).total_seconds() < self._CHART_CACHE_TTL:
			return cached['data']
		data = await asyncio.get_event_loop().run_in_executor(
			None, fn_ka10080, stk_cd, needed, 'N', '', self.token
		)
		await asyncio.sleep(1.0)
		self._chart_cache[stk_cd] = {'ts': now, 'data': data}
		return data

	async def _check_charts_and_trade(self):
		"""1분봉 기준 고점 돌파 진입 / 데드크로스+RSI 청산 (phase 기반)"""
		max_retries = 5
		retry_delay = 1  # 1초

		for attempt in range(max_retries):
			try:
				chart_short      = get_setting('chart_short', 5)
				chart_long       = get_setting('chart_long', 20)
				rsi_period       = 14
				cooldown_minutes = 20
				needed = max(chart_long + 1, rsi_period + 2)

				breakout_bars = 5  # MOMENTUM 고정

				# 보유 종목 확인
				my_stocks, aset_evlt_amt_cache, _ = await asyncio.get_event_loop().run_in_executor(
					None, fn_kt00004, False, 'N', '', self.token
				)
				if my_stocks is None:
					# API 실패 시 보유 종목 확인 불가 → 이중 매수 방지를 위해 이번 회차 스킵
					get_logger().warning('[차트체크] fn_kt00004 실패 — 이번 회차 스킵')
					await asyncio.sleep(5)
					continue
				held_stock_codes = [stock['stk_cd'].replace('A', '') for stock in my_stocks]

				# ── ORB 진입 루프 (09:05~09:30, 초반 전용) ──────────
				if self.orb_candidates:
					now_time = datetime.datetime.now().time()
					if datetime.time(9, 5) <= now_time <= datetime.time(9, 30):
						for orb_stock in self.orb_candidates:
							stk_cd_orb = orb_stock['stk_cd']
							if stk_cd_orb in held_stock_codes or stk_cd_orb in self.entry_time:
								continue
							p_orb, v_orb, _, _ = await self._get_chart(stk_cd_orb, needed)
							if len(p_orb) < needed or any(p == 0.0 for p in p_orb):
								continue
							rsi_orb = self._calc_rsi(p_orb, rsi_period)
							rsi_s_orb = f"{rsi_orb:.1f}" if rsi_orb is not None else "N/A"
							await self._try_orb_entry(stk_cd_orb, p_orb[0], p_orb, v_orb, rsi_orb, rsi_s_orb, acnt_cache=(my_stocks, aset_evlt_amt_cache))

				# 체크할 종목 (선정된 종목 + 보유 종목)
				stocks_to_check = list(set(self.selected_stocks + held_stock_codes))

				for stk_cd in stocks_to_check:
					# 1분봉 데이터 조회 (needed개, 최신순) - 종가 + 거래량 + 시가 + 고가
					prices, volumes, _, _ = await self._get_chart(stk_cd, needed)

					# 데이터 유효성 검사
					if len(prices) < needed or any(p == 0.0 for p in prices):
						print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: 데이터 부족 또는 유효하지 않음 ({len(prices)}/{needed}개)")
						continue

					current_price = prices[0]

					# ── 데드크로스 감지 (청산용) ──────────────────────────
					ma_short_curr = self._calc_ma(prices, chart_short)
					ma_long_curr  = self._calc_ma(prices, chart_long)
					ma_short_prev = self._calc_ma(prices[1:], chart_short)
					ma_long_prev  = self._calc_ma(prices[1:], chart_long)

					if None in (ma_short_curr, ma_long_curr, ma_short_prev, ma_long_prev):
						continue

					dead_cross = (ma_short_prev >= ma_long_prev) and (ma_short_curr < ma_long_curr)

					print(
						f"{stk_cd} | 현재가: {current_price:.0f} "
						f"| MA{chart_short}: {ma_short_curr:.1f} MA{chart_long}: {ma_long_curr:.1f}"
					)

					# ── 청산: 데드크로스 AND RSI < 45 ────────────────────
					if dead_cross and stk_cd in held_stock_codes:
						rsi_exit = self._calc_rsi(prices, rsi_period)
						if rsi_exit is not None and rsi_exit < 45:
							signal_info = (
								f"📉 데드크로스+RSI 청산\n"
								f"   MA{chart_short}: {ma_short_curr:.1f} < MA{chart_long}: {ma_long_curr:.1f}\n"
								f"   RSI: {rsi_exit:.1f} < 45"
							)
							await self._sell_stock(stk_cd, '데드크로스', signal_info=signal_info)
						else:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: 데드크로스 감지 but RSI {f'{rsi_exit:.1f}' if rsi_exit else 'N/A'} >= 45 - 청산 보류")

					# ── 진입 (phase별 조건) ──────────────────────────
					if stk_cd in self.selected_stocks and stk_cd not in held_stock_codes and stk_cd not in self.entry_time:

						if not MarketHour.is_entry_allowed():
							continue

						breakout_high = max(prices[1:breakout_bars + 1])

						chase_limit = 1.015  # MOMENTUM 고정
						if current_price > breakout_high * chase_limit:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd} 탈락: 추격매수 방지 (현재가 {current_price:.0f} > 고점×{chase_limit} {breakout_high*chase_limit:.0f})")
							continue

						# 실제 돌파 미발생이면 대기 (0.995~1.0 구간은 준비 상태만)
						if current_price <= breakout_high:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd} 탈락: 돌파 미발생 (현재가 {current_price:.0f} ≤ 고점 {breakout_high:.0f})")
							continue

						# 쿨다운: 매도 후 20분 이내 재매수 금지
						last_sell = self.sell_cooldown.get(stk_cd)
						if last_sell:
							elapsed = (datetime.datetime.now() - last_sell).total_seconds() / 60
							if elapsed < cooldown_minutes:
								print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: 쿨다운 중 ({elapsed:.0f}/{cooldown_minutes}분) - 매수 스킵")
								continue

						curr_vol = volumes[0] if len(volumes) > 0 else 0
						prev_vol = volumes[1] if len(volumes) > 1 else 0
						rsi      = self._calc_rsi(prices, rsi_period)
						rsi_str  = f"{rsi:.1f}" if rsi is not None else "N/A"

						prev_rsi = self._calc_rsi(prices[1:], rsi_period)

						# ── MOMENTUM 진입 조건: RSI 45~70 + RSI 상승 중 ──────
						if rsi is None or rsi < 45:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: RSI {rsi_str} < 45 - 매수 스킵")
							continue
						if rsi > 70:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: RSI {rsi_str} > 70 (과열) - 매수 스킵")
							continue
						if prev_rsi is not None and rsi < prev_rsi * 0.98:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: RSI 하락 중 ({prev_rsi:.1f}→{rsi_str}) - 매수 스킵")
							continue

						# ── 당일 2회 손실 종목 진입 금지 ────────────────
						if self.daily_loss_count.get(stk_cd, 0) >= 2:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: 당일 손실 {self.daily_loss_count[stk_cd]}회 - 금일 거래 금지")
							continue

						# ── 과열 종목 진입 금지 (등락률 > 23%) ────────
						flu_rt = self.selected_stocks_meta.get(stk_cd, {}).get('flu_rt', 0)
						if flu_rt > 23:
							print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {stk_cd}: 과열(flu_rt={flu_rt:.1f}% > 23%) - 매수 스킵")
							continue

						# ── 진입 스냅샷 빌드 ────────────────────────────
						confirm_secs = 3.0
						meta = self.selected_stocks_meta.get(stk_cd, {})
						kospi_flu, kosdaq_flu = await asyncio.get_event_loop().run_in_executor(
							None, fn_get_market_index, self.token
						)
						market_open  = datetime.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
						entry_time_min     = round((datetime.datetime.now() - market_open).total_seconds() / 60, 1)
						breakout_strength  = round((current_price / breakout_high - 1) * 100, 2)
						entry_snapshot = {
							'entry_price':     current_price,
							'entry_rsi':       round(rsi, 2) if rsi is not None else None,
							'entry_flu_rt':    meta.get('flu_rt', 0),
							'entry_vol_ratio': round(curr_vol / prev_vol, 2) if prev_vol > 0 else None,
							'entry_score':     round(meta.get('score', 0), 4),
						'is_foreign':      meta.get('is_foreign', False),
							'entry_trde_amt':     meta.get('trde_amt', None),
							'entry_trde_amt_rank': meta.get('trde_amt_rank', None),
							'entry_time_min':     entry_time_min,
						}

						# 돌파 유지 확인
						if not await self._confirm_breakout(stk_cd, breakout_high, confirm_secs):
							continue

						gap_to_high = (current_price / breakout_high - 1) * 100
						signal_info = (
							f"📈 [MOMENTUM] 돌파 확인 진입: {stk_cd}\n"
							f"   현재가: {current_price:.0f} | 직전{breakout_bars}봉 고점: {breakout_high:.0f} ({gap_to_high:+.1f}%)\n"
							f"   RSI: {rsi_str} | 거래량: {curr_vol:.0f} (직전봉: {prev_vol:.0f}) | 확인: {confirm_secs}초"
						)
						await self._buy_stock(stk_cd, current_price, signal_info=signal_info, snapshot=entry_snapshot, acnt_cache=(my_stocks, aset_evlt_amt_cache))

				# 성공적으로 완료되면 루프 종료
				return

			except Exception as e:
				get_logger().error(f'[차트체크 오류] 시도 {attempt + 1}/{max_retries}: {e}', exc_info=True)
				if attempt < max_retries - 1:
					await asyncio.sleep(retry_delay)
				else:
					get_logger().error(f'[차트체크 실패] 최대 재시도 횟수({max_retries}) 초과')

	async def _confirm_breakout(self, stk_cd, breakout_high, confirm_seconds):
		"""돌파 후 confirm_seconds 동안 cur_prc > breakout_high 유지 확인. True=진입, False=초기화"""
		log = get_logger()
		poll_interval = 0.5
		elapsed = 0.0

		while elapsed < confirm_seconds:
			await asyncio.sleep(poll_interval)
			elapsed += poll_interval

			stk_info = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka10001, stk_cd, 'N', '', self.token
			)
			if not stk_info:
				log.info(f'[돌파확인] {stk_cd} API 실패 — 중단')
				return False

			cur_prc = stk_info.get('cur_prc', 0)

			if cur_prc <= breakout_high:
				log.info(f'[돌파확인] {stk_cd} 돌파 이탈 ({cur_prc:.0f} ≤ {breakout_high:.0f}) — 초기화')
				return False

		log.info(f'[돌파확인] {stk_cd} {confirm_seconds}초 유지 완료 → 진입')
		return True

	async def _try_orb_entry(self, stk_cd, current_price, _prices, volumes, rsi, rsi_str, acnt_cache=None):
		"""ORB(Opening Range Breakout) 진입 시도. 성공 시 True 반환"""
		log = get_logger()

		# ORB 범위 확립 (종목당 최초 1회): 09:00~09:04 봉 사용
		if stk_cd not in self.orb_data:
			candles = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka10080_full, stk_cd, 30, 'N', '', self.token
			)
			def _hhmm(t):
				t = str(t).strip()
				return t[8:12] if len(t) >= 14 else t[0:4]

			orb_candles = [c for c in candles if '0900' <= _hhmm(c['cntr_tm']) <= '0904']
			if len(orb_candles) < 3:
				log.info(f'[ORB] {stk_cd} 범위 미확립: 09:00~09:04 봉 {len(orb_candles)}개 (3개 미만)')
				return False

			orb_high = max(c['high_pric'] for c in orb_candles)
			orb_low  = min(c['low_pric']  for c in orb_candles)

			first      = orb_candles[-1]  # 09:00 봉 (가장 오래된)
			prev_close = first['cur_prc'] - first['pred_pre']
			gap_up     = (first['open_pric'] > prev_close) if prev_close > 0 else False

			self.orb_data[stk_cd] = {'high': orb_high, 'low': orb_low, 'gap_up': gap_up}
			log.info(f'[ORB] {stk_cd} 범위 확립: high={orb_high:.0f} low={orb_low:.0f} gap_up={gap_up}')

		orb      = self.orb_data[stk_cd]
		orb_high = orb['high']

		if not orb['gap_up']:
			log.info(f'[ORB] {stk_cd} 진입 거절: 갭상승 없음')
			return False

		if current_price <= orb_high:
			log.info(f'[ORB] {stk_cd} 진입 거절: 현재가({current_price:.0f}) <= ORB고점({orb_high:.0f})')
			return False
		if current_price > orb_high * 1.01:
			log.info(f'[ORB] {stk_cd} 진입 거절: 추격매수 방지 (현재가={current_price:.0f} > ORB고점*1.01={orb_high*1.01:.0f})')
			return False

		curr_vol  = volumes[0] if volumes else 0
		prev_vol  = volumes[1] if len(volumes) > 1 else 0
		vol_ratio = curr_vol / prev_vol if prev_vol > 0 else 0
		if prev_vol == 0 or curr_vol < prev_vol * 1.5:
			log.info(f'[ORB] {stk_cd} 진입 거절: 거래량 미달 (현재={curr_vol:.0f}, 직전={prev_vol:.0f}, {vol_ratio:.2f}x)')
			return False

		if rsi is None or rsi < 50 or rsi > 75:
			log.info(f'[ORB] {stk_cd} 진입 거절: RSI 범위 이탈 (RSI={rsi_str}, 범위: 50<=x<=75)')
			return False

		orb_max = get_setting('orb_max_count', 5)
		if self.orb_buy_count >= orb_max:
			log.info(f'[ORB] {stk_cd} 진입 거절: ORB 최대 매수 횟수 초과 ({self.orb_buy_count}/{orb_max})')
			return False

		last_sell = self.sell_cooldown.get(stk_cd)
		if last_sell:
			elapsed = (datetime.datetime.now() - last_sell).total_seconds() / 60
			if elapsed < 20:
				log.info(f'[ORB] {stk_cd} 진입 거절: 쿨다운 중 ({elapsed:.0f}/20분)')
				return False

		# 손절 기준: ORB 저점 vs -2% 중 타이트한 쪽 (더 높은 가격 = 더 빠른 손절)
		orb_low_pct  = (orb['low'] / current_price - 1) * 100
		orb_stop_pct = round(max(orb_low_pct, -2.0), 2)

		# 진입 오버슈트: 진입가가 ORB 고점 대비 얼마나 위인지
		orb_overshoot = round((current_price / orb_high - 1) * 100, 2)

		# 선정 시 갭%
		orb_gap = next((c['gap'] for c in self.orb_candidates if c['stk_cd'] == stk_cd), None)

		meta = self.selected_stocks_meta.get(stk_cd, {})
		kospi_flu, kosdaq_flu = await asyncio.get_event_loop().run_in_executor(
			None, fn_get_market_index, self.token
		)
		snapshot = {
			'entry_price':     current_price,
			'entry_rsi':       round(rsi, 2) if rsi is not None else None,
			'entry_flu_rt':    meta.get('flu_rt', 0),
			'entry_vol_ratio': round(curr_vol / prev_vol, 2) if prev_vol > 0 else None,
			'entry_score':     round(meta.get('score', 0), 4),
			'is_foreign':      meta.get('is_foreign', False),
			'kospi_flu':       kospi_flu,
			'kosdaq_flu':      kosdaq_flu,
			'orb_stop_pct':    orb_stop_pct,
			'orb_gap':         orb_gap,
			'orb_overshoot':   orb_overshoot,
			'strategy':        'ORB',
			'confirm_secs':    3.0,
		}
		# 돌파 유지 확인: 3초 동안 가격·거래량 유지
		if not await self._confirm_breakout(stk_cd, orb_high, 3.0):
			return False

		signal_info = (
			f"📈 [ORB] 개장범위 돌파 확인: {stk_cd}\n"
			f"   현재가: {current_price:.0f} > ORB 고점: {orb_high:.0f} (+{orb_overshoot:.2f}%)\n"
			f"   갭: {orb_gap:.1f}% | RSI: {rsi_str} | 거래량비율: {vol_ratio:.1f}x | 손절: {orb_stop_pct:+.2f}%"
		)
		bought = await self._buy_stock(stk_cd, current_price, signal_info=signal_info, snapshot=snapshot, acnt_cache=acnt_cache)
		if bought:
			self.orb_buy_count += 1
		return bought

	async def _buy_stock(self, stk_cd, current_price, signal_info='', snapshot=None, acnt_cache=None):
		"""종목 매수. 성공 시 True, 실패 시 False 반환"""
		log = get_logger()
		try:
			entry = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt00001, 'N', '', self.token
			)
			if not entry:
				log.warning(f'[매수] {stk_cd} 예수금 조회 실패 - 매수 취소')
				tel_send(f"❌ 매수 취소: {stk_cd} (예수금 조회 실패)")
				return False

			if acnt_cache is not None:
				my_stk, aset_evlt_amt = acnt_cache
			else:
				my_stk, aset_evlt_amt, _ = await asyncio.get_event_loop().run_in_executor(
					None, fn_kt00004, False, 'N', '', self.token
				)
			if my_stk is None:
				# kt00004 실패 시 추정예탁자산(kt00002)으로 대체
				prsm, _ = await asyncio.get_event_loop().run_in_executor(
					None, fn_kt00002, self.token
				)
				if prsm and prsm != '0':
					total_assets = float(str(prsm).replace(',', ''))
					log.warning(f'[매수] {stk_cd} kt00004 실패 — 추정예탁자산 {total_assets:,.0f}원 사용')
				elif self.last_known_assets:
					total_assets = self.last_known_assets
					log.warning(f'[매수] {stk_cd} 계좌 조회 실패 — 캐시 총자산 {total_assets:,.0f}원 사용')
				else:
					log.warning(f'[매수] {stk_cd} 계좌 조회 실패 — 매수 취소 (총자산 불명)')
					tel_send(f"❌ 매수 취소: {stk_cd} (계좌 조회 실패 — 총자산 불명)")
					return False
			else:
				stk_evlt_sum = sum(float(s.get('evlt_amt', '0') or '0') for s in my_stk) if my_stk else 0
				cash_val = float(aset_evlt_amt) if aset_evlt_amt and aset_evlt_amt != '0' else float(entry)
				total_assets = cash_val + stk_evlt_sum
				self.last_known_assets = total_assets

			buy_ratio  = get_setting('buy_ratio', 8.0)
			buy_amount = total_assets * (buy_ratio / 100.0)
			ord_qty    = int(buy_amount / current_price)

			log.info(f'[매수 시도] {stk_cd} | 현재가={current_price:.0f} | 총자산={total_assets:,.0f} | 매수금액={buy_amount:,.0f} | 수량={ord_qty}')

			if ord_qty <= 0:
				log.warning(f'[매수] {stk_cd} 수량 0 - 매수 취소 (총자산={total_assets:,.0f}, 현재가={current_price:.0f})')
				tel_send(f"❌ 매수 취소: {stk_cd} (수량 0 — 총자산 {total_assets:,.0f}원 / 현재가 {int(current_price):,}원)")
				return False

			result = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt10000, stk_cd, str(ord_qty), '', 'N', '', self.token
			)

			if result == 0:
				stk_nm = self.selected_stocks_names.get(stk_cd, stk_cd)
				self.entry_time[stk_cd] = datetime.datetime.now()
				if snapshot:
					self.entry_snapshot[stk_cd] = snapshot
				log.info(f'[매수 완료] {stk_nm}({stk_cd}) {ord_qty}주')
				msg = f"{signal_info}\n🟢 {stk_nm}({stk_cd}) {ord_qty}주 매수 완료\n   가격: {int(current_price):,}원 | 총자산: {int(total_assets):,}원 기준"
				tel_send(msg)
				return True
			else:
				log.error(f'[매수 실패] {stk_cd} API 결과={result}')
				tel_send(f"{signal_info}\n❌ 매수 실패: {stk_cd} (API 결과={result})")
				return False

		except Exception as e:
			log.error(f'[매수 오류] {stk_cd}: {e}', exc_info=True)
			return False
