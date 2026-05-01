import math
import asyncio
from api.market import fn_ka20001_full
from util.logger import get_logger

KOSPI_MRKT  = ('0', '001')
KOSDAQ_MRKT = ('1', '101')


# ── Continuous trailing functions ─────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
	return max(lo, min(hi, val))


def orb_trailing(peak: float) -> float:
	"""ORB continuous trailing gap (%) — 빠른 청산, 수익 반납 최소화"""
	return _clamp(1.0 + peak * 0.12, 1.0, 1.8)


def momentum_trailing(peak: float, volatility: float) -> float:
	"""MOMENTUM continuous trailing gap (%) — 추세 유지, 눌림 허용"""
	adjustment = math.log(1 + peak) * 0.6 if peak > 0 else 0.0
	vol_adj    = volatility * 0.5
	return _clamp(2.0 + adjustment + vol_adj, 2.0, 3.2)


# ── Market Regime 계산 (ka20001 당일 OHLC 기반) ───────────────────────────────

def _intraday_vol(index_data: dict) -> float:
	"""(high - low) / cur_prc * 100 — 당일 장중 진폭(%)"""
	if not index_data:
		return 0.0
	cur  = index_data['cur_prc']
	high = index_data['high_pric']
	low  = index_data['low_pric']
	return ((high - low) / cur * 100) if cur > 0 else 0.0


def _trend_magnitude(index_data: dict) -> float:
	"""|flu_rt| — 전일 대비 지수 변동폭 절댓값(%)"""
	if not index_data:
		return 0.0
	return abs(index_data.get('flu_rt', 0.0))


def _classify(vol: float, trend: float) -> str:
	if vol > 2.5:
		return 'volatile_market'
	if trend > 0.8:
		return 'trend_strong'
	if trend < 0.3:
		return 'sideways'
	return 'normal'


# ── RegimeMixin ───────────────────────────────────────────────────────────────

class RegimeMixin:
	async def _regime_loop(self):
		"""5분 주기로 KOSPI+KOSDAQ 당일 OHLC 분석 → Market Regime 갱신"""
		log = get_logger()
		while self.is_running:
			try:
				kospi_d, kosdaq_d = await asyncio.gather(
					asyncio.get_event_loop().run_in_executor(
						None, fn_ka20001_full, *KOSPI_MRKT, self.token
					),
					asyncio.get_event_loop().run_in_executor(
						None, fn_ka20001_full, *KOSDAQ_MRKT, self.token
					),
				)

				kospi_vol  = _intraday_vol(kospi_d)
				kosdaq_vol = _intraday_vol(kosdaq_d)
				kospi_tr   = _trend_magnitude(kospi_d)
				kosdaq_tr  = _trend_magnitude(kosdaq_d)

				market_volatility = kospi_vol * 0.4 + kosdaq_vol * 0.6
				market_trend      = kospi_tr  * 0.4 + kosdaq_tr  * 0.6
				regime            = _classify(market_volatility, market_trend)

				self.market_volatility = market_volatility
				self.market_regime     = regime
				log.info(
					f'[Regime] {regime} | '
					f'vol={market_volatility:.3f} (K={kospi_vol:.3f} Q={kosdaq_vol:.3f}) | '
					f'trend={market_trend:.3f} (K={kospi_tr:.3f} Q={kosdaq_tr:.3f})'
				)
			except Exception as e:
				log.warning(f'[Regime] 갱신 오류: {e}')

			await asyncio.sleep(300)  # 5분
