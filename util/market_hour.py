import datetime

class MarketHour:
	"""장 시간 관련 상수 및 메서드를 관리하는 클래스"""

	# 장 시작/종료 시간 상수
	MARKET_START_HOUR = 9
	MARKET_START_MINUTE = 0
	MARKET_END_HOUR = 15
	MARKET_END_MINUTE = 30

	# 구간 경계
	EARLY_END_HOUR   = 9   # 장 초반 종료: 09:30
	EARLY_END_MINUTE = 30
	LATE_START_HOUR   = 15  # 장 후반 시작: 15:00
	LATE_START_MINUTE = 0

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

	@classmethod
	def get_market_phase(cls):
		"""현재 장 구간을 반환합니다: 'early' | 'mid' | 'late' | 'closed'"""
		if not cls._is_weekday():
			return 'closed'
		now = datetime.datetime.now()
		open_  = cls._get_market_time(cls.MARKET_START_HOUR, cls.MARKET_START_MINUTE)
		early_end  = cls._get_market_time(cls.EARLY_END_HOUR,  cls.EARLY_END_MINUTE)
		late_start = cls._get_market_time(cls.LATE_START_HOUR, cls.LATE_START_MINUTE)
		close_ = cls._get_market_time(cls.MARKET_END_HOUR,  cls.MARKET_END_MINUTE)
		if now < open_ or now > close_:
			return 'closed'
		if now < early_end:
			return 'early'
		if now < late_start:
			return 'mid'
		return 'late'
