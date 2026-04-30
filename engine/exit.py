import asyncio
import datetime
from api.account import fn_kt00004
from api.order import fn_kt10001
from util.market_hour import MarketHour
from util.get_setting import get_setting
from util.tel_send import tel_send
from util.logger import get_logger


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

					# 매도 주문
					result = await asyncio.get_event_loop().run_in_executor(
						None, fn_kt10001, stk_cd, str(ord_qty), 'N', '', self.token
					)

					log.info(f'[매도 시도] {stk_cd} | 수량={ord_qty} | 수익률={profit_loss_rate:+.2f}% | reason={reason}')
					if result == 0:
						emoji = "🔴" if profit_loss_rate > 0 else ("🔵" if profit_loss_rate < 0 else "➡️")
						mfe      = self.peak_profit.pop(stk_cd, None)
						mae      = self.min_profit.pop(stk_cd, None)
						entry_dt = self.entry_time.pop(stk_cd, None)
						snap     = self.entry_snapshot.pop(stk_cd, None)
						held_min = round((datetime.datetime.now() - entry_dt).total_seconds() / 60, 1) if entry_dt else None
						if snap is not None:
							snap['held_minutes'] = held_min
						log.info(f'[매도 완료] {stk_cd} | 수익률={profit_loss_rate:+.2f}% | MFE={mfe} | MAE={mae} | 보유={held_min}분')
						completion = f"{emoji} {stock['stk_nm']} ({stk_cd}) {ord_qty}주 매도 완료\n   수익률: {profit_loss_rate:+.2f}% | {reason}"
						tel_send(f"{signal_info}\n{completion}" if signal_info else completion)
						self._log_trade(stock['stk_nm'], stk_cd, profit_loss_rate, reason, mfe=mfe, mae=mae, snapshot=snap)
					else:
						log.error(f'[매도 실패] {stk_cd} API 결과={result}')
						tel_send(f"❌ 매도 실패: {stk_cd} (API 결과={result})")
					self.sell_cooldown[stk_cd] = datetime.datetime.now()
					break

		except Exception as e:
			log.error(f'[매도 오류] {stk_cd}: {e}', exc_info=True)
			tel_send(f"❌ {stk_cd} 매도 중 오류: {e}\n5초 후 다시 시도합니다.")
			await asyncio.sleep(5)
			await self._sell_stock(stk_cd, reason, signal_info=signal_info)

	async def _profit_check_loop(self):
		"""수익율을 매 초 확인하고 익절/손절하는 백그라운드 루프"""
		try:
			while self.is_running:
				if MarketHour.is_market_open_time():
					# 보유 종목 수익율 확인
					my_stocks, _, _ = await asyncio.get_event_loop().run_in_executor(
						None, fn_kt00004, False, 'N', '', self.token
					)

					if my_stocks:
						stop_loss_ratio = get_setting('stop_loss_rate', -3.0)
						trailing_gap    = get_setting('trailing_stop_gap', 3.0)

						# ── Phase별 손절/트레일링 조정 ───────────────────
						phase = MarketHour.get_market_phase()
						if phase == 'early':
							effective_stop  = -2.0
							effective_trail = 2.0
						elif phase == 'late':
							effective_stop  = stop_loss_ratio
							effective_trail = 2.5
						else:
							effective_stop  = stop_loss_ratio
							effective_trail = trailing_gap

						held_codes = set()

						for stock in my_stocks:
							stk_cd  = stock['stk_cd'].replace('A', '')
							ord_qty = int(stock['rmnd_qty'])
							pl_rt   = float(stock.get('pl_rt', 0))
							held_codes.add(stk_cd)

							# MFE(최고 수익률) / MAE(최저 수익률) 갱신
							if pl_rt > self.peak_profit.get(stk_cd, pl_rt):
								self.peak_profit[stk_cd] = pl_rt
							else:
								self.peak_profit.setdefault(stk_cd, pl_rt)

							if pl_rt < self.min_profit.get(stk_cd, pl_rt):
								self.min_profit[stk_cd] = pl_rt
							else:
								self.min_profit.setdefault(stk_cd, pl_rt)

							peak = self.peak_profit[stk_cd]
							snap = self.entry_snapshot.get(stk_cd, {})

							# ORB 전용 트레일링 (4단계)
							if snap.get('strategy') == 'ORB':
								if peak < 2.0:
									dynamic_trail = 1.2
								elif peak < 4.0:
									dynamic_trail = 1.5
								elif peak < 7.0:
									dynamic_trail = 2.0
								else:
									dynamic_trail = 2.5
							# 4단계 동적 trailing gap (모멘텀)
							elif peak >= 7.0:
								dynamic_trail = 1.5
							elif peak >= 4.0:
								dynamic_trail = 2.0
							elif peak >= 2.0:
								dynamic_trail = 2.5
							else:
								dynamic_trail = effective_trail  # phase 기본값 (초반 2 / 중반 trailing_stop_gap / 후반 2.5)
							trail_trigger = peak - dynamic_trail

							should_sell = False
							sell_reason = ''

							# 조기 손절: 진입 후 2분 이내 -1.2% 이하
							entry_dt = self.entry_time.get(stk_cd)
							if entry_dt:
								elapsed_min = (datetime.datetime.now() - entry_dt).total_seconds() / 60
								if elapsed_min <= 2 and pl_rt < -1.2:
									should_sell = True
									sell_reason = f'조기 손절 (진입 후 {elapsed_min:.1f}분, {pl_rt:+.2f}%)'

							# ORB 손절: max(저점, -2%) 기준 이탈
							orb_stop_pct = snap.get('orb_stop_pct')
							if not should_sell and orb_stop_pct is not None and pl_rt <= orb_stop_pct:
								should_sell = True
								sell_reason = f'ORB 손절 ({pl_rt:+.2f}% ≤ {orb_stop_pct:+.2f}%)'

							# ORB 수익 반납 방지: peak ≥ 1.5% 도달 후 수익률이 0% 아래로 내려오면 즉시 매도
							if not should_sell and snap.get('strategy') == 'ORB' and peak >= 1.5 and pl_rt < 0:
								should_sell = True
								sell_reason = f'ORB 수익 반납 방지 (고점: {peak:+.2f}% → 현재: {pl_rt:+.2f}%)'

							# 고정 손절
							if not should_sell and pl_rt <= effective_stop:
								should_sell = True
								sell_reason = f'손절 (수익률: {pl_rt:+.2f}%)'

							# 트레일링 스탑 (수익 구간에서만)
							elif peak > 0 and pl_rt <= trail_trigger:
								should_sell = True
								sell_reason = f'트레일링 스탑 (고점: {peak:+.2f}% → 현재: {pl_rt:+.2f}%)'

							if should_sell:
								result = await asyncio.get_event_loop().run_in_executor(
									None, fn_kt10001, stk_cd, str(ord_qty), 'N', '', self.token
								)
								if result == 0:
									mfe      = self.peak_profit.get(stk_cd)
									mae      = self.min_profit.get(stk_cd)
									entry_dt = self.entry_time.get(stk_cd)
									snap     = self.entry_snapshot.pop(stk_cd, None)
									held_min = round((datetime.datetime.now() - entry_dt).total_seconds() / 60, 1) if entry_dt else None
									if snap is not None:
										snap['held_minutes'] = held_min
									emoji = '💰' if pl_rt > 0 else '🔵'
									tel_send(f"{emoji} {stock['stk_nm']} ({stk_cd}) {ord_qty}주 매도 ({sell_reason})")
									self._log_trade(stock['stk_nm'], stk_cd, pl_rt, sell_reason, mfe=mfe, mae=mae, snapshot=snap)
									self.peak_profit.pop(stk_cd, None)
									self.min_profit.pop(stk_cd, None)
									self.entry_time.pop(stk_cd, None)
									self.sell_cooldown[stk_cd] = datetime.datetime.now()
								else:
									get_logger().error(f'[매도 실패] {stk_cd} result={result} — 다음 주기 재시도')
									tel_send(f"⚠️ {stock['stk_nm']} ({stk_cd}) 매도 실패 (result={result}) — 재시도 중")

						# 매도된 종목 peak_profit / min_profit 정리
						for cd in list(self.peak_profit.keys()):
							if cd not in held_codes:
								self.peak_profit.pop(cd, None)
								self.min_profit.pop(cd, None)

				await asyncio.sleep(1)  # 1초마다 체크

		except asyncio.CancelledError:
			print("수익율 체크 루프가 중지되었습니다")
		except Exception as e:
			get_logger().error(f'[수익율 체크 루프 오류] {e}', exc_info=True)
			tel_send(f"❌ 수익율 체크 루프 오류: {e}")
