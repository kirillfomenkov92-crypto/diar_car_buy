# parsers/youla.py — парсер Youla.ru для Diar Car Buy AI v3.0.
# Меньше конкуренции — часто те же владельцы продают дешевле.

import random
import time
import re
import logging

from bs4 import BeautifulSoup

from config import load_config
from utils.retry_session import get_session

SOURCE = "youla"
BASE_URL = "https://youla.ru/all/auto"

_session = get_session("youla")


def _sleep():
    time.sleep(random.uniform(3, 8))


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
    """Разобрать карточку объявления Youla."""
    try:
        link = card.find("a", href=True)
        href = link.get("href") if link else ""
        listing_url = href if href.startswith("http") else f"https://youla.ru{href}"
        m = re.search(r"/([a-f0-9]{24})", href)
        listing_id = m.group(1) if m else href or ""

        title_tag = card.find(class_=re.compile(r"name|title", re.I)) or card.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else ""

        price_tag = card.find(class_=re.compile(r"price", re.I))
        price = _parse_price(price_tag.get_text()) if price_tag else 0

        desc_tag = card.find(class_=re.compile(r"description|params", re.I))
        description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

        photos = card.find_all("img")
        photo_urls = [img.get("src") for img in photos if img.get("src")]

        return {
            "listing_id": str(listing_id) if listing_id else href,
            "source": SOURCE,
            "title": title,
            "price": price,
            "year": _extract_year(title + " " + description),
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
        logging.error(f"Youla: ошибка разбора карточки: {e}")
        return None


def parse() -> list:
    """Главная точка входа: парсинг Youla.ru."""
    cfg = load_config()
    max_price = cfg.get("MAX_PRICE", 140000)
    url = f"{BASE_URL}?attributes%5Bprice%5D%5Bto%5D={max_price}"
    results = []

    try:
        _sleep()
        resp = _session.get(url, timeout=25)
        if resp is None:
            return results
        soup = BeautifulSoup(resp.text, "lxml")

        # Карточки объявлений
        cards = (
            soup.find_all(attrs={"data-test-id": "product-item"})
            or soup.find_all(class_=re.compile(r"ProductItem|product-item|listing-item", re.I))
            or soup.find_all("article")
        )

        for card in cards:
            listing = _parse_card(card)
            if listing and 0 < listing["price"] <= max_price:
                results.append(listing)

        logging.info(f"Youla: получено {len(results)} объявлений")

    except Exception as e:
        logging.error(f"Youla: непредвиденная ошибка: {e}")

    return results
