# arbitrage_detector.py — поиск арбитражных возможностей регион→Москва.
# Машина в Туле за 85к → в Москве стоит 125к → едем.

import logging

from config import RUNTIME_CONFIG

# Стоимость перегона авто из регионов в Москву, ₽
TRANSPORT_COSTS = {
    "Тула": 3000,
    "Рязань": 3500,
    "Калуга": 3000,
    "Владимир": 3500,
    "Тверь": 3500,
    "Ярославль": 4500,
    "Смоленск": 5000,
    "default": 5000,
}

# Московская наценка относительно региональной цены (доля)
MOSCOW_PREMIUM = {
    "Тула": 0.18,
    "Рязань": 0.20,
    "Калуга": 0.17,
    "Владимир": 0.22,
    "Тверь": 0.19,
    "Ярославль": 0.21,
    "Смоленск": 0.23,
    "default": 0.20,
}


def check_arbitrage(listing: dict) -> dict | None:
    """
    Проверить региональное объявление на арбитражный потенциал.
    Возвращает dict с расчётом прибыли или None если невыгодно.
    Работает только с региональными объявлениями Drom (is_regional=True).
    """
    try:
        max_price = RUNTIME_CONFIG.get("MAX_PRICE", 150000)
        if listing.get("price", 0) > max_price:
            return None

        if not listing.get("is_regional"):
            return None

        city = listing.get("city", "")
        region_price = listing.get("price", 0)
        if not region_price:
            return None

        transport = TRANSPORT_COSTS.get(city, TRANSPORT_COSTS["default"])
        premium = MOSCOW_PREMIUM.get(city, MOSCOW_PREMIUM["default"])

        moscow_estimate = int(region_price * (1 + premium))
        # +2000 ₽ прочие расходы: бензин туда, оформление, мойка
        total_cost = region_price + transport + 2000
        net_profit = moscow_estimate - total_cost

        if net_profit < 25000:
            return None

        roi = round(net_profit / total_cost * 100, 1)

        return {
            "region_price": region_price,
            "city": city,
            "transport_cost": transport,
            "moscow_estimate": moscow_estimate,
            "total_cost": total_cost,
            "net_profit": net_profit,
            "roi": roi,
            "is_arbitrage": True,
        }
    except Exception as e:
        logging.error(f"Ошибка check_arbitrage: {e}")
        return None
