# parsers/autoru.py — парсер Auto.ru через curl_cffi (TLS fingerprint Chrome 124).
# curl_cffi обходит Yandex SmartCaptcha лучше requests и быстрее Playwright.

import re
import time
import random
import logging

import requests as _requests

from config import load_config, RUNTIME_CONFIG
from database import is_seen
from utils.headers import get_random_headers

SOURCE = "autoru"


def _load_autoru_cookies(session) -> int:
    """Загружает куки auto.ru напрямую из Firefox (fallback: Chrome)."""
    try:
        import browser_cookie3
        for loader in [browser_cookie3.firefox, browser_cookie3.chrome]:
            try:
                cj = loader(domain_name=".auto.ru")
                count = 0
                for c in cj:
                    if "auto.ru" in c.domain:
                        session.cookies.set(c.name, c.value, domain=".auto.ru")
                        count += 1
                if count:
                    logging.info(f"Auto.ru: {count} куки из браузера")
                    return count
            except Exception:
                continue
    except Exception as e:
        logging.warning(f"Auto.ru: не удалось загрузить куки: {e}")
    return 0


def parse() -> list:
    """Парсит Auto.ru через curl_cffi с живыми куками из Firefox."""
    load_config()
    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError:
        logging.error("Auto.ru: curl_cffi не установлен — pip install curl_cffi")
        return []

    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)
    session = CurlSession(impersonate="chrome124")
    _load_autoru_cookies(session)

    headers = get_random_headers(referer="https://auto.ru/")
    url = f"https://auto.ru/moskva/cars/used/?price_to={max_price}&seller_group=PRIVATE"

    from utils.proxy import curl_proxies
    proxies = curl_proxies()

    time.sleep(random.uniform(3, 7))

    try:
        response = session.get(url, headers=headers, timeout=60, proxies=proxies)
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

    results = _parse_from_json(response.text, max_price)
    logging.info(f"Auto.ru: {len(results)} новых объявлений")

    if not results:
        cnt = RUNTIME_CONFIG.get("AUTORU_EMPTY_CYCLES", 0) + 1
        RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = cnt
        if cnt >= 5:
            RUNTIME_CONFIG["AUTORU_EMPTY_CYCLES"] = 0
            _notify_stale_cookies()

    return results


def _pick_photo_size(sizes: dict) -> str:
    """Выбрать URL крупного размера фото для анализа (WxH с макс. площадью)."""
    wh = {}
    for s in sizes:
        m = re.fullmatch(r"(\d+)x(\d+)", s)
        if m:
            wh[s] = int(m.group(1)) * int(m.group(2))
    if wh:
        return sizes[max(wh, key=wh.get)]
    for pref in ("full", "orig"):
        if pref in sizes:
            return sizes[pref]
    return next(iter(sizes.values()))


def _extract_autoru_photos(html: str, pos: int, limit: int = 5) -> list:
    """Извлечь ссылки на реальные фото продавца из image_urls оффера Auto.ru.

    Блок "image_urls":[{...}] идёт сразу после saleId (~+840 симв). Реальные
    снимки — get-autoru-vos (get-verba = стоковые каталожные картинки, мусор).
    На каждое фото берём один URL крупного размера.
    """
    block_start = html.find('"image_urls":[', pos, pos + 4000)
    if block_start < 0:
        return []
    arr_start = block_start + len('"image_urls":')
    end = html.find("]", arr_start)
    block = html[arr_start:end + 1] if end > 0 else html[arr_start:arr_start + 8000]

    photos: dict = {}  # (id, hash) -> {size: url} — сохраняет порядок фото
    for m in re.finditer(
        r"//avatars\.mds\.yandex\.net/get-autoru-vos/(\d+)/([a-f0-9]+)/(\w+)",
        block,
    ):
        key = (m.group(1), m.group(2))
        photos.setdefault(key, {})[m.group(3)] = "https:" + m.group(0)

    urls = [_pick_photo_size(sizes) for sizes in photos.values()]
    return urls[:limit]


def _parse_from_json(html: str, max_price: int) -> list:
    """Извлекает объявления из embedded JSON в HTML страницы Auto.ru."""
    sale_ids = [(m.group(1), m.start()) for m in re.finditer(r'"saleId":"([\d]+-[a-f\d]+)"', html)]
    logging.info(f"Auto.ru: найдено {len(sale_ids)} saleId в JSON")

    # Глобальный индекс numeric_id → (mark, model, полный рабочий href).
    # Реальный href содержит полный saleId с хешем (1132859985-aec39aa9),
    # числовой URL без хеша даёт 404 — поэтому сохраняем href целиком.
    url_index: dict[str, tuple[str, str, str]] = {}
    for um in re.finditer(
        r'(https://auto\.ru/cars/used/sale/([a-z0-9_]+)/([a-z0-9_]+)/(\d{7,})-[a-f0-9]+/?)',
        html,
    ):
        full_url, mark_slug, model_slug, num_id = um.group(1), um.group(2), um.group(3), um.group(4)
        url_index[num_id] = (mark_slug, model_slug, full_url.rstrip("/") + "/")

    results = []
    seen_ids = set()
    for sid, pos in sale_ids:
        try:
            if sid in seen_ids:
                continue
            seen_ids.add(sid)

            if is_seen(sid, SOURCE):
                continue

            window = html[max(0, pos - 6000):pos + 1000]

            price_m = re.search(r'"price_info":\{"price":(\d+)', window)
            year_m  = re.search(r'"year":(\d{4})', window)
            km_m    = re.search(r'"mileage":(\d+)', window)
            price = int(price_m.group(1)) if price_m else 0
            year  = int(year_m.group(1)) if year_m else 0

            if price <= 0 or price > max_price:
                continue
            if year < 1990:
                continue

            numeric_id = sid.split("-")[0]
            mileage = int(km_m.group(1)) if km_m else 0
            mark_slug, model_slug, full_url = url_index.get(numeric_id, ("", "", ""))
            mark  = mark_slug.replace("_", " ").title()
            model = model_slug.replace("_", " ").title()
            # Используем реальный href со страницы (с полным saleId и хешем)
            listing_url = full_url or f"https://auto.ru/cars/used/sale/{sid}/"
            title = f"{mark} {model}, {year}".strip(" ,") if (mark or model) else str(year)

            photo_urls = _extract_autoru_photos(html, pos)

            results.append({
                "listing_id":       sid,
                "source":           SOURCE,
                "title":            title,
                "price":            price,
                "year":             year,
                "mileage":          mileage,
                "city":             "Москва",
                "description":      title,
                "photo_count":      len(photo_urls),
                "photo_urls":       photo_urls,
                "seller_ads_count": 0,
                "seller_id":        "",
                "published_at":     "",
                "listing_url":      listing_url,
                "is_regional":      False,
            })
        except Exception as e:
            logging.debug(f"Auto.ru parse item {sid}: {e}")

    return results


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
