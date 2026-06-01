# parsers/youla.py — парсер Youla.ru для Diar Car Buy AI v3.0.
# Меньше конкуренции — часто те же владельцы продают дешевле.

import random
import time
import re
import logging
import json

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from config import load_config

SOURCE = "youla"
_API_URL = "https://youla.ru/web-api/products/?category_slug=avtomobili&price_max={max_price}&page={page}"
_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://youla.ru/",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def _sleep():
    time.sleep(random.uniform(2, 5))


def _parse_price(text: str) -> int:
    try:
        digits = "".join(ch for ch in str(text) if ch.isdigit())
        return int(digits) if digits else 0
    except Exception:
        return 0


def _extract_year(text: str) -> int:
    try:
        for m in re.findall(r"(19[89]\d|20[0-3]\d)", text):
            return int(m)
    except Exception:
        pass
    return 0


def _extract_mileage(text: str) -> int:
    try:
        m = re.search(r"([\d\s]{2,7})\s*км", text)
        if m:
            return _parse_price(m.group(1))
    except Exception:
        pass
    return 0


def _parse_card(card) -> dict | None:
    """Разобрать карточку объявления Youla из web-api HTML фрагмента."""
    try:
        listing_id = card.get("data-id", "")
        if not listing_id:
            return None

        link = card.find("a", href=True)
        href = link.get("href", "") if link else ""
        listing_url = href if href.startswith("http") else f"https://youla.ru{href}"

        title_tag = card.find(class_="product_item__title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        price_tag = card.find(class_=re.compile(r"price", re.I))
        price = _parse_price(price_tag.get_text()) if price_tag else 0

        location_tag = card.find(class_="product_item__location")
        description = location_tag.get_text(strip=True) if location_tag else ""

        photos = card.find_all("img", src=True)
        photo_urls = [img["src"] for img in photos if img.get("src","").startswith("http")]

        return {
            "listing_id": listing_id,
            "source": SOURCE,
            "title": title,
            "price": price,
            "year": _extract_year(title),
            "mileage": _extract_mileage(description),
            "city": "Москва",
            "description": description,
            "photo_count": len(photo_urls),
            "photo_urls": photo_urls,
            "seller_ads_count": 0,
            "seller_id": "",
            "published_at": "",
            "listing_url": listing_url,
            "is_regional": False,
        }
    except Exception as e:
        logging.debug(f"Youla: ошибка разбора карточки: {e}")
        return None


def parse() -> list:
    """Парсинг Youla через web-api (curl_cffi, без Playwright)."""
    logging.warning(
        "Youla: web-api и GraphQL API заблокированы без авторизации — парсер отключён. "
        "Для включения нужен OAuth-токен Youla."
    )
    return []
