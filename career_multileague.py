"""
Standalone multi-league backend for the Telegram football-manager bot.
Supports: 7 league tables/calendars, multiple Telegram managers with one unique club each,
automatic fixtures/results, season calendar, and importing real FC 27 roster/rating CSV data.

This module intentionally uses its own SQLite database (fm_multileague.sqlite3) so it does not
silently reset or corrupt the existing career.py database. Integrate its handlers into your
main bot after testing. Club lists currently represent the v2 catalog season and MUST be
verified/updated for 2026/27 before launching a live season.
"""
from __future__ import annotations
import csv, random, sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).with_name("fm_multileague.sqlite3")
START_BUDGET_EUR = 100_000_000
LEAGUES = {
"England · Premier League":["Arsenal","Aston Villa","Bournemouth","Brentford","Brighton","Burnley","Chelsea","Crystal Palace","Everton","Fulham","Leeds United","Liverpool","Manchester City","Manchester United","Newcastle United","Nottingham Forest","Sunderland","Tottenham Hotspur","West Ham United","Wolverhampton Wanderers"],
"Spain · La Liga":["Athletic Club","Atlético Madrid","Barcelona","Celta Vigo","Elche","Espanyol","Getafe","Girona","Levante","Mallorca","Osasuna","Rayo Vallecano","Real Betis","Real Madrid","Real Oviedo","Real Sociedad","Sevilla","Valencia","Villarreal","Alavés"],
"Italy · Serie A":["Atalanta","Bologna","Cagliari","Como","Cremonese","Fiorentina","Genoa","Inter","Juventus","Lazio","Lecce","Milan","Napoli","Parma","Pisa","Roma","Sassuolo","Torino","Udinese","Hellas Verona"],
"Germany · Bundesliga":["Augsburg","Bayer Leverkusen","Bayern Munich","Borussia Dortmund","Borussia Mönchengladbach","Eintracht Frankfurt","FC Heidenheim","Hamburger SV","Hoffenheim","Mainz 05","RB Leipzig","SC Freiburg","St. Pauli","Union Berlin","VfB Stuttgart","Werder Bremen","Wolfsburg","1. FC Köln"],
"France · Ligue 1":["Angers","Auxerre","Brest","Le Havre","Lens","Lille","Lorient","Lyon","Marseille","Metz","Monaco","Nantes","Nice","Paris FC","Paris Saint-Germain","Rennes","Strasbourg","Toulouse"],
"Netherlands · Eredivisie":["Ajax","AZ Alkmaar","Excelsior","Feyenoord","Fortuna Sittard","Go Ahead Eagles","Groningen","Heerenveen","Heracles Almelo","NAC Breda","NEC Nijmegen","PEC Zwolle","PSV Eindhoven","Sparta Rotterdam","Telstar","Twente","Utrecht","Volendam"],
"Portugal · Primeira Liga":["Alverca","Arouca","AVS","Benfica","Braga","Casa Pia","Estoril","Estrela Amadora","Famalicão","Gil Vicente","Moreirense","Nacional","Porto","Rio Ave","Santa Clara","Sporting CP","Tondela","Vitória SC"]}


# Stable fictional English-style player names used when no real roster CSV is supplied.
_FIRST_NAMES = [
    "Oliver", "Jack", "Harry", "George", "Charlie", "Thomas", "Jacob", "Oscar", "William", "James",
    "Leo", "Alfie", "Noah", "Archie", "Henry", "Freddie", "Ethan", "Mason", "Logan", "Lucas",
    "Alexander", "Daniel", "Samuel", "Benjamin", "Max", "Ryan", "Callum", "Finley", "Liam", "Nathan",
    "Adam", "Jamie", "Reece", "Jude", "Theo", "Harvey", "Dylan", "Aaron", "Kai", "Cameron",
    "Elliot", "Rory", "Tyler", "Connor", "Jordan", "Aiden", "Lewis", "Myles", "Blake", "Jenson"
]
_LAST_NAMES = [
    "Smith", "Jones", "Taylor", "Brown", "Wilson", "Davies", "Evans", "Thomas", "Roberts", "Johnson",
    "Walker", "Wright", "Robinson", "Thompson", "White", "Hughes", "Edwards", "Green", "Hall", "Lewis",
    "Harris", "Clarke", "Patel", "Jackson", "Wood", "Turner", "Martin", "Cooper", "Hill", "Ward",
    "Morris", "Moore", "Clark", "Lee", "King", "Baker", "Harrison", "Morgan", "Allen", "James",
    "Scott", "Phillips", "Watson", "Parker", "Bennett", "Carter", "Mitchell", "Bailey", "Foster", "Gray",
    "Reed", "Kelly", "Price", "Bell", "Cook", "Murphy", "Bailey", "Richardson", "Cox", "Howard",
    "Brooks", "Bishop", "Fletcher", "Webb", "Chapman", "Mills", "Porter", "Hunt", "Shaw", "Marshall",
    "Armstrong", "Spencer", "West", "Palmer", "Holmes", "Pearson", "Ellis", "Fisher", "Barnes", "Knight",
    "Dixon", "Harper", "Wells", "Stephens", "Atkinson", "Lawrence", "Barrett", "Holland", "Sullivan", "Barker"
]
_POSITION_POOL = [
    ("GK", 2), ("CB", 4), ("LB", 2), ("RB", 2), ("CDM", 2), ("CM", 4),
    ("CAM", 2), ("LM", 1), ("RM", 1), ("LW", 1), ("RW", 1), ("ST", 3)
]

def seed_generated_squads(players_per_club=23):
    """Create demo squads only when no Transfermarkt roster CSV is installed.

    If transfermarkt_players.csv exists, real imported rosters are preferred and
    missing clubs are left empty rather than silently filled with fictional players.
    """
    if Path(__file__).with_name("transfermarkt_players.csv").exists():
        return 0
    rng = random.Random(27062026)
    with connect() as c:
        clubs_rows = [dict(r) for r in c.execute("SELECT id,name FROM clubs ORDER BY id")]
        total = 0
        for club in clubs_rows:
            if c.execute("SELECT 1 FROM players WHERE club_id=? LIMIT 1", (club["id"],)).fetchone():
                continue
            # Use a club-specific RNG so restarting the bot never changes a generated roster.
            crng = random.Random(100000 + int(club["id"]) * 97)
            names = []
            while len(names) < players_per_club:
                full = f"{crng.choice(_FIRST_NAMES)} {crng.choice(_LAST_NAMES)}"
                if full not in names:
                    names.append(full)
            positions = [p for p, count in _POSITION_POOL for _ in range(count)]
            crng.shuffle(positions)
            for i, name in enumerate(names):
                pos = positions[i] if i < len(positions) else crng.choice(["CB", "CM", "ST"])
                age = crng.randint(17, 34)
                overall = crng.randint(58, 82)
                if age <= 22:
                    potential = min(99, overall + crng.randint(3, 16))
                else:
                    potential = min(99, overall + crng.randint(0, 7))
                wage = max(1500, overall * overall * 35)
                market_value = max(100000, overall ** 3 * 180)
                c.execute(
                    "INSERT OR IGNORE INTO players(club_id,name,position,age,overall,potential,wage,market_value,source) VALUES(?,?,?,?,?,?,?,?,?)",
                    (club["id"], name, pos, age, overall, potential, wage, market_value, "Generated English-style roster")
                )
                total += 1
        return total

def connect():
    con=sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con
def install():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS leagues(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, season TEXT NOT NULL DEFAULT '2026/27');
        CREATE TABLE IF NOT EXISTS clubs(id INTEGER PRIMARY KEY, league_id INTEGER NOT NULL REFERENCES leagues(id), name TEXT NOT NULL, budget INTEGER NOT NULL DEFAULT 100000000, UNIQUE(league_id,name));
        CREATE TABLE IF NOT EXISTS managers(user_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, club_id INTEGER UNIQUE REFERENCES clubs(id), joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, club_id INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE, name TEXT NOT NULL, position TEXT, age INTEGER, overall INTEGER NOT NULL, potential INTEGER, wage INTEGER DEFAULT 0, market_value INTEGER DEFAULT 0, source TEXT DEFAULT 'FC 27 CSV', UNIQUE(club_id,name));
        CREATE TABLE IF NOT EXISTS fixtures(id INTEGER PRIMARY KEY, league_id INTEGER NOT NULL REFERENCES leagues(id), season TEXT NOT NULL, round_no INTEGER NOT NULL, match_date TEXT, home_id INTEGER NOT NULL REFERENCES clubs(id), away_id INTEGER NOT NULL REFERENCES clubs(id), home_goals INTEGER, away_goals INTEGER, played INTEGER NOT NULL DEFAULT 0, UNIQUE(league_id,season,round_no,home_id,away_id));
        CREATE TABLE IF NOT EXISTS calendar(id INTEGER PRIMARY KEY, season TEXT NOT NULL, event_date TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, UNIQUE(season,event_date,category,title));
        CREATE TABLE IF NOT EXISTS coaches(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL,
            skill INTEGER NOT NULL CHECK(skill BETWEEN 1 AND 5),
            specialty TEXT NOT NULL DEFAULT 'balanced', description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS club_coaches(
            club_id INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
            coach_id INTEGER NOT NULL REFERENCES coaches(id),
            hired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(club_id,coach_id)
        );
        CREATE TABLE IF NOT EXISTS training_plans(
            id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, focus TEXT NOT NULL,
            base_gain REAL NOT NULL, fatigue INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS training_log(
            id INTEGER PRIMARY KEY, club_id INTEGER NOT NULL REFERENCES clubs(id),
            player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
            plan_id INTEGER NOT NULL REFERENCES training_plans(id),
            trained_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            rating_before INTEGER NOT NULL, rating_after INTEGER NOT NULL, progress REAL NOT NULL DEFAULT 0
        );
        """)
        coach_catalog = [
            ("Молодой специалист",500000,1,"development","Бюджетная прокачка"),
            ("Тренер академии",2000000,2,"development","Сильнее развивает молодых"),
            ("Специалист по позициям",5000000,3,"position","Улучшает профильные навыки"),
            ("Тренер первой команды",12000000,4,"balanced","Быстрый рост основной команды"),
            ("Элитный тренер",25000000,5,"elite","Максимальная скорость развития"),
        ]
        for name,price,skill,specialty,desc in coach_catalog:
            c.execute("INSERT OR IGNORE INTO coaches(name,price,skill,specialty,description) VALUES(?,?,?,?,?)",(name,price,skill,specialty,desc))
        plans = [
            ("Техника","technical",1.0,1),("Физическая подготовка","physical",0.9,2),
            ("Тактика","tactical",0.85,1),("Удары и завершение","finishing",0.95,1),
            ("Оборона","defending",0.95,1),("Вратарская подготовка","goalkeeping",0.95,1),
            ("Комплексная","balanced",0.8,1),("Развитие молодёжи","youth",1.1,1)
        ]
        for name,focus,gain,fatigue in plans:
            c.execute("INSERT OR IGNORE INTO training_plans(name,focus,base_gain,fatigue) VALUES(?,?,?,?)",(name,focus,gain,fatigue))
        for league, teams in LEAGUES.items():
            c.execute("INSERT OR IGNORE INTO leagues(name) VALUES(?)",(league,))
            lid=c.execute("SELECT id FROM leagues WHERE name=?",(league,)).fetchone()["id"]
            for name in teams: c.execute("INSERT OR IGNORE INTO clubs(league_id,name) VALUES(?,?)",(lid,name))
def league_list():
    with connect() as c: return [dict(r) for r in c.execute("SELECT l.id,l.name,l.season,COUNT(cl.id) club_count FROM leagues l LEFT JOIN clubs cl ON cl.league_id=l.id GROUP BY l.id ORDER BY l.name")]
def clubs(league_id=None, free_only=False):
    q="SELECT cl.*,l.name league FROM clubs cl JOIN leagues l ON l.id=cl.league_id WHERE 1=1"
    args=[]
    if league_id is not None: q+=" AND cl.league_id=?";args.append(league_id)
    if free_only: q+=" AND cl.id NOT IN (SELECT club_id FROM managers WHERE club_id IS NOT NULL)"
    q+=" ORDER BY l.name,cl.name"
    with connect() as c:return [dict(r) for r in c.execute(q,args)]
def claim_club(user_id, display_name, club_id):
    """Atomically assign one club to one manager. A manager may own only one club."""
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        current=c.execute("SELECT club_id FROM managers WHERE user_id=?",(user_id,)).fetchone()
        if current and current["club_id"] is not None: return False,"Вы уже управляете клубом. Сначала освободите его."
        if not c.execute("SELECT 1 FROM clubs WHERE id=?",(club_id,)).fetchone(): return False,"Клуб не найден."
        if c.execute("SELECT 1 FROM managers WHERE club_id=?",(club_id,)).fetchone(): return False,"Этот клуб уже занят другим менеджером."
        c.execute("INSERT INTO managers(user_id,display_name,club_id) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name,club_id=excluded.club_id",(user_id,display_name,club_id))
        return True,"Клуб закреплён за вами."
def release_club(user_id):
    with connect() as c:
        cur=c.execute("UPDATE managers SET club_id=NULL WHERE user_id=?",(user_id,))
        return cur.rowcount>0
def my_club(user_id):
    with connect() as c:
        r=c.execute("SELECT cl.*,l.name league,m.display_name manager FROM managers m JOIN clubs cl ON cl.id=m.club_id JOIN leagues l ON l.id=cl.league_id WHERE m.user_id=?",(user_id,)).fetchone()
        return dict(r) if r else None
def generate_fixtures(league_id, season="2026/27", start_date=None):
    """Generate double round-robin calendar independently for every league."""
    start_date=date.fromisoformat(start_date) if isinstance(start_date,str) else (start_date or date(2026,8,15))
    with connect() as c:
        ids=[r["id"] for r in c.execute("SELECT id FROM clubs WHERE league_id=? ORDER BY id",(league_id,))]
        if len(ids)<2:return 0
        c.execute("DELETE FROM fixtures WHERE league_id=? AND season=?",(league_id,season))
        if len(ids)%2: ids.append(None)
        n=len(ids); rotation=ids[:]; rounds=[]
        for rnd in range(n-1):
            games=[]
            for i in range(n//2):
                a,b=rotation[i],rotation[n-1-i]
                if a is not None and b is not None:
                    if (rnd+i)%2: a,b=b,a
                    games.append((a,b))
            rounds.append(games)
            rotation=[rotation[0],rotation[-1],*rotation[1:-1]]
        for rno,games in enumerate(rounds,1):
            for home,away in games:
                c.execute("INSERT INTO fixtures(league_id,season,round_no,match_date,home_id,away_id) VALUES(?,?,?,?,?,?)",(league_id,season,rno,(start_date+timedelta(days=3*(rno-1))).isoformat(),home,away))
                c.execute("INSERT INTO fixtures(league_id,season,round_no,match_date,home_id,away_id) VALUES(?,?,?,?,?,?)",(league_id,season,rno+len(rounds),(start_date+timedelta(days=3*(rno-1+len(rounds)))).isoformat(),away,home))
        return len(rounds)*2
def _poisson_goals(lam: float) -> int:
    """Sample a football score from a Poisson distribution (Knuth algorithm)."""
    lam = max(0.08, min(3.8, float(lam)))
    limit = __import__("math").exp(-lam)
    product = 1.0
    k = 0
    while product > limit and k < 12:
        k += 1
        product *= random.random()
    return min(8, k - 1)


def _club_match_profile(conn, club_id):
    """Build a lightweight team profile from actual imported squad ratings."""
    rows = list(conn.execute(
        "SELECT overall, position FROM players WHERE club_id=? ORDER BY overall DESC",
        (club_id,)
    ))
    if not rows:
        return {"strength": 70.0, "attack": 70.0, "defence": 70.0, "depth": 0}
    ratings = [max(1, min(99, float(r["overall"] or 70))) for r in rows]
    # First-team quality matters much more than the tail of the squad.
    starters = ratings[:11]
    strength = sum(starters) / len(starters)
    positions = [(str(r["position"] or "").lower(), float(r["overall"] or 70)) for r in rows[:18]]
    def is_def(pos):
        return any(x in pos for x in ("gk", "keeper", "врат", "cb", "lb", "rb", "def", "защит", "вр", "цз", "лз", "пз"))
    def is_att(pos):
        return any(x in pos for x in ("st", "cf", "lw", "rw", "wing", "forward", "напад", "форвард", "лф", "пф", "цф"))
    defensive = [r for p, r in positions if is_def(p)]
    attacking = [r for p, r in positions if is_att(p)]
    return {
        "strength": strength,
        "attack": (sum(attacking) / len(attacking)) if attacking else strength,
        "defence": (sum(defensive) / len(defensive)) if defensive else strength,
        "depth": len(rows),
    }


def play_round(league_id, round_no, season="2026/27"):
    """Simulate a league round using squad quality, home advantage and realistic goal rates."""
    with connect() as c:
        rows = list(c.execute(
            """SELECT f.*,h.name home_name,a.name away_name
               FROM fixtures f JOIN clubs h ON h.id=f.home_id
               JOIN clubs a ON a.id=f.away_id
               WHERE f.league_id=? AND f.round_no=? AND f.season=? AND f.played=0
               ORDER BY f.id""", (league_id, round_no, season)
        ))
        results = []
        for f in rows:
            home = _club_match_profile(c, f["home_id"])
            away = _club_match_profile(c, f["away_id"])

            # Ratings alter expected goals gradually; no single rating gap guarantees a win.
            # Home advantage is modest, and weak squads remain capable of upsets.
            home_edge = 0.20
            home_xg = 1.34 + home_edge + (home["attack"] - away["defence"]) * 0.035
            away_xg = 1.12 + (away["attack"] - home["defence"]) * 0.035
            # Shallow squads are slightly more vulnerable over a season.
            if home["depth"] and home["depth"] < 16:
                home_xg *= 0.96
                away_xg *= 1.04
            if away["depth"] and away["depth"] < 16:
                away_xg *= 0.96
                home_xg *= 1.04
            hg = _poisson_goals(home_xg)
            ag = _poisson_goals(away_xg)

            # Rare match events add believable scoreline variety without scripted outcomes.
            if random.random() < 0.035:
                if random.random() < 0.5:
                    hg = max(0, hg - 1)
                else:
                    ag = max(0, ag - 1)
            c.execute(
                "UPDATE fixtures SET home_goals=?,away_goals=?,played=1 WHERE id=?",
                (hg, ag, f["id"])
            )
            results.append({
                "home": f["home_name"], "away": f["away_name"],
                "score": f"{hg}:{ag}",
                "home_xg": round(home_xg, 2), "away_xg": round(away_xg, 2),
            })
        return results

def table(league_id, season="2026/27"):
    with connect() as c:
        teams=[dict(r) for r in c.execute("SELECT id,name,budget FROM clubs WHERE league_id=? ORDER BY name",(league_id,))]
        stats={t["id"]:dict(id=t["id"],name=t["name"],p=0,w=0,d=0,l=0,gf=0,ga=0,pts=0,budget=t["budget"]) for t in teams}
        for f in c.execute("SELECT * FROM fixtures WHERE league_id=? AND season=? AND played=1",(league_id,season)):
            for cid,gf,ga in ((f["home_id"],f["home_goals"],f["away_goals"]),(f["away_id"],f["away_goals"],f["home_goals"])):
                s=stats[cid];s["p"]+=1;s["gf"]+=gf;s["ga"]+=ga
                if gf>ga:s["w"]+=1;s["pts"]+=3
                elif gf==ga:s["d"]+=1;s["pts"]+=1
                else:s["l"]+=1
        return sorted(stats.values(),key=lambda s:(-s["pts"],-(s["gf"]-s["ga"]),-s["gf"],s["name"]))
def calendar(season="2026/27"):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM calendar WHERE season=? ORDER BY event_date",(season,))]
def seed_calendar(season="2026/27", start_year=2026):
    events=[
      (f"{start_year}-06-15","transfer","Открытие летнего трансферного окна"),
      (f"{start_year}-08-15","league","Старт национальных чемпионатов"),
      (f"{start_year}-09-07","international","Международная пауза — товарищеские матчи"),
      (f"{start_year}-10-05","international","Международная пауза — товарищеские матчи"),
      (f"{start_year}-11-09","international","Международная пауза — товарищеские матчи"),
      (f"{start_year+1}-01-01","transfer","Открытие зимнего трансферного окна"),
      (f"{start_year+1}-01-31","transfer","Закрытие зимнего трансферного окна"),
      (f"{start_year+1}-03-22","international","Международная пауза — товарищеские матчи"),
      (f"{start_year+1}-05-24","league","Финиш национальных чемпионатов"),
      (f"{start_year+1}-06-01","season","Итоги сезона и развитие игроков")]
    with connect() as c:
        for d,cat,title in events:c.execute("INSERT OR IGNORE INTO calendar(season,event_date,category,title) VALUES(?,?,?,?)",(season,d,cat,title))
def import_fc27_csv(csv_path, clear_existing=False):
    """
    Import roster ratings from a CSV exported/downloaded from a database of FC 27 ratings.
    Required columns (case-insensitive aliases): player/name, club/team, league, overall/ovr.
    Optional: position/pos, age, potential/pot, wage, market_value/value.
    Does not fabricate players or ratings. Map FC team names to this module's club names
    in the CSV or provide matching club names and league names.
    """
    aliases={"name":["player","name","player name"],"club":["club","team","team name"],"league":["league","competition"],"overall":["overall","ovr","rating"],"position":["position","pos"],"age":["age"],"potential":["potential","pot"],"wage":["wage"],"market_value":["market_value","value","market value"]}
    with open(csv_path,newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f); headers={h.strip().lower():h for h in (reader.fieldnames or [])}
        def get(row,key):
            for alias in aliases[key]:
                if alias in headers:return row.get(headers[alias])
            return None
        if not all(get({h:"" for h in headers},k) is not None for k in ("name","club","league","overall")):
            raise ValueError("CSV должен содержать колонки player/name, club/team, league и overall/ovr.")
        rows=list(reader)
    imported=0; unmatched=[]
    with connect() as c:
        if clear_existing:c.execute("DELETE FROM players")
        for r in rows:
            name=(get(r,"name") or "").strip(); club=(get(r,"club") or "").strip(); league=(get(r,"league") or "").strip()
            ov=get(r,"overall")
            if not name or not club or not league or not ov:continue
            clubrow=c.execute("SELECT cl.id FROM clubs cl JOIN leagues l ON l.id=cl.league_id WHERE lower(cl.name)=lower(?) AND lower(l.name)=lower(?)",(club,league)).fetchone()
            if not clubrow:
                unmatched.append(f"{league} / {club}");continue
            try: overall=max(1,min(99,int(float(ov))))
            except ValueError:continue
            def num(k):
                try:return int(float(get(r,k) or 0))
                except (ValueError,TypeError):return 0
            c.execute("""INSERT INTO players(club_id,name,position,age,overall,potential,wage,market_value,source) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(club_id,name) DO UPDATE SET position=excluded.position,age=excluded.age,overall=excluded.overall,potential=excluded.potential,wage=excluded.wage,market_value=excluded.market_value,source=excluded.source""",
                (clubrow["id"],name,(get(r,"position") or "").strip(),num("age"),overall,num("potential"),num("wage"),num("market_value"),"FC 27 ratings CSV"))
            imported+=1
    return {"imported":imported,"unmatched":sorted(set(unmatched))}

def import_transfermarkt_csv(csv_path, clear_existing=False):
    """Import current rosters from a Transfermarkt-style players.csv export.

    Supported columns include current_club_name, name, date_of_birth, position,
    market_value_in_eur and current_club_domestic_competition_id (as used by
    public Transfermarkt datasets). Transfermarkt does not provide an OVR rating;
    when no overall/ovr column exists, this function estimates a game rating from
    market value and age and marks it as an estimate.
    """
    aliases = {
        "name": ("name", "player", "player_name"),
        "club": ("current_club_name", "club", "team", "current club"),
        "league": ("league", "competition", "current_club_domestic_competition_id"),
        "position": ("position", "sub_position", "pos"),
        "age": ("age",),
        "dob": ("date_of_birth", "date of birth", "birth_date"),
        "value": ("market_value_in_eur", "market_value", "market value", "value"),
        "overall": ("overall", "ovr", "rating"),
        "potential": ("potential", "pot"),
        "wage": ("wage",),
    }
    def norm(value):
        import re, unicodedata
        value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
        value = re.sub(r"\b(fc|cf|afc|sc|sv|club|football club)\b", " ", value)
        return " ".join(re.sub(r"[^a-z0-9 ]", " ", value).split())
    def parse_int(value, default=0):
        try:
            return int(float(str(value).replace("€", "").replace(",", "").strip() or default))
        except (TypeError, ValueError):
            return default
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = {str(h).strip().lower(): h for h in (reader.fieldnames or [])}
        def get(row, key):
            for a in aliases[key]:
                if a in fields:
                    return row.get(fields[a])
            return None
        if get({}, "name") is None or get({}, "club") is None:
            raise ValueError("Transfermarkt CSV должен содержать колонки name и current_club_name (или player и club).")
        rows = list(reader)
    imported, unmatched, skipped = 0, set(), 0
    with connect() as c:
        club_rows = list(c.execute("SELECT cl.id,cl.name,l.name league FROM clubs cl JOIN leagues l ON l.id=cl.league_id"))
        by_norm = {norm(r["name"]): r for r in club_rows}
        # Common Transfermarkt spellings vs short in-game club names.
        aliases_clubs = {"athletic bilbao":"athletic club", "atletico madrid":"atletico madrid", "manchester city":"manchester city", "manchester united":"manchester united", "paris saint germain":"paris saint germain", "tottenham hotspur":"tottenham hotspur", "bayern munchen":"bayern munich", "borussia monchengladbach":"borussia monchengladbach", "inter milan":"inter", "ac milan":"milan", "as roma":"roma", "sporting clube de portugal":"sporting cp", "vitoria guimaraes":"vitoria sc", "psv":"psv eindhoven", "fc twente":"twente"}
        if clear_existing:
            c.execute("DELETE FROM players")
        for row in rows:
            name = (get(row, "name") or "").strip()
            club_name = (get(row, "club") or "").strip()
            if not name or not club_name:
                skipped += 1; continue
            club = by_norm.get(norm(club_name))
            if club is None:
                club = by_norm.get(norm(aliases_clubs.get(norm(club_name), "")))
            if club is None:
                unmatched.add(club_name); continue
            age = parse_int(get(row, "age"), 0)
            if not age and get(row, "dob"):
                try:
                    born = date.fromisoformat(str(get(row, "dob"))[:10])
                    today = date.today(); age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                except ValueError:
                    age = 0
            value = parse_int(get(row, "value"), 0)
            raw_ovr = get(row, "overall")
            if raw_ovr not in (None, ""):
                overall = max(1, min(99, parse_int(raw_ovr, 60)))
                source = "Transfermarkt CSV + supplied OVR"
            else:
                # Explicitly estimated gameplay rating; market value is not an official rating.
                import math
                overall = max(45, min(91, int(52 + math.log10(max(value, 100_000)) * 4.0 - max(0, age - 29) * 1.2)))
                source = "Transfermarkt CSV; OVR estimated from market value/age"
            potential = parse_int(get(row, "potential"), min(99, overall + (max(0, 23-age)//2)))
            position = (get(row, "position") or "").strip()
            wage = parse_int(get(row, "wage"), max(1500, overall * overall * 35))
            c.execute("""INSERT INTO players(club_id,name,position,age,overall,potential,wage,market_value,source)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(club_id,name) DO UPDATE SET
                position=excluded.position,age=excluded.age,overall=excluded.overall,potential=excluded.potential,
                wage=excluded.wage,market_value=excluded.market_value,source=excluded.source""",
                (club["id"], name, position, age or 0, overall, potential, wage, value, source))
            imported += 1
    return {"imported": imported, "unmatched_clubs": sorted(unmatched), "skipped": skipped}

def squad(club_id):
    with connect() as c:return [dict(r) for r in c.execute("SELECT * FROM players WHERE club_id=? ORDER BY overall DESC,name",(club_id,))]




def set_player_position(user_id, player_id, position):
    """Only the club director (the user who owns the club) may change player roles."""
    allowed={"ВР":"Вратарь", "ЦЗ":"Центральный защитник", "ЛЗ":"Левый защитник", "ПЗ":"Правый защитник", "ЦОП":"Опорный полузащитник", "ЦП":"Центральный полузащитник", "ЦАП":"Атакующий полузащитник", "ЛП":"Левый полузащитник", "ПП":"Правый полузащитник", "ЛФ":"Левый форвард", "ЦФ":"Центральный форвард", "ПФ":"Правый форвард"}
    if position not in allowed:
        return False, "Неизвестная роль игрока."
    with connect() as c:
        manager=c.execute("SELECT club_id FROM managers WHERE user_id=?",(user_id,)).fetchone()
        if not manager or manager["club_id"] is None:
            return False, "Сначала выберите клуб."
        cur=c.execute("UPDATE players SET position=? WHERE id=? AND club_id=?",(position,player_id,manager["club_id"]))
        if not cur.rowcount:
            return False, "Игрок не найден в вашем клубе."
    return True, f"Роль игрока изменена: {allowed[position]} ({position})."


def coach_catalog():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM coaches ORDER BY price")]
def hired_coaches(club_id):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT co.*,cc.hired_at FROM club_coaches cc JOIN coaches co ON co.id=cc.coach_id WHERE cc.club_id=? ORDER BY co.skill DESC",(club_id,))]
def hire_coach(user_id, coach_id):
    """Each club can hire at most five distinct coaches; duplicate hiring is forbidden."""
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        m=c.execute("SELECT club_id FROM managers WHERE user_id=?",(user_id,)).fetchone()
        if not m or m["club_id"] is None:return False,"Сначала выберите клуб."
        club_id=m["club_id"]
        coach=c.execute("SELECT * FROM coaches WHERE id=?",(coach_id,)).fetchone()
        if not coach:return False,"Тренер не найден."
        count=c.execute("SELECT COUNT(*) n FROM club_coaches WHERE club_id=?",(club_id,)).fetchone()["n"]
        if count>=5:return False,"Можно нанять не более пяти тренеров."
        if c.execute("SELECT 1 FROM club_coaches WHERE club_id=? AND coach_id=?",(club_id,coach_id)).fetchone():
            return False,"Этот тренер уже нанят."
        club=c.execute("SELECT budget FROM clubs WHERE id=?",(club_id,)).fetchone()
        if club["budget"]<coach["price"]:return False,"Недостаточно средств."
        c.execute("UPDATE clubs SET budget=budget-? WHERE id=?",(coach["price"],club_id))
        c.execute("INSERT INTO club_coaches(club_id,coach_id) VALUES(?,?)",(club_id,coach_id))
        return True,f"Нанят {coach['name']} за €{coach['price']:,}."
def training_plan_catalog():
    with connect() as c:return [dict(r) for r in c.execute("SELECT * FROM training_plans ORDER BY id")]
def train_player(user_id, player_id, plan_id):
    """Progress accumulates fractionally; OVR rises by one only after enough training, capped at 99."""
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        m=c.execute("SELECT club_id FROM managers WHERE user_id=?",(user_id,)).fetchone()
        if not m or m["club_id"] is None:return False,"Сначала выберите клуб."
        club_id=m["club_id"]
        pl=c.execute("SELECT * FROM players WHERE id=? AND club_id=?",(player_id,club_id)).fetchone()
        if not pl:return False,"Игрок не найден в вашем клубе."
        if pl["overall"]>=99:return False,"У игрока уже максимальный OVR 99."
        plan=c.execute("SELECT * FROM training_plans WHERE id=?",(plan_id,)).fetchone()
        if not plan:return False,"Шаблон тренировки не найден."
        coach_rows=list(c.execute("SELECT co.* FROM club_coaches cc JOIN coaches co ON co.id=cc.coach_id WHERE cc.club_id=?",(club_id,)))
        if not coach_rows:return False,"Сначала наймите хотя бы одного тренера."
        # Diminishing returns prevent five coaches from multiplying growth without bound.
        coach_factor=1.0+sum(co["skill"] for co in coach_rows)*0.12
        age_factor=1.15 if pl["age"] and pl["age"]<=21 else (0.75 if pl["age"] and pl["age"]>=30 else 1.0)
        potential=int(pl["potential"] or 99)
        if pl["overall"]>=min(99,potential):return False,"Игрок достиг своего потенциала."
        focus_factor=1.15 if plan["focus"]=="youth" and pl["age"] and pl["age"]<=23 else 1.0
        progress_gain=float(plan["base_gain"])*coach_factor*age_factor*focus_factor
        # Persist fractional progress so training sessions eventually raise OVR.
        prior=float(c.execute("SELECT COALESCE(SUM(progress),0) p FROM training_log WHERE player_id=?",(player_id,)).fetchone()["p"])
        earned=int(c.execute("SELECT COALESCE(SUM(rating_after-rating_before),0) n FROM training_log WHERE player_id=?",(player_id,)).fetchone()["n"])
        total=prior+progress_gain
        rating_before=pl["overall"]
        rating_after=min(99,potential,rating_before+max(0,int(total-earned)))
        # Store the session gain and rating delta so accumulated progress is not counted twice.
        c.execute("INSERT INTO training_log(club_id,player_id,plan_id,rating_before,rating_after,progress) VALUES(?,?,?,?,?,?)",(club_id,player_id,plan_id,rating_before,rating_after,progress_gain))
        if rating_after>rating_before:
            c.execute("UPDATE players SET overall=? WHERE id=?",(rating_after,player_id))
        return True, f"{pl['name']}: OVR {rating_before} → {rating_after}. Прогресс тренировки +{progress_gain:.2f}; тренеров: {len(coach_rows)}."
def team_sheet(club_id):
    """Structured XI for rendering a graphic or text lineup in Telegram."""
    players=squad(club_id)
    by_pos={"GK":[],"DEF":[],"MID":[],"FWD":[]}
    for p in players:
        pos=(p.get("position") or "").upper()
        if any(x in pos for x in ("GK","POR","ВР")): group="GK"
        elif any(x in pos for x in ("CB","LB","RB","WB","DEF","ЗАЩ")): group="DEF"
        elif any(x in pos for x in ("CM","CDM","CAM","LM","RM","MID","ЦП","ЦОП","ЦАП","ПЗ")): group="MID"
        else: group="FWD"
        by_pos[group].append(p)
    xi=[]
    for group,limit in (("GK",1),("DEF",4),("MID",3),("FWD",3)):
        xi.extend(by_pos[group][:limit])
    return xi
