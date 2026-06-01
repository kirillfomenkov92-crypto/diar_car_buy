# database.py — слой работы с SQLite для Diar Car Buy AI v3.0.
# 6 таблиц: seen_listings, market_data, deals, daily_stats,
#           seller_history, arbitrage_opportunities.

import sqlite3
import json
import logging
from datetime import datetime, timedelta

DB_PATH = "diar_car_buy.db"


def _connect():
    """Открыть соединение с WAL-режимом и таймаутом для конкурентного доступа."""
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _migrate_db(conn):
    """Добавить новые колонки в существующие таблицы (безопасная миграция)."""
    cur = conn.cursor()
    migrations = [
        "ALTER TABLE seen_listings ADD COLUMN title TEXT",
        "ALTER TABLE seen_listings ADD COLUMN listing_url TEXT",
        "ALTER TABLE seen_listings ADD COLUMN response_time_minutes INTEGER",
        "ALTER TABLE deals ADD COLUMN buy_city TEXT",
        "ALTER TABLE deals ADD COLUMN source TEXT",
        "ALTER TABLE daily_stats ADD COLUMN fastest_alert_minutes INTEGER",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
        except Exception:
            pass  # колонка уже существует
    conn.commit()


def init_db():
    """Создать все таблицы и выполнить миграцию схемы."""
    try:
        conn = _connect()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen_listings (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id            TEXT,
                source                TEXT,
                title                 TEXT,
                listing_url           TEXT,
                first_seen            TEXT,
                last_price            INTEGER,
                price_history         TEXT,
                last_dcb_score        INTEGER,
                last_notified         TEXT,
                response_time_minutes INTEGER,
                UNIQUE(listing_id, source)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                model            TEXT,
                city             TEXT,
                date             TEXT,
                avg_price        INTEGER,
                min_price        INTEGER,
                count_listings   INTEGER,
                avg_days_to_sell INTEGER
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                model       TEXT,
                buy_price   INTEGER,
                buy_city    TEXT,
                buy_date    TEXT,
                sell_price  INTEGER,
                sell_date   TEXT,
                profit      INTEGER,
                days_held   INTEGER,
                roi         REAL,
                source      TEXT,
                status      TEXT DEFAULT 'open'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                date                  TEXT UNIQUE,
                analyzed              INTEGER DEFAULT 0,
                notified              INTEGER DEFAULT 0,
                total_dcb_score       INTEGER DEFAULT 0,
                fastest_alert_minutes INTEGER
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS seller_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id       TEXT,
                source          TEXT,
                first_seen      TEXT,
                total_listings  INTEGER DEFAULT 1,
                avg_price       INTEGER,
                avg_discount_pct REAL,
                UNIQUE(seller_id, source)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS arbitrage_opportunities (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id           TEXT,
                source               TEXT,
                source_city          TEXT,
                listing_url          TEXT,
                region_price         INTEGER,
                moscow_price_estimate INTEGER,
                transport_cost       INTEGER,
                net_profit           INTEGER,
                created_at           TEXT,
                status               TEXT DEFAULT 'new'
            )
        """)

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_notified "
            "ON seen_listings(last_notified)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_source "
            "ON seen_listings(source)"
        )

        conn.commit()
        _migrate_db(conn)
        conn.close()
        logging.info("База данных v3.0 инициализирована")
    except Exception as e:
        logging.error(f"Ошибка init_db: {e}")


# ── Функции для seen_listings ──────────────────────────────────────────────

def is_seen(listing_id: str, source: str) -> bool:
    """Проверить, встречалось ли объявление ранее."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id=? AND source=?",
            (listing_id, source),
        )
        return cur.fetchone() is not None
    except Exception as e:
        logging.error(f"Ошибка is_seen: {e}")
        return False
    finally:
        if conn:
            conn.close()


def mark_seen(listing_id: str, source: str, price: int,
              title: str = "", listing_url: str = ""):
    """Добавить новое объявление или обновить цену существующего."""
    try:
        now = datetime.now().isoformat()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT price_history FROM seen_listings WHERE listing_id=? AND source=?",
            (listing_id, source),
        )
        row = cur.fetchone()

        if row is None:
            history = json.dumps([{"date": now, "price": price}], ensure_ascii=False)
            cur.execute("""
                INSERT INTO seen_listings
                    (listing_id, source, title, listing_url, first_seen, last_price, price_history)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, source, title, listing_url, now, price, history))
        else:
            try:
                history = json.loads(row["price_history"]) if row["price_history"] else []
            except Exception:
                history = []
            if not history or history[-1].get("price") != price:
                history.append({"date": now, "price": price})
            cur.execute("""
                UPDATE seen_listings
                SET last_price=?, price_history=?, title=?, listing_url=?
                WHERE listing_id=? AND source=?
            """, (price, json.dumps(history, ensure_ascii=False),
                  title, listing_url, listing_id, source))

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка mark_seen: {e}")


def price_dropped(listing_id: str, source: str) -> tuple:
    """Вернуть (True, разница ₽) если цена упала с первого появления."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT price_history FROM seen_listings WHERE listing_id=? AND source=?",
            (listing_id, source),
        )
        row = cur.fetchone()
        conn.close()
        if row is None or not row["price_history"]:
            return (False, 0)
        history = json.loads(row["price_history"])
        if len(history) < 2:
            return (False, 0)
        first_price = history[0]["price"]
        last_price = history[-1]["price"]
        if last_price < first_price:
            return (True, first_price - last_price)
        return (False, 0)
    except Exception as e:
        logging.error(f"Ошибка price_dropped: {e}")
        return (False, 0)


def days_on_market(listing_id: str, source: str) -> int:
    """Вернуть количество дней с первого появления объявления."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT first_seen FROM seen_listings WHERE listing_id=? AND source=?",
            (listing_id, source),
        )
        row = cur.fetchone()
        conn.close()
        if row is None or not row["first_seen"]:
            return 0
        return (datetime.now() - datetime.fromisoformat(row["first_seen"])).days
    except Exception as e:
        logging.error(f"Ошибка days_on_market: {e}")
        return 0


def was_notified(listing_id: str, source: str) -> bool:
    """Проверить, отправлялось ли уведомление по объявлению."""
    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_notified FROM seen_listings WHERE listing_id=? AND source=?",
            (listing_id, source),
        )
        row = cur.fetchone()
        return row is not None and row["last_notified"] is not None
    except Exception as e:
        logging.error(f"Ошибка was_notified: {e}")
        return False
    finally:
        if conn:
            conn.close()


def mark_notified(listing_id: str, source: str, dcb_score: int) -> bool:
    """Атомарно отметить объявление как уведомлённое.
    Возвращает True только если запись обновлена впервые (защита от дублей).
    """
    try:
        now = datetime.now().isoformat()
        conn = _connect()
        cur = conn.cursor()
        # WHERE last_notified IS NULL гарантирует атомарность:
        # второй concurrent вызов не обновит строку и вернёт rowcount=0
        cur.execute("""
            UPDATE seen_listings SET last_notified=?, last_dcb_score=?
            WHERE listing_id=? AND source=? AND last_notified IS NULL
        """, (now, dcb_score, listing_id, source))
        updated = cur.rowcount > 0
        conn.commit()
        conn.close()
        return updated
    except Exception as e:
        logging.error(f"Ошибка mark_notified: {e}")
        return False


def score_changed(listing_id: str, source: str, new_score: int) -> bool:
    """True если DCB Score изменился по сравнению с последним уведомлением."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_dcb_score FROM seen_listings WHERE listing_id=? AND source=?",
            (listing_id, source),
        )
        row = cur.fetchone()
        conn.close()
        if row is None or row["last_dcb_score"] is None:
            return True
        return row["last_dcb_score"] != new_score
    except Exception as e:
        logging.error(f"Ошибка score_changed: {e}")
        return True


def record_response_time(listing_id: str, source: str, minutes: int):
    """Сохранить время реакции на объявление и обновить рекорд за сегодня."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            UPDATE seen_listings SET response_time_minutes=?
            WHERE listing_id=? AND source=?
        """, (minutes, listing_id, source))
        # Обновляем рекорд в daily_stats
        today = datetime.now().strftime("%Y-%m-%d")
        _ensure_today_row(cur, today)
        cur.execute("""
            UPDATE daily_stats
            SET fastest_alert_minutes = CASE
                WHEN fastest_alert_minutes IS NULL OR ? < fastest_alert_minutes
                THEN ? ELSE fastest_alert_minutes END
            WHERE date=?
        """, (minutes, minutes, today))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка record_response_time: {e}")


def get_similar_from_db(model: str, days: int = 30) -> list:
    """Найти похожие объявления в БД за последние N дней (для рыночного анализа)."""
    try:
        if not model:
            return []
        conn = _connect()
        cur = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        keywords = model.lower().split()[:2]
        conditions = " OR ".join(
            f"LOWER(title) LIKE '%' || LOWER(?) || '%'" for _ in keywords
        )
        params = keywords + [cutoff]
        cur.execute(
            f"SELECT title, last_price FROM seen_listings WHERE ({conditions}) AND first_seen >= ?",
            params,
        )
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logging.error(f"Ошибка get_similar_from_db: {e}")
        return []


# ── Функции для seller_history ─────────────────────────────────────────────

def get_seller_history(seller_id: str, source: str) -> dict:
    """Получить историю продавца из БД (количество объявлений, средняя цена)."""
    try:
        if not seller_id:
            return {}
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM seller_history WHERE seller_id=? AND source=?",
            (seller_id, source),
        )
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        logging.error(f"Ошибка get_seller_history: {e}")
        return {}


def update_seller_history(seller_id: str, source: str, price: int):
    """Обновить историю продавца (количество объявлений и средняя цена)."""
    try:
        if not seller_id:
            return
        now = datetime.now().isoformat()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT total_listings, avg_price FROM seller_history WHERE seller_id=? AND source=?",
            (seller_id, source),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("""
                INSERT INTO seller_history (seller_id, source, first_seen, total_listings, avg_price)
                VALUES (?, ?, ?, 1, ?)
            """, (seller_id, source, now, price))
        else:
            total = row["total_listings"] + 1
            avg = int((row["avg_price"] * row["total_listings"] + price) / total)
            cur.execute("""
                UPDATE seller_history SET total_listings=?, avg_price=?
                WHERE seller_id=? AND source=?
            """, (total, avg, seller_id, source))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка update_seller_history: {e}")


# ── Функции для deals ──────────────────────────────────────────────────────

def add_deal(description: str, model: str, buy_price: int,
             buy_city: str = "Москва", source: str = "manual"):
    """Записать новую открытую сделку (покупку авто) в таблицу deals."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO deals (description, model, buy_price, buy_city, buy_date, source, status)
            VALUES (?, ?, ?, ?, ?, ?, 'open')
        """, (description, model, buy_price, buy_city, datetime.now().isoformat(), source))
        conn.commit()
        conn.close()
        logging.info(f"Сделка записана: {model} за {buy_price} ₽")
    except Exception as e:
        logging.error(f"Ошибка add_deal: {e}")


def close_deal(sell_price: int) -> dict:
    """Закрыть самую старую открытую сделку. Вернуть итоги или {}."""
    try:
        now = datetime.now()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM deals WHERE status='open' ORDER BY buy_date ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            conn.close()
            return {}
        buy_price = row["buy_price"] or 0
        buy_date = datetime.fromisoformat(row["buy_date"]) if row["buy_date"] else now
        profit = sell_price - buy_price
        days_held = max((now - buy_date).days, 0)
        roi = round((profit / buy_price) * 100, 1) if buy_price else 0.0
        cur.execute("""
            UPDATE deals
            SET sell_price=?, sell_date=?, profit=?, days_held=?, roi=?, status='closed'
            WHERE id=?
        """, (sell_price, now.isoformat(), profit, days_held, roi, row["id"]))
        conn.commit()
        conn.close()
        return {"model": row["model"], "buy_price": buy_price,
                "sell_price": sell_price, "profit": profit,
                "days": days_held, "roi": roi}
    except Exception as e:
        logging.error(f"Ошибка close_deal: {e}")
        return {}


def get_deals_stats() -> dict:
    """Сводная статистика по всем сделкам."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM deals WHERE status='closed'")
        total = cur.fetchone()["c"]
        cur.execute(
            "SELECT AVG(profit) AS ap, AVG(roi) AS ar, AVG(days_held) AS ad FROM deals WHERE status='closed'"
        )
        avg_row = cur.fetchone()
        avg_roi = round(avg_row["ar"] or 0, 1)
        avg_days = round(avg_row["ad"] or 0)
        cur.execute("""
            SELECT model, AVG(profit) AS ap FROM deals
            WHERE status='closed' GROUP BY model ORDER BY ap DESC LIMIT 1
        """)
        best_row = cur.fetchone()
        best_model = best_row["model"] if best_row else "—"
        best_avg = round(best_row["ap"]) if best_row and best_row["ap"] else 0
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        cur.execute(
            "SELECT SUM(profit) AS s FROM deals WHERE status='closed' AND sell_date>=?",
            (month_ago,),
        )
        month_profit = cur.fetchone()["s"] or 0
        cur.execute("SELECT COUNT(*) AS c FROM deals WHERE status='open'")
        open_count = cur.fetchone()["c"]
        conn.close()
        return {"total": total, "best_model": best_model, "avg": best_avg,
                "roi": avg_roi, "days": avg_days, "month_profit": month_profit,
                "open": open_count}
    except Exception as e:
        logging.error(f"Ошибка get_deals_stats: {e}")
        return {"total": 0, "best_model": "—", "avg": 0,
                "roi": 0, "days": 0, "month_profit": 0, "open": 0}


def get_model_stats(model: str) -> dict:
    """Средняя прибыль и срок по закрытым сделкам данной модели."""
    try:
        if not model:
            return {}
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT AVG(profit) AS ap, AVG(days_held) AS ad, COUNT(*) AS c
            FROM deals
            WHERE status='closed' AND LOWER(model) LIKE '%'||LOWER(?)||'%'
        """, (model,))
        row = cur.fetchone()
        conn.close()
        if not row or not row["c"]:
            return {}
        return {"avg_profit": round(row["ap"] or 0), "avg_days": round(row["ad"] or 0)}
    except Exception as e:
        logging.error(f"Ошибка get_model_stats: {e}")
        return {}


# ── Функции для daily_stats ────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ensure_today_row(cur, today: str = None):
    """Гарантировать наличие строки статистики за сегодня."""
    today = today or _today()
    cur.execute("SELECT id FROM daily_stats WHERE date=?", (today,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO daily_stats (date) VALUES (?)", (today,))


def get_today_stats() -> dict:
    """Вернуть статистику за сегодня: analyzed, notified, avg_score."""
    try:
        conn = _connect()
        cur = conn.cursor()
        _ensure_today_row(cur)
        conn.commit()
        cur.execute(
            "SELECT analyzed, notified, total_dcb_score, fastest_alert_minutes FROM daily_stats WHERE date=?",
            (_today(),),
        )
        row = cur.fetchone()
        conn.close()
        analyzed = row["analyzed"] or 0
        notified = row["notified"] or 0
        total_score = row["total_dcb_score"] or 0
        avg_score = round(total_score / notified) if notified else 0
        return {"analyzed": analyzed, "notified": notified,
                "avg_score": avg_score,
                "fastest_alert": row["fastest_alert_minutes"] or 0}
    except Exception as e:
        logging.error(f"Ошибка get_today_stats: {e}")
        return {"analyzed": 0, "notified": 0, "avg_score": 0, "fastest_alert": 0}


def increment_analyzed():
    """Увеличить счётчик проанализированных объявлений за сегодня."""
    try:
        conn = _connect()
        cur = conn.cursor()
        _ensure_today_row(cur)
        cur.execute(
            "UPDATE daily_stats SET analyzed=analyzed+1 WHERE date=?", (_today(),)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка increment_analyzed: {e}")


def increment_notified(dcb_score: int):
    """Увеличить счётчик уведомлений и сумму DCB Score за сегодня."""
    try:
        conn = _connect()
        cur = conn.cursor()
        _ensure_today_row(cur)
        cur.execute("""
            UPDATE daily_stats
            SET notified=notified+1, total_dcb_score=total_dcb_score+?
            WHERE date=?
        """, (dcb_score, _today()))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка increment_notified: {e}")


def get_top5_today() -> list:
    """Топ-5 объявлений за сегодня по DCB Score."""
    try:
        today = _today()
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, listing_url, last_price, last_dcb_score, source
            FROM seen_listings
            WHERE last_dcb_score IS NOT NULL
              AND date(first_seen)=?
              AND source != 'test'
            ORDER BY last_dcb_score DESC
            LIMIT 5
        """, (today,))
        rows = cur.fetchall()
        conn.close()
        return [{"title": r["title"] or f"[{r['source']}]",
                 "score": r["last_dcb_score"] or 0,
                 "price": r["last_price"] or 0,
                 "url": r["listing_url"] or ""}
                for r in rows]
    except Exception as e:
        logging.error(f"Ошибка get_top5_today: {e}")
        return []


# ── Функции для arbitrage_opportunities ───────────────────────────────────

def save_arbitrage(listing_id: str, source: str, source_city: str,
                   listing_url: str, region_p: int, moscow_p: int,
                   transport: int, profit: int):
    """Сохранить арбитражную возможность в БД."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO arbitrage_opportunities
                (listing_id, source, source_city, listing_url,
                 region_price, moscow_price_estimate, transport_cost,
                 net_profit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (listing_id, source, source_city, listing_url,
              region_p, moscow_p, transport, profit,
              datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка save_arbitrage: {e}")


def get_active_arbitrage() -> list:
    """Вернуть активные арбитражные возможности (status='new'), сортировка по прибыли."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM arbitrage_opportunities
            WHERE status='new'
            ORDER BY net_profit DESC
            LIMIT 10
        """)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logging.error(f"Ошибка get_active_arbitrage: {e}")
        return []


# ── Аналитические функции ──────────────────────────────────────────────────

def get_speed_stats() -> dict:
    """Средняя скорость реакции на объявления по источникам."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT source,
                   AVG(response_time_minutes) AS avg_t,
                   MIN(response_time_minutes) AS min_t
            FROM seen_listings
            WHERE response_time_minutes IS NOT NULL AND response_time_minutes < 999
            GROUP BY source
            ORDER BY avg_t
        """)
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return {"avg": 0, "best": 0, "best_source": "—", "by_source": {}}
        total_avg = sum(r["avg_t"] for r in rows) / len(rows)
        best_row = min(rows, key=lambda r: r["min_t"])
        return {
            "avg": round(total_avg),
            "best": best_row["min_t"],
            "best_source": best_row["source"],
            "by_source": {r["source"]: round(r["avg_t"]) for r in rows},
        }
    except Exception as e:
        logging.error(f"Ошибка get_speed_stats: {e}")
        return {"avg": 0, "best": 0, "best_source": "—", "by_source": {}}


def get_source_stats() -> dict:
    """Количество найденных объявлений за сегодня по каждому источнику."""
    try:
        today = _today()
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT source, COUNT(*) AS cnt
            FROM seen_listings
            WHERE date(first_seen)=?
              AND source != 'test'
            GROUP BY source
            ORDER BY cnt DESC
        """, (today,))
        rows = cur.fetchall()
        conn.close()
        result = {r["source"]: r["cnt"] for r in rows}
        result["best"] = max(result, key=result.get) if result else "—"
        return result
    except Exception as e:
        logging.error(f"Ошибка get_source_stats: {e}")
        return {"best": "—"}
