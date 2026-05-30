"""
database.py — слой работы с SQLite для Diar Car Buy AI.

Хранит увиденные объявления, историю сделок и ежедневную статистику.
Используется только стандартная библиотека sqlite3.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta

# Путь к файлу базы данных
DB_PATH = "diar_car_buy.db"


def _connect():
    """Открыть соединение с БД с поддержкой доступа к колонкам по имени."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создать таблицы seen_listings, deals и daily_stats при их отсутствии."""
    try:
        conn = _connect()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT,
                source TEXT,
                first_seen TEXT,
                last_price INTEGER,
                price_history TEXT,
                last_dcb_score INTEGER,
                last_notified TEXT,
                UNIQUE(listing_id, source)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                model TEXT,
                buy_price INTEGER,
                buy_date TEXT,
                sell_price INTEGER,
                sell_date TEXT,
                profit INTEGER,
                days_held INTEGER,
                roi REAL,
                status TEXT DEFAULT 'open'
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                analyzed INTEGER DEFAULT 0,
                notified INTEGER DEFAULT 0,
                total_dcb_score INTEGER DEFAULT 0
            )
            """
        )

        conn.commit()
        conn.close()
        logging.info("База данных инициализирована")
    except Exception as e:
        logging.error(f"Ошибка инициализации БД: {e}")


def is_seen(listing_id, source):
    """Проверить, встречалось ли объявление ранее. Возвращает bool."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id = ? AND source = ?",
            (listing_id, source),
        )
        row = cur.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logging.error(f"Ошибка is_seen: {e}")
        return False


def mark_seen(listing_id, source, price):
    """
    Запомнить объявление или обновить его цену.

    При первом появлении создаётся запись с историей цен.
    При повторном — добавляется новая цена в price_history (JSON).
    """
    try:
        now = datetime.now().isoformat()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT price_history FROM seen_listings WHERE listing_id = ? AND source = ?",
            (listing_id, source),
        )
        row = cur.fetchone()

        if row is None:
            # Новое объявление
            history = json.dumps([{"date": now, "price": price}], ensure_ascii=False)
            cur.execute(
                """
                INSERT INTO seen_listings
                    (listing_id, source, first_seen, last_price, price_history)
                VALUES (?, ?, ?, ?, ?)
                """,
                (listing_id, source, now, price, history),
            )
        else:
            # Объявление уже известно — обновляем цену и историю
            try:
                history = json.loads(row["price_history"]) if row["price_history"] else []
            except Exception:
                history = []
            if not history or history[-1].get("price") != price:
                history.append({"date": now, "price": price})
            cur.execute(
                """
                UPDATE seen_listings
                SET last_price = ?, price_history = ?
                WHERE listing_id = ? AND source = ?
                """,
                (price, json.dumps(history, ensure_ascii=False), listing_id, source),
            )

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка mark_seen: {e}")


def price_dropped(listing_id, source):
    """
    Проверить, упала ли цена с момента публикации.

    Возвращает кортеж (bool, int): был ли спад и на сколько рублей.
    """
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT price_history FROM seen_listings WHERE listing_id = ? AND source = ?",
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


def days_on_market(listing_id, source):
    """Вернуть количество дней с момента первого появления объявления."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT first_seen FROM seen_listings WHERE listing_id = ? AND source = ?",
            (listing_id, source),
        )
        row = cur.fetchone()
        conn.close()

        if row is None or not row["first_seen"]:
            return 0
        first_seen = datetime.fromisoformat(row["first_seen"])
        return (datetime.now() - first_seen).days
    except Exception as e:
        logging.error(f"Ошибка days_on_market: {e}")
        return 0


def was_notified(listing_id, source):
    """Проверить, отправлялось ли уведомление по объявлению. Возвращает bool."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_notified FROM seen_listings WHERE listing_id = ? AND source = ?",
            (listing_id, source),
        )
        row = cur.fetchone()
        conn.close()
        return row is not None and row["last_notified"] is not None
    except Exception as e:
        logging.error(f"Ошибка was_notified: {e}")
        return False


def mark_notified(listing_id, source, dcb_score):
    """Отметить, что по объявлению отправлено уведомление, и сохранить DCB Score."""
    try:
        now = datetime.now().isoformat()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE seen_listings
            SET last_notified = ?, last_dcb_score = ?
            WHERE listing_id = ? AND source = ?
            """,
            (now, dcb_score, listing_id, source),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка mark_notified: {e}")


def score_changed(listing_id, source, new_score):
    """
    Проверить, изменился ли DCB Score по сравнению с прошлым уведомлением.

    Возвращает True, если оценка отличается (или ранее не было оценки).
    """
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT last_dcb_score FROM seen_listings WHERE listing_id = ? AND source = ?",
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


def add_deal(description, model, buy_price):
    """Записать новую открытую сделку (покупку авто) в таблицу deals."""
    try:
        now = datetime.now().isoformat()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO deals (description, model, buy_price, buy_date, status)
            VALUES (?, ?, ?, ?, 'open')
            """,
            (description, model, buy_price, now),
        )
        conn.commit()
        conn.close()
        logging.info(f"Добавлена сделка: {model} за {buy_price}")
    except Exception as e:
        logging.error(f"Ошибка add_deal: {e}")


def close_deal(sell_price):
    """
    Закрыть самую старую открытую сделку, проставив цену продажи.

    Рассчитывает прибыль, срок владения и ROI.
    Возвращает dict с итогами или пустой dict при отсутствии открытых сделок.
    """
    try:
        now = datetime.now()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM deals WHERE status = 'open' ORDER BY buy_date ASC LIMIT 1"
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

        cur.execute(
            """
            UPDATE deals
            SET sell_price = ?, sell_date = ?, profit = ?,
                days_held = ?, roi = ?, status = 'closed'
            WHERE id = ?
            """,
            (sell_price, now.isoformat(), profit, days_held, roi, row["id"]),
        )
        conn.commit()
        conn.close()

        return {
            "model": row["model"],
            "buy_price": buy_price,
            "sell_price": sell_price,
            "profit": profit,
            "days": days_held,
            "roi": roi,
        }
    except Exception as e:
        logging.error(f"Ошибка close_deal: {e}")
        return {}


def get_deals_stats():
    """
    Собрать сводную статистику по всем сделкам.

    Возвращает dict: всего сделок, лучшая модель, средние прибыль/ROI/срок,
    прибыль за последний месяц и число открытых сделок.
    """
    try:
        conn = _connect()
        cur = conn.cursor()

        # Всего закрытых сделок
        cur.execute("SELECT COUNT(*) AS c FROM deals WHERE status = 'closed'")
        total = cur.fetchone()["c"]

        # Средние показатели по закрытым сделкам
        cur.execute(
            """
            SELECT AVG(profit) AS avg_profit, AVG(roi) AS avg_roi,
                   AVG(days_held) AS avg_days
            FROM deals WHERE status = 'closed'
            """
        )
        avg_row = cur.fetchone()
        avg_roi = round(avg_row["avg_roi"] or 0, 1)
        avg_days = round(avg_row["avg_days"] or 0)

        # Лучшая модель по средней прибыли
        cur.execute(
            """
            SELECT model, AVG(profit) AS avg_profit
            FROM deals WHERE status = 'closed'
            GROUP BY model
            ORDER BY avg_profit DESC
            LIMIT 1
            """
        )
        best_row = cur.fetchone()
        best_model = best_row["model"] if best_row else "—"
        best_avg = round(best_row["avg_profit"]) if best_row and best_row["avg_profit"] else 0

        # Прибыль за последние 30 дней
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        cur.execute(
            "SELECT SUM(profit) AS s FROM deals WHERE status = 'closed' AND sell_date >= ?",
            (month_ago,),
        )
        month_profit = cur.fetchone()["s"] or 0

        # Открытые сделки
        cur.execute("SELECT COUNT(*) AS c FROM deals WHERE status = 'open'")
        open_count = cur.fetchone()["c"]

        conn.close()
        return {
            "total": total,
            "best_model": best_model,
            "avg": best_avg,
            "roi": avg_roi,
            "days": avg_days,
            "month_profit": month_profit,
            "open": open_count,
        }
    except Exception as e:
        logging.error(f"Ошибка get_deals_stats: {e}")
        return {
            "total": 0,
            "best_model": "—",
            "avg": 0,
            "roi": 0,
            "days": 0,
            "month_profit": 0,
            "open": 0,
        }


def get_model_stats(model):
    """
    Вернуть личную статистику по конкретной модели.

    Возвращает dict {avg_profit, avg_days} по закрытым сделкам,
    либо пустой dict, если сделок по модели нет.
    """
    try:
        if not model:
            return {}
        conn = _connect()
        cur = conn.cursor()
        # Ищем по вхождению названия модели (регистронезависимо)
        cur.execute(
            """
            SELECT AVG(profit) AS avg_profit, AVG(days_held) AS avg_days, COUNT(*) AS c
            FROM deals
            WHERE status = 'closed' AND LOWER(model) LIKE '%' || LOWER(?) || '%'
            """,
            (model,),
        )
        row = cur.fetchone()
        conn.close()

        if not row or not row["c"]:
            return {}
        return {
            "avg_profit": round(row["avg_profit"] or 0),
            "avg_days": round(row["avg_days"] or 0),
        }
    except Exception as e:
        logging.error(f"Ошибка get_model_stats: {e}")
        return {}


def _today():
    """Вернуть текущую дату в формате YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def _ensure_today_row(cur):
    """Гарантировать наличие строки статистики за сегодня."""
    today = _today()
    cur.execute("SELECT id FROM daily_stats WHERE date = ?", (today,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO daily_stats (date) VALUES (?)", (today,))


def get_today_stats():
    """
    Вернуть статистику за сегодня.

    Возвращает dict: analyzed, notified, avg_score.
    """
    try:
        conn = _connect()
        cur = conn.cursor()
        _ensure_today_row(cur)
        conn.commit()
        cur.execute(
            "SELECT analyzed, notified, total_dcb_score FROM daily_stats WHERE date = ?",
            (_today(),),
        )
        row = cur.fetchone()
        conn.close()

        analyzed = row["analyzed"] or 0
        notified = row["notified"] or 0
        total_score = row["total_dcb_score"] or 0
        avg_score = round(total_score / notified) if notified else 0
        return {"analyzed": analyzed, "notified": notified, "avg_score": avg_score}
    except Exception as e:
        logging.error(f"Ошибка get_today_stats: {e}")
        return {"analyzed": 0, "notified": 0, "avg_score": 0}


def increment_analyzed():
    """Увеличить счётчик проанализированных объявлений за сегодня на 1."""
    try:
        conn = _connect()
        cur = conn.cursor()
        _ensure_today_row(cur)
        cur.execute(
            "UPDATE daily_stats SET analyzed = analyzed + 1 WHERE date = ?",
            (_today(),),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка increment_analyzed: {e}")


def increment_notified(dcb_score):
    """Увеличить счётчик отправленных уведомлений и сумму DCB Score за сегодня."""
    try:
        conn = _connect()
        cur = conn.cursor()
        _ensure_today_row(cur)
        cur.execute(
            """
            UPDATE daily_stats
            SET notified = notified + 1, total_dcb_score = total_dcb_score + ?
            WHERE date = ?
            """,
            (dcb_score, _today()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка increment_notified: {e}")


def get_top5_today():
    """
    Вернуть топ-5 объявлений за сегодня по DCB Score.

    Возвращает список dict: {title, score, price, url}.
    Заголовок берётся из listing_id, т.к. отдельного поля title нет —
    поэтому возвращаем доступные данные из seen_listings.
    """
    try:
        today = _today()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT listing_id, source, last_price, last_dcb_score, last_notified
            FROM seen_listings
            WHERE last_notified IS NOT NULL
              AND date(last_notified) = ?
            ORDER BY last_dcb_score DESC
            LIMIT 5
            """,
            (today,),
        )
        rows = cur.fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append(
                {
                    "title": f"{r['listing_id']} ({r['source']})",
                    "score": r["last_dcb_score"] or 0,
                    "price": r["last_price"] or 0,
                    "url": r["listing_id"],
                }
            )
        return result
    except Exception as e:
        logging.error(f"Ошибка get_top5_today: {e}")
        return []
