Set BOT_TOKEN in the hosting panel environment variables.
"""
import asyncio
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

import career_multileague as ml
from admin_auth import configured_admin_ids
import career_economy as eco
from career_multileague_ui import router as multileague_router
from career_economy_ui import router as economy_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
help_router = Router(name="help")

@help_router.message(Command("start", "help", "commands"))
async def help_command(message: Message):
    await message.answer(
        "⚽ FOOTBALL MANAGER — команды\n\n"
        "🏟 Клубы и составы\n"
        "/leagues — выбрать клуб из 7 лиг\n"
        "/myteam — мой клуб и стартовый состав\n"
        "/squad — состав моего клуба; /squad Arsenal — состав указанной команды\n"
        "/roles — изменить роли игроков\n"
        "/teamprofile — трофеи и призовые моей команды\n\n"
        "📊 Матчи и таблицы\n"
        "/mlsetup — подготовить 7 лиг и составы (администратор)\n"
        "/mlround — сыграть следующий тур (администратор)\n"
        "/mltable — таблица лиги\n"
        "/mlcalendar или /calendar — календарь\n\n"
        "👤 Игроки\n"
        "/playerprofile имя_или_ID — профиль, голы, ассисты, оценки\n"
        "/playerstats — рейтинг игроков\n"
        "/goldenball 2026/27 — выдать Золотой мяч (администратор)\n\n"
        "💶 Менеджмент и сезоны\n"
        "/market — рынок игроков\n"
        "/transfer — трансферы\n"
        "/contracts — контракты\n"
        "/training — тренировки\n"
        "/coaches — тренеры\n"
        "/cups — кубковые турниры\n"
        "/finishcup ЛЧ 2026/27 — завершить кубок (администратор)\n"
        "/finishseason ID_лиги 2026/27 — завершить одну лигу\n"
        "/finishallleagues 2026/27 — завершить все 7 лиг\n\n"
        "Админ-доступ: ADMIN_IDS в переменных окружения (ID через запятую) или статус администратора Telegram-группы."
    )

async def main():
    token=os.getenv("8873900600:AAGHv3MAfUFAXefu8k1q2r_fcIfPIH316Iw", "").strip()
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN. Укажите токен бота в переменных окружения Bothost.")
    logging.info("Configured admin IDs: %s", sorted(configured_admin_ids()))
    ml.install()
    eco.install()
    transfermarkt_csv = os.path.join(os.path.dirname(__file__), "transfermarkt_players.csv")
    if os.path.isfile(transfermarkt_csv):
        result = ml.import_transfermarkt_csv(transfermarkt_csv, clear_existing=False)
        logging.info("Transfermarkt roster import: %s; unmatched clubs: %s", result["imported"], len(result["unmatched_clubs"]))
    generated=ml.seed_generated_squads()
    ml.seed_calendar()
    # Create schedules only if the season has not been generated yet. Never reset played fixtures.
    for league in ml.league_list():
        with ml.connect() as con:
            exists=con.execute("SELECT 1 FROM fixtures WHERE league_id=? AND season=? LIMIT 1",(league["id"],league["season"])).fetchone()
        if not exists:
            ml.generate_fixtures(league["id"], league["season"])
    logging.info("Database ready; generated %s player records", generated)
    bot=Bot(token=token)
    dp=Dispatcher()
    dp.include_router(help_router)
    # Economy router first because it contains the richer /mlround selector; it must win over legacy handler.
    dp.include_router(economy_router)
    dp.include_router(multileague_router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__=="__main__":
    asyncio.run(main())
