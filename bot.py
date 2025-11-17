import os
import json
import time
import logging
import hashlib
from pathlib import Path
from functools import wraps
from typing import Dict, Any, List

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# =====================================================
# CONFIG
# =====================================================

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("ENV TELEGRAM_TOKEN belum di-set!")

OWNER_IDS = {123456789}  # GANTI dengan Telegram user id lu

BOT_NAME = "Installer RDP"
BOT_VERSION = "1.0"

USERS_FILE = Path("users.json")
INSTALLS_FILE = Path("installs.json")

# daftar OS yang tersedia (bisa lu ubah sesuka hati)
OS_LIST: List[Dict[str, str]] = [
    {"id": "win-10-pro", "name": "Windows 10 Pro", "note": "RDP umum, ringan"},
    {"id": "win-11-pro", "name": "Windows 11 Pro", "note": "UI modern, agak berat"},
    {"id": "win-serv-2019", "name": "Windows Server 2019", "note": "Stabil untuk server"},
    {"id": "win-serv-2022", "name": "Windows Server 2022", "note": "Terbaru, enterprise"},
]

# =====================================================
# LOGGING
# =====================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =====================================================
# UTIL JSON
# =====================================================


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data: Any):
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Gagal save %s: %s", path, e)


# =====================================================
# DATA LAYER: USERS & INSTALLS
# =====================================================

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def get_users() -> Dict[str, Any]:
    # key = str(telegram_user_id)
    return load_json(USERS_FILE, {})


def save_users(users: Dict[str, Any]):
    save_json(USERS_FILE, users)


def get_installs() -> List[Dict[str, Any]]:
    return load_json(INSTALLS_FILE, [])


def save_installs(installs: List[Dict[str, Any]]):
    save_json(INSTALLS_FILE, installs)


# =====================================================
# AUTH DECORATOR
# =====================================================

def login_required(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        message = update.effective_message

        users = get_users()
        if str(user.id) not in users:
            await message.reply_text(
                "❌ Kamu belum terdaftar / login.\n"
                "Daftar / login dulu pakai:\n"
                "`/login username password`",
                parse_mode="Markdown",
            )
            return

        return await func(update, context)

    return wrapper


# =====================================================
# KEYBOARD
# =====================================================

def build_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🚀 Install OS", callback_data="menu_install"),
                InlineKeyboardButton("💽 Daftar OS", callback_data="menu_oslist"),
            ],
            [
                InlineKeyboardButton("📊 Status Install", callback_data="menu_status"),
                InlineKeyboardButton("🧾 Riwayat", callback_data="menu_history"),
            ],
            [
                InlineKeyboardButton("👤 Akun / Login", callback_data="menu_account"),
            ],
        ]
    )


# =====================================================
# COMMAND HANDLERS
# =====================================================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"🌟 *SELAMAT DATANG DI {BOT_NAME.upper()}* 🌟\n\n"
        f"Hai {user.mention_markdown()}!\n"
        "Siap membuat RDP Windows di VPS kamu dengan mudah?\n\n"
        "*PERINTAH UTAMA*\n"
        "`/login [username] [password]` - Daftar/login ke bot\n"
        "`/install [ip] [port] [os_id]` - Request install OS ke VPS\n"
        "`/oslist` - Lihat daftar OS tersedia\n"
        "`/status` - Lihat status install aktif\n"
        "`/history` - Lihat riwayat instalasi\n\n"
        "_InstallerRDP — Template bot installer VPS untuk Anda_"
    )
    await update.effective_message.reply_markdown(
        text,
        reply_markup=build_main_menu(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📝 *BANTUAN BOT INSTALLER RDP*\n\n"
        "*1. Login / Daftar*\n"
        "`/login username password`\n"
        "• Kalau belum ada → otomatis daftar.\n"
        "• Kalau sudah ada → dicek password-nya.\n\n"
        "*2. Lihat daftar OS*\n"
        "`/oslist`\n"
        "• Menampilkan list OS & `os_id` untuk perintah /install.\n\n"
        "*3. Request Install*\n"
        "`/install ip port os_id`\n"
        "Contoh:\n"
        "`/install 128.199.59.22 22 win-10-pro`\n\n"
        "*4. Cek status & riwayat*\n"
        "`/status`  - Lihat install aktif\n"
        "`/history` - Lihat semua riwayat milik akunmu\n\n"
        "⚠️ *NOTE KEAMANAN*: Template ini TIDAK menjalankan SSH beneran.\n"
        "Kamu bisa sambungkan ke script installer sendiri (baca file `installs.json`)."
    )
    await update.effective_message.reply_markdown(text)


# ---------- LOGIN / ACCOUNT ----------

async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    if len(context.args) < 2:
        await message.reply_text(
            "Pakai: `/login username password`\nContoh: `/login vanzsky superpass`",
            parse_mode="Markdown",
        )
        return

    username = context.args[0]
    password = " ".join(context.args[1:])
    pw_hash = hash_password(password)

    users = get_users()

    # Cek kalau username sudah dipakai user lain
    for uid, info in users.items():
        if info.get("username") == username and str(user.id) != uid:
            await message.reply_text("❌ Username sudah dipakai user lain.")
            return

    user_key = str(user.id)
    existing = users.get(user_key)

    if existing:
        # user sudah ada → cek password
        if existing.get("password_hash") == pw_hash:
            await message.reply_text(
                f"✅ Login berhasil!\nUsername: *{existing['username']}*",
                parse_mode="Markdown",
            )
        else:
            await message.reply_text("❌ Password salah.")
    else:
        # register baru
        users[user_key] = {
            "username": username,
            "password_hash": pw_hash,
            "created_at": int(time.time()),
        }
        save_users(users)
        await message.reply_text(
            f"✅ Pendaftaran berhasil!\nUsername: *{username}*",
            parse_mode="Markdown",
        )


@login_required
async def me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    users = get_users()
    info = users.get(str(user.id), {})
    text = (
        "👤 *Info Akun*\n\n"
        f"ID Telegram: `{user.id}`\n"
        f"Username bot: *{info.get('username', '-')}*\n"
    )
    await message.reply_markdown(text)


@login_required
async def logout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    users = get_users()
    if str(user.id) in users:
        users.pop(str(user.id))
        save_users(users)
        await message.reply_text("✅ Kamu sudah logout & data akun dihapus.")
    else:
        await message.reply_text("Kamu belum login bro.")


# ---------- OS LIST & INSTALL ----------

async def oslist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["💽 *DAFTAR OS TERSEDIA:*\n"]
    for osdata in OS_LIST:
        lines.append(
            f"`{osdata['id']}` - *{osdata['name']}*\n"
            f"  _{osdata['note']}_\n"
        )
    text = "\n".join(lines)
    await update.effective_message.reply_markdown(text)


@login_required
async def install_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    users = get_users()
    user_info = users.get(str(user.id))

    if len(context.args) < 3:
        await message.reply_text(
            "Format: `/install ip port os_id`\n"
            "Contoh: `/install 128.199.59.22 22 win-10-pro`",
            parse_mode="Markdown",
        )
        return

    ip = context.args[0]
    port = context.args[1]
    os_id = context.args[2]

    # cek os_id valid
    os_data = next((o for o in OS_LIST if o["id"] == os_id), None)
    if not os_data:
        await message.reply_text(
            "❌ os_id tidak dikenal.\n"
            "Cek daftar OS dengan perintah: /oslist"
        )
        return

    installs = get_installs()

    install_obj = {
        "install_id": f"INST-{int(time.time())}-{user.id}",
        "user_id": user.id,
        "username": user_info.get("username"),
        "ip": ip,
        "port": port,
        "os_id": os_id,
        "os_name": os_data["name"],
        "status": "pending",   # pending / running / success / failed
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }

    installs.append(install_obj)
    save_installs(installs)

    await message.reply_text(
        "✅ *Request install berhasil disimpan!*\n\n"
        f"ID Install: `{
