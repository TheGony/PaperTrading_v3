import asyncio
from api.account import fn_kt00004, fn_kt00002
from util.market_hour import MarketHour
from util.get_setting import get_setting, update_setting
from util.tel_send import tel_send


class BotCommandsMixin:
	async def sel(self):
		"""sel 명령어 - 현재 선정된 종목 조회"""
		try:
			if not self.token:
				token = self.get_token()
				if not token:
					tel_send("❌ 토큰 발급에 실패했습니다")
					return False

			# ── ORB 준비 상태 + Market Regime ─────────────────
			orb_status = "완료 ✅" if self.orb_ready else "대기 중 ⏳"
			vol        = getattr(self, 'market_volatility', 0.0)
			regime     = getattr(self, 'market_regime', 'normal')
			msg = (
				f"👀 [선정 종목] (ORB: {orb_status})\n"
				f"📊 [Market Regime] {regime} | 변동성: {vol:.3f}%\n\n"
			)

			# ── MOMENTUM 종목 ──────────────────────────────────
			if not self.selected_stocks:
				msg += "   아직 MOMENTUM 종목이 선정되지 않았습니다.\n"
			else:
				for stk_cd in self.selected_stocks:
					meta    = self.selected_stocks_meta.get(stk_cd, {})
					nm      = self.selected_stocks_names.get(stk_cd, stk_cd)
					rank    = meta.get('rank', '-')
					score   = meta.get('score', 0)
					rsi     = meta.get('rsi')
					flu_rt  = meta.get('flu_rt', 0)
					foreign = meta.get('is_foreign', False)
					trde    = meta.get('trde_amt')

					try:
						flu_val = float(flu_rt)
						emoji   = '🔴' if flu_val > 0 else ('🔵' if flu_val < 0 else '➡️')
					except Exception:
						emoji = '➡️'

					rsi_str   = f"{rsi:.1f}" if rsi is not None else '-'
					trde_str  = f"{trde / 100:.0f}억" if trde and trde >= 100 else (f"{trde}백만" if trde else '-')
					foreign_s = '○' if foreign else '×'

					msg += (
						f"{emoji} #{rank} [{nm}] ({stk_cd})\n"
						f"   점수: {score:.3f} | RSI: {rsi_str} | 외인수급: {foreign_s}\n"
						f"   등락률: {flu_rt:+.2f}% | 거래대금: {trde_str}\n\n"
					)

				msg += f"📋 MOMENTUM {len(self.selected_stocks)}개"

			# ── ORB 후보 ──────────────────────────────────────
			orb_list = self.orb_candidates or []
			if orb_list:
				msg += f"\n\n📌 [ORB 후보] ({len(orb_list)}종목, 09:01 1차·09:03 2차 확정)\n"
				for c in orb_list:
					trde     = c.get('trde_prica', 0)
					trde_str = f"{trde / 10000:.0f}억" if trde >= 10000 else f"{trde:.0f}백만"
					gap_str  = f"{c['gap']:+.1f}%" if c.get('gap') is not None else 'N/A'
					score_s  = f"{c['score']:.3f}" if c.get('score') is not None else '-'
					msg += (
						f"   {c['stk_nm']}({c['stk_cd']}) "
						f"점수={score_s} | 갭={gap_str} | "
						f"등락={c['flu_rt']:+.1f}% | 거래대금={trde_str}\n"
					)
			else:
				msg += "\n\n📌 [ORB 후보] 없음"

			tel_send(msg)
			return True

		except Exception as e:
			tel_send(f"❌ sel 명령어 실행 중 오류: {e}")
			return False

	async def report(self):
		"""report 명령어 - 보유 종목 수익률 조회"""
		try:
			if not self.token:
				token = self.get_token()
				if not token:
					tel_send("❌ 토큰 발급에 실패했습니다")
					return False

			try:
				account_data, _, _ = await asyncio.wait_for(
					asyncio.get_event_loop().run_in_executor(None, fn_kt00004, False, 'N', '', self.token),
					timeout=10.0
				)
			except asyncio.TimeoutError:
				tel_send("⏰ 서버로부터 응답이 늦어지고 있습니다. 나중에 다시 시도해주세요.")
				return False

			msg = "💰 [보유 종목]\n\n"
			if account_data is None:
				tel_send("❌ 계좌 조회 실패: API 오류 또는 토큰 만료. 로그를 확인해주세요.")
				return False

			if account_data:
				total_profit_loss = 0
				total_pl_amt      = 0
				for stock in account_data:
					stk_cd           = stock.get('stk_cd', 'N/A').replace('A', '')
					stk_nm           = stock.get('stk_nm', 'N/A')
					profit_loss_rate = float(stock.get('pl_rt', 0))
					pl_amt           = int(stock.get('pl_amt', 0))
					remaining_qty    = int(stock.get('rmnd_qty', 0))
					snap             = self.entry_snapshot.get(stk_cd, {})
					strategy         = snap.get('strategy', '-')
					peak             = self.peak_profit.get(stk_cd)
					entry_time       = self.entry_time.get(stk_cd)

					emoji = '🔴' if profit_loss_rate > 0 else ('🔵' if profit_loss_rate < 0 else '➡️')
					peak_str  = f"{peak:+.2f}%" if peak is not None else '-'
					entry_str = entry_time.strftime('%H:%M:%S') if entry_time else '-'

					msg += f"{emoji} [{stk_nm}] ({stk_cd}) [{strategy}]\n"
					msg += f"   수익률: {profit_loss_rate:+.2f}%  MFE: {peak_str}\n"
					msg += f"   평가손익: {pl_amt:,.0f}원 | 보유: {remaining_qty:,}주\n"
					msg += f"   진입: {entry_str}\n\n"
					total_profit_loss += profit_loss_rate
					total_pl_amt      += pl_amt

				avg = total_profit_loss / len(account_data)
				msg += f"📋 총 {len(account_data)}종목 | 평균 {avg:+.2f}% | 총손익 {total_pl_amt:+,}원"
			else:
				msg += "   보유 종목이 없습니다."

			tel_send(msg)
			return True

		except Exception as e:
			tel_send(f"❌ report 명령어 실행 중 오류: {e}")
			return False

	async def bal(self):
		"""bal 명령어 - 현재 계좌 자산 현황 조회"""
		try:
			if not self.token:
				token = self.get_token()
				if not token:
					tel_send("❌ 토큰 발급에 실패했습니다")
					return False

			(my_stocks, aset_evlt_amt, _), (prsm, _) = await asyncio.gather(
				asyncio.get_event_loop().run_in_executor(None, fn_kt00004, False, 'N', '', self.token),
				asyncio.get_event_loop().run_in_executor(None, fn_kt00002, self.token),
			)

			if my_stocks is None:
				tel_send("❌ 계좌 조회 실패: API 오류 또는 토큰 만료. 로그를 확인해주세요.")
				return False

			stk_evlt_sum = sum(self._safe_int(s.get('evlt_amt', '0')) for s in my_stocks) if my_stocks else 0
			cash_val     = self._safe_int(aset_evlt_amt)

			prsm_int = self._safe_int(prsm)
			if prsm_int > 0:
				total_assets = prsm_int
				asset_label  = "추정예탁자산"
			else:
				total_assets = cash_val + stk_evlt_sum
				asset_label  = "추정예탁자산(계산)"

			msg  = "💼 [계좌 자산 현황]\n\n"
			msg += f"   {asset_label}: {total_assets:,}원\n"
			msg += f"   현금(예탁자산평가액): {cash_val:,}원\n"
			msg += f"   주식평가금액:   {stk_evlt_sum:,}원\n"
			if my_stocks:
				msg += f"\n   보유 종목 ({len(my_stocks)}개)\n"
				for s in my_stocks:
					nm    = s.get('stk_nm', s.get('stk_cd', 'N/A'))
					pl_rt = self._safe_float(s.get('pl_rt', '0'))
					evlt  = self._safe_int(s.get('evlt_amt', '0'))
					emoji = '🔴' if pl_rt > 0 else ('🔵' if pl_rt < 0 else '➡️')
					msg += f"   {emoji} {nm}: {evlt:,}원 ({pl_rt:+.2f}%)\n"
			tel_send(msg)
			return True

		except Exception as e:
			tel_send(f"❌ bal 명령어 실행 중 오류: {e}")
			return False

	async def top(self, number):
		"""top 명령어 - stock_count 수정"""
		try:
			count = int(number)
			if count <= 0:
				tel_send("❌ 종목 개수는 1 이상이어야 합니다")
				return False
			if count > 20:
				tel_send("❌ 종목 개수는 20 이하여야 합니다")
				return False

			was_running = self.is_running
			if was_running:
				tel_send("🔄 종목 개수 변경을 위해 프로세스를 재시작합니다...")
				await self.stop(set_auto_start_false=False)
				await asyncio.sleep(1)

			if update_setting('stock_count', count):
				tel_send(f"✅ 종목 선정 개수가 {count}개로 설정되었습니다")
				if was_running and MarketHour.is_market_open_time():
					await asyncio.sleep(1)
					await self.start()
				return True
			else:
				tel_send("❌ 종목 선정 개수 설정에 실패했습니다")
				return False

		except ValueError:
			tel_send("❌ 잘못된 숫자 형식입니다. 예: top 10")
			return False
		except Exception as e:
			tel_send(f"❌ top 명령어 실행 중 오류: {e}")
			return False

	async def brt(self, number):
		"""brt 명령어 - buy_ratio 수정"""
		try:
			ratio = float(number)
			if ratio <= 0 or ratio > 100:
				tel_send("❌ 매수 비율은 0 초과 100 이하여야 합니다")
				return False
			if update_setting('buy_ratio', ratio):
				tel_send(f"✅ 1회 매수 비율이 총자산의 {ratio}%로 설정되었습니다")
				return True
			else:
				tel_send("❌ 매수 비율 설정에 실패했습니다")
				return False
		except ValueError:
			tel_send("❌ 잘못된 숫자 형식입니다. 예: brt 10")
			return False
		except Exception as e:
			tel_send(f"❌ brt 명령어 실행 중 오류: {e}")
			return False

	async def chart(self, x, y):
		"""chart 명령어 - MA 단기/장기 설정"""
		try:
			chart_short = int(x)
			chart_long  = int(y)

			if chart_short <= 0 or chart_long <= 0:
				tel_send("❌ 차트 값은 1 이상이어야 합니다")
				return False
			if chart_long <= chart_short:
				tel_send(f"❌ 장기 MA({chart_long})는 단기 MA({chart_short})보다 커야 합니다")
				return False

			was_running = self.is_running
			if was_running:
				tel_send("🔄 차트 설정 변경을 위해 프로세스를 재시작합니다...")
				await self.stop(set_auto_start_false=False)
				await asyncio.sleep(1)

			if update_setting('chart_short', chart_short) and update_setting('chart_long', chart_long):
				tel_send(
					f"✅ MA 설정이 변경되었습니다\n"
					f"   단기: MA{chart_short} | 장기: MA{chart_long}\n"
					f"   청산 조건: MA{chart_short} < MA{chart_long} AND RSI < 45"
				)
				if was_running and MarketHour.is_market_open_time():
					await asyncio.sleep(1)
					await self.start()
				return True
			else:
				tel_send("❌ 차트 설정 변경에 실패했습니다")
				return False

		except ValueError:
			tel_send("❌ 잘못된 숫자 형식입니다. 예: chart 5 20")
			return False
		except Exception as e:
			tel_send(f"❌ chart 명령어 실행 중 오류: {e}")
			return False

	async def help(self):
		"""help 명령어 - 명령어 설명 및 사용법 가이드"""
		try:
			chart_short = get_setting('chart_short', 5)
			chart_long  = get_setting('chart_long', 20)
			brt         = get_setting('buy_ratio', 8.0)
			top_n       = get_setting('stock_count', 10)

			msg_cmd = f"""🤖 PaperTrading v3

[명령어]
start        매매 시작
stop         매매 중지 (포지션 유지)
r            보유 종목 수익률 조회
s            선정 종목·ORB 후보 조회
b            계좌 자산 현황
help         이 도움말

[설정]
top {{n}}      MOMENTUM 종목 수  (현재: {top_n}개)
brt {{n}}      1회 매수 비율(%)  (현재: {brt}%)
chart {{x}} {{y}} 데드크로스 MA    (현재: MA{chart_short}/MA{chart_long})

[전략 요약]
ORB      09:05~09:30 / 갭상승 돌파 / 손절 max(ORB저점,-2%) / 트레일링 1.0~1.8%
MOM      09:03~15:20 / 5봉 고점 돌파 / 손절 -3% / 트레일링 2.0~3.2%
공통     조기손절 2분이내 -1.2% / 쿨다운 20분 / 당일 2회 손절 종목 제외"""

			tel_send(msg_cmd)
			return True

		except Exception as e:
			tel_send(f"❌ help 명령어 실행 중 오류: {e}")
			return False

	async def process_command(self, text):
		"""텍스트 명령어를 처리합니다."""
		command = text.strip().lower()

		if command == 'start':
			return await self.start()
		elif command == 'stop':
			return await self.stop(True)
		elif command in ('report', 'r'):
			return await self.report()
		elif command in ('sel', 's'):
			return await self.sel()
		elif command in ('bal', 'b'):
			return await self.bal()
		elif command == 'help':
			return await self.help()
		elif command.startswith('top '):
			parts = command.split()
			if len(parts) == 2:
				return await self.top(parts[1])
			tel_send("❌ 사용법: top {숫자}  예) top 10")
			return False
		elif command.startswith('brt '):
			parts = command.split()
			if len(parts) == 2:
				return await self.brt(parts[1])
			tel_send("❌ 사용법: brt {숫자}  예) brt 10")
			return False
		elif command.startswith('chart '):
			parts = command.split()
			if len(parts) == 3:
				return await self.chart(parts[1], parts[2])
			tel_send("❌ 사용법: chart {x} {y}  예) chart 5 20")
			return False
		elif command.startswith('slr') or command.startswith('tsg'):
			tel_send(
				"⚠️ slr/tsg 는 더 이상 지원하지 않습니다.\n"
				"손절·트레일링은 전략별 연속 함수(continuous function)로 고정 운용됩니다.\n"
				"   ORB:      손절 -2.0% / trailing = clamp(1.0 + peak×0.12, 1.0, 1.8)\n"
				"   MOMENTUM: 손절 -3.0% / trailing = clamp(2.0 + log(1+peak)×0.6 + vol×0.5, 2.0, 3.2)"
			)
			return False
		else:
			tel_send(f"❓ 알 수 없는 명령어입니다: {text}\n'help' 를 입력하면 명령어 목록을 확인할 수 있습니다.")
			return False
