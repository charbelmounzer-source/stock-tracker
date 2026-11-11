"""One small HTTP client shared by every source: rate limit, retries, timeouts."""
import time

import requests

RETRY_STATUSES = (429, 500, 502, 503, 504)


class Client:
    def __init__(self, headers=None, max_per_second=5.0, retries=4, timeout=30,
                 retry_statuses=RETRY_STATUSES, session=None, sleep=time.sleep, clock=time.monotonic):
        self.session = session or requests.Session()
        self.session.headers.update(headers or {})
        self.min_interval = 1.0 / max_per_second
        self.retries = retries
        self.timeout = timeout
        self.retry_statuses = retry_statuses
        self._sleep = sleep
        self._clock = clock
        self._last = None

    def _throttle(self):
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get(self, url, params=None):
        """GET with exponential backoff. Raises requests.HTTPError once retries run out."""
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == self.retries:
                    raise
                self._sleep(2 ** attempt)
                continue
            if response.status_code in self.retry_statuses and attempt < self.retries:
                retry_after = response.headers.get("Retry-After", "")
                self._sleep(float(retry_after) if retry_after.isdigit() else 2 ** attempt)
                continue
            if response.status_code >= 400:
                raise requests.HTTPError(
                    f"{response.status_code} for {url}: {response.text[:200]}", response=response)
            return response

    def get_json(self, url, params=None):
        return self.get(url, params).json()
