import time
import random
import requests
import logging
from fake_useragent import UserAgent

class ScraperConfig:
    def __init__(self, retry_delay: float = 30.0, max_retries: int = 3):
        self.retry_delay = retry_delay
        self.max_retries = max_retries

class BaseScraper:
    def __init__(self, name: str, config: ScraperConfig = None):
        self.logger = logging.getLogger(name)
        self.config = config or ScraperConfig()
        self.session = requests.Session()
        self.ua = UserAgent()
        self.update_headers()
        self.consecutive_429_count = 0

    def update_headers(self):
        """更新請求頭，使用隨機 User-Agent"""
        try:
            user_agent = self.ua.random
        except Exception:
             # Fallback list
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5.2 Safari/605.1.15",
            ]
            user_agent = random.choice(user_agents)

        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.logger.debug(f"Updated User-Agent: {user_agent}")

    def handle_429_error(self):
        """處理429錯誤"""
        self.consecutive_429_count += 1
        wait_time = self.config.retry_delay * (2 ** min(self.consecutive_429_count - 1, 5))
        self.logger.warning(f"檢測到429錯誤 (請求過多)，等待 {wait_time:.1f} 秒")
        self.update_headers()
        time.sleep(wait_time)

    def make_request(self, method: str, url: str, **kwargs):
        """發送請求並處理重試邏輯"""
        for retry in range(self.config.max_retries):
            try:
                response = self.session.request(method, url, timeout=30, **kwargs)
                
                if response.status_code == 429:
                    self.handle_429_error()
                    continue
                
                self.consecutive_429_count = 0
                return response
            
            except requests.RequestException as e:
                self.logger.warning(f"請求失敗 ({retry+1}/{self.config.max_retries}): {e}")
                if retry < self.config.max_retries - 1:
                    time.sleep(random.uniform(2, 5))
                else:
                    self.logger.error(f"達到最大重試次數: {url}")
                    raise

    def get(self, url: str, **kwargs):
        return self.make_request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.make_request("POST", url, **kwargs)
