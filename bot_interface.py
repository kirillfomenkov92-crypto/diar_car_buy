# bot_interface.py — «перекупский» интерфейс Diar Car Buy AI v5.0.
# Дополняет bot_commands.py (не заменяет): постоянная ReplyKeyboard,
# HTML-карточки объявлений, пошаговый подбор, избранное.
# Все handlers — только для двух админов (@authorized_only / проверка _is_authorized).

import html
import random
import asyncio
import logging
from functools import wraps

from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters,
)

from config import RUNTIME_CONFIG, set_value
from bot_commands import authorized_only, _is_authorized, _fmt, LINE
from database import (
    get_top5_today, search_listings, get_today_stats, get_source_stats,
    get_recent_listings, get_listing, add_favorite,
)

# ═══════════════════════════════════════════════════════════════════════════
#  ВСЕ ТЕКСТЫ — здесь, для локализации и быстрой правки
# ═══════════════════════════════════════════════════════════════════════════

VIBE_PHRASES = [
    "Сел и поехал, масло меняю каждую 1000 км",
    "Не бит, не крашен, только муха сидела",
    "Капсула времени, стояла в гараже у деда",
    "Вложений не требует, только заправляй",
    "Один хозяин, женщина возила в церковь по воскресеньям",
    "Тапку в пол — летит как новая",
    "Резина зима-лето в подарок, брат",
    "Чёткий вариант, сам бы катался да деньги нужны",
]

ERROR_PHRASES = [
    "🛠 Что-то пошло не так, как пыльник отбойника сорвало. Попробуй позже.",
    "🛠 Заглохло. Дай минуту, заведу заново.",
    "🛠 Движок чихнул. Повтори чуть позже, брат.",
]

TEXTS = {
    "greeting": (
        "👋 Здорово, брат! Я бот-перекуп. Ищу тебе тачки без вложений "
        "до 150к на Авито, Авто.ру и Дроме. Жми кнопки внизу 👇"
    ),
    "fresh_header": "🚘 Свежак на сегодня, держи 👇",
    "fresh_empty": "🚘 Пока пусто, брат. Как нагоню свежих — сразу покажу.",
    "urgent_header": "🔥 Горячее за последний час, лови 👇",
    "urgent_empty": "🔥 Пока тихо, брат. Как появится горячее — сразу скину.",
    "search_brand": "🔍 Подбираем тачку\nШаг 1/3 — выбирай марку:",
    "search_price": "🔍 Подбираем тачку\nШаг 2/3 — до скольки берём:",
    "search_cond": "🔍 Подбираем тачку\nШаг 3/3 — состояние:",
    "search_header": "🔍 Вот что нашёл, брат 👇",
    "search_empty": (
        "🔎 В базе пока мало подходящих, брат. "
        "Ищу новые — гляну в ближайшем цикле."
    ),
    "country_step": "🌍 По стране\nШаг 1/2 — чей автопром?",
    "country_price": "🌍 По стране\nШаг 2/2 — до скольки?",
    "country_header": "🌍 Держи, что нашлось 👇",
    "stats": (
        "📊 За сегодня прошерстил {n} тачек, {m} годных нашёл.\n"
        "Средний скор {score}. Лучший источник: {src}"
    ),
    "filters_title": "⚙️ Фильтры — настрой под себя, брат:",
    "filters_applied": "🔧 Фильтры обновил, брат. Теперь ищем как надо.",
    "filters_reset": "🔄 Сбросил фильтры начисто.",
    "phone_stub": "📞 Звони прямо по ссылке, телефон там. Скажи что от перекупа 😎",
    "fav_added": "⭐ Закинул в избранное, брат!",
    "fav_exists": "⭐ Уже в избранном, расслабься 😎",
    "gone": "🕳 Это объявление уже уехало, брат.",
    "closed": "👌 Окей, брат. Жми кнопки внизу.",
    "denied": "Не для тебя, брат 😎",
    "help": (
        "ℹ️ <b>Чё умею, брат:</b>\n"
        f"{LINE}\n"
        "🚘 <b>Свежие тачки</b> — топ выгодных за сегодня\n"
        "🔥 <b>Срочные</b> — что подъехало за последний час\n"
        "🔍 <b>Найти тачку</b> — подбор: марка → цена → состояние\n"
        "🌍 <b>По стране</b> — наш автопром или иномарки\n"
        "📊 <b>Статистика</b> — сколько нашёл за день\n"
        "⚙️ <b>Фильтры</b> — цена, год, только собственники\n"
        "🎲 <b>Мудрость</b> — мудрость старого перекупа\n"
        f"{LINE}\n"
        "А ещё сам пришлю карточку, как найду годное 😎"
    ),
    "notify_urgent": "🆕🔥 Только что появилось! Хватай пока хозяин не передумал!",
    "notify_good": "🆕 Свежак подъехал, глянь 👇",
}

# Красивые имена источников.
SOURCE_NAMES = {
    "avito": "Avito", "drom": "Drom", "autoru": "Auto.ru",
    "youla": "Youla", "vk": "ВКонтакте", "telegram": "Telegram",
}

# Кнопки постоянной клавиатуры (тексты — они же ключи диспетчера).
BTN_FRESH = "🚘 Свежие тачки"
BTN_URGENT = "🔥 Срочные"
BTN_SEARCH = "🔍 Найти тачку"
BTN_COUNTRY = "🌍 По стране"
BTN_STATS = "📊 Статистика"
BTN_FILTERS = "⚙️ Фильтры"
BTN_WISDOM = "🎲 Мудрость"
BTN_HELP = "ℹ️ Помощь"

BACK = "⬅️ Назад"

# Шаги подбора.
SEARCH_BRANDS = [("Lada", "lada"), ("Renault", "renault"),
                 ("Kia", "kia"), ("Ford", "ford"),
                 ("Chevrolet", "chevrolet"), ("Hyundai", "hyundai")]
PRICE_CHOICES = [("до 80к", 80000), ("до 100к", 100000),
                 ("до 120к", 120000), ("до 150к", 150000)]
COUNTRY_PRICE_CHOICES = [("до 80к", 80000), ("до 120к", 120000),
                         ("до 150к", 150000)]
COND_LABELS = {"any": "Любое", "nodtp": "Без ДТП", "noresell": "Не перекуп"}


# ═══════════════════════════════════════════════════════════════════════════
#  Вспомогательное
# ═══════════════════════════════════════════════════════════════════════════

def _chunk(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]


def _state(uid) -> dict:
    """Состояние пошагового подбора пользователя."""
    return RUNTIME_CONFIG.setdefault("ui_state", {}).setdefault(uid, {})


def _filters(uid) -> dict:
    """Текущие фильтры пользователя."""
    return RUNTIME_CONFIG.setdefault("ui_filters", {}).setdefault(uid, {})


def safe_handler(func):
    """Обернуть handler в try/except: пользователю — перекупская фраза, в лог — реальная ошибка."""
    @wraps(func)
    async def wrapper(update, context):
        try:
            return await func(update, context)
        except Exception as e:
            logging.error(f"bot_interface.{func.__name__}: {e}")
            phrase = random.choice(ERROR_PHRASES)
            try:
                if update.message:
                    await update.message.reply_text(phrase)
                elif update.callback_query:
                    await update.callback_query.message.reply_text(phrase)
            except Exception:
                pass
    return wrapper


def _reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_FRESH, BTN_URGENT],
         [BTN_SEARCH, BTN_COUNTRY],
         [BTN_STATS, BTN_FILTERS],
         [BTN_WISDOM, BTN_HELP]],
        resize_keyboard=True,
    )


def _parse_title(title: str):
    """Грубо вытащить (модель, год) из заголовка 'Vaz 2107, 2026'."""
    if not title:
        return ("", "")
    parts = [p.strip() for p in title.split(",")]
    if len(parts) >= 2 and parts[-1][:4].isdigit():
        return (", ".join(parts[:-1]), parts[-1][:4])
    return (title, "")


def _norm_db(row: dict) -> dict:
    """Нормализовать строку БД (get_top5_today/search_listings/get_recent_listings) в данные карточки."""
    title = row.get("title") or ""
    model, year = _parse_title(title)
    price = row.get("last_price")
    if price is None:
        price = row.get("price", 0)
    score = row.get("last_dcb_score")
    if score is None:
        score = row.get("score", 0)
    return {
        "model": model or title or "Авто",
        "year": year,
        "price": price or 0,
        "score": score or 0,
        "url": row.get("listing_url") or row.get("url") or "",
        "source": row.get("source") or "",
        "listing_id": row.get("listing_id") or "",
        "pct": None, "mileage": None, "owner": None, "city": None, "mode": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Карточка объявления (HTML)
# ═══════════════════════════════════════════════════════════════════════════

def _badge(data: dict) -> str:
    mode = data.get("mode")
    if mode == "urgent":
        return "🔥 СРОЧНО"
    if mode == "good":
        return "💰 ВЫГОДНО"
    return "⭐ ЧЁТКИЙ ВАРИАНТ" if (data.get("score") or 0) >= 85 else "💰 ВЫГОДНО"


def render_card(data: dict) -> str:
    """Собрать HTML-карточку. Все пользовательские данные — через html.escape."""
    e = html.escape
    model = e(str(data.get("model") or "Авто"))
    year = data.get("year") or ""
    title = f"{model} {e(str(year))}".strip()
    src = SOURCE_NAMES.get(data.get("source") or "", data.get("source") or "сайте")

    price_line = f"💰 <b>{_fmt(data.get('price') or 0)} ₽</b>"
    if data.get("pct"):
        price_line += f"  (на {e(str(data['pct']))}% ниже рынка)"

    lines = [f"🚗 <b>{title}</b>", _badge(data), LINE, price_line]
    if data.get("mileage"):
        lines.append(f"🔢 {_fmt(data['mileage'])} км")
    if year:
        lines.append(f"📅 {e(str(year))}")
    if data.get("owner"):
        lines.append(f"👤 {e(str(data['owner']))}")
    if data.get("city"):
        lines.append(f"📍 {e(str(data['city']))}")
    lines.append(f"⭐ DCB Score: {data.get('score') or 0}/100")
    if data.get("visual_issues"):
        issues = "; ".join(str(i) for i in data["visual_issues"])
        lines.append(f"👁 По фото: {e(issues)}")
    lines.append("")
    lines.append(f"<i>\"{e(random.choice(VIBE_PHRASES))}\"</i>")
    if data.get("url"):
        lines.append("")
        lines.append(f"🔗 <a href=\"{e(data['url'])}\">Смотреть на {e(src)}</a>")
    return "\n".join(lines)


def _card_keyboard(data: dict) -> InlineKeyboardMarkup:
    lid = data.get("listing_id") or ""
    url = data.get("url") or ""
    row1 = [InlineKeyboardButton("🔄 Обновить", callback_data=f"bi_refresh_{lid}"),
            InlineKeyboardButton("⭐ В избранное", callback_data=f"bi_fav_{lid}")]
    row2 = [InlineKeyboardButton("📞 Телефон", callback_data="bi_phone")]
    if url:
        row2.append(InlineKeyboardButton("🔗 Открыть", url=url))
    return InlineKeyboardMarkup([row1, row2])


async def _send_card(message, data: dict):
    await message.reply_text(
        render_card(data), parse_mode="HTML",
        reply_markup=_card_keyboard(data), disable_web_page_preview=True,
    )


async def _send_cards(message, rows: list, header: str, empty_text: str):
    """Показать список объявлений карточками (по одной, с паузой)."""
    if not rows:
        await message.reply_text(empty_text)
        return
    await message.reply_text(header)
    for row in rows:
        await _send_card(message, _norm_db(row))
        await asyncio.sleep(0.4)


# ═══════════════════════════════════════════════════════════════════════════
#  Inline-клавиатуры шагов
# ═══════════════════════════════════════════════════════════════════════════

def _kb_brand() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(l, callback_data=f"bi_sb_{k}") for l, k in SEARCH_BRANDS]
    rows = _chunk(btns, 2)
    rows.append([InlineKeyboardButton("Любая", callback_data="bi_sb_any"),
                 InlineKeyboardButton(BACK, callback_data="bi_close")])
    return InlineKeyboardMarkup(rows)


def _kb_price() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(l, callback_data=f"bi_sp_{v}") for l, v in PRICE_CHOICES]
    rows = _chunk(btns, 2)
    rows.append([InlineKeyboardButton(BACK, callback_data="bi_search")])
    return InlineKeyboardMarkup(rows)


def _kb_cond() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Любое", callback_data="bi_sc_any"),
         InlineKeyboardButton("Без ДТП", callback_data="bi_sc_nodtp")],
        [InlineKeyboardButton("Не перекуп", callback_data="bi_sc_noresell"),
         InlineKeyboardButton(BACK, callback_data="bi_sstep_price")],
    ])


def _kb_country() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Наш автопром", callback_data="bi_cc_domestic"),
         InlineKeyboardButton("🌍 Иномарки", callback_data="bi_cc_foreign")],
        [InlineKeyboardButton(BACK, callback_data="bi_close")],
    ])


def _kb_country_price() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(l, callback_data=f"bi_cp_{v}") for l, v in COUNTRY_PRICE_CHOICES]
    rows = _chunk(btns, 3)
    rows.append([InlineKeyboardButton(BACK, callback_data="bi_country")])
    return InlineKeyboardMarkup(rows)


def _kb_filters(uid) -> InlineKeyboardMarkup:
    f = _filters(uid)
    mp, yf, own = f.get("max_price"), f.get("year_from"), f.get("owners_only", False)
    mark = lambda val, cur: "✅ " if val == cur else ""
    row_price = [InlineKeyboardButton(f"{mark(v, mp)}до {v // 1000}к",
                                      callback_data=f"bi_fprice_{v}")
                 for v in (100000, 120000, 150000)]
    row_year = [InlineKeyboardButton(f"{mark(y, yf)}от {y}",
                                     callback_data=f"bi_fyear_{y}")
                for y in (2005, 2010, 2015)]
    row_own = [InlineKeyboardButton(
        f"👤 Только собственники: {'вкл ✅' if own else 'выкл'}",
        callback_data="bi_fowners")]
    row_act = [InlineKeyboardButton("✅ Применить", callback_data="bi_fapply"),
               InlineKeyboardButton("🔄 Сбросить", callback_data="bi_freset")]
    return InlineKeyboardMarkup([row_price, row_year, row_own, row_act])


# ═══════════════════════════════════════════════════════════════════════════
#  Команды и кнопки постоянной клавиатуры
# ═══════════════════════════════════════════════════════════════════════════

@safe_handler
@authorized_only
async def cmd_ui_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — приветствие и постоянная клавиатура."""
    await update.message.reply_text(TEXTS["greeting"], reply_markup=_reply_kb())


@safe_handler
@authorized_only
async def cmd_ui_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/menu — показать клавиатуру меню."""
    await update.message.reply_text(TEXTS["greeting"], reply_markup=_reply_kb())


@safe_handler
@authorized_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Диспетчер нажатий постоянной клавиатуры."""
    text = (update.message.text or "").strip()
    uid = update.effective_user.id

    if text == BTN_FRESH:
        await _send_cards(update.message, get_top5_today(),
                          TEXTS["fresh_header"], TEXTS["fresh_empty"])
    elif text == BTN_URGENT:
        await _send_cards(update.message, get_recent_listings(60, 0, 5),
                          TEXTS["urgent_header"], TEXTS["urgent_empty"])
    elif text == BTN_SEARCH:
        _state(uid).clear()
        await update.message.reply_text(TEXTS["search_brand"], reply_markup=_kb_brand())
    elif text == BTN_COUNTRY:
        _state(uid).clear()
        await update.message.reply_text(TEXTS["country_step"], reply_markup=_kb_country())
    elif text == BTN_STATS:
        s = get_today_stats()
        src = get_source_stats()
        best = src.get("best", "—")
        await update.message.reply_text(TEXTS["stats"].format(
            n=s["analyzed"], m=s["notified"], score=s["avg_score"],
            src=SOURCE_NAMES.get(best, best),
        ))
    elif text == BTN_FILTERS:
        await update.message.reply_text(TEXTS["filters_title"], reply_markup=_kb_filters(uid))
    elif text == BTN_WISDOM:
        await update.message.reply_text(
            f"<i>\"{html.escape(random.choice(VIBE_PHRASES))}\"</i>", parse_mode="HTML")
    elif text == BTN_HELP:
        await update.message.reply_text(TEXTS["help"], parse_mode="HTML")
    # прочий текст игнорируем — не мешаем другим обработчикам


# ═══════════════════════════════════════════════════════════════════════════
#  Обработчик inline-кнопок (карточки + подбор + фильтры)
# ═══════════════════════════════════════════════════════════════════════════

async def _edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb,
                                  parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.debug(f"_edit: {e}")


async def _deliver(q, items, header):
    if not items:
        await _edit(q, TEXTS["search_empty"])
        return
    await _edit(q, header)
    for row in items:
        await _send_card(q.message, _norm_db(row))
        await asyncio.sleep(0.4)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единый обработчик всех bi_-callback'ов."""
    q = update.callback_query
    if q is None or not update.effective_user:
        return
    uid = update.effective_user.id
    if not _is_authorized(uid):
        await q.answer(TEXTS["denied"], show_alert=True)
        logging.warning(f"bot_interface: попытка доступа user_id={uid}")
        return

    data = q.data or ""
    try:
        # ── Заглушка телефона (alert, без снятия «часиков» отдельно) ──
        if data == "bi_phone":
            await q.answer(TEXTS["phone_stub"], show_alert=True)
            return

        await q.answer()

        # ── Кнопки карточки ──────────────────────────────────────────
        if data.startswith("bi_refresh_"):
            row = get_listing(data[len("bi_refresh_"):])
            if not row:
                await q.message.reply_text(TEXTS["gone"])
                return
            d = _norm_db(row)
            try:
                await q.edit_message_text(
                    render_card(d), parse_mode="HTML",
                    reply_markup=_card_keyboard(d), disable_web_page_preview=True)
            except Exception as e:
                logging.debug(f"refresh edit: {e}")
        elif data.startswith("bi_fav_"):
            lid = data[len("bi_fav_"):]
            added = add_favorite(uid, lid) if lid else False
            await q.answer(TEXTS["fav_added"] if added else TEXTS["fav_exists"],
                           show_alert=True)
        elif data == "bi_close":
            await _edit(q, TEXTS["closed"])

        # ── Подбор: марка → цена → состояние ─────────────────────────
        elif data == "bi_search":
            await _edit(q, TEXTS["search_brand"], _kb_brand())
        elif data.startswith("bi_sb_"):
            brand = data[len("bi_sb_"):]
            _state(uid)["brand"] = None if brand == "any" else brand
            await _edit(q, TEXTS["search_price"], _kb_price())
        elif data == "bi_sstep_price":
            await _edit(q, TEXTS["search_price"], _kb_price())
        elif data.startswith("bi_sp_"):
            _state(uid)["max_price"] = int(data[len("bi_sp_"):])
            await _edit(q, TEXTS["search_cond"], _kb_cond())
        elif data.startswith("bi_sc_"):
            st = _state(uid)
            st["condition"] = data[len("bi_sc_"):]
            cond = st["condition"] if st["condition"] != "any" else None
            f = _filters(uid)
            items = search_listings(brand=st.get("brand"),
                                    max_price=st.get("max_price"),
                                    condition=cond,
                                    year_from=f.get("year_from"),
                                    owners_only=f.get("owners_only", False),
                                    min_score=0, limit=5)
            await _deliver(q, items, TEXTS["search_header"])

        # ── По стране: страна → сумма ────────────────────────────────
        elif data == "bi_country":
            await _edit(q, TEXTS["country_step"], _kb_country())
        elif data.startswith("bi_cc_"):
            _state(uid)["country"] = data[len("bi_cc_"):]
            await _edit(q, TEXTS["country_price"], _kb_country_price())
        elif data.startswith("bi_cp_"):
            st = _state(uid)
            st["max_price"] = int(data[len("bi_cp_"):])
            f = _filters(uid)
            items = search_listings(country=st.get("country"),
                                    max_price=st.get("max_price"),
                                    year_from=f.get("year_from"),
                                    owners_only=f.get("owners_only", False),
                                    min_score=0, limit=5)
            await _deliver(q, items, TEXTS["country_header"])

        # ── Фильтры ──────────────────────────────────────────────────
        elif data.startswith("bi_fprice_"):
            _filters(uid)["max_price"] = int(data[len("bi_fprice_"):])
            await _edit(q, TEXTS["filters_title"], _kb_filters(uid))
        elif data.startswith("bi_fyear_"):
            _filters(uid)["year_from"] = int(data[len("bi_fyear_"):])
            await _edit(q, TEXTS["filters_title"], _kb_filters(uid))
        elif data == "bi_fowners":
            f = _filters(uid)
            f["owners_only"] = not f.get("owners_only", False)
            await _edit(q, TEXTS["filters_title"], _kb_filters(uid))
        elif data == "bi_fapply":
            f = _filters(uid)
            if f.get("max_price"):
                set_value("MAX_PRICE", f["max_price"])
            await _edit(q, TEXTS["filters_applied"])
        elif data == "bi_freset":
            _filters(uid).clear()
            await _edit(q, TEXTS["filters_reset"], _kb_filters(uid))

        else:
            logging.debug(f"bot_interface: неизвестный callback {data}")
    except Exception as e:
        logging.error(f"bot_interface.on_callback ({data}): {e}")
        try:
            await q.message.reply_text(random.choice(ERROR_PHRASES))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#  Интеграция с notifier.py
# ═══════════════════════════════════════════════════════════════════════════

def build_notification(result: dict):
    """Собрать (текст_HTML, InlineKeyboardMarkup) для уведомления о новом объявлении.

    Используется notifier.send_notification. Шапка зависит от режима (urgent/good).
    """
    listing = result.get("listing", {}) or {}
    market = result.get("market", {}) or {}
    mode = result.get("notification_mode")

    sac = listing.get("seller_ads_count", 0) or 0
    owner = "Перекуп" if sac and sac > 1 else "Собственник"

    data = {
        "model": listing.get("title") or "Авто",
        "year": listing.get("year") or "",
        "price": listing.get("price") or 0,
        "pct": market.get("undervaluation_pct") or None,
        "mileage": listing.get("mileage") or None,
        "owner": owner,
        "city": listing.get("city") or None,
        "score": result.get("dcb_score", 0),
        "source": listing.get("source", ""),
        "url": listing.get("listing_url", ""),
        "listing_id": listing.get("listing_id", ""),
        "mode": mode,
        "visual_issues": result.get("visual_issues") or None,
    }

    header = TEXTS["notify_urgent"] if mode == "urgent" else TEXTS["notify_good"]
    extra = []
    if result.get("arbitrage"):
        arb = result["arbitrage"]
        extra.append(f"🚚 Арбитраж из {html.escape(str(arb.get('city', '?')))}: "
                     f"+{_fmt(arb.get('net_profit', 0))} ₽")
    if result.get("price_dropped"):
        extra.append(f"🔄 Цена упала на {_fmt(result.get('drop_amount', 0))} ₽")
    extra_str = ("\n" + "\n".join(extra)) if extra else ""

    text = f"{header}{extra_str}\n\n{render_card(data)}"
    return text, _card_keyboard(data)


# ═══════════════════════════════════════════════════════════════════════════
#  Регистрация
# ═══════════════════════════════════════════════════════════════════════════

def get_interface_handlers() -> list:
    """Handlers перекупского интерфейса. Регистрировать ДО bot_commands —
    у нового интерфейса приоритет на /start и /menu."""
    return [
        CommandHandler("start", cmd_ui_start),
        CommandHandler("menu", cmd_ui_menu),
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
        CallbackQueryHandler(on_callback, pattern=r"^bi_"),
    ]
