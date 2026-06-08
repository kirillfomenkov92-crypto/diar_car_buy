# utils/watchdog.py — самоконтроль бота: heartbeat и health_check.

import time
import logging

import requests

from config import RUNTIME_CONFIG

# Порог молчания — должен быть больше максимального интервала цикла (20 мин = 1200 с)
HEARTBEAT_TIMEOUT = 1500  # 25 минут


def record_heartbeat():
    """Записать время последнего успешного цикла."""
    RUNTIME_CONFIG["LAST_HEARTBEAT"] = time.time()


def _send_telegram(chat_id, text: str):
    """Отправить сообщение конкретному chat_id (синхронно)."""
    token = RUNTIME_CONFIG.get("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logging.error(f"watchdog: не удалось отправить тревогу: {e}")


def _admin_ids() -> list:
    """Список chat_id админов из ALLOWED_USER_IDS / TELEGRAM_CHAT_ID."""
    ids = RUNTIME_CONFIG.get("ALLOWED_USER_IDS", [])
    if isinstance(ids, (str, int)):
        ids = [ids]
    if not ids:
        chat = RUNTIME_CONFIG.get("TELEGRAM_CHAT_ID", "")
        if chat:
            ids = [chat]
    return ids


def health_check():
    """Проверить heartbeat. Если циклов не было 15+ мин — тревога админам.
    Тревога шлётся один раз до восстановления (флаг _HEALTH_ALERTED)."""
    last = RUNTIME_CONFIG.get("LAST_HEARTBEAT", 0)
    if not last:
        return  # ещё ни одного цикла не было — нормально на старте

    silence = time.time() - last
    if silence > HEARTBEAT_TIMEOUT:
        if not RUNTIME_CONFIG.get("_HEALTH_ALERTED"):
            mins = int(silence / 60)
            for chat_id in _admin_ids():
                _send_telegram(
                    chat_id,
                    f"⚠️ Бот не делал циклов {mins}+ минут — проверь работу.",
                )
            RUNTIME_CONFIG["_HEALTH_ALERTED"] = True
            logging.warning(f"watchdog: тревога — молчание {mins} мин")
    else:
        # Восстановился — сбрасываем флаг чтобы следующая тревога сработала
        if RUNTIME_CONFIG.get("_HEALTH_ALERTED"):
            RUNTIME_CONFIG["_HEALTH_ALERTED"] = False
            logging.info("watchdog: heartbeat восстановлен")
