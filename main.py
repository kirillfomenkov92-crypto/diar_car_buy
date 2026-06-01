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
    for listing in listings:
        try:
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
                send_notification(result)
                increment_notified(result["dcb_score"])
                age = result.get("age_minutes", 999)
                if age < 999:
                    record_response_time(lid, src, age)
                logging.info(
                    f"{tag} ✅ {listing['title']} | {listing['price']:,}₽"
                    f" | Score:{result['dcb_score']} | {src}"
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
    """Быстрый цикл — Авито с интервальным контролем + детект разблокировки."""
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

    # Уведомление о разблокировке
    was_blocked = RUNTIME_CONFIG.get("AVITO_WAS_BLOCKED", False)
    if was_blocked and len(avito_results) > 0:
        RUNTIME_CONFIG["AVITO_WAS_BLOCKED"] = False
        notify_text = f"Авито разблокирован — получено {len(avito_results)} объявлений"
        await asyncio.to_thread(_send_tg_message, notify_text)
        logging.info(f"[FAST] {notify_text}")

    fresh = [
        l for l in listings
        if calculate_listing_age_minutes(l.get("published_at", "")) <= 30
    ]
    logging.info(f"[FAST] Свежих (до 30 мин): {len(fresh)} из {len(listings)}")

    await _process_listings(fresh, tag="[FAST]")


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

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler("agent.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()  # сбрасываем всё что могло навесить APScheduler при импорте
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    init_db()
    asyncio.run(run())


if __name__ == "__main__":
    main()
