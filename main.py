# main.py — точка входа Diar Car Buy AI v3.0.
# Два планировщика: fast_cycle (каждую минуту, RSS) + monitor_cycle (каждые 15 мин, все источники).

import asyncio
import io
import logging
import sys
import time

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, CommandHandler

from config import load_config, RUNTIME_CONFIG
from database import (
    init_db, mark_seen, was_notified, price_dropped,
    increment_analyzed, increment_notified, record_response_time,
)
from analyzer import analyze_listing
from notifier import send_notification
from bot_commands import get_command_handlers
from speed_monitor import calculate_listing_age_minutes

from parsers.avito import parse as avito_parse
from parsers.drom import parse as drom_parse
from parsers.autoru import parse as autoru_parse
from parsers.youla import parse as youla_parse
from parsers.vk_parser import parse as vk_parse
from parsers.tg_parser import parse as tg_parse


async def _process_listings(listings: list, tag: str = ""):
    """Общая логика анализа и уведомлений для списка объявлений."""
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)
    target = RUNTIME_CONFIG.get("TARGET_MODELS", [])
    for listing in listings:
        try:
            if listing.get("price", 0) > max_price:
                logging.debug(
                    f"Пропуск: цена {listing['price']} > MAX_PRICE {max_price} "
                    f"({listing.get('title', listing.get('listing_id'))})"
                )
                continue

            # Фильтр целевых моделей — отсекаем нецелевой мусор
            if target:
                title_low = listing.get("title", "").lower()
                if not any(m.lower() in title_low for m in target):
                    logging.debug(f"Не целевая модель: {listing.get('title')}")
                    continue

            lid = listing["listing_id"]
            src = listing["source"]

            mark_seen(
                lid, src, listing["price"],
                listing.get("title", ""), listing.get("listing_url", ""),
            )
            increment_analyzed()

            should_analyze = (
                not was_notified(lid, src)
                or price_dropped(lid, src)[0]
            )
            if not should_analyze:
                continue

            result = await asyncio.to_thread(analyze_listing, listing)
            min_score = RUNTIME_CONFIG.get("MIN_DCB_SCORE", 80)

            if result["dcb_score"] >= min_score:
                await asyncio.to_thread(send_notification, result)
                increment_notified(result["dcb_score"])
                age = result.get("age_minutes", 999)
                if age < 999:
                    record_response_time(lid, src, age)
                logging.info(
                    f"{tag} ✅ {listing['title']} | {listing['price']:,}₽"
                    f" | Score:{result['dcb_score']} | {src}"
                )
            else:
                logging.info(
                    f"ПРОПУСК: {listing.get('title', '?')} | "
                    f"{listing.get('price', 0):,}₽ | "
                    f"Score {result['dcb_score']} | "
                    f"{result.get('reject_reason', '')} | {src}"
                )

        except Exception as e:
            logging.error(f"{tag} listing {listing.get('listing_id')}: {e}")


def _send_tg_message(text: str):
    """Отправить сообщение в Telegram (синхронно, для вызова через to_thread)."""
    token = RUNTIME_CONFIG.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = RUNTIME_CONFIG.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logging.warning(f"Telegram notify: {e}")


async def fast_cycle():
    """Быстрый цикл — Авито + Auto.ru (без Playwright, быстрые источники)."""
    if RUNTIME_CONFIG.get("PAUSED", False):
        return

    sources_cfg = RUNTIME_CONFIG.get("SOURCES", {})
    listings = []
    avito_results = []

    if sources_cfg.get("avito", True):
        last_avito = RUNTIME_CONFIG.get("LAST_AVITO_PARSE", 0)
        min_interval = RUNTIME_CONFIG.get("AVITO_MIN_INTERVAL_SECONDS", 90)
        if time.time() - last_avito >= min_interval:
            try:
                avito_results = await asyncio.to_thread(avito_parse)
                RUNTIME_CONFIG["LAST_AVITO_PARSE"] = time.time()
                listings += avito_results
                logging.info(f"[FAST] avito: {len(avito_results)} новых")
            except Exception as e:
                logging.error(f"[FAST] avito: {e}")
        else:
            logging.debug("Авито: пропуск — слишком частые запросы")

    # Auto.ru — curl_cffi без Playwright, работает быстро
    if sources_cfg.get("autoru", True):
        last_autoru = RUNTIME_CONFIG.get("LAST_AUTORU_FAST_PARSE", 0)
        if time.time() - last_autoru >= 300:  # не чаще раза в 5 мин
            try:
                autoru_results = await asyncio.to_thread(autoru_parse)
                RUNTIME_CONFIG["LAST_AUTORU_FAST_PARSE"] = time.time()
                listings += autoru_results
                logging.info(f"[FAST] autoru: {len(autoru_results)} новых")
            except Exception as e:
                logging.error(f"[FAST] autoru: {e}")

    # Уведомление о разблокировке
    was_blocked = RUNTIME_CONFIG.get("AVITO_WAS_BLOCKED", False)
    if was_blocked and len(avito_results) > 0:
        RUNTIME_CONFIG["AVITO_WAS_BLOCKED"] = False
        notify_text = f"Авито разблокирован — получено {len(avito_results)} объявлений"
        await asyncio.to_thread(_send_tg_message, notify_text)
        logging.info(f"[FAST] {notify_text}")

    # Адаптивный интервал по времени суток
    new_interval = get_current_fast_interval()
    if RUNTIME_CONFIG.get("_FAST_INTERVAL_CURRENT") != new_interval:
        try:
            _scheduler = RUNTIME_CONFIG.get("_SCHEDULER")
            if _scheduler:
                _scheduler.reschedule_job(
                    "fast_cycle", trigger="interval", minutes=new_interval
                )
                RUNTIME_CONFIG["_FAST_INTERVAL_CURRENT"] = new_interval
                logging.info(f"[FAST] интервал обновлён: {new_interval} мин")
        except Exception as _e:
            logging.debug(f"reschedule: {_e}")

    fresh = [
        l for l in listings
        if calculate_listing_age_minutes(l.get("published_at", "")) <= 30
    ]
    logging.info(f"[FAST] Свежих (до 30 мин): {len(fresh)} из {len(listings)}")

    await _process_listings(fresh, tag="[FAST]")


def get_current_fast_interval() -> int:
    """Возвращает интервал fast_cycle зависимости от времени суток."""
    from datetime import datetime as _dt
    hour = _dt.now().hour
    if 0 <= hour < 8:
        return RUNTIME_CONFIG.get("FAST_INTERVAL_NIGHT", 2)
    elif 9 <= hour < 18:
        return RUNTIME_CONFIG.get("FAST_INTERVAL_DAY", 8)
    else:
        return RUNTIME_CONFIG.get("FAST_INTERVAL_EVENING", 3)


async def monitor_cycle():
    """Полный цикл — все источники, без фильтра по возрасту."""
    if RUNTIME_CONFIG.get("PAUSED", False):
        logging.info("Мониторинг на паузе, цикл пропущен")
        return

    sources_cfg = RUNTIME_CONFIG.get("SOURCES", {})
    all_parsers = [
        ("avito",    avito_parse),
        ("drom",     drom_parse),
        ("autoru",   autoru_parse),
        ("youla",    youla_parse),
        ("vk",       vk_parse),
        ("telegram", tg_parse),
    ]

    listings = []
    for name, parser in all_parsers:
        if sources_cfg.get(name, True):
            try:
                found = await asyncio.to_thread(parser)
                listings += found
                logging.info(f"{name}: +{len(found)} объявлений")
            except Exception as e:
                logging.error(f"{name}: {e}")

    listings.sort(
        key=lambda x: calculate_listing_age_minutes(x.get("published_at", "999"))
    )
    logging.info(f"Всего объявлений для обработки: {len(listings)}")

    await _process_listings(listings, tag="[FULL]")


async def run():
    """Главная async функция: инициализация бота и планировщика."""
    cfg = load_config()
    RUNTIME_CONFIG.update(cfg)

    token = cfg.get("TELEGRAM_BOT_TOKEN", "")
    app = ApplicationBuilder().token(token).build()

    for cmd, handler in get_command_handlers():
        app.add_handler(CommandHandler(cmd, handler))

    scheduler = AsyncIOScheduler()
    fast_interval = cfg.get("FAST_CHECK_INTERVAL", 1)
    full_interval = cfg.get("CHECK_INTERVAL_MINUTES", 15)
    scheduler.add_job(
        fast_cycle, "interval", minutes=fast_interval,
        max_instances=1, misfire_grace_time=30,
    )
    scheduler.add_job(
        monitor_cycle, "interval", minutes=full_interval,
        max_instances=1, misfire_grace_time=120,
    )
    scheduler.start()
    RUNTIME_CONFIG["_SCHEDULER"] = scheduler
    RUNTIME_CONFIG["_FAST_INTERVAL_CURRENT"] = fast_interval
    logging.info(
        f"Diar Car Buy AI v3.0 запущен. "
        f"Быстрый цикл: {fast_interval} мин | Полный цикл: {full_interval} мин"
    )

    async with app:
        await app.start()
        await app.updater.start_polling()
        logging.info("Telegram бот слушает команды.")
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


def main():
    """Инициализация логирования, БД и запуск event loop."""
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    from config import RUNTIME_CONFIG, load_config
    _cfg = load_config()
    _token = _cfg.get("TELEGRAM_BOT_TOKEN", "")

    class _TokenFilter(logging.Filter):
        def filter(self, record):
            if _token:
                try:
                    msg = record.getMessage()
                    if _token in msg:
                        record.msg = msg.replace(_token, "***TOKEN***")
                        record.args = ()
                except Exception:
                    pass
            return True

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    token_filter = _TokenFilter()

    file_handler = logging.FileHandler("agent.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    file_handler.addFilter(token_filter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    console_handler.addFilter(token_filter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()  # сбрасываем всё что могло навесить APScheduler при импорте
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    init_db()
    asyncio.run(run())


if __name__ == "__main__":
    main()
