"""
analyzer.py — анализ объявления через Claude API для Diar Car Buy AI.

Собирает контекст из БД (история цены, срок на рынке, личная статистика по
модели), формирует user-сообщение с учётом сезонности и отправляет его в
Claude. Из ответа извлекаются DCB Score и вердикт.
"""

import re
import logging
from datetime import datetime

import anthropic

from config import load_config
from database import price_dropped, days_on_market, get_model_stats

# Путь к файлу системного промпта
SYSTEM_PROMPT_PATH = "prompts/system.txt"

# Названия месяцев для подстановки в сообщение
MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _read_system_prompt():
    """Прочитать системный промпт из файла, вернуть пустую строку при ошибке."""
    try:
        with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Ошибка чтения системного промпта: {e}")
        return ""


def _build_user_message(listing, days, dropped, drop_amount, model_stats, month_name):
    """
    Собрать текст user-сообщения для Claude из данных объявления и контекста.

    Добавляет блоки про срок на рынке, снижение цены и личную статистику,
    только если соответствующие условия выполнены.
    """
    message = f"""Проанализируй объявление:

Название: {listing.get('title', '')}
Цена: {listing.get('price', 0)} ₽
Год: {listing.get('year', 0)}
Пробег: {listing.get('mileage', 0)} км
Город: {listing.get('city', '')}
Описание: {listing.get('description', '')}
Количество фото: {listing.get('photo_count', 0)}
Объявлений у продавца: {listing.get('seller_ads_count', 0)}

Текущий месяц: {month_name}. Учти сезонный коэффициент.
"""

    if days >= 7:
        message += (
            f"\nОбъявление на рынке уже {days} дней.\n"
            "Продавец мотивирован. +10 к оценке потенциала торга.\n"
        )

    if dropped:
        message += (
            f"\nЦена снижена на {drop_amount} ₽ с публикации.\n"
            "Сигнал срочной продажи.\n"
        )

    if model_stats:
        message += (
            "\nЛичная статистика по данной модели:\n"
            f"средняя прибыль {model_stats.get('avg_profit', 0)} ₽,\n"
            f"средний срок продажи {model_stats.get('avg_days', 0)} дней.\n"
            "Учти в прогнозе.\n"
        )

    return message


def analyze_listing(listing):
    """
    Проанализировать одно объявление и вернуть результат с DCB Score.

    Возвращает dict с полями dcb_score, verdict, full_analysis, listing,
    price_dropped, drop_amount, days_on_market. При ошибке dcb_score = 0.
    """
    listing_id = listing.get("listing_id")
    source = listing.get("source")

    # Шаг 1. Контекст из БД
    dropped, drop_amount = price_dropped(listing_id, source)
    days = days_on_market(listing_id, source)
    model_stats = get_model_stats(listing.get("title", ""))

    # Шаг 2. Текущий месяц
    month_name = MONTH_NAMES[datetime.now().month - 1]

    # Шаг 3. user-сообщение
    user_message = _build_user_message(
        listing, days, dropped, drop_amount, model_stats, month_name
    )

    dcb_score = 0
    verdict = ""
    full_text = ""

    # Шаг 4. Вызов Claude API
    try:
        cfg = load_config()
        client = anthropic.Anthropic(api_key=cfg.get("CLAUDE_API_KEY", ""))
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=_read_system_prompt(),
            messages=[{"role": "user", "content": user_message}],
        )
        full_text = response.content[0].text
    except Exception as e:
        logging.error(f"Ошибка вызова Claude API: {e}")

    # Шаг 5. Парсинг ответа
    try:
        score_match = re.search(r"DCB SCORE[:\s]+(\d+)", full_text)
        if score_match:
            dcb_score = int(score_match.group(1))

        verdict_match = re.search(r"ВЕРДИКТ[:\s]+(.+)", full_text)
        if verdict_match:
            verdict = verdict_match.group(1).strip()
    except Exception as e:
        logging.error(f"Ошибка парсинга ответа Claude: {e}")

    return {
        "dcb_score": dcb_score,
        "verdict": verdict,
        "full_analysis": full_text,
        "listing": listing,
        "price_dropped": dropped,
        "drop_amount": drop_amount,
        "days_on_market": days,
    }
