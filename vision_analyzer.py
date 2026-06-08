# vision_analyzer.py — второй агент Diar Car Buy AI v5.0: анализатор фото.
# Работает В ПАРЕ с текстовым Groq-агентом (analyzer.py), не заменяя его.
# Gemini Vision смотрит фотографии ТОЛЬКО для прошедших порог кандидатов
# (см. analyzer.analyze_listing) — это экономит запросы Vision.
# Может ТОЛЬКО снизить DCB Score (штраф), если видит проблемы кузова.

import re
import logging

import requests
from google import genai
from google.genai import types

from config import RUNTIME_CONFIG

# Модель Vision (можно переопределить в config.yaml / .env через GEMINI_VISION_MODEL).
DEFAULT_VISION_MODEL = "gemini-2.0-flash"

# Сколько фото максимум скачиваем и отдаём в Vision (хватает для оценки кузова).
MAX_PHOTOS = 5
# Лимит размера одного фото (защита от гигантских orig — Vision хватает превью).
MAX_PHOTO_BYTES = 6 * 1024 * 1024

VISION_PROMPT = """Ты опытный перекупщик авто. Смотри на фото машины
{model} {year}, цена {price}₽.

Ищи ВИЗУАЛЬНЫЕ проблемы которые видно на фото:
- Ржавчина: арки, пороги, низ дверей, капот
- Гнилой металл, сквозная коррозия
- Битый/крашеный кузов: разные оттенки, неровные зазоры
- Вмятины, повреждения
- Состояние салона (убитый/нормальный)

Ответь СТРОГО в формате:
СОСТОЯНИЕ: [чистая / есть вопросы / гнилая-битая]
ПРОБЛЕМЫ: [перечисли что видишь, или "не выявлено"]
ШТРАФ: [число 0-50, насколько снизить оценку]"""


def _empty(visual_ok=None) -> dict:
    """Нейтральный результат — Vision не применялся/нет данных (Score не трогаем)."""
    return {"photo_score_penalty": 0, "visual_issues": [], "visual_ok": visual_ok}


def _download_photos(photo_urls: list) -> list:
    """Скачать первые MAX_PHOTOS фото. Возвращает список bytes (JPEG/др.)."""
    images = []
    for url in photo_urls[:MAX_PHOTOS]:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200 and resp.content:
                if len(resp.content) <= MAX_PHOTO_BYTES:
                    images.append(resp.content)
                else:
                    logging.debug(f"Vision: фото слишком большое, пропуск {url}")
        except Exception as e:
            logging.debug(f"Vision: не скачал фото {url}: {e}")
    return images


def analyze_photos(photo_urls: list, listing: dict) -> dict:
    """
    Анализирует фото машины через Gemini Vision.
    Возвращает: {
        'photo_score_penalty': int,  # сколько вычесть из DCB Score (0..50)
        'visual_issues': list,        # найденные проблемы кузова/салона
        'visual_ok': bool             # чистая по фото (True) / проблемная (False) / неизвестно (None)
    }
    """
    if not photo_urls:
        return _empty()

    api_key = RUNTIME_CONFIG.get("GEMINI_API_KEY", "")
    if not api_key:
        logging.warning("Vision: GEMINI_API_KEY не задан — пропуск фото-анализа")
        return _empty()

    images = _download_photos(photo_urls)
    if not images:
        logging.debug("Vision: ни одно фото не скачалось — пропуск")
        return _empty()

    model_name = RUNTIME_CONFIG.get("GEMINI_VISION_MODEL", DEFAULT_VISION_MODEL)
    prompt = VISION_PROMPT.format(
        model=listing.get("title", ""),
        year=listing.get("year", ""),
        price=listing.get("price", 0),
    )

    try:
        client = genai.Client(api_key=api_key)
        # contents: текстовый промпт + изображения (canonical способ google-genai 2.x)
        contents = [prompt]
        for img in images:
            contents.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))

        response = client.models.generate_content(model=model_name, contents=contents)
        text = response.text or ""

        penalty_m = re.search(r"ШТРАФ:\s*(\d+)", text)
        penalty = int(penalty_m.group(1)) if penalty_m else 0
        penalty = max(0, min(50, penalty))

        issues = []
        prob_m = re.search(r"ПРОБЛЕМЫ:\s*(.+)", text)
        if prob_m and "не выявлено" not in prob_m.group(1).lower():
            issues = [prob_m.group(1).strip()]

        low = text.lower()
        visual_ok = "гнилая" not in low and "битая" not in low

        logging.info(
            f"Vision: {listing.get('title')} ({len(images)} фото) → "
            f"штраф {penalty}, {issues}"
        )
        return {
            "photo_score_penalty": penalty,
            "visual_issues": issues,
            "visual_ok": visual_ok,
        }
    except Exception as e:
        logging.error(f"Vision анализ: {e}")
        return _empty()
