import requests
import json
import time
from util.config import host_url
from util.logger import get_logger

# 외국인기관매매상위요청 (ka90009)
# 당일 외인/기관 순매수 상위 종목코드 set 반환
def fn_ka90009(cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/rkinfo'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka90009',
	}

	params = {
		'mrkt_tp':    '000',  # 전체 (코스피+코스닥)
		'amt_qty_tp': '1',    # 금액(천만)
		'qry_dt_tp':  '1',    # 조회일자 포함
		'date':       '',     
		'stex_tp':    '1',    # KRX
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka90009] 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka90009] 요청 실패: {e}')
				return set()
			log.warning(f'[ka90009] 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return set()

	log.debug(f'[ka90009] status={response.status_code} body={json.dumps(data, ensure_ascii=False)}')

	rows = data.get('frgnr_orgn_trde_upper', [])
	if not rows:
		log.warning('[ka90009] 외인/기관 데이터 없음')
		return set()

	buy_stocks = set()
	for row in rows:
		for_cd  = row.get('for_netprps_stk_cd', '').replace('A', '').strip()
		orgn_cd = row.get('orgn_netprps_stk_cd', '').replace('A', '').strip()
		if for_cd:
			buy_stocks.add(for_cd)
		if orgn_cd:
			buy_stocks.add(orgn_cd)

	return buy_stocks
