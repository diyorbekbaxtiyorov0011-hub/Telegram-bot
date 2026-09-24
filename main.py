import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().with_name(".env"), override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
RAW_GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.6-flash").strip()
GEMINI_MODEL = RAW_GEMINI_MODEL if RAW_GEMINI_MODEL.startswith("gemini-") else "gemini-3.6-flash"
GEMINI_FALLBACK_MODELS = tuple(
    dict.fromkeys(
        [
            GEMINI_MODEL,
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
        ]
    )
)
gemini_session: aiohttp.ClientSession | None = None

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN .env faylida ko'rsatilmagan")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = Router()


class BroadcastState(StatesGroup):
    waiting_for_message = State()


class ContentState(StatesGroup):
    waiting_for_section = State()
    waiting_for_text = State()


class GeminiState(StatesGroup):
    chatting = State()


DEFAULT_CONTENT = {
    "portfolio": "Portfolio bo'limi tez orada to'ldiriladi.",
    "services": "Xizmatlar bo'limi tez orada to'ldiriladi.",
    "contact": "Aloqa uchun: @your_username",
}


def init_db() -> None:
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                section TEXT PRIMARY KEY,
                text TEXT NOT NULL
            )
            """
        )
        for section, text in DEFAULT_CONTENT.items():
            connection.execute(
                "INSERT OR IGNORE INTO content (section, text) VALUES (?, ?)",
                (section, text),
            )
        connection.commit()


def save_user(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, username, first_name, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (
                user.id,
                user.username,
                user.first_name,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()


def get_user_ids() -> list[int]:
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        rows = connection.execute("SELECT user_id FROM users").fetchall()
    return [row[0] for row in rows]


def get_user_count() -> int:
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get_content(section: str) -> str:
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        row = connection.execute(
            "SELECT text FROM content WHERE section = ?", (section,)
        ).fetchone()
    return row[0] if row else DEFAULT_CONTENT[section]


def update_content(section: str, text: str) -> None:
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO content (section, text) VALUES (?, ?)",
            (section, text),
        )
        connection.commit()


def is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id == ADMIN_ID


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Portfolio"), KeyboardButton(text="Xizmatlar")],
            [KeyboardButton(text="Aloqa")],
            [KeyboardButton(text="Gemini bilan suhbat")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Statistika"), KeyboardButton(text="Broadcast")],
            [KeyboardButton(text="Kontentni tahrirlash")],
            [KeyboardButton(text="Bekor qilish")],
        ],
        resize_keyboard=True,
    )


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    save_user(message)
    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}!\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_keyboard(),
    )


@router.message(Command("ai"))
@router.message(F.text == "Gemini bilan suhbat")
async def gemini_start_handler(message: Message, state: FSMContext) -> None:
    if not GEMINI_API_KEY:
        await message.answer(
            "Gemini hali sozlanmagan. Admin GEMINI_API_KEY qiymatini .env fayliga kiritsin."
        )
        return
    await state.set_state(GeminiState.chatting)
    await state.update_data(history=[])
    await message.answer(
        "Gemini bilan suhbat boshlandi. Savolingizni yozing.\n"
        "Suhbatni tugatish uchun /stop_ai yuboring."
    )


@router.message(Command("stop_ai"), GeminiState.chatting)
async def gemini_stop_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Gemini suhbati tugatildi.", reply_markup=main_keyboard())


async def ask_gemini(history: list[dict[str, object]]) -> str:
    payload = {
        "contents": history[-6:],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.4,
            "candidateCount": 1,
        },
    }
    global gemini_session
    if gemini_session is None or gemini_session.closed:
        timeout = aiohttp.ClientTimeout(total=8, connect=2)
        gemini_session = aiohttp.ClientSession(timeout=timeout)

    errors = []
    for model_index, model in enumerate(GEMINI_FALLBACK_MODELS):
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_API_KEY}"
        )
        try:
            async with gemini_session.post(url, json=payload) as response:
                response_data = await response.json(content_type=None)
            if response.status == 200:
                try:
                    return response_data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError, TypeError) as error:
                    errors.append(f"{model}: javob formati xato ({error})")
                    break

            error = response_data.get("error", {}).get("message", "Noma'lum xato")
            errors.append(f"{model}: {error}")
            logger.warning("Gemini %s xato berdi (%s): %s", model, response.status, error)
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            errors.append(f"{model}: {error}")
            logger.warning("Gemini %s ulanib bo'lmadi: %s", model, error)

    raise RuntimeError("Gemini hozircha band yoki API limiti tugagan. Qayta urinib ko'ring.")


@router.message(GeminiState.chatting)
async def gemini_message_handler(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer("Iltimos, matnli xabar yuboring.")
        return

    data = await state.get_data()
    history = data.get("history", [])
    history.append({"role": "user", "parts": [{"text": user_text}]})
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        answer = await ask_gemini(history)
    except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as error:
        history.pop()
        await state.update_data(history=history)
        await message.answer(f"Gemini bilan bog'lanishda xatolik: {error}")
        return

    history.append({"role": "model", "parts": [{"text": answer}]})
    await state.update_data(history=history[-6:])
    await message.answer(answer)


@router.message(Command("admin"))
async def admin_handler(message: Message) -> None:
    if not is_admin(message):
        await message.answer("Bu buyruq faqat administrator uchun.")
        return
    await message.answer("Admin paneliga xush kelibsiz.", reply_markup=admin_keyboard())


@router.message(F.text == "Statistika")
async def statistics_handler(message: Message) -> None:
    if not is_admin(message):
        return
    await message.answer(f"A'zolar soni: {get_user_count()} ta")


@router.message(F.text == "Broadcast")
async def broadcast_start_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message):
        return
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer(
        "Barcha foydalanuvchilarga yuboriladigan xabarni kiriting.\n"
        "Bekor qilish uchun /cancel yuboring."
    )


@router.message(Command("cancel"), BroadcastState.waiting_for_message)
@router.message(F.text == "Bekor qilish", BroadcastState.waiting_for_message)
async def cancel_broadcast_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Broadcast bekor qilindi.", reply_markup=admin_keyboard())


@router.message(BroadcastState.waiting_for_message)
async def broadcast_send_handler(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message):
        await state.clear()
        return

    user_ids = get_user_ids()
    sent_count = 0
    failed_count = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, message.text or "")
            sent_count += 1
        except Exception as error:
            failed_count += 1
            logger.warning("Xabar yuborilmadi (%s): %s", user_id, error)

    await state.clear()
    await message.answer(
        f"Broadcast yakunlandi.\nYuborildi: {sent_count}\n"
        f"Yuborilmadi: {failed_count}",
        reply_markup=admin_keyboard(),
    )


@router.message(F.text == "Kontentni tahrirlash")
async def content_edit_start_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message):
        return
    await state.set_state(ContentState.waiting_for_section)
    await message.answer(
        "Qaysi bo'lim matnini o'zgartiramiz?\n"
        "1 - Portfolio\n2 - Xizmatlar\n3 - Aloqa\n\n"
        "Bekor qilish uchun /cancel yuboring."
    )


@router.message(Command("cancel"), ContentState.waiting_for_section)
@router.message(Command("cancel"), ContentState.waiting_for_text)
@router.message(F.text == "Bekor qilish", ContentState.waiting_for_section)
@router.message(F.text == "Bekor qilish", ContentState.waiting_for_text)
async def cancel_content_edit_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Tahrirlash bekor qilindi.", reply_markup=admin_keyboard())


@router.message(ContentState.waiting_for_section)
async def content_section_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message):
        await state.clear()
        return

    section_map = {
        "1": ("portfolio", "Portfolio"),
        "2": ("services", "Xizmatlar"),
        "3": ("contact", "Aloqa"),
        "Portfolio": ("portfolio", "Portfolio"),
        "Xizmatlar": ("services", "Xizmatlar"),
        "Aloqa": ("contact", "Aloqa"),
    }
    selected = section_map.get(message.text or "")
    if selected is None:
        await message.answer("Iltimos, 1, 2, 3 yoki bo'lim nomini yuboring.")
        return

    section, title = selected
    await state.update_data(section=section)
    await state.set_state(ContentState.waiting_for_text)
    await message.answer(
        f"{title} uchun yangi matnni yuboring.\n\n"
        f"Hozirgi matn:\n{get_content(section)}"
    )


@router.message(ContentState.waiting_for_text)
async def content_text_handler(message: Message, state: FSMContext) -> None:
    if not is_admin(message):
        await state.clear()
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Matn bo'sh bo'lmasligi kerak. Qayta yuboring.")
        return

    data = await state.get_data()
    update_content(data["section"], new_text)
    await state.clear()
    await message.answer("Ma'lumot muvaffaqiyatli o'zgartirildi.", reply_markup=admin_keyboard())


@router.message(F.text == "Portfolio")
async def portfolio_handler(message: Message) -> None:
    await message.answer(get_content("portfolio"))


@router.message(F.text == "Xizmatlar")
async def services_handler(message: Message) -> None:
    await message.answer(get_content("services"))


@router.message(F.text == "Aloqa")
async def contact_handler(message: Message) -> None:
    await message.answer(get_content("contact"))


async def main() -> None:
    init_db()
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    health_app = web.Application()

    async def health_check(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    health_app.router.add_get("/", health_check)
    health_app.router.add_get("/healthz", health_check)
    health_runner = web.AppRunner(health_app)
    await health_runner.setup()
    health_site = web.TCPSite(
        health_runner,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
    )
    await health_site.start()
    logger.info("Bot ishga tushmoqda...")
    try:
        await dispatcher.start_polling(bot)
    finally:
        if gemini_session is not None and not gemini_session.closed:
            await gemini_session.close()
        await health_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
