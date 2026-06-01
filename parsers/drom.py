# parsers/drom.py — парсер Drom.ru через curl_cffi (TLS fingerprint Chrome 124).
# Москва + региональные URL (для арбитража). is_regional=True для регионов.

import re
import time
import random
import logging

from bs4 import BeautifulSoup

from config import load_config, RUNTIME_CONFIG
from database import is_seen
from utils.headers import get_drom_headers

SOURCE = "drom"

DROM_URLS = [
    "https://auto.drom.ru/moscow/all/?priceto={max_price}",
    "https://auto.drom.ru/tula/all/?priceto=130000",
    "https://auto.drom.ru/ryazan/all/?priceto=130000",
    "https://auto.drom.ru/kaluga/all/?priceto=130000",
    "https://auto.drom.ru/vladimir/all/?priceto=130000",
    "https://auto.drom.ru/tver/all/?priceto=130000",
]


def parse() -> list:
    """Парсит Drom.ru через curl_cffi с TLS fingerprint Chrome 124."""
    load_config()
    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError:
        logging.error("Drom: curl_cffi не установлен — pip install curl_cffi")
        return []

    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)
    session = CurlSession(impersonate="chrome124")
    results = []

    urls = [DROM_URLS[0].format(max_price=max_price)] + DROM_URLS[1:]

    for i, url in enumerate(urls):
        is_regional = i > 0
        city_slug = url.split("drom.ru/")[1].split("/")[0]
        city = _CITY_NAMES.get(city_slug, city_slug.capitalize())

        time.sleep(random.uniform(2, 5))

        try:
            response = session.get(url, headers=get_drom_headers(), timeout=25)
        except Exception as e:
            logging.error(f"Drom {city}: {e}")
            continue

        if response.status_code != 200:
            logging.warning(f"Drom {city}: статус {response.status_code}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        # Карточки — ссылки на конкретные объявления с числовым ID
        items = soup.find_all(
            "a", href=re.compile(r"auto\.drom\.ru/[a-z]+/[a-z0-9_]+/[a-z0-9_]+/\d+\.html")
        )
        logging.info(f"Drom {city}: найдено {len(items)} карточек")

        for item in items[:25]:
            try:
                listing = _parse_link_item(item, city, is_regional)
                if listing is None:
                    continue
                if listing["price"] <= 0:
                    continue
                if not is_regional and listing["price"] > max_price:
                    continue
                if is_seen(listing["listing_id"], SOURCE):
                    continue
                results.append(listing)
            except Exception as e:
                logging.debug(f"Drom item {city}: {e}")

        logging.info(f"Drom {city}: {len([r for r in results if r['city'] == city])} новых")

    logging.info(f"Drom итого: {len(results)} новых объявлений")
    return results


def _parse_link_item(link_el, city: str, is_regional: bool) -> dict | None:
    """Разобрать объявление Drom из элемента <a href=...>text</a>."""
    try:
        href = link_el.get("href", "")
        id_match = re.search(r"(\d{6,})\.html", href)
        listing_id = id_match.group(1) if id_match else None
        if not listing_id:
            return None

        text = link_el.get_text(separator=" ", strip=True)
        # Формат текста: "1 500 000 ₽Лада Веста, 2024Москва"
        price_m = re.search(r"([\d\s\xa0]+)\s*[₽р]", text)
        price = int(re.sub(r"\D", "", price_m.group(1))) if price_m else 0

        year_m = re.search(r"\b(199\d|200\d|201\d|202[0-6])\b", text)
        year = int(year_m.group(1)) if year_m else 0

        km_m = re.search(r"([\d\s\xa0]+)\s*км", text)
        mileage = int(re.sub(r"\D", "", km_m.group(1))) if km_m else 0

        # Название: часть между ценой и годом
        title = re.sub(r"[\d\s₽р.,]*$", "", re.sub(r"^[\d\s₽р.,]*", "", text)).strip()[:80]
        if not title:
            # берём марку/модель из URL
            parts = href.rstrip("/").split("/")
            if len(parts) >= 5:
                title = f"{parts[-3].title()} {parts[-2].title()}, {year}".strip()

        return {
            "listing_id":       listing_id,
            "source":           SOURCE,
            "title":            title,
            "price":            price,
            "year":             year,
            "mileage":          mileage,
            "city":             city,
            "description":      text[:600],
            "photo_count":      0,
            "photo_urls":       [],
            "seller_ads_count": 0,
            "seller_id":        "",
            "published_at":     "",
            "listing_url":      href,
            "is_regional":      is_regional,
        }
    except Exception as e:
        logging.debug(f"parse_drom_link_item: {e}")
        return None


def _parse_item(item, city: str, is_regional: bool) -> dict | None:
    """Разобрать карточку объявления Drom из BeautifulSoup."""
    try:
        link = (
            item.select_one("a[data-ftid='bull_title']")
            or item.select_one("a[href*='drom.ru']")
        )
        if not link:
            return None

        href = link.get("href", "")
        id_match = re.search(r"(\d{6,})", href)
        listing_id = id_match.group(1) if id_match else None
        if not listing_id:
            return None

        title = link.get_text(strip=True)[:100]

        price_el = (
            item.select_one("[data-ftid='bull_price']")
            or item.select_one("[class*='price']")
        )
        price_text = price_el.get_text() if price_el else "0"
        digits = re.sub(r"\D", "", price_text)
        price = int(digits) if digits else 0

        text = item.get_text(separator=" ")
        year_match = re.search(r"\b(199\d|200\d|201\d|202[0-6])\b", text)
        year = int(year_match.group(1)) if year_match else 0

        km_match = re.search(r"(\d[\d\s]+)\s*км", text)
        mileage = int(re.sub(r"\D", "", km_match.group(1))) if km_match else 0

        date_el = (
            item.select_one("span[class*='date']")
            or item.select_one("[data-ftid*='date']")
        )
        published_at = date_el.get_text(strip=True) if date_el else ""

        return {
            "listing_id":       listing_id,
            "source":           SOURCE,
            "title":            title,
            "price":            price,
            "year":             year,
            "mileage":          mileage,
            "city":             city,
            "description":      text[:600],
            "photo_count":      len(item.select("img")),
            "photo_urls":       [],
            "seller_ads_count": 0,
            "seller_id":        "",
            "published_at":     published_at,
            "listing_url":      href,
            "is_regional":      is_regional,
        }
    except Exception as e:
        logging.debug(f"parse_drom_item: {e}")
        return None


_CITY_NAMES = {
    "moscow":   "Москва",
    "tula":     "Тула",
    "ryazan":   "Рязань",
    "kaluga":   "Калуга",
    "vladimir": "Владимир",
    "tver":     "Тверь",
}
