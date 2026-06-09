# parsers/avito.py — оркестратор парсинга Avito: RSS → curl_cffi → Playwright stealth.
# В одном вызове parse() всегда работает ТОЛЬКО ОДИН уровень.

import time
import logging

from config import RUNTIME_CONFIG, load_config

SOURCE = "avito"


def parse() -> list:
    """Строгая очерёдность: RSS → curl_cffi → Playwright stealth.
    Каждый уровень запускается только если предыдущий вернул 0,
    и только после выдержки паузы между уровнями.
    """
    now = time.time()

    # ── Уровень 1: RSS / curl_cffi с прогревом ──────────────────────────
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

        not_before = RUNTIME_CONFIG.get("AVITO_CURL_NOT_BEFORE", 0)
        if now > not_before:
            RUNTIME_CONFIG["AVITO_CURL_NOT_BEFORE"] = now + 600
            logging.info("Avito RSS: 0 — curl_cffi разрешён через 10 мин")
        return []

    # ── Уровень 2: curl_cffi без прогрева ───────────────────────────────
    curl_not_before = RUNTIME_CONFIG.get("AVITO_CURL_NOT_BEFORE", 0)
    curl_http_blocked = now < RUNTIME_CONFIG.get("AVITO_CURL_BLOCKED_UNTIL", 0)
    if not curl_http_blocked and now >= curl_not_before and curl_not_before > 0:
        try:
            import re
            from parsers.avito_rss import _browser_cookies, _HEADERS, _CAPTCHA_PHRASES
            from curl_cffi import requests as cffi_requests
            from bs4 import BeautifulSoup
            from database import is_seen
            load_config()
            max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)
            cookies = _browser_cookies()
            resp = cffi_requests.get(
                f"https://www.avito.ru/moskva/avtomobili?s=104&pmax={max_price}",
                headers=_HEADERS,
                cookies=cookies,
                impersonate="chrome124",
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
                            price = int(re.sub(r"\D", "", price_meta.get("content", "0") if price_meta else "0") or 0)
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
        return []

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
