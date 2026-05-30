"""
main.py — точка входа Diar Car Buy AI.

Запускает Telegram-бота с командами и планировщик, который с заданным
интервалом обходит парсеры, анализирует новые/подешевевшие объявления и
отправляет уведомления по тем, что прошли порог DCB Score.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, CommandHandler

from config import load_config
from database import (
    init_db,
    mark_seen,
    increment_analyzed,
    was_notified,
    price_dropped,
    increment_notified,
)
from analyzer import analyze_listing
from notifier import send_notification
from bot_commands import get_command_handlers
from parsers import avito, drom


async def monitor_cycle():
    """
    Один цикл мониторинга: парсинг, анализ и рассылка уведомлений.

    Уважает флаг PAUSED. Анализируются только новые объявления или те, у
    которых упала цена. Любые ошибки логируются, цикл не должен падать.
    """
    cfg = load_config()
    if cfg.get("PAUSED"):
        logging.info("Цикл мониторинга пропущен: PAUSED=True")
        return

    listings = []
    try:
        listings += avito.parse()
        listings += drom.parse()
    except Exception as e:
        logging.error(f"Ошибка парсинга в monitor_cycle: {e}")

    for listing in listings:
        try:
            lid = listing["listing_id"]
            src = listing["source"]

            mark_seen(lid, src, listing["price"])
            increment_analyzed()

            # Анализируем новое объявление либо то, где упала цена
            should_analyze = (not was_notified(lid, src)) or price_dropped(lid, src)[0]
            if not should_analyze:
                continue

            result = analyze_listing(listing)
            cfg = load_config()

            if result["dcb_score"] >= cfg.get("MIN_DCB_SCORE", 70):
                send_notification(result)
                increment_notified(result["dcb_score"])
        except Exception as e:
            logging.error(f"Ошибка обработки объявления: {e}")


def main():
    """Инициализировать логирование, БД, бота и планировщик; запустить polling."""
    logging.basicConfig(
        filename="agent.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load_config()
    init_db()

    token = cfg.get("TELEGRAM_BOT_TOKEN", "")
    app = ApplicationBuilder().token(token).build()

    # Регистрируем обработчики команд бота
    for cmd, handler in get_command_handlers():
        app.add_handler(CommandHandler(cmd, handler))

    # Планировщик периодического мониторинга
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        monitor_cycle,
        "interval",
        minutes=cfg.get("CHECK_INTERVAL_MINUTES", 20),
    )
    scheduler.start()

    logging.info("Diar Car Buy AI запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
