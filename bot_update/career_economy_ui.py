"""Aiogram 3 UI for career_economy extension. Register router after career_multileague_ui.router."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import career_multileague as ml
import career_economy as eco
router=Router(name='career_economy_ui')

def _round_menu():
    rows=[[InlineKeyboardButton(text='🌍 Все лиги',callback_data='eco:round:all')]]
    rows += [[InlineKeyboardButton(text=f'🏆 {l["name"]}',callback_data=f'eco:round:league:{l["id"]}')] for l in ml.league_list()]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(Command('mlround'))
async def round_cmd(m:Message):
    if m.chat.type not in ('group','supergroup'):
        await m.answer('Запускайте тур в группе.');return
    member=await m.bot.get_chat_member(m.chat.id,m.from_user.id)
    if member.status not in ('creator','administrator'):
        await m.answer('Симуляцию тура запускает администратор группы.');return
    await m.answer('Выберите, какие матчи симулировать:',reply_markup=_round_menu())

async def _play_rounds(call, selected):
    lines=[]
    for l in selected:
        with ml.connect() as c:
            row=c.execute('SELECT COALESCE(MAX(round_no),0) r FROM fixtures WHERE league_id=? AND season=? AND played=1',(l['id'],l['season'])).fetchone()
            rnd=int(row['r'])+1
            exists=c.execute('SELECT 1 FROM fixtures WHERE league_id=? AND season=? AND round_no=? AND played=0',(l['id'],l['season'],rnd)).fetchone()
        if not exists:continue
        results=eco.simulate_league_round(l['id'],rnd,l['season'])
        if results:
            lines.append(f'\n🏆 {l["name"]} · тур {rnd}')
            lines.extend(f'{r["home"]} {r["score"]} {r["away"]}' for r in results)
    await call.message.answer('⚽ Результаты тура:\n'+'\n'.join(lines) if lines else 'В выбранных лигах больше нет матчей.')

@router.callback_query(F.data=='eco:round:all')
async def round_all(call:CallbackQuery):
    await _play_rounds(call,ml.league_list());await call.answer()
@router.callback_query(F.data.startswith('eco:round:league:'))
async def round_league(call:CallbackQuery):
    lid=int(call.data.rsplit(':',1)[1]); leagues=[l for l in ml.league_list() if l['id']==lid]
    await _play_rounds(call,leagues);await call.answer()

@router.message(Command('market'))
async def market_cmd(m:Message):
    eco.install(); eco.ai_market_tick()
    offers=eco.pending_for_manager(m.from_user.id)
    if not offers:
        await m.answer('💼 Трансферный рынок обновлён. Сейчас нет ожидающих предложений вашему клубу. ИИ-клубы могут делать новые предложения во время игровых обновлений.');return
    for o in offers[:10]:
        text=f'📩 Предложение от {o["buyer_name"]}\nИгрок: {o["player_name"]}\nСумма: €{o["fee"]:,}\nЗарплата: €{o["wage"]:,}/нед. · контракт {o["years"]} лет'
        if o.get('offered_name'):text+=f'\nОбмен: {o["offered_name"]}'
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Принять',callback_data=f'eco:offer:{o["id"]}:yes'),InlineKeyboardButton(text='❌ Отклонить',callback_data=f'eco:offer:{o["id"]}:no')]])
        await m.answer(text,reply_markup=kb)

@router.callback_query(F.data.startswith('eco:offer:'))
async def offer_decision(call:CallbackQuery):
    _,_,oid,decision=call.data.split(':')
    ok,msg=eco.decide_offer(call.from_user.id,int(oid),decision=='yes')
    await call.answer('Готово' if ok else msg,show_alert=not ok)
    if ok:await call.message.edit_reply_markup(reply_markup=None);await call.message.answer(msg)

@router.message(Command('contracts'))
async def contracts_cmd(m:Message):
    c=ml.my_club(m.from_user.id)
    if not c:await m.answer('Сначала выберите клуб: /leagues');return
    players=ml.squad(c['id'])
    lines=[]
    for p in players[:35]:
        lines.append(f'• {p["name"]} — €{int(p.get("wage") or 0):,}/нед. · {p.get("contract_years",3)} лет · усталость {p.get("fatigue",0)}% · форма {p.get("form",0):+d}')
    await m.answer('📄 Контракты, зарплаты и состояние игроков\n'+'\n'.join(lines))

@router.message(Command('cups'))
async def cups_cmd(m:Message):
    rows=[[InlineKeyboardButton(text=f'🏆 {cup}',callback_data=f'eco:cup:{cup}:1')] for cup in ('ЛЧ','ЛЕ','ЛК')]
    await m.answer('Выберите отдельный еврокубок для симуляции:',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith('eco:cup:'))
async def cup_cb(call:CallbackQuery):
    _,_,cup,rnd=call.data.split(':');rnd=int(rnd)
    eco.install();created=eco.create_cup(cup)
    results=eco.simulate_cup_round(cup,rnd)
    if not results:
        await call.answer('На этом этапе матчей нет. Возможно, сначала нужно начать турнир через /cups.',show_alert=True);return
    text=f'🏆 {cup} · раунд {rnd}\n'+'\n'.join(f'{r["home"]} {r["score"]} {r["away"]}' for r in results)
    next_round=rnd+1
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'Симулировать следующий раунд · {cup}',callback_data=f'eco:cup:{cup}:{next_round}')]]) if len(results)>1 else None
    await call.message.answer(text,reply_markup=kb);await call.answer()


@router.message(Command('transfer'))
async def transfer_cmd(m:Message):
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🆓 Свободные агенты',callback_data='eco:transfer:free:0')],
        [InlineKeyboardButton(text='🔎 Игроки клубов',callback_data='eco:transfer:players:0')]
    ])
    await m.answer('⚽ Трансферный центр\nВыберите раздел:',reply_markup=kb)

@router.callback_query(F.data.startswith('eco:transfer:'))
async def transfer_list(call:CallbackQuery):
    parts=call.data.split(':')
    kind=parts[2]; offset=int(parts[3]) if len(parts)>3 else 0
    if kind=='free':
        agents=eco.list_free_agents(10,offset)
        if not agents:
            await call.answer()
            await call.message.answer('Свободных агентов пока нет в базе. Добавьте игроков в таблицу free_agents, чтобы они появились здесь.')
            return
        lines=['🆓 Свободные агенты:']
        buttons=[]
        for a in agents:
            lines.append(f'• {a["name"]} · {a.get("position") or "—"} · {a.get("age") or "?"} лет · OVR {a["overall"]} · €{int(a.get("market_value") or 0):,}')
            buttons.append([InlineKeyboardButton(text=f'Подписать: {a["name"]}',callback_data=f'eco:transfer:sign:{a["id"]}')])
        if offset: buttons.append([InlineKeyboardButton(text='⬅️ Назад',callback_data=f'eco:transfer:free:{max(0,offset-10)}')])
        if len(agents)==10: buttons.append([InlineKeyboardButton(text='➡️ Далее',callback_data=f'eco:transfer:free:{offset+10}')])
        await call.message.answer('\n'.join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    elif kind=='players':
        players=eco.list_transfer_players(10,offset)
        if not players:
            await call.message.answer('Игроков на рынке пока нет. Сначала импортируйте составы клубов.')
        else:
            lines=['🔎 Игроки клубов (сумма — ориентировочная рыночная стоимость):']
            buttons=[]
            for p in players:
                value=eco.player_market_value(p)
                lines.append(f'• {p["name"]} — {p["club_name"]} · {p.get("age") or "?"} лет · OVR {p["overall"]} · €{value:,}')
                buttons.append([InlineKeyboardButton(text=f'Предложить за {p["name"]}',callback_data=f'eco:transfer:buy:{p["id"]}')])
            nav=[]
            if offset: nav.append(InlineKeyboardButton(text='⬅️ Назад',callback_data=f'eco:transfer:players:{max(0,offset-10)}'))
            if len(players)==10: nav.append(InlineKeyboardButton(text='➡️ Далее',callback_data=f'eco:transfer:players:{offset+10}'))
            if nav: buttons.append(nav)
            await call.message.answer('\n'.join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    elif kind=='sign':
        ok,msg=eco.sign_free_agent(call.from_user.id,int(parts[3]))
        await call.answer(msg,show_alert=True)
    elif kind=='buy':
        club=ml.my_club(call.from_user.id)
        if not club:
            await call.answer('Сначала выберите клуб: /leagues',show_alert=True);return
        with ml.connect() as c:
            player=c.execute('SELECT id,club_id,market_value FROM players WHERE id=?',(int(parts[3]),)).fetchone()
        if not player or player['club_id']==club['id']:
            await call.answer('Нельзя купить этого игрока.',show_alert=True);return
        fee=eco.player_market_value(dict(player))
        ok,msg=eco.create_offer(player['club_id'],player['id'],club['id'],fee=fee)
        await call.answer(msg,show_alert=True)
    await call.answer()


@router.message(Command('playerstats'))
async def playerstats_cmd(m:Message):
    eco.install(); rows=eco.player_leaderboard(15)
    if not rows: await m.answer('Пока нет игроков для статистики.'); return
    lines=['📊 Статистика игроков · голы / ассисты / рейтинг']
    for i,p in enumerate(rows,1):
        lines.append(f"{i}. {p['name']} ({p['club_name']}) — ID {p['id']} | ⚽ {p['goals']} | 🎯 {p['assists']} | ⭐ {p['rating']:.2f} | OVR {p['overall']}")
    await m.answer('\n'.join(lines))

@router.message(Command('finishcup'))
async def finishcup_cmd(m:Message):
    if m.chat.type in ('group','supergroup'):
        member=await m.bot.get_chat_member(m.chat.id,m.from_user.id)
        if member.status not in ('creator','administrator'):
            await m.answer('Завершать турниры может только администратор группы.'); return
    args=(m.text or '').split()
    if len(args)<2 or args[1] not in ('ЛЧ','ЛЕ','ЛК'):
        await m.answer('Использование: /finishcup ЛЧ [сезон]\nТакже доступны ЛЕ и ЛК.'); return
    season=args[2] if len(args)>2 else '2026/27'
    ok,msg=eco.finish_cup(args[1],season)
    await m.answer(msg)

@router.message(Command('finishseason'))
async def finishseason_cmd(m:Message):
    if m.chat.type in ('group','supergroup'):
        member=await m.bot.get_chat_member(m.chat.id,m.from_user.id)
        if member.status not in ('creator','administrator'):
            await m.answer('Завершать сезон может только администратор группы.'); return
    args=(m.text or '').split()
    if len(args)<2:
        leagues=ml.league_list()
        await m.answer('Использование: /finishseason <ID_лиги> [сезон]\nID и названия лиг:\n'+'\n'.join(f'{l["id"]} — {l["name"]}' for l in leagues))
        return
    try: league_id=int(args[1])
    except ValueError:
        await m.answer('Укажите числовой ID лиги. ID можно посмотреть командой /leagues.')
        return
    season=args[2] if len(args)>2 else '2026/27'
    eco.install(); ok,msg=eco.finish_season(league_id,season)
    await m.answer(msg)

@router.message(Command('finishallleagues'))
async def finishallleagues_cmd(m:Message):
    if m.chat.type in ('group','supergroup'):
        member=await m.bot.get_chat_member(m.chat.id,m.from_user.id)
        if member.status not in ('creator','administrator'):
            await m.answer('Завершать все лиги может только администратор группы.'); return
    args=(m.text or '').split(); season=args[1] if len(args)>1 else '2026/27'
    eco.install(); ok,msg=eco.finish_all_leagues(season)
    await m.answer(msg)

@router.message(Command('teamprofile'))
async def teamprofile_cmd(m:Message):
    eco.install(); club=ml.my_club(m.from_user.id)
    if not club: await m.answer('Сначала выберите клуб: /leagues'); return
    trophies=eco.club_trophies(club['id'])
    lines=[f"🏟 Профиль команды: {club['name']}",f"🏆 Кубки: {len(trophies)}"]
    lines += [f"• {t['competition']} — сезон {t['season']}" for t in trophies]
    if not trophies: lines.append('Пока нет выигранных кубков.')
    prizes=eco.season_prize_history(club['id'])
    lines.append('\n💶 Призовые за места в лигах:')
    lines.extend([f'• {x["league"]} · {x["season"]} · место {x["place"]}: €{x["amount"]:,}' for x in prizes] or ['Пока нет сезонных выплат.'])
    await m.answer('\n'.join(lines))

@router.message(Command('playerprofile'))
async def playerprofile_cmd(m:Message):
    eco.install()
    args=(m.text or '').split(maxsplit=1)
    if len(args)<2:
        await m.answer('Использование: /playerprofile <имя игрока или ID>\nНапример: /playerprofile Мбаппе'); return
    query=args[1].strip()
    p=eco.player_profile(player_id=int(query)) if query.isdigit() else eco.player_profile(name=query)
    if not p:
        await m.answer('Игрок не найден. Укажите точное имя или ID игрока. ID можно узнать в профиле другого игрока/списке статистики.'); return
    lines=[f"👤 Профиль игрока: {p['name']}",f"🏟 Команда: {p['club_name']}",f"🪪 ID: {p['id']} · позиция: {p.get('position') or '—'} · возраст: {p.get('age') or '—'}",f"⭐ Общий рейтинг: {p['overall']} · потенциал: {p.get('potential') or '—'}",'', '📊 Результативность:',f"⚽ Голы: {p['goals']}",f"🎯 Ассисты: {p['assists']}",f"🗓 Матчи: {p['appearances']}",f"🌟 Средняя оценка: {p['rating']:.2f}"]
    lines.append('🏅 Награды:')
    lines.extend([f"• {a['award']} — {a['season']}" for a in p['awards']] or ['Пока нет индивидуальных наград.'])
    await m.answer('\n'.join(lines))

@router.message(Command('goldenball'))
async def goldenball_cmd(m:Message):
    if m.chat.type in ('group','supergroup'):
        member=await m.bot.get_chat_member(m.chat.id,m.from_user.id)
        if member.status not in ('creator','administrator'):
            await m.answer('Выдавать Золотой мяч может только администратор группы.'); return
    args=(m.text or '').split()
    season=args[1] if len(args)>1 else '2026/27'
    ok,msg=eco.award_golden_ball(season)
    await m.answer(msg)
