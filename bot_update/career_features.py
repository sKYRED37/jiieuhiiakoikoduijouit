"""Дополнительные функции для карьерного бота.

Важно: список клубов — каталог состава топ-7 лиг сезона 2025/26. Он не превращает
старый однотурнирный движок в семь независимых чемпионатов: для этого надо менять
схему fixtures/table и основной движок, которых в исходном пакете нет.
Суммы в существующем career.py хранятся в тысячах евро.
"""
from datetime import date, timedelta
import random
import db
import career

TOP7_LEAGUES = {
    "Англия · Premier League": [
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Burnley",
        "Chelsea", "Crystal Palace", "Everton", "Fulham", "Leeds United", "Liverpool",
        "Manchester City", "Manchester United", "Newcastle United", "Nottingham Forest",
        "Sunderland", "Tottenham Hotspur", "West Ham United", "Wolverhampton Wanderers"],
    "Испания · La Liga": [
        "Athletic Club", "Atlético Madrid", "Barcelona", "Celta Vigo", "Elche", "Espanyol",
        "Getafe", "Girona", "Levante", "Mallorca", "Osasuna", "Rayo Vallecano", "Real Betis",
        "Real Madrid", "Real Oviedo", "Real Sociedad", "Sevilla", "Valencia", "Villarreal", "Alavés"],
    "Италия · Serie A": [
        "Atalanta", "Bologna", "Cagliari", "Como", "Cremonese", "Fiorentina", "Genoa", "Inter",
        "Juventus", "Lazio", "Lecce", "Milan", "Napoli", "Parma", "Pisa", "Roma", "Sassuolo",
        "Torino", "Udinese", "Hellas Verona"],
    "Германия · Bundesliga": [
        "Augsburg", "Bayer Leverkusen", "Bayern Munich", "Borussia Dortmund", "Borussia Mönchengladbach",
        "Eintracht Frankfurt", "FC Heidenheim", "Hamburger SV", "Hoffenheim", "Mainz 05", "RB Leipzig",
        "SC Freiburg", "St. Pauli", "Union Berlin", "VfB Stuttgart", "Werder Bremen", "Wolfsburg", "1. FC Köln"],
    "Франция · Ligue 1": [
        "Angers", "Auxerre", "Brest", "Le Havre", "Lens", "Lille", "Lorient", "Lyon", "Marseille",
        "Metz", "Monaco", "Nantes", "Nice", "Paris FC", "Paris Saint-Germain", "Rennes", "Strasbourg", "Toulouse"],
    "Нидерланды · Eredivisie": [
        "Ajax", "AZ Alkmaar", "Excelsior", "Feyenoord", "Fortuna Sittard", "Go Ahead Eagles", "Groningen",
        "Heerenveen", "Heracles Almelo", "NAC Breda", "NEC Nijmegen", "PEC Zwolle", "PSV Eindhoven",
        "Sparta Rotterdam", "Telstar", "Twente", "Utrecht", "Volendam"],
    "Португалия · Primeira Liga": [
        "Alverca", "Arouca", "AVS", "Benfica", "Braga", "Casa Pia", "Estoril", "Estrela Amadora",
        "Famalicão", "Gil Vicente", "Moreirense", "Nacional", "Porto", "Rio Ave", "Santa Clara",
        "Sporting CP", "Tondela", "Vitória SC"],
}

# Окна для товарищеских матчей во время международных пауз (приблизительная модель).
_BREAK_WINDOWS = [(date(2000, 9, 1), date(2000, 9, 9)),
                  (date(2000, 10, 6), date(2000, 10, 14)),
                  (date(2000, 11, 10), date(2000, 11, 18)),
                  (date(2000, 3, 23), date(2000, 3, 31))]


def install():
    db.x("""CREATE TABLE IF NOT EXISTS career_friendlies (
        id INTEGER PRIMARY KEY AUTOINCREMENT, season INTEGER NOT NULL,
        played_on TEXT NOT NULL, home_id INTEGER NOT NULL, away_id INTEGER NOT NULL,
        home_goals INTEGER NOT NULL, away_goals INTEGER NOT NULL,
        is_international_break INTEGER NOT NULL DEFAULT 1)""")
    db.x("""CREATE TABLE IF NOT EXISTS career_friendly_players (
        friendly_id INTEGER NOT NULL, player_id INTEGER NOT NULL,
        match_rating REAL NOT NULL, PRIMARY KEY(friendly_id, player_id))""")
    db.x("""CREATE TABLE IF NOT EXISTS career_club_catalog (
        league TEXT NOT NULL, club_name TEXT NOT NULL, season_label TEXT NOT NULL DEFAULT '2025/26',
        PRIMARY KEY(league, club_name))""")
    for league, names in TOP7_LEAGUES.items():
        for name in names:
            db.x("INSERT OR IGNORE INTO career_club_catalog(league,club_name) VALUES(?,?)", (league, name))


def catalog():
    return {league: list(names) for league, names in TOP7_LEAGUES.items()}


def is_international_break(day=None):
    day = day or date.today()
    # Match month/day, independent of season year.
    for a, b in _BREAK_WINDOWS:
        start, end = date(day.year, a.month, a.day), date(day.year, b.month, b.day)
        if start <= day <= end:
            return True
    return False


def _field(row, key, default=None):
    try:
        value = row[key]
        return default if value is None else value
    except (KeyError, IndexError, TypeError):
        return default


def _rating(club_row, players):
    if not players:
        return float(club_row["rep"])
    top = sorted((float(p["ovr"]) + (float(_field(p, "form", 6.5) or 6.5) - 6.5) * 1.2 for p in players), reverse=True)[:11]
    return sum(top) / max(1, len(top)) * 0.72 + float(club_row["rep"]) * 0.28


def play_friendly(home_id, away_id, day=None, force=False):
    """Сыграть товарищеский матч. Не меняет таблицу и статистику официальной лиги.

    Форма участвовавших игроков слегка обновляется, чтобы поддерживать игровой тонус.
    По умолчанию доступно только в международную паузу; force=True предназначен для админа.
    """
    day = day or date.today()
    if home_id == away_id:
        raise ValueError("Нельзя играть товарищеский матч против самого себя.")
    if not force and not is_international_break(day):
        raise ValueError("Сейчас нет международной паузы. Товарищеские матчи доступны в международные окна.")
    home, away = career.club(home_id), career.club(away_id)
    if not home or not away:
        raise ValueError("Один из клубов не найден.")
    hp, ap = career.club_players(home_id), career.club_players(away_id)
    hs, as_ = _rating(home, hp), _rating(away, ap)
    # Пуассон-подобная, но лёгкая симуляция; фактор поля и случайность дают разные результаты.
    hg = max(0, min(6, int(random.gauss(1.25 + (hs-as_)*0.055 + 0.25, 1.15))))
    ag = max(0, min(6, int(random.gauss(1.15 + (as_-hs)*0.055, 1.10))))
    with db.tx():
        fid = db.x("INSERT INTO career_friendlies(season,played_on,home_id,away_id,home_goals,away_goals,is_international_break) VALUES(?,?,?,?,?,?,?)",
                    (career.season(), day.isoformat(), home_id, away_id, hg, ag, int(is_international_break(day))))
        for squad in (hp, ap):
            # Лучшие 11 получают игровую практику; все остальные не теряют форму.
            chosen = sorted(squad, key=lambda p: float(p["ovr"]), reverse=True)[:11]
            for pl in chosen:
                old_form = float(_field(pl, "form", 6.5) or 6.5)
                rating = max(5.5, min(8.5, random.gauss(6.6 + (float(pl["ovr"])-60)*0.012, 0.55)))
                new_form = max(4.0, min(9.5, old_form * 0.65 + rating * 0.35))
                db.x("UPDATE players SET apps=apps+1, rating_sum=rating_sum+?, form=? WHERE id=?", (rating, new_form, pl["id"]))
                db.x("INSERT INTO career_friendly_players(friendly_id,player_id,match_rating) VALUES(?,?,?)", (fid, pl["id"], rating))
    return {"id": fid, "date": day.isoformat(), "home": home["name"], "away": away["name"],
            "home_goals": hg, "away_goals": ag, "international_break": is_international_break(day)}


def friendly_history(limit=10):
    return db.q("""SELECT f.*, h.name home_name, a.name away_name FROM career_friendlies f
        JOIN clubs h ON h.id=f.home_id JOIN clubs a ON a.id=f.away_id
        ORDER BY f.id DESC LIMIT ?""", (limit,))


def friendly_keyboard(own_id):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for c in db.q("SELECT id,name,rep FROM clubs WHERE id<>? ORDER BY rep DESC", (own_id,))[:30]:
        rows.append([InlineKeyboardButton(text=f"🤝 {c['name']} · {c['rep']}", callback_data=f"friendly:{c['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Нет соперников", callback_data="friendly:none")]])
