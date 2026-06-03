# notifier.py — отправка уведомлений в Telegram для Diar Car Buy AI v3.0.

import logging
import time

import requests

from config import load_config, RUNTIME_CONFIG
from database import was_notified, score_changed, mark_notified

MAX_MESSAGE_LEN = 4000


def _send_part(token: str, chat_id: str, text: str, retries: int = 3) -> bool:
    """Отправить одну часть сообщения одному chat_id. True если доставлено."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(retries):
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=15,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            if attempt == retries - 1:
                logging.error(f"Telegram send {chat_id} failed after {retries} attempts: {e}")
            else:
                time.sleep(2 ** attempt)
    return False


def _recipients() -> list:
    """Список получателей уведомлений: ALLOWED_USER_IDS или TELEGRAM_CHAT_ID."""
    ids = RUNTIME_CONFIG.get("ALLOWED_USER_IDS", [])
    if isinstance(ids, (str, int)):
        ids = [ids]
    if not ids:
        chat = RUNTIME_CONFIG.get("TELEGRAM_CHAT_ID", "")
        ids = [chat] if chat else []
    return ids


def send_notification(result: dict):
    """
    Отправить уведомление по результату анализа объявления.
    - Пропускает если уже уведомляли и DCB Score не изменился.
    - Добавляет заголовок об арбитраже / снижении цены.
    - Разбивает длинные сообщения на части по 4000 символов.
    """
    try:
        load_config()
        listing = result.get("listing", {})
        listing_id = listing.get("listing_id")
        source = listing.get("source")
        dcb_score = result.get("dcb_score", 0)
        strategy = result.get("strategy", {})
        arbitrage = result.get("arbitrage")

        # Финальная проверка цены — блокируем уведомления дороже бюджета
        price = listing.get("price", 0)
        max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)
        if price > max_price:
            logging.warning(
                f"Блокировка уведомления: цена {price:,} > MAX_PRICE {max_price:,} "
                f"({listing_id})"
            )
            return

        # Дедупликация: пропускаем если оценка не изменилась
        if was_notified(listing_id, source):
            if not score_changed(listing_id, source, dcb_score):
                logging.info(f"Пропуск {listing_id}: оценка не изменилась")
                return

        # Заголовок
        header_parts = []
        if arbitrage:
            header_parts.append(
                f"🚚 АРБИТРАЖ из {arbitrage['city']}! "
                f"Прибыль: +{arbitrage['net_profit']:,} ₽".replace(",", " ")
            )
        if result.get("price_dropped"):
            header_parts.append(
                f"🔄 ОБНОВЛЕНО — цена упала на {result['drop_amount']:,} ₽".replace(",", " ")
            )
        header = "\n".join(header_parts) + "\n\n" if header_parts else ""

        # Основное тело
        body = result.get("full_analysis", "")

        # Стратегия звонка
        footer_parts = []
        if strategy:
            footer_parts.append(f"📞 ЗВОНИТЬ: {strategy.get('best_time', '')}")
            footer_parts.append(f"💬 \"{strategy.get('call_script', '')}\"")
        footer_parts.append(f"⏱ {result.get('urgency_label', '')}")
        footer_parts.append(f"🔗 {listing.get('listing_url', '')}")
        footer = "\n".join(footer_parts)

        message = f"{header}{body}\n\n{footer}"

        # Разбивка на части
        parts = [message[i:i + MAX_MESSAGE_LEN]
                 for i in range(0, len(message), MAX_MESSAGE_LEN)]

        token = RUNTIME_CONFIG.get("TELEGRAM_BOT_TOKEN", "")
        recipients = _recipients()

        if not token or not recipients:
            logging.error("Не задан TELEGRAM_BOT_TOKEN или список получателей")
            return

        # Шлём всем админам. send_ok=True если доставлено хотя бы одному —
        # помечаем как уведомлённое только при успешной доставке.
        send_ok = False
        for chat_id in recipients:
            delivered = all(_send_part(token, chat_id, part) for part in parts)
            if delivered:
                send_ok = True
            else:
                logging.warning(f"Доставка {chat_id} не удалась: {listing_id}")

        if not send_ok:
            logging.warning(f"Уведомление НЕ помечено (отправка провалилась): {listing_id}")
            return

        if not mark_notified(listing_id, source, dcb_score):
            logging.info(f"Пропуск {listing_id}: уже помечено другим циклом")
            return

        logging.info(
            f"Уведомление отправлено {len(recipients)} админам: "
            f"{listing_id} ({source}), score={dcb_score}"
        )

    except Exception as e:
        logging.error(f"Ошибка send_notification: {e}")
