"""utils/headers.py — пул User-Agent строк и генератор HTTP-заголовков."""

import random

# 25 реальных User-Agent строк
USER_AGENTS: list[str] = [
    # Chrome 120-124 на Windows 10/11 (10 штук)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.185 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.234 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome 120-124 на macOS (5 штук)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.122 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox 121-124 на Windows (5 штук)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox 121-124 на macOS (3 штуки)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.6; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Chrome на Android (2 штуки)
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Samsung Galaxy S23) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.40 Mobile Safari/537.36",
]

ACCEPT_LANGUAGES: list[str] = [
    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "ru-RU,ru;q=0.9,en;q=0.8",
    "ru,en-US;q=0.9,en;q=0.8",
    "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "ru-RU,ru;q=0.9,en-GB;q=0.8,en;q=0.7",
    "ru;q=1.0,en-US;q=0.9,en;q=0.8",
    "ru-RU,ru;q=0.7,en;q=0.3",
    "ru-RU,ru;q=0.9",
]

_MOBILE_MARKERS = ("Android", "Mobile", "iPhone")


def _is_mobile(ua: str) -> bool:
    return any(m in ua for m in _MOBILE_MARKERS)


def get_random_headers(referer: str = None) -> dict:
    """Возвращает dict со случайными браузерными заголовками.

    Args:
        referer: если передан, добавляется поле Referer и Sec-Fetch-Site=same-origin.
    """
    ua = random.choice(USER_AGENTS)
    headers: dict[str, str] = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    if not _is_mobile(ua):
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "same-origin" if referer else "none"
        headers["Sec-Fetch-User"] = "?1"
        headers["Sec-CH-UA-Mobile"] = "?0"

    if referer:
        headers["Referer"] = referer

    if random.random() < 0.5:
        headers["Cache-Control"] = random.choice(["no-cache", "max-age=0"])

    return headers


def get_avito_headers() -> dict:
    """Заголовки для запросов к Avito."""
    headers = get_random_headers(referer="https://www.avito.ru/")
    headers["Origin"] = "https://www.avito.ru"
    return headers


def get_drom_headers() -> dict:
    """Заголовки для запросов к Drom."""
    return get_random_headers(referer="https://auto.drom.ru/")
