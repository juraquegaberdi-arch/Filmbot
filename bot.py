"""\
Yashil menyuli Telegram kino bot — Python 3.10+, Aiogram 3.x, SQLite.

Kutubxonalar: python -m pip install -r requirements.txt
Xavfsiz sozlash: BOT_TOKEN va OWNER_IDS muhit o'zgaruvchilarini kiriting.
Token yoki UID kod ichida saqlanmaydi.
"""

import asyncio
import html
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# --------------------------- Bot sozlamalari ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_IDS_RAW = os.getenv("OWNER_IDS", "")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip()
SUBSCRIPTION_URL = os.getenv("SUBSCRIPTION_URL", "").strip()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "kino_bot.sqlite3"))
LOG_PATH = os.getenv("LOG_PATH", os.path.join(BASE_DIR, "bot.log"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("green_kino_bot")


def parse_ids(raw: str) -> set[int]:
    result: set[int] = set()
    for part in raw.split(","):
        try:
            if part.strip():
                result.add(int(part.strip()))
        except ValueError:
            log.warning("OWNER_IDS ichida noto'g'ri ID bor; e'tiborsiz qoldirildi")
    return result


OWNER_IDS = parse_ids(OWNER_IDS_RAW)
router = Router()
dp = Dispatcher()
dp.include_router(router)
# Faqat joriy suhbat bosqichlari xotirada turadi. Kino, foydalanuvchi va sozlamalar SQLite'da.
states: dict[int, dict[str, Any]] = {}

# Inline tugmalardagi success uslubi qo'llab-quvvatlanadigan Telegram ilovalarida yashil rang beradi.
GREEN = "success"
BLUE = "primary"
RED = "danger"


def button(text: str, data: str, style: str = GREEN) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def home_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [button("🎬 Kino izlash", "user:search"), button("🔥 Mashhur", "user:popular")],
        [button("📊 Statistika", "user:stats"), button("📞 Admin bilan aloqa", "user:contact")],
    ]
    if is_admin(user_id):
        rows.append([button("🛠 Admin panel", "admin:home")])
    if is_owner(user_id):
        rows.append([button("👑 Owner panel", "owner:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("➕ Kino qo‘shish", "admin:add"), button("🗑 Kino o‘chirish", "admin:delete", RED)],
        [button("✏️ Kino tahrirlash", "admin:edit"), button("📋 Kinolar", "admin:list")],
        [button("📊 Statistika", "admin:stats")],
        [button("🏠 Asosiy menyu", "user:home", BLUE)],
    ])


def owner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("🎉 Start salomini sozlash", "owner:welcome")],
        [button("📣 Foydalanuvchilarga xabar yuborish", "owner:broadcast")],
        [button("👮 Adminlarni boshqarish", "owner:admins")],
        [button("👥 Foydalanuvchilar ro‘yxati", "owner:users"), button("📊 Statistika", "owner:stats")],
        [button("💾 Bazani zaxiralash", "owner:backup", BLUE)],
        [button("🏠 Asosiy menyu", "user:home", BLUE)],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button("❌ Bekor qilish", "flow:cancel", RED)]])


def subscription_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    url = SUBSCRIPTION_URL
    if not url and REQUIRED_CHANNEL.startswith("@"):
        url = "https://t.me/" + REQUIRED_CHANNEL[1:]
    if url.startswith(("https://", "http://")):
        rows.append([InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=url, style=GREEN)])
    rows.append([button("✅ Obunani tekshirish", "sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT NOT NULL DEFAULT '',
            joined_at TEXT NOT NULL, last_seen TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS movies (
            code INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            file_id TEXT NOT NULL, added_by INTEGER, added_at TEXT NOT NULL,
            views INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY, added_by INTEGER, added_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movies_views ON movies(views DESC)")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('welcome_text',?)", (
            "🟢 Assalomu alaykum, {username}!\n\n"
            "🎬 Kino botiga xush kelibsiz. Kino raqamini yuboring yoki quyidagi menyudan bo‘limni tanlang.",
        ))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def is_admin(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    with db() as conn:
        return conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone() is not None


def admin_ids() -> list[int]:
    with db() as conn:
        rows = conn.execute("SELECT user_id FROM admins").fetchall()
    return sorted(OWNER_IDS | {int(row["user_id"]) for row in rows})


def setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def register_user(user: Any) -> bool:
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user.id,)).fetchone()
        conn.execute("""INSERT INTO users(user_id,username,first_name,joined_at,last_seen)
            VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
            first_name=excluded.first_name,last_seen=excluded.last_seen""",
            (user.id, user.username, user.first_name or "", now(), now()))
    return exists is None


def esc(value: str | None) -> str:
    return html.escape(value or "", quote=False)


def username_label(user: Any) -> str:
    return "@" + esc(user.username) if user.username else esc(user.full_name or "do‘st")


def welcome_message(user: Any) -> str:
    template = setting("welcome_text", "Assalomu alaykum, {username}!")
    replacements = {
        "{username}": "@" + user.username if user.username else (user.first_name or "do‘st"),
        "{first_name}": user.first_name or "do‘st",
        "{user_id}": str(user.id),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return esc(template)


async def check_subscription(bot: Bot, user_id: int) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        status = str(member.status)
        return status in {"creator", "administrator", "member"} or (
            status == "restricted" and bool(getattr(member, "is_member", False))
        )
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError) as exc:
        log.warning("Kanal obunasi tekshirilmagan: %s", exc)
        return False


async def subscription_prompt(message: Message) -> None:
    await message.answer("🔒 Botdan foydalanish uchun avval kanalga obuna bo‘ling, so‘ng tekshiring.", reply_markup=subscription_keyboard())


async def callback_subscription_prompt(callback: CallbackQuery) -> None:
    await callback.answer("Avval kanalga obuna bo‘ling.", show_alert=True)
    if callback.message:
        await callback.message.answer("🔒 Kanalga obuna bo‘ling, so‘ng tekshiring.", reply_markup=subscription_keyboard())


async def send_home(message: Message, user: Any, greeting: bool = False) -> None:
    if greeting:
        await message.answer(welcome_message(user), reply_markup=home_keyboard(user.id))
    else:
        await message.answer("🟢 <b>Asosiy menyu</b>", reply_markup=home_keyboard(user.id))


async def stats_text() -> str:
    with db() as conn:
        users = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        movies = conn.execute("SELECT COUNT(*) n FROM movies").fetchone()["n"]
        views = conn.execute("SELECT COALESCE(SUM(views),0) n FROM movies").fetchone()["n"]
        admins = conn.execute("SELECT COUNT(*) n FROM admins").fetchone()["n"]
    return ("📊 <b>Bot statistikasi</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{users}</b>\n"
            f"🎬 Kinolar: <b>{movies}</b>\n"
            f"▶️ Kino yuborilgan: <b>{views}</b> marta\n"
            f"👮 Qo‘shimcha adminlar: <b>{admins}</b>")


async def popular_text() -> str:
    with db() as conn:
        rows = conn.execute("SELECT code,title,views FROM movies ORDER BY views DESC,added_at DESC LIMIT 10").fetchall()
    if not rows:
        return "🔥 Hozircha kinolar ro‘yxati bo‘sh."
    lines = ["🔥 <b>Mashhur kinolar</b>", ""]
    lines.extend(f"{i}. <b>{esc(row['title'])}</b> — <code>{row['code']}</code> · 👁 {row['views']}" for i, row in enumerate(rows, 1))
    lines.append("\nKinoni olish uchun raqamini yuboring.")
    return "\n".join(lines)


def movie_caption(movie: sqlite3.Row) -> str:
    head = f"🎬 <b>{esc(movie['title'])}</b>\n🔢 Raqami: <code>{movie['code']}</code>\n\n📝 "
    description = esc(movie["description"] or "Tavsif kiritilmagan.")
    return head + (description[: max(0, 1000 - len(head) - 1)] + "…" if len(description) + len(head) > 1000 else description)


async def send_movie(message: Message, code: int) -> None:
    with db() as conn:
        movie = conn.execute("SELECT * FROM movies WHERE code=?", (code,)).fetchone()
        if movie:
            conn.execute("UPDATE movies SET views=views+1 WHERE code=?", (code,))
    if not movie:
        await message.answer(f"🔎 <code>{code}</code> raqamli kino topilmadi. Raqamni tekshiring.")
        return
    try:
        await message.answer_video(movie["file_id"], caption=movie_caption(movie), supports_streaming=True)
    except TelegramBadRequest:
        log.exception("Video yuborishda xato; kino raqami=%s", code)
        await message.answer("Videoni yuborib bo‘lmadi. Admin bilan bog‘laning.")


async def show_movie_list(message: Message) -> None:
    with db() as conn:
        rows = conn.execute("SELECT code,title,views FROM movies ORDER BY code").fetchall()
    if not rows:
        await message.answer("📋 Hozircha kino yo‘q.", reply_markup=admin_keyboard())
        return
    chunks: list[str] = []
    current = "📋 <b>Barcha kinolar</b>\n\n"
    for row in rows:
        line = f"<code>{row['code']}</code> — {esc(row['title'])} · 👁 {row['views']}\n"
        if len(current) + len(line) > 3800:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    for chunk in chunks:
        await message.answer(chunk, reply_markup=admin_keyboard())


async def owner_users(message: Message) -> None:
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        rows = conn.execute("SELECT user_id,username,first_name,joined_at FROM users ORDER BY joined_at DESC LIMIT 20").fetchall()
    lines = [f"👥 <b>Oxirgi foydalanuvchilar</b> (jami {total})", ""]
    for row in rows:
        name = "@" + esc(row["username"]) if row["username"] else esc(row["first_name"] or "Ismsiz")
        lines.append(f"• {name} — <code>{row['user_id']}</code>")
    if not rows:
        lines.append("Hozircha foydalanuvchi yo‘q.")
    await message.answer("\n".join(lines), reply_markup=owner_keyboard())


async def prompt_admin_management(message: Message, owner_id: int) -> None:
    if not is_owner(owner_id):
        await message.answer("⛔ Bu amal faqat owner uchun.")
        return
    with db() as conn:
        rows = conn.execute("SELECT user_id FROM admins ORDER BY user_id").fetchall()
    ids = sorted(OWNER_IDS | {int(row["user_id"]) for row in rows})
    listing = "\n".join(f"• <code>{i}</code>{' — owner' if i in OWNER_IDS else ''}" for i in ids) or "Adminlar yo‘q."
    states[owner_id] = {"step": "owner_admins"}
    await message.answer(
        "👮 <b>Adminlar</b>\n" + listing +
        "\n\nQo‘shish: <code>add 123456789</code>\nO‘chirish: <code>remove 123456789</code>\nBekor qilish: /cancel",
        reply_markup=owner_keyboard())


async def notify_owner_new_user(bot: Bot, user: Any) -> None:
    username = username_label(user)
    for owner_id in OWNER_IDS:
        try:
            await bot.send_message(owner_id, f"🟢 Yangi foydalanuvchi botga qo‘shildi: {username} · <code>{user.id}</code>")
        except (TelegramBadRequest, TelegramForbiddenError):
            # Owner bot bilan avval /start orqali suhbat boshlamagan bo'lishi mumkin.
            log.info("Yangi foydalanuvchi haqidagi xabar ownerga yuborilmadi")


async def process_state(message: Message, state: dict[str, Any]) -> bool:
    user_id = message.from_user.id
    text = (message.text or "").strip()
    step = state.get("step")
    if text == "/cancel":
        states.pop(user_id, None)
        await message.answer("Amal bekor qilindi.", reply_markup=home_keyboard(user_id))
        return True

    if step == "search":
        if not text.isdigit():
            await message.answer("Kino raqamini faqat raqam bilan yuboring:")
            return True
        states.pop(user_id, None)
        await send_movie(message, int(text))
        return True

    if step == "contact":
        delivered = 0
        caption = f"📩 <b>Foydalanuvchi xabari</b>\nKimdan: {username_label(message.from_user)}\nID: <code>{user_id}</code>"
        for aid in admin_ids():
            try:
                await message.bot.send_message(aid, caption)
                await message.bot.copy_message(aid, message.chat.id, message.message_id)
                delivered += 1
            except (TelegramBadRequest, TelegramForbiddenError):
                log.info("Admin xabarni qabul qila olmadi: %s", aid)
        states.pop(user_id, None)
        await message.answer("✅ Xabaringiz adminga yetkazildi." if delivered else "Hozir adminga yetkazib bo‘lmadi.", reply_markup=home_keyboard(user_id))
        return True

    if step == "owner_welcome":
        if not is_owner(user_id):
            states.pop(user_id, None)
            await message.answer("⛔ Ruxsat yo‘q.")
            return True
        if not text:
            await message.answer("Salomlashuv matnini matn ko‘rinishida yuboring:")
            return True
        if len(text) > 3000:
            await message.answer("Xabar 3000 belgidan oshmasin. Qisqartirib yuboring:")
            return True
        set_setting("welcome_text", text)
        states.pop(user_id, None)
        await message.answer("✅ Start salomi saqlandi. O‘zgaruvchilar: <code>{username}</code>, <code>{first_name}</code>, <code>{user_id}</code>.", reply_markup=owner_keyboard())
        return True

    if step == "owner_broadcast":
        if not is_owner(user_id):
            states.pop(user_id, None)
            return True
        if not text:
            await message.answer("Hozircha faqat matnli xabarni yuborish mumkin. Xabar matnini kiriting:")
            return True
        if len(text) > 3500:
            await message.answer("Xabar 3500 belgidan oshmasin. Qisqartiring:")
            return True
        state["draft"] = text
        state["step"] = "owner_broadcast_confirm"
        await message.answer(
            "📣 <b>Xabar loyihasi</b>\n\n" + esc(text) + "\n\nBarcha foydalanuvchilarga yuborilsinmi?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                button("✅ Ha, yuborish", "owner:broadcast_send", GREEN),
                button("❌ Bekor qilish", "owner:broadcast_cancel", RED),
            ]]))
        return True

    if step == "owner_admins":
        if not is_owner(user_id):
            states.pop(user_id, None)
            return True
        match = re.fullmatch(r"(add|remove)\s+(\d{5,20})", text, re.IGNORECASE)
        if not match:
            await message.answer("Format: <code>add 123456789</code> yoki <code>remove 123456789</code>. /cancel — bekor qilish.")
            return True
        action, raw_id = match.group(1).lower(), int(match.group(2))
        if action == "add":
            if raw_id in OWNER_IDS:
                await message.answer("Bu foydalanuvchi allaqachon owner.")
            else:
                with db() as conn:
                    conn.execute("INSERT OR IGNORE INTO admins(user_id,added_by,added_at) VALUES(?,?,?)", (raw_id, user_id, now()))
                await message.answer(f"✅ <code>{raw_id}</code> admin qilindi.")
        else:
            if raw_id in OWNER_IDS:
                await message.answer("Owner ID’ni admin paneldan olib tashlab bo‘lmaydi.")
            else:
                with db() as conn:
                    cur = conn.execute("DELETE FROM admins WHERE user_id=?", (raw_id,))
                await message.answer("✅ Admin olib tashlandi." if cur.rowcount else "Bu ID admin emas.")
        await message.answer("Yana buyruq kiriting: <code>add ID</code> yoki <code>remove ID</code>.", reply_markup=owner_keyboard())
        return True

    if not is_admin(user_id):
        states.pop(user_id, None)
        await message.answer("⛔ Admin ruxsati topilmadi.")
        return True

    if step == "movie_add_code":
        if not text.isdigit() or int(text) <= 0:
            await message.answer("Takrorlanmaydigan musbat raqam kiriting:")
            return True
        code = int(text)
        with db() as conn:
            exists = conn.execute("SELECT 1 FROM movies WHERE code=?", (code,)).fetchone()
        if exists:
            await message.answer("Bu kino raqami band. Boshqa raqam tanlang:")
            return True
        state.update(step="movie_add_title", code=code)
        await message.answer("Kino nomini yuboring:")
        return True

    if step == "movie_add_title":
        if not text:
            await message.answer("Kino nomi bo‘sh bo‘lmasin:")
            return True
        state.update(step="movie_add_desc", title=text[:200])
        await message.answer("Kino tavsifi (bo‘sh qoldirish uchun -):")
        return True

    if step == "movie_add_desc":
        if message.text is None:
            await message.answer("Tavsifni matn ko‘rinishida yuboring:")
            return True
        state["description"] = "" if text == "-" else text[:1500]
        state["step"] = "movie_add_video"
        await message.answer("Endi kino videosini Telegram video sifatida yuboring:")
        return True

    if step == "movie_add_video":
        if not message.video:
            await message.answer("Video topilmadi. Kino videosini video shaklida yuboring:")
            return True
        try:
            with db() as conn:
                conn.execute("INSERT INTO movies(code,title,description,file_id,added_by,added_at,views) VALUES(?,?,?,?,?,?,0)",
                             (state["code"], state["title"], state.get("description", ""), message.video.file_id, user_id, now()))
        except sqlite3.IntegrityError:
            states[user_id] = {"step": "movie_add_code"}
            await message.answer("Raqam boshqa admin tomonidan band qilingan. Yangi raqam kiriting:")
            return True
        code = state["code"]
        states.pop(user_id, None)
        await message.answer(f"✅ Kino qo‘shildi. Raqami: <code>{code}</code>", reply_markup=admin_keyboard())
        return True

    if step == "movie_delete":
        if not text.isdigit():
            await message.answer("O‘chiriladigan kino raqamini yuboring:")
            return True
        with db() as conn:
            cur = conn.execute("DELETE FROM movies WHERE code=?", (int(text),))
        states.pop(user_id, None)
        await message.answer("✅ Kino o‘chirildi." if cur.rowcount else "Kino topilmadi.", reply_markup=admin_keyboard())
        return True

    if step == "movie_edit_code":
        if not text.isdigit():
            await message.answer("Tahrir qilinadigan kino raqamini yuboring:")
            return True
        with db() as conn:
            movie = conn.execute("SELECT * FROM movies WHERE code=?", (int(text),)).fetchone()
        if not movie:
            await message.answer("Kino topilmadi. Raqamni qayta yuboring:")
            return True
        state.update(step="movie_edit_title", code=int(text))
        await message.answer(f"Hozirgi nom: {esc(movie['title'])}\nYangi nom yoki o‘zgartirmaslik uchun -:")
        return True

    if step == "movie_edit_title":
        with db() as conn:
            movie = conn.execute("SELECT title FROM movies WHERE code=?", (state["code"],)).fetchone()
            if not movie:
                states.pop(user_id, None)
                await message.answer("Kino topilmadi.")
                return True
            title = movie["title"] if text == "-" else text[:200]
            if not title:
                await message.answer("Nom bo‘sh bo‘lmasligi kerak:")
                return True
            conn.execute("UPDATE movies SET title=? WHERE code=?", (title, state["code"]))
            row = conn.execute("SELECT description FROM movies WHERE code=?", (state["code"],)).fetchone()
        state["step"] = "movie_edit_desc"
        await message.answer(f"Hozirgi tavsif: {esc(row['description']) or '—'}\nYangi tavsif yoki o‘zgartirmaslik uchun -:")
        return True

    if step == "movie_edit_desc":
        with db() as conn:
            row = conn.execute("SELECT description FROM movies WHERE code=?", (state["code"],)).fetchone()
            if row:
                desc = row["description"] if text == "-" else text[:1500]
                conn.execute("UPDATE movies SET description=? WHERE code=?", (desc, state["code"]))
        code = state["code"]
        states.pop(user_id, None)
        await message.answer(f"✅ <code>{code}</code> kino ma’lumoti yangilandi.", reply_markup=admin_keyboard())
        return True

    return False


@router.message(F.text == "/start")
async def on_start(message: Message) -> None:
    if not message.from_user:
        return
    states.pop(message.from_user.id, None)
    is_new = register_user(message.from_user)
    if not await check_subscription(message.bot, message.from_user.id):
        await subscription_prompt(message)
        return
    await send_home(message, message.from_user, greeting=True)
    if is_new:
        await notify_owner_new_user(message.bot, message.from_user)


@router.message(F.text == "/cancel")
async def on_cancel(message: Message) -> None:
    if message.from_user:
        states.pop(message.from_user.id, None)
        await message.answer("Amal bekor qilindi.", reply_markup=home_keyboard(message.from_user.id))


@router.message()
async def on_message(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    register_user(user)
    if not await check_subscription(message.bot, user.id):
        await subscription_prompt(message)
        return
    text = (message.text or "").strip()
    if user.id in states and await process_state(message, states[user.id]):
        return
    if text.isdigit():
        await send_movie(message, int(text))
    elif message.video:
        await message.answer("Kino olish uchun raqamini yuboring. Video qo‘shish admin paneldan amalga oshiriladi.")
    else:
        await message.answer("🟢 Menyudan bo‘lim tanlang yoki kino raqamini yuboring.", reply_markup=home_keyboard(user.id))


@router.callback_query()
async def on_callback(callback: CallbackQuery) -> None:
    user = callback.from_user
    data = callback.data or ""
    if not callback.message:
        await callback.answer()
        return
    if data == "flow:cancel":
        states.pop(user.id, None)
        await callback.answer("Bekor qilindi")
        await callback.message.answer("🟢 Amal bekor qilindi.", reply_markup=home_keyboard(user.id))
        return
    if data == "sub:check":
        if await check_subscription(callback.bot, user.id):
            await callback.answer("Obuna tasdiqlandi")
            states.pop(user.id, None)
            await callback.message.answer(welcome_message(user), reply_markup=home_keyboard(user.id))
        else:
            await callback.answer("Obuna aniqlanmadi. Kanalga qo‘shilib qayta tekshiring.", show_alert=True)
        return

    # Bot menyulari va admin amallari majburiy obunani talab qiladi.
    if not await check_subscription(callback.bot, user.id):
        await callback_subscription_prompt(callback)
        return
    await callback.answer()

    if data == "user:home":
        states.pop(user.id, None)
        await callback.message.answer("🟢 <b>Asosiy menyu</b>", reply_markup=home_keyboard(user.id))
    elif data == "user:search":
        states[user.id] = {"step": "search"}
        await callback.message.answer("🔎 Kino raqamini yuboring:", reply_markup=cancel_keyboard())
    elif data == "user:popular":
        await callback.message.answer(await popular_text(), reply_markup=home_keyboard(user.id))
    elif data == "user:stats":
        await callback.message.answer(await stats_text(), reply_markup=home_keyboard(user.id))
    elif data == "user:contact":
        states[user.id] = {"step": "contact"}
        await callback.message.answer("Adminlarga yubormoqchi bo‘lgan xabaringizni yozing. Bekor qilish: /cancel", reply_markup=cancel_keyboard())
    elif data == "admin:home":
        if not is_admin(user.id):
            await callback.message.answer("⛔ Admin huquqi yo‘q.")
            return
        states.pop(user.id, None)
        await callback.message.answer("🛠 <b>Admin panel</b>", reply_markup=admin_keyboard())
    elif data == "admin:add":
        if not is_admin(user.id):
            await callback.message.answer("⛔ Ruxsat yo‘q.")
            return
        states[user.id] = {"step": "movie_add_code"}
        await callback.message.answer("➕ Takrorlanmaydigan musbat kino raqamini yuboring:", reply_markup=cancel_keyboard())
    elif data == "admin:delete":
        if not is_admin(user.id):
            await callback.message.answer("⛔ Ruxsat yo‘q.")
            return
        states[user.id] = {"step": "movie_delete"}
        await callback.message.answer("🗑 O‘chiriladigan kino raqamini yuboring:", reply_markup=cancel_keyboard())
    elif data == "admin:edit":
        if not is_admin(user.id):
            await callback.message.answer("⛔ Ruxsat yo‘q.")
            return
        states[user.id] = {"step": "movie_edit_code"}
        await callback.message.answer("✏️ Tahrir qilinadigan kino raqamini yuboring:", reply_markup=cancel_keyboard())
    elif data == "admin:list":
        if not is_admin(user.id):
            await callback.message.answer("⛔ Ruxsat yo‘q.")
            return
        await show_movie_list(callback.message)
    elif data == "admin:stats":
        if not is_admin(user.id):
            await callback.message.answer("⛔ Ruxsat yo‘q.")
            return
        await callback.message.answer(await stats_text(), reply_markup=admin_keyboard())
    elif data.startswith("owner:"):
        if not is_owner(user.id):
            await callback.message.answer("⛔ Owner ruxsati kerak.")
            return
        await handle_owner_callback(callback, data)
    else:
        await callback.message.answer("Buyruq tushunilmadi. Menyuni qayta oching.", reply_markup=home_keyboard(user.id))


async def handle_owner_callback(callback: CallbackQuery, data: str) -> None:
    user_id = callback.from_user.id
    message = callback.message
    if data == "owner:home":
        states.pop(user_id, None)
        await message.answer("👑 <b>Owner paneli</b>", reply_markup=owner_keyboard())
    elif data == "owner:welcome":
        states[user_id] = {"step": "owner_welcome"}
        current = setting("welcome_text", "Assalomu alaykum, {username}!")
        await message.answer(
            "🎉 <b>Start salomini sozlash</b>\n\nHozirgi xabar:\n" + esc(current) +
            "\n\nYangi matnni yuboring. Qo‘llanadigan o‘zgaruvchilar: <code>{username}</code>, <code>{first_name}</code>, <code>{user_id}</code>.\nBekor qilish: /cancel",
            reply_markup=cancel_keyboard())
    elif data == "owner:broadcast":
        states[user_id] = {"step": "owner_broadcast"}
        await message.answer("📣 Yuboriladigan matnni kiriting. Jo‘natishdan oldin tasdiqlash ko‘rsatiladi. Bekor qilish: /cancel", reply_markup=cancel_keyboard())
    elif data == "owner:broadcast_cancel":
        states.pop(user_id, None)
        await message.answer("Xabar tarqatish bekor qilindi.", reply_markup=owner_keyboard())
    elif data == "owner:broadcast_send":
        state = states.get(user_id, {})
        if state.get("step") != "owner_broadcast_confirm" or not state.get("draft"):
            await message.answer("Xabar loyihasi topilmadi. Tarqatishni qayta boshlang.", reply_markup=owner_keyboard())
            return
        draft = state["draft"]
        states.pop(user_id, None)
        with db() as conn:
            rows = conn.execute("SELECT user_id FROM users").fetchall()
        sent = failed = 0
        status_msg = await message.answer(f"📣 Xabar yuborilmoqda… 0/{len(rows)}")
        for row in rows:
            try:
                await callback.bot.send_message(int(row["user_id"]), esc(draft))
                sent += 1
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1
            except TelegramNetworkError:
                failed += 1
                log.exception("Broadcast tarmoq xatosi")
            await asyncio.sleep(0.05)
        await status_msg.edit_text(f"✅ Tarqatish yakunlandi. Yuborildi: <b>{sent}</b>, yetkazilmadi: <b>{failed}</b>.", reply_markup=owner_keyboard())
    elif data == "owner:admins":
        await prompt_admin_management(message, user_id)
    elif data == "owner:users":
        await owner_users(message)
    elif data == "owner:stats":
        await message.answer(await stats_text(), reply_markup=owner_keyboard())
    elif data == "owner:backup":
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix="kino_backup_", suffix=".sqlite3", delete=False) as temp:
                temp_path = temp.name
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(temp_path) as target:
                source.backup(target)
            await callback.bot.send_document(user_id, document=FSInputFile(temp_path, filename="kino_bot_backup.sqlite3"), caption="💾 SQLite baza zaxirasi")
        except Exception:
            log.exception("Bazani zaxiralashda xato")
            await message.answer("Bazani zaxiralashda xato yuz berdi.", reply_markup=owner_keyboard())
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN muhit o'zgaruvchisi belgilanmagan.")
    init_db()
    if not OWNER_IDS:
        log.warning("OWNER_IDS yo'q: owner panelidan foydalanib bo'lmaydi.")
    if REQUIRED_CHANNEL:
        log.info("Majburiy kanal obunasi yoqilgan: %s", REQUIRED_CHANNEL)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        me = await bot.get_me()
        log.info("Ishga tushdi: @%s (ID %s)", me.username, me.id)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to‘xtatildi")
