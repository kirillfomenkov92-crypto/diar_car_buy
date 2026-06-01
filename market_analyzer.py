# market_analyzer.py — анализ позиции объявления относительно рынка.

import logging
from datetime import datetime, timedelta

from database import get_similar_from_db

# Ликвидность по дням продажи для типовых моделей
LIQUIDITY_MAP = {
    "lada priora": 10,
    "lada 2114": 12,
    "lada 2115": 12,
    "lada 2107": 14,
    "renault logan": 9,
    "ford focus": 11,
    "kia spectra": 13,
    "chevrolet lanos": 12,
    "hyundai accent": 11,
    "daewoo nexia": 15,
    "nissan almera": 13,
    "chevrolet aveo": 14,
    "chevrolet lacetti": 13,
}


def estimate_liquidity_default(model: str) -> int:
    """Оценить ликвидность модели в днях по справочнику."""
    model_lower = (model or "").lower()
    for key, days in LIQUIDITY_MAP.items():
        if key in model_lower:
            return days
    return 20


def get_market_trend(model: str) -> str:
    """Определить ценовой тренд модели: сравнить последние 7 дней с предыдущими."""
    try:
        from database import _connect
        conn = _connect()
        cur = conn.cursor()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        keywords = (model or "").lower().split()[:2]
        if not keywords:
            return "нет данных"
        conditions = " OR ".join(
            f"LOWER(title) LIKE '%' || LOWER(?) || '%'" for _ in keywords
        )
        cur.execute(
            f"SELECT AVG(last_price) AS a FROM seen_listings WHERE first_seen>=? AND ({conditions})",
            [week_ago] + keywords,
        )
        recent_avg = cur.fetchone()["a"] or 0
        cur.execute(
            f"SELECT AVG(last_price) AS a FROM seen_listings WHERE first_seen>=? AND first_seen<? AND ({conditions})",
            [month_ago, week_ago] + keywords,
        )
        older_avg = cur.fetchone()["a"] or 0
        conn.close()
        if not older_avg:
            return "нет данных"
        diff = (recent_avg - older_avg) / older_avg * 100
        if diff > 5:
            return f"↗ растёт (+{diff:.1f}%)"
        elif diff < -5:
            return f"↘ падает ({diff:.1f}%)"
        else:
            return "→ стабильный"
    except Exception as e:
        logging.error(f"Ошибка get_market_trend: {e}")
        return "нет данных"


def analyze_market(model: str, current_price: int, city: str = "Москва") -> dict:
    """Проанализировать позицию объявления относительно рынка по накопленным данным."""
    try:
        similar = get_similar_from_db(model, days=30)

        if not similar:
            return {
                "market_avg": current_price,
                "market_min": current_price,
                "market_count": 0,
                "price_percentile": 50,
                "undervaluation_pct": 0,
                "trend": "нет данных",
                "liquidity_days": estimate_liquidity_default(model),
            }

        prices = [s["last_price"] for s in similar if s.get("last_price")]
        if not prices:
            return {
                "market_avg": current_price,
                "market_min": current_price,
                "market_count": 0,
                "price_percentile": 50,
                "undervaluation_pct": 0,
                "trend": "нет данных",
                "liquidity_days": estimate_liquidity_default(model),
            }

        market_avg = int(sum(prices) / len(prices))
        market_min = min(prices)
        sorted_prices = sorted(prices)

        # Персентиль: процент объявлений дороже текущей цены
        cheaper_count = sum(1 for p in sorted_prices if p < current_price)
        price_percentile = int(cheaper_count / len(sorted_prices) * 100)

        undervaluation = round((market_avg - current_price) / market_avg * 100, 1) if market_avg else 0
        trend = get_market_trend(model)

        return {
            "market_avg": market_avg,
            "market_min": market_min,
            "market_count": len(prices),
            "price_percentile": price_percentile,
            "undervaluation_pct": undervaluation,
            "trend": trend,
            "liquidity_days": estimate_liquidity_default(model),
        }
    except Exception as e:
        logging.error(f"Ошибка analyze_market: {e}")
        return {
            "market_avg": current_price,
            "market_min": current_price,
            "market_count": 0,
            "price_percentile": 50,
            "undervaluation_pct": 0,
            "trend": "ошибка",
            "liquidity_days": estimate_liquidity_default(model),
        }
