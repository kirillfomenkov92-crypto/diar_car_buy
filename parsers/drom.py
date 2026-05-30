"""
parsers/drom.py — парсер объявлений о продаже авто с Drom.ru.

Логика аналогична парсеру Avito: requests + BeautifulSoup, ротация
User-Agent, случайные задержки, фильтрация по цене и городу. Все ошибки
перехватываются и логируются, наружу исключения не выбрасываются.
"""

import random
import time
import logging
import re

import requests
from bs4 import BeautifulSoup

from config import load_config

SOURCE = "drom"

# Базовый URL поиска по Москве. Шаблон — реальные параметры могут отличаться.
BASE_URL = "https://moscow.drom.ru/auto/all/"

# Список User-Agent для ротации (минимум 5 строк)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]


def _headers():
    """Сформировать HTTP-заголовки со случайным User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _sleep():
    """Случайная пауза 2–5 секунд между запросами."""
    time.sleep(random.uniform(2, 5))


def _parse_price(text):
    """Извлечь целое число рублей из строки, вернуть 0 при неудаче."""
    try:
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else 0
    except Exception:
        return 0


def _extract_year(text):
    """Найти год выпуска (1980–2030) в тексте."""
    try:
        for m in re.findall(r"(19[89]\d|20[0-3]\d)", text):
            return int(m)
    except Exception:
        pass
    return 0


def _extract_mileage(text):
    """Найти пробег в км в тексте, вернуть 0 при неудаче."""
    try:
        m = re.search(r"([\d\s]+)\s*км", text)
        if m:
            return _parse_price(m.group(1))
    except Exception:
        pass
    return 0


def _passes_filters(listing, cfg):
    """Проверить объявление по фильтрам цены и города из конфигурации."""
    max_price = cfg.get("MAX_PRICE", 140000)
    if listing["price"] <= 0 or listing["price"] > max_price:
        return False
    cities = cfg.get("CITIES", [])
    if cities:
        city = (listing.get("city") or "").lower()
        if not any(c.lower() in city for c in cities):
            return False
    return True


def _parse_card(card):
    """
    Разобрать один блок объявления Drom в dict.

    Возвращает dict или None при ошибке. Селекторы выбраны мягко, так как
    разметка Drom может меняться.
    """
    try:
        link = card.find("a", href=True)
        listing_url = link.get("href") if link else ""
        if listing_url and not listing_url.startswith("http"):
            listing_url = f"https://moscow.drom.ru{listing_url}"

        # ID объявления вытаскиваем из URL
        m = re.search(r"/(\d+)\.html", listing_url)
        listing_id = m.group(1) if m else listing_url

        title_tag = card.find("h3") or card.find(attrs={"data-ftid": "bull_title"})
        title = title_tag.get_text(strip=True) if title_tag else ""

        price_tag = card.find(attrs={"data-ftid": "bull_price"}) or card.find(
            class_=re.compile("price")
        )
        price = _parse_price(price_tag.get_text()) if price_tag else 0

        desc_tag = card.find(attrs={"data-ftid": "component_inline-bull-description"})
        description = desc_tag.get_text(" ", strip=True) if desc_tag else title

        photos = card.find_all("img")
        photo_urls = [img.get("src") for img in photos if img.get("src")]
        photo_count = len(photo_urls)

        year = _extract_year(title + " " + description)
        mileage = _extract_mileage(description)

        return {
            "listing_id": str(listing_id),
            "source": SOURCE,
            "title": title,
            "price": price,
            "year": year,
            "mileage": mileage,
            "city": "Москва",
            "description": description,
            "photo_count": photo_count,
            "photo_urls": photo_urls,
            "seller_ads_count": 0,
            "listing_url": listing_url,
        }
    except Exception as e:
        logging.error(f"Drom: ошибка разбора карточки: {e}")
        return None


def parse():
    """
    Основная точка входа парсера Drom.

    Возвращает список dict с объявлениями, прошедшими фильтры.
    Никогда не выбрасывает исключения наружу.
    """
    cfg = load_config()
    results = []
    try:
        _sleep()
        resp = requests.get(BASE_URL, headers=_headers(), timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        cards = soup.find_all(attrs={"data-ftid": "bulls-list_bull"})
        if not cards:
            cards = soup.find_all("a", attrs={"data-ftid": "bull_title"})

        for card in cards:
            listing = _parse_card(card)
            if listing and _passes_filters(listing, cfg):
                results.append(listing)

        logging.info(f"Drom: собрано {len(results)} объявлений после фильтрации")
    except requests.RequestException as e:
        logging.error(f"Drom: сетевая ошибка: {e}")
    except Exception as e:
        logging.error(f"Drom: непредвиденная ошибка: {e}")

    return results
