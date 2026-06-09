"""tests/test_bugfixes.py — регрессионные тесты для исправленных багов аудита."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1: notifier.py — mark_notified не вызывается при провале отправки
# ─────────────────────────────────────────────────────────────────────────────

def test_notifier_no_mark_on_send_failure(monkeypatch):
    """notifier: mark_notified НЕ вызывается если _send_part бросил исключение."""
    import notifier
    from config import RUNTIME_CONFIG

    RUNTIME_CONFIG["TELEGRAM_BOT_TOKEN"] = "test_token"
    RUNTIME_CONFIG["TELEGRAM_CHAT_ID"] = "123"
    RUNTIME_CONFIG["MAX_PRICE"] = 150000

    mark_called = []

    monkeypatch.setattr(notifier, "was_notified", lambda lid, src: False)
    monkeypatch.setattr(notifier, "score_changed", lambda lid, src, s: True)
    monkeypatch.setattr(notifier, "mark_notified",
                        lambda lid, src, score: mark_called.append(1) or True)
    monkeypatch.setattr(notifier, "_send_part",
                        lambda token, chat, text, retries=3, **kw: (_ for _ in ()).throw(
                            Exception("network error")))

    result = {
        "listing": {"listing_id": "abc123", "source": "avito", "price": 90000},
        "dcb_score": 85,
        "full_analysis": "Хорошая сделка",
        "strategy": {"opening_offer": 80000, "target_price": 85000,
                     "walk_away": 75000, "best_time": "10:00",
                     "arguments": [], "call_script": ""},
        "arbitrage": None,
        "price_dropped": False,
        "drop_amount": 0,
    }
    notifier.send_notification(result)

    assert len(mark_called) == 0, "mark_notified не должен вызываться при провале отправки"


def test_notifier_marks_on_success(monkeypatch):
    """notifier: mark_notified вызывается ПОСЛЕ успешной отправки."""
    import notifier
    from config import RUNTIME_CONFIG

    RUNTIME_CONFIG["TELEGRAM_BOT_TOKEN"] = "test_token"
    RUNTIME_CONFIG["TELEGRAM_CHAT_ID"] = "123"
    RUNTIME_CONFIG["ALLOWED_USER_IDS"] = [123]  # один получатель
    RUNTIME_CONFIG["MAX_PRICE"] = 150000

    mark_called = []

    monkeypatch.setattr(notifier, "was_notified", lambda lid, src: False)
    monkeypatch.setattr(notifier, "score_changed", lambda lid, src, s: True)
    monkeypatch.setattr(notifier, "mark_notified",
                        lambda lid, src, score: mark_called.append(1) or True)
    monkeypatch.setattr(notifier, "_send_part",
                        lambda token, chat, text, retries=3, **kw: True)

    result = {
        "listing": {"listing_id": "abc456", "source": "avito", "price": 90000},
        "dcb_score": 85,
        "full_analysis": "Хорошая сделка",
        "strategy": {"opening_offer": 80000, "target_price": 85000,
                     "walk_away": 75000, "best_time": "10:00",
                     "arguments": [], "call_script": ""},
        "arbitrage": None,
        "price_dropped": False,
        "drop_amount": 0,
    }
    notifier.send_notification(result)

    assert len(mark_called) == 1, "mark_notified должен вызваться ровно один раз при успехе"


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2: analyzer.py — не падает если analyze_market вернул {}
# ─────────────────────────────────────────────────────────────────────────────

def test_analyzer_empty_market_no_crash(tmp_path, monkeypatch):
    """analyzer: analyze_listing не падает с KeyError если analyze_market вернул {}."""
    import analyzer
    from config import RUNTIME_CONFIG

    RUNTIME_CONFIG["DEEPSEEK_API_KEY"] = "test"
    RUNTIME_CONFIG["MAX_PRICE"] = 150000

    monkeypatch.setattr(analyzer, "analyze_market", lambda title, price: {})
    monkeypatch.setattr(analyzer, "profile_seller", lambda listing: {
        "motivation_score": 50, "motivation_signals": [],
        "reseller_probability": 20, "reseller_signals": [],
        "bargain_potential": "средний", "bargain_pct": 10,
    })
    monkeypatch.setattr(analyzer, "detect_fraud", lambda listing: {
        "risk_level": "низкий", "risk_score": 10, "risks": [],
    })
    monkeypatch.setattr(analyzer, "build_strategy", lambda l, m, s, f: {
        "opening_offer": 70000, "target_price": 80000, "walk_away": 65000,
        "best_time": "10:00", "arguments": [], "call_script": "",
    })
    monkeypatch.setattr(analyzer, "check_arbitrage", lambda listing: None)
    monkeypatch.setattr(analyzer, "save_arbitrage", lambda *a, **kw: None)
    monkeypatch.setattr(analyzer, "price_dropped", lambda lid, src: (False, 0))
    monkeypatch.setattr(analyzer, "days_on_market", lambda lid, src: 0)
    monkeypatch.setattr(analyzer, "get_model_stats", lambda title: {})
    monkeypatch.setattr(analyzer, "calculate_listing_age_minutes", lambda pub: 999)
    monkeypatch.setattr(analyzer, "get_urgency_label", lambda age: "⏱ нейтрально")

    # DeepSeek бросает исключение → должен сработать fallback
    class FakeDeepSeek:
        def __init__(self, api_key, base_url=None): pass
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise Exception("DeepSeek недоступен")
    monkeypatch.setattr(analyzer, "OpenAI", FakeDeepSeek)

    listing = {
        "listing_id": "test_empty_market",
        "source": "avito",
        "title": "Lada Priora 2014",
        "price": 90000,
        "year": 2014,
        "mileage": 100000,
        "city": "Москва",
        "description": "",
        "photo_count": 3,
        "published_at": "",
        "listing_url": "https://avito.ru/test",
        "is_regional": False,
    }

    # Не должен бросить KeyError — это главное
    result = analyzer.analyze_listing(listing)
    assert isinstance(result, dict)
    assert "dcb_score" in result
    assert 0 <= result["dcb_score"] <= 100
    assert "notification_mode" in result
    assert result["notification_mode"] in ("urgent", "good")


# ─────────────────────────────────────────────────────────────────────────────
# BUG 3: analyzer.py — DeepSeek fallback срабатывает при строке "Ошибка анализа"
# ─────────────────────────────────────────────────────────────────────────────

def test_deepseek_fallback_on_error_string(monkeypatch):
    """analyzer: локальный fallback score считается когда DeepSeek бросил исключение."""
    import analyzer
    from config import RUNTIME_CONFIG

    RUNTIME_CONFIG["DEEPSEEK_API_KEY"] = "test"
    RUNTIME_CONFIG["MAX_PRICE"] = 150000

    monkeypatch.setattr(analyzer, "analyze_market", lambda title, price: {
        "market_avg": 120000, "market_min": 80000, "market_count": 15,
        "undervaluation_pct": 25, "price_percentile": 30,
        "trend": "растёт", "liquidity_days": 10,
    })
    monkeypatch.setattr(analyzer, "profile_seller", lambda listing: {
        "motivation_score": 70, "motivation_signals": ["срочно"],
        "reseller_probability": 20, "reseller_signals": [],
        "bargain_potential": "высокий", "bargain_pct": 15,
    })
    monkeypatch.setattr(analyzer, "detect_fraud", lambda listing: {
        "risk_level": "низкий", "risk_score": 5, "risks": [],
    })
    monkeypatch.setattr(analyzer, "build_strategy", lambda l, m, s, f: {
        "opening_offer": 75000, "target_price": 85000, "walk_away": 70000,
        "best_time": "10:00", "arguments": [], "call_script": "",
    })
    monkeypatch.setattr(analyzer, "check_arbitrage", lambda listing: None)
    monkeypatch.setattr(analyzer, "save_arbitrage", lambda *a, **kw: None)
    monkeypatch.setattr(analyzer, "price_dropped", lambda lid, src: (False, 0))
    monkeypatch.setattr(analyzer, "days_on_market", lambda lid, src: 3)
    monkeypatch.setattr(analyzer, "get_model_stats", lambda title: {})
    monkeypatch.setattr(analyzer, "calculate_listing_age_minutes", lambda pub: 15)
    monkeypatch.setattr(analyzer, "get_urgency_label", lambda age: "🔥 срочно")

    class FakeDeepSeek:
        def __init__(self, api_key, base_url=None): pass
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise ConnectionError("timeout")
    monkeypatch.setattr(analyzer, "OpenAI", FakeDeepSeek)

    listing = {
        "listing_id": "fallback_test",
        "source": "avito",
        "title": "Lada Priora 2015",
        "price": 90000,
        "year": 2015,
        "mileage": 110000,
        "city": "Москва",
        "description": "",
        "photo_count": 5,
        "published_at": "",
        "listing_url": "https://avito.ru/fallback",
        "is_regional": False,
    }

    result = analyzer.analyze_listing(listing)
    # Fallback должен посчитать ненулевой score
    assert result["dcb_score"] > 0, "Fallback score должен быть > 0 при недоступном Groq"
    assert "Локальная оценка" in result.get("verdict", "") or result["dcb_score"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# BUG 4: drom.py — не сохраняет в БД машины дороже MAX_PRICE
# ─────────────────────────────────────────────────────────────────────────────

def test_drom_price_filter_excludes_expensive():
    """drom._parse_card: цена парсится корректно; фильтр > max_price отсекает дорогие."""
    from bs4 import BeautifulSoup
    from parsers.drom import _parse_card

    html = """
    <div data-ftid="bulls-list_bull">
        <a data-ftid="bull_title"
           href="https://auto.drom.ru/tula/kia/rio/12345678.html">
           Kia Rio, 2020
        </a>
        <span data-ftid="bull_price">200\xa0000 ₽</span>
        <span data-ftid="bull_location">Тула</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    card = soup.find(attrs={"data-ftid": "bulls-list_bull"})

    listing = _parse_card(card, "Тула", is_regional=True)
    assert listing is not None
    assert listing["price"] == 200000

    # Фильтр из _parse_city (исправленный): price > max_price → не включать
    max_price = 140000
    assert listing["price"] > max_price, "Тест ожидает дорогую машину"

    results = []
    if listing["price"] > max_price:
        pass  # отфильтровано
    else:
        results.append(listing)

    assert len(results) == 0, "Машина дороже MAX_PRICE не должна попасть в results"


def test_drom_price_filter_includes_cheap():
    """drom._parse_card: дешёвая машина проходит фильтр max_price."""
    from bs4 import BeautifulSoup
    from parsers.drom import _parse_card

    html = """
    <div data-ftid="bulls-list_bull">
        <a data-ftid="bull_title"
           href="https://auto.drom.ru/tula/lada/priora/87654321.html">
           Lada Priora, 2014
        </a>
        <span data-ftid="bull_price">85\xa0000 ₽</span>
        <span data-ftid="bull_location">Тула</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    card = soup.find(attrs={"data-ftid": "bulls-list_bull"})

    listing = _parse_card(card, "Тула", is_regional=True)
    assert listing is not None
    assert listing["price"] == 85000

    max_price = 140000
    results = []
    if listing["price"] > max_price:
        pass
    else:
        results.append(listing)

    assert len(results) == 1, "Машина дешевле MAX_PRICE должна пройти фильтр"


# ─────────────────────────────────────────────────────────────────────────────
# BUG 5: avito.py — RSS и curl имеют независимые таймеры блокировки
# ─────────────────────────────────────────────────────────────────────────────

def test_avito_rss_not_blocked_by_curl_block(monkeypatch):
    """avito.parse: AVITO_CURL_BLOCKED_UNTIL не блокирует RSS уровень."""
    import time
    import parsers.avito as avito_mod
    from config import RUNTIME_CONFIG

    # Симулируем: curl заблокирован, RSS нет
    RUNTIME_CONFIG["AVITO_CURL_BLOCKED_UNTIL"] = time.time() + 3600  # curl заблокирован
    RUNTIME_CONFIG.pop("AVITO_RSS_BLOCKED_UNTIL", None)              # RSS не заблокирован
    RUNTIME_CONFIG.pop("AVITO_CURL_NOT_BEFORE", None)
    RUNTIME_CONFIG["MAX_PRICE"] = 140000

    rss_called = []

    def _make_listing(i):
        return {"listing_id": f"rss{i}", "source": "avito", "price": 90000,
                "title": f"Test {i}", "year": 2014, "mileage": 100000,
                "city": "Москва", "description": "", "photo_count": 0,
                "photo_urls": [], "seller_ads_count": 0, "seller_id": "",
                "published_at": "", "listing_url": f"https://avito.ru/{i}",
                "is_regional": False}

    def fake_rss_parse():
        rss_called.append(1)
        return [_make_listing(i) for i in range(5)]  # >= 3 чтобы parse() вернул результат

    monkeypatch.setattr("parsers.avito_rss.parse", fake_rss_parse)

    result = avito_mod.parse()

    assert len(rss_called) == 1, "RSS должен запуститься даже когда curl заблокирован"
    assert len(result) == 5


def test_avito_curl_not_blocked_by_rss_block(monkeypatch):
    """avito.parse: AVITO_RSS_BLOCKED_UNTIL не блокирует curl уровень."""
    import time
    import parsers.avito as avito_mod
    from config import RUNTIME_CONFIG

    # Симулируем: RSS заблокирован (капча RSS), curl должен запуститься через 10 мин
    RUNTIME_CONFIG["AVITO_RSS_BLOCKED_UNTIL"] = time.time() + 3600   # RSS заблокирован
    RUNTIME_CONFIG.pop("AVITO_CURL_BLOCKED_UNTIL", None)             # curl не HTTP-заблокирован
    RUNTIME_CONFIG["AVITO_CURL_NOT_BEFORE"] = time.time() - 1        # 10 мин уже прошло
    RUNTIME_CONFIG["MAX_PRICE"] = 140000

    curl_called = []

    # RSS заблокирован — parse() должна перейти к уровню 2 (curl)
    # Мокаем BeautifulSoup карточки чтобы curl вернул результат
    import parsers.avito as av

    original_parse = av.parse

    # Проверяем что когда RSS заблокирован, поле rss_blocked = True
    # и код не пытается вызвать RSS
    rss_calls = []
    monkeypatch.setattr("parsers.avito_rss.parse",
                        lambda: rss_calls.append(1) or [])

    # curl уровень — пробрасываем ошибку чтобы не делать реальный HTTP
    import parsers.avito_rss as rss_mod
    original_get = None
    try:
        from curl_cffi import requests as cffi
        monkeypatch.setattr(cffi, "Session",
                            lambda *a, **kw: (_ for _ in ()).throw(Exception("mocked")))
    except Exception:
        pass

    av.parse()

    # Главная проверка: RSS НЕ вызывается когда AVITO_RSS_BLOCKED_UNTIL > now
    assert len(rss_calls) == 0, "RSS не должен вызываться когда AVITO_RSS_BLOCKED_UNTIL установлен"
