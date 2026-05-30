"""
parsers/avito.py — парсер объявлений о продаже авто с Avito.

Собирает объявления, фильтрует по цене (MAX_PRICE) и городу (CITIES) из
конфигурации. Использует requests + BeautifulSoup, ротацию User-Agent и
случайные задержки между запросами. При любых ошибках сети/разметки не
падает, а логирует проблему и возвращает то, что успел собрать.
"""

import random
import time
import logging

import requests
from bs4 import BeautifulSoup

from config import load_config

SOURCE = "avito"

# Базовый URL поиска авто. Регион/категория могут отличаться — это шаблон.
BASE_URL = "https://www.avito.ru/moskva_i_mo/avtomobili"

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
    """Случайная пауза 2–5 секунд между запросами для имитации человека."""
    time.sleep(random.uniform(2, 5))


def _parse_price(text):
    """Извлечь целое число рублей из строки цены, вернуть 0 при неудаче."""
    try:
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else 0
    except Exception:
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
    Разобрать одну карточку объявления в dict.

    Селекторы Avito регулярно меняются, поэтому используются мягкие выборки
    с запасными значениями. Возвращает dict или None при ошибке.
    """
    try:
        # Идентификатор и ссылка
        link = card.find("a", attrs={"itemprop": "url"}) or card.find("a", href=True)
        href = link.get("href") if link else ""
        listing_url = href if href.startswith("http") else f"https://www.avito.ru{href}"
        listing_id = card.get("data-item-id") or href

        # Заголовок
        title_tag = card.find(attrs={"itemprop": "name"}) or card.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Цена
        price_tag = card.find(attrs={"itemprop": "price"})
        if price_tag and price_tag.get("content"):
            price = _parse_price(price_tag.get("content"))
        else:
            price_text = card.find(attrs={"data-marker": "item-price"})
            price = _parse_price(price_text.get_text()) if price_text else 0

        # Описание
        desc_tag = card.find(attrs={"data-marker": "item-specific-params"}) or card.find("p")
        description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

        # Фотографии
        photos = card.find_all("img")
        photo_urls = [img.get("src") for img in photos if img.get("src")]
        photo_count = len(photo_urls)

        # Год и пробег пытаемся вытащить из заголовка/описания
        year = _extract_year(title + " " + description)
        mileage = _extract_mileage(description)

        return {
            "listing_id": str(listing_id),
            "source": SOURCE,
            "title": title,
            "price": price,
            "year": year,
            "mileage": mileage,
            "city": "Москва и МО",
            "description": description,
            "photo_count": photo_count,
            "photo_urls": photo_urls,
            "seller_ads_count": 0,
            "listing_url": listing_url,
        }
    except Exception as e:
        logging.error(f"Avito: ошибка разбора карточки: {e}")
        return None


def _extract_year(text):
    """Найти год выпуска (4 цифры в диапазоне 1980–2030) в тексте."""
    try:
        import re

        for m in re.findall(r"(19[89]\d|20[0-3]\d)", text):
            return int(m)
    except Exception:
        pass
    return 0


def _extract_mileage(text):
    """Найти пробег в км в тексте описания, вернуть 0 при неудаче."""
    try:
        import re

        m = re.search(r"([\d\s]+)\s*км", text)
        if m:
            return _parse_price(m.group(1))
    except Exception:
        pass
    return 0


def parse():
    """
    Основная точка входа парсера Avito.

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

        cards = soup.find_all(attrs={"data-marker": "item"})
        if not cards:
            cards = soup.find_all("div", attrs={"itemtype": "http://schema.org/Product"})

        for card in cards:
            listing = _parse_card(card)
            if listing and _passes_filters(listing, cfg):
                results.append(listing)

        logging.info(f"Avito: собрано {len(results)} объявлений после фильтрации")
    except requests.RequestException as e:
        logging.error(f"Avito: сетевая ошибка: {e}")
    except Exception as e:
        logging.error(f"Avito: непредвиденная ошибка: {e}")

    return results
