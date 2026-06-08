# analyzer.py — главный анализатор: синтез всех модулей + LLM fallback цепочка.

import re
import time
import logging
from datetime import datetime

import requests
from openai import OpenAI

from config import load_config, RUNTIME_CONFIG
from database import (
    price_dropped, days_on_market, get_model_stats, save_arbitrage,
)
from market_analyzer import analyze_market
from seller_profiler import profile_seller
from fraud_detector import detect_fraud
from deal_strategist import build_strategy
from arbitrage_detector import check_arbitrage
from speed_monitor import calculate_listing_age_minutes, get_urgency_label

SYSTEM_PROMPT_PATH = "prompts/system.txt"

MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# Цепочка провайдеров: Groq (бесплатный) → DeepSeek (платный) → локальный скоринг
LLM_PROVIDERS = [
    {
        "name": "groq",
        "key_config": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "disabled_flag": "GROQ_DISABLED",
        "error_codes": [429, 402, 401],
    },
    {
        "name": "deepseek",
        "key_config": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "disabled_flag": "DEEPSEEK_DISABLED",
        "error_codes": [402, 401],
    },
]


def _read_system_prompt() -> str:
    try:
        with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Ошибка чтения системного промпта: {e}")
        return ""


def _notify_llm_down(provider_name: str = "LLM"):
    token = RUNTIME_CONFIG.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = RUNTIME_CONFIG.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    text = (
        f"⚠️ {provider_name} недоступен (нет баланса или ключ неверный).\n"
        "Бот автоматически переключился на следующий провайдер."
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        logging.warning(f"{provider_name} down: уведомление отправлено админам")
    except Exception as e:
        logging.error(f"Не удалось отправить уведомление о {provider_name}: {e}")


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def _try_provider(provider: dict, system_prompt: str, user_msg: str) -> str | None:
    """Пробует один LLM-провайдер. При 429 — пауза 30 сек и одна повторная попытка."""
    name = provider["name"]
    api_key = RUNTIME_CONFIG.get(provider["key_config"], "")
    if not api_key:
        return None

    for attempt in range(2):
        try:
            client = OpenAI(api_key=api_key, base_url=provider["base_url"])
            response = client.chat.completions.create(
                model=provider["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=1000,
                timeout=30,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            err_str = str(e)
            # 429 rate limit — одна повторная попытка через 30 сек
            if "429" in err_str and attempt == 0:
                logging.warning(f"LLM {name}: 429 rate limit — пауза 30 сек")
                time.sleep(30)
                continue
            # 402 нет баланса — отключаем провайдер
            if "402" in err_str or "Insufficient Balance" in err_str:
                RUNTIME_CONFIG[provider["disabled_flag"]] = True
                _notify_llm_down(name)
                logging.warning(f"LLM {name}: 402 — отключён, пополните баланс")
            # 401 неверный ключ — отключаем провайдер
            elif "401" in err_str or "Unauthorized" in err_str or "Invalid API key" in err_str:
                RUNTIME_CONFIG[provider["disabled_flag"]] = True
                logging.warning(f"LLM {name}: 401 — неверный ключ, отключён")
            else:
                logging.error(f"LLM {name} ошибка: {e}")
            return None

    return None


def get_llm_response(system_prompt: str, user_msg: str) -> tuple[str, str]:
    """Пробует провайдеров по цепочке Groq → DeepSeek.
    Возвращает (текст_ответа, имя_провайдера) или ('', '') если все недоступны."""
    for i, provider in enumerate(LLM_PROVIDERS):
        if RUNTIME_CONFIG.get(provider["disabled_flag"]):
            continue
        if not RUNTIME_CONFIG.get(provider["key_config"]):
            continue

        name = provider["name"]
        result = _try_provider(provider, system_prompt, user_msg)
        if result:
            return result, name

        # Этот провайдер не ответил — находим следующего и логируем переключение
        remaining = [
            p for p in LLM_PROVIDERS[i + 1:]
            if not RUNTIME_CONFIG.get(p["disabled_flag"])
            and RUNTIME_CONFIG.get(p["key_config"])
        ]
        if remaining:
            logging.warning(f"LLM переключился: {name} → {remaining[0]['name']}")

    return "", ""


def analyze_listing(listing: dict) -> dict:
    """
    Главный анализатор объявления.
    Синтезирует рыночный анализ, профиль продавца, детектор фрода,
    стратегию сделки, арбитраж и LLM (Groq → DeepSeek → локальный).
    Возвращает полный dict с dcb_score, verdict, full_analysis и всеми модулями.
    """
    load_config()

    listing_id = listing.get("listing_id", "")
    source = listing.get("source", "")

    # ── Все аналитические модули ───────────────────────────────────────────
    market = analyze_market(listing.get("title", ""), listing.get("price", 0))
    seller = profile_seller(listing)
    fraud = detect_fraud(listing)
    strategy = build_strategy(listing, market, seller, fraud)
    arbitrage = check_arbitrage(listing)

    # Сохранить арбитражную возможность в БД
    if arbitrage:
        try:
            save_arbitrage(
                listing_id, source,
                arbitrage.get("city", ""),
                listing.get("listing_url", ""),
                arbitrage["region_price"],
                arbitrage["moscow_estimate"],
                arbitrage["transport_cost"],
                arbitrage["net_profit"],
            )
        except Exception as e:
            logging.error(f"Ошибка сохранения арбитража: {e}")

    # ── Контекст из БД ────────────────────────────────────────────────────
    dropped, drop_amount = price_dropped(listing_id, source)
    days = days_on_market(listing_id, source)
    model_stats = get_model_stats(listing.get("title", ""))

    # ── Возраст объявления и срочность ───────────────────────────────────
    age_minutes = calculate_listing_age_minutes(listing.get("published_at", ""))
    urgency_label = get_urgency_label(age_minutes)

    price_val = listing.get("price") or 0
    mileage_val = listing.get("mileage") or 0

    # ── Предфильтр: цена выше рынка → не тратим LLM ──────────────────────
    market_avg = market.get("market_avg", 0)
    if market_avg > 0 and price_val > market_avg * 1.05:
        logging.info(f"Пропущено (цена {price_val:,} >= рынок {market_avg:,}): {listing.get('title', '')}")
        return {
            "dcb_score": 0, "verdict": "Цена выше рынка — пропущено",
            "full_analysis": "", "listing": listing, "market": market,
            "seller": seller, "fraud": fraud, "strategy": strategy,
            "arbitrage": arbitrage, "price_dropped": dropped,
            "drop_amount": drop_amount, "days_on_market": days,
            "age_minutes": age_minutes, "urgency_label": urgency_label,
        }

    # ── Текущий месяц для сезонности ─────────────────────────────────────
    month_name = MONTH_NAMES[datetime.now().month - 1]

    # ── Системный промпт ──────────────────────────────────────────────────
    system_prompt = _read_system_prompt()

    # ── Формирование user-сообщения ───────────────────────────────────────
    user_msg = f"""Источник: {source.upper()} | {urgency_label}
Объявление: {listing.get('title', '')}
Цена: {_fmt(price_val)} ₽ | Год: {listing.get('year', 0)} | Пробег: {_fmt(mileage_val)} км
Город: {listing.get('city', '')} | Фото: {listing.get('photo_count', 0)}
Описание: {str(listing.get('description', ''))[:500]}

РЫНОЧНЫЙ АНАЛИЗ:
Средняя цена рынка: {_fmt(market.get('market_avg', 0))} ₽
Минимум на рынке: {_fmt(market.get('market_min', 0))} ₽
Аналогов на рынке: {market.get('market_count', 0)}
Недооценённость: {market.get('undervaluation_pct', 0)}%
Дешевле {market.get('price_percentile', 0)}% аналогов
Тренд рынка: {market.get('trend', '—')}
Ликвидность модели: {market.get('liquidity_days', '—')} дней

ПРОФИЛЬ ПРОДАВЦА:
Мотивация: {seller['motivation_score']}/100
Сигналы мотивации: {', '.join(seller['motivation_signals']) or 'не выявлены'}
Вероятность перекупа: {seller['reseller_probability']}%
Признаки перекупа: {', '.join(seller['reseller_signals']) or 'не выявлены'}
Потенциал торга: {seller['bargain_potential']} ({seller['bargain_pct']}%)

РИСКИ И ДЕФЕКТЫ:
Уровень риска: {fraud['risk_level']} ({fraud['risk_score']}/100)
Выявленные риски: {chr(10).join(fraud['risks']) if fraud['risks'] else 'серьёзных рисков не выявлено'}

СТРАТЕГИЯ СДЕЛКИ:
Открытие торга: {_fmt(strategy['opening_offer'])} ₽
Целевая цена: {_fmt(strategy['target_price'])} ₽
Красная линия: {_fmt(strategy['walk_away'])} ₽
Лучшее время: {strategy['best_time']}
Аргументы: {' | '.join(strategy['arguments'])}

Текущий месяц: {month_name}"""

    if dropped:
        user_msg += f"\n\nЦЕНА СНИЖЕНА на {_fmt(drop_amount)} ₽ — сигнал срочности!"
    if days >= 7:
        user_msg += f"\n\nВисит {days} дней — продавец мотивирован"
    if arbitrage:
        user_msg += (
            f"\n\nАРБИТРАЖ: регион {arbitrage['city']}, "
            f"привезти за {_fmt(arbitrage['total_cost'])} ₽, "
            f"продать в Москве за ~{_fmt(arbitrage['moscow_estimate'])} ₽, "
            f"прибыль ~{_fmt(arbitrage['net_profit'])} ₽"
        )
    if model_stats and model_stats.get("avg_profit"):
        user_msg += (
            f"\n\nМОЯ СТАТИСТИКА по {listing.get('title', '')[:20]}: "
            f"средняя прибыль {_fmt(model_stats['avg_profit'])} ₽, "
            f"срок {model_stats['avg_days']} дней"
        )

    # ── Вызов LLM (Groq → DeepSeek → локальный скоринг) ──────────────────
    full_text, used_provider = get_llm_response(system_prompt, user_msg)

    # ── Парсинг DCB Score и вердикта ──────────────────────────────────────
    dcb_score = 0
    verdict = "НЕТ ВЕРДИКТА"
    try:
        score_match = re.search(r"DCB SCORE[:\s*]*(\d+)", full_text, re.IGNORECASE)
        if score_match:
            dcb_score = int(score_match.group(1))

        verdict_match = re.search(r"ВЕРДИКТ[:\s]+(.+)", full_text)
        if verdict_match:
            verdict = verdict_match.group(1).strip()
    except Exception as e:
        logging.error(f"Ошибка парсинга ответа LLM: {e}")

    # Все LLM недоступны — локальный скоринг как последний резерв
    if dcb_score == 0 and (not full_text.strip() or full_text.startswith("Ошибка")):
        underval = market.get("undervaluation_pct", 0)
        fraud_penalty = fraud.get("risk_score", 0)
        motivation_bonus = min(seller.get("motivation_score", 0) // 2, 20)
        dcb_score = int(40 + underval * 0.8 + motivation_bonus - fraud_penalty * 0.4)
        verdict = f"Локальная оценка (LLM недоступен): недооценка {underval}%, риск {fraud_penalty}/100"
        logging.warning(f"Все LLM недоступны — локальный score: {dcb_score}/100 для {listing_id}")

    # Штраф за перекупщика (применяется поверх оценки LLM)
    if seller["reseller_probability"] >= 70:
        dcb_score -= 15

    # Финальная валидация — score всегда в диапазоне 0..100
    dcb_score = max(0, min(100, dcb_score))

    # ── Второй агент: Gemini Vision (фото) ────────────────────────────────
    visual_issues = []
    visual_ok = None
    if dcb_score >= 60 and listing.get("photo_urls"):
        try:
            from vision_analyzer import analyze_photos
            vision = analyze_photos(listing["photo_urls"], listing)
            penalty = vision["photo_score_penalty"]
            if penalty > 0:
                dcb_score = max(0, dcb_score - penalty)
                logging.info(f"Фото снизило Score на {penalty}: {vision['visual_issues']}")
            visual_issues = vision["visual_issues"]
            visual_ok = vision["visual_ok"]
        except Exception as e:
            logging.error(f"Vision интеграция: {e}")

    # Причина отказа — формируется для логирования пропущенных объявлений
    reject_reasons = []
    if seller.get("reseller_probability", 0) >= 70:
        reject_reasons.append("перекуп")
    if fraud.get("risk_score", 0) >= 50:
        reject_reasons.append(f"риски: {fraud.get('risk_level', '?')}")
    if listing.get("mileage", 0) > 200000:
        reject_reasons.append("высокий пробег")
    if market.get("undervaluation_pct", 0) < 5:
        reject_reasons.append("цена не ниже рынка")
    reject_reason = ", ".join(reject_reasons) if reject_reasons else "низкий общий балл"

    return {
        "dcb_score": dcb_score,
        "verdict": verdict,
        "full_analysis": full_text,
        "reject_reason": reject_reason,
        "used_provider": used_provider,
        "listing": listing,
        "market": market,
        "seller": seller,
        "fraud": fraud,
        "strategy": strategy,
        "arbitrage": arbitrage,
        "price_dropped": dropped,
        "drop_amount": drop_amount,
        "days_on_market": days,
        "age_minutes": age_minutes,
        "urgency_label": urgency_label,
        "visual_issues": visual_issues,
        "visual_ok": visual_ok,
    }
