# parsers/autoru.py — парсер Auto.ru через curl_cffi (TLS fingerprint Chrome 124).
# curl_cffi обходит Yandex SmartCaptcha лучше requests и быстрее Playwright.

import re
import time
import random
import logging

import requests as _requests
from bs4 import BeautifulSoup

from config import load_config, RUNTIME_CONFIG
from database import is_seen
from utils.headers import get_random_headers

SOURCE = "autoru"


def parse() -> list:
    """Парсит Auto.ru через curl_cffi с TLS fingerprint Chrome 124."""
    load_config()
    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError:
        logging.error("Auto.ru: curl_cffi не установлен — pip install curl_cffi")
        return []

    cookies = RUNTIME_CONFIG.get("AUTORU_COOKIES", {}) or {}
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)

    session = CurlSession(impersonate="chrome124")
    for name, value in cookies.items():
        if value:
            session.cookies.set(name, str(value), domain=".auto.ru")

    headers = get_random_headers(referer="https://auto.ru/")
    url = f"https://auto.ru/moskva/cars/used/?price_to={max_price}&seller_group=PRIVATE"

    time.sleep(random.uniform(3, 7))

    try:
        response = session.get(url, headers=headers, timeout=20)
    except Exception as e:
        logging.error(f"Auto.ru запрос: {e}")
        return []

    if response.status_code == 429:
        logging.warning("Auto.ru: 429 — пауза 90 сек")
        time.sleep(90)
        return []

    if response.status_code == 403:
        logging.warning("Auto.ru: 403 — куки устарели. Запусти: python utils/cookie_extractor.py")
        cnt = RUNTIME_CONFIG.get("AUTORU_EMPTY_CYCLES", 0) + 1
        RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = cnt
        if cnt >= 5:
            RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = 0
            _notify_stale_cookies()
        return []

    if response.status_code != 200:
        logging.error(f"Auto.ru: статус {response.status_code}")
        return []

    RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = 0

    soup = BeautifulSoup(response.text, "lxml")
    items = (
        soup.select("div.ListingItem")
        or soup.select("article[class*='listing-item']")
        or soup.select("div[class*='ListingItem']")
    )
    logging.info(f"Auto.ru: найдено {len(items)} карточек")

    results = []
    for item in items[:25]:
        try:
            listing = _parse_item(item)
            if listing is None:
                continue
            if listing["price"] <= 0 or listing["price"] > max_price:
                continue
            if is_seen(listing["listing_id"], SOURCE):
                continue
            results.append(listing)
        except Exception as e:
            logging.debug(f"Auto.ru item: {e}")

    # Счётчик пустых циклов при пустом ответе с кодом 200
    if not results:
        cnt = RUNTIME_CONFIG.get("AUTORU_EMPTY_CYCLES", 0) + 1
        RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = cnt
        if cnt >= 5:
            RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = 0
            _notify_stale_cookies()
    else:
        RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = 0

    logging.info(f"Auto.ru: {len(results)} новых объявлений")
    return results


def _parse_item(item) -> dict | None:
    """Разобрать карточку объявления Auto.ru из BeautifulSoup."""
    try:
        link = (
            item.select_one("a[href*='auto.ru']")
            or item.select_one("a[class*='link']")
        )
        if not link:
            return None

        href = link.get("href", "")
        id_match = re.search(r"/(\d+)-", href) or re.search(r"(\d{8,})", href)
        listing_id = id_match.group(1) if id_match else None
        if not listing_id:
            return None

        title_el = item.select_one("[class*='name']") or item.select_one("[class*='title']")
        title = title_el.get_text(strip=True)[:100] if title_el else ""

        price_el = item.select_one("[class*='price']")
        price_text = price_el.get_text() if price_el else "0"
        digits = re.sub(r"\D", "", price_text)
        price = int(digits) if digits else 0

        text = item.get_text(separator=" ")
        year_match = re.search(r"\b(199\d|200\d|201\d|202[0-6])\b", text)
        year = int(year_match.group(1)) if year_match else 0

        km_match = re.search(r"(\d[\d\s]+)\s*км", text)
        mileage = int(re.sub(r"\D", "", km_match.group(1))) if km_match else 0

        listing_url = href if href.startswith("http") else f"https:{href}"

        # Пропускаем дилеров
        text_lower = text.lower()
        if any(w in text_lower for w in ("дилер", "dealer", "автосалон", "certified")):
            return None

        return {
            "listing_id":       listing_id,
            "source":           SOURCE,
            "title":            title,
            "price":            price,
            "year":             year,
            "mileage":          mileage,
            "city":             "Москва",
            "description":      text[:600],
            "photo_count":      len(item.select("img")),
            "photo_urls":       [],
            "seller_ads_count": 0,
            "seller_id":        "",
            "published_at":     "",
            "listing_url":      listing_url,
            "is_regional":      False,
        }
    except Exception as e:
        logging.debug(f"parse_autoru_item: {e}")
        return None


def _notify_stale_cookies():
    """Отправить предупреждение в Telegram об устаревших куках Auto.ru."""
    token = RUNTIME_CONFIG.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = RUNTIME_CONFIG.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    text = (
        "Auto.ru: 5 циклов без объявлений.\n"
        "Куки устарели. Обнови командой:\n"
        "python utils/cookie_extractor.py\n"
        "(закрой Chrome перед запуском)"
    )
    try:
        _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        logging.warning("Auto.ru: отправлено предупреждение об устаревших куках")
    except Exception as e:
        logging.error(f"Auto.ru: не удалось отправить предупреждение: {e}")
