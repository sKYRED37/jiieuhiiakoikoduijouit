"""Групповой Telegram-интерфейс виртуальной футбольной лиги для aiogram 3.x.

В группе каждый Telegram-пользователь управляет одним клубом.
Автоматический тур симулируется один раз и публикуется в тот же чат.
"""
import asyncio
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import career
import career_expansion as cx

router = Router()
_round_lock = asyncio.Lock()


def _manager(event):
    return career.get_manager(event.from_user.id)


def _club_id(event):
    m = _manager(event)
    return m["club_id"] if m and m["club_id"] and not m["sacked"] else None


def _group_message(message):
    return message.chat.type in ("group", "supergroup")


async def _is_group_admin(message: Message) -> bool:
    if not _group_message(message):
        return False
    member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in ("creator", "administrator")


def _main_menu_text():
    return (
        "⚽ Виртуальная футбольная лига\n\n"
        "Каждый участник группы управляет своим клубом.\n"
        "Матчи симулируются автоматически: состав, рейтинг игроков, форма и тактика "
        "влияют на результат.\n\nВыберите действие кнопками ниже."
    )


@router.message(CommandStart())
async def start(message: Message):
    user = message.from_user
    career.register_manager(user.id, user.full_name or user.username or str(user.id))
    await message.answer(_main_menu_text(), reply_markup=cx.main_keyboard())
    if not _club_id(message):
        offers = career.job_offers(user.id)
        buttons = [
            [InlineKeyboardButton(text=f"🏟 {c['name']} · рейтинг {c['rep']}",
                                  callback_data=f"job:{c['id']}")]
            for c in offers[:20]
        ]
        if buttons:
            await message.answer("Выберите клуб, которым будете управлять:", 
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(Command("club"))
@router.message(F.text == "🏟 Мой клуб")
async def my_club(message: Message):
    cid = _club_id(message)
    if not cid:
        await message.answer("У вас пока нет клуба. Нажмите /start и выберите свободную команду.")
        return
    x = career.club_overview(cid)
    c, nxt = x["club"], x["next"]
    next_text = "нет ближайшего матча" if not nxt else f"тур {nxt['md']}"
    await message.answer(
        f"🏟 {c['name']}\nПозиция: {x['position']}\n"
        f"Сезон {x['season']} · тур {x['md']}/{x['total']}\n"
        f"Средний рейтинг состава: {x['avg_ovr']}\n"
        f"Бюджет: €{x['finance']['budget']} тыс.\nСледующий матч: {next_text}",
        reply_markup=cx.main_keyboard()
    )


@router.callback_query(F.data.startswith("job:"))
async def choose_job(call: CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    ok, msg = career.take_job(call.from_user.id, cid)
    await call.answer(msg, show_alert=not ok)
    if ok:
        await call.message.answer(f"✅ {msg}\nТеперь вы можете управлять клубом через меню.")
    else:
        await call.message.answer(f"❌ {msg}")


@router.message(Command("table"))
@router.message(F.text == "📊 Таблица")
async def table_menu(message: Message):
    rows = career.table()
    lines = [f"📊 Чемпионат · сезон {career.season()} · тур {max(0, career.matchday()-1)}"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['name']} — {r['pts']} оч. | {r['p']} игр | мячи {r['gf']}:{r['ga']} ({r['gd']:+})")
    await message.answer("\n".join(lines))


@router.message(F.text == "⚽ Состав")
async def squad_menu(message: Message):
    cid = _club_id(message)
    if not cid:
        await message.answer("Сначала выберите клуб через /start.")
        return
    players = career.squad(cid)
    lines = [f"⚽ Состав «{career.club(cid)['name']}»:"]
    for p in players:
        injured = f" 🩹 травма: {p['injury']} тур." if p["injury"] else ""
        lines.append(f"• {p['name']} — {p['pos']} · OVR {p['ovr']} · {p['age']} лет · форма {p['form']}{injured}")
    await message.answer("\n".join(lines[:33]))


@router.message(F.text == "🧠 Тактика")
async def tactics_menu(message: Message):
    cid = _club_id(message)
    if not cid:
        await message.answer("Сначала выберите клуб.")
        return
    import engine as E
    c = career.club(cid)
    buttons = []
    row = []
    for formation in E.FORMATIONS:
        row.append(InlineKeyboardButton(text=formation, callback_data=f"tactic:{formation}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons += [[
        InlineKeyboardButton(text="⚔️ Атака", callback_data="mental:attack"),
        InlineKeyboardButton(text="⚖️ Баланс", callback_data="mental:balanced"),
        InlineKeyboardButton(text="🛡 Защита", callback_data="mental:defend"),
    ]]
    await message.answer(
        f"🧠 Тактика «{c['name']}»\nСхема: {c['formation']}\nМенталитет: {E.MENTALITY_RU[c['mentality']]}\nВыберите изменение:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("tactic:"))
async def set_formation(call: CallbackQuery):
    cid = _club_id(call)
    if not cid:
        await call.answer("Сначала выберите клуб через /start", show_alert=True)
        return
    ok, msg = career.set_tactics(cid, formation=call.data.split(":", 1)[1])
    await call.answer(msg, show_alert=not ok)
    await call.message.answer(msg)


@router.callback_query(F.data.startswith("mental:"))
async def set_mentality(call: CallbackQuery):
    cid = _club_id(call)
    if not cid:
        await call.answer("Сначала выберите клуб через /start", show_alert=True)
        return
    ok, msg = career.set_tactics(cid, mentality=call.data.split(":", 1)[1])
    await call.answer(msg, show_alert=not ok)
    await call.message.answer(msg)


@router.message(F.text == "🏋️ Тренировки")
async def training_menu(message: Message):
    cid = _club_id(message)
    if not cid:
        await message.answer("Сначала выберите клуб.")
        return
    ok, msg = career.train(cid)
    await message.answer(("🏋️ " if ok else "⚠️ ") + msg)


@router.message(F.text == "💶 Финансы")
async def finances_menu(message: Message):
    cid = _club_id(message)
    if not cid:
        await message.answer("Сначала выберите клуб.")
        return
    f = career.finance_report(cid)
    await message.answer(
        f"💶 Финансы «{career.club(cid)['name']}»\n"
        f"Бюджет: €{f['budget']} тыс.\nЗарплаты в неделю: €{f['wages']} тыс.\n"
        f"Доход в неделю: €{f['income']} тыс.\nБаланс недели: €{f['net_week']} тыс."
    )


@router.message(F.text == "📅 Календарь")
async def calendar_menu(message: Message):
    await message.answer("📅 Календарь игрового сезона", reply_markup=cx.calendar_keyboard())


@router.callback_query(F.data.startswith("cal:"))
async def calendar_callback(call: CallbackQuery):
    mode = call.data.split(":", 1)[1]
    if mode == "summer":
        rows = [e for e in cx.calendar(career.season()) if e["event_key"].startswith("summer")]
    elif mode == "winter":
        rows = [e for e in cx.calendar(career.season()) if e["event_key"].startswith("winter")]
    elif mode == "europe":
        rows = cx.calendar(career.season(), "europe")
    else:
        rows = cx.calendar(career.season())
    await call.message.answer(cx.format_events(rows).replace("\\n", "\n"))
    await call.answer()


@router.message(F.text == "🏆 Турниры")
async def tournaments_menu(message: Message):
    await message.answer("🏆 Европейские турниры (пока календарь и каталог)", reply_markup=cx.tournaments_keyboard())


@router.callback_query(F.data.startswith("cup:"))
async def competition_callback(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    rows = [r for r in cx.competitions(career.season()) if r["code"] == code]
    await call.message.answer(cx.format_competitions(rows).replace("\\n", "\n"))
    await call.answer()


@router.message(F.text == "🌍 Европейские лиги")
async def leagues_menu(message: Message):
    await message.answer(cx.format_leagues().replace("\\n", "\n"))


@router.message(F.text == "🔁 Трансферы")
async def transfer_menu(message: Message):
    await message.answer(
        "🔁 Трансферный центр\n"
        "В движке доступны поиск игроков, рынок, ставки, переговоры о зарплате, "
        "продажа и свободные агенты. Интерфейс сделок подключим следующим этапом."
    )


@router.message(F.text == "❓ Помощь")
async def help_menu(message: Message):
    await message.answer(
        "Команды:\n/start — регистрация и выбор клуба\n/club — мой клуб\n/table — таблица\n"
        "▶️ Следующий тур — только администратор группы\n\n"
        "Матчи проходят автоматически. Перед туром настройте состав и тактику. "
        "Нажатие кнопки тура симулирует матчи всех клубов ровно один раз."
    )


@router.message(Command("next"))
@router.message(F.text == "▶️ Следующий тур")
async def next_round(message: Message):
    if not _group_message(message):
        await message.answer("Запускайте тур из группового чата лиги.")
        return
    if not await _is_group_admin(message):
        await message.answer("⛔ Следующий тур может запускать только администратор группы.")
        return
    async with _round_lock:
        result = career.play_matchday()
    lines = [f"⚽ ИТОГИ ТУРА {result['md']} · СЕЗОН {result['season']}"]
    if not result["results"]:
        lines.append("На этот тур нет несыгранных матчей. Проверьте календарь лиги.")
    for r in result["results"]:
        lines.append(f"{r['home']} {r['hg']}:{r['ag']} {r['away']}")
        if r.get("best"):
            lines.append(f"   ⭐ Игрок матча: {r['best']['name']} ({r['best']['rating']:.1f})")
    if result.get("injuries"):
        lines.append("\n🩹 Травмы:")
        for injury in result["injuries"]:
            lines.append(f"• {injury['name']} — {injury['games']} тур. ({injury['reason']})")
    if result.get("sacked"):
        lines.append("\n🚨 Увольнения:")
        for item in result["sacked"]:
            lines.append(f"• {item['club']}: {item['reason']}")
    if result.get("season_end"):
        end = result["season_end"]
        lines.append(f"\n🏆 ЧЕМПИОН СЕЗОНА: {end['champion']}")
        if end.get("top_scorer"):
            lines.append(f"🥇 Лучший бомбардир: {end['top_scorer']}")
        cx.create_season_calendar(career.season())
    await message.answer("\n".join(lines))


@router.message(Command("league"))
async def league_info(message: Message):
    await message.answer(
        f"⚽ Виртуальная лига\nСезон: {career.season()}\n"
        f"Текущий тур: {career.matchday()} из {career.total_mds()}\n"
        f"Менеджеров с клубами: {len([m for m in career.table() if m])}"
    )
