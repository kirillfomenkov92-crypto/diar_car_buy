"""utils/retry_session.py — requests.Session с exponential backoff и ротацией заголовков."""

import logging
import random
import time

import requests

from utils.headers import get_avito_headers, get_drom_headers, get_random_headers


class RetrySession:
    """requests.Session с умной обработкой ошибок и автоматической ротацией заголовков."""

    def __init__(self, source: str = "default", max_retries: int = 4):
        self.source = source
        self.max_retries = max_retries
        self.session = requests.Session()
        self.consecutive_errors = 0
        self._apply_headers()

    def _apply_headers(self):
        if self.source == "avito":
            self.session.headers.update(get_avito_headers())
        elif self.source == "drom":
            self.session.headers.update(get_drom_headers())
        else:
            self.session.headers.update(get_random_headers())

    def _rotate_headers(self):
        self.session.headers.clear()
        self._apply_headers()
        logging.info(f"[{self.source}] Заголовки ротированы")

    def _backoff(self, attempt: int, reason: str):
        base = 30 * (2 ** attempt)
        jitter = random.uniform(0, base * 0.3)
        wait = base + jitter
        logging.warning(
            f"[{self.source}] {reason} — ждём {wait:.0f}с (попытка {attempt + 1}/{self.max_retries})"
        )
        time.sleep(wait)

    def get(self, url: str, timeout: int = 15, **kwargs) -> requests.Response | None:
        """GET с автоматическими повторами по стратегии backoff."""
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=timeout, **kwargs)
                status = resp.status_code

                if 200 <= status < 300:
                    self.consecutive_errors = 0
                    return resp

                if status == 429:
                    self._backoff(attempt, "429 лимит запросов")
                    self._rotate_headers()

                elif status == 403:
                    self._rotate_headers()
                    self._backoff(attempt, "403 доступ закрыт")

                elif status in (500, 502, 503, 504):
                    self._backoff(attempt, f"{status} ошибка сервера")

                else:
                    logging.warning(f"[{self.source}] Неожиданный статус {status} для {url}")
                    return None

            except (requests.ConnectionError, requests.Timeout) as e:
                self._backoff(attempt, f"сетевая ошибка ({type(e).__name__})")

            if attempt < self.max_retries - 1:
                time.sleep(random.uniform(2, 5))

        self.consecutive_errors += 1
        if self.consecutive_errors >= 5:
            logging.error(
                f"[{self.source}] 5 подряд ошибок — источник на паузе 30 минут"
            )
            time.sleep(1800)
            self.consecutive_errors = 0

        return None


def get_session(source: str = "default") -> RetrySession:
    """Создаёт новый RetrySession для указанного источника."""
    return RetrySession(source=source)
