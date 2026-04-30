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

			phase = MarketHour.get_market_phase()
			msg   = f"👀 [MOMENTUM 선정 종목]\n\n"

			if not self.selected_stocks:
				msg += "   아직 종목이 선정되지 않았습니다.\n"
				tel_send(msg)
				return True

			for stk_cd in self.selected_stocks:
				nm   = self.selected_stocks_names.get(stk_cd, stk_cd)
				meta = self.selected_stocks_meta.get(stk_cd, {})
				
				flu_rt    = meta.get('flu_rt', 0)
				score     = meta.get('score', 0)
				is_foreign = meta.get('is_foreign', False)
				trde_amt  = meta.get('trde_amt', None)
				trde_amt_rank = meta.get('trde_amt_rank', None)
				
				try:
					emoji = "🔴" if flu_rt > 0 else ("🔵" if flu_rt < 0 else "➡️")
				except:
					emoji = "➡️"
				
				foreign_tag = "🌏" if is_foreign else "📍"
				trde_info = f"{trde_amt:.0f}백만 (순위{trde_amt_rank})" if trde_amt and trde_amt_rank else "N/A"
				
				msg += f"{emoji} [{nm}] ({stk_cd}) {foreign_tag}\n"
				msg += f"   등락률: {flu_rt:+.2f}% | 점수: {score:.3f} | 거래대금: {trde_info}\n\n"

			msg += f"📋 총 {len(self.selected_stocks)}개 선정\n"

			# ── ORB 후보 ──────────────────────────────
			orb_list = getattr(self, 'orb_candidates', [])
			if orb_list:
				msg += f"\n📌 [ORB 후보] ({len(orb_list)}종목)\n"
				for c in orb_list:
					trde     = c.get('trde_prica', 0)
					trde_str = f"{trde/10000:.0f}억" if trde >= 10000 else f"{trde:.0f}백만"
					gap_str  = f"{c['gap']:+.1f}%" if c.get('gap') is not None else "N/A"
					score_str = f"{c['score']:.3f}" if c.get('score') is not None else "N/A"
					msg += (
						f"   {c['stk_nm']}({c['stk_cd']}) "
						f"갭={gap_str} | 등락={c['flu_rt']:+.1f}% | "
						f"점수={score_str} | 거래대금={trde_str}\n"
					)
			else:
				msg += f"\n📌 [ORB 후보] 없음 (미선정)"

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
					stock_code       = stock.get('stk_cd', 'N/A').replace('A', '')
					stock_name       = stock.get('stk_nm', 'N/A')
					profit_loss_rate = float(stock.get('pl_rt', 0))
					pl_amt           = int(stock.get('pl_amt', 0))
					remaining_qty    = int(stock.get('rmnd_qty', 0))
					emoji = "🔴" if profit_loss_rate > 0 else ("🔵" if profit_loss_rate < 0 else "➡️")
					msg += f"{emoji} [{stock_name}] ({stock_code})\n"
					msg += f"   수익률: {profit_loss_rate:+.2f}%\n"
					msg += f"   평가손익: {pl_amt:,.0f}원\n"
					msg += f"   보유수량: {remaining_qty:,}주\n\n"
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
		"""top 명령어를 처리합니다 - stock_count 수정"""
		try:
			count = int(number)
			if count <= 0:
				tel_send("❌ 종목 개수는 1 이상이어야 합니다")
				return False
			if count > 20:
				tel_send("❌ 종목 개수는 20 이하여야 합니다")
				return False

			# 실행 중이면 stop 후 start
			was_running = self.is_running
			if was_running:
				tel_send("🔄 종목 개수 변경을 위해 프로세스를 재시작합니다...")
				await self.stop(set_auto_start_false=False)  # auto_start는 유지
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

	async def slr(self, number):
		"""slr 명령어를 처리합니다 - stop_loss_rate 수정"""
		try:
			rate = float(number)
			if rate > 0:
				rate = -rate
			if update_setting('stop_loss_rate', rate):
				tel_send(f"✅ 손절 기준이 {rate}%로 설정되었습니다")
				return True
			else:
				tel_send("❌ 손절 기준 설정에 실패했습니다")
				return False
		except ValueError:
			tel_send("❌ 잘못된 숫자 형식입니다. 예: slr 3")
			return False
		except Exception as e:
			tel_send(f"❌ slr 명령어 실행 중 오류: {e}")
			return False

	async def tsg(self, number):
		"""tsg 명령어를 처리합니다 - trailing_stop_gap 수정"""
		try:
			gap = float(number)
			if gap <= 0:
				tel_send("❌ 트레일링 스탑 간격은 양수로 입력해주세요. 예: tsg 3")
				return False
			if update_setting('trailing_stop_gap', gap):
				tel_send(f"✅ 트레일링 스탑 간격이 {gap}%로 설정되었습니다\n   (고점 대비 {gap}% 하락 시 매도)")
				return True
			else:
				tel_send("❌ 트레일링 스탑 간격 설정에 실패했습니다")
				return False
		except ValueError:
			tel_send("❌ 잘못된 숫자 형식입니다. 예: tsg 3")
			return False
		except Exception as e:
			tel_send(f"❌ tsg 명령어 실행 중 오류: {e}")
			return False

	async def brt(self, number):
		"""brt 명령어를 처리합니다 - buy_ratio 수정"""
		try:
			ratio = float(number)
			if update_setting('buy_ratio', ratio):
				tel_send(f"✅ 매수 비용 비율이 {ratio}%로 설정되었습니다")
				return True
			else:
				tel_send("❌ 매수 비용 비율 설정에 실패했습니다")
				return False
		except ValueError:
			tel_send("❌ 잘못된 숫자 형식입니다. 예: brt 10")
			return False
		except Exception as e:
			tel_send(f"❌ brt 명령어 실행 중 오류: {e}")
			return False

	async def chart(self, x, y):
		"""chart 명령어를 처리합니다 - 차트 설정 수정 (x분봉, y분봉, y분마다 체크)"""
		try:
			chart_short = int(x)
			chart_long  = int(y)

			if chart_short <= 0 or chart_long <= 0:
				tel_send("❌ 차트 값은 1 이상이어야 합니다")
				return False
			if chart_long <= chart_short:
				tel_send(f"❌ 장기 MA({chart_long})는 단기 MA({chart_short})보다 커야 합니다")
				return False

			# 실행 중이면 stop 후 start
			was_running = self.is_running
			if was_running:
				tel_send("🔄 차트 설정 변경을 위해 프로세스를 재시작합니다...")
				await self.stop(set_auto_start_false=False)
				await asyncio.sleep(1)

			if update_setting('chart_short', chart_short) and update_setting('chart_long', chart_long):
				tel_send(
					f"✅ MA 설정이 변경되었습니다\n"
					f"   단기 이동평균: MA{chart_short} (1분봉 {chart_short}개 평균)\n"
					f"   장기 이동평균: MA{chart_long} (1분봉 {chart_long}개 평균)\n"
					f"   체크 주기: 1분마다"
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
		"""help 명령어를 처리합니다 - 명령어 설명 및 사용법 가이드"""
		try:
			chart_short = get_setting('chart_short', 5)
			chart_long  = get_setting('chart_long', 20)
			slr         = get_setting('stop_loss_rate', -3.0)
			tsg         = get_setting('trailing_stop_gap', 3.0)
			brt         = get_setting('buy_ratio', 8.0)
			top_n       = get_setting('stock_count', 10)
			help_message = f"""🤖 [PaperTrading v2 명령어 가이드]

[기본 명령어]
• start   - 매매 시작 (장 외 시간이면 다음 장 시작 시 자동 실행)
• stop    - 매매 중지 (보유 포지션은 유지)
• sel (s) - 현재 선정 종목 조회 (MOMENTUM + ORB 후보)
• report (r) - 보유 종목 수익률 조회
• bal (b) - 계좌 자산 현황 (예탁자산·예수금·주식평가액)
• help    - 이 도움말 표시

[설정 명령어] (현재값)
• top {{n}}      - 선정 종목 수 설정 (현재: {top_n}개)          예) top 5
• slr {{n}}      - 고정 손절 기준 설정 (현재: {slr}%)           예) slr 3 → -3%
• tsg {{n}}      - 트레일링 스탑 gap (현재: {tsg}%)            예) tsg 3.5
• brt {{n}}      - 1회 매수 비율 설정 (현재: {brt}%)           예) brt 10
• chart {{x}} {{y}} - MA 설정 (현재: MA{chart_short}/MA{chart_long})  예) chart 5 20

[종목 선정 방식]

■ ORB 전략 풀 (09:01 1차 + 09:03 2차 갱신 후 고정)
  API: ka10032(거래대금 상위 30) + ka10030(거래량 상위 30) 병합
  필터: 갭상승(시가>전일종가) / 갭 ≤ 0% 제외 / 현재가 < 시가×0.98 제외
  소프트 패널티: 갭 1.5~8% 이탈 / 윗꼬리 > 5% / 음봉 2개 이상
  스코어: 거래대금*0.25 + 거래량*0.30 + 예상체결*0.25 + 등락률*0.10 - 패널티
  상위 15종목 선정 / 미만 시 거래대금 순으로 5종목 보충 / ETF·ETN·스팩 제외

■ MOMENTUM 전략 풀 (5분 주기 갱신, 점수 기반 선택적 교체)
  API: ka10030(거래량 상위 30) → 기관/외인(ka90009) 조회 추가
  1차 필터: 등락률 ≥ 0.3% + 거래대금 ≥ 10억
  2차 필터: 과열 제외(등락률 > 23%)
  스코어: 거래대금*0.35 + 등락률*0.30 + RSI*0.20 + 외인*0.15
  Fallback: 차트 미통과 시 거래대금*0.60 + 등락률*0.40
  상위 {top_n}개 선정 / 기존 종목과 점수 비교 후 교체 여부 결정

[매매 전략]

■ ORB 매매 (09:05~09:30, 장초반 한정)
  진입 조건:
    • 09:00~09:04 ORB 범위 확립(고점/저점) 후
    • 현재가 > ORB고점 + 거래량 ≥ 직전봉×1.5 + RSI 50~75
    • 추격 방지: 현재가 ≤ ORB고점×1.01 / 최대 5회
  손절: max(ORB저점%, -2%) 기준 이탈 시 즉시 매도
  수익 관리 (4단계 동적):
    peak < 2%  → 트레일링 1.2% / peak < 4%  → 1.5%
    peak < 7%  → 2.0% / peak ≥ 7%  → 2.5%
  수익 반납 방지: peak ≥ 1.5% 후 수익률 0% 이하 시 즉시 매도

■ MOMENTUM 매매 (09:00~15:20)
  공통 조건:
    • 직전 5봉 고점 돌파 확인(3초 유지)
    • 추격 방지: +1.5% 초과 금지 / 과열 종목(등락률>23%) 제외
    • 쿨다운: 매도 후 20분 동일 종목 재매수 금지 / 당일 손실 2회 이상 금지
  진입 신호: 현재가 > 직전5봉고점 + RSI 45~70 + RSI 상승 중
  청산 신호: 데드크로스(MA{chart_short}<MA{chart_long}) AND RSI < 45
  손절: {slr}% 기준 즉시 매도 / 조기손절 -1.2%(진입 후 2분 이내)
  수익 관리 (4단계 동적):
    peak ≥ 7%  → 1.5% / peak ≥ 4%  → 2.0%
    peak ≥ 2%  → 2.5% / peak < 2%   → {tsg}% (phase 기본값)

• 1회 매수 금액: 총자산 × {brt}%"""

			tel_send(help_message)
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
			return await self.stop(True)  # 사용자 명령이므로 auto_start를 false로 설정
		elif command == 'report' or command == 'r':
			return await self.report()
		elif command == 'sel' or command == 's':
			return await self.sel()
		elif command == 'bal' or command == 'b':
			return await self.bal()
		elif command == 'help':
			return await self.help()
		elif command.startswith('top '):
			parts = command.split()
			if len(parts) == 2:
				return await self.top(parts[1])
			else:
				tel_send("❌ 사용법: top {숫자} (예: top 10)")
				return False
		elif command.startswith('slr '):
			parts = command.split()
			if len(parts) == 2:
				return await self.slr(parts[1])
			else:
				tel_send("❌ 사용법: slr {숫자} (예: slr 3)")
				return False
		elif command.startswith('tsg '):
			parts = command.split()
			if len(parts) == 2:
				return await self.tsg(parts[1])
			else:
				tel_send("❌ 사용법: tsg {숫자} (예: tsg 3)")
				return False
		elif command.startswith('brt '):
			parts = command.split()
			if len(parts) == 2:
				return await self.brt(parts[1])
			else:
				tel_send("❌ 사용법: brt {숫자} (예: brt 10)")
				return False
		elif command.startswith('chart '):
			parts = command.split()
			if len(parts) == 3:
				return await self.chart(parts[1], parts[2])
			else:
				tel_send("❌ 사용법: chart {x} {y} (예: chart 5 20)")
				return False
		else:
			tel_send(f"❓ 알 수 없는 명령어입니다: {text}")
			return False
