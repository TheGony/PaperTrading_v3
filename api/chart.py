import requests
import json
import time
import random
from util.config import host_url
from util.logger import get_logger


def _parse_price(val):
	if isinstance(val, str) and val.startswith('-'):
		val = val[1:]
	try:
		return float(val)
	except (ValueError, TypeError):
		return 0.0


def _retry_wait(attempt):
	"""exponential backoff + jitter"""
	return (attempt + 1) * 2 + random.uniform(0.5, 1.5)


# 주식분봉차트조회요청 - 1분봉 기준 여러 봉의 종가 리스트 반환 (최신순)
# 반환: (prices, volumes, open_prices, highs, cntr_tm_latest)
def fn_ka10080(stk_cd, count=30, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/chart'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10080',
	}

	params = {
		'stk_cd': stk_cd,
		'tic_scope': '1',
		'upd_stkpc_tp': '1',
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = _retry_wait(attempt)
				log.warning(f'[ka10080] {stk_cd} 429 rate limit, {wait:.1f}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10080] {stk_cd} 요청 실패: {e}')
				return [], [], [], [], ''
			wait = _retry_wait(attempt)
			log.warning(f'[ka10080] {stk_cd} 요청 실패 ({attempt+1}/3): {e}')
			time.sleep(wait)
	else:
		return [], [], [], [], ''

	chart_data = data.get('stk_min_pole_chart_qry', [])
	if not chart_data:
		log.warning(f'[ka10080] {stk_cd} 데이터 없음 body={json.dumps(data, ensure_ascii=False)[:200]}')
	else:
		log.debug(f'[ka10080] {stk_cd} {len(chart_data)}봉 수신')

	prices      = []
	volumes     = []
	open_prices = []
	highs       = []
	cntr_tm_latest = ''

	for i, candle in enumerate(chart_data[:count]):
		prices.append(_parse_price(candle.get('cur_prc', '0')))
		open_prices.append(_parse_price(candle.get('open_pric', '0')))
		highs.append(_parse_price(candle.get('high_pric', '0')))

		try:
			volumes.append(float(str(candle.get('trde_qty', '0')).replace(',', '')))
		except (ValueError, TypeError):
			volumes.append(0.0)

		if i == 0:
			cntr_tm_latest = str(candle.get('cntr_tm', '')).strip()

	return prices, volumes, open_prices, highs, cntr_tm_latest  # 최신봉 기준 내림차순


def fn_ka10080_full(stk_cd, count=30, cont_yn='N', next_key='', token=None):
	"""1분봉 전체 필드 반환 (ORB용). 최신순 리스트 of dict"""
	log = get_logger()
	url = host_url + '/api/dostk/chart'
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10080',
	}
	params = {'stk_cd': stk_cd, 'tic_scope': '1', 'upd_stkpc_tp': '1'}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = _retry_wait(attempt)
				log.warning(f'[ka10080_full] {stk_cd} 429, {wait:.1f}초 후 재시도')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10080_full] {stk_cd} 요청 실패: {e}')
				return []
			wait = _retry_wait(attempt)
			time.sleep(wait)
	else:
		return []

	def _p(val):
		s = str(val).strip().replace(',', '')
		neg = s.startswith('-')
		try:
			return -float(s[1:]) if neg else float(s.lstrip('+'))
		except (ValueError, TypeError):
			return 0.0

	result = []
	for candle in data.get('stk_min_pole_chart_qry', [])[:count]:
		try:
			vol = float(str(candle.get('trde_qty', '0')).replace(',', ''))
		except (ValueError, TypeError):
			vol = 0.0
		result.append({
			'cur_prc':   abs(_p(candle.get('cur_prc',   '0'))),
			'open_pric': abs(_p(candle.get('open_pric', '0'))),
			'high_pric': abs(_p(candle.get('high_pric', '0'))),
			'low_pric':  abs(_p(candle.get('low_pric',  '0'))),
			'trde_qty':  vol,
			'cntr_tm':   str(candle.get('cntr_tm', '')).strip(),
			'pred_pre':  _p(candle.get('pred_pre', '0')),
		})
	return result
