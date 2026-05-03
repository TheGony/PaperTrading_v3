import requests
import json
import datetime
import time
import pandas as pd
from util.config import host_url
from util.logger import get_logger

# 계좌평가현황요청 (kt00004)
def fn_kt00004(print_df=False, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/acnt'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'kt00004',
	}

	params = {
		'qry_tp': '0',
		'dmst_stex_tp': 'KRX',
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = 3 * (2 ** attempt)  # 3, 6, 12초
				log.warning(f'[kt00004] 429 Rate Limit — {wait}초 대기 ({attempt + 1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
		except Exception as e:
			log.error(f'[kt00004] 요청 실패: {e}')
			return None, '0', '0'

		return_code = data.get('return_code', 0)
		if return_code != 0:
			log.error(f'[kt00004] API 오류: code={return_code} msg={data.get("return_msg", "")}')
			return None, '0', '0'

		aset_evlt_amt = data.get('aset_evlt_amt', '0') or '0'
		entr = data.get('entr', '0') or '0'
		stk_acnt_evlt_prst = data.get('stk_acnt_evlt_prst', [])
		if not stk_acnt_evlt_prst:
			return [], aset_evlt_amt, entr

		if print_df:
			df = pd.DataFrame(stk_acnt_evlt_prst)[['stk_cd', 'stk_nm', 'pl_rt', 'rmnd_qty']]
			pd.set_option('display.unicode.east_asian_width', True)
			print(df.to_string(index=False))

		return stk_acnt_evlt_prst, aset_evlt_amt, entr

	log.error('[kt00004] 429 재시도 3회 초과 — None 반환')
	return None, '0', '0'


# 당일 추정예탁자산 조회 (kt00002)
def fn_kt00002(token=None):
	"""반환: (prsm_dpst_aset_amt, entr) = (추정예탁자산, 예수금)"""
	log = get_logger()
	today = datetime.datetime.now().strftime('%Y%m%d')

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': 'N',
		'next-key': '',
		'api-id': 'kt00002',
	}
	body = {
		'start_dt': today,
		'end_dt': today,
	}

	for attempt in range(3):
		try:
			response = requests.post(host_url + '/api/dostk/acnt', headers=headers, json=body, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[kt00002] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			log.error(f'[kt00002] 요청 실패: {e}')
			return '0', '0'
	else:
		log.error('[kt00002] 429 재시도 3회 초과')
		return '0', '0'

	log.debug(f'[kt00002] status={response.status_code} body={json.dumps(data, ensure_ascii=False)}')

	rows = data.get('daly_prsm_dpst_aset_amt_prst', [])
	if not rows:
		log.warning('[kt00002] 추정예탁자산 데이터 없음')
		return '0', '0'

	row = rows[0]
	prsm = row.get('prsm_dpst_aset_amt', '0') or '0'
	entr = row.get('entr', '0') or '0'
	return prsm, entr


# 예수금상세현황요청 (kt00001)
def fn_kt00001(cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/acnt'

	params = {
		'qry_tp': '3', # 조회구분 3:추정조회, 2:일반조회
	}

	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'kt00001', # TR명
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[kt00001] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			entry = data.get('entr')
			log.debug(f'[kt00001] 예수금={entry}')
			return entry
		except Exception as e:
			log.error(f'[kt00001] 요청 실패: {e}')
			return None

	log.error('[kt00001] 429 재시도 3회 초과')
	return None


# 일별잔고수익률 (ka01690)
def fn_ka01690(qry_dt, cont_yn='N', next_key='', token=None):
	url = host_url + '/api/dostk/acnt'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'ka01690', # TR명
	}

	params = {
		'qry_dt': qry_dt, # 조회일자 YYYYMMDD
	}

	try:
		response = requests.post(url, headers=headers, json=params, timeout=10)
		response.raise_for_status()
		data = response.json()
	except Exception as e:
		print(f'[ka01690] 요청 실패: {e}')
		return None

	print('Code:', response.status_code)
	print('Header:', json.dumps({key: response.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
	print('Body:', json.dumps(data, indent=4, ensure_ascii=False))

	return data


# 일자별종목별실현손익요청_일자 (ka10072)
def fn_ka10072(strt_dt, stk_cd='', cont_yn='N', next_key='', token=None):
	url = host_url + '/api/dostk/acnt'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'ka10072', # TR명
	}

	params = {
		'stk_cd': stk_cd if stk_cd else '', # 종목코드 (빈 값이면 전체)
		'strt_dt': strt_dt, # 시작일자 YYYYMMDD
	}

	try:
		response = requests.post(url, headers=headers, json=params, timeout=10)
		response.raise_for_status()
		data = response.json()
	except Exception as e:
		print(f'[ka10072] 요청 실패: {e}')
		return None

	print('Code:', response.status_code)
	print('Header:', json.dumps({key: response.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
	print('Body:', json.dumps(data, indent=4, ensure_ascii=False))

	return data
