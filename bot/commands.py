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

			msg_cmd = f"""🤖 [PaperTrading v2 명령어 가이드]

[기본 명령어]
• start  - 매매 시작 (장 외이면 장 시작 시 자동 실행)
• stop   - 매매 중지 (보유 포지션 유지)
• r      - 보유 종목 수익률·MFE 조회
• s      - 선정 종목·ORB 후보 조회
• b      - 계좌 자산 현황
• help   - 이 도움말

[설정 명령어] (현재값)
• top {{n}}         선정 종목 수   (현재: {top_n}개)      예) top 5
• brt {{n}}         1회 매수 비율 (현재: {brt}%)         예) brt 8
• chart {{x}} {{y}}    MA 설정       (현재: MA{chart_short}/MA{chart_long}) 예) chart 5 20
※ 손절·트레일링은 전략별 고정값 (slr·tsg 명령어 없음)"""

			msg_sel = f"""
━━━━━━━━━━━━━━━━━━━━━━
[1단계] 종목선정방식
━━━━━━━━━━━━━━━━━━━━━━

■ ORB 후보 (09:01 1차 → 09:03 2차 확정, 이후 고정, 최대 15종목)
  API: 거래대금상위(ka10032) + 당일거래량상위(ka10030) 병합
  하드 필터:
    · 갭상승(gap > 0%) 종목만
    · 시가 대비 -2% 이상 눌린 종목 제외
    · ETF·ETN·스팩·레버리지 제외
  소프트 패널티 (각 -0.2):
    · 갭 1.5~8% 범위 이탈
    · 당일 윗꼬리 > 5%
    · 09:00~09:10 음봉 2개 이상
  스코어 = 당일거래량 40% + 거래대금 30% + 등락률 30% - 패널티
  보충: 5종목 미만 시 캔들 미통과 종목을 거래대금 순으로 보충

■ MOMENTUM 후보 (09:03 이후 초기 선정, 5분 주기 점수 비교 갱신, 상위 {top_n}종목)
  API: 당일거래량상위(ka10030) + 거래량급증(ka10023) 병합
       외인수급: 외국인 순매수 종목 조회(ka90009)
  하드 필터:
    · 등락률 ≥ +0.3% + 거래대금 ≥ 10억
    · 과열 종목(등락률 > 23%) 제외
    · ETF·ETN·스팩·레버리지 제외
  차트 필터: RSI(14) 계산용 1분봉 조회 (캐시 활용)
  스코어 = 거래대금 30% + 등락률 25% + RSI(14) 20%
           + 외인수급 15% + 거래량급증비율(sdnin_rt) 10%
  갱신: 기존 종목과 신규 후보 점수 비교 후 선택적 교체
        (갱신 시 기존 상위 종목은 1사이클 버팀)"""

			msg_entry = f"""
━━━━━━━━━━━━━━━━━━━━━━
[2단계] 매수로직
━━━━━━━━━━━━━━━━━━━━━━

■ ORB 매수 (09:05~09:30, 최대 5회)
  사전 조건:
    · orb_ready 플래그 True (09:03 2차 선정 완료 이후)
    · 미보유 + 쿨다운 20분 경과
    · ORB 범위 확립: 09:00~09:04 구간 봉 3개 이상 필요
    · 갭상승(gap_up) 종목만
  진입 조건:
    · 현재가 > ORB 고점 (09:00~09:04 봉 최고가)
    · 추격방지: 현재가 ≤ ORB 고점 × 1.01
    · 거래량 > 직전봉 × 1.5
    · RSI(14) 50~75
  손절 기준 계산: max(ORB 저점%, -2.0%) → 스냅샷에 저장

■ MOMENTUM 매수 (09:03~15:20, 5초 루프)
  사전 조건:
    · orb_ready 플래그 True (09:03 이후)
    · selected_stocks 내 종목 + 미보유 + 미진입 대기 중
    · 쿨다운 20분 경과
    · 당일 2회 이상 손절 종목 영구 제외
    · 과열 종목(등락률 > 23%) 제외
    · 동일봉 스킵: 직전 체크와 동일 cntr_tm이면 재평가 생략
  진입 조건:
    · 현재가 > 직전 5봉 고점 (1분봉)
    · 추격방지: 현재가 ≤ 직전 5봉 고점 × 1.015
    · RSI(14) 45~70
    · RSI 하락폭 제한: 직전봉 RSI 대비 2% 이상 하락 시 스킵
    · 고점 근접 필터: 현재가 ≥ 당일고점×0.98 이면서 거래량비율 ≤ 1.7배 시 스킵
    · 거래량 필터: 현재봉 > 직전 5봉 평균 × 1.2
    · VWAP 기관수급: 현재가 > VWAP, VWAP갭 ≤ 3%, 최근5봉 거래대금 > 이전5봉 × 1.2

■ 공통
  매수 금액: 총자산(예탁자산평가액 + 주식평가금액) × {brt}%
  주문 단위: 해당 금액 ÷ 현재가 (정수 내림)"""

			msg_exit = f"""
━━━━━━━━━━━━━━━━━━━━━━
[3단계] 매도로직 / 검증방식
━━━━━━━━━━━━━━━━━━━━━━

■ ORB 청산 (profit_check_loop, 1초 주기)
  우선순위 (위일수록 먼저 체크):
  1. 조기손절    진입 2분 이내 수익률 < -1.2%       → 즉시 매도
  2. ORB 저점    수익률 ≤ orb_stop_pct              → 즉시 매도
                 (orb_stop_pct = max(ORB저점%, -2.0%))
  3. 수익반납방지 peak ≥ 1.5% 도달 후 pl < 0%       → 2회 확인
  4. 트레일링    pl ≤ peak - orb_trailing(peak)     → 2회 확인
                 orb_trailing = clamp(1.0 + peak×0.12,  1.0, 1.8)
                 예) peak 2%→1.24%  5%→1.60%  7%+→1.80%
  5. 고정손절    수익률 ≤ -2.0%                     → 즉시 매도

■ MOMENTUM 청산 (두 루프 병행)
  [차트체크 5초 루프]
    데드크로스: MA{chart_short} < MA{chart_long} AND RSI(14) < 45 → 즉시 매도

  [profit_check 1초 루프]
  우선순위:
  1. 조기손절    진입 2분 이내 수익률 < -1.2%                   → 즉시 매도
  2. 트레일링    pl ≤ peak - momentum_trailing(peak, vol)      → 2회 확인
                 momentum_trailing = clamp(2.0 + log(1+peak)×0.6 + vol×0.5,  2.0, 3.2)
                 vol = 시장변동성 (KOSPI×0.4 + KOSDAQ×0.6 장중진폭%)
                 예) peak 2%,vol=0→2.54%  peak 5%,vol=1.0→3.20%
  3. 고정손절    수익률 ≤ -3.0%                                → 즉시 매도

■ Market Regime (5분 주기 갱신, _regime_loop)
  KOSPI+KOSDAQ 당일 OHLC(ka20001) 기반
  · 변동성 = (고가-저가)/현재가 × 100 의 가중평균
  · 추세   = |등락률| 의 가중평균
  · volatile_market(vol>2.5) / trend_strong(trend>0.8)
    sideways(trend<0.3) / normal
  → Regime은 MOMENTUM trailing의 vol 파라미터에만 반영

■ 자동매매 검증방식
  · 돌파 확인: 진입 전 3초 동안 0.5초 간격 현재가 재조회
               가격 이탈 시 진입 취소 (false positive 방지)
  · 동일봉 스킵: 1분봉 cntr_tm 비교, 동일봉이면 MOMENTUM 진입 조건 재평가 생략
  · 차트 캐시: TTL 55초, Semaphore(4) 병렬 제한
               대기 중 타 코루틴이 먼저 채우면 double-fetch 방지
  · 휩쏘 방지: 소프트 스탑(트레일링·수익반납)은 연속 2회 조건 충족 시만 매도
  · 보유 재확인: 체크 루프 매 회차마다 fn_kt00004 API로 실계좌 보유 현황 재조회
  · MFE·MAE 추적: peak_profit(MFE) / min_profit(MAE) 실시간 갱신
                  매도 시 trade_detail.csv에 기록
  · ghost 정리: 매 루프마다 실계좌 보유 없는 종목의 peak·signal_count 자동 삭제
  · 매도 실패: API 오류 시 상태 유지 → 다음 루프(1초 후) 자동 재시도"""

			tel_send(msg_cmd)
			tel_send(msg_sel)
			tel_send(msg_entry)
			tel_send(msg_exit)
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
