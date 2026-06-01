# bot_commands.py — обработчики команд Telegram-бота Diar Car Buy AI v3.0.
# python-telegram-bot v20+ async. Красивое форматирование всех ответов.

import re
import logging
import time
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

from config import load_config, set_value, RUNTIME_CONFIG


def authorized_only(func):
    @wraps(func)
    async def wrapper(update, context):
        if not update.effective_user:
            return
        uid = update.effective_user.id
        allowed = RUNTIME_CONFIG.get("ALLOWED_USER_IDS", [])
        if allowed and uid not in allowed:
            await update.message.reply_text("Доступ запрещён")
            logging.warning(f"Попытка доступа: user_id={uid}")
            return
        return await func(update, context)
    return wrapper
from database import (
    get_today_stats, get_top5_today, get_deals_stats,
    add_deal, close_deal, get_active_arbitrage,
    get_speed_stats, get_source_stats,
)
from market_analyzer import analyze_market

LINE = "━━━━━━━━━━━━━━━"


def _fmt(n) -> str:
    """Форматировать число с пробелами."""
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — приветственное сообщение с описанием источников и команд."""
    try:
        text = (
            "🚗 Diar Car Buy AI v3.0 запущен!\n"
            f"{LINE}\n"
            "📡 Источники мониторинга:\n"
            "  • Avito — каждые 15 минут\n"
            "  • Drom — Москва + регионы (арбитраж)\n"
            "  • Auto.ru — только частные\n"
            "  • Youla — меньше конкуренции\n"
            "  • ВКонтакте — раньше чем на Avito\n"
            "  • Telegram — за 5–15 мин до Avito\n"
            f"{LINE}\n"
            "Команды:\n"
            "/status — состояние Авито и бота\n"
            "/stats — статистика за сегодня\n"
            "/top5 — топ-5 лучших за 24ч\n"
            "/sources — статистика по источникам\n"
            "/market [модель] — срез рынка\n"
            "/arbitrage — арбитражные возможности\n"
            "/speed — скорость реакции\n"
            "/pause — пауза мониторинга\n"
            "/resume — возобновить\n"
            "/budget [сумма] — изменить бюджет\n"
            "/score [число] — порог DCB Score\n"
            "/bought [авто] за [сумма] — записать покупку\n"
            "/sold за [сумма] — закрыть сделку\n"
            "/deals — статистика сделок\n"
            "/help — помощь"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_start: {e}")


@authorized_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats — статистика анализа за сегодня по всем источникам."""
    try:
        s = get_today_stats()
        src = get_source_stats()
        best = src.pop("best", "—")
        src_lines = "\n".join(
            f"  {k}: {v}" for k, v in sorted(src.items(), key=lambda x: -x[1])
        ) or "  нет данных"
        text = (
            f"📊 Статистика за сегодня\n"
            f"{LINE}\n"
            f"🔍 Проанализировано: {s['analyzed']}\n"
            f"📨 Отправлено: {s['notified']}\n"
            f"⭐ Средний DCB Score: {s['avg_score']}\n"
            f"⚡ Рекорд скорости: {s['fastest_alert']} мин\n"
            f"{LINE}\n"
            f"По источникам:\n{src_lines}\n"
            f"Лучший источник: {best}\n"
            f"{LINE}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_stats: {e}")


@authorized_only
async def cmd_top5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/top5 — топ-5 объявлений за 24 часа по DCB Score."""
    try:
        items = get_top5_today()
        if not items:
            await update.message.reply_text("Сегодня ещё нет отправленных объявлений.")
            return
        lines = [f"🏆 Топ-5 за 24 часа\n{LINE}"]
        for i, it in enumerate(items, 1):
            lines.append(
                f"{i}. ⭐{it['score']} | {it['title']}\n"
                f"   💰 {_fmt(it['price'])} ₽ | 🔗 {it['url']}"
            )
        lines.append(LINE)
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logging.error(f"Ошибка cmd_top5: {e}")


@authorized_only
async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sources — статистика уведомлений по источникам за сегодня."""
    try:
        src = get_source_stats()
        best = src.pop("best", "—")
        sources_display = {
            "avito": "Avito",
            "drom": "Drom",
            "autoru": "Auto.ru",
            "youla": "Youla",
            "vk": "ВКонтакте",
            "telegram": "Telegram",
        }
        lines = [f"📡 ИСТОЧНИКИ СЕГОДНЯ\n{LINE}"]
        for key, label in sources_display.items():
            count = src.get(key, 0)
            lines.append(f"{label:12}: {count} объявлений")
        lines.append(LINE)
        lines.append(f"Лучший источник: {sources_display.get(best, best)}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logging.error(f"Ошибка cmd_sources: {e}")


@authorized_only
async def cmd_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/market [модель] — срез рынка по модели из накопленных данных."""
    try:
        model = " ".join(context.args) if context.args else ""
        if not model:
            await update.message.reply_text(
                "Использование: /market Lada Priora\n"
                "Или: /market Renault Logan"
            )
            return
        market = analyze_market(model, 0)
        text = (
            f"📊 Рынок: {model}\n"
            f"{LINE}\n"
            f"Средняя цена: {_fmt(market['market_avg'])} ₽\n"
            f"Минимум: {_fmt(market['market_min'])} ₽\n"
            f"Аналогов в БД: {market['market_count']}\n"
            f"Тренд: {market['trend']}\n"
            f"Ликвидность: ~{market['liquidity_days']} дней\n"
            f"{LINE}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_market: {e}")


@authorized_only
async def cmd_arbitrage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/arbitrage — активные арбитражные возможности из БД."""
    try:
        arbs = get_active_arbitrage()
        if not arbs:
            await update.message.reply_text(
                "Нет активных арбитражных возможностей.\n"
                "Региональные объявления появятся после следующего цикла мониторинга Drom."
            )
            return
        lines = [f"🚚 Арбитражные возможности ({len(arbs)})\n{LINE}"]
        for arb in arbs[:5]:
            lines.append(
                f"🏙 {arb.get('source_city', '?')} → Москва\n"
                f"   Регион: {_fmt(arb.get('region_price', 0))} ₽\n"
                f"   В Москве: ~{_fmt(arb.get('moscow_price_estimate', 0))} ₽\n"
                f"   Прибыль: +{_fmt(arb.get('net_profit', 0))} ₽\n"
                f"   🔗 {arb.get('listing_url', '—')}"
            )
        lines.append(LINE)
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logging.error(f"Ошибка cmd_arbitrage: {e}")


@authorized_only
async def cmd_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/speed — статистика скорости реакции на объявления."""
    try:
        s = get_speed_stats()
        by_source = s.get("by_source", {})
        src_lines = "\n".join(
            f"  {k}: {v} мин" for k, v in sorted(by_source.items(), key=lambda x: x[1])
        ) or "  нет данных"
        text = (
            f"⚡ СКОРОСТЬ РЕАКЦИИ\n"
            f"{LINE}\n"
            f"Среднее время: {s.get('avg', 0)} мин\n"
            f"Рекорд: {s.get('best', 0)} мин\n"
            f"Самый быстрый источник: {s.get('best_source', '—')}\n"
            f"{LINE}\n"
            f"По источникам:\n{src_lines}\n"
            f"{LINE}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_speed: {e}")


@authorized_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pause — приостановить мониторинг."""
    try:
        set_value("PAUSED", True)
        await update.message.reply_text("⏸ Мониторинг приостановлен")
    except Exception as e:
        logging.error(f"Ошибка cmd_pause: {e}")


@authorized_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/resume — возобновить мониторинг."""
    try:
        set_value("PAUSED", False)
        await update.message.reply_text("▶️ Мониторинг возобновлён")
    except Exception as e:
        logging.error(f"Ошибка cmd_resume: {e}")


@authorized_only
async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/budget [сумма] — изменить максимальную цену поиска."""
    try:
        if not context.args:
            await update.message.reply_text("Использование: /budget 140000")
            return
        amount = int(re.sub(r"\D", "", context.args[0]))
        set_value("MAX_PRICE", amount)
        await update.message.reply_text(f"💰 Бюджет изменён: {_fmt(amount)} ₽")
    except Exception as e:
        logging.error(f"Ошибка cmd_budget: {e}")
        await update.message.reply_text("Не удалось распознать сумму.")


@authorized_only
async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/score [число] — изменить порог DCB Score для уведомлений."""
    try:
        if not context.args:
            await update.message.reply_text("Использование: /score 70")
            return
        value = int(re.sub(r"\D", "", context.args[0]))
        set_value("MIN_DCB_SCORE", value)
        await update.message.reply_text(f"⭐ Порог изменён: {value}/100")
    except Exception as e:
        logging.error(f"Ошибка cmd_score: {e}")
        await update.message.reply_text("Не удалось распознать число.")


@authorized_only
async def cmd_bought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bought [авто] за [сумма] — записать новую сделку (покупку)."""
    try:
        raw = " ".join(context.args) if context.args else ""
        m = re.search(r"(.+?)\s+за\s+([\d\s]+)", raw, re.IGNORECASE)
        if not m:
            await update.message.reply_text(
                "Использование: /bought Lada Priora 2012 за 85000"
            )
            return
        description = m.group(1).strip()
        buy_price = int(re.sub(r"\D", "", m.group(2)))
        model = " ".join(description.split()[:2])
        add_deal(description, model, buy_price)
        text = (
            f"✅ Сделка записана!\n"
            f"🚗 {description}\n"
            f"💸 Куплено за: {_fmt(buy_price)} ₽\n"
            "Удачи с продажей! 🤝"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_bought: {e}")
        await update.message.reply_text("Не удалось записать сделку.")


@authorized_only
async def cmd_sold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sold за [сумма] — закрыть открытую сделку."""
    try:
        raw = " ".join(context.args) if context.args else ""
        m = re.search(r"за\s+([\d\s]+)", raw, re.IGNORECASE)
        if not m:
            await update.message.reply_text("Использование: /sold за 130000")
            return
        sell_price = int(re.sub(r"\D", "", m.group(1)))
        deal = close_deal(sell_price)
        if not deal:
            await update.message.reply_text("Нет открытых сделок для закрытия.")
            return
        text = (
            f"🎉 Сделка закрыта!\n"
            f"{LINE}\n"
            f"💰 Прибыль: +{_fmt(deal['profit'])} ₽\n"
            f"📅 Срок: {deal['days']} дней\n"
            f"📈 ROI: {deal['roi']}%\n"
            f"{LINE}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_sold: {e}")
        await update.message.reply_text("Не удалось закрыть сделку.")


@authorized_only
async def cmd_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/deals — сводная статистика по всем сделкам."""
    try:
        s = get_deals_stats()
        text = (
            f"📈 Статистика сделок\n"
            f"{LINE}\n"
            f"Всего сделок: {s['total']}\n"
            f"Лучшая модель: {s['best_model']} (avg +{_fmt(s['avg'])} ₽)\n"
            f"Средний ROI: {s['roi']}%\n"
            f"Средний срок: {s['days']} дней\n"
            f"Прибыль за месяц: +{_fmt(s['month_profit'])} ₽\n"
            f"В работе: {s['open']}\n"
            f"{LINE}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_deals: {e}")


@authorized_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — текущее состояние Авито и планировщика."""
    try:
        blocked_until = RUNTIME_CONFIG.get("AVITO_BLOCKED_UNTIL", 0)
        if time.time() < blocked_until:
            mins = int((blocked_until - time.time()) / 60)
            avito_status = f"заблокирован ещё {mins} мин"
        else:
            avito_status = "работает"

        last_parse = RUNTIME_CONFIG.get("LAST_AVITO_PARSE", 0)
        ago = int((time.time() - last_parse) / 60) if last_parse else 999
        min_interval = RUNTIME_CONFIG.get("AVITO_MIN_INTERVAL_SECONDS", 90)
        paused = RUNTIME_CONFIG.get("PAUSED", False)

        text = (
            f"Статус Diar Car Buy AI\n"
            f"{LINE}\n"
            f"Авито:      {avito_status}\n"
            f"Последний запрос: {ago} мин назад\n"
            f"Пауза между запросами: {min_interval}с\n"
            f"{LINE}\n"
            f"Остальные источники: работают\n"
            f"Мониторинг: {'на паузе' if paused else 'активен'}\n"
            f"Scheduler: активен\n"
            f"Telegram polling: активен"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_status: {e}")


@authorized_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — список всех команд."""
    try:
        text = (
            f"📋 Команды Diar Car Buy AI v3.0\n"
            f"{LINE}\n"
            "/start — приветствие и описание\n"
            "/status — состояние Авито и бота\n"
            "/stats — статистика за сегодня\n"
            "/top5 — топ-5 за 24 часа\n"
            "/sources — источники сегодня\n"
            "/market [модель] — срез рынка\n"
            "/arbitrage — арбитраж регион→Москва\n"
            "/speed — скорость реакции\n"
            f"{LINE}\n"
            "/pause — пауза мониторинга\n"
            "/resume — возобновить\n"
            "/budget [₽] — изменить бюджет\n"
            "/score [0-100] — порог DCB Score\n"
            f"{LINE}\n"
            "/bought [авто] за [₽] — записать покупку\n"
            "/sold за [₽] — закрыть сделку\n"
            "/deals — статистика сделок\n"
            f"{LINE}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_help: {e}")


def get_command_handlers() -> list:
    """Вернуть список (команда, обработчик) для регистрации в приложении."""
    return [
        ("start", cmd_start),
        ("status", cmd_status),
        ("stats", cmd_stats),
        ("top5", cmd_top5),
        ("sources", cmd_sources),
        ("market", cmd_market),
        ("arbitrage", cmd_arbitrage),
        ("speed", cmd_speed),
        ("pause", cmd_pause),
        ("resume", cmd_resume),
        ("budget", cmd_budget),
        ("score", cmd_score),
        ("bought", cmd_bought),
        ("sold", cmd_sold),
        ("deals", cmd_deals),
        ("help", cmd_help),
    ]
