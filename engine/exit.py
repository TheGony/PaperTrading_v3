import asyncio
import datetime
from api.account import fn_kt00004
from api.order import fn_kt10001
from engine.regime import orb_trailing, momentum_trailing
from util.market_hour import MarketHour
from util.tel_send import tel_send
from util.logger import get_logger

# ── 매매 비용 상수 ────────────────────────────────────────────────────────────
FEE_TAX       = 0.23   # 증권사 수수료 + 유관기관 + 거래세 합계 (%)
EST_SLIPPAGE  = 0.10   # 시장가 매도 슬리피지 예상치 (%)
SAFETY_MARGIN = FEE_TAX + EST_SLIPPAGE  # 0.33% — pl_rt에서 차감하여 net_pl_rt 산출


class ExitMixin:
	async def _sell_stock(self, stk_cd, reason='데드크로스', signal_info=''):
		"""종목 매도"""
		log = get_logger()
		try:
			my_stocks, _, _ = await asyncio.get_event_loop().run_in_executor(
				None, fn_kt00004, False, 'N', '', self.token
			)

			if my_stocks is None:
				log.error(f'[매도] {stk_cd} 계좌 조회 API 오류 - 매도 취소 (reason={reason})')
				tel_send(f"❌ 매도 취소: {stk_cd} (계좌 조회 API 오류)")
				return
			if not my_stocks:
				log.warning(f'[매도] {stk_cd} 보유 종목 조회 결과 없음 - 매도 취소 (reason={reason})')
				return

			for stock in my_stocks:
				if stock['stk_cd'].replace('A', '') == stk_cd:
					ord_qty          = int(stock['rmnd_qty'])
					profit_loss_rate = float(stock.get('pl_rt', 0))
					net_pl_rt        = round(profit_loss_rate - SAFETY_MARGIN, 2)

					result = await asyncio.get_event_loop().run_in_executor(
						None, fn_kt10001, stk_cd, str(ord_qty), 'N', '', self.token
					)

					log.info(f'[매도 시도] {stk_cd} | 수량={ord_qty} | 수익률={profit_loss_rate:+.2f}% | 실질={net_pl_rt:+.2f}% | reason={reason}')
					if result == 0:
						emoji    = '🔴' if profit_loss_rate > 0 else ('🔵' if profit_loss_rate < 0 else '➡️')
						mfe      = self.peak_profit.pop(stk_cd, None)
						mae      = self.min_profit.pop(stk_cd, None)
						entry_dt = self.entry_time.pop(stk_cd, None)
						snap     = self.entry_snapshot.pop(stk_cd, None)
						held_min = round((datetime.datetime.now() - entry_dt).total_seconds() / 60, 1) if entry_dt else None
						if snap is not None:
							snap['held_minutes'] = held_min
						log.info(f'[매도 완료] {stk_cd} | 수익률={profit_loss_rate:+.2f}% | 실질={net_pl_rt:+.2f}% | MFE={mfe} | MAE={mae} | 보유={held_min}분')
						completion = f"{emoji} {stock['stk_nm']} ({stk_cd}) {ord_qty}주 매도 완료\n   수익률: {profit_loss_rate:+.2f}% (실질 {net_pl_rt:+.2f}%) | {reason}"
						tel_send(f"{signal_info}\n{completion}" if signal_info else completion)
						self._log_trade(stock['stk_nm'], stk_cd, profit_loss_rate, reason, mfe=mfe, mae=mae, snapshot=snap, net_pl_rt=net_pl_rt)
						self.sell_cooldown[stk_cd] = datetime.datetime.now()
					else:
						log.error(f'[매도 실패] {stk_cd} API 결과={result}')
						tel_send(f"❌ 매도 실패: {stk_cd} (API 결과={result})")
					break

		except Exception as e:
			log.error(f'[매도 오류] {stk_cd}: {e}', exc_info=True)
			tel_send(f"❌ {stk_cd} 매도 중 오류: {e}")

	async def _profit_check_loop(self):
		"""수익율을 매 초 확인하고 익절/손절하는 백그라운드 루프"""
		log = get_logger()
		try:
			while self.is_running:
				if MarketHour.is_market_open_time():
					my_stocks, _, _ = await asyncio.get_event_loop().run_in_executor(
						None, fn_kt00004, False, 'N', '', self.token
					)

					if my_stocks:
						held_codes = set()

						for stock in my_stocks:
							stk_cd    = stock['stk_cd'].replace('A', '')
							ord_qty   = int(stock['rmnd_qty'])
							pl_rt     = float(stock.get('pl_rt', 0))
							net_pl_rt = round(pl_rt - SAFETY_MARGIN, 2)
							held_codes.add(stk_cd)

							# ── MFE / MAE 갱신 (net 기준) ───────────────────────
							if net_pl_rt > self.peak_profit.get(stk_cd, net_pl_rt):
								self.peak_profit[stk_cd] = net_pl_rt
							else:
								self.peak_profit.setdefault(stk_cd, net_pl_rt)
							if net_pl_rt < self.min_profit.get(stk_cd, net_pl_rt):
								self.min_profit[stk_cd] = net_pl_rt
							else:
								self.min_profit.setdefault(stk_cd, net_pl_rt)

							net_peak = self.peak_profit[stk_cd]
							snap     = self.entry_snapshot.get(stk_cd, {})
							strategy = snap.get('strategy', 'MOMENTUM')

							if strategy == 'ORB':
								stop_loss = -2.0
								trail_gap = orb_trailing(net_peak)
							else:
								stop_loss = -3.0
								trail_gap = momentum_trailing(net_peak, self.market_volatility)

							# ── 청산 우선순위 평가 (net_pl_rt 기준) ─────────────
							should_sell = False
							sell_reason = ''
							hard_sell   = False

							# 1순위: 조기손절 (net -1.2% / 2분 이내) — hard stop
							entry_dt = self.entry_time.get(stk_cd)
							if entry_dt:
								elapsed_min = (datetime.datetime.now() - entry_dt).total_seconds() / 60
								if elapsed_min <= 2.0 and net_pl_rt < -1.2:
									should_sell = True
									hard_sell   = True
									sell_reason = f'조기 손절 (진입 후 {elapsed_min:.1f}분, 실질 {net_pl_rt:+.2f}%)'

							# 2순위: ORB 저점 손절 — hard stop
							orb_stop_pct = snap.get('orb_stop_pct')
							if not should_sell and orb_stop_pct is not None and net_pl_rt <= orb_stop_pct:
								should_sell = True
								hard_sell   = True
								sell_reason = f'ORB 손절 (실질 {net_pl_rt:+.2f}% ≤ {orb_stop_pct:+.2f}%)'

							# 3순위: 트레일링 스탑 — 휩쏘 방지 적용
							# 트레일링 스탑 — 전략별 하한선으로 손실 제한
							# ORB: 0.05% (실질 본절 사수), MOMENTUM: -0.5% (소폭 손실까지 허용)
							if not should_sell and net_peak >= 1.5:
								floor         = 0.05 if strategy == 'ORB' else -0.5
								actual_trigger = max(net_peak - trail_gap, floor)
								if net_pl_rt <= actual_trigger:
									should_sell = True
									floor_note  = ' [하한보존]' if actual_trigger == floor else ''
									sell_reason = (
										f'트레일링 스탑{floor_note} [{strategy}] '
										f'(고점: {net_peak:+.2f}% → 실질: {net_pl_rt:+.2f}%, 트리거: {actual_trigger:+.2f}%)'
									)

							# 4순위: 고정 손절 (최후 안전망) — hard stop
							if not should_sell and net_pl_rt <= stop_loss:
								should_sell = True
								hard_sell   = True
								sell_reason = f'고정 손절 [{strategy}] (실질 {net_pl_rt:+.2f}% ≤ {stop_loss:+.2f}%)'

							# ── 휩쏘 방지 — 연속 2회 확인 후 매도 ───────────────
							if should_sell:
								if hard_sell:
									self._sell_signal_count.pop(stk_cd, None)
									do_sell = True
								else:
									cnt = self._sell_signal_count.get(stk_cd, 0) + 1
									self._sell_signal_count[stk_cd] = cnt
									do_sell = cnt >= 2
									if not do_sell:
										log.info(f'[휩쏘 방지] {stk_cd} 1차 신호 — {sell_reason}')
							else:
								self._sell_signal_count.pop(stk_cd, None)
								do_sell = False

							if not do_sell:
								continue

							# ── 매도 실행 ────────────────────────────────────────
							result = await asyncio.get_event_loop().run_in_executor(
								None, fn_kt10001, stk_cd, str(ord_qty), 'N', '', self.token
							)
							if result == 0:
								mfe          = self.peak_profit.get(stk_cd)
								mae          = self.min_profit.get(stk_cd)
								entry_dt_log = self.entry_time.get(stk_cd)
								snap_log     = self.entry_snapshot.pop(stk_cd, None)
								held_min     = (
									round((datetime.datetime.now() - entry_dt_log).total_seconds() / 60, 1)
									if entry_dt_log else None
								)
								if snap_log is not None:
									snap_log['held_minutes'] = held_min
								emoji = '💰' if pl_rt > 0 else '🔵'
								tel_send(f"{emoji} {stock['stk_nm']} ({stk_cd}) {ord_qty}주 매도 ({sell_reason})\n   수익률: {pl_rt:+.2f}% | 실질: {net_pl_rt:+.2f}%")
								self._log_trade(stock['stk_nm'], stk_cd, pl_rt, sell_reason, mfe=mfe, mae=mae, snapshot=snap_log, net_pl_rt=net_pl_rt)
								self.peak_profit.pop(stk_cd, None)
								self.min_profit.pop(stk_cd, None)
								self.entry_time.pop(stk_cd, None)
								self._sell_signal_count.pop(stk_cd, None)
								self.sell_cooldown[stk_cd] = datetime.datetime.now()
							else:
								log.error(f'[매도 실패] {stk_cd} result={result} — 상태 유지, 다음 루프 재시도')
								tel_send(f"⚠️ {stock['stk_nm']} ({stk_cd}) 매도 실패 (result={result}) — 재시도 중")

						# ghost position cleanup
						for cd in list(self.peak_profit.keys()):
							if cd not in held_codes:
								self.peak_profit.pop(cd, None)
								self.min_profit.pop(cd, None)
						for cd in list(self._sell_signal_count.keys()):
							if cd not in held_codes:
								self._sell_signal_count.pop(cd, None)

				await asyncio.sleep(1)

		except asyncio.CancelledError:
			print("수익율 체크 루프가 중지되었습니다")
		except Exception as e:
			log.error(f'[수익율 체크 루프 오류] {e}', exc_info=True)
			tel_send(f"❌ 수익율 체크 루프 오류: {e}")
