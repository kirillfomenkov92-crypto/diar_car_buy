# notifier.py — отправка уведомлений в Telegram для Diar Car Buy AI v3.0.

import logging
import time

import requests

from config import load_config, RUNTIME_CONFIG
from database import was_notified, score_changed, mark_notified

MAX_MESSAGE_LEN = 4000


def _send_part(token: str, chat_id: str, text: str, retries: int = 3,
               parse_mode: str = None, reply_markup: dict = None) -> bool:
    """Отправить одну часть сообщения одному chat_id. True если доставлено."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
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
    Использует HTML-карточку из build_notification() если доступна,
    иначе fallback на plain-text из full_analysis.
    """
    try:
        load_config()
        listing = result.get("listing", {})
        listing_id = listing.get("listing_id")
        source = listing.get("source")
        dcb_score = result.get("dcb_score", 0)

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

        # HTML-карточка из bot_interface (красивое форматирование)
        text = ""
        parse_mode = None
        reply_markup_dict = None
        try:
            from bot_interface import build_notification
            html_text, keyboard = build_notification(result)
            if html_text:
                text = html_text
                parse_mode = "HTML"
                reply_markup_dict = keyboard.to_dict() if keyboard else None
        except Exception as e:
            logging.warning(f"build_notification недоступен: {e} — fallback на plain text")

        # Fallback: сырой LLM-текст + стратегия + ссылка
        if not text:
            strategy = result.get("strategy", {})
            arbitrage = result.get("arbitrage")
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
            body = result.get("full_analysis", "")
            footer_parts = []
            if strategy:
                footer_parts.append(f"📞 ЗВОНИТЬ: {strategy.get('best_time', '')}")
                footer_parts.append(f"💬 \"{strategy.get('call_script', '')}\"")
            footer_parts.append(f"⏱ {result.get('urgency_label', '')}")
            footer_parts.append(f"🔗 {listing.get('listing_url', '')}")
            text = f"{header}{body}\n\n{'\n'.join(footer_parts)}"

        # Разбивка на части (4000 символов — лимит Telegram)
        parts = [text[i:i + MAX_MESSAGE_LEN] for i in range(0, len(text), MAX_MESSAGE_LEN)]

        token = RUNTIME_CONFIG.get("TELEGRAM_BOT_TOKEN", "")
        recipients = _recipients()

        if not token or not recipients:
            logging.error("Не задан TELEGRAM_BOT_TOKEN или список получателей")
            return

        # Шлём всем: клавиатура только к первой части, остальные — plain
        send_ok = False
        for chat_id in recipients:
            ok_parts = []
            for i, part in enumerate(parts):
                kb = reply_markup_dict if i == 0 else None
                delivered = _send_part(token, chat_id, part,
                                       parse_mode=parse_mode, reply_markup=kb)
                ok_parts.append(delivered)
            if all(ok_parts):
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
