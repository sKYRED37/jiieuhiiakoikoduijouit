"""Optional economy, contracts, fatigue and cup competitions extension for career_multileague.
Install with career_economy.install(); register career_economy_ui.router in aiogram.
"""
from __future__ import annotations
import random, sqlite3
from datetime import date, timedelta
import career_multileague as ml


def install():
    ml.install()
    with ml.connect() as c:
        cols={r['name'] for r in c.execute('PRAGMA table_info(players)')}
        for name,ddl in [('fatigue','INTEGER NOT NULL DEFAULT 0'),('form','INTEGER NOT NULL DEFAULT 0'),('contract_until','TEXT'),('contract_years','INTEGER NOT NULL DEFAULT 3')]:
            if name not in cols: c.execute(f'ALTER TABLE players ADD COLUMN {name} {ddl}')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS transfer_offers(id INTEGER PRIMARY KEY, seller_club INTEGER NOT NULL, buyer_club INTEGER NOT NULL, player_id INTEGER NOT NULL, fee INTEGER NOT NULL, wage INTEGER NOT NULL DEFAULT 0, years INTEGER NOT NULL DEFAULT 3, offered_player_id INTEGER, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS contracts(id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL UNIQUE, wage INTEGER NOT NULL, years INTEGER NOT NULL, signed_on TEXT NOT NULL DEFAULT CURRENT_DATE);
        CREATE TABLE IF NOT EXISTS cup_fixtures(id INTEGER PRIMARY KEY, competition TEXT NOT NULL, season TEXT NOT NULL, round_no INTEGER NOT NULL, home_id INTEGER NOT NULL, away_id INTEGER NOT NULL, home_goals INTEGER, away_goals INTEGER, played INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS match_log(id INTEGER PRIMARY KEY, fixture_id INTEGER, competition TEXT NOT NULL, played_on TEXT NOT NULL DEFAULT CURRENT_DATE, club_id INTEGER NOT NULL, opponent_id INTEGER NOT NULL, goals_for INTEGER NOT NULL, goals_against INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS transfer_history(id INTEGER PRIMARY KEY, club_id INTEGER NOT NULL, player_id INTEGER, action TEXT NOT NULL, day TEXT NOT NULL DEFAULT CURRENT_DATE);
        CREATE TABLE IF NOT EXISTS free_agents(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, position TEXT, age INTEGER, overall INTEGER NOT NULL, potential INTEGER, wage INTEGER DEFAULT 0, market_value INTEGER DEFAULT 0, contract_years INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS player_stats(player_id INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE, goals INTEGER NOT NULL DEFAULT 0, assists INTEGER NOT NULL DEFAULT 0, appearances INTEGER NOT NULL DEFAULT 0, rating_sum REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS trophies(id INTEGER PRIMARY KEY, competition TEXT NOT NULL, season TEXT NOT NULL, club_id INTEGER NOT NULL REFERENCES clubs(id), awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(competition,season));
        CREATE TABLE IF NOT EXISTS player_awards(id INTEGER PRIMARY KEY, award TEXT NOT NULL, season TEXT NOT NULL, player_id INTEGER NOT NULL REFERENCES players(id), awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(award,season));
        CREATE TABLE IF NOT EXISTS season_closures(id INTEGER PRIMARY KEY, league_id INTEGER NOT NULL REFERENCES leagues(id), season TEXT NOT NULL, champion_club_id INTEGER NOT NULL REFERENCES clubs(id), closed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(league_id,season));
        CREATE TABLE IF NOT EXISTS season_prizes(id INTEGER PRIMARY KEY, league_id INTEGER NOT NULL REFERENCES leagues(id), season TEXT NOT NULL, club_id INTEGER NOT NULL REFERENCES clubs(id), place INTEGER NOT NULL, amount INTEGER NOT NULL, UNIQUE(league_id,season,club_id));
        ''')
        # Contracts get realistic baseline wages based on OVR and market value, without overwriting existing wages.
        c.execute("UPDATE players SET wage=CASE WHEN COALESCE(wage,0)>0 THEN wage ELSE MAX(1500, overall*overall*35) END")
        c.execute("UPDATE players SET market_value=CASE WHEN COALESCE(market_value,0)>0 THEN market_value ELSE CAST(overall*overall*overall*180 AS INTEGER) END")
        c.execute("UPDATE players SET contract_until=DATE('now','+'||COALESCE(contract_years,3)||' years') WHERE contract_until IS NULL")


def _owner(c, club_id):
    row=c.execute('SELECT user_id FROM managers WHERE club_id=?',(club_id,)).fetchone()
    return row['user_id'] if row else None

def player_market_value(player):
    age=player['age'] or 26; ovr=player['overall'] or 60
    age_factor=1.25 if age<=23 else (1.0 if age<=28 else max(.35,1-(age-28)*.08))
    return max(100_000, int((player['market_value'] or ovr**3*180)*age_factor))

def create_offer(seller_club, player_id, buyer_club, fee=None, wage=None, years=3, offered_player_id=None):
    with ml.connect() as c:
        p=c.execute('SELECT * FROM players WHERE id=? AND club_id=?',(player_id,seller_club)).fetchone()
        b=c.execute('SELECT * FROM clubs WHERE id=?',(buyer_club,)).fetchone()
        s=c.execute('SELECT * FROM clubs WHERE id=?',(seller_club,)).fetchone()
        if not p or not b or not s:return False,'Игрок или клуб не найден.'
        value=player_market_value(dict(p)); fee=int(fee if fee is not None else value*random.uniform(0.88,1.22))
        if fee<1:return False,'Сумма предложения должна быть положительной.'
        if fee>b['budget']:return False,'У покупателя недостаточно бюджета.'
        if offered_player_id:
            op=c.execute('SELECT * FROM players WHERE id=? AND club_id=?',(offered_player_id,buyer_club)).fetchone()
            if not op:return False,'Игрок для обмена не принадлежит покупателю.'
        cur=c.execute('INSERT INTO transfer_offers(seller_club,buyer_club,player_id,fee,wage,years,offered_player_id) VALUES(?,?,?,?,?,?,?)',(seller_club,buyer_club,player_id,fee,int(wage or p['wage'] or 0),max(1,min(5,int(years))),offered_player_id))
        return True, f'Предложение №{cur.lastrowid}: €{fee:,}, зарплата €{int(wage or p["wage"] or 0):,}/нед., контракт на {years} лет.'

def pending_for_manager(user_id):
    with ml.connect() as c:
        m=c.execute('SELECT club_id FROM managers WHERE user_id=?',(user_id,)).fetchone()
        if not m or m['club_id'] is None:return []
        return [dict(r) for r in c.execute('''SELECT o.*,p.name player_name,b.name buyer_name,s.name seller_name,op.name offered_name FROM transfer_offers o JOIN players p ON p.id=o.player_id JOIN clubs b ON b.id=o.buyer_club JOIN clubs s ON s.id=o.seller_club LEFT JOIN players op ON op.id=o.offered_player_id WHERE o.seller_club=? AND o.status='pending' ORDER BY o.id DESC''',(m['club_id'],))]

def decide_offer(user_id, offer_id, accept):
    with ml.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        o=c.execute('SELECT * FROM transfer_offers WHERE id=? AND status="pending"',(offer_id,)).fetchone()
        if not o:return False,'Предложение уже обработано.'
        m=c.execute('SELECT club_id FROM managers WHERE user_id=?',(user_id,)).fetchone()
        if not m or m['club_id']!=o['seller_club']:return False,'Решение может принять только директор продающего клуба.'
        if not accept:
            c.execute('UPDATE transfer_offers SET status="rejected" WHERE id=?',(offer_id,)); return True,'Предложение отклонено.'
        p=c.execute('SELECT * FROM players WHERE id=? AND club_id=?',(o['player_id'],o['seller_club'])).fetchone()
        buyer=c.execute('SELECT budget FROM clubs WHERE id=?',(o['buyer_club'],)).fetchone()
        seller=c.execute('SELECT budget FROM clubs WHERE id=?',(o['seller_club'],)).fetchone()
        if not p or not buyer or buyer['budget']<o['fee']:return False,'Игрок или бюджет изменились; сделка отменена.'
        if o['offered_player_id']:
            op=c.execute('SELECT * FROM players WHERE id=? AND club_id=?',(o['offered_player_id'],o['buyer_club'])).fetchone()
            if not op:return False,'Игрок для обмена уже недоступен.'
            c.execute('UPDATE players SET club_id=? WHERE id=?',(o['seller_club'],op['id']))
        c.execute('UPDATE clubs SET budget=budget-? WHERE id=?',(o['fee'],o['buyer_club']))
        c.execute('UPDATE clubs SET budget=budget+? WHERE id=?',(o['fee'],o['seller_club']))
        c.execute('UPDATE players SET club_id=?,wage=?,contract_years=?,contract_until=DATE(\'now\', ? || \' years\') WHERE id=?',(o['buyer_club'],o['wage'],o['years'],f'+{o["years"]}',p['id']))
        c.execute('INSERT INTO contracts(player_id,wage,years) VALUES(?,?,?) ON CONFLICT(player_id) DO UPDATE SET wage=excluded.wage,years=excluded.years,signed_on=CURRENT_DATE',(p['id'],o['wage'],o['years']))
        c.execute('UPDATE transfer_offers SET status="accepted" WHERE id=?',(offer_id,))
        return True,f'Сделка завершена: {p["name"]} перешёл за €{o["fee"]:,}. Контракт: {o["years"]} лет, €{o["wage"]:,}/нед.'

def ai_market_tick():
    """Conservative AI transfers: one deal per AI club per 7 days, max two per year,
    roster cap 28, and AI never auto-buys from a human-managed club."""
    made=[]
    with ml.connect() as c:
        clubs=[dict(r) for r in c.execute('SELECT * FROM clubs')]
        managed={r['club_id'] for r in c.execute('SELECT club_id FROM managers WHERE club_id IS NOT NULL')}
        season=date.today().strftime('%Y')
        for buyer in clubs:
            if buyer['id'] in managed or random.random() > .025:
                continue
            recent=c.execute("SELECT COUNT(*) n FROM transfer_history WHERE club_id=? AND action='ai_buy' AND day>=DATE('now','-7 days')",(buyer['id'],)).fetchone()['n']
            yearly=c.execute("SELECT COUNT(*) n FROM transfer_history WHERE club_id=? AND action='ai_buy' AND substr(day,1,4)=?",(buyer['id'],season)).fetchone()['n']
            roster_count=c.execute('SELECT COUNT(*) n FROM players WHERE club_id=?',(buyer['id'],)).fetchone()['n']
            if recent>=1 or yearly>=2 or roster_count>=28: continue
            positions=[r['position'] for r in c.execute('SELECT position FROM players WHERE club_id=?',(buyer['id'],))]
            candidates=[]
            for seller in clubs:
                if seller['id']==buyer['id'] or seller['id'] in managed: continue
                for p in c.execute('SELECT * FROM players WHERE club_id=?',(seller['id'],)):
                    value=player_market_value(dict(p)); fee=int(value*random.uniform(1.12,1.38))
                    if fee<=buyer['budget'] and (not p['position'] or positions.count(p['position'])<2):
                        candidates.append((seller,dict(p),fee))
            if not candidates: continue
            seller,p,fee=random.choice(candidates)
            wage=int(max(p['wage'] or 1500,1500)*random.uniform(1.08,1.22))
            c.execute('UPDATE clubs SET budget=budget-? WHERE id=?',(fee,buyer['id']))
            c.execute('UPDATE clubs SET budget=budget+? WHERE id=?',(fee,seller['id']))
            c.execute("UPDATE players SET club_id=?,wage=?,contract_years=3,contract_until=DATE('now','+3 years') WHERE id=?",(buyer['id'],wage,p['id']))
            c.execute("INSERT INTO transfer_history(club_id,player_id,action) VALUES(?,?,'ai_buy')",(buyer['id'],p['id']))
            made.append(f'{p["name"]}: {seller["name"]} → {buyer["name"]} (€{fee:,})')
    return made


def list_free_agents(limit=10, offset=0):
    install()
    with ml.connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM free_agents ORDER BY overall DESC, age ASC LIMIT ? OFFSET ?',(limit,offset))]

def list_transfer_players(limit=10, offset=0):
    install()
    with ml.connect() as c:
        return [dict(r) for r in c.execute('SELECT p.*,c.name club_name FROM players p JOIN clubs c ON c.id=p.club_id ORDER BY p.overall DESC, p.market_value DESC LIMIT ? OFFSET ?',(limit,offset))]

def sign_free_agent(user_id, agent_id):
    with ml.connect() as c:
        m=c.execute('SELECT club_id FROM managers WHERE user_id=?',(user_id,)).fetchone()
        if not m or m['club_id'] is None: return False,'Сначала выберите клуб.'
        a=c.execute('SELECT * FROM free_agents WHERE id=?',(agent_id,)).fetchone()
        club=c.execute('SELECT * FROM clubs WHERE id=?',(m['club_id'],)).fetchone()
        if not a: return False,'Свободный агент уже недоступен.'
        roster=c.execute('SELECT COUNT(*) n FROM players WHERE club_id=?',(m['club_id'],)).fetchone()['n']
        if roster>=28: return False,'В составе уже 28 игроков.'
        wage=int(a['wage'] or max(1500,a['overall']**2*30))
        c.execute('INSERT INTO players(club_id,name,position,age,overall,potential,wage,market_value,source) VALUES(?,?,?,?,?,?,?,?,?)',(m['club_id'],a['name'],a['position'],a['age'],a['overall'],a['potential'],wage,a['market_value'],'Free agent'))
        c.execute('DELETE FROM free_agents WHERE id=?',(agent_id,))
        return True,f'Подписан {a["name"]}: OVR {a["overall"]}, €{wage:,}/нед.'


def _record_player_match(c, club_id, goals, opponent_id, competition):
    """Record one appearance for every squad player, then attribute goals/assists."""
    players=[dict(r) for r in c.execute("SELECT id,overall FROM players WHERE club_id=?",(club_id,))]
    if not players: return
    ratings={p['id']: max(4.5, min(10.0, 6.2 + (p['overall']-65)*0.035 + random.uniform(-0.8,1.0))) for p in players}
    for p in players:
        c.execute("INSERT INTO player_stats(player_id,goals,assists,appearances,rating_sum) VALUES(?,0,0,1,?) ON CONFLICT(player_id) DO UPDATE SET appearances=appearances+1,rating_sum=rating_sum+excluded.rating_sum",(p['id'],ratings[p['id']]))
    for _ in range(int(goals or 0)):
        scorer=random.choice(players)
        c.execute("UPDATE player_stats SET goals=goals+1 WHERE player_id=?",(scorer['id'],))
        if len(players)>1 and random.random()<0.78:
            assist=random.choice([p for p in players if p['id']!=scorer['id']])
            c.execute("UPDATE player_stats SET assists=assists+1 WHERE player_id=?",(assist['id'],))

def player_profile(player_id=None, name=None):
    install()
    with ml.connect() as c:
        if player_id is not None:
            row=c.execute("SELECT p.id,p.name,p.position,p.age,p.overall,p.potential,p.club_id,cl.name club_name,COALESCE(s.goals,0) goals,COALESCE(s.assists,0) assists,COALESCE(s.appearances,0) appearances,CASE WHEN COALESCE(s.appearances,0)>0 THEN ROUND(s.rating_sum/s.appearances,2) ELSE 0 END rating FROM players p JOIN clubs cl ON cl.id=p.club_id LEFT JOIN player_stats s ON s.player_id=p.id WHERE p.id=?",(player_id,)).fetchone()
        else:
            row=c.execute("SELECT p.id,p.name,p.position,p.age,p.overall,p.potential,p.club_id,cl.name club_name,COALESCE(s.goals,0) goals,COALESCE(s.assists,0) assists,COALESCE(s.appearances,0) appearances,CASE WHEN COALESCE(s.appearances,0)>0 THEN ROUND(s.rating_sum/s.appearances,2) ELSE 0 END rating FROM players p JOIN clubs cl ON cl.id=p.club_id LEFT JOIN player_stats s ON s.player_id=p.id WHERE p.name=? COLLATE NOCASE ORDER BY p.overall DESC LIMIT 1",(name,)).fetchone()
            if not row and name:
                row=c.execute("SELECT p.id,p.name,p.position,p.age,p.overall,p.potential,p.club_id,cl.name club_name,COALESCE(s.goals,0) goals,COALESCE(s.assists,0) assists,COALESCE(s.appearances,0) appearances,CASE WHEN COALESCE(s.appearances,0)>0 THEN ROUND(s.rating_sum/s.appearances,2) ELSE 0 END rating FROM players p JOIN clubs cl ON cl.id=p.club_id LEFT JOIN player_stats s ON s.player_id=p.id WHERE p.name LIKE ? COLLATE NOCASE ORDER BY p.overall DESC LIMIT 1",('%'+name+'%',)).fetchone()
        if not row:return None
        result=dict(row)
        result['awards']=[dict(r) for r in c.execute("SELECT award,season FROM player_awards WHERE player_id=? ORDER BY awarded_at DESC",(result['id'],))]
        return result

def award_golden_ball(season='2026/27'):
    install()
    with ml.connect() as c:
        if c.execute("SELECT 1 FROM player_awards WHERE award='Золотой мяч' AND season=?",(season,)).fetchone():
            return False, 'Золотой мяч за этот сезон уже выдан.'
        row=c.execute("SELECT p.id,p.name,p.overall,cl.name club_name,COALESCE(s.goals,0) goals,COALESCE(s.assists,0) assists,COALESCE(s.appearances,0) appearances,CASE WHEN COALESCE(s.appearances,0)>0 THEN ROUND(s.rating_sum/s.appearances,2) ELSE 0 END rating FROM players p JOIN clubs cl ON cl.id=p.club_id LEFT JOIN player_stats s ON s.player_id=p.id WHERE COALESCE(s.appearances,0)>0 ORDER BY (COALESCE(s.goals,0)*2.2 + COALESCE(s.assists,0)*1.5 + CASE WHEN COALESCE(s.appearances,0)>0 THEN s.rating_sum/s.appearances ELSE 0 END*3 + p.overall*0.08) DESC, s.goals DESC LIMIT 1").fetchone()
        if not row:return False, 'Нет сыгранных матчей и статистики для определения обладателя.'
        c.execute("INSERT INTO player_awards(award,season,player_id) VALUES('Золотой мяч',?,?)",(season,row['id']))
        return True, f"🏆 Золотой мяч {season} получает {row['name']} ({row['club_name']})! Голы: {row['goals']} · ассисты: {row['assists']} · матчей: {row['appearances']} · рейтинг: {row['rating']:.2f}. Награда сохранена в профиль игрока №{row['id']}."

def player_leaderboard(limit=15):
    install()
    with ml.connect() as c:
        sql="SELECT p.id,p.name,p.position,p.overall,cl.name club_name,COALESCE(s.goals,0) goals,COALESCE(s.assists,0) assists,COALESCE(s.appearances,0) appearances,CASE WHEN COALESCE(s.appearances,0)>0 THEN ROUND(s.rating_sum/s.appearances,2) ELSE 0 END rating FROM players p JOIN clubs cl ON cl.id=p.club_id LEFT JOIN player_stats s ON s.player_id=p.id ORDER BY goals DESC,assists DESC,rating DESC,p.overall DESC LIMIT ?"
        return [dict(r) for r in c.execute(sql,(limit,))]

def club_trophies(club_id):
    install()
    with ml.connect() as c:
        return [dict(r) for r in c.execute("SELECT competition,season,awarded_at FROM trophies WHERE club_id=? ORDER BY awarded_at DESC",(club_id,))]

def finish_cup(competition, season='2026/27'):
    install()
    with ml.connect() as c:
        rounds=list(c.execute("SELECT round_no,COUNT(*) total,SUM(played) done FROM cup_fixtures WHERE competition=? AND season=? GROUP BY round_no ORDER BY round_no DESC",(competition,season)))
        if not rounds: return False,'Турнир не найден.'
        final=rounds[0]
        if final['total']!=1 or final['done']!=1: return False,'Финал ещё не сыгран. Доведите турнир до финального матча и сыграйте его.'
        row=c.execute("SELECT f.home_id,f.away_id,f.home_goals,f.away_goals,h.name home,a.name away FROM cup_fixtures f JOIN clubs h ON h.id=f.home_id JOIN clubs a ON a.id=f.away_id WHERE f.competition=? AND f.season=? AND f.round_no=? AND f.played=1",(competition,season,final['round_no'])).fetchone()
        winner=row['home_id'] if row['home_goals']>row['away_goals'] else row['away_id']
        club=row['home'] if winner==row['home_id'] else row['away']
        cur=c.execute("INSERT OR IGNORE INTO trophies(competition,season,club_id) VALUES(?,?,?)",(competition,season,winner))
        if not cur.rowcount: return False,'Кубок за этот сезон уже выдан.'
        prize={'ЛЧ':15_000_000,'ЛЕ':10_000_000,'ЛК':7_000_000}.get(competition,5_000_000)
        c.execute('UPDATE clubs SET budget=budget+? WHERE id=?',(prize,winner))
        return True,f'🏆 Турнир {competition} {season} завершён! Кубок выдан команде «{club}», призовые: €{prize:,}.'

def _advance_season_players(c, league_id):
    """Age every player in this league once and apply a gradual age curve to OVR.

    Young players can grow toward potential; players in their prime are mostly stable;
    players over 29 gradually decline. This is called only after a season closure is
    inserted, so the closure uniqueness constraint prevents duplicate aging.
    """
    rows = list(c.execute(
        "SELECT p.id,p.age,p.overall,p.potential FROM players p "
        "JOIN clubs cl ON cl.id=p.club_id WHERE cl.league_id=?", (league_id,)))
    for p in rows:
        age = int(p['age'] or 0)
        ovr = int(p['overall'] or 50)
        potential = int(p['potential'] or ovr)
        new_age = age + 1
        if age <= 21:
            # Development is modest and never exceeds potential.
            new_ovr = min(potential, ovr + (1 if random.random() < 0.65 else 0))
        elif age <= 28:
            new_ovr = ovr
        elif age <= 30:
            new_ovr = max(1, ovr - (1 if random.random() < 0.35 else 0))
        elif age <= 32:
            new_ovr = max(1, ovr - (1 if random.random() < 0.65 else 0))
        else:
            new_ovr = max(1, ovr - (1 if random.random() < 0.75 else 2))
        c.execute('UPDATE players SET age=?, overall=? WHERE id=?',
                  (new_age, new_ovr, p['id']))


def finish_season(league_id, season='2026/27'):
    """Close one completed league season, award champion trophy and distribute place-based prize money."""
    install()
    prize_by_place=[25_000_000,18_000_000,14_000_000,11_000_000,9_000_000,7_500_000,6_000_000,5_000_000,4_000_000,3_500_000,3_000_000,2_800_000,2_600_000,2_400_000,2_200_000,2_000_000,1_800_000,1_600_000,1_400_000,1_200_000]
    league=next((x for x in ml.league_list() if x['id']==int(league_id)),None)
    if not league:return False,'Лига не найдена.'
    with ml.connect() as c:
        total=c.execute('SELECT COUNT(*) n FROM fixtures WHERE league_id=? AND season=?',(league_id,season)).fetchone()['n']
        done=c.execute('SELECT COUNT(*) n FROM fixtures WHERE league_id=? AND season=? AND played=1',(league_id,season)).fetchone()['n']
        if not total:return False,f'Для {league["name"]} не создан календарь сезона {season}.'
        if done!=total:return False,f'Сезон {season} нельзя завершить: сыграно {done} из {total} матчей в лиге {league["name"]}.'
        if c.execute('SELECT 1 FROM season_closures WHERE league_id=? AND season=?',(league_id,season)).fetchone():return False,f'Сезон {season} лиги {league["name"]} уже завершён.'
        standings=ml.table(int(league_id),season)
        if not standings:return False,'Не удалось рассчитать итоговую таблицу.'
        champion=standings[0]
        c.execute('INSERT INTO season_closures(league_id,season,champion_club_id) VALUES(?,?,?)',(league_id,season,champion['id']))
        # Age/develop/decline every player exactly once for this closed league season.
        _advance_season_players(c, league_id)
        c.execute('INSERT OR IGNORE INTO trophies(competition,season,club_id) VALUES(?,?,?)',(league['name'],season,champion['id']))
        payout_lines=[]
        for place,team in enumerate(standings,1):
            prize=prize_by_place[min(place-1,len(prize_by_place)-1)]
            c.execute('UPDATE clubs SET budget=budget+? WHERE id=?',(prize,team['id']))
            c.execute('INSERT OR IGNORE INTO season_prizes(league_id,season,club_id,place,amount) VALUES(?,?,?,?,?)',(league_id,season,team['id'],place,prize))
            payout_lines.append(f'{place}. {team["name"]} — €{prize:,}')
        best=c.execute("SELECT p.id,p.name,cl.name club_name,COALESCE(s.goals,0) goals,COALESCE(s.assists,0) assists,COALESCE(s.appearances,0) appearances,CASE WHEN COALESCE(s.appearances,0)>0 THEN s.rating_sum/s.appearances ELSE 0 END rating FROM players p JOIN clubs cl ON cl.id=p.club_id LEFT JOIN player_stats s ON s.player_id=p.id WHERE cl.league_id=? AND COALESCE(s.appearances,0)>0 ORDER BY (COALESCE(s.rating_sum,0)/MAX(1,COALESCE(s.appearances,0))*4 + COALESCE(s.goals,0)*1.2 + COALESCE(s.assists,0)*0.8) DESC, goals DESC LIMIT 1",(league_id,)).fetchone()
        award_text=''
        if best:
            award=f'Игрок сезона — {league["name"]}'
            c.execute('INSERT OR IGNORE INTO player_awards(award,season,player_id) VALUES(?,?,?)',(award,season,best['id']))
            award_text=f'\n🌟 Игрок сезона: {best["name"]} ({best["club_name"]}) — голы {best["goals"]}, ассисты {best["assists"]}, средняя оценка {best["rating"]:.2f}.'
        return True,f'🏁 Сезон {season} завершён: {league["name"]}.\n🏆 Чемпион: {champion["name"]} — кубок добавлен в профиль команды.\n💶 Выплаты по местам:\n'+'\n'.join(payout_lines)+award_text

def finish_all_leagues(season='2026/27'):
    """Close all seven leagues; validate all schedules before changing anything."""
    install(); leagues=ml.league_list()
    if len(leagues)!=7:return False,f'Ожидалось 7 лиг, найдено {len(leagues)}. Ничего не завершено.'
    with ml.connect() as c:
        for league in leagues:
            total=c.execute('SELECT COUNT(*) n FROM fixtures WHERE league_id=? AND season=?',(league['id'],season)).fetchone()['n']
            done=c.execute('SELECT COUNT(*) n FROM fixtures WHERE league_id=? AND season=? AND played=1',(league['id'],season)).fetchone()['n']
            if not total or total!=done:return False,f'Все 7 лиг не завершены. {league["name"]}: сыграно {done}/{total}. Сначала доиграйте все матчи.'
            if c.execute('SELECT 1 FROM season_closures WHERE league_id=? AND season=?',(league['id'],season)).fetchone():return False,f'Лига {league["name"]} за сезон {season} уже закрыта. Для защиты от повторных выплат операция остановлена.'
    results=[]
    for league in leagues:
        ok,msg=finish_season(league['id'],season)
        if not ok:return False,'Остановлено: '+msg
        results.append(msg)
    return True,'🌍 ВСЕ 7 ЛИГ ЗАВЕРШЕНЫ!\n\n'+'\n\n'.join(results)

def season_prize_history(club_id):
    install()
    with ml.connect() as c:
        return [dict(r) for r in c.execute('SELECT l.name league,sp.season,sp.place,sp.amount FROM season_prizes sp JOIN leagues l ON l.id=sp.league_id WHERE sp.club_id=? ORDER BY sp.season DESC,sp.place',(club_id,))]

def apply_match_effects(fixture_id, competition='league'):
    """Fatigue rises after a match; recent form changes modestly. Recovery is 3 days between fixtures."""
    with ml.connect() as c:
        f=c.execute('SELECT * FROM fixtures WHERE id=?',(fixture_id,)).fetchone()
        if not f or not f['played']:return
        for cid,gf,ga in ((f['home_id'],f['home_goals'],f['away_goals']),(f['away_id'],f['away_goals'],f['home_goals'])):
            c.execute('UPDATE players SET fatigue=MIN(100,fatigue+CASE WHEN fatigue>70 THEN 24 ELSE 32 END), form=MAX(-3,MIN(3,form+?)) WHERE club_id=?',(1 if gf>ga else (-1 if gf<ga else 0),cid))
            c.execute('INSERT INTO match_log(competition,club_id,opponent_id,goals_for,goals_against) VALUES(?,?,?,?,?)',(competition,cid,f['away_id'] if cid==f['home_id'] else f['home_id'],gf,ga))
            _record_player_match(c,cid,gf,f['away_id'] if cid==f['home_id'] else f['home_id'],competition)

def recover_three_days():
    with ml.connect() as c:c.execute('UPDATE players SET fatigue=MAX(0,fatigue-35)')

def simulate_league_round(league_id, round_no, season='2026/27'):
    with ml.connect() as c:
        old=list(c.execute('SELECT id FROM fixtures WHERE league_id=? AND season=? AND round_no=? AND played=0',(league_id,season,round_no)))
    results=ml.play_round(league_id,round_no,season)
    for row in old: apply_match_effects(row['id'],'league')
    if results: recover_three_days()
    return results

def create_cup(competition, season='2026/27'):
    """Create a separate knockout bracket for UCL/UEL/UECL, with clubs from all leagues."""
    if competition not in ('ЛЧ','ЛЕ','ЛК'):return 0
    with ml.connect() as c:
        if c.execute('SELECT 1 FROM cup_fixtures WHERE competition=? AND season=?',(competition,season)).fetchone():return 0
        ids=[r['id'] for r in c.execute('SELECT id FROM clubs ORDER BY RANDOM() LIMIT 16')]
        random.shuffle(ids); rnd=1; count=0
        for i in range(0,len(ids)-1,2):
            c.execute('INSERT INTO cup_fixtures(competition,season,round_no,home_id,away_id) VALUES(?,?,?,?,?)',(competition,season,rnd,ids[i],ids[i+1]));count+=1
        return count

def simulate_cup_round(competition, round_no, season='2026/27'):
    with ml.connect() as c:
        rows=list(c.execute('SELECT f.*,h.name home,a.name away FROM cup_fixtures f JOIN clubs h ON h.id=f.home_id JOIN clubs a ON a.id=f.away_id WHERE competition=? AND season=? AND round_no=? AND played=0',(competition,season,round_no)))
        results=[]
        for f in rows:
            hs=c.execute('SELECT AVG(overall) x FROM players WHERE club_id=?',(f['home_id'],)).fetchone()['x'] or 68
            aws=c.execute('SELECT AVG(overall) x FROM players WHERE club_id=?',(f['away_id'],)).fetchone()['x'] or 68
            hg=max(0,min(5,round(random.gauss(1.3+(hs-aws)*.045,1.0)))); ag=max(0,min(5,round(random.gauss(1.1+(aws-hs)*.045,1.0))))
            if hg==ag: # knockout tie-breaker, winner advances without a drawn bracket result
                if random.random()<.5:hg+=1
                else:ag+=1
            c.execute('UPDATE cup_fixtures SET home_goals=?,away_goals=?,played=1 WHERE id=?',(hg,ag,f['id']))
            winner=f['home_id'] if hg>ag else f['away_id']
            _record_player_match(c,f['home_id'],hg,f['away_id'],competition)
            _record_player_match(c,f['away_id'],ag,f['home_id'],competition)
            results.append({'home':f['home'],'away':f['away'],'score':f'{hg}:{ag}','winner_id':winner})
        if results:
            next_round=round_no+1
            for i in range(0,len(results)-1,2):
                a,b=results[i]['winner_id'],results[i+1]['winner_id']
                c.execute('INSERT INTO cup_fixtures(competition,season,round_no,home_id,away_id) VALUES(?,?,?,?,?)',(competition,season,next_round,a,b))
        return results
