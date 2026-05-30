"""
notifier.py — отправка уведомлений в Telegram для Diar Car Buy AI.

Решает, нужно ли отправлять сообщение по объявлению (с учётом того, было ли
оно уже отправлено и изменился ли DCB Score / цена), формирует текст и шлёт
его через Telegram Bot API.
"""

import logging

import requests

from config import load_config
from database import was_notified, score_changed, mark_notified


def _send_telegram_message(text):
    """Отправить текстовое сообщение в Telegram через Bot API."""
    try:
        cfg = load_config()
        token = cfg.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = cfg.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            logging.error("Не задан TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        resp = requests.post(url, data=payload, timeout=20)
        resp.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")
        return False


def send_notification(result):
    """
    Отправить уведомление по результату анализа объявления.

    Логика дедупликации:
    - если уведомление уже было и DCB Score не изменился — пропустить;
    - если цена упала — добавить заголовок об обновлении;
    - иначе отправить обычным образом.
    После успешной отправки отмечает объявление как уведомлённое.
    """
    try:
        listing = result.get("listing", {})
        listing_id = listing.get("listing_id")
        source = listing.get("source")
        dcb_score = result.get("dcb_score", 0)

        header = ""

        if was_notified(listing_id, source):
            # Уже уведомляли — отправляем повторно только при изменениях
            if not score_changed(listing_id, source, dcb_score):
                logging.info(f"Пропуск {listing_id}: оценка не изменилась")
                return
            if result.get("price_dropped"):
                drop_amount = result.get("drop_amount", 0)
                header = f"🔄 ОБНОВЛЕНО — цена упала на {drop_amount} ₽\n"

        # Формируем итоговый текст сообщения
        text = (
            f"{header}"
            f"{result.get('full_analysis', '')}\n"
            f"🔗 {listing.get('listing_url', '')}"
        )

        if _send_telegram_message(text):
            mark_notified(listing_id, source, dcb_score)
            logging.info(f"Отправлено уведомление по {listing_id} ({source})")
    except Exception as e:
        logging.error(f"Ошибка send_notification: {e}")
