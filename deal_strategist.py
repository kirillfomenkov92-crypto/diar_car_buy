# deal_strategist.py — построение конкретной стратегии сделки с числами и скриптом.

import logging


def build_strategy(listing: dict, market: dict, seller: dict, fraud: dict) -> dict:
    """
    Сформировать конкретную стратегию торга с числами и скриптом звонка.
    Возвращает dict с opening_offer, target_price, walk_away, скриптом и аргументами.
    """
    try:
        price = listing.get("price", 100000) or 100000
        motivation = seller.get("motivation_score", 0)
        bargain_pct = seller.get("bargain_pct", 5)

        # Цены торга: открываем ниже цели, цель = цена * (1 - скидка), красная линия = 97% цены
        opening_offer = int(price * (1 - bargain_pct / 100 - 0.05))
        target_price = int(price * (1 - bargain_pct / 100))
        walk_away = int(price * 0.97)  # максимум, который мы заплатим

        # Лучшее время для звонка
        if motivation >= 70:
            best_time = "СЕЙЧАС — мотивация максимальная"
        elif motivation >= 40:
            best_time = "Вечер будних 18–20ч или выходные 10–12ч"
        else:
            best_time = "Выходные утром, когда никто не торопится"

        # Аргументы для торга
        arguments = []
        if fraud.get("risks"):
            arg = fraud["risks"][0].replace("⚠️ ", "").replace("🚕 ", "").replace("⚖️ ", "")
            arguments.append(f"Укажи при осмотре: {arg}")
        if market.get("market_count", 0) > 3:
            arguments.append(
                f"На рынке сейчас {market['market_count']} аналогов — есть из чего выбрать"
            )
        if listing.get("mileage", 0) > 120000:
            arguments.append("Высокий пробег = замена расходников при покупке")
        if not arguments:
            arguments.append("Осмотр всегда выявляет мелкие недостатки")

        opening_fmt = f"{opening_offer:,}".replace(",", " ")
        call_script = (
            f"Здравствуйте, машина ещё актуальна? "
            f"Готов приехать сегодня с деньгами, "
            f"рассматриваю за {opening_fmt} — реально?"
        )

        return {
            "opening_offer": opening_offer,
            "target_price": target_price,
            "walk_away": walk_away,
            "best_time": best_time,
            "arguments": arguments,
            "call_script": call_script,
            "discount_pct": bargain_pct,
        }
    except Exception as e:
        logging.error(f"Ошибка build_strategy: {e}")
        return {
            "opening_offer": 0,
            "target_price": 0,
            "walk_away": 0,
            "best_time": "—",
            "arguments": [],
            "call_script": "—",
            "discount_pct": 0,
        }
