# parsers/avito_rss.py — парсер Avito через curl_cffi (Firefox TLS fingerprint) + BeautifulSoup.
# Обходит капчу без Playwright: правильный TLS fingerprint + куки из реального Firefox.

import logging
import random
import re
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from config import RUNTIME_CONFIG, load_config
from database import is_seen

SOURCE = "avito"
_BASE_URL = "https://www.avito.ru/moskva/avtomobili"

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.ru/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
}

_CAPTCHA_PHRASES = [
    "капча", "автоматические запросы",
    "подозрительная активность", "слишком много запросов",
    "access denied", "доступ запрещён",
]


def _browser_cookies() -> dict:
    try:
        import browser_cookie3
        for loader in [browser_cookie3.firefox, browser_cookie3.chrome]:
            try:
                cj = loader(domain_name=".avito.ru")
                cookies = {c.name: c.value for c in cj if "avito.ru" in c.domain}
                if cookies:
                    return cookies
            except Exception:
                continue
    except Exception:
        pass
    return {}


def _parse_price(text: str) -> int:
    try:
        m = re.search(r"([\d][\d\s]{1,8}[\d])\s*[₽р]", str(text))
        if m:
            return int(re.sub(r"\s", "", m.group(1)))
        digits = re.sub(r"[^\d]", "", str(text))
        return int(digits) if digits else 0
    except Exception:
        return 0


def _extract_year(text: str) -> int:
    m = re.search(r"\b(199\d|200\d|201\d|202\d)\b", text)
    return int(m.group(1)) if m else 0


def _extract_mileage(text: str) -> int:
    m = re.search(r"(\d[\d\s]{1,6})\s*(?:тыс\.?\s*)?км", text.lower())
    if m:
        val = int(re.sub(r"\s", "", m.group(1)))
        return val * 1000 if val < 1000 else val
    return 0


def parse() -> list:
    load_config()
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)
    url = f"{_BASE_URL}?s=104&pmax={max_price}"

    cookies = _browser_cookies()
    logging.info(f"Avito curl_cffi: {len(cookies)} куки из браузера")

    blocked_until = RUNTIME_CONFIG.get("AVITO_RSS_BLOCKED_UNTIL", 0)
    if time.time() < blocked_until:
        mins = int((blocked_until - time.time()) / 60)
        logging.info(f"Avito curl_cffi: пауза ещё {mins} мин")
        return []

    try:
        session = cffi_requests.Session(impersonate="firefox133")
        # прогрев сессии — заходим на главную как обычный браузер
        session.get(
            "https://www.avito.ru/",
            headers={**_HEADERS, "Referer": "https://www.google.ru/"},
            cookies=cookies,
            timeout=15,
        )
        time.sleep(random.uniform(2, 4))

        resp = session.get(
            url,
            headers={**_HEADERS, "Referer": "https://www.avito.ru/"},
            cookies=cookies,
            timeout=30,
        )
    except Exception as e:
        logging.error(f"Avito curl_cffi: ошибка запроса: {e}")
        return []

    if resp.status_code == 403:
        logging.warning("Avito curl_cffi: 403 — IP временно заблокирован, пауза 15 мин")
        RUNTIME_CONFIG["AVITO_RSS_BLOCKED_UNTIL"] = time.time() + 900
        return []
    if resp.status_code == 429:
        logging.warning("Avito curl_cffi: 429 — слишком много запросов, пауза 20 мин")
        RUNTIME_CONFIG["AVITO_RSS_BLOCKED_UNTIL"] = time.time() + 1200
        return []
    if resp.status_code != 200:
        logging.warning(f"Avito curl_cffi: HTTP {resp.status_code}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.find_all(attrs={"data-marker": "item"})
    logging.info(f"Avito curl_cffi: найдено {len(cards)} карточек")

    if not cards:
        low = resp.text.lower()
        if any(p in low for p in _CAPTCHA_PHRASES):
            RUNTIME_CONFIG["AVITO_RSS_BLOCKED_UNTIL"] = time.time() + 1800
            logging.warning("Avito curl_cffi: капча — пауза 30 минут")
        else:
            logging.warning("Avito curl_cffi: карточки не найдены — возможно изменился HTML")
        return []

    results = []
    for card in cards:
        try:
            listing_id = card.get("data-item-id", "")
            if not listing_id or is_seen(listing_id, SOURCE):
                continue

            title_el = card.find(attrs={"data-marker": "item-title"})
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if not href:
                continue
            listing_url = href if href.startswith("http") else f"https://www.avito.ru{href}"

            price_meta = card.find("meta", itemprop="price")
            if price_meta:
                price = _parse_price(price_meta.get("content", ""))
            else:
                price_el = card.find(attrs={"data-marker": "item-price"})
                price = _parse_price(price_el.get_text() if price_el else "")

            if price <= 0 or price > max_price:
                continue

            desc_el = card.find(attrs={"data-marker": "item-description"}) or \
                      card.find(class_=re.compile(r"item-description|itemDescription"))
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            date_el = card.find(attrs={"data-marker": "item-date"})
            published_at = date_el.get_text(strip=True) if date_el else ""

            photo_urls = [
                img["src"] for img in card.find_all("img", src=True)
                if img.get("src", "").startswith("http")
            ]

            combined = f"{title} {description}"
            results.append({
                "listing_id": str(listing_id),
                "source": SOURCE,
                "title": title,
                "price": price,
                "year": _extract_year(combined),
                "mileage": _extract_mileage(combined),
                "city": "Москва",
                "description": description[:600],
                "photo_count": len(photo_urls),
                "photo_urls": photo_urls,
                "seller_ads_count": 0,
                "seller_id": "",
                "published_at": published_at,
                "listing_url": listing_url,
                "is_regional": False,
            })
        except Exception as e:
            logging.debug(f"Avito curl_cffi: ошибка карточки: {e}")

    logging.info(f"Avito curl_cffi: {len(results)} новых объявлений")
    return results
