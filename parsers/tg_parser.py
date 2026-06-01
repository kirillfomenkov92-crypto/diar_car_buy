# parsers/tg_parser.py — парсер Telegram для Diar Car Buy AI v3.0.
# Самый быстрый источник: объявления появляются за 5-15 минут до Avito.
# Использует Telethon (MTProto). Синхронная обёртка для вызова из main.py.

import re
import asyncio
import threading
import logging

from config import load_config, RUNTIME_CONFIG

SOURCE = "telegram"

# Ключевые слова продажи
SALE_KEYWORDS = ["продам", "продаю", "продаётся"]


def extract_year_from_text(text: str) -> int:
    """Извлечь год выпуска из текста объявления."""
    match = re.search(r"\b(199\d|200\d|201\d|202[0-6])\b", text)
    return int(match.group(1)) if match else 0


def extract_mileage_from_text(text: str) -> int:
    """Извлечь пробег из текста объявления."""
    patterns = [
        r"пробег\s*[\:\-]?\s*(\d+)\s*(?:тыс|000|км)",
        r"(\d+)\s*тыс\s*км",
        r"(\d+)\s*000\s*км",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            val = int(match.group(1))
            if val < 1000:
                val *= 1000
            return val
    return 0


def extract_price_from_text(text: str) -> int:
    """Извлечь цену из текста Telegram-сообщения."""
    patterns = [
        r"(\d[\d\s]{2,6})\s*₽",
        r"(\d[\d\s]{2,6})\s*руб",
        r"цена\s*[\:\-]?\s*(\d[\d\s]{2,6})",
        r"(\d+)\s*тыс(?:яч)?(?:\s*рублей)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            val_str = match.group(1).replace(" ", "")
            try:
                val = int(val_str)
                if val < 1000 and "тыс" in text[max(0, match.start()-5):match.end()+5].lower():
                    val *= 1000
                if 10000 < val < 500000:
                    return val
            except Exception:
                pass
    return 0


async def _parse_channels() -> list:
    """Async: читать последние сообщения из Telegram каналов/чатов."""
    try:
        from telethon import TelegramClient
    except ImportError:
        logging.warning("TG: telethon не установлен, пропускаем")
        return []

    load_config()
    api_id = RUNTIME_CONFIG.get("TG_API_ID")
    api_hash = RUNTIME_CONFIG.get("TG_API_HASH")
    session = RUNTIME_CONFIG.get("TG_SESSION_NAME", "diar_session")
    channels = RUNTIME_CONFIG.get("TG_CHANNELS", [])
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)

    if not api_id or not api_hash:
        logging.warning("TG: TG_API_ID/TG_API_HASH не заполнены в config.yaml — парсер отключён")
        return []

    results = []
    try:
        async with TelegramClient(session, int(api_id), api_hash) as client:
            for channel in channels:
                try:
                    messages = await client.get_messages(channel, limit=20)
                    for msg in messages:
                        if not msg.text:
                            continue
                        text = msg.text
                        text_lower = text.lower()

                        if not any(k in text_lower for k in SALE_KEYWORDS):
                            continue

                        price = extract_price_from_text(text)
                        if not price or price > max_price:
                            continue

                        channel_name = channel.replace("@", "")
                        listing = {
                            "listing_id": f"tg_{msg.id}_{channel_name}",
                            "source": SOURCE,
                            "title": text[:80].strip(),
                            "price": price,
                            "year": extract_year_from_text(text),
                            "mileage": extract_mileage_from_text(text),
                            "city": "Москва",
                            "description": text,
                            "photo_count": 1 if msg.photo else 0,
                            "photo_urls": [],
                            "seller_ads_count": 1,
                            "seller_id": str(msg.sender_id or ""),
                            "published_at": msg.date.isoformat() if msg.date else "",
                            "listing_url": f"https://t.me/{channel_name}/{msg.id}",
                            "is_regional": False,
                        }
                        results.append(listing)

                except Exception as e:
                    logging.error(f"TG канал {channel}: {e}")

    except Exception as e:
        logging.error(f"TG клиент: {e}")

    return results


def parse() -> list:
    """Синхронная точка входа. Запускает async парсинг в отдельном потоке с собственным event loop."""
    load_config()
    if not RUNTIME_CONFIG.get("TG_API_ID") or not RUNTIME_CONFIG.get("TG_API_HASH"):
        logging.warning("TG: TG_API_ID/TG_API_HASH не заполнены в config.yaml — парсер отключён")
        return []

    result = []

    def _run():
        nonlocal result
        try:
            result = asyncio.run(_parse_channels())
        except Exception as e:
            logging.error(f"TG asyncio.run: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=10)

    if thread.is_alive():
        logging.warning("TG парсер завис — пропускаем цикл")
        return []

    logging.info(f"Telegram: получено {len(result)} объявлений")
    return result
