"""tests/test_fixes.py — тесты для всех исправлений из аудита."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# speed_monitor: "дней" корректно даёт минуты
# ─────────────────────────────────────────────────────────────────────────────

def test_speed_monitor_days_plural():
    """speed_monitor: '5 дней назад' → 7200 минут (не 999)."""
    from speed_monitor import calculate_listing_age_minutes
    assert calculate_listing_age_minutes("5 дней назад") == 7200


def test_speed_monitor_days_singular():
    """speed_monitor: '1 день назад' → 1440 минут."""
    from speed_monitor import calculate_listing_age_minutes
    assert calculate_listing_age_minutes("1 день назад") == 1440


def test_speed_monitor_days_genitive():
    """speed_monitor: '3 дня назад' → 4320 минут."""
    from speed_monitor import calculate_listing_age_minutes
    assert calculate_listing_age_minutes("3 дня назад") == 4320


def test_speed_monitor_tolko_chto():
    """speed_monitor: 'только что' → 1 минута."""
    from speed_monitor import calculate_listing_age_minutes
    assert calculate_listing_age_minutes("только что") == 1


# ─────────────────────────────────────────────────────────────────────────────
# deal_strategist: walk_away всегда >= target_price
# ─────────────────────────────────────────────────────────────────────────────

def test_deal_strategist_no_inversion():
    """deal_strategist: walk_away всегда >= target_price при любом bargain_pct."""
    from deal_strategist import build_strategy
    listing = {"price": 100000, "mileage": 80000}
    seller_low = {"motivation_score": 10, "bargain_pct": 1, "bargain_potential": "низкий",
                  "reseller_probability": 20, "reseller_signals": []}
    fraud = {"risk_score": 0, "risk_level": "низкий", "risks": []}
    result = build_strategy(listing, {}, seller_low, fraud)
    assert result["walk_away"] >= result["target_price"], (
        f"walk_away={result['walk_away']} < target_price={result['target_price']}"
    )


def test_deal_strategist_walk_away_zero_bargain():
    """deal_strategist: при bargain_pct=0 walk_away корректен."""
    from deal_strategist import build_strategy
    listing = {"price": 90000, "mileage": 100000}
    seller = {"motivation_score": 5, "bargain_pct": 0, "bargain_potential": "низкий",
              "reseller_probability": 15, "reseller_signals": []}
    fraud = {"risk_score": 0, "risk_level": "низкий", "risks": []}
    result = build_strategy(listing, {}, seller, fraud)
    assert result["walk_away"] >= result["target_price"]
    assert result["walk_away"] >= result["opening_offer"]


# ─────────────────────────────────────────────────────────────────────────────
# fraud_detector: стук двигателя → высокий риск
# ─────────────────────────────────────────────────────────────────────────────

def test_fraud_engine_knock():
    """fraud_detector: 'стукнул двигатель' → высокий риск (score >= 60)."""
    from fraud_detector import detect_fraud
    listing = {
        "description": "стукнул двигатель, продаю как есть",
        "title": "Lada Priora 2015",
        "price": 50000, "year": 2015, "mileage": 180000,
    }
    result = detect_fraud(listing)
    assert result["risk_score"] >= 60
    assert result["risk_level"] == "высокий"


def test_fraud_engine_seized():
    """fraud_detector: 'клин двигателя' → риск >= 70."""
    from fraud_detector import detect_fraud
    listing = {
        "description": "произошёл клин двигателя",
        "title": "Ford Focus 2010",
        "price": 60000, "year": 2010, "mileage": 220000,
    }
    result = detect_fraud(listing)
    assert result["risk_score"] >= 70


def test_fraud_not_running():
    """fraud_detector: 'не на ходу' → риск >= 40."""
    from fraud_detector import detect_fraud
    listing = {
        "description": "машина не на ходу, нужен ремонт",
        "title": "Kia Rio 2012",
        "price": 55000, "year": 2012, "mileage": 150000,
    }
    result = detect_fraud(listing)
    assert result["risk_score"] >= 40


# ─────────────────────────────────────────────────────────────────────────────
# analyzer: предфильтр "не на ходу" возвращает score=0
# ─────────────────────────────────────────────────────────────────────────────

def test_analyzer_prefilter_not_running(monkeypatch):
    """analyzer: объявление 'не на ходу' получает score=0 без вызова LLM."""
    import analyzer
    from config import RUNTIME_CONFIG
    RUNTIME_CONFIG["MAX_PRICE"] = 150000

    llm_called = []

    monkeypatch.setattr(analyzer, "get_llm_response",
                        lambda s, u: llm_called.append(1) or ("", ""))
    monkeypatch.setattr(analyzer, "analyze_market", lambda t, p: {})
    monkeypatch.setattr(analyzer, "profile_seller", lambda l: {
        "motivation_score": 50, "motivation_signals": [],
        "reseller_probability": 20, "reseller_signals": [],
        "bargain_potential": "средний", "bargain_pct": 10,
    })
    monkeypatch.setattr(analyzer, "detect_fraud", lambda l: {
        "risk_level": "высокий", "risk_score": 70, "risks": [],
    })
    monkeypatch.setattr(analyzer, "build_strategy", lambda l, m, s, f: {
        "opening_offer": 0, "target_price": 0, "walk_away": 0,
        "best_time": "", "arguments": [], "call_script": "",
    })
    monkeypatch.setattr(analyzer, "check_arbitrage", lambda l: None)
    monkeypatch.setattr(analyzer, "save_arbitrage", lambda *a, **kw: None)
    monkeypatch.setattr(analyzer, "price_dropped", lambda lid, src: (False, 0))
    monkeypatch.setattr(analyzer, "days_on_market", lambda lid, src: 0)
    monkeypatch.setattr(analyzer, "get_model_stats", lambda t: {})
    monkeypatch.setattr(analyzer, "calculate_listing_age_minutes", lambda p: 999)
    monkeypatch.setattr(analyzer, "get_urgency_label", lambda a: "⏱ нейтрально")

    listing = {
        "listing_id": "not_running_test",
        "source": "avito",
        "title": "Lada Priora 2014",
        "price": 45000,
        "year": 2014,
        "mileage": 200000,
        "city": "Москва",
        "description": "стукнул двигатель, продаём на запчасти",
        "photo_count": 2,
        "published_at": "",
        "listing_url": "https://avito.ru/test",
        "is_regional": False,
    }

    result = analyzer.analyze_listing(listing)
    assert result["dcb_score"] == 0, "Объявление 'не на ходу' должно получить score=0"
    assert len(llm_called) == 0, "LLM не должен вызываться для нерабочих авто"


# ─────────────────────────────────────────────────────────────────────────────
# database: try/finally — соединение закрывается при исключении в mark_seen
# ─────────────────────────────────────────────────────────────────────────────

def test_database_mark_seen_no_leak(tmp_path, monkeypatch):
    """database: mark_seen корректно работает с реальной БД."""
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    from database import init_db, mark_seen, is_seen
    init_db()
    mark_seen("lid1", "avito", 90000, "Lada", "https://avito.ru/1", 2015, 1)
    assert is_seen("lid1", "avito")
    # Повторный вызов с другой ценой не должен упасть
    mark_seen("lid1", "avito", 85000, "Lada", "https://avito.ru/1", 2015, 1)


def test_database_price_dropped(tmp_path, monkeypatch):
    """database: price_dropped возвращает (True, diff) после снижения цены."""
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    from database import init_db, mark_seen, price_dropped
    init_db()
    mark_seen("lid2", "avito", 100000)
    mark_seen("lid2", "avito", 85000)
    dropped, diff = price_dropped("lid2", "avito")
    assert dropped is True
    assert diff == 15000


# ─────────────────────────────────────────────────────────────────────────────
# notifier: None listing_id → ранний выход без записи в БД
# ─────────────────────────────────────────────────────────────────────────────

def test_notifier_none_listing_id(monkeypatch):
    """notifier: listing_id=None → функция возвращается без вызова was_notified."""
    import notifier
    from config import RUNTIME_CONFIG
    RUNTIME_CONFIG["TELEGRAM_BOT_TOKEN"] = "test"
    RUNTIME_CONFIG["TELEGRAM_CHAT_ID"] = "123"

    was_called = []
    monkeypatch.setattr(notifier, "was_notified",
                        lambda lid, src: was_called.append(1) or False)

    result = {
        "listing": {"listing_id": None, "source": None, "price": 80000},
        "dcb_score": 85,
        "full_analysis": "test",
        "strategy": {"opening_offer": 70000, "target_price": 75000,
                     "walk_away": 78000, "best_time": "", "arguments": [],
                     "call_script": ""},
        "arbitrage": None, "price_dropped": False, "drop_amount": 0,
    }
    notifier.send_notification(result)
    assert len(was_called) == 0, "was_notified не должен вызываться при None listing_id"
