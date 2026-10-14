"""
Расширение менеджерской футбольной лиги:
- календарь сезона (летнее/зимнее трансферные окна и европейские турниры);
- каталог европейских лиг;
- меню-кнопки Telegram для aiogram 3.x;
- таблицы создаются отдельно и не меняют существующую схему career.py.

Подключение:
    import career_expansion as cx
    cx.install()
    # В обработчике /start: await message.answer("Меню", reply_markup=cx.main_keyboard())
"""
from datetime import date, timedelta
import json
import db

EUROPEAN_LEAGUES = [
    {"country": "Англия", "name": "Premier League", "tier": 1, "teams": 20},
    {"country": "Англия", "name": "Championship", "tier": 2, "teams": 24},
    {"country": "Испания", "name": "La Liga", "tier": 1, "teams": 20},
    {"country": "Испания", "name": "La Liga 2", "tier": 2, "teams": 22},
    {"country": "Италия", "name": "Serie A", "tier": 1, "teams": 20},
    {"country": "Италия", "name": "Serie B", "tier": 2, "teams": 20},
    {"country": "Германия", "name": "Bundesliga", "tier": 1, "teams": 18},
    {"country": "Германия", "name": "2. Bundesliga", "tier": 2, "teams": 18},
    {"country": "Франция", "name": "Ligue 1", "tier": 1, "teams": 18},
    {"country": "Франция", "name": "Ligue 2", "tier": 2, "teams": 18},
    {"country": "Португалия", "name": "Primeira Liga", "tier": 1, "teams": 18},
    {"country": "Нидерланды", "name": "Eredivisie", "tier": 1, "teams": 18},
    {"country": "Бельгия", "name": "Belgian Pro League", "tier": 1, "teams": 16},
    {"country": "Шотландия", "name": "Scottish Premiership", "tier": 1, "teams": 12},
    {"country": "Турция", "name": "Süper Lig", "tier": 1, "teams": 18},
    {"country": "Австрия", "name": "Austrian Bundesliga", "tier": 1, "teams": 12},
    {"country": "Швейцария", "name": "Swiss Super League", "tier": 1, "teams": 12},
    {"country": "Греция", "name": "Super League Greece", "tier": 1, "teams": 14},
    {"country": "Россия", "name": "РПЛ", "tier": 1, "teams": 16},
    {"country": "Украина", "name": "УПЛ", "tier": 1, "teams": 16},
    {"country": "Дания", "name": "Danish Superliga", "tier": 1, "teams": 12},
    {"country": "Норвегия", "name": "Eliteserien", "tier": 1, "teams": 16},
    {"country": "Швеция", "name": "Allsvenskan", "tier": 1, "teams": 16},
    {"country": "Польша", "name": "Ekstraklasa", "tier": 1, "teams": 18},
    {"country": "Чехия", "name": "Czech First League", "tier": 1, "teams": 16},
    {"country": "Хорватия", "name": "HNL", "tier": 1, "teams": 10},
    {"country": "Сербия", "name": "Serbian SuperLiga", "tier": 1, "teams": 16},
]

EUROPEAN_TOURNAMENTS = [
    ("UCL", "Лига чемпионов УЕФА", "continental"),
    ("UEL", "Лига Европы УЕФА", "continental"),
    ("UECL", "Лига конференций УЕФА", "continental"),
    ("USC", "Суперкубок УЕФА", "supercup"),
    ("FAKE_NONE", "Кубки национальных ассоциаций", "domestic_cup"),
]

# Модельный календарь на сезон: даты ориентировочные, а не официальный календарь УЕФА.
# Для игровых сезонов применяется год начала сезона.
def season_calendar(start_year=None):
    y = start_year or date.today().year
    events = [
        ("summer_window_open", "Открытие летнего трансферного окна", date(y, 6, 15), "transfer"),
        ("summer_window_close", "Закрытие летнего трансферного окна", date(y, 8, 31), "transfer"),
        ("league_start", "Старт национальных лиг", date(y, 8, 10), "league"),
        ("ucl_league_phase", "Еврокубки: основной этап", date(y, 9, 16), "europe"),
        ("winter_window_open", "Открытие зимнего трансферного окна", date(y + 1, 1, 1), "transfer"),
        ("winter_window_close", "Закрытие зимнего трансферного окна", date(y + 1, 1, 31), "transfer"),
        ("uefa_super_cup", "Суперкубок УЕФА", date(y, 8, 13), "europe"),
        ("ucl_final", "Финал Лиги чемпионов", date(y + 1, 5, 29), "europe"),
        ("uel_final", "Финал Лиги Европы", date(y + 1, 5, 20), "europe"),
        ("uecl_final", "Финал Лиги конференций", date(y + 1, 5, 27), "europe"),
        ("league_end", "Финиш национальных лиг", date(y + 1, 5, 24), "league"),
        ("season_end", "Итоги сезона и развитие игроков", date(y + 1, 6, 1), "season"),
    ]
    return sorted(
        [{"event_key": k, "title": title, "event_date": d.isoformat(), "category": cat}
         for k, title, d, cat in events],
        key=lambda e: e["event_date"]
    )

def install():
    """Создать дополнительные таблицы. Безопасно вызывать при запуске бота."""
    db.x("""CREATE TABLE IF NOT EXISTS career_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season INTEGER NOT NULL,
        event_key TEXT NOT NULL,
        title TEXT NOT NULL,
        event_date TEXT NOT NULL,
        category TEXT NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        UNIQUE(season, event_key)
    )""")
    db.x("""CREATE TABLE IF NOT EXISTS career_competitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season INTEGER NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'scheduled',
        UNIQUE(season, code)
    )""")
    db.x("""CREATE TABLE IF NOT EXISTS career_leagues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT NOT NULL,
        name TEXT NOT NULL UNIQUE,
        tier INTEGER NOT NULL,
        team_count INTEGER NOT NULL
    )""")
    for row in EUROPEAN_LEAGUES:
        db.x("INSERT OR IGNORE INTO career_leagues(country,name,tier,team_count) VALUES(?,?,?,?)",
             (row["country"], row["name"], row["tier"], row["teams"]))
    for code, name, kind in EUROPEAN_TOURNAMENTS:
        if code == "FAKE_NONE":
            continue
        db.x("INSERT OR IGNORE INTO career_competitions(season,code,name,kind) VALUES(1,?,?,?)",
             (code, name, kind))

def create_season_calendar(season_no, start_year=None):
    """Добавить календарь для игрового сезона; повторный вызов не дублирует события."""
    for e in season_calendar(start_year):
        db.x("""INSERT OR IGNORE INTO career_calendar
             (season,event_key,title,event_date,category) VALUES(?,?,?,?,?)""",
             (season_no, e["event_key"], e["title"], e["event_date"], e["category"]))
    for code, name, kind in EUROPEAN_TOURNAMENTS:
        if code != "FAKE_NONE":
            db.x("INSERT OR IGNORE INTO career_competitions(season,code,name,kind) VALUES(?,?,?,?)",
                 (season_no, code, name, kind))
    return calendar(season_no)

def calendar(season_no, category=None):
    if category:
        return db.q("SELECT * FROM career_calendar WHERE season=? AND category=? ORDER BY event_date",
                    (season_no, category))
    return db.q("SELECT * FROM career_calendar WHERE season=? ORDER BY event_date", (season_no,))

def upcoming_events(season_no, today=None, limit=8):
    today = (today or date.today()).isoformat()
    return db.q("""SELECT * FROM career_calendar
        WHERE season=? AND completed=0 AND event_date>=?
        ORDER BY event_date LIMIT ?""", (season_no, today, limit))

def mark_event_done(event_id):
    db.x("UPDATE career_calendar SET completed=1 WHERE id=?", (event_id,))

def leagues(country=None):
    if country:
        return db.q("SELECT * FROM career_leagues WHERE country=? ORDER BY tier,name", (country,))
    return db.q("SELECT * FROM career_leagues ORDER BY country,tier,name")

def competitions(season_no):
    return db.q("SELECT * FROM career_competitions WHERE season=? ORDER BY kind,name", (season_no,))

# Клавиатуры для aiogram 3.x. Импорт внутри функции позволяет использовать модуль
# даже если Telegram-библиотека пока не установлена.
def main_keyboard():
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    rows = [
        [KeyboardButton(text="🏟 Мой клуб"), KeyboardButton(text="📅 Календарь")],
        [KeyboardButton(text="⚽ Состав"), KeyboardButton(text="🧠 Тактика")],
        [KeyboardButton(text="🔁 Трансферы"), KeyboardButton(text="🏋️ Тренировки")],
        [KeyboardButton(text="🏆 Турниры"), KeyboardButton(text="🌍 Европейские лиги")],
        [KeyboardButton(text="💶 Финансы"), KeyboardButton(text="📊 Таблица")],
        [KeyboardButton(text="▶️ Следующий тур"), KeyboardButton(text="❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="Выберите раздел")

def calendar_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Все события", callback_data="cal:all")],
        [InlineKeyboardButton(text="☀️ Летнее окно", callback_data="cal:summer")],
        [InlineKeyboardButton(text="❄️ Зимнее окно", callback_data="cal:winter")],
        [InlineKeyboardButton(text="🏆 Еврокубки", callback_data="cal:europe")],
        [InlineKeyboardButton(text="↩️ Главное меню", callback_data="menu:main")],
    ])

def tournaments_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Лига чемпионов", callback_data="cup:UCL"),
         InlineKeyboardButton(text="🥈 Лига Европы", callback_data="cup:UEL")],
        [InlineKeyboardButton(text="🥉 Лига конференций", callback_data="cup:UECL")],
        [InlineKeyboardButton(text="🛡 Суперкубок УЕФА", callback_data="cup:USC")],
        [InlineKeyboardButton(text="↩️ Главное меню", callback_data="menu:main")],
    ])

def format_events(events):
    if not events:
        return "В календаре пока нет событий. Создайте календарь сезона."
    return "\\n".join(f"📅 {e['event_date']} — {e['title']}" for e in events)

def format_leagues(rows=None):
    rows = rows if rows is not None else leagues()
    if not rows:
        return "Список лиг пуст."
    last = None
    out = ["🌍 Европейские лиги:"]
    for r in rows:
        if r["country"] != last:
            last = r["country"]
            out.append(f"\\n🇪🇺 {last}")
        out.append(f"• {r['name']} (дивизион {r['tier']}, {r['team_count']} клубов)")
    return "\\n".join(out)

def format_competitions(rows):
    if not rows:
        return "Турниры ещё не созданы для этого сезона."
    return "\\n".join(f"🏆 {r['name']} — {r['status']}" for r in rows)
