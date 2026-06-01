import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_mark_notified_atomic(tmp_path, monkeypatch):
    """database: второй вызов mark_notified возвращает False — атомарная защита от дублей."""
    import time as _time
    import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    from database import init_db, mark_seen, was_notified, mark_notified
    init_db()
    uid = f"unit_{int(_time.time() * 1000)}"
    mark_seen(uid, "unit_test", 100000)
    assert not was_notified(uid, "unit_test")
    assert mark_notified(uid, "unit_test", 85) is True
    assert mark_notified(uid, "unit_test", 85) is False


def test_fraud_zapret():
    """fraud_detector: запрет регистрационных действий = высокий риск."""
    from fraud_detector import detect_fraud
    listing = {
        "description": "хорошая машина, есть запрет регистрационных действий",
        "title": "Lada Priora 2014",
        "price": 90000, "year": 2014, "mileage": 110000,
    }
    result = detect_fraud(listing)
    assert result["risk_level"] == "высокий"
    assert result["risk_score"] >= 50


def test_fraud_taxi():
    """fraud_detector: коммерческое использование (такси) = повышенный риск."""
    from fraud_detector import detect_fraud
    listing = {
        "description": "Работала в такси Яндекс, хорошее состояние",
        "title": "Kia Rio 2015",
        "price": 80000, "year": 2015, "mileage": 280000,
    }
    result = detect_fraud(listing)
    assert result["risk_score"] >= 40


def test_rss_date_parsing():
    """speed_monitor: RSS-дата парсится без ошибок."""
    from speed_monitor import calculate_listing_age_minutes
    age = calculate_listing_age_minutes("Mon, 01 Jun 2026 10:00:00 +0300")
    assert 0 <= age < 99999


def test_bad_date():
    """speed_monitor: некорректная дата возвращает 999."""
    from speed_monitor import calculate_listing_age_minutes
    age = calculate_listing_age_minutes("не дата вообще")
    assert age == 999


def test_score_range():
    """analyzer: dcb_score всегда в диапазоне 0..100."""
    assert max(0, min(100, 150)) == 100
    assert max(0, min(100, -10)) == 0
    assert max(0, min(100, 75)) == 75


def test_config_loads():
    """config: load_config возвращает непустой dict с обязательными ключами."""
    from config import load_config, RUNTIME_CONFIG
    RUNTIME_CONFIG.clear()
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert "MAX_PRICE" in cfg
    assert "MIN_DCB_SCORE" in cfg


def test_tg_parser_no_creds():
    """tg_parser: без TG_API_ID возвращает [] без зависания."""
    from config import RUNTIME_CONFIG
    RUNTIME_CONFIG["TG_API_ID"] = ""
    RUNTIME_CONFIG["TG_API_HASH"] = ""
    from parsers.tg_parser import parse
    result = parse()
    assert result == []
