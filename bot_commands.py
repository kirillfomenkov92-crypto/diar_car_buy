"""
bot_commands.py — обработчики команд Telegram-бота Diar Car Buy AI.

Использует python-telegram-bot (v20+, async). Команды позволяют смотреть
статистику, управлять мониторингом (пауза/возобновление), менять бюджет и
порог DCB Score в runtime, а также вести учёт сделок (покупка/продажа).
"""

import re
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import load_config, set_value
from database import (
    get_today_stats,
    get_top5_today,
    get_deals_stats,
    add_deal,
    close_deal,
)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats — показать статистику анализа за сегодня."""
    try:
        s = get_today_stats()
        text = (
            "📊 Статистика за сегодня\n"
            f"Проанализировано: {s['analyzed']}\n"
            f"Отправлено: {s['notified']}\n"
            f"Средний DCB Score: {s['avg_score']}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_stats: {e}")


async def cmd_top5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/top5 — показать топ-5 объявлений за сегодня по DCB Score."""
    try:
        items = get_top5_today()
        if not items:
            await update.message.reply_text("Сегодня ещё нет отправленных объявлений.")
            return
        lines = []
        for it in items:
            lines.append(
                f"⭐{it['score']} | {it['title']} | {it['price']}₽\n🔗{it['url']}"
            )
        await update.message.reply_text("\n\n".join(lines))
    except Exception as e:
        logging.error(f"Ошибка cmd_top5: {e}")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pause — приостановить мониторинг (PAUSED=True в runtime)."""
    try:
        set_value("PAUSED", True)
        await update.message.reply_text("⏸ Мониторинг приостановлен")
    except Exception as e:
        logging.error(f"Ошибка cmd_pause: {e}")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/resume — возобновить мониторинг (PAUSED=False в runtime)."""
    try:
        set_value("PAUSED", False)
        await update.message.reply_text("▶️ Мониторинг возобновлён")
    except Exception as e:
        logging.error(f"Ошибка cmd_resume: {e}")


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/budget [число] — изменить максимальную цену (MAX_PRICE) в runtime."""
    try:
        if not context.args:
            await update.message.reply_text("Использование: /budget 140000")
            return
        amount = int(re.sub(r"\D", "", context.args[0]))
        set_value("MAX_PRICE", amount)
        await update.message.reply_text(f"💰 Бюджет изменён: {amount} ₽")
    except Exception as e:
        logging.error(f"Ошибка cmd_budget: {e}")
        await update.message.reply_text("Не удалось распознать сумму.")


async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/score [число] — изменить порог DCB Score (MIN_DCB_SCORE) в runtime."""
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


async def cmd_bought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bought [текст] за [число] — записать новую сделку (покупку).

    Из текста извлекается описание/модель (до слова «за») и цена покупки.
    """
    try:
        raw = " ".join(context.args) if context.args else ""
        m = re.search(r"(.+?)\s+за\s+([\d\s]+)", raw, re.IGNORECASE)
        if not m:
            await update.message.reply_text("Использование: /bought Lada Priora за 90000")
            return
        description = m.group(1).strip()
        buy_price = int(re.sub(r"\D", "", m.group(2)))
        # В качестве модели берём первые два слова описания
        model = " ".join(description.split()[:2])
        add_deal(description, model, buy_price)
        await update.message.reply_text("✅ Сделка записана! Удачи с продажей 🚗")
    except Exception as e:
        logging.error(f"Ошибка cmd_bought: {e}")
        await update.message.reply_text("Не удалось записать сделку.")


async def cmd_sold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sold за [число] — закрыть открытую сделку с указанной ценой продажи."""
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
            "🎉 Сделка закрыта!\n"
            f"Прибыль: +{deal['profit']} ₽\n"
            f"Срок: {deal['days']} дней\n"
            f"ROI: {deal['roi']}%"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_sold: {e}")
        await update.message.reply_text("Не удалось закрыть сделку.")


async def cmd_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/deals — показать сводную статистику по всем сделкам."""
    try:
        s = get_deals_stats()
        text = (
            f"📈 Твои сделки — всего {s['total']}\n"
            f"Лучшая модель: {s['best_model']} (avg +{s['avg']}₽)\n"
            f"Средний ROI: {s['roi']}%\n"
            f"Средний срок: {s['days']} дней\n"
            f"Прибыль за месяц: +{s['month_profit']} ₽\n"
            f"В работе сейчас: {s['open']}"
        )
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Ошибка cmd_deals: {e}")


def get_command_handlers():
    """
    Вернуть список пар (имя_команды, обработчик) для регистрации в приложении.

    Используется в main.py для добавления CommandHandler.
    """
    return [
        ("stats", cmd_stats),
        ("top5", cmd_top5),
        ("pause", cmd_pause),
        ("resume", cmd_resume),
        ("budget", cmd_budget),
        ("score", cmd_score),
        ("bought", cmd_bought),
        ("sold", cmd_sold),
        ("deals", cmd_deals),
    ]
