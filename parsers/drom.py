# parsers/drom.py — парсер Drom.ru через Playwright Firefox.
# Drom рендерит листинги через JS — curl_cffi даёт только платные размещения.
# Playwright + скролл загружает реальные отфильтрованные объявления.
# Москва + региональные URL (is_regional=True для арбитража).

import re
import time
import random
import logging

from bs4 import BeautifulSoup

from config import load_config, RUNTIME_CONFIG
from database import is_seen
from utils.headers import get_drom_headers

SOURCE = "drom"

# Москва + ближнее Подмосковье (≤ ~40 км). Далёкие регионы (Тула/Рязань/Калуга —
# 150+ км) убраны: партнёру нужны машины, которые можно забрать самому.
DROM_URLS = [
    "https://auto.drom.ru/moscow/all/?priceto={max_price}",
    "https://auto.drom.ru/krasnogorsk/all/?priceto={max_price}",
    "https://auto.drom.ru/himki/all/?priceto={max_price}",
    "https://auto.drom.ru/balashiha/all/?priceto={max_price}",
    "https://auto.drom.ru/mytishchi/all/?priceto={max_price}",
    "https://auto.drom.ru/korolev/all/?priceto={max_price}",
    "https://auto.drom.ru/podolsk/all/?priceto={max_price}",
    "https://auto.drom.ru/elektrostal/all/?priceto={max_price}",
]

_CITY_NAMES = {
    "moscow":      "Москва",
    "krasnogorsk": "Красногорск",
    "himki":       "Химки",
    "balashiha":   "Балашиха",
    "mytishchi":   "Мытищи",
    "korolev":     "Королёв",
    "podolsk":     "Подольск",
    "elektrostal": "Электросталь",
}


def _drom_cookies() -> list:
    """Куки Drom из Firefox в формате Playwright."""
    try:
        import browser_cookie3
        for loader in [browser_cookie3.firefox, browser_cookie3.chrome]:
            try:
                cj = loader(domain_name=".drom.ru")
                result = [
                    {"name": c.name, "value": c.value, "domain": ".drom.ru", "path": "/"}
                    for c in cj if "drom.ru" in c.domain
                ]
                if result:
                    return result
            except Exception:
                continue
    except Exception:
        pass
    return []


def _photo_urls_from_card(card, limit: int = 5) -> list:
    """Собрать ссылки на реальные фото машины из <img> карточки Drom.

    Реальные снимки лежат на CDN *.auto.drom.ru/photo/ (иконки/логотипы — нет).
    В srcset есть 1x и 2x версии одного снимка — берём максимальное разрешение,
    дедупим по базовому пути (genNNNwb.jpg — варианты одного фото).
    """
    urls: list = []
    seen: set = set()
    for img in card.find_all("img"):
        candidates: list = []
        srcset = img.get("srcset") or img.get("data-srcset") or ""
        if srcset:
            # "url1 1x, url2 2x" — берём по убыванию плотности (2x крупнее 1x)
            entries = []
            for p in srcset.split(","):
                p = p.strip()
                if not p:
                    continue
                parts = p.split(" ")
                density = parts[1] if len(parts) > 1 else "1x"
                entries.append((density, parts[0]))
            entries.sort(reverse=True)  # "2x" > "1x"
            candidates.extend(u for _, u in entries)
        for attr in ("data-src", "src"):
            v = img.get(attr)
            if v:
                candidates.append(v)

        # Только реальные фото машины с CDN drom; крупный размер из srcset в приоритете
        photo = next((c for c in candidates if ".drom.ru/photo/" in c), None)
        if not photo:
            continue
        if photo.startswith("//"):
            photo = "https:" + photo

        base = re.sub(r"/gen\d+wb\.jpg.*$", "", photo)
        if base in seen:
            continue
        seen.add(base)
        urls.append(photo)
        if len(urls) >= limit:
            break
    return urls


def _parse_card(card, city: str, is_regional: bool) -> dict | None:
    """Разобрать карточку Drom из data-ftid='bulls-list_bull'."""
    try:
        title_el = card.find(attrs={"data-ftid": "bull_title"})
        price_el = card.find(attrs={"data-ftid": "bull_price"})
        link_el  = card.find("a", href=re.compile(r"\d{7,}\.html"))

        if not title_el or not link_el:
            return None

        href = link_el.get("href", "")
        id_m = re.search(r"(\d{7,})\.html", href)
        listing_id = id_m.group(1) if id_m else None
        if not listing_id:
            return None

        title = title_el.get_text(strip=True)[:100]
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = int(re.sub(r"\D", "", price_text)) if price_text else 0

        year_m = re.search(r"\b(199\d|200\d|201\d|202\d)\b", title)
        year = int(year_m.group(1)) if year_m else 0

        location_el = card.find(attrs={"data-ftid": "bull_location"})
        location = location_el.get_text(strip=True) if location_el else city

        photo_urls = _photo_urls_from_card(card)

        return {
            "listing_id":       listing_id,
            "source":           SOURCE,
            "title":            title,
            "price":            price,
            "year":             year,
            "mileage":          0,
            "city":             location or city,
            "description":      title,
            "photo_count":      len(photo_urls),
            "photo_urls":       photo_urls,
            "seller_ads_count": 0,
            "seller_id":        "",
            "published_at":     "",
            "listing_url":      href,
            "is_regional":      is_regional,
        }
    except Exception as e:
        logging.debug(f"Drom parse_card: {e}")
        return None


def _parse_city(url: str, city: str, is_regional: bool,
                max_price: int, browser) -> list:
    """Открыть страницу Drom через Playwright, прокрутить и собрать карточки."""
    try:
        context = browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1280, "height": 900},
        )
        cookies = _drom_cookies()
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2, 4))

        # Скроллим для загрузки lazy-loaded объявлений
        for _ in range(6):
            page.evaluate("window.scrollBy(0, 2000)")
            time.sleep(random.uniform(0.8, 1.4))
        time.sleep(2)

        soup = BeautifulSoup(page.content(), "html.parser")
        context.close()

        cards = soup.find_all(attrs={"data-ftid": "bulls-list_bull"})
        logging.info(f"Drom {city}: найдено {len(cards)} карточек")

        results = []
        for card in cards:
            listing = _parse_card(card, city, is_regional)
            if listing is None:
                continue
            if listing["price"] <= 0:
                continue
            # Ценовой фильтр ДО is_seen/mark_seen — дорогие не попадают в БД
            if listing["price"] > max_price:
                continue
            if is_seen(listing["listing_id"], SOURCE):
                continue
            results.append(listing)

        logging.info(f"Drom {city}: {len(results)} новых")
        return results

    except Exception as e:
        logging.error(f"Drom {city}: {e}")
        return []


def parse() -> list:
    """Парсит Drom.ru через Playwright Firefox с прокруткой страницы."""
    load_config()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logging.error("Drom: playwright не установлен")
        return []

    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)
    urls = [u.format(max_price=max_price) for u in DROM_URLS]
    results = []

    from utils.proxy import playwright_proxy
    proxy = playwright_proxy()

    try:
        with sync_playwright() as pw:
            # Firefox: лучше обходит антибот; на VPS кириллица не проблема
            launch_kwargs = {"headless": True}
            if proxy:
                launch_kwargs["proxy"] = proxy
            browser = pw.firefox.launch(**launch_kwargs)
            for i, url in enumerate(urls):
                # Все города — ближнее Подмосковье/Москва, считаем локальными
                # (арбитраж «из далёкого региона» больше не нужен).
                is_regional = False
                city_slug = url.split("drom.ru/")[1].split("/")[0]
                city = _CITY_NAMES.get(city_slug, city_slug.capitalize())
                city_results = _parse_city(url, city, is_regional, max_price, browser)
                results.extend(city_results)
                if i < len(urls) - 1:
                    time.sleep(random.uniform(3, 6))
            browser.close()
    except Exception as e:
        logging.error(f"Drom Playwright: {e}")

    logging.info(f"Drom итого: {len(results)} новых объявлений")
    return results

