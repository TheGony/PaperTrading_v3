import datetime

class MarketHour:
	"""장 시간 관련 상수 및 메서드를 관리하는 클래스"""

	# 장 시작/종료 시간 상수
	MARKET_START_HOUR = 9
	MARKET_START_MINUTE = 0
	MARKET_END_HOUR = 15
	MARKET_END_MINUTE = 30

	# 매수/종목선정 종료 시각
	ENTRY_END_HOUR   = 15  # 15:20 이후 진입 차단
	ENTRY_END_MINUTE = 20
	
	@staticmethod
	def _is_weekday():
		"""평일인지 확인합니다."""
		return datetime.datetime.now().weekday() < 5
	
	@staticmethod
	def _get_market_time(hour, minute):
		"""장 시간을 반환합니다."""
		now = datetime.datetime.now()
		return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
	
	@classmethod
	def is_market_open_time(cls):
		"""현재 시간이 장 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_open = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		market_close = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		return market_open <= now <= market_close
	
	@classmethod
	def is_market_start_time(cls):
		"""현재 시간이 장 시작 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_start = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		return now >= market_start and (now - market_start).seconds < 60  # 1분 이내
	
	@classmethod
	def is_market_end_time(cls):
		"""현재 시간이 장 종료 시간인지 확인합니다."""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		market_end = cls._get_market_time(cls.MARKET_END_HOUR, cls.MARKET_END_MINUTE)
		return now >= market_end and (now - market_end).seconds < 60  # 1분 이내

	@classmethod
	def is_entry_allowed(cls):
		"""현재 시간이 매수/종목선정 허용 구간인지 확인 (15:20 이후 차단)"""
		if not cls._is_weekday():
			return False
		now = datetime.datetime.now()
		open_    = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		entry_end = cls._get_market_time(cls.ENTRY_END_HOUR, cls.ENTRY_END_MINUTE)
		return open_ <= now < entry_end

