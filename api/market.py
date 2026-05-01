import requests
import json
import time
from util.config import host_url
from util.logger import get_logger


# ── 주식기본정보요청 (ka10001) ─────────────────────────────────────────

def _parse_price(val):
	"""가격 필드 파싱: '+12345'/'-12345' → 절대값 float. 부호는 방향 표시일 뿐."""
	if not val:
		return 0.0
	try:
		return abs(float(str(val).strip().lstrip('+-').replace(',', '')))
	except (ValueError, TypeError):
		return 0.0


def _parse_rate(val):
	"""등락률 등 부호 있는 실수 파싱: '+3.22'→3.22, '-0.78'→-0.78."""
	if not val:
		return 0.0
	s = str(val).strip()
	try:
		if s.startswith('-'):
			return -float(s[1:].replace(',', ''))
		return float(s.lstrip('+').replace(',', ''))
	except (ValueError, TypeError):
		return 0.0


def fn_ka10001(stk_cd, cont_yn='N', next_key='', token=None):
	"""주식기본정보요청 (ka10001).
	반환: dict (high_pric, cur_prc, flu_rt 등 숫자 변환 완료) — 실패 시 None
	"""
	log = get_logger()
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10001',
	}
	for attempt in range(3):
		try:
			response = requests.post(
				host_url + '/api/dostk/stkinfo',
				headers=headers,
				json={'stk_cd': stk_cd},
				timeout=5,
			)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10001] {stk_cd} 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.warning(f'[ka10001] {stk_cd} 요청 실패: {e}')
				return None
			log.warning(f'[ka10001] {stk_cd} 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return None

	if data.get('return_code', -1) != 0:
		log.warning(f'[ka10001] {stk_cd} API 오류: {data.get("return_msg")}')
		return None

	return {
		'stk_nm':    data.get('stk_nm', ''),
		'cur_prc':   _parse_price(data.get('cur_prc')),
		'high_pric': _parse_price(data.get('high_pric')),
		'low_pric':  _parse_price(data.get('low_pric')),
		'open_pric': _parse_price(data.get('open_pric')),
		'flu_rt':    _parse_rate(data.get('flu_rt')),
		'trde_qty':  _parse_price(data.get('trde_qty')),
	}


# ── 업종현재가요청 (ka20001) — 코스피/코스닥 등락률 ──────────────────────

_MARKETS = [
	('0', '001', 'kospi'),
	('1', '101', 'kosdaq'),
]


def _fetch_index_flu_rt(mrkt_tp, inds_cd, token):
	"""ka20001로 업종 등락률 조회. 실패 시 None 반환."""
	log = get_logger()
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': 'N',
		'next-key': '',
		'api-id': 'ka20001',
	}
	data = None
	for attempt in range(3):
		try:
			response = requests.post(
				host_url + '/api/dostk/sect',
				headers=headers,
				json={'mrkt_tp': mrkt_tp, 'inds_cd': inds_cd},
				timeout=5,
			)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[market_index] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.warning(f'[market_index] mrkt_tp={mrkt_tp} inds_cd={inds_cd} 조회 실패: {e}')
				return None
			log.warning(f'[market_index] 조회 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	if data is None:
		return None

	return_code = data.get('return_code', -1)
	if return_code != 0:
		log.warning(f'[market_index] ka20001 오류: code={return_code} msg={data.get("return_msg")}')
		return None

	val = data.get('flu_rt')
	if not val:
		return None
	val = str(val).strip()
	if val.startswith('-'):
		return -float(val[1:])
	return float(val.lstrip('+'))


def fn_ka20001_full(mrkt_tp, inds_cd, token=None):
	"""업종현재가요청 (ka20001) — 지수 당일 OHLC + 등락률 + 시장 breadth.
	반환: {'cur_prc', 'high_pric', 'low_pric', 'flu_rt', 'rising', 'fall'} — 실패 시 None
	"""
	log = get_logger()
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': 'N',
		'next-key': '',
		'api-id': 'ka20001',
	}
	for attempt in range(3):
		try:
			response = requests.post(
				host_url + '/api/dostk/sect',
				headers=headers,
				json={'mrkt_tp': mrkt_tp, 'inds_cd': inds_cd},
				timeout=5,
			)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka20001_full] {inds_cd} 429, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.warning(f'[ka20001_full] {inds_cd} 요청 실패: {e}')
				return None
			time.sleep((attempt + 1) * 2)
	else:
		return None

	if data.get('return_code', -1) != 0:
		return None

	def _r(val):
		s = str(val).strip()
		try:
			return -float(s[1:].replace(',', '')) if s.startswith('-') else float(s.lstrip('+').replace(',', ''))
		except (ValueError, TypeError):
			return 0.0

	def _i(val):
		try:
			return int(str(val).replace(',', ''))
		except (ValueError, TypeError):
			return 0

	return {
		'cur_prc':   abs(_r(data.get('cur_prc',   '0'))),
		'high_pric': abs(_r(data.get('high_pric', '0'))),
		'low_pric':  abs(_r(data.get('low_pric',  '0'))),
		'flu_rt':    _r(data.get('flu_rt', '0')),
		'rising':    _i(data.get('rising', '0')),
		'fall':      _i(data.get('fall',   '0')),
	}


def fn_get_market_index(token=None):
	"""코스피/코스닥 현재 등락률 반환.
	반환: (kospi_flu_rt, kosdaq_flu_rt) — 조회 실패 시 해당 값 None
	"""
	result = {}
	for mrkt_tp, inds_cd, key in _MARKETS:
		result[key] = _fetch_index_flu_rt(mrkt_tp, inds_cd, token)
	return result.get('kospi'), result.get('kosdaq')
