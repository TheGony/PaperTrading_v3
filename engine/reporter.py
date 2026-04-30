import os
import csv
import datetime
import asyncio
from api.account import fn_kt00004, fn_kt00002, fn_ka01690, fn_ka10072
from util.market_hour import MarketHour
from util.tel_send import tel_send
from util.logger import get_logger


class ReporterMixin:
	LOG_DIR = 'trading_logs'

	def _safe_int(self, value, default=0):
		"""문자열을 안전하게 정수로 변환합니다."""
		if value is None:
			return default
		if isinstance(value, (int, float)):
			return int(value)
		value_str = str(value).strip().replace(',', '').replace(' ', '')
		if not value_str or value_str == '':
			return default
		try:
			if '.' in value_str:
				return int(float(value_str))
			return int(value_str)
		except (ValueError, TypeError):
			return default

	def _safe_float(self, value, default=0.0):
		"""문자열을 안전하게 실수로 변환합니다."""
		if value is None:
			return default
		if isinstance(value, (int, float)):
			return float(value)
		value_str = str(value).strip().replace(',', '').replace(' ', '').replace('+', '').replace('%', '')
		if not value_str or value_str == '':
			return default
		try:
			return float(value_str)
		except (ValueError, TypeError):
			return default

	def _log_trade(self, stk_nm, stk_cd, pl_rt, reason, mfe=None, mae=None, snapshot=None):
		record = {
			'time':   datetime.datetime.now().strftime('%H:%M:%S'),
			'phase':  MarketHour.get_market_phase(),
			'stk_nm': stk_nm,
			'stk_cd': stk_cd,
			'pl_rt':  pl_rt,
			'mfe':    mfe,
			'mae':    mae,
			'reason': reason,
		}
		if snapshot:
			record.update(snapshot)
		self.trade_log.append(record)
		if pl_rt < 0:
			self.daily_loss_count[stk_cd] = self.daily_loss_count.get(stk_cd, 0) + 1
			if self.daily_loss_count[stk_cd] >= 2 and stk_cd in self.selected_stocks:
				self.selected_stocks.remove(stk_cd)
				self.needs_stock_refresh = True
				get_logger().info(f'[종목제외] {stk_cd} 당일 손실 2회 → 선정 목록 즉시 제거, 보충 갱신 예약')

	def _write_csv(self, today, summary):
		os.makedirs(self.LOG_DIR, exist_ok=True)

		# ── trade_detail.csv (매매 건별 누적) ─────────────────────────────
		detail_path = os.path.join(self.LOG_DIR, 'trade_detail.csv')
		expected_header = [
			'날짜', '시간', '구간', '종목명', '종목코드',
			'수익률(%)', 'MFE(%)', 'MAE(%)', '매도사유',
			'진입가', '진입RSI', '진입등락률(%)', '거래량비율',
			'선정점수', '외인기관', 'KOSPI등락(%)', 'KOSDAQ등락(%)', '전략',
			'갭(%)', 'ORB손절기준(%)', '보유시간(분)', 'ORB오버슈트(%)', '돌파확인(초)',
			'돌파강도(%)', '추격비율(%)', '거래대금', '거래대금순위', '진입시간(분)',
		]
		if os.path.exists(detail_path):
			# 기존 헤더 확인 후 컬럼 추가된 경우 파일 재작성
			with open(detail_path, 'r', encoding='utf-8-sig') as f:
				existing_header = next(csv.reader(f), [])
			if existing_header != expected_header:
				with open(detail_path, 'r', encoding='utf-8-sig') as f:
					rows = list(csv.reader(f))
				with open(detail_path, 'w', newline='', encoding='utf-8-sig') as f:
					w2 = csv.writer(f)
					w2.writerow(expected_header)
					for row in rows[1:]:
						# 기존 행은 부족한 컬럼을 빈값으로 채움
						padded = row + [''] * (len(expected_header) - len(row))
						w2.writerow(padded[:len(expected_header)])
		with open(detail_path, 'a', newline='', encoding='utf-8-sig') as f:
			w = csv.writer(f)
			if not os.path.exists(detail_path) or os.path.getsize(detail_path) == 0:
				w.writerow(expected_header)
			phase_map = {'early': '장초반', 'mid': '장중반', 'late': '장후반'}
			for t in self.trade_log:
				mfe_str   = f"{t['mfe']:+.2f}" if t.get('mfe') is not None else ''
				mae_str   = f"{t['mae']:+.2f}" if t.get('mae') is not None else ''
				phase_str = phase_map.get(t.get('phase', ''), t.get('phase', ''))
				w.writerow([
					today, t['time'], phase_str, t['stk_nm'], t['stk_cd'],
					f"{t['pl_rt']:+.2f}", mfe_str, mae_str, t['reason'],
					t.get('entry_price', ''), t.get('entry_rsi', ''),
					t.get('entry_flu_rt', ''), t.get('entry_vol_ratio', ''),
					t.get('entry_score', ''), '○' if t.get('is_foreign') else '×',
					t.get('kospi_flu', ''), t.get('kosdaq_flu', ''),
					t.get('strategy', 'MOMENTUM'),
					f"{t['orb_gap']:+.2f}"        if t.get('orb_gap')       is not None else '',
					f"{t['orb_stop_pct']:+.2f}"   if t.get('orb_stop_pct')  is not None else '',
					t.get('held_minutes', ''),
					f"{t['orb_overshoot']:+.2f}"  if t.get('orb_overshoot') is not None else '',
					t.get('confirm_secs', ''),
					f"{t['breakout_strength']:+.2f}" if t.get('breakout_strength') is not None else '',
					f"{t['chase_pct']:+.2f}"         if t.get('chase_pct')         is not None else '',
					t.get('entry_trde_amt', ''),
					t.get('entry_trde_amt_rank', ''),
					t.get('entry_time_min', ''),
				])

		# ── daily_summary.csv (날짜별 1행 누적) ──────────────────────────
		summary_path = os.path.join(self.LOG_DIR, 'daily_summary.csv')
		write_header = not os.path.exists(summary_path)
		with open(summary_path, 'a', newline='', encoding='utf-8-sig') as f:
			w = csv.writer(f)
			if write_header:
				w.writerow([
					'날짜', '예탁자산(원)', '일손익(원)', '일수익률(%)', '누적수익률(%)',
					'매매횟수', '수익매매수', '손실매매수', '승률(%)',
					'평균수익률(%)', '평균손실률(%)', '손익비',
					'최대단일수익(%)', '최대단일손실(%)',
				])
			w.writerow([
				today,
				summary['total_assets'],
				summary['day_profit'],
				f"{summary['day_profit_rt']:+.2f}",
				f"{summary['cum_profit_rt']:+.2f}",
				summary['trade_count'],
				summary['win_count'],
				summary['lose_count'],
				f"{summary['win_rate']:.1f}",
				f"{summary['avg_win']:+.2f}",
				f"{summary['avg_loss']:+.2f}",
				f"{summary['profit_factor']:.2f}",
				f"{summary['max_win']:+.2f}",
				f"{summary['max_loss']:+.2f}",
			])

	async def _send_daily_report(self):
		"""장 마감 시 일별 보고서 발송"""
		try:
			today         = datetime.datetime.now().strftime('%Y%m%d')
			today_display = datetime.datetime.now().strftime('%Y-%m-%d')

			# 병렬 조회
			day_bal_data, (my_stocks, aset_evlt_amt, _), profit_data, (prsm, _) = await asyncio.gather(
				asyncio.get_event_loop().run_in_executor(None, fn_ka01690, today, 'N', '', self.token),
				asyncio.get_event_loop().run_in_executor(None, fn_kt00004, False, 'N', '', self.token),
				asyncio.get_event_loop().run_in_executor(None, fn_ka10072, today, '', 'N', '', self.token),
				asyncio.get_event_loop().run_in_executor(None, fn_kt00002, self.token),
			)

			message = f"📊 [장 마감 일별 보고서] {today_display}\n\n"

			# ── 1. 계좌 잔고 ──────────────────────────────
			stk_evlt_sum = sum(self._safe_int(s.get('evlt_amt', '0')) for s in my_stocks) if my_stocks else 0
			cash_val     = self._safe_int(aset_evlt_amt) if aset_evlt_amt else 0
			prsm_int     = self._safe_int(prsm)
			total_assets = prsm_int if prsm_int > 0 else (cash_val + stk_evlt_sum)

			message += "💼 [계좌 잔고]\n"
			message += f"   추정예탁자산: {total_assets:,}원\n"
			message += f"   현금(예탁자산평가액): {cash_val:,}원\n"
			message += f"   주식평가금액: {stk_evlt_sum:,}원\n\n"

			# ── 2. 보유 주식 현황 ─────────────────────────
			if my_stocks:
				message += "📦 [보유 주식]\n"
				for s in my_stocks:
					nm    = s.get('stk_nm', s.get('stk_cd', 'N/A'))
					cd    = s.get('stk_cd', '').replace('A', '')
					qty   = self._safe_int(s.get('rmnd_qty', '0'))
					evlt  = self._safe_int(s.get('evlt_amt', '0'))
					pl_rt = self._safe_float(s.get('pl_rt', '0'))
					emoji = '🔴' if pl_rt > 0 else ('🔵' if pl_rt < 0 else '➡️')
					message += f"   {emoji} {nm}({cd}) {qty}주 | {evlt:,}원 | {pl_rt:+.2f}%\n"
				message += "\n"
			else:
				message += "📦 [보유 주식] 없음\n\n"

			# ── 3. 오늘 수익 요약 ─────────────────────────
			profit_by_stock = {}
			total_profit    = 0
			trade_count     = 0

			if profit_data and 'dt_stk_div_rlzt_pl' in profit_data:
				for item in profit_data['dt_stk_div_rlzt_pl']:
					stk_nm     = item.get('stk_nm', 'N/A')
					tdy_sel_pl = self._safe_int(item.get('tdy_sel_pl', '0'))
					pl_rt      = self._safe_float(item.get('pl_rt', '0'))
					trade_count += 1
					if stk_nm not in profit_by_stock:
						profit_by_stock[stk_nm] = {'profit': 0, 'rate': 0.0, 'count': 0}
					profit_by_stock[stk_nm]['profit'] += tdy_sel_pl
					profit_by_stock[stk_nm]['rate']    = pl_rt
					profit_by_stock[stk_nm]['count']  += 1
					total_profit += tdy_sel_pl

			tot_prft_rt    = 0.0
			tot_evltv_prft = 0
			if day_bal_data:
				tot_prft_rt    = self._safe_float(day_bal_data.get('tot_prft_rt', '0'))
				tot_evltv_prft = self._safe_int(day_bal_data.get('tot_evltv_prft', '0'))
			if tot_evltv_prft == 0 and total_profit != 0:
				tot_evltv_prft = total_profit
			if tot_prft_rt == 0 and profit_by_stock:
				total_weighted_rate = 0
				total_abs_profit    = 0
				for sd in profit_by_stock.values():
					ap = abs(sd['profit'])
					total_weighted_rate += sd['rate'] * ap
					total_abs_profit    += ap
				if total_abs_profit > 0:
					tot_prft_rt = total_weighted_rate / total_abs_profit

			day_emoji = '📈' if tot_evltv_prft >= 0 else '📉'
			message += f"{day_emoji} [오늘 손익]\n"
			message += f"   총 손익: {tot_evltv_prft:+,}원\n"
			message += f"   수익률: {tot_prft_rt:+.2f}%\n"
			message += f"   총 매매 횟수: {trade_count}회\n\n"

			# ── 4. 종목별 실현손익 상세 ───────────────────
			if profit_by_stock:
				win  = [(n, d) for n, d in profit_by_stock.items() if d['profit'] > 0]
				lose = [(n, d) for n, d in profit_by_stock.items() if d['profit'] <= 0]
				message += f"📋 [실현손익 상세] (수익 {len(win)}종목 / 손실 {len(lose)}종목)\n"
				sorted_stocks = sorted(profit_by_stock.items(), key=lambda x: x[1]['profit'], reverse=True)
				for stk_nm, sd in sorted_stocks:
					emoji = '🔴' if sd['profit'] > 0 else '🔵'
					message += f"   {emoji} {stk_nm}: {sd['profit']:+,}원 ({sd['rate']:+.2f}%)\n"

			tel_send(message)

			# ── CSV 저장 ──────────────────────────────────
			wins       = [t for t in self.trade_log if t['pl_rt'] > 0]
			losses     = [t for t in self.trade_log if t['pl_rt'] <= 0]
			win_rates  = [t['pl_rt'] for t in wins]
			lose_rates = [t['pl_rt'] for t in losses]
			avg_win    = sum(win_rates)  / len(win_rates)  if win_rates  else 0.0
			avg_loss   = sum(lose_rates) / len(lose_rates) if lose_rates else 0.0
			profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
			all_rates  = [t['pl_rt'] for t in self.trade_log]

			# 누적수익률: daily_summary.csv 마지막 행에서 읽어서 합산
			summary_path = os.path.join(self.LOG_DIR, 'daily_summary.csv')
			prev_cum = 0.0
			if os.path.exists(summary_path):
				with open(summary_path, 'r', encoding='utf-8-sig') as f:
					rows = list(csv.reader(f))
					if len(rows) > 1:
						try:
							prev_cum = float(rows[-1][4])  # 누적수익률 컬럼
						except (ValueError, IndexError):
							prev_cum = 0.0
			cum_profit_rt = prev_cum + tot_prft_rt

			summary = {
				'total_assets':  total_assets,
				'day_profit':    tot_evltv_prft,
				'day_profit_rt': tot_prft_rt,
				'cum_profit_rt': cum_profit_rt,
				'trade_count':   trade_count,
				'win_count':     len(wins),
				'lose_count':    len(losses),
				'win_rate':      len(wins) / trade_count * 100 if trade_count else 0.0,
				'avg_win':       avg_win,
				'avg_loss':      avg_loss,
				'profit_factor': profit_factor,
				'max_win':       max(all_rates) if all_rates else 0.0,
				'max_loss':      min(all_rates) if all_rates else 0.0,
			}
			try:
				self._write_csv(today, summary)
				print(f"CSV 저장 완료: {self.LOG_DIR}/")
			except Exception as csv_e:
				print(f"CSV 저장 오류: {csv_e}")

			# 장 종료 시 초기화
			self.selected_stocks = []
			self.last_chart_check_time = None
			self.trade_log = []
			self.daily_loss_count = {}
			self.entry_time = {}
			self.entry_snapshot = {}
			self.orb_data = {}
			self.orb_buy_count = 0
			self.orb_candidates = []
			print("장 종료: 선정된 종목 리스트를 초기화했습니다.")

		except Exception as e:
			print(f"일별 보고서 발송 중 오류: {e}")
			tel_send(f"❌ 일별 보고서 발송 중 오류: {e}")
