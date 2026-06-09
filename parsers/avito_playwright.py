# parsers/avito_playwright.py — async fallback-парсер Avito через Playwright + stealth.
# Запускается автоматически из parsers/avito.py если основной парсер вернул 0.

import asyncio
import logging
import random
import re

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

_stealth = Stealth()

from config import RUNTIME_CONFIG
from database import is_seen
from utils.headers import USER_AGENTS

CAPTCHA_PHRASES = [
    "подтвердите, что вы не робот", "доступ ограничен",
    "автоматические запросы", "подозрительная активность",
    "слишком много запросов", "проверка безопасности",
    "ddos-guard", "you have been blocked",
]


def is_captcha_response(text: str) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in CAPTCHA_PHRASES)


def _avito_playwright_cookies() -> list:
    try:
        import browser_cookie3
        for browser_name, loader in [
            ("Firefox", browser_cookie3.firefox),
            ("Chrome", browser_cookie3.chrome),
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

AVITO_URL = "https://www.avito.ru/moskva/avtomobili?s=104&pmax={max_price}"

_CARD_SELECTORS = [
    "[data-marker='item']",
    "div[class*='iva-item-root']",
    "article[class*='item']",
]


def _proxy_config() -> dict | None:
    """Резидентный прокси для Playwright (общий хелпер utils.proxy)."""
    from utils.proxy import playwright_proxy
    return playwright_proxy()


async def _parse_item(item) -> dict | None:
    """Парсит одну карточку объявления."""
    try:
        link_el = await item.query_selector(
            "a[data-marker='item-title'], a[itemprop='url'], a[href*='/moskva/']"
        )
        if not link_el:
            return None

        href = await link_el.get_attribute("href")
        if not href:
            return None

        listing_url = f"https://www.avito.ru{href}" if href.startswith("/") else href

        id_match = re.search(r"_(\d+)$", href)
        listing_id = id_match.group(1) if id_match else re.sub(r"\D", "", href)[-10:]
        if not listing_id:
            return None

        title = (await link_el.inner_text()).strip()[:100]

        price_el = await item.query_selector(
            "[data-marker='item-price'] *[class*='price'], [data-marker='item-price']"
        )
        price_text = await price_el.inner_text() if price_el else "0"
        digits = re.sub(r"\D", "", price_text)
        price = int(digits) if digits else 0

        date_el = await item.query_selector("[data-marker='item-date'], p[class*='date']")
        published_at = (await date_el.inner_text()).strip() if date_el else ""

        desc_el = await item.query_selector(
            "[class*='description'], [data-marker='item-description']"
        )
        description = (await desc_el.inner_text()).strip() if desc_el else ""

        full_text = f"{title} {description}"
        year_match = re.search(r"\b(199\d|200\d|201\d|202\d)\b", full_text)
        year = int(year_match.group(1)) if year_match else 0

        mileage_match = re.search(r"(\d+)\s*(?:тыс\.?\s*)?км", full_text)
        mileage = 0
        if mileage_match:
            val = int(mileage_match.group(1))
            mileage = val * 1000 if val < 1000 else val

        return {
            "listing_id": listing_id,
            "source": "avito",
            "title": title,
            "price": price,
            "year": year,
            "mileage": mileage,
            "city": "Москва",
            "description": description[:600],
            "photo_count": 1,
            "photo_urls": [],
            "seller_ads_count": 0,
            "seller_id": "",
            "published_at": published_at,
            "listing_url": listing_url,
            "is_regional": False,
        }

    except Exception as e:
        logging.debug(f"Avito Playwright: ошибка карточки: {e}")
        return None


async def parse_async() -> list:
    """Основной async парсер через Playwright + stealth."""
    import time
    blocked_until = RUNTIME_CONFIG.get("AVITO_STEALTH_BLOCKED_UNTIL", 0)
    if time.time() < blocked_until:
        mins = int((blocked_until - time.time()) / 60)
        logging.info(f"Avito Stealth: пауза ещё {mins} мин")
        return []

    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)
    url = AVITO_URL.format(max_price=max_price)
    results = []

    proxy_config = _proxy_config()

    async with async_playwright() as p:
        # Firefox: лучше обходит антибот; на VPS кириллица не проблема
        launch_kwargs = {"headless": True}
        if proxy_config:
            launch_kwargs["proxy"] = proxy_config
        browser = await p.firefox.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )
        cookies = _avito_playwright_cookies()
        if cookies:
            await context.add_cookies(cookies)
            logging.info(f"Avito Playwright: внедрено {len(cookies)} куки из Firefox")
        page = await context.new_page()
        await _stealth.apply_stealth_async(page)

        try:
            # Пауза перед загрузкой: резидентный прокси добавляет задержку,
            # к тому же снижает шанс капчи на «слишком быстрый» заход.
            await asyncio.sleep(random.uniform(5, 10))
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(random.uniform(3, 6))

            # Прокрутка как у человека
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await asyncio.sleep(random.uniform(1, 2))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await asyncio.sleep(random.uniform(1, 2))

            # Карточки на Avito подгружаются JS — ждём появления, иначе
            # query_selector_all может сработать до рендера и вернуть 0.
            for selector in _CARD_SELECTORS:
                try:
                    await page.wait_for_selector(selector, timeout=15000)
                    break
                except Exception:
                    continue

            # Ищем карточки по нескольким селекторам
            items = []
            for selector in _CARD_SELECTORS:
                items = await page.query_selector_all(selector)
                if items:
                    logging.info(f"Avito Playwright: {len(items)} карточек ({selector})")
                    break

            # Капчу проверяем ТОЛЬКО когда карточек нет: на легитимной выдаче
            # тоже встречаются слова-маркеры в скриптах, и раньше это давало
            # ложную часовую паузу при реально загруженных объявлениях.
            if not items:
                page_html = await page.content()
                if is_captcha_response(page_html):
                    import time as _time
                    RUNTIME_CONFIG["AVITO_STEALTH_BLOCKED_UNTIL"] = _time.time() + 3600
                    RUNTIME_CONFIG["AVITO_WAS_BLOCKED"] = True
                    logging.warning("Avito Stealth: капча — пауза 60 минут")
                else:
                    logging.warning("Avito Playwright: карточки не найдены — возможно блокировка")
                await browser.close()
                return []

            for item in items[:20]:
                try:
                    listing = await _parse_item(item)
                    if listing is None:
                        continue
                    if listing["price"] <= 0 or listing["price"] > max_price:
                        continue
                    if is_seen(listing["listing_id"], "avito"):
                        continue
                    results.append(listing)
                except Exception as e:
                    logging.debug(f"Avito Playwright: пропуск карточки: {e}")

            logging.info(f"Avito Playwright: {len(results)} новых объявлений")

        except Exception as e:
            logging.error(f"Avito Playwright: ошибка страницы: {e}")
        finally:
            await browser.close()

    return results


def parse() -> list:
    """Синхронная обёртка — вызывается из main.py через asyncio.to_thread."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(parse_async())
    except Exception as e:
        logging.error(f"Avito Playwright sync wrapper: {e}")
        return []
    finally:
        loop.close()
