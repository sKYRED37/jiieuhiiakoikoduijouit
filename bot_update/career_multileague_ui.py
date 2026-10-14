"""Optional aiogram 3 router for the standalone seven-league backend.
Include with dp.include_router(career_multileague_ui.router).
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
import career_multileague as ml

router = Router(name="career_multileague_ui")

def _league_keyboard():
    rows=[]
    for l in ml.league_list():
        rows.append([InlineKeyboardButton(text=f"{l['name']} · {l['club_count']} клубов", callback_data=f"ml:league:{l['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _clubs_keyboard(league_id):
    rows=[]
    for c in ml.clubs(league_id, free_only=True):
        rows.append([InlineKeyboardButton(text=f"🏟 {c['name']} · €{c['budget']:,}", callback_data=f"ml:claim:{c['id']}")])
    if not rows:
        rows=[[InlineKeyboardButton(text="Свободных клубов нет",callback_data="ml:none")]]
    rows.append([InlineKeyboardButton(text="↩️ Все лиги",callback_data="ml:leagues")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(Command("mlsetup"))
async def mlsetup(message: Message):
    if message.chat.type in ("group", "supergroup"):
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in ("creator", "administrator"):
            await message.answer("Подготовить игровую базу может только администратор группы.")
            return
    ml.install()
    import career_economy as eco
    eco.install()
    generated = ml.seed_generated_squads()
    ml.seed_calendar()
    created=[]
    for l in ml.league_list():
        with ml.connect() as con:
            exists=con.execute("SELECT 1 FROM fixtures WHERE league_id=? AND season=? LIMIT 1",(l["id"],l["season"])).fetchone()
        count=0 if exists else ml.generate_fixtures(l["id"],season=l["season"])
        created.append(f"• {l['name']}: {'календарь сохранён' if exists else str(count) + ' туров создано'}")
    await message.answer("⚽ Игровая база 7 лиг подготовлена.\n"+"\n".join(created)+f"\n\nСгенерировано игроков: {generated}. Составы доступны через /squad и /myteam.")

@router.message(Command("leagues"))
async def leagues_cmd(message: Message):
    await message.answer("🌍 Выберите лигу, чтобы занять свободный клуб:",reply_markup=_league_keyboard())

@router.message(Command("myteam"))
async def myteam_cmd(message: Message):
    c=ml.my_club(message.from_user.id)
    if not c:
        await message.answer("У вас пока нет клуба. Используйте /leagues")
        return
    players=ml.squad(c["id"])
    text=f"🏟 {c['name']} — {c['league']}\nБюджет: €{c['budget']:,}\nМенеджер: {c['manager']}\n"
    if players:
        text+="\n⚽ Состав (FC 27):\n"+"\n".join(f"• {p['name']} — {p['position'] or '?'} · OVR {p['overall']} · {p['age'] or '?'} лет" for p in players[:30])
    else:
        text+="\nСостав ещё не импортирован. Подготовьте FC27 CSV и запустите импорт."
    xi=ml.team_sheet(c["id"])
    if xi:
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io
            # Render a clean, dynamic squad graphic based on the club's actual saved lineup.
            W,H=1100,1000
            im=Image.new("RGB",(W,H),(9,16,22)); d=ImageDraw.Draw(im)
            try:
                font=ImageFont.truetype("DejaVuSans.ttf",22)
                small=ImageFont.truetype("DejaVuSans.ttf",17)
                titlefont=ImageFont.truetype("DejaVuSans.ttf",32)
            except OSError:
                font=small=titlefont=ImageFont.load_default()
            d.rounded_rectangle((18,18,W-18,H-18),radius=22,fill=(10,19,27),outline=(38,54,62),width=2)
            d.text((42,35),c["name"],fill=(245,248,250),font=titlefont)
            d.text((44,78),"Стартовый состав",fill=(155,174,190),font=font)
            # Pitch
            L,T,R,B=40,130,760,950
            d.rounded_rectangle((L,T,R,B),radius=14,fill=(13,75,43),outline=(77,133,94),width=3)
            line=(155,190,164)
            d.rectangle((L+18,T+18,R-18,B-18),outline=line,width=2)
            d.line((L+18,(T+B)//2,R-18,(T+B)//2),fill=line,width=2)
            d.ellipse(((L+R)//2-80,(T+B)//2-80,(L+R)//2+80,(T+B)//2+80),outline=line,width=2)
            d.rectangle((L+210,T+18,R-210,T+145),outline=line,width=2)
            d.rectangle((L+210,B-145,R-210,B-18),outline=line,width=2)
            # Map positions by broad playing role; never show individual OVR ratings.
            slots={"GK":[((L+R)//2,B-85)],"DEF":[(L+115,B-235),(L+290,B-250),(L+465,B-250),(R-115,B-235)],"MID":[(L+180,(T+B)//2+35),((L+R)//2,(T+B)//2+65),(R-180,(T+B)//2+35)],"FWD":[(L+190,T+255),((L+R)//2,T+205),(R-190,T+255)]}
            groups={k:[] for k in slots}
            for player in xi:
                pos=(player.get("position") or "").upper()
                if any(x in pos for x in ("GK","POR","ВР","ВРТ")): group="GK"
                elif any(x in pos for x in ("CB","LB","RB","WB","DEF","ЗАЩ","ЦЗ","ЛЗ","ПЗ")): group="DEF"
                elif any(x in pos for x in ("CM","CDM","CAM","LM","RM","MID","ЦП","ЦОП","ЦАП","ОП")): group="MID"
                else: group="FWD"
                groups[group].append(player)
            colors={"GK":(27,145,91),"DEF":(198,42,42),"MID":(198,42,42),"FWD":(198,42,42)}
            for group,plist in groups.items():
                for idx,player in enumerate(plist[:len(slots[group])]):
                    x,y=slots[group][idx]
                    # Simple shirt marker instead of player portrait.
                    d.polygon([(x-22,y-18),(x-38,y-8),(x-28,y+7),(x-20,y+1),(x-20,y+25),(x+20,y+25),(x+20,y+1),(x+28,y+7),(x+38,y-8),(x+22,y-18),(x+12,y-11),(x-12,y-11)],fill=colors[group],outline=(235,240,242))
                    number=str(player.get("shirt_number") or player.get("number") or "•")
                    bb=d.textbbox((0,0),number,font=small)
                    d.text((x-(bb[2]-bb[0])/2,y-7),number,fill="white",font=small)
                    name=(player.get("name") or "Игрок")[:22]
                    bb=d.textbbox((0,0),name,font=small); tw=bb[2]-bb[0]
                    d.rounded_rectangle((x-tw/2-8,y+30,x+tw/2+8,y+58),radius=5,fill=(7,18,23))
                    d.text((x-tw/2,y+33),name,fill=(242,246,248),font=small)
                    role=(player.get("position") or "?")[:8]
                    rb=d.textbbox((0,0),role,font=small); rw=rb[2]-rb[0]
                    d.text((x-rw/2,y+61),role,fill=(160,184,199),font=small)
            # Right-side bench list, no player ratings.
            sx=790
            d.rounded_rectangle((sx,130,W-40,950),radius=12,fill=(12,23,31),outline=(38,54,62),width=2)
            d.text((sx+22,153),"Запасные игроки",fill=(245,248,250),font=font)
            starters={p.get("id") for p in xi}
            bench=[p for p in players if p.get("id") not in starters]
            y=205
            for player in bench[:17]:
                d.line((sx+18,y+37,W-60,y+37),fill=(36,51,60),width=1)
                d.text((sx+22,y),str(player.get("shirt_number") or player.get("number") or "—"),fill=(155,174,190),font=small)
                name=(player.get("name") or "Игрок")[:23]
                d.text((sx+65,y),name,fill=(235,241,245),font=small)
                role=(player.get("position") or "?")[:8]
                rb=d.textbbox((0,0),role,font=small); rw=rb[2]-rb[0]
                d.text((W-60-rw,y),role,fill=(60,218,153),font=small)
                y+=42
                if y>900: break
            buf=io.BytesIO(); im.save(buf,format="PNG")
            await message.answer_photo(BufferedInputFile(buf.getvalue(),filename="starting_lineup.png"),caption=f"⚽ Стартовый состав · {c['name']}\nПозиции и запасные игроки. Изменить роли: /roles")
        except ImportError:
            await message.answer(text+"\n\nДля изображения поля установите Pillow: pip install pillow")
    else:
        await message.answer(text)


@router.message(Command("squad"))
async def squad_cmd(message: Message):
    """Show the caller's squad, or search a club by its name."""
    ml.install()
    args=(message.text or "").split(maxsplit=1)
    if len(args)==1:
        club=ml.my_club(message.from_user.id)
        if not club:
            await message.answer("Сначала выберите клуб: /leagues. Либо укажите название команды: /squad Arsenal")
            return
    else:
        query=args[1].strip()
        with ml.connect() as con:
            row=con.execute("SELECT cl.*,l.name league FROM clubs cl JOIN leagues l ON l.id=cl.league_id WHERE cl.name LIKE ? COLLATE NOCASE ORDER BY CASE WHEN lower(cl.name)=lower(?) THEN 0 ELSE 1 END LIMIT 1",("%"+query+"%",query)).fetchone()
        club=dict(row) if row else None
        if not club:
            await message.answer("Команда не найдена. Проверьте название и попробуйте снова.")
            return
    players=ml.squad(club["id"])
    if not players:
        await message.answer(f"У команды {club['name']} пока нет игроков. Администратор может выполнить /mlsetup.")
        return
    lines=[f"⚽ Состав: {club['name']} · {club['league']}",f"Игроков: {len(players)}",""]
    for p in players:
        lines.append(f"#{p['id']} · {p['name']} — {p['position'] or '—'} · {p['age'] or '—'} лет · OVR {p['overall']}")
    # Telegram messages have a 4096 character limit; split long squad lists safely.
    text="\n".join(lines)
    for start in range(0,len(text),3800):
        await message.answer(text[start:start+3800])


ROLE_OPTIONS=[("ВР","Вратарь"),("ЦЗ","Центральный защитник"),("ЛЗ","Левый защитник"),("ПЗ","Правый защитник"),("ЦОП","Опорный полузащитник"),("ЦП","Центральный полузащитник"),("ЦАП","Атакующий полузащитник"),("ЛП","Левый полузащитник"),("ПП","Правый полузащитник"),("ЛФ","Левый форвард"),("ЦФ","Центральный форвард"),("ПФ","Правый форвард")]

@router.message(Command("roles"))
async def roles_cmd(message: Message):
    club=ml.my_club(message.from_user.id)
    if not club:
        await message.answer("Сначала выберите клуб: /leagues"); return
    players=ml.squad(club["id"])
    if not players:
        await message.answer("Состав не загружен. Импортируйте CSV с игроками FC 27."); return
    rows=[[InlineKeyboardButton(text=f"{p['name']} · {p['position'] or 'роль не задана'} · OVR {p['overall']}",callback_data=f"ml:roleplayer:{p['id']}")] for p in players[:50]]
    await message.answer(f"🧑‍💼 Управление ролями — {club['name']}\nВы — директор клуба. Выберите игрока, чтобы изменить его игровую позицию:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("ml:roleplayer:"))
async def role_player_cb(call: CallbackQuery):
    pid=int(call.data.rsplit(":",1)[1])
    club=ml.my_club(call.from_user.id)
    if not club or not any(p['id']==pid for p in ml.squad(club['id'])):
        await call.answer("Менять роли может только директор своего клуба.",show_alert=True); return
    rows=[]
    for code,label in ROLE_OPTIONS:
        rows.append([InlineKeyboardButton(text=f"{label} ({code})",callback_data=f"ml:setrole:{pid}:{code}")])
    await call.message.answer("Выберите новую роль футболиста:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()

@router.callback_query(F.data.startswith("ml:setrole:"))
async def set_role_cb(call: CallbackQuery):
    _,_,pid,role=call.data.split(":")
    ok,msg=ml.set_player_position(call.from_user.id,int(pid),role)
    await call.answer("Роль обновлена" if ok else msg,show_alert=not ok)
    if ok:
        await call.message.answer("✅ "+msg+"\nИзменение сохранено и будет использоваться в составе. Посмотреть команду: /myteam · Изменить роли: /roles")

@router.message(Command("coaches"))
async def coaches_cmd(message: Message):
    c=ml.my_club(message.from_user.id)
    if not c:
        await message.answer("Сначала выберите клуб: /leagues");return
    hired=ml.hired_coaches(c["id"])
    rows=[[InlineKeyboardButton(text=f"{co['name']} · €{co['price']:,} · уровень {co['skill']}/5",callback_data=f"ml:hire:{co['id']}")] for co in ml.coach_catalog()]
    await message.answer(f"🧑‍🏫 Тренеры клуба: {len(hired)}/5\n"+("\n".join(f"• {x['name']} (ур. {x['skill']}/5)" for x in hired) or "Пока тренеров нет.")+"\n\nВыберите тренера для найма:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.message(Command("training"))
async def training_cmd(message: Message):
    c=ml.my_club(message.from_user.id)
    if not c:
        await message.answer("Сначала выберите клуб: /leagues");return
    players=ml.squad(c["id"])
    if not players:
        await message.answer("Состав не загружен. Сначала импортируйте CSV с рейтингами FC 27.");return
    rows=[]
    for pl in players[:30]:
        rows.append([InlineKeyboardButton(text=f"{pl['name']} · OVR {pl['overall']}",callback_data=f"ml:player:{pl['id']}")])
    await message.answer("🏋️ Выберите игрока для тренировки:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("ml:hire:"))
async def hire_cb(call: CallbackQuery):
    ok,msg=ml.hire_coach(call.from_user.id,int(call.data.rsplit(":",1)[1]))
    await call.answer(msg,show_alert=True)
    if ok: await call.message.answer(msg+"\nТренеры повышают скорость прокачки. /coaches — список, /training — тренировка.")

@router.callback_query(F.data.startswith("ml:player:"))
async def training_player_cb(call: CallbackQuery):
    pid=int(call.data.rsplit(":",1)[1])
    rows=[[InlineKeyboardButton(text=f"{plan['name']} · скорость {plan['base_gain']}",callback_data=f"ml:plan:{pid}:{plan['id']}")] for plan in ml.training_plan_catalog()]
    await call.message.answer("Выберите шаблон тренировки:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()

@router.callback_query(F.data.startswith("ml:plan:"))
async def training_plan_cb(call: CallbackQuery):
    _,_,pid,planid=call.data.split(":")
    ok,msg=ml.train_player(call.from_user.id,int(pid),int(planid))
    await call.answer("Тренировка выполнена" if ok else "Не удалось",show_alert=not ok)
    await call.message.answer(("✅ " if ok else "⚠️ ")+msg)

@router.message(Command("mltable"))
async def mltable_cmd(message: Message):
    rows=[[InlineKeyboardButton(text=l["name"],callback_data=f"ml:table:{l['id']}")] for l in ml.league_list()]
    await message.answer("📊 Выберите чемпионат:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.message(Command("mlcalendar"))
async def mlcalendar_cmd(message: Message):
    events=ml.calendar()
    if not events:
        ml.seed_calendar(); events=ml.calendar()
    await message.answer("📅 Календарь сезона:\n"+"\n".join(f"{e['event_date']} — {e['title']}" for e in events))

@router.message(Command("mlround"))
async def mlround_cmd(message: Message):
    if message.chat.type not in ("group","supergroup"):
        await message.answer("Запускайте тур в группе, чтобы результаты увидели все участники.")
        return
    member=await message.bot.get_chat_member(message.chat.id,message.from_user.id)
    if member.status not in ("creator","administrator"):
        await message.answer("Следующий тур может запустить только администратор группы.")
        return
    leagues=ml.league_list()
    lines=[]
    for l in leagues:
        with ml.connect() as c:
            row=c.execute("SELECT COALESCE(MAX(round_no),0) r FROM fixtures WHERE league_id=? AND season=? AND played=1",(l["id"],l["season"])).fetchone()
            next_round=int(row["r"])+1
        results=ml.play_round(l["id"],next_round,l["season"])
        if results:
            lines.append(f"\n🏆 {l['name']} · тур {next_round}")
            lines.extend(f"{r['home']} {r['score']} {r['away']}" for r in results)
    await message.answer("⚽ Результаты тура:\n"+"\n".join(lines) if lines else "Все матчи сезона уже сыграны.")

@router.callback_query(F.data=="ml:leagues")
async def ml_leagues_cb(call: CallbackQuery):
    await call.message.answer("🌍 Выберите лигу:",reply_markup=_league_keyboard())
    await call.answer()

@router.callback_query(F.data.startswith("ml:league:"))
async def ml_league_cb(call: CallbackQuery):
    league_id=int(call.data.rsplit(":",1)[1])
    l=next((x for x in ml.league_list() if x["id"]==league_id),None)
    if not l:
        await call.answer("Лига не найдена",show_alert=True);return
    await call.message.answer(f"🏆 {l['name']}\nСвободные клубы — выберите команду:",reply_markup=_clubs_keyboard(league_id))
    await call.answer()

@router.callback_query(F.data.startswith("ml:claim:"))
async def ml_claim_cb(call: CallbackQuery):
    club_id=int(call.data.rsplit(":",1)[1])
    ok,msg=ml.claim_club(call.from_user.id,call.from_user.full_name or call.from_user.username or str(call.from_user.id),club_id)
    await call.answer(msg,show_alert=not ok)
    if ok:
        c=ml.my_club(call.from_user.id)
        await call.message.answer(f"✅ {msg}\n🏟 {c['name']} — {c['league']}\nБюджет: €{c['budget']:,}\nКоманды: /myteam · /roles · /mltable · /mlcalendar")
    else:
        await call.message.answer("Если клуб уже занят, выберите другую команду через /leagues.")

@router.callback_query(F.data.startswith("ml:table:"))
async def ml_table_cb(call: CallbackQuery):
    league_id=int(call.data.rsplit(":",1)[1])
    l=next((x for x in ml.league_list() if x["id"]==league_id),None)
    if not l:
        await call.answer("Лига не найдена",show_alert=True);return
    rows=ml.table(league_id,l["season"])
    text=[f"📊 {l['name']} · сезон {l['season']}","Поз И Клуб И В Н П Мячи О"]
    for i,r in enumerate(rows,1):
        text.append(f"{i}. {r['name']} · {r['p']} {r['w']} {r['d']} {r['l']} {r['gf']}:{r['ga']} {r['pts']}")
    await call.message.answer("\\n".join(text))
    await call.answer()


# Calendar command: upcoming and completed fixtures with results.
@router.message(Command("calendar"))
async def calendar_cmd(message: Message):
    ml.install()
    with ml.connect() as con:
        rows = con.execute("""
            SELECT f.match_date, f.round_no, f.played, f.home_goals, f.away_goals,
                   h.name AS home_name, a.name AS away_name, l.name AS league_name
            FROM fixtures f
            JOIN clubs h ON h.id=f.home_id
            JOIN clubs a ON a.id=f.away_id
            JOIN leagues l ON l.id=f.league_id
            WHERE f.season='2026/27'
            ORDER BY CASE WHEN f.played=0 THEN 0 ELSE 1 END,
                     COALESCE(f.match_date, '9999-12-31'), l.name, f.round_no
            LIMIT 18
        """).fetchall()
    if not rows:
        await message.answer("📅 Календарь пока пуст. Сначала подготовьте сезон командой /mlsetup.")
        return
    lines = ["📅 КАЛЕНДАРЬ МАТЧЕЙ · СЕЗОН 2026/27", ""]
    last_date = None
    for r in rows:
        d = r["match_date"] or "Дата не назначена"
        if d != last_date:
            lines.append(f"🗓 {d}")
            last_date = d
        status = (f"{r['home_goals']} : {r['away_goals']}" if r["played"] else "— : —")
        mark = "✅" if r["played"] else "⏳"
        lines.append(f"{mark} {r['league_name']} · Тур {r['round_no']}")
        lines.append(f"   {r['home_name']}  **{status}**  {r['away_name']}")
    lines += ["", "ℹ️ Завершённые матчи показывают сохранённый счёт. Национальные лиги и еврокубки симулируются отдельно."]
    await message.answer("\n".join(lines), parse_mode="Markdown")



@router.message(Command("setleader"))
async def setleader_cmd(message: Message):
    """Admin assigns a club to the user whose message is being replied to.
    Usage: reply to a user's message with /setleader Arsenal
    """
    ml.install()
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Использование: ответь на сообщение игрока командой /setleader Название клуба")
        return
    if not message.from_user:
        return
    # Only group administrators may assign club leadership.
    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in ("administrator", "creator"):
            await message.answer("⛔ Назначать директоров могут только администраторы группы.")
            return
    except Exception:
        await message.answer("Не удалось проверить права администратора в этой группе.")
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Укажи клуб. Пример: /setleader Arsenal — ответом на сообщение игрока.")
        return
    club_name = args[1].strip()
    target = message.reply_to_message.from_user
    display_name = target.full_name or target.username or str(target.id)
    with ml.connect() as con:
        clubs = con.execute(
            "SELECT c.id,c.name,l.name AS league FROM clubs c JOIN leagues l ON l.id=c.league_id WHERE lower(c.name)=lower(?)",
            (club_name,)
        ).fetchall()
        if not clubs:
            await message.answer(f"Клуб «{club_name}» не найден. Сначала запусти /mlsetup и проверь название.")
            return
        if len(clubs) > 1:
            await message.answer("Нашлось несколько клубов с таким названием. Укажи более точное название.")
            return
        club = clubs[0]
        con.execute("BEGIN IMMEDIATE")
        current = con.execute("SELECT club_id FROM managers WHERE user_id=?", (target.id,)).fetchone()
        occupied = con.execute("SELECT user_id FROM managers WHERE club_id=? AND user_id<>?", (club["id"], target.id)).fetchone()
        if occupied:
            con.rollback()
            await message.answer(f"⛔ Клуб {club['name']} уже назначен другому директору.")
            return
        if current and current["club_id"] is not None and current["club_id"] != club["id"]:
            con.rollback()
            await message.answer("⛔ У этого игрока уже есть клуб. Сначала нужно снять старое назначение.")
            return
        con.execute(
            "INSERT INTO managers(user_id,display_name,club_id) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name,club_id=excluded.club_id",
            (target.id, display_name, club["id"])
        )
    await message.answer(f"✅ Директор назначен!\n🏟 Клуб: {club['name']}\n🏆 Лига: {club['league']}\n👤 Директор: {display_name}")
