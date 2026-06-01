# parsers/vk_parser.py — парсер ВКонтакте для Diar Car Buy AI v3.0.
# Объявления из VK групп появляются РАНЬШЕ чем на Avito.
# Использует официальный VK API — без парсинга HTML.

import re
import logging

import requests

from config import load_config, RUNTIME_CONFIG

SOURCE = "vk"
VK_API = "https://api.vk.com/method"

# Ключевые слова для фильтрации постов
SALE_KEYWORDS = ["продам", "продаю", "продаётся", "цена", "₽", "руб", "тыс"]
CAR_KEYWORDS = [
    "лада", "приора", "логан", "focus", "spectra", "nexia",
    "авто", "машина", "автомобил", "lada", "renault", "chevrolet",
    "kia", "hyundai", "ford", "daewoo", "nissan",
]


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


def _extract_price(text: str, max_price: int) -> int:
    """Извлечь цену из текста поста VK."""
    patterns = [
        r"(\d[\d\s]{2,6})\s*₽",
        r"(\d[\d\s]{2,6})\s*руб",
        r"цена\s*[\:\-]?\s*(\d[\d\s]{2,6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            val_str = match.group(1).replace(" ", "")
            try:
                val = int(val_str)
                if 10000 < val < max_price * 2:
                    return val
            except Exception:
                pass

    # "N тыс" формат
    match = re.search(r"(\d+)\s*тыс(?:яч)?(?:\s*(?:рублей|руб|₽))?", text.lower())
    if match:
        val = int(match.group(1)) * 1000
        if 10000 < val < max_price * 2:
            return val

    return 0


def parse_vk_groups() -> list:
    """Парсить посты из VK групп с объявлениями о продаже авто."""
    load_config()
    token = RUNTIME_CONFIG.get("VK_ACCESS_TOKEN", "")
    if not token:
        logging.warning("VK: VK_ACCESS_TOKEN не заполнен в config.yaml — парсер отключён")
        return []

    groups = RUNTIME_CONFIG.get("VK_GROUPS", [])
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 140000)
    results = []

    for group in groups:
        try:
            response = requests.get(
                f"{VK_API}/wall.get",
                params={
                    "domain": group,
                    "count": 20,
                    "access_token": token,
                    "v": "5.131",
                },
                timeout=10,
            )
            data = response.json()

            if "error" in data:
                logging.warning(f"VK {group}: ошибка API: {data['error']}")
                continue

            for post in data.get("response", {}).get("items", []):
                try:
                    text = post.get("text", "")
                    if not text:
                        continue

                    text_lower = text.lower()
                    has_sale = any(k in text_lower for k in SALE_KEYWORDS)
                    has_car = any(k in text_lower for k in CAR_KEYWORDS)
                    if not (has_sale and has_car):
                        continue

                    price = _extract_price(text, max_price)
                    if not price or price > max_price:
                        continue

                    owner_id = post.get("owner_id", "")
                    post_id = post.get("id", "")

                    listing = {
                        "listing_id": f"vk_{post_id}",
                        "source": SOURCE,
                        "title": text[:80].strip(),
                        "price": price,
                        "year": extract_year_from_text(text),
                        "mileage": extract_mileage_from_text(text),
                        "city": "Москва",
                        "description": text,
                        "photo_count": len(post.get("attachments", [])),
                        "photo_urls": [],
                        "seller_ads_count": 1,
                        "seller_id": str(post.get("from_id", "")),
                        "published_at": str(post.get("date", "")),
                        "listing_url": f"https://vk.com/wall{owner_id}_{post_id}",
                        "is_regional": False,
                    }
                    results.append(listing)

                except Exception as e:
                    logging.error(f"VK {group}: ошибка разбора поста: {e}")

        except Exception as e:
            logging.error(f"VK парсинг {group}: {e}")

    return results


def extract_price_from_text(text: str) -> int:
    """Публичный alias для извлечения цены из текста поста."""
    load_config()
    max_price = RUNTIME_CONFIG.get("MAX_PRICE", 500000)
    return _extract_price(text, max_price)


def parse() -> list:
    """Точка входа для main.py."""
    return parse_vk_groups()
