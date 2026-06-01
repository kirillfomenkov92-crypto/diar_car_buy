# seller_profiler.py — психологический портрет продавца и стратегия торга.

import logging

from database import get_seller_history

# Словарь сигналов срочности продажи: слово → вес мотивации
URGENCY_MAP = {
    "срочно": 20,
    "нужны деньги": 25,
    "уезжаю": 20,
    "переезд": 18,
    "куплю другую": 15,
    "торг уместен": 12,
    "торг при осмотре": 10,
    "звоните": 8,
    "не могу содержать": 20,
    "развод": 15,
    "продаю в связи": 15,
    "вынужден продать": 20,
    "срочная продажа": 22,
    "без посредников": 10,
}

# Шаблонные фразы перекупа
TEMPLATE_PHRASES = [
    "на ходу", "всё работает", "не бита не крашена",
    "один хозяин", "гаражное хранение", "не гнилая",
    "ухоженная", "своевременное то",
]


def profile_seller(listing: dict) -> dict:
    """
    Составить психологический портрет продавца.
    Возвращает dict с мотивацией, вероятностью перекупа и стратегией торга.
    """
    try:
        description = (listing.get("description") or "").lower()
        seller_ads = listing.get("seller_ads_count", 0) or 0
        photo_count = listing.get("photo_count", 0) or 0
        published_at = str(listing.get("published_at", "") or "")
        source = listing.get("source", "")

        # ── МОТИВАЦИЯ (0–100) ──────────────────────────────────────────────
        motivation_score = 0
        motivation_signals = []

        for word, weight in URGENCY_MAP.items():
            if word in description:
                motivation_score += weight
                motivation_signals.append(f"'{word}'")

        # Время публикации: ночью/вечером = выше мотивация
        try:
            if "T" in published_at:
                hour = int(published_at.split("T")[1][:2])
            elif ":" in published_at and len(published_at) > 15:
                hour = int(published_at[11:13])
            else:
                hour = -1
            if 0 <= hour <= 6 or hour >= 21:
                motivation_score += 15
                motivation_signals.append("публикация ночью")
            elif hour >= 18:
                motivation_score += 8
                motivation_signals.append("публикация вечером")
        except Exception:
            pass

        # VK/Telegram = минует платные площадки → выше мотивация
        if source in ("vk", "telegram"):
            motivation_score += 10
            motivation_signals.append(f"публикует в {source} — минует площадки")

        motivation_score = min(motivation_score, 100)

        # ── ПЕРЕКУП (0–100) ────────────────────────────────────────────────
        reseller_score = 0
        reseller_signals = []

        if photo_count < 3:
            reseller_score += 35
            reseller_signals.append(f"мало фото ({photo_count})")
        elif photo_count < 5:
            reseller_score += 20
            reseller_signals.append(f"мало фото ({photo_count})")

        if seller_ads > 3:
            reseller_score += 30
            reseller_signals.append(f"много объявлений ({seller_ads})")
        elif seller_ads > 1:
            reseller_score += 15
            reseller_signals.append(f"несколько объявлений ({seller_ads})")

        template_count = sum(1 for p in TEMPLATE_PHRASES if p in description)
        if template_count >= 3:
            reseller_score += 15
            reseller_signals.append("шаблонное описание")

        for word in ("авторынок", "стоянка", "на рынке"):
            if word in description:
                reseller_score += 25
                reseller_signals.append(f"'{word}' в описании")
                break

        if "без торга" in description:
            reseller_score += 15
            reseller_signals.append("'без торга'")

        reseller_score = min(reseller_score, 100)

        # ── СТРАТЕГИЯ ТОРГА ────────────────────────────────────────────────
        if motivation_score >= 70:
            bargain_potential = "высокий"
            bargain_pct = 18
        elif motivation_score >= 40:
            bargain_potential = "средний"
            bargain_pct = 11
        else:
            bargain_potential = "низкий"
            bargain_pct = 4

        # Перекуп торгуется хуже
        if reseller_score >= 70:
            bargain_pct = min(bargain_pct, 7)

        seller_history = get_seller_history(
            str(listing.get("seller_id", "") or ""),
            source,
        )

        return {
            "motivation_score": motivation_score,
            "motivation_signals": motivation_signals,
            "reseller_probability": reseller_score,
            "reseller_signals": reseller_signals,
            "bargain_potential": bargain_potential,
            "bargain_pct": bargain_pct,
            "seller_history": seller_history,
            "source": source,
        }
    except Exception as e:
        logging.error(f"Ошибка profile_seller: {e}")
        return {
            "motivation_score": 0,
            "motivation_signals": [],
            "reseller_probability": 0,
            "reseller_signals": [],
            "bargain_potential": "низкий",
            "bargain_pct": 5,
            "seller_history": {},
            "source": "",
        }
