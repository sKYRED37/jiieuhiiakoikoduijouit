"""Карьера тренера: лига, расписание, туры, тактика, тренировки, скаутинг, трансферы,
финансы, совет директоров, увольнение/новая работа, конец сезона, академия.

Все публичные функции возвращают простые dict/tuple — форматирование для Telegram делает бот.
Транзакции (db.tx) не вкладываются: tx() открывают только публичные функции верхнего уровня.
"""
import math
import random

import db
import engine as E
from engine import clamp, money

CLUB_NAMES = [
    "Northport", "Real Alvar", "Dinamo Karst", "Sporting Verda", "Athletic Brenn",
    "FC Lunden", "Olympia Rhein", "Borussia Held", "Torino Vale", "Ajax Moor",
    "Spartak Veles", "Racing Corva", "Union Arden", "Lokomotiv Sava", "Celtic Fenn",
    "Rapid Oster", "Benfica Lis", "Galata Bosk", "Zenit Nevsk", "Vitesse Aalm",
]
MIN_SQUAD, MAX_SQUAD = 20, 32
MIN_POS = {"GK": 2, "DEF": 6, "MID": 6, "FWD": 3}
SCOUT_COST = 25  # тыс. €


# ---------- Базовые помощники ----------

def season():
    return db.get_meta("season", 1)


def matchday():
    return db.get_meta("md", 1)


def total_mds():
    return db.get_meta("total_md", 38)


def club(cid):
    return db.one("SELECT * FROM clubs WHERE id = ?", (cid,))


def player(pid):
    return db.one("SELECT * FROM players WHERE id = ?", (pid,))


def club_players(cid):
    return db.q("SELECT * FROM players WHERE club_id = ?", (cid,))


def _count(cid):
    return db.one("SELECT COUNT(*) n FROM players WHERE club_id = ?", (cid,))["n"]


def _is_managed(cid):
    return bool(cid) and db.one(
        "SELECT 1 FROM managers WHERE club_id = ? AND sacked = 0", (cid,)) is not None


def club_strength(rep):
    return 40 + rep * 0.4


def _income(rep):
    """Еженедельный доход клуба (тыс. €), растёт с репутацией."""
    return int(220 * math.exp(0.045 * (rep - 55)))


def _insert_player(cid, p):
    return db.x(
        "INSERT INTO players (club_id, name, pos, age, ovr, pot, profile, wage) VALUES (?,?,?,?,?,?,?,?)",
        (cid, p["name"], p["pos"], p["age"], p["ovr"], p["pot"], p["profile"], p["wage"]))


def _is_key(p):
    """Игрок в стартовом составе клуба по своей позиции (по OVR)."""
    mates = sorted([m for m in club_players(p["club_id"]) if m["pos"] == p["pos"]],
                   key=lambda m: -m["ovr"])
    return p["id"] in [m["id"] for m in mates[:E.SQUAD_STARTERS[p["pos"]]]]


def asking_price(p):
    """Цена, которую просит клуб-продавец (тыс. €)."""
    if not p["club_id"]:
        return 0
    mult = 1.0 if p["listed"] else 1.25
    if _is_key(p):
        mult += 0.15
    return max(50, int(E.player_value(p) * mult / 50) * 50)


# ---------- Создание лиги, расписание, таблица ----------

def new_league(n=20):
    """Полный сброс и создание новой лиги: клубы, составы, свободные агенты, календарь."""
    n = min(n, len(CLUB_NAMES))
    db.reset()
    with db.tx():
        reps = sorted(random.sample(range(52, 93), n), reverse=True)
        for name, rep in zip(random.sample(CLUB_NAMES, n), reps):
            cid = db.x(
                "INSERT INTO clubs (name, rep, budget, formation, mentality) VALUES (?,?,?,?,?)",
                (name, rep, 100000, random.choice(list(E.FORMATIONS)),
                 random.choice(["attack", "balanced", "balanced", "defend"])))
            for p in E.gen_squad(club_strength(rep)):
                _insert_player(cid, p)
        for _ in range(30):
            _insert_player(0, E.gen_player(random.choice(E.POSITIONS), 58))
        db.set_meta("season", 1)
        db.set_meta("md", 1)
        _set_objectives()
        _make_fixtures(1)


def _set_objectives():
    rows = db.q("SELECT id FROM clubs ORDER BY rep DESC, id")
    for i, r in enumerate(rows, 1):
        db.x("UPDATE clubs SET objective = ? WHERE id = ?", (max(1, i - (1 if i > 3 else 0)), r["id"]))


def _make_fixtures(s):
    """Двухкруговой турнир методом «круга»."""
    ids = [r["id"] for r in db.q("SELECT id FROM clubs ORDER BY id")]
    random.shuffle(ids)
    if len(ids) % 2:
        ids.append(None)
    m, arr, rounds = len(ids), ids[:], []
    for r in range(m - 1):
        pairs = []
        for i in range(m // 2):
            a, b = arr[i], arr[m - 1 - i]
            if a is None or b is None:
                continue
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        arr = [arr[0], arr[-1]] + arr[1:-1]
    md = 1
    for swap in (False, True):
        for pairs in rounds:
            for h, a in pairs:
                db.x("INSERT INTO fixtures (season, md, home, away) VALUES (?,?,?,?)",
                     (s, md, a if swap else h, h if swap else a))
            md += 1
    db.set_meta("total_md", md - 1)


def table(s=None):
    s = s or season()
    rows = {c["id"]: dict(id=c["id"], name=c["name"], p=0, w=0, d=0, l=0, gf=0, ga=0, gd=0, pts=0)
            for c in db.q("SELECT id, name FROM clubs")}
    for f in db.q("SELECT * FROM fixtures WHERE season = ? AND played = 1", (s,)):
        for cid, gf, ga in ((f["home"], f["hg"], f["ag"]), (f["away"], f["ag"], f["hg"])):
            r = rows[cid]
            r["p"] += 1
            r["gf"] += gf
            r["ga"] += ga
            r["gd"] = r["gf"] - r["ga"]
            if gf > ga:
                r["w"] += 1
                r["pts"] += 3
            elif gf == ga:
                r["d"] += 1
                r["pts"] += 1
            else:
                r["l"] += 1
    return sorted(rows.values(), key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["name"]))


def position(cid):
    for i, r in enumerate(table(), 1):
        if r["id"] == cid:
            return i
    return 0


def next_fixture(cid):
    return db.one(
        "SELECT * FROM fixtures WHERE season = ? AND played = 0 AND (home = ? OR away = ?) "
        "ORDER BY md LIMIT 1", (season(), cid, cid))


def top_scorers(limit=10):
    return db.q(
        "SELECT p.id, p.name, p.pos, p.goals, p.assists, p.apps, c.name AS club FROM players p "
        "LEFT JOIN clubs c ON c.id = p.club_id WHERE p.goals > 0 OR p.assists > 0 "
        "ORDER BY p.goals DESC, p.assists DESC, p.apps ASC LIMIT ?", (limit,))


# ---------- Тренер: регистрация, работа, увольнение ----------

def get_manager(uid):
    return db.one("SELECT * FROM managers WHERE user_id = ?", (uid,))


def register_manager(uid, name):
    if not get_manager(uid):
        db.x("INSERT INTO managers (user_id, name, club_id, sacked) VALUES (?,?,NULL,0)", (uid, name))
    return get_manager(uid)


def job_offers(uid):
    """Свободные клубы. Уволенному тренеру доступна только нижняя половина по репутации."""
    free = db.q("SELECT * FROM clubs WHERE id NOT IN "
                "(SELECT club_id FROM managers WHERE club_id IS NOT NULL AND sacked = 0) ORDER BY rep")
    m = get_manager(uid)
    if m and m["sacked"]:
        total = db.one("SELECT COUNT(*) n FROM clubs")["n"]
        free = [c for c in free if c["rep"] <= sorted(
            r["rep"] for r in db.q("SELECT rep FROM clubs"))[total // 2]]
    return free


def take_job(uid, cid):
    m = get_manager(uid)
    if not m:
        return False, "Сначала зарегистрируйтесь как тренер"
    if m["club_id"] and not m["sacked"]:
        return False, "Вы уже возглавляете клуб"
    if cid not in [c["id"] for c in job_offers(uid)]:
        return False, "Этот клуб вам недоступен"
    db.x("UPDATE managers SET club_id = ?, sacked = 0 WHERE user_id = ?", (cid, uid))
    db.x("UPDATE clubs SET board_conf = 60, trained_md = -1 WHERE id = ?", (cid,))
    return True, f"Вы назначены главным тренером «{club(cid)['name']}»"


def resign(uid):
    m = get_manager(uid)
    if not m or not m["club_id"]:
        return False, "У вас нет клуба"
    db.x("UPDATE managers SET club_id = NULL WHERE user_id = ?", (uid,))
    return True, "Вы покинули пост по собственному желанию"


def _sack(uid):
    db.x("UPDATE managers SET club_id = NULL, sacked = 1 WHERE user_id = ?", (uid,))


def _board_update(cid, delta):
    c = club(cid)
    db.x("UPDATE clubs SET board_conf = ? WHERE id = ?",
         (int(clamp(round(c["board_conf"] + delta), 0, 100)), cid))


# ---------- Тактика, тренировки ----------

def set_tactics(cid, formation=None, mentality=None):
    if formation:
        if formation not in E.FORMATIONS:
            return False, "Схемы: " + ", ".join(E.FORMATIONS)
        db.x("UPDATE clubs SET formation = ? WHERE id = ?", (formation, cid))
    if mentality:
        m = E.MENTALITY_ALIASES.get(mentality.lower())
        if not m:
            return False, "Менталитет: атака / баланс / защита"
        db.x("UPDATE clubs SET mentality = ? WHERE id = ?", (m, cid))
    c = club(cid)
    return True, f"Схема {c['formation']}, менталитет: {E.MENTALITY_RU[c['mentality']]}"


def train(cid, focus=None):
    """Одна тренировка за тур: форма всем, небольшой шанс роста OVR у молодых (до 23 лет)."""
    md = matchday()
    if club(cid)["trained_md"] == md:
        return False, "В этом туре тренировка уже проведена"
    pos = E.POS_ALIASES.get(focus.lower()) if focus else None
    if focus and not pos:
        return False, "Позиции: ВРТ / ЗАЩ / ПЗ / НАП"
    grown = []
    with db.tx():
        for p in club_players(cid):
            if p["injury"] > 0:
                continue
            on_focus = pos == p["pos"]
            form = clamp(p["form"] + 0.3 + (0.3 if on_focus else 0), 4.0, 9.5)
            ovr = p["ovr"]
            if p["age"] <= 23 and ovr < p["pot"] and random.random() < (0.06 if on_focus else 0.03):
                ovr += 1
                grown.append(p["name"])
            db.x("UPDATE players SET form = ?, ovr = ? WHERE id = ?", (form, ovr, p["id"]))
        db.x("UPDATE clubs SET trained_md = ? WHERE id = ?", (md, cid))
    return True, "Тренировка проведена" + (f". Прогресс: {', '.join(grown)}" if grown else "")


# ---------- Скаутинг ----------

def is_scouted(cid, pid):
    p = player(pid)
    return bool(p and p["club_id"] == cid) or db.one(
        "SELECT 1 FROM scouted WHERE club_id = ? AND player_id = ?", (cid, pid)) is not None


def scout(cid, pid):
    """Платный отчёт: открывает потенциал и профиль развития чужого игрока."""
    p = player(pid)
    if not p:
        return False, "Игрок не найден"
    if is_scouted(cid, pid):
        return True, "Отчёт уже есть"
    if club(cid)["budget"] < SCOUT_COST:
        return False, "Недостаточно средств на скаутинг"
    with db.tx():
        db.x("UPDATE clubs SET budget = budget - ? WHERE id = ?", (SCOUT_COST, cid))
        db.x("INSERT OR IGNORE INTO scouted (club_id, player_id) VALUES (?,?)", (cid, pid))
    return True, f"Отчёт готов (−{money(SCOUT_COST)})"


def market(cid, pos=None, max_age=None, min_ovr=0, free_agents=False, limit=15):
    """Игроки на трансферном рынке: выставленные на продажу чужие + свободные агенты."""
    sql = ("SELECT p.*, c.name AS club_name FROM players p LEFT JOIN clubs c ON c.id = p.club_id "
           "WHERE p.ovr >= ? AND ")
    sql += "p.club_id = 0" if free_agents else "(p.listed = 1 AND p.club_id NOT IN (0, ?))"
    args = [min_ovr] if free_agents else [min_ovr, cid]
    if pos:
        sql += " AND p.pos = ?"
        args.append(pos)
    if max_age:
        sql += " AND p.age <= ?"
        args.append(max_age)
    sql += " ORDER BY p.ovr DESC LIMIT ?"
    return db.q(sql, (*args, limit))


def search_players(cid, pos=None, max_age=None, min_ovr=0, max_fee=None, limit=15):
    """Поиск среди всех игроков лиги (не только выставленных)."""
    sql = "SELECT p.*, c.name AS club_name FROM players p LEFT JOIN clubs c ON c.id = p.club_id " \
          "WHERE p.club_id NOT IN (0, ?) AND p.ovr >= ?"
    args = [cid, min_ovr]
    if pos:
        sql += " AND p.pos = ?"
        args.append(pos)
    if max_age:
        sql += " AND p.age <= ?"
        args.append(max_age)
    rows = db.q(sql + " ORDER BY p.ovr DESC", args)
    if max_fee:
        rows = [p for p in rows if asking_price(p) <= max_fee]
    return rows[:limit]


# ---------- Покупка: ставка → зарплата → трансфер ----------

def _transfer(pid, buyer, fee, wage):
    p = player(pid)
    db.x("UPDATE players SET club_id = ?, wage = ?, listed = 0 WHERE id = ?", (buyer, wage, pid))
    if fee:
        db.x("UPDATE clubs SET budget = budget - ? WHERE id = ?", (fee, buyer))
        if p["club_id"]:
            db.x("UPDATE clubs SET budget = budget + ? WHERE id = ?", (fee, p["club_id"]))
    db.x("UPDATE offers SET status = 'void' WHERE player_id = ? AND status = 'open'", (pid,))
    db.x("UPDATE deals SET stage = 'failed' WHERE player_id = ? AND stage = 'club_ok'", (pid,))


def make_bid(buyer, pid, fee):
    """Ставка за игрока. Клуб-ИИ отвечает сразу; клуб живого тренера получает предложение."""
    p = player(pid)
    if not p:
        return dict(ok=False, msg="Игрок не найден")
    if p["club_id"] == buyer:
        return dict(ok=False, msg="Это ваш игрок")
    if p["club_id"] == 0:
        return dict(ok=False, msg="Свободный агент — подпишите его напрямую")
    if fee > club(buyer)["budget"]:
        return dict(ok=False, msg="Недостаточно средств")
    if _count(buyer) >= MAX_SQUAD:
        return dict(ok=False, msg=f"В заявке максимум {MAX_SQUAD} игроков")
    if db.one("SELECT 1 FROM deals WHERE buyer = ? AND player_id = ? AND stage = 'club_ok'", (buyer, pid)):
        return dict(ok=False, msg="Сделка по этому игроку уже открыта")
    seller = p["club_id"]
    if _is_managed(seller):
        oid = db.x("INSERT INTO offers (seller, player_id, buyer, fee) VALUES (?,?,?,?)",
                   (seller, pid, buyer, fee))
        return dict(ok=True, pending=True, offer_id=oid, msg="Предложение отправлено тренеру клуба")
    ask = asking_price(p)
    if fee < ask * 0.85:
        return dict(ok=False, msg="Клуб отклонил предложение — слишком мало")
    if fee < ask:
        return dict(ok=False, counter=ask, msg=f"Клуб просит {money(ask)}")
    rival_fee, rival_club = 0, None
    if not p["listed"] and p["ovr"] >= 65 and random.random() < 0.25:
        rivals = db.q("SELECT id FROM clubs WHERE id NOT IN (?, ?) AND budget > ? AND id NOT IN "
                      "(SELECT club_id FROM managers WHERE club_id IS NOT NULL AND sacked = 0)",
                      (buyer, seller, fee * 1.25))
        if rivals:
            rival_club = random.choice(rivals)["id"]
            rival_fee = max(fee + 50, int(fee * random.uniform(1.05, 1.2) / 50) * 50)
    did = db.x("INSERT INTO deals (buyer, seller, player_id, fee, stage, rival_fee, rival_club) "
               "VALUES (?,?,?,?,'club_ok',?,?)", (buyer, seller, pid, fee, rival_fee, rival_club))
    msg = f"Клуб согласен на {money(fee)}. Договоритесь с игроком о зарплате"
    if rival_fee:
        msg += f". ⚠ Конкурент ({club(rival_club)['name']}) готов заплатить {money(rival_fee)}"
    return dict(ok=True, deal_id=did, rival_fee=rival_fee, demand=E.wage_demand(p), msg=msg)


def raise_bid(deal_id, fee):
    d = db.one("SELECT * FROM deals WHERE id = ? AND stage = 'club_ok'", (deal_id,))
    if not d:
        return dict(ok=False, msg="Сделка не найдена или закрыта")
    if fee <= d["fee"]:
        return dict(ok=False, msg="Новая ставка должна быть выше текущей")
    if fee > club(d["buyer"])["budget"]:
        return dict(ok=False, msg="Недостаточно средств")
    rival = d["rival_fee"] if fee < d["rival_fee"] else 0
    db.x("UPDATE deals SET fee = ?, rival_fee = ? WHERE id = ?", (fee, rival, deal_id))
    if rival:
        return dict(ok=False, msg=f"Конкурент всё ещё впереди ({money(rival)})")
    return dict(ok=True, msg="Вы перебили конкурента" if d["rival_fee"] else "Ставка повышена")


def agree_wage(deal_id, wage):
    """Переговоры с игроком. Успех = немедленное завершение трансфера."""
    d = db.one("SELECT * FROM deals WHERE id = ? AND stage = 'club_ok'", (deal_id,))
    if not d:
        return dict(ok=False, msg="Сделка не найдена или закрыта")
    p = player(d["player_id"])
    if p["club_id"] != d["seller"]:
        db.x("UPDATE deals SET stage = 'failed' WHERE id = ?", (deal_id,))
        return dict(ok=False, msg="Игрок уже сменил клуб")
    if d["rival_fee"] > d["fee"]:
        return dict(ok=False, msg=f"Конкурент предложил {money(d['rival_fee'])} — повысьте ставку")
    if d["fee"] > club(d["buyer"])["budget"]:
        return dict(ok=False, msg="Недостаточно средств")
    demand = E.wage_demand(p)
    if wage >= demand * 0.95:
        with db.tx():
            _transfer(p["id"], d["buyer"], d["fee"], wage)
            db.x("UPDATE deals SET stage = 'done', wage = ? WHERE id = ?", (wage, deal_id))
        return dict(ok=True, msg=f"{p['name']} перешёл в клуб за {money(d['fee'])}, зарплата €{wage}K/нед")
    if wage >= demand * 0.8:
        return dict(ok=False, counter=demand, msg=f"Игрок хочет €{demand}K в неделю")
    db.x("UPDATE deals SET stage = 'failed' WHERE id = ?", (deal_id,))
    return dict(ok=False, failed=True, msg="Игрок отказался вести переговоры")


def sign_free_agent(cid, pid, wage):
    p = player(pid)
    if not p or p["club_id"] != 0:
        return dict(ok=False, msg="Игрок не свободен")
    if _count(cid) >= MAX_SQUAD:
        return dict(ok=False, msg=f"В заявке максимум {MAX_SQUAD} игроков")
    demand = E.wage_demand(p)
    if wage >= demand * 0.95:
        with db.tx():
            _transfer(pid, cid, 0, wage)
        return dict(ok=True, msg=f"{p['name']} подписан как свободный агент")
    if wage >= demand * 0.8:
        return dict(ok=False, counter=demand, msg=f"Игрок хочет €{demand}K в неделю")
    return dict(ok=False, msg="Игрок отказался")


# ---------- Продажа, предложения, увольнение игроков ----------

def list_player(cid, pid, listed=True):
    p = player(pid)
    if not p or p["club_id"] != cid:
        return False, "Это не ваш игрок"
    db.x("UPDATE players SET listed = ? WHERE id = ?", (1 if listed else 0, pid))
    return True, f"{p['name']} {'выставлен на трансфер' if listed else 'снят с трансфера'}"


def my_offers(cid):
    return db.q("SELECT o.*, p.name pname, p.ovr, p.pos, c.name bname FROM offers o "
                "JOIN players p ON p.id = o.player_id JOIN clubs c ON c.id = o.buyer "
                "WHERE o.seller = ? AND o.status = 'open' ORDER BY o.fee DESC", (cid,))


def accept_offer(offer_id, cid):
    o = db.one("SELECT * FROM offers WHERE id = ? AND seller = ? AND status = 'open'", (offer_id, cid))
    if not o:
        return False, "Предложение недоступно"
    p = player(o["player_id"])
    if not p or p["club_id"] != cid:
        db.x("UPDATE offers SET status = 'void' WHERE id = ?", (offer_id,))
        return False, "Игрока уже нет в клубе"
    others = db.one("SELECT COUNT(*) n FROM players WHERE club_id = ? AND pos = ?", (cid, p["pos"]))["n"]
    if others <= 1 or _count(cid) <= 16:
        return False, "Нельзя продавать: в составе не хватит игроков"
    buyer = club(o["buyer"])
    if buyer["budget"] < o["fee"]:
        db.x("UPDATE offers SET status = 'void' WHERE id = ?", (offer_id,))
        return False, "У покупателя уже нет таких денег"
    with db.tx():
        if _is_managed(o["buyer"]):
            db.x("INSERT INTO deals (buyer, seller, player_id, fee, stage) VALUES (?,?,?,?,'club_ok')",
                 (o["buyer"], cid, p["id"], o["fee"]))
            db.x("UPDATE offers SET status = 'accepted' WHERE id = ?", (offer_id,))
            return True, "Клуб-покупатель теперь договаривается с игроком"
        _transfer(p["id"], o["buyer"], o["fee"], E.wage_demand(p))
        db.x("UPDATE offers SET status = 'accepted' WHERE id = ?", (offer_id,))
    return True, f"{p['name']} продан в «{buyer['name']}» за {money(o['fee'])}"


def reject_offer(offer_id, cid):
    db.x("UPDATE offers SET status = 'rejected' WHERE id = ? AND seller = ? AND status = 'open'",
         (offer_id, cid))
    return True, "Предложение отклонено"


def counter_offer(offer_id, cid, fee):
    """Запросить больше: ИИ-клуб соглашается, если цена не выше 125% оценки."""
    o = db.one("SELECT * FROM offers WHERE id = ? AND seller = ? AND status = 'open'", (offer_id, cid))
    if not o:
        return False, "Предложение недоступно"
    p = player(o["player_id"])
    if fee <= o["fee"]:
        return True, "Текущая цена уже не ниже"
    if fee > E.player_value(p) * 1.25 or fee > club(o["buyer"])["budget"]:
        return False, "Покупатель не готов платить столько"
    db.x("UPDATE offers SET fee = ? WHERE id = ?", (fee, offer_id))
    return True, f"Покупатель согласен на {money(fee)} — можно принимать"


def release_player(cid, pid):
    """Расторжение контракта: компенсация 8 недельных зарплат."""
    p = player(pid)
    if not p or p["club_id"] != cid:
        return False, "Это не ваш игрок"
    n_pos = db.one("SELECT COUNT(*) n FROM players WHERE club_id = ? AND pos = ?", (cid, p["pos"]))["n"]
    if _count(cid) <= 16 or n_pos <= (2 if p["pos"] == "GK" else 3):
        return False, "В составе не хватит игроков"
    pay = p["wage"] * 8
    if club(cid)["budget"] < pay:
        return False, f"Нужна компенсация {money(pay)}"
    with db.tx():
        db.x("UPDATE clubs SET budget = budget - ? WHERE id = ?", (pay, cid))
        db.x("UPDATE players SET club_id = 0, listed = 0 WHERE id = ?", (pid,))
    return True, f"{p['name']} уволен (компенсация {money(pay)})"


# ---------- Обзоры ----------

def squad(cid, order="ovr"):
    col = {"ovr": "ovr DESC", "age": "age", "form": "form DESC", "pos": "pos, ovr DESC",
           "goals": "goals DESC"}.get(order, "ovr DESC")
    return db.q(f"SELECT * FROM players WHERE club_id = ? ORDER BY {col}", (cid,))


def finance_report(cid):
    c = club(cid)
    wages = db.one("SELECT COALESCE(SUM(wage), 0) w FROM players WHERE club_id = ?", (cid,))["w"]
    income = _income(c["rep"])
    return dict(budget=c["budget"], wages=wages, income=income, home_bonus=int(income * 0.3),
                net_week=income - wages)


def club_overview(cid):
    c, sq = club(cid), club_players(cid)
    nf = next_fixture(cid)
    return dict(club=c, position=position(cid), season=season(), md=matchday(), total=total_mds(),
                avg_ovr=round(sum(p["ovr"] for p in sq) / max(1, len(sq)), 1),
                injured=[p for p in sq if p["injury"] > 0], next=nf, finance=finance_report(cid),
                trained=c["trained_md"] == matchday())


# ---------- Игровой тур ----------

def _apply_match(r, pl):
    goals, assists = {}, {}
    for e in r["events"]:
        goals[e["scorer"]] = goals.get(e["scorer"], 0) + 1
        if e["assist"]:
            assists[e["assist"]] = assists.get(e["assist"], 0) + 1
    for pid, rating in r["ratings"].items():
        form = clamp(0.7 * pl[pid]["form"] + 0.3 * rating, 4.0, 9.5)
        db.x("UPDATE players SET apps = apps + 1, rating_sum = rating_sum + ?, goals = goals + ?, "
             "assists = assists + ?, form = ? WHERE id = ?",
             (rating, goals.get(pid, 0), assists.get(pid, 0), form, pid))


def _after_result(cid, my_rep, opp_rep, gf, ga):
    k = clamp((opp_rep - my_rep) / 15, -2, 2)
    if gf > ga:
        delta = 2 + k
    elif gf == ga:
        delta = k * 0.5
    else:
        delta = -3 + k * 0.5
    _board_update(cid, delta)


def play_matchday():
    """Сыграть текущий тур для всей лиги. Возвращает results, injuries, sacked, season_end."""
    with db.tx():
        s, md = season(), matchday()
        fixtures = db.q("SELECT * FROM fixtures WHERE season = ? AND md = ? AND played = 0", (s, md))
        clubs = {c["id"]: c for c in db.q("SELECT * FROM clubs")}
        managed = {m["club_id"]: m["user_id"] for m in db.q(
            "SELECT * FROM managers WHERE sacked = 0 AND club_id IS NOT NULL")}
        db.x("UPDATE players SET form = form + (6.5 - form) * 0.1 WHERE club_id > 0")
        results, new_inj = [], {}
        for f in fixtures:
            h, a = clubs[f["home"]], clubs[f["away"]]
            hp, ap = club_players(h["id"]), club_players(a["id"])
            pl = {p["id"]: p for p in hp + ap}
            r = E.simulate_match(hp, ap, h["formation"], h["mentality"], a["formation"], a["mentality"])
            db.x("UPDATE fixtures SET hg = ?, ag = ?, played = 1 WHERE id = ?", (r["hg"], r["ag"], f["id"]))
            _apply_match(r, pl)
            for pid, games, name in r["injuries"]:
                if games > new_inj.get(pid, (0, ""))[0]:
                    new_inj[pid] = (games, name)
            for cid, my, opp, gf, ga in ((h["id"], h, a, r["hg"], r["ag"]), (a["id"], a, h, r["ag"], r["hg"])):
                if cid in managed:
                    _after_result(cid, my["rep"], opp["rep"], gf, ga)
            results.append(dict(
                fixture=f["id"], home_id=h["id"], away_id=a["id"], home=h["name"], away=a["name"],
                hg=r["hg"], ag=r["ag"],
                events=sorted([dict(min=e["min"], side=e["side"], scorer=pl[e["scorer"]]["name"],
                                    assist=pl[e["assist"]]["name"] if e["assist"] else None)
                               for e in r["events"]], key=lambda e: e["min"]),
                best=max(r["ratings"], key=r["ratings"].get) and dict(
                    name=pl[max(r["ratings"], key=r["ratings"].get)]["name"],
                    rating=max(r["ratings"].values()))))
        db.x("UPDATE players SET injury = injury - 1 WHERE injury > 0")
        injuries = []
        for pid, (games, name) in new_inj.items():
            db.x("UPDATE players SET injury = ?, inj_name = ? WHERE id = ?", (games, name, pid))
            p = player(pid)
            injuries.append(dict(player_id=pid, name=p["name"], club_id=p["club_id"], games=games, reason=name))
        _weekly_finances(clubs, {f["home"] for f in fixtures}, managed)
        sacked = _check_sack(managed, md)
        season_end = None
        if md >= total_mds():
            season_end = _end_season()
        else:
            db.set_meta("md", md + 1)
            _generate_offers()
            _ai_trade()
            _ai_squad_upkeep()
    return dict(season=s, md=md, results=results, injuries=injuries, sacked=sacked, season_end=season_end)


def _weekly_finances(clubs, home_ids, managed):
    wages = {r["club_id"]: r["w"] for r in db.q(
        "SELECT club_id, SUM(wage) w FROM players WHERE club_id > 0 GROUP BY club_id")}
    for cid, c in clubs.items():
        inc = _income(c["rep"])
        if cid in home_ids:
            inc += int(inc * 0.3)
        db.x("UPDATE clubs SET budget = budget + ? WHERE id = ?", (inc - wages.get(cid, 0), cid))
    for cid in managed:
        if club(cid)["budget"] < 0:
            _board_update(cid, -1)


def _check_sack(managed, md):
    out = []
    if md < 8:
        return out
    for cid, uid in managed.items():
        if club(cid)["board_conf"] <= 10:
            out.append(dict(user_id=uid, club=club(cid)["name"], reason="доверие совета директоров упало"))
            _sack(uid)
    return out


# ---------- Рынок ИИ ----------

def _generate_offers():
    """Каждый тур ИИ-клубы шлют предложения за игроков живых тренеров (действуют один тур)."""
    db.x("UPDATE offers SET status = 'expired' WHERE status = 'open' AND buyer NOT IN "
         "(SELECT club_id FROM managers WHERE club_id IS NOT NULL AND sacked = 0)")
    ai = [c for c in db.q("SELECT * FROM clubs") if not _is_managed(c["id"])]
    for m in db.q("SELECT club_id FROM managers WHERE sacked = 0 AND club_id IS NOT NULL"):
        cid, n = m["club_id"], 0
        for p in club_players(cid):
            if n >= 4:
                break
            prob = 0.35 if p["listed"] else (0.03 if p["ovr"] >= 60 else 0)
            if random.random() >= prob:
                continue
            fee = max(50, int(E.player_value(p) * random.uniform(0.85, 1.2) / 50) * 50)
            cands = [c for c in ai if c["budget"] >= fee and _count(c["id"]) < MAX_SQUAD]
            if not cands:
                continue
            b = random.choice(cands)
            if db.one("SELECT 1 FROM offers WHERE player_id = ? AND buyer = ? AND status = 'open'",
                      (p["id"], b["id"])):
                continue
            db.x("INSERT INTO offers (seller, player_id, buyer, fee) VALUES (?,?,?,?)",
                 (cid, p["id"], b["id"], fee))
            n += 1


def _ai_trade():
    """Более осмысленный ИИ-рынок: сделки по потребностям, возрасту и бюджету.

    Внутренние суммы движка — тысячи евро: бюджет 100000 означает €100 млн.
    Сделка не проводится, если продавец потеряет минимальное покрытие позиции,
    покупатель переплатит относительно бюджета или зарплата станет чрезмерной.
    """
    ai = [c for c in db.q("SELECT * FROM clubs") if not _is_managed(c["id"])]
    if len(ai) < 2:
        return
    # Несколько независимых попыток за тур, но не массовый трансферный хаос.
    for _ in range(min(4, max(1, len(ai) // 5))):
        if random.random() > 0.55:
            continue
        buyer, seller = random.sample(ai, 2)
        buyer_squad, seller_squad = club_players(buyer["id"]), club_players(seller["id"])
        if len(buyer_squad) >= MAX_SQUAD or len(seller_squad) <= MIN_SQUAD:
            continue
        needs = []
        for pos, min_need in MIN_POS.items():
            own = [p for p in buyer_squad if p["pos"] == pos]
            if len(own) < min_need + 1:
                needs.append((pos, min_need + 1 - len(own)))
        # Если состав укомплектован, усиливаем только слабую позицию.
        if not needs:
            for pos in E.POSITIONS:
                own = sorted([p for p in buyer_squad if p["pos"] == pos], key=lambda p: -p["ovr"])
                if len(own) >= E.SQUAD_STARTERS[pos] and own[E.SQUAD_STARTERS[pos]-1]["ovr"] < buyer["rep"] + 4:
                    needs.append((pos, 1))
        if not needs:
            continue
        pos = random.choice(needs)[0]
        sellers = [p for p in seller_squad if p["pos"] == pos and
                   sum(1 for x in seller_squad if x["pos"] == pos) > MIN_POS[pos]]
        buyers_at_pos = sorted([p for p in buyer_squad if p["pos"] == pos], key=lambda p: -p["ovr"])
        if not sellers:
            continue
        # Не продаём ключевого игрока без премии; чаще выбираем резервиста или молодого.
        sellers.sort(key=lambda p: (p["ovr"] >= seller["rep"] + 8, p["age"] > 30, p["ovr"]))
        candidates = []
        for pl in sellers:
            if buyers_at_pos and pl["ovr"] <= buyers_at_pos[-1]["ovr"] + 1:
                continue
            if pl["age"] >= 31 and pl["ovr"] < buyer["rep"] - 5:
                continue
            price = asking_price(pl)
            # Реалистичная скидка/надбавка зависит от возраста и потенциала.
            age_factor = 1.18 if pl["age"] <= 23 and pl["pot"] >= pl["ovr"] + 8 else (0.78 if pl["age"] >= 30 else 1.0)
            fee = max(100, int(price * age_factor * random.uniform(0.88, 1.08) / 50) * 50)
            wage = E.wage_demand(pl)
            if fee <= buyer["budget"] * 0.30 and wage <= max(100, int(_income(buyer["rep"]) * 0.22)):
                candidates.append((pl, fee, wage))
        if not candidates:
            continue
        pl, fee, wage = max(candidates, key=lambda item: (item[0]["ovr"] + max(0, item[0]["pot"]-item[0]["ovr"])*0.15 - item[0]["age"]*0.15))
        _transfer(pl["id"], buyer["id"], fee, wage)

def _ai_squad_upkeep():
    """ИИ-клубы добирают недостающие позиции (свободные агенты или молодёжь) и сбрасывают лишних."""
    for c in db.q("SELECT id, rep FROM clubs"):
        cid = c["id"]
        if _is_managed(cid):
            continue
        extra = _count(cid) - MAX_SQUAD
        if extra > 0:
            db.x("UPDATE players SET club_id = 0, listed = 0 WHERE id IN "
                 "(SELECT id FROM players WHERE club_id = ? ORDER BY ovr ASC LIMIT ?)", (cid, extra))
        pl = club_players(cid)
        for pos, need in MIN_POS.items():
            for _ in range(need - sum(1 for p in pl if p["pos"] == pos)):
                fa = db.one("SELECT * FROM players WHERE club_id = 0 AND pos = ? ORDER BY ovr DESC LIMIT 1", (pos,))
                if fa:
                    db.x("UPDATE players SET club_id = ?, wage = ? WHERE id = ?",
                         (cid, E.base_wage(fa["ovr"]), fa["id"]))
                else:
                    _insert_player(cid, E.gen_player(pos, club_strength(c["rep"]) - 8))


# ---------- Конец сезона ----------

def _end_season():
    """Итоги сезона: чемпион, призовые, совет директоров, развитие, пенсия, академия, новый календарь."""
    s, tb = season(), table()
    champ = tb[0]
    top = db.one("SELECT p.name, p.goals FROM players p WHERE p.club_id > 0 "
                 "ORDER BY p.goals DESC, p.assists DESC LIMIT 1")
    db.x("INSERT OR REPLACE INTO history (season, champion, top_scorer) VALUES (?,?,?)",
         (s, champ["name"], f"{top['name']} ({top['goals']})" if top else "—"))
    db.x("UPDATE clubs SET titles = titles + 1 WHERE id = ?", (champ["id"],))
    n = len(tb)
    managed = {m["club_id"]: m for m in db.q(
        "SELECT * FROM managers WHERE sacked = 0 AND club_id IS NOT NULL")}
    reviews = []
    for i, r in enumerate(tb, 1):
        prize = (n + 1 - i) * 120 + (3000 if i == 1 else 0)
        rep_d = 2 if i == 1 else (1 if i <= 3 else (-1 if i > n - 3 else 0))
        c = club(r["id"])
        db.x("UPDATE clubs SET budget = budget + ?, rep = ? WHERE id = ?",
             (prize, int(clamp(c["rep"] + rep_d, 45, 98)), r["id"]))
        if r["id"] in managed:
            delta = (c["objective"] - i) * 3 + (10 if i == 1 else 0)
            _board_update(r["id"], delta)
            conf = club(r["id"])["board_conf"]
            rv = dict(user_id=managed[r["id"]]["user_id"], club=r["name"], position=i,
                      objective=c["objective"], prize=prize, board_conf=conf, sacked=False)
            if conf <= 20:
                rv["sacked"] = True
                _sack(managed[r["id"]]["user_id"])
            reviews.append(rv)
    retired, grown = _develop_players()
    youth = _youth_intake()
    for _ in range(12):
        _insert_player(0, E.gen_player(random.choice(E.POSITIONS), 58))
    db.x("UPDATE players SET goals = 0, assists = 0, apps = 0, rating_sum = 0, form = 6.5, "
         "injury = 0, inj_name = NULL, listed = CASE WHEN club_id = 0 THEN 0 ELSE listed END")
    db.x("UPDATE offers SET status = 'expired' WHERE status = 'open'")
    db.x("UPDATE deals SET stage = 'failed' WHERE stage = 'club_ok'")
    db.x("UPDATE clubs SET trained_md = -1")
    for c in db.q("SELECT id FROM clubs"):
        if not _is_managed(c["id"]):
            db.x("UPDATE clubs SET formation = ?, mentality = ? WHERE id = ?",
                 (random.choice(list(E.FORMATIONS)), random.choice(["attack", "balanced", "balanced", "defend"]),
                  c["id"]))
    _ai_squad_upkeep()
    _set_objectives()
    db.set_meta("season", s + 1)
    db.set_meta("md", 1)
    _make_fixtures(s + 1)
    return dict(season=s, champion=champ["name"], table=tb, top_scorer=top["name"] if top else None,
                reviews=reviews, retired=retired, youth=youth, grown=grown)


def _develop_players():
    """Ежегодное развитие, старение, ренегоциация зарплат, завершение карьер."""
    retired, grown = [], []
    managed_clubs = {m["club_id"] for m in db.q(
        "SELECT club_id FROM managers WHERE sacked = 0 AND club_id IS NOT NULL")}
    for p in db.q("SELECT * FROM players"):
        if p["age"] >= 34 and random.random() < (p["age"] - 33) * 0.25:
            if p["club_id"] in managed_clubs:
                retired.append(dict(name=p["name"], club_id=p["club_id"], age=p["age"], ovr=p["ovr"]))
            db.x("DELETE FROM players WHERE id = ?", (p["id"],))
            db.x("DELETE FROM scouted WHERE player_id = ?", (p["id"],))
            continue
        new = E.progress(p["ovr"], p["pot"], p["age"], p["profile"])
        age = p["age"] + 1
        pot = new if age >= 29 else max(new, p["pot"])
        db.x("UPDATE players SET ovr = ?, pot = ?, age = ?, wage = ? WHERE id = ?",
             (new, pot, age, E.base_wage(new) if p["club_id"] else p["wage"], p["id"]))
        if p["club_id"] in managed_clubs and new - p["ovr"] >= 3:
            grown.append(dict(name=p["name"], club_id=p["club_id"], old=p["ovr"], new=new))
    return retired, grown


def _youth_intake():
    """Академия: каждый клуб получает 2 молодых игрока (если в заявке есть место)."""
    out = []
    for c in db.q("SELECT id FROM clubs"):
        for _ in range(2):
            if _count(c["id"]) >= MAX_SQUAD and not _is_managed(c["id"]):
                break
            pos = random.choices(E.POSITIONS, weights=[1, 3, 3, 2])[0]
            p = E.gen_player(pos, 50, youth=True)
            p["wage"] = max(2, p["wage"] // 2)
            pid = _insert_player(c["id"], p)
            if _is_managed(c["id"]):
                out.append(dict(player_id=pid, club_id=c["id"], name=p["name"], pos=pos,
                                age=p["age"], ovr=p["ovr"]))
    return out


def history():
    return db.q("SELECT * FROM history ORDER BY season DESC")
