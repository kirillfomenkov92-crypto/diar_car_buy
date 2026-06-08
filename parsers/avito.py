# parsers/avito.py — парсер Avito через Playwright headless Firefox (fallback: Chromium).

import re
import time
import random
import logging

from config import RUNTIME_CONFIG, load_config
from database import is_seen

def _avito_playwright_cookies() -> list:
    """Загружает все куки avito.ru напрямую из Firefox (fallback: Chrome)."""
    try:
        import browser_cookie3
        for browser_name, loader in [
            ("Firefox", browser_cookie3.firefox),
            ("Chrome",  browser_cookie3.chrome),
        ]:
            try:
                cj = loader(domain_name=".avito.ru")
                result = [
                    {"name": c.name, "value": c.value, "domain": ".avito.ru", "path": "/"}
                    for c in cj if "avito.ru" in c.domain
                ]
                if result:
                    logging.info(f"Avito: {len(result)} куки из {browser_name}")
                    return result
            except Exception as e:
                logging.debug(f"Avito cookies: {browser_name} недоступен: {e}")
    except Exception as e:
        logging.warning(f"Avito: не удалось загрузить куки: {e}")
    return []

SOURCE = "avito"
BASE_URL = "https://www.avito.ru/moskva/avtomobili"

# Специфичные фразы антибот-страниц. Раньше список содержал «captcha»/«robot»/
# «подтвердите», которые встречаются в скриптах ЛЕГИТИМНЫХ страниц Avito и давали
# ложную «капчу» (бот уходил в часовую паузу при реально загруженных карточках).
# Теперь только однозначные маркеры блокировки.
CAPTCHA_PHRASES = [
    "подтвердите, что вы не робот", "доступ ограничен",
    "автоматические запросы", "подозрительная активность",
    "слишком много запросов", "проверка безопасности",
    "ddos-guard", "you have been blocked",
]


def is_captcha_response(text: str) -> bool:
    lower = text.lower()
    return any(p.lower() in lower for p in CAPTCHA_PHRASES)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


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


def _parse_main() -> list:
    """Парсит Avito через Playwright headless Firefox."""
    blocked_until = RUNTIME_CONFIG.get("AVITO_FF_BLOCKED_UNTIL", 0)
    if time.time() < blocked_until:
        mins = int((blocked_until - time.time()) / 60)
        logging.info(f"Авито Firefox: пауза ещё {mins} мин")
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logging.error("Avito: playwright не установлен")
        return []

    load_config()
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)
    url = f"{BASE_URL}?pmax={max_price}&s=104"
    results = []

    try:
        with sync_playwright() as pw:
            # Chromium: Firefox не запускается на Windows с кириллицей в пути
            # пользователя (spawn UNKNOWN). Chromium работает.
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                viewport={
                    "width": random.randint(1280, 1920),
                    "height": random.randint(800, 1080),
                },
            )
            cookies = _avito_playwright_cookies()
            if cookies:
                context.add_cookies(cookies)
                logging.info(f"Avito: внедрено {len(cookies)} куки из Firefox")

            page = context.new_page()
            page.set_extra_http_headers({
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "DNT": "1",
                "Referer": "https://www.google.ru/",
                "Upgrade-Insecure-Requests": "1",
            })

            time.sleep(random.uniform(1, 3))
            page.goto(url, wait_until="networkidle", timeout=45000)
            time.sleep(random.uniform(1, 3))

            content_lower = page.content().lower()
            if is_captcha_response(content_lower):
                RUNTIME_CONFIG["AVITO_FF_BLOCKED_UNTIL"] = time.time() + 3600
                RUNTIME_CONFIG["AVITO_WAS_BLOCKED"] = True
                logging.warning("Авито Firefox: капча — пауза 60 минут")
                browser.close()
                return []

            try:
                page.wait_for_selector("[data-marker='item']", timeout=15000)
            except Exception:
                logging.warning("Avito: карточки не появились за 15с")
                browser.close()
                return []

            cards = page.query_selector_all("[data-marker='item']")
            logging.info(f"Avito: найдено {len(cards)} карточек")

            for card in cards:
                try:
                    item_id = card.get_attribute("data-item-id") or ""
                    if not item_id or is_seen(item_id, SOURCE):
                        continue

                    title_el = card.query_selector("[data-marker='item-title']")
                    href = title_el.get_attribute("href") if title_el else ""
                    title = title_el.inner_text().strip() if title_el else ""
                    if not href:
                        continue
                    listing_url = (
                        href if href.startswith("http")
                        else f"https://www.avito.ru{href}"
                    )

                    price_meta = card.query_selector("meta[itemprop='price']")
                    if price_meta:
                        price = _parse_price(price_meta.get_attribute("content") or "")
                    else:
                        price_el = card.query_selector("[data-marker='item-price']")
                        price = _parse_price(price_el.inner_text()) if price_el else 0

                    if price <= 0 or price > max_price:
                        continue

                    desc_el = card.query_selector(
                        "[class*='item-description'], [class*='itemDescription'], [data-marker='item-description']"
                    )
                    description = desc_el.inner_text(" ").strip() if desc_el else ""

                    date_el = card.query_selector("[data-marker='item-date']")
                    published_at = date_el.inner_text().strip() if date_el else ""

                    photos = card.query_selector_all("img[src]")
                    photo_urls = [
                        img.get_attribute("src") for img in photos
                        if img.get_attribute("src")
                    ]

                    combined = title + " " + description
                    results.append({
                        "listing_id": str(item_id),
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
                    logging.error(f"Avito: ошибка карточки: {e}")

            browser.close()
            logging.info(f"Avito: {len(results)} новых объявлений")

    except Exception as e:
        logging.error(f"Avito: ошибка Playwright: {e}")

    return results


def parse() -> list:
    """Строгая очерёдность: RSS → curl_cffi → Playwright stealth.
    Каждый уровень запускается только если предыдущий вернул 0,
    и только после выдержки паузы между уровнями.
    В одном вызове parse() всегда работает ТОЛЬКО ОДИН уровень.
    """
    now = time.time()

    # ── Уровень 1: RSS / curl_cffi с прогревом ──────────────────────────
    # RSS имеет собственный ключ блокировки — не зависит от curl 403
    rss_blocked = now < RUNTIME_CONFIG.get("AVITO_RSS_BLOCKED_UNTIL", 0)
    if not rss_blocked:
        try:
            from parsers.avito_rss import parse as rss_parse
            results = rss_parse()
        except Exception as e:
            logging.warning(f"Avito RSS: ошибка: {e}")
            results = []

        RUNTIME_CONFIG["AVITO_RSS_LAST"] = now
        RUNTIME_CONFIG["AVITO_RSS_LAST_COUNT"] = len(results)

        if len(results) >= 3:
            logging.info(f"Avito RSS: успех — {len(results)} объявлений")
            RUNTIME_CONFIG.pop("AVITO_CURL_NOT_BEFORE", None)
            return results

        # RSS не дал результата — выставляем 10-мин паузу перед curl
        not_before = RUNTIME_CONFIG.get("AVITO_CURL_NOT_BEFORE", 0)
        if now > not_before:
            RUNTIME_CONFIG["AVITO_CURL_NOT_BEFORE"] = now + 600
            logging.info("Avito RSS: 0 — curl_cffi разрешён через 10 мин")
        return []   # в этом цикле больше ничего не запускаем

    # ── Уровень 2: curl_cffi без прогрева (autoru.py стиль) ─────────────
    curl_not_before = RUNTIME_CONFIG.get("AVITO_CURL_NOT_BEFORE", 0)
    curl_http_blocked = now < RUNTIME_CONFIG.get("AVITO_CURL_BLOCKED_UNTIL", 0)
    if not curl_http_blocked and now >= curl_not_before and curl_not_before > 0:
        try:
            from parsers.avito_rss import _browser_cookies, _HEADERS, _CAPTCHA_PHRASES
            from curl_cffi import requests as cffi_requests
            from bs4 import BeautifulSoup
            import re as _re
            load_config()
            max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)
            cookies = _browser_cookies()
            resp = cffi_requests.get(
                f"https://www.avito.ru/moskva/avtomobili?s=104&pmax={max_price}",
                headers=_HEADERS,
                cookies=cookies,
                impersonate="chrome124",   # другой fingerprint чем уровень 1
                timeout=25,
            )
            results = []
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all(attrs={"data-marker": "item"})
                if not cards and any(p in resp.text.lower() for p in _CAPTCHA_PHRASES):
                    RUNTIME_CONFIG["AVITO_CURL_BLOCKED_UNTIL"] = now + 1800
                    logging.warning("Avito curl: капча — пауза 30 мин")
                else:
                    from database import is_seen
                    for card in cards:
                        try:
                            lid = str(card.get("data-item-id", ""))
                            if not lid or is_seen(lid, SOURCE):
                                continue
                            title_el = card.find(attrs={"data-marker": "item-title"})
                            if not title_el:
                                continue
                            href = title_el.get("href", "")
                            price_meta = card.find("meta", itemprop="price")
                            price = int(_re.sub(r"\D", "", price_meta.get("content","0") if price_meta else "0") or 0)
                            if price <= 0 or price > max_price:
                                continue
                            results.append({
                                "listing_id": lid, "source": SOURCE,
                                "title": title_el.get_text(strip=True),
                                "price": price, "year": 0, "mileage": 0,
                                "city": "Москва", "description": "",
                                "photo_count": 0, "photo_urls": [],
                                "seller_ads_count": 0, "seller_id": "",
                                "published_at": "",
                                "listing_url": f"https://www.avito.ru{href}" if not href.startswith("http") else href,
                                "is_regional": False,
                            })
                        except Exception:
                            pass
            elif resp.status_code == 403:
                RUNTIME_CONFIG["AVITO_CURL_BLOCKED_UNTIL"] = now + 900
                logging.warning("Avito curl: 403 — пауза 15 мин")
        except Exception as e:
            logging.warning(f"Avito curl (прямой): {e}")
            results = []

        RUNTIME_CONFIG["AVITO_CURL_LAST"] = now
        RUNTIME_CONFIG["AVITO_CURL_LAST_COUNT"] = len(results)

        if len(results) >= 1:
            logging.info(f"Avito curl: успех — {len(results)} объявлений")
            RUNTIME_CONFIG.pop("AVITO_CURL_NOT_BEFORE", None)
            return results

        logging.info("Avito curl: 0 — Playwright разрешён если прошло 30 мин")
        return []   # в этом цикле Playwright не запускаем

    # ── Уровень 3: Playwright stealth (не чаще раза в 30 мин) ───────────
    playwright_last = RUNTIME_CONFIG.get("AVITO_PLAYWRIGHT_LAST", 0)
    if now - playwright_last >= 1800:
        try:
            from parsers.avito_playwright import parse as stealth_parse
            results = stealth_parse()
        except Exception as e:
            logging.error(f"Avito Stealth: {e}")
            results = []
        RUNTIME_CONFIG["AVITO_PLAYWRIGHT_LAST"] = now
        logging.info(f"Avito Playwright stealth: {len(results)} объявлений")
        return results

    mins_left = int((playwright_last + 1800 - now) / 60)
    logging.debug(f"Avito Playwright: cooldown ещё {mins_left} мин")
    return []
