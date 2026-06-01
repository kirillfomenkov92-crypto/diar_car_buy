# fraud_detector.py — детектор скрытых проблем и мошенничества.

import logging

# Паттерны скрытых дефектов: ключевая фраза → (реальная проблема, вес риска)
DEFECT_PATTERNS = {
    "небольшое дтп": ("серьёзные повреждения", 25),
    "после дтп": ("кузовной ремонт", 30),
    "масло не ест": ("вероятно ест масло", 20),
    "требует вложений": ("серьёзные проблемы", 25),
    "не заводится": ("проблемы ДВС/электрики", 35),
    "стучит": ("проблемы ДВС/подвески", 30),
    "течёт": ("утечки", 25),
    "ржавчина": ("коррозия кузова", 20),
    "свежепокрашен": ("скрытие дефектов", 25),
    "по запчастям": ("серьёзные проблемы", 40),
    "не на ходу": ("требует ремонта", 40),
    "кузов после": ("кузовной ремонт", 20),
    "варёная": ("сварка кузова", 35),
    "восстановленная": ("после серьёзного ДТП", 30),
    "на запчасти": ("серьёзные проблемы", 40),
    "бита": ("кузовные повреждения", 25),
    "крашена": ("возможно скрытие дефектов", 15),
}

# Юридические риски
LEGAL_RISKS = {
    "в залоге": 50,
    "под залогом": 50,
    "кредит": 20,
    "ограничения": 35,
    "арест": 50,
    "дтп": 15,
    "запрет": 50,
    "обременение": 45,
}

# Слова-маркеры коммерческой эксплуатации
COMMERCIAL_WORDS = [
    "такси", "каршеринг", "аренда", "прокат",
    "яндекс", "убер", "ситимобил", "bolt",
]


def detect_fraud(listing: dict) -> dict:
    """
    Обнаружить скрытые проблемы и юридические риски в объявлении.
    Возвращает dict: risk_score (0–100), risk_level, risks (список строк).
    """
    try:
        description = (listing.get("description") or "").lower()
        title = (listing.get("title") or "").lower()
        price = listing.get("price", 0) or 0
        year = listing.get("year", 2010) or 2010
        mileage = listing.get("mileage", 0) or 0

        risks = []
        risk_score = 0

        # Скрытые дефекты
        for pattern, (meaning, weight) in DEFECT_PATTERNS.items():
            if pattern in description:
                risks.append(f"⚠️ '{pattern}' → вероятно: {meaning}")
                risk_score += weight

        # Аномальный пробег
        age = max(2026 - year, 1) if year > 2000 else 10
        if mileage > 0:
            if mileage < age * 4000:
                risks.append(
                    f"⚠️ Подозрительно малый пробег ({mileage:,} км за {age} лет)".replace(",", " ")
                )
                risk_score += 25
            elif mileage > age * 28000:
                risks.append(
                    f"⚠️ Критически высокий пробег ({mileage:,} км за {age} лет)".replace(",", " ")
                )
                risk_score += 20
            if mileage % 10000 == 0 and mileage > 50000:
                risks.append(
                    f"⚠️ Круглый пробег {mileage:,} км — возможна скрутка".replace(",", " ")
                )
                risk_score += 15

        # Коммерческая эксплуатация
        for word in COMMERCIAL_WORDS:
            if word in description or word in title:
                risks.append(f"🚕 Коммерческое использование: '{word}'")
                risk_score += 40
                break

        # Юридические риски
        for word, weight in LEGAL_RISKS.items():
            if word in description:
                risks.append(f"⚖️ Юридический риск: '{word}'")
                risk_score += weight

        # Срочная продажа по подозрительно низкой цене
        if ("срочно" in description or "нужны деньги" in description) and price < 70000:
            risks.append("⚠️ Срочная продажа по очень низкой цене — проверь юридическую чистоту")
            risk_score += 20

        risk_score = min(risk_score, 100)
        risk_level = (
            "низкий" if risk_score < 20
            else "средний" if risk_score < 50
            else "высокий"
        )

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "risks": risks,
        }
    except Exception as e:
        logging.error(f"Ошибка detect_fraud: {e}")
        return {"risk_score": 0, "risk_level": "низкий", "risks": []}
