from strategy.indicators import IndicatorsMixin
from strategy.mom_selector import StockSelectorMixin
from strategy.orb_selector import OrbSelectorMixin
from engine.reporter import ReporterMixin
from engine.entry import EntryMixin
from engine.exit import ExitMixin
from engine.regime import RegimeMixin
from engine.trader import TraderMixin
from bot.commands import BotCommandsMixin


class ChatCommand(
	IndicatorsMixin,
	StockSelectorMixin,
	OrbSelectorMixin,
	EntryMixin,
	ExitMixin,
	RegimeMixin,
	ReporterMixin,
	TraderMixin,
	BotCommandsMixin,
):
	def __init__(self):
		self.token                  = None   # 현재 사용 중인 토큰
		self.is_running             = False  # 프로세스 실행 여부
		self.trading_task           = None   # 트레이딩 백그라운드 태스크
		self.profit_check_task      = None   # 수익율 체크 백그라운드 태스크
		self.selected_stocks        = []     # 선정된 종목 코드 리스트
		self.selected_stocks_names  = {}     # 종목코드 → 종목명 매핑
		self.selected_stocks_meta   = {}     # 종목코드 → {flu_rt, score, is_foreign}
		self.last_chart_check_time  = None   # 마지막 차트 체크 시간
		self.sell_cooldown          = {}     # 매도 후 재매수 금지 추적 {stk_cd: 매도시각}
		self.daily_loss_count       = {}     # 당일 종목별 손실 횟수 {stk_cd: count}
		self.entry_time             = {}     # 매수 체결 시각 {stk_cd: datetime}
		self.entry_snapshot         = {}     # 매수 시점 스냅샷 {stk_cd: dict}
		self.peak_profit            = {}     # 트레일링 스탑용 종목별 최고 수익률 {stk_cd: max_pl_rt}
		self.min_profit             = {}     # MAE 추적: 보유 중 최저 수익률 {stk_cd: min_pl_rt}
		self.trade_log              = []     # 당일 매매 기록
		self.orb_ready              = False  # ORB 2차 선정 완료 플래그 (True 이후에만 진입 허용)
		self.orb_data               = {}     # ORB 고점/저점 캐시 {stk_cd: {'high', 'low', 'gap_up'}}
		self.orb_buy_count          = 0      # ORB 매수 횟수 (최대 orb_max_count회)
		self.orb_candidates         = []     # ORB 전용 후보 리스트 (장 시작 2회 선정 고정)
		self.last_known_assets      = None   # 총자산 캐시 (kt00004 429 등 일시 실패 시 폴백)
		self.needs_stock_refresh    = False  # 종목 즉시 보충 플래그 (daily_loss_count 2회 제거 시)
		self._chart_cache           = {}     # ka10080 캐시 {stk_cd: {'ts': datetime, 'data': tuple}}
		self._chart_semaphore       = None   # 동시 API 호출 제한 (Semaphore(4), 첫 호출 시 초기화)
		self._last_candle_time      = {}     # cntr_tm 기반 동일봉 스킵 {stk_cd: cntr_tm}
		self._sell_signal_count     = {}     # 휩쏘 방지: 연속 매도 신호 횟수 {stk_cd: count}
		self.market_volatility      = 0.0    # KOSPI*0.4 + KOSDAQ*0.6 ATR(14)/price*100
		self.market_regime          = 'normal'  # volatile_market / trend_strong / sideways / normal
		self.regime_task            = None   # Market Regime 갱신 백그라운드 태스크
