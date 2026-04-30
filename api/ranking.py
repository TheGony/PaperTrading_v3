import requests
import json
import time
from util.config import host_url
from util.logger import get_logger

# 거래량급증요청 (ka10023)
# 전일 대비 거래량이 급증하면서 상승 중인 종목 반환
def fn_ka10023(count=20, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/rkinfo'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10023',
	}

	params = {
		'mrkt_tp':     '000',  # 전체 (코스피+코스닥)
		'sort_tp':     '2',    # 급증률 기준 내림차순
		'tm_tp':       '2',    # 전일 대비
		'trde_qty_tp': '10',   # 만주 이상 (소형주 노이즈 제거)
		'tm':          '',
		'stk_cnd':     '4',    # 관리종목 + 우선주 제외
		'pric_tp':     '8',    # 1천원 이상 (동전주 제외)
		'stex_tp':     '1',    # KRX
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10023] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10023] 요청 실패: {e}')
				return []
			log.warning(f'[ka10023] 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return []

	log.debug(f'[ka10023] status={response.status_code}')
	log.debug(f'[ka10023] body={json.dumps(data, ensure_ascii=False)}')

	raw_list = data.get('trde_qty_sdnin', [])
	if not raw_list:
		return []

	candidates = []
	for item in raw_list:
		try:
			flu_rt   = float(item.get('flu_rt',   '0').replace('+', '').replace(',', ''))
			sdnin_rt = float(item.get('sdnin_rt', '0').replace('+', '').replace(',', ''))
			stk_cd   = item.get('stk_cd', '').replace('A', '')
			stk_nm   = item.get('stk_nm', '')

			# 필터: 상승 중(양봉) + 전일 대비 거래량 2배 이상
			if flu_rt > 0 and sdnin_rt >= 100:
				candidates.append({
					'stk_cd':   stk_cd,
					'stk_nm':   stk_nm,
					'flu_rt':   flu_rt,
					'sdnin_rt': sdnin_rt,
				})
		except (ValueError, TypeError):
			continue

	# 급증률 높은 순 정렬 후 count개 반환
	candidates.sort(key=lambda x: x['sdnin_rt'], reverse=True)
	return candidates[:count]


# 거래량상위요청 (ka10030)
# 당일 거래량 상위 종목 반환
def fn_ka10030(count=20, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/rkinfo'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10030',
	}

	params = {
		'mrkt_tp':        '000',  # 전체
		'sort_tp':        '1',    # 거래량
		'mang_stk_incls': '4',    # 관리종목, 우선주제외
		'crd_tp':         '0',    # 전체
		'trde_qty_tp':    '100',  # 10만주 이상
		'pric_tp':        '2',    # 1천원 이상
		'trde_prica_tp':  '100',  # 10억원 이상
		'mrkt_open_tp':   '1',    # 장중
		'stex_tp':        '1',    # KRX
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10030] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10030] 요청 실패: {e}')
				return []
			log.warning(f'[ka10030] 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return []

	log.debug(f'[ka10030] status={response.status_code}')
	log.debug(f'[ka10030] body={json.dumps(data, ensure_ascii=False)}')

	raw_list = data.get('trde_qty_upper', [])
	if not raw_list:
		return []

	candidates = []
	for item in raw_list:
		try:
			stk_cd   = item.get('stk_cd', '').replace('A', '')
			stk_nm   = item.get('stk_nm', '')
			flu_rt   = float(item.get('flu_rt',    '0').replace('+', '').replace(',', ''))
			trde_qty = float(item.get('trde_qty',  '0').replace(',', '') or '0')
			trde_amt = float(item.get('trde_prica','0').replace(',', '') or '0')  # 백만원 단위

			candidates.append({
				'stk_cd':   stk_cd,
				'stk_nm':   stk_nm,
				'flu_rt':   flu_rt,
				'trde_qty': trde_qty,
				'trde_amt': trde_amt,
			})
		except (ValueError, TypeError):
			continue

	return candidates[:count]


# 전일대비등락률상위요청 (ka10027)
# 당일 등락률 상위 종목 반환
def fn_ka10027(count=20, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/rkinfo'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10027',
	}

	params = {
		'mrkt_tp':        '000',  # 전체
		'mang_stk_incls': '0',    # 관리종목 미포함
		'stex_tp':        '1',    # KRX
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10027] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10027] 요청 실패: {e}')
				return []
			log.warning(f'[ka10027] 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return []

	log.debug(f'[ka10027] status={response.status_code}')
	log.debug(f'[ka10027] body={json.dumps(data, ensure_ascii=False)}')

	raw_list = data.get('pred_pre_flu_rt_upper', [])
	if not raw_list:
		return []

	candidates = []
	for item in raw_list:
		try:
			stk_cd      = item.get('stk_cd', '').replace('A', '')
			stk_nm      = item.get('stk_nm', '')
			flu_rt      = float(item.get('flu_rt',        '0').replace('+', '').replace(',', ''))
			now_trde_qty = float(item.get('now_trde_qty', '0').replace(',', '') or '0')
			candidates.append({'stk_cd': stk_cd, 'stk_nm': stk_nm, 'flu_rt': flu_rt, 'now_trde_qty': now_trde_qty})
		except (ValueError, TypeError):
			continue

	return candidates[:count]


# 예상체결등락률상위요청 (ka10029)
# 예상체결 기준 등락률 상위 종목 반환 (장 시작 전/직후 유효)
def fn_ka10029(count=20, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/rkinfo'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10029',
	}

	params = {
		'mrkt_tp':        '000',  # 전체
		'mang_stk_incls': '0',    # 관리종목 미포함
		'stex_tp':        '1',    # KRX
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10029] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10029] 요청 실패: {e}')
				return []
			log.warning(f'[ka10029] 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return []

	log.debug(f'[ka10029] status={response.status_code}')
	log.debug(f'[ka10029] body={json.dumps(data, ensure_ascii=False)}')

	raw_list = data.get('exp_cntr_flu_rt_upper', [])
	if not raw_list:
		return []

	candidates = []
	for item in raw_list:
		try:
			stk_cd       = item.get('stk_cd', '').replace('A', '')
			stk_nm       = item.get('stk_nm', '')
			flu_rt       = float(item.get('flu_rt',       '0').replace('+', '').replace(',', ''))
			exp_cntr_qty = float(item.get('exp_cntr_qty', '0').replace(',', '') or '0')
			candidates.append({'stk_cd': stk_cd, 'stk_nm': stk_nm, 'flu_rt': flu_rt, 'exp_cntr_qty': exp_cntr_qty})
		except (ValueError, TypeError):
			continue

	return candidates[:count]


# 거래대금상위요청 (ka10032)
# 당일 거래대금 상위 종목 반환
def fn_ka10032(count=20, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/rkinfo'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10032',
	}

	params = {
		'mrkt_tp':        '000',  # 전체 (코스피+코스닥)
		'mang_stk_incls': '0',    # 관리종목 미포함
		'stex_tp':        '1',    # KRX
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10032] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10032] 요청 실패: {e}')
				return []
			log.warning(f'[ka10032] 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return []

	log.debug(f'[ka10032] status={response.status_code}')
	log.debug(f'[ka10032] body={json.dumps(data, ensure_ascii=False)}')

	raw_list = data.get('trde_prica_upper', [])
	if not raw_list:
		return []

	candidates = []
	for item in raw_list:
		try:
			stk_cd     = item.get('stk_cd', '').replace('A', '')
			stk_nm     = item.get('stk_nm', '')
			flu_rt     = float(item.get('flu_rt', '0').replace('+', '').replace(',', ''))
			trde_prica = float(item.get('trde_prica', '0').replace(',', '') or '0')

			# 필터: 급락 종목 제외 (등락률 -3% 이하 제외), 최소 거래대금 100억 (단위: 백만원)
			if flu_rt >= -3.0 and trde_prica >= 10000:
				candidates.append({
					'stk_cd':     stk_cd,
					'stk_nm':     stk_nm,
					'flu_rt':     flu_rt,
					'trde_prica': trde_prica,
				})
		except (ValueError, TypeError):
			continue

	return candidates[:count]
