import asyncio
import copy
import json
import logging
import os
import random
import re
import hashlib
import sqlite3
import tempfile
import time
import zlib
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from html import escape
from io import BytesIO
from urllib.parse import urlencode

import aiohttp

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, BufferedInputFile, InputMediaPhoto,
    LabeledPrice, PreCheckoutQuery,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineQuery,
    InlineQueryResultArticle, InlineQueryResultCachedPhoto, InlineQueryResultCachedVideo,
    InputTextMessageContent,
)
from aiogram.types import InlineKeyboardButton as _TgInlineKeyboardButton, KeyboardButton as _TgKeyboardButton
from aiogram.client.default import DefaultBotProperties, Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Импортируем Telethon для работы с личными аккаунтами
from telethon import TelegramClient
from telethon import errors as tg_errors
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.tl.types import InputMediaDice, ChatInviteAlready, User
from telethon import events, utils as tg_utils
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel

# ============================================================
# 🔑 НАСТРОЙКИ И ТОКЕНЫ
# ============================================================
# Секреты задаются через переменные окружения Windows/VS Code (или файл .env):
#   BOT_TOKEN, API_ID, API_HASH
# Не храните токен бота и API_HASH в исходном коде.

def _load_dotenv(path: str) -> None:
    """Мини-загрузчик .env: строки KEY=VALUE, переменные окружения имеют приоритет."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v:
                    os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()


DATA_DIR = os.getenv("DATA_DIR", "").strip() or os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

PROXY = ""
TIMEZONE_NAME = "Europe/Moscow"

BUY_ACCOUNT_URL = "https://t.me/soraXTgAccountbot"
SUPPORT_URL = "https://t.me/durovsor"
POLICY_URL = ""
TERMS_URL = ""

ADMIN_ID = 619112100
ADMIN_USERNAME = "durovsor"

# Подпись, которая добавляется к сообщениям на бесплатном тарифе (без подписки)
AD_SIGNATURE = "\n\n━━━━━━━━━━\n🤖 Отправлено через @CabinetSenderBot"
# ============================================================

CHATS_PER_PAGE = 20
MAX_MESSAGES = 20
ACCOUNT_LIMIT_FREE = 1
ACCOUNT_LIMIT_PAID = 5
REF_PERCENT = 50.0
REF_MIN_WITHDRAW = 1.0

PLAN_INFO = {
    "1d": {"days": 1, "price": 0.19, "label": "1 день"},
    "7d": {"days": 7, "price": 0.99, "label": "7 дней"},
    "30d": {"days": 30, "price": 2.99, "label": "30 дней"},
}


# ============================================================
# 💳 НАСТРОЙКИ ОПЛАТЫ
# Ключи читаются из файла .env (лежит рядом с этим файлом) или из переменных
# окружения. Если ключа нет — этот способ оплаты просто скрывается из меню.
# ============================================================
# Lave Pay (Laveshka): ключ вида LAVE-<merchant_id>-<secret>
LAVE_API_KEY = os.getenv("LAVE_API_KEY", "").strip()
LAVE_BASE = "https://laveshka.io/merchant/v1"

# CryptoBot (Crypto Pay API): токен из @CryptoBot -> Crypto Pay -> My Apps
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN", "").strip()
CRYPTO_PAY_BASE = "https://pay.crypt.bot/api"
CRYPTOBOT_FEE = Decimal("0.03")   # наценка за CryptoBot (показывается как «+3%»), 0 — без наценки

# xRocket Pay API: токен из @xRocket -> Pay API -> Settings -> API Token
XROCKET_TOKEN = os.getenv("XROCKET_TOKEN", "").strip()
XROCKET_BASE = "https://pay.api.xrocket.exchange"

# Оплата криптой напрямую на кошельки (проверка платежей через TON Center / TronGrid)
TONCENTER_KEY = os.getenv("TONCENTER_KEY", "").strip()
TONCENTER_BASE = "https://toncenter.com/api/v3"
TON_WALLET_GRAM = os.getenv("TON_WALLET_GRAM", "UQC1sKGY2gNVR9cteNlGiFlYQglDKryw1QzXyj88x-hX7Fo3").strip()
TON_WALLET_USDT = os.getenv("TON_WALLET_USDT", "UQC1sKGY2gNVR9cteNlGiFlYQglDKryw1QzXyj88x-hX7Fo3").strip()
TRON_WALLET = os.getenv("TRON_WALLET", "TL6i4f3NdnTXRVgSWCNmXDrJWufQSPa7Fq").strip()
TRONGRID_KEY = os.getenv("TRONGRID_KEY", "").strip()
TRONGRID_BASE = "https://api.trongrid.io"
USDT_TON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"
USDT_TON_MASTER_HEX = "B113A994B5024A16719F69139328EB759596C38A25F59028B146FECDC3621DFE"
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


class PromoState(StatesGroup):
    waiting_for_promo = State()


class AccState(StatesGroup):
    proxy = State()
    api_id = State()
    api_hash = State()
    phone = State()
    code = State()
    password = State()

class AdminState(StatesGroup):
    broadcast_wait = State()
    search_wait = State()
    dm_wait = State()
    discount_wait = State()


class CS(StatesGroup):
    name = State()
    cd_cycle = State()
    add_message = State()
    add_forward = State()
    cd_chats = State()
    add_chat = State()
    add_folder = State()
    add_txt = State()
    btn_url = State()
    btn_text = State()
    time_range = State()
    chat_interval = State()
    reply_range = State()
    tag_count = State()


class PS(StatesGroup):
    chats = State()
    folder = State()
    txt = State()
    keywords = State()
    stopwords = State()
    reply_text = State()


user_data_db = {}
admin_stats = {
    "purchases": {"1d": 0, "7d": 0, "30d": 0},
    "revenue": 0.0,
}

router = Router()


# ============================================================
# 💾 ХРАНИЛИЩЕ (Redis): данные переживают перезапуск и деплой
# ------------------------------------------------------------
# Что сохраняется в Redis:
#   • все пользователи (user_data_db): аккаунты, рассылки, парсеры, прогрев,
#     рефералы, баланс, баны, скидки;
#   • FSM-состояния диалогов (RedisStorage);
#   • файлы сессий Telethon (.session) — аккаунты не разлогиниваются;
#   • база подписок/счетов/платежей (снимок bot.db).
# После старта запущенные рассылки/парсеры/прогрев поднимаются сами.
# Если REDIS_URL не задан — бот работает как раньше (всё в памяти и на диске).
# ============================================================
REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("KV_URL") or "").strip()
REDIS_PREFIX = os.getenv("REDIS_PREFIX", "autosender:")
PERSIST_RUNNING_EVERY = int(os.getenv("PERSIST_RUNNING_EVERY", "60") or 60)    # сек: пользователи с работающими задачами
PERSIST_ALL_EVERY = int(os.getenv("PERSIST_ALL_EVERY", "300") or 300)          # сек: полная сверка всех
SESSION_BACKUP_EVERY = int(os.getenv("SESSION_BACKUP_EVERY", "600") or 600)    # сек: копии .session в Redis

_redis = None
_dirty_users: set = set()
_saved_hash: dict = {}
_bg_tasks: set = set()
_db_dirty = False
_db_task = None


def get_redis():
    global _redis
    if _redis is None and REDIS_URL:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(REDIS_URL, health_check_interval=30, socket_keepalive=True)
    return _redis


def spawn(coro):
    """create_task с удержанием ссылки (иначе задачу может собрать сборщик мусора)."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


def mark_dirty(uid) -> None:
    if REDIS_URL and isinstance(uid, int):
        _dirty_users.add(uid)


# ---------- (де)сериализация: datetime / set / tuple переживают JSON ----------
def _pack(o):
    if isinstance(o, datetime):
        return {"__dt__": o.isoformat()}
    if isinstance(o, (set, frozenset)):
        return {"__set__": [_pack(x) for x in o]}
    if isinstance(o, tuple):
        return {"__tuple__": [_pack(x) for x in o]}
    if isinstance(o, list):
        return [_pack(x) for x in o]
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else f"__int__:{k}"): _pack(v) for k, v in o.items()}
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    raise TypeError(f"нельзя сохранить тип {type(o).__name__}")


def _unpack(o):
    if isinstance(o, list):
        return [_unpack(x) for x in o]
    if isinstance(o, dict):
        if len(o) == 1:
            if "__dt__" in o:
                return datetime.fromisoformat(o["__dt__"])
            if "__set__" in o:
                return {_unpack(x) for x in o["__set__"]}
            if "__tuple__" in o:
                return tuple(_unpack(x) for x in o["__tuple__"])
        return {(int(k[8:]) if k.startswith("__int__:") else k): _unpack(v) for k, v in o.items()}
    return o


def dump_user(info: dict) -> bytes:
    raw = json.dumps(_pack(info), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return zlib.compress(raw, 6)


def load_user_blob(blob: bytes) -> dict:
    return _unpack(json.loads(zlib.decompress(blob).decode("utf-8")))


async def save_user(uid: int, force: bool = False) -> None:
    r = get_redis()
    if r is None or uid not in user_data_db:
        return
    try:
        blob = dump_user(user_data_db[uid])
        h = hashlib.md5(blob).hexdigest()
        if not force and _saved_hash.get(uid) == h:
            return
        await r.set(f"{REDIS_PREFIX}user:{uid}", blob)
        _saved_hash[uid] = h
    except Exception:
        logging.exception("Не удалось сохранить пользователя %s в Redis", uid)


async def load_all_users() -> int:
    r = get_redis()
    if r is None:
        return 0
    n = 0
    async for key in r.scan_iter(match=f"{REDIS_PREFIX}user:*", count=500):
        key = key.decode() if isinstance(key, bytes) else key
        try:
            uid = int(key.rsplit(":", 1)[1])
            blob = await r.get(key)
            if not blob:
                continue
            user_data_db[uid] = load_user_blob(blob)
            _saved_hash[uid] = hashlib.md5(blob).hexdigest()
            n += 1
        except Exception:
            logging.exception("Не удалось загрузить %s из Redis", key)
    return n


def _has_background_work(ui: dict) -> bool:
    if any(c.get("running") for c in ui.get("campaigns", [])):
        return True
    if any(p.get("running") for p in ui.get("parsers", [])):
        return True
    return any(w.get("running") for w in ui.get("warmup", {}).values())


async def persist_loop():
    """Фоновое сохранение: быстро — то, что менял пользователь, реже — статистика работающих задач."""
    last_all = last_run = time.monotonic()
    while True:
        await asyncio.sleep(2)
        try:
            if _dirty_users:
                batch = list(_dirty_users)
                _dirty_users.clear()
                for uid in batch:
                    await save_user(uid)
            now = time.monotonic()
            if now - last_all >= PERSIST_ALL_EVERY:
                last_all = last_run = now
                for uid in list(user_data_db):
                    await save_user(uid)
            elif now - last_run >= PERSIST_RUNNING_EVERY:
                last_run = now
                for uid, ui in list(user_data_db.items()):
                    if _has_background_work(ui):
                        await save_user(uid)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("persist_loop")


class PersistMiddleware(BaseMiddleware):
    """После каждого действия пользователя помечает его данные как изменённые."""

    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        finally:
            u = getattr(event, "from_user", None)
            if u:
                mark_dirty(u.id)


# ---------- файлы: .session (Telethon) и bot.db (SQLite) ----------
def snapshot_sqlite(path: str) -> bytes:
    """Консистентная копия SQLite-файла (можно делать, пока файл открыт)."""
    fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        src = sqlite3.connect(path)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def session_filename(phone: str) -> str:
    return f"session_{phone.replace('+', '')}.session"


async def backup_sessions() -> None:
    r = get_redis()
    if r is None:
        return
    files = {session_filename(p) for ui in user_data_db.values() for p in ui.get("accounts", [])}
    for fname in files:
        path = os.path.join(SESSIONS_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            data = await asyncio.to_thread(snapshot_sqlite, path)
            await r.set(f"{REDIS_PREFIX}sess:{fname}", data)
        except Exception as e:
            logging.warning("Копия сессии %s не сохранена: %s", fname, e)


async def session_backup_loop():
    while True:
        await asyncio.sleep(SESSION_BACKUP_EVERY)
        try:
            await backup_sessions()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("session_backup_loop")


def request_db_backup() -> None:
    """Вызывается после каждой записи в bot.db: снимок уезжает в Redis (с небольшой склейкой запросов)."""
    global _db_dirty, _db_task
    if not REDIS_URL:
        return
    _db_dirty = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _db_task is None or _db_task.done():
        _db_task = loop.create_task(_db_backup_worker())


async def _db_backup_worker():
    global _db_dirty
    while _db_dirty:
        _db_dirty = False
        await asyncio.sleep(0.3)
        try:
            data = await asyncio.to_thread(snapshot_sqlite, DB_PATH)
            await get_redis().set(f"{REDIS_PREFIX}dbsnap", data)
        except Exception:
            logging.exception("Не удалось сохранить bot.db в Redis")


async def restore_files_from_redis() -> None:
    """При старте возвращает на диск то, чего там нет (после деплоя диск обычно пустой)."""
    r = get_redis()
    if r is None:
        return
    restored = 0
    async for key in r.scan_iter(match=f"{REDIS_PREFIX}sess:*", count=200):
        key = key.decode() if isinstance(key, bytes) else key
        fname = key.split("sess:", 1)[1]
        if not fname.endswith(".session") or "/" in fname or "\\" in fname or ".." in fname:
            continue
        path = os.path.join(SESSIONS_DIR, fname)
        if os.path.exists(path):
            continue
        blob = await r.get(key)
        if blob:
            with open(path, "wb") as f:
                f.write(blob)
            restored += 1
    if not os.path.exists(DB_PATH):
        blob = await r.get(f"{REDIS_PREFIX}dbsnap")
        if blob:
            with open(DB_PATH, "wb") as f:
                f.write(blob)
            print("💾 bot.db восстановлен из Redis")
    print(f"💾 Сессий восстановлено из Redis: {restored}")


async def flush_all() -> None:
    """Штатная остановка (деплой/SIGTERM): сохраняем всё до последней мелочи."""
    if not REDIS_URL:
        return
    try:
        for uid in list(user_data_db):
            await save_user(uid, force=True)
        await backup_sessions()
        if os.path.exists(DB_PATH):
            data = await asyncio.to_thread(snapshot_sqlite, DB_PATH)
            await get_redis().set(f"{REDIS_PREFIX}dbsnap", data)
        print("💾 Данные сохранены в Redis")
    except Exception:
        logging.exception("flush_all")


# ============================================================
# 💎 ПРЕМИУМ-ЭМОДЗИ И СТИЛИ КНОПОК
# ============================================================
def pe(emoji_id: str, fallback: str) -> str:
    """Премиум-эмодзи для текста сообщений (HTML)."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


BACK_EMOJI_ID = "6039539366177541657"

# --- явные ID премиум-эмодзи (прописаны вручную, не зависят от автозамены) ---
E_GREEN = "5416081784641168838"    # 🟢
E_RED = "5411225014148014586"      # 🔴 (кнопка «Остановить»)
E_OK = "5206607081334906820"       # ✅ (везде)
E_TRASH = "5445267414562389170"    # 🗑
E_FOLDER = "5433653135799228968"   # 📁
E_DOC = "5435970940670320222"      # 📄 / 📋
E_PENCIL = "5395444784611480792"  # вњЏпёЏ
E_PLUS = "5397916757333654639"    # вћ•
E_FORWARD = "5253742260054409879" # вњ‰пёЏ
E_ROTATE = "5345783284653636765"  # 🔄
E_TIMER = "5373236586760651455"   # вЏ±
E_WARN = "5447644880824181073"     # вљ пёЏ
E_WAVE = "5343984088493599366"     # 👋
E_NEXT = "5343802377017252363"     # ⏩ (вместо ▶️)
E_USER = "5373012449597335010"     # 👤
E_PHONE = "5407025283456835913"    # 📱
E_PHONE2 = "5406809207947142040"   # 📲
E_NUM = "6323436631428695574"      # 🔢
E_RED_BULLET = "5398038979217989221"  # 🔴 (маркеры в тексте)
E_CROSS = "5210952531676504517"    # вќЊ
E_PLAY = "5422811933969499922"     # ▶️ (кнопка «Пропустить»)
E_GEAR = "5341715473882955310"     # вљ™пёЏ
E_BAN = "5240241223632954241"      # 🚫
# невидимый маркер в конце текста кнопки: «не красить автоматически» (обычная прозрачная кнопка)
PLAIN_MARK = "\u2060"

OK = pe(E_OK, "вњ”пёЏ")

_BACK_RE = re.compile(r"^[^\w]*\s*(Назад|Главное меню)\s*$", re.IGNORECASE)


def _restyle_back(data: dict) -> None:
    """Любая кнопка «Назад» / «Главное меню» (с любой стрелкой: ◀️ ⬅️ 🔙) →
    синяя + премиум-эмодзи вместо стрелки. Без текста стрелки (одиночная ◀️ в пагинации) не трогаем."""
    text = data.get("text") or ""
    m = _BACK_RE.match(text)
    if m and text.strip() != m.group(1):
        data["text"] = m.group(1)
        data["style"] = "primary"
        data["icon_custom_emoji_id"] = BACK_EMOJI_ID


class InlineKeyboardButton(_TgInlineKeyboardButton):
    def __init__(self, **data):
        _restyle_back(data)
        super().__init__(**data)


class KeyboardButton(_TgKeyboardButton):
    def __init__(self, **data):
        _restyle_back(data)
        super().__init__(**data)


# ============================================================
# 💎 АВТО-ПРЕМИУМ UI: все сообщения и все кнопки
# Любой известный эмодзи в тексте -> премиум, любая inline-кнопка -> цветная
# (с премиум-иконкой, если эмодзи известен). Если Telegram отклонит запрос
# (например, нет прав на премиум-иконки) — сообщение уйдёт в упрощённом виде.
# ============================================================
PREMIUM_IDS = {
    "👋": "5343984088493599366",
    "вљЎ": "5456140674028019486",
    "🔴": "5398038979217989221",
    "👇": "5305522282695768654",
    "🔥": "5389038097860144794",
    "в­ђ": "5438496463044752972",
    "🎟": "5377599075237502153",
    "💳": "5445353829304387411",
    "👤": "5373012449597335010",
    "🤝": "5395732581780040886",
    "🛠": "5863945989127148135",
    "🔨": "5863945989127148135",
    "в„№": "5334544901428229844",
    "📋": "5435970940670320222",
    "📄": "5435970940670320222",
    "🔒": "5296369303661067030",
    "🚀": "5445284980978621387",
    "вћ•": "5397916757333654639",
    "📊": "5231200819986047254",
    "в–¶": "5343802377017252363",
    "вЏ©": "5343802377017252363",
    "🛒": "5312361253610475399",
    "🔑": "5330115548900501467",
    "вќЊ": "5210952531676504517",
    "📱": "5407025283456835913",
    "🔢": "6323436631428695574",
    "📲": "5406809207947142040",
    "🗑": "5445267414562389170",
    "🛡": "5821453562680448557",
    "🎉": "5436040291507247633",
    "👥": "5372926953978341366",
    "💰": "5287231198098117669",
    "💵": "5409048419211682843",
    "💸": "5287231198098117669",
    "📤": "5433614747381538714",
    "🔍": "5188217332748527444",
    "🆓": "5406756500108501710",
    "🤖": "5372981976804366741",
    "вњ‰": "5253742260054409879",
    "💡": "5422439311196834318",
    "вњЏ": "5395444784611480792",
    "🔗": "5271604874419647061",
    "📁": "5433653135799228968",
    "🎯": "5310278924616356636",
    "🫥": "5303543015736883901",
    "🔄": "5345783284653636765",
    "в†©": "5436118790624518351",
    "🌐": "5447410659077661506",
    "🎲": "5384474763827620477",
    "вњ…": "5206607081334906820",
    "вњ”": "5206607081334906820",
    "🟢": "5416081784641168838",
    "вљ ": "5447644880824181073",
    "📅": "5413879192267805083",
    "📢": "5298609030321691620",
}
PREMIUM_IDS.update({
    "🆔": "5334890573281114250",
    "вќ—": "5274099962655816924",
    "🔎": "5188217332748527444",
    "💬": "5443038326535759644",
    "1\ufe0f\u20e3": "5233693563170069641",
    "2\ufe0f\u20e3": "5235822582753664660",
    "3\ufe0f\u20e3": "5235824798956791363",
    "4\ufe0f\u20e3": "5233740739090848096",
    "вљ™": "5341715473882955310",
    "📥": "5433811242135331842",
    "📨": "5433811242135331842",
    "🚫": "5240241223632954241",
    "🔁": "5346269127059196142",
    "🔃": "5346269127059196142",
})

_EMOJI_RE = re.compile("(" + "|".join(map(re.escape, PREMIUM_IDS)) + ")\ufe0f?")
_PROTECTED_RE = re.compile(
    r"(<tg-emoji\b[^>]*>.*?</tg-emoji>|<(?:code|pre)\b[^>]*>.*?</(?:code|pre)>|<[^>]+>)",
    re.DOTALL,
)
_BTN_LEAD_RE = re.compile("^\\s*(" + "|".join(map(re.escape, PREMIUM_IDS)) + ")\ufe0f?\\s*")

# обратная таблица: id -> обычный эмодзи (для упрощённого запасного режима)
REV_IDS = {v: k for k, v in PREMIUM_IDS.items()}
REV_IDS.update({
    BACK_EMOJI_ID: "◀️", E_RED: "🔴", E_GREEN: "🟢", E_NEXT: "⏩",
    E_TRASH: "🗑", E_OK: "✔️", E_FOLDER: "📁", E_DOC: "📋", E_TIMER: "⏱",
})
_TG_EMOJI_RE = re.compile(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", re.DOTALL)


def premiumize_html(text):
    if not text or "<tg-emoji" in text and not _EMOJI_RE.search(_PROTECTED_RE.sub("", text)):
        return text
    parts = _PROTECTED_RE.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = _EMOJI_RE.sub(
            lambda m: f'<tg-emoji emoji-id="{PREMIUM_IDS[m.group(1)]}">{m.group(0)}</tg-emoji>',
            parts[i],
        )
    return "".join(parts)


def degrade_html(text):
    """Запасной режим: убирает премиум-теги, оставляя обычные эмодзи."""
    return _TG_EMOJI_RE.sub(r"\1", text) if isinstance(text, str) else text


def degrade_markup(markup):
    """Запасной режим: убирает премиум-иконки с кнопок (возвращая обычный эмодзи в текст), цвет остаётся."""
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for b in row:
            icon = getattr(b, "icon_custom_emoji_id", None)
            if icon:
                em = REV_IDS.get(icon, "")
                txt = f"{em} {b.text or ''}".strip()
                new_row.append(b.model_copy(update={"icon_custom_emoji_id": None, "text": txt}))
            else:
                new_row.append(b)
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _auto_style(text: str) -> str:
    low = text.lower()
    if any(x in text for x in ("❌", "🗑", "🚫", "⏹")) or "удалить" in low or "поддержка" in low:
        return "danger"
    if text.startswith("вњ…"):
        return "success"
    return "primary"


def premiumize_markup(markup):
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for b in row:
            upd = {}
            if not getattr(b, "icon_custom_emoji_id", None):
                m = _BTN_LEAD_RE.match(b.text or "")
                if m and (b.text or "")[m.end():].strip():
                    upd["icon_custom_emoji_id"] = PREMIUM_IDS[m.group(1)]
                    upd["text"] = (b.text or "")[m.end():]
            if not getattr(b, "style", None) and not (b.text or "").endswith(PLAIN_MARK):
                upd["style"] = _auto_style(b.text or "")
            new_row.append(b.model_copy(update=upd) if upd else b)
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ------------------------------------------------------------
# ✅ Проверка ID премиум-эмодзи при старте.
# Если в клавиатуре есть хотя бы один невалидный ID, Telegram отклоняет
# её целиком и все иконки становятся обычными. Поэтому невалидные ID
# убираются по одному, а остальные остаются премиум.
# ------------------------------------------------------------
VALID_EMOJI_IDS = None  # None = ещё не проверяли


async def validate_premium_ids(bot):
    global VALID_EMOJI_IDS
    ids = sorted(set(PREMIUM_IDS.values()) | set(PAY_EMOJI_IDS) | {
        BACK_EMOJI_ID, E_GREEN, E_RED, E_OK, E_TRASH, E_FOLDER, E_DOC, E_WARN,
        E_WAVE, E_NEXT, E_USER, E_PHONE, E_PHONE2, E_NUM, E_RED_BULLET, E_PENCIL, E_TIMER,
        E_PLUS, E_FORWARD, E_ROTATE, E_CROSS, E_PLAY, E_GEAR, E_BAN,
    })
    valid = set()

    # Сначала проверяем пачкой. Если Telegram отклонит пачку из-за одного ID,
    # проверяем каждый ID отдельно, чтобы один ошибочный эмодзи не отключал остальные.
    try:
        for i in range(0, len(ids), 200):
            stickers = await bot.get_custom_emoji_stickers(ids[i:i + 200])
            valid.update(s.custom_emoji_id for s in stickers)
    except Exception as batch_error:
        logging.warning("Проверка пачкой не прошла, проверяю ID по одному: %s", batch_error)

    # Проверяем по одному все ID, которые не вернулись из пакетного запроса.
    # Так частичный ответ Telegram тоже не отключит остальные рабочие эмодзи.
    for emoji_id in ids:
        if emoji_id in valid:
            continue
        try:
            stickers = await bot.get_custom_emoji_stickers([emoji_id])
            if any(sticker.custom_emoji_id == emoji_id for sticker in stickers):
                valid.add(emoji_id)
        except Exception as e:
            logging.warning("Премиум-эмодзи %s недоступен: %s", emoji_id, e)

    VALID_EMOJI_IDS = valid
    bad = [x for x in ids if x not in valid]
    print("🧪 Невалидные/недоступные ID премиум-эмодзи:", bad or "нет")
    print(f"🧪 Доступно премиум-эмодзи: {len(valid)} из {len(ids)}")


def drop_invalid_html(text):
    if VALID_EMOJI_IDS is None or not isinstance(text, str):
        return text

    def repl(m):
        return m.group(0) if m.group(1) in VALID_EMOJI_IDS else m.group(2)

    return re.sub(r'<tg-emoji emoji-id="(\d+)">(.*?)</tg-emoji>', repl, text, flags=re.DOTALL)


def drop_invalid_markup(markup):
    if VALID_EMOJI_IDS is None or not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for b in row:
            icon = getattr(b, "icon_custom_emoji_id", None)
            if icon and icon not in VALID_EMOJI_IDS:
                em = REV_IDS.get(icon, "")
                new_row.append(b.model_copy(update={
                    "icon_custom_emoji_id": None,
                    "text": f"{em} {b.text or ''}".strip(),
                }))
            else:
                new_row.append(b)
        rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


class PremiumUIMiddleware(BaseRequestMiddleware):
    _warned = False

    async def __call__(self, make_request, bot, method):
        upd = {}
        pm = getattr(method, "parse_mode", None)
        html = isinstance(pm, Default) or str(getattr(pm, "value", pm)).upper() == "HTML"
        if html:
            for attr in ("text", "caption"):
                val = getattr(method, attr, None)
                if isinstance(val, str):
                    upd[attr] = premiumize_html(val)
        rm = getattr(method, "reply_markup", None)
        if isinstance(rm, InlineKeyboardMarkup):
            upd["reply_markup"] = premiumize_markup(rm)
        if not upd:
            return await make_request(bot, method)

        # убираем только невалидные ID, остальные премиум-эмодзи остаются
        if VALID_EMOJI_IDS is not None:
            for k, v in list(upd.items()):
                upd[k] = drop_invalid_markup(v) if k == "reply_markup" else drop_invalid_html(v)

        try:
            res = await make_request(bot, method.model_copy(update=upd))
            sent = upd.get("text") or upd.get("caption") or ""
            if "<tg-emoji" in sent and not PremiumUIMiddleware._warned:
                ents = (getattr(res, "entities", None) or getattr(res, "caption_entities", None) or [])
                if hasattr(res, "message_id") and not any(getattr(en, "type", "") == "custom_emoji" for en in ents):
                    PremiumUIMiddleware._warned = True
                    print("⚠️ Telegram принял сообщение, но УБРАЛ премиум-эмодзи: у бота нет прав на премиум-эмодзи "
                          "(нужны доп. юзернеймы на Fragment). Это ограничение Telegram, не кода.")
            return res
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                raise
            if not PremiumUIMiddleware._warned:
                PremiumUIMiddleware._warned = True
                print(f"⚠️ Премиум-оформление отклонено Telegram: {e}\n"
                      "   Пробую отправить в упрощённом виде. Проверь версию aiogram (>=3.25) и права бота на премиум-эмодзи.")
            # 1) обычные эмодзи, но цвет кнопок сохраняем
            plain = {}
            for k, v in upd.items():
                plain[k] = degrade_markup(v) if k == "reply_markup" else degrade_html(v)
            try:
                return await make_request(bot, method.model_copy(update=plain))
            except TelegramBadRequest as e2:
                if "not modified" in str(e2):
                    raise
            # 2) как есть
            return await make_request(bot, method)


def get_user(user_id: int) -> dict:
    if user_id not in user_data_db:
        user_data_db[user_id] = {
            "has_received_promo": False,
            "promo_used": False,
            "is_active": False,
            "free_plan": False,
            "promo_message_id": None,
            "accounts": [],
            "proxies": {},
            "apis": {},
            "campaigns": [],
            "draft": None,
            "next_id": 1,
            "referrals": [],
            "referred_by": None,
            "ref_buyers": 0,
            "balance": 0.0,
            "joined_at": datetime.now(),
            "username": None,
            "first_name": None,
        }
    return user_data_db[user_id]


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def pbtn(text: str, data: str, icon: str, style: str = None) -> InlineKeyboardButton:
    """Кнопка с явной премиум-иконкой (и цветом, если указан). Текст — без эмодзи."""
    kw = {"text": text, "callback_data": data, "icon_custom_emoji_id": icon}
    if style:
        kw["style"] = style
    return InlineKeyboardButton(**kw)


def acc_btn(phone: str, data: str) -> InlineKeyboardButton:
    """Кнопка с номером аккаунта: перед номером премиум 🟢."""
    return InlineKeyboardButton(text=fmt_phone(phone), callback_data=data, icon_custom_emoji_id=E_GREEN)


def next_btn(data: str) -> InlineKeyboardButton:
    """Кнопка «вперёд» в пагинации: премиум ⏩ (вместо ▶️)."""
    return InlineKeyboardButton(text="Далее", callback_data=data, icon_custom_emoji_id=E_NEXT)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


async def show(target, text: str, markup: InlineKeyboardMarkup):
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                raise
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


def parse_int(text, minimum: int):
    t = (text or "").strip()
    if not re.fullmatch(r"\d{1,7}", t):
        return None
    v = int(t)
    return v if v >= minimum else None


def fmt_interval(s: int) -> str:
    if s < 60:
        return f"{s}с"
    if s < 3600:
        return f"{s // 60}м"
    return f"{s // 3600}С‡"


def main_menu_kb(admin: bool = False) -> InlineKeyboardMarkup:
    def mb(text: str, data: str, emoji_id: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=text, callback_data=data, style="primary", icon_custom_emoji_id=emoji_id
        )

    rows = [
        [
            mb("Мои рассылки", "menu:campaigns", "5435970940670320222"),
            mb("Аккаунт", "menu:account", "5373012449597335010"),
        ],
        [
            mb("Подписка", "menu:subscription", "5445353829304387411"),
            mb("Рефералы", "menu:referrals", "5395732581780040886"),
        ],
        [
            mb("Инструменты", "menu:tools", "5863945989127148135"),
        ],
        [
            mb("Помощь", "menu:help", "5334544901428229844"),
        ],
    ]
    if admin:
        rows.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_text(first_name: str) -> str:
    name = escape(first_name or "друг")
    red = pe(E_RED_BULLET, "🔴")
    return (
        f"{pe('5343984088493599366', '👋')} Привет, <b>{name}</b>!\n\n"
        "Добро пожаловать в <b>AutoSender</b> — инструмент для автоматических "
        "рассылок через Telegram-аккаунты.\n\n"
        f"{pe('5456140674028019486', '⚡')} <b>Что умеет бот:</b>\n"
        f"{red} Рассылка сообщений по чатам и группам\n"
        f"{red} Автоприветствие в личные сообщения\n"
        f"{red} Автоответчик в группах\n"
        f"{red} Гибкое расписание и интервалы\n"
        f"{red} Управление несколькими аккаунтами\n"
        f"{red} Парсер чатов и прогрев аккаунта\n\n"
        f"Выберите раздел ниже {pe('5305522282695768654', '👇')}"
    )


def inactive_sub_text() -> str:
    return (
        "💳 <b>Ваша подписка</b>\n\n"
        "❌ <b>Подписка не активна</b>\n"
        "Для использования всех функций бота необходима подписка.\n\n"
        "<b>Стоимость:</b>\n"
        "🔴 1 день — 0.19 USDT\n"
        "🔴 7 дней — 0.99 USDT\n"
        "🔴 30 дней — 2.99 USDT\n\n"
        "🆓 Или используйте бота бесплатно с рекламной подписью."
    )


def inactive_sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="sub:promo"),
            pbtn("Купить подписку", "pay:methods", "5445353829304387411", "success")
        ],
        [
            InlineKeyboardButton(text="🆓 Использовать бесплатно (с рекламой)", callback_data="sub:free")
        ],
        [
            InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:back")
        ]
    ])


def active_sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="pay:methods")],
        [InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="sub:promo")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:back")],
    ])


def free_plan_text() -> str:
    return (
        "🆓 <b>Бесплатный тариф</b>\n\n"
        "Полный доступ ко всем функциям бота — бесплатно.\n\n"
        "<b>Что включено:</b>\n"
        "🔴 Рассылки по чатам и группам\n"
        "🔴 Автоприветствие в ЛС, автоответчик в группах\n"
        "🔴 До 1 аккаунта\n\n"
        "<b>Ограничения:</b>\n"
        "🔴 К каждому сообщению добавляется подпись:\n"
        "в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ\n"
        "🤖 Отправлено через @CabinetSenderBot\n"
        "🔴 Пересылка сообщений (forward) недоступна\n\n"
        "Купите подписку — и реклама исчезнет автоматически."
    )


def free_plan_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Активировать бесплатный тариф", callback_data="sub:free_on")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:subscription")],
    ])


def is_sub_active(user_info: dict) -> bool:
    expiry = user_info.get("expiry")
    return bool(user_info.get("is_active") and expiry and expiry > datetime.now())


def has_access(user_info: dict) -> bool:
    return is_sub_active(user_info) or bool(user_info.get("free_plan"))


def subscription_screen(user_info: dict):
    if is_sub_active(user_info):
        expiry = user_info["expiry"]
        days_left = (expiry - datetime.now()).days
        text = (
            "💳 <b>Ваша подписка</b>\n\n"
            "✅ <b>Подписка активна</b>\n"
            f"Действует до: {expiry.strftime('%d.%m.%Y %H:%M')}\n"
            f"Осталось дней: {days_left}\n\n"
            "<b>Стоимость продления:</b>\n"
            "🔴 1 день — 0.19 USDT\n"
            "🔴 7 дней — 0.99 USDT\n"
            "🔴 30 дней — 2.99 USDT"
        )
        return text, active_sub_kb()

    user_info["is_active"] = False
    return inactive_sub_text(), inactive_sub_kb()


# ============================================================
# 💳 ОПЛАТА ПОДПИСКИ
# Laveshka · CryptoBot · xRocket · TON / USDT(TON) / USDT(TRC20) напрямую · Telegram Stars
# Звёзды приходят на этого же бота (send_invoice вызывается от его имени).
# Подписки и платежи сохраняются в bot.db и переживают перезапуск.
# ============================================================
pay_router = Router()   # подключается в main() раньше основного router

DB_PATH = os.path.join(DATA_DIR, "bot.db")
INVOICE_TTL = 1800            # сколько секунд действует счёт (30 минут)
POLL_INTERVAL = 5             # как часто проверять оплату, секунд
CRYPTO_POLL_INTERVAL = 10     # для прямых крипто-платежей (меньше нагрузка на API)
CRYPTO_PROVIDERS = ("ton", "usdt_ton", "usdt_trc20")

PLAN_BY_DAYS = {p["days"]: (key, p) for key, p in PLAN_INFO.items()}
# цена в Telegram Stars: 1 USDT = 100 звёзд (0.19 -> 19, 0.99 -> 99, 2.99 -> 299)
STARS_PRICES = {d: max(1, int(round(p["price"] * 100))) for d, (_k, p) in PLAN_BY_DAYS.items()}

# премиум-эмодзи платёжных экранов (входят в проверку validate_premium_ids)
PE_CARD = "5445353829304387411"
PE_CAL = "5413879192267805083"
PE_BANK = "5895356592496320896"
PE_CRYPTOBOT = "5361914370068613491"
PE_XROCKET = "5372951469651702259"
PE_CRYPTO = "5235630047959727475"
PE_GRAM = "5188672371648634636"
PE_STARS = "5438496463044752972"
PE_CHECK = "5386367538735104399"
PE_GEM = "5471952986970267163"
PE_DOLLAR = "6030661990899257068"
PAY_EMOJI_IDS = {
    PE_CARD, PE_CAL, PE_BANK, PE_CRYPTOBOT, PE_XROCKET, PE_CRYPTO,
    PE_GRAM, PE_STARS, PE_CHECK, PE_GEM, PE_DOLLAR,
}


# ============================================================
# 🎁 ПЕРСОНАЛЬНЫЕ СКИДКИ (выдаёт админ; действуют на подписку «1 месяц»)
# ============================================================
DISCOUNT_DAYS = 30            # на какой тариф действует скидка (30 дней = 1 месяц)
DISCOUNT_MIN, DISCOUNT_MAX = 1, 75
DISCOUNT_TTL_HOURS = 48       # сколько часов действует выданная скидка
E_GIFT = "5370781982886220096"
E_HOURGLASS = "5891211339170326418"
PAY_EMOJI_IDS |= {E_GIFT, E_HOURGLASS}


def fmt_ts(ts) -> str:
    """Unix-время -> дата в часовом поясе бота (TIMEZONE_NAME)."""
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, now_local().tzinfo).strftime("%d.%m.%Y %H:%M")


def active_discount(uid) -> int:
    """Процент действующей скидки пользователя (0 — скидки нет или она истекла)."""
    d = (user_data_db.get(uid) or {}).get("discount")
    if d and float(d.get("expires", 0)) > time.time():
        return int(d.get("percent", 0))
    return 0


def price_with_discount(days: int, pct: int) -> Decimal:
    price = Decimal(str(PLAN_BY_DAYS[days][1]["price"]))
    if pct and days == DISCOUNT_DAYS and DISCOUNT_MIN <= pct <= DISCOUNT_MAX:
        price = (price * (100 - pct) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return price


def stars_for(days: int, pct: int = 0) -> int:
    return max(1, int(round(price_with_discount(days, pct) * 100)))


def discount_text(pct: int) -> str:
    return (
        f"{pe(E_GIFT, '🎁')} <b>Персональная скидка {pct}% на подписку!</b>\n\n"
        "Только для вас — код уже активирован, вводить ничего не нужно, "
        "скидка применится автоматически при оформлении покупки.\n\n"
        "Скидка работает при заказе на 1 месяц.\n\n"
        f"{pe(E_HOURGLASS, '⌛️')} <b>Успейте до истечения — предложение действует ограниченное время.</b>"
    )


def discount_kb() -> InlineKeyboardMarkup:
    return kb([InlineKeyboardButton(text="Применить скидку", callback_data="disc:apply", style="primary")])


async def grant_discount(bot: Bot, uid: int, pct: int) -> bool:
    """Записывает скидку пользователю и отправляет ему сообщение. True — сообщение доставлено."""
    ui = user_data_db.get(uid)
    if ui is None:
        ui = get_user(uid)
        ui["joined_at"] = None   # запись создана ради скидки, а не нового пользователя
    ui["discount"] = {
        "percent": int(pct),
        "expires": time.time() + DISCOUNT_TTL_HOURS * 3600,
        "granted_at": time.time(),
    }
    mark_dirty(uid)
    try:
        await bot.send_message(uid, discount_text(int(pct)), reply_markup=discount_kb())
        return True
    except Exception as e:
        logging.warning("Скидка выдана, но сообщение %s не доставлено: %s", uid, e)
        return False


class PayError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def term_text(days: int) -> str:
    return f"{days} {'день' if days == 1 else 'дней'}"


def plan_price(days: int, uid: int = None) -> Decimal:
    """Цена тарифа; если у пользователя есть активная скидка — уже со скидкой."""
    return price_with_discount(days, active_discount(uid) if uid else 0)


# ---------- тексты и клавиатуры ----------

def plans_text(uid: int = None) -> str:
    lines = [f"{pe(PE_CARD, '💳')} <b>Выберите план подписки:</b>\n"]
    for _days, (_k, p) in PLAN_BY_DAYS.items():
        pct = active_discount(uid) if (uid and _days == DISCOUNT_DAYS) else 0
        if pct:
            lines.append(f"{pe(PE_CAL, '📅')} {p['label']} — <s>{p['price']:.2f}</s> "
                         f"{price_with_discount(_days, pct):.2f} USDT (−{pct}%)")
        else:
            lines.append(f"{pe(PE_CAL, '📅')} {p['label']} — {p['price']:.2f} USDT")
    return "\n".join(lines)


def plans_kb() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(
            text=p["label"], callback_data=f"pay:plan:{days}",
            style="primary", icon_custom_emoji_id=PE_CAL,
        )
        for days, (_k, p) in PLAN_BY_DAYS.items()
    ]
    return kb(row, [btn("◀️ Назад", "menu:subscription")])


def payment_text(days: int, uid: int = None) -> str:
    price = plan_price(days, uid)
    pct = active_discount(uid) if (uid and days == DISCOUNT_DAYS) else 0
    lines = [f"{pe(PE_CARD, '💳')} <b>Способ оплаты ({term_text(days)}):</b>\n"]
    if pct:
        until = fmt_ts(user_data_db[uid]['discount']['expires'])
        lines.append(f"{pe(E_GIFT, '🎁')} Персональная скидка {pct}% — до {until}\n")
    if LAVE_API_KEY:
        lines.append(f"{pe(PE_BANK, '🏦')} Laveshka — {price:.2f} USDT (TON)")
    if CRYPTO_PAY_TOKEN:
        fee = f" (+{int(CRYPTOBOT_FEE * 100)}%)" if CRYPTOBOT_FEE else ""
        lines.append(f"{pe(PE_CRYPTOBOT, '👛')} CryptoBot — {price:.2f} USDT{fee}")
    if XROCKET_TOKEN:
        lines.append(f"{pe(PE_XROCKET, '🚀')} xRocket — {price:.2f} USDT")
    lines.append(f"{pe(PE_GRAM, '💎')} Крипта — {price:.2f} USDT (TON, USDT TON)")
    lines.append(f"{pe(PE_STARS, '⭐️')} Telegram Stars — {stars_for(days, pct)}")
    return "\n".join(lines)


def payment_kb(days: int) -> InlineKeyboardMarkup:
    rows = []
    if LAVE_API_KEY:
        rows.append([InlineKeyboardButton(
            text="Laveshka", callback_data=f"pay:m:laveshka:{days}",
            style="success", icon_custom_emoji_id=PE_BANK)])
    row = []
    if CRYPTO_PAY_TOKEN:
        row.append(InlineKeyboardButton(
            text="CryptoBot (USDT)", callback_data=f"pay:m:cryptobot:{days}",
            style="primary", icon_custom_emoji_id=PE_CRYPTOBOT))
    if XROCKET_TOKEN:
        row.append(InlineKeyboardButton(
            text="xRocket (USDT)", callback_data=f"pay:m:xrocket:{days}",
            style="primary", icon_custom_emoji_id=PE_XROCKET))
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(
            text="Крипта", callback_data=f"pay:m:crypto:{days}",
            style="primary", icon_custom_emoji_id=PE_CRYPTO),
        InlineKeyboardButton(
            text="Telegram Stars", callback_data=f"pay:m:stars:{days}",
            style="primary", icon_custom_emoji_id=PE_STARS),
    ])
    rows.append([btn("◀️ Назад", "pay:methods")])
    return kb(*rows)


def crypto_menu_text() -> str:
    return f"{pe(PE_GEM, '💎')} <b>Выберите криптовалюту:</b>"


def crypto_menu_kb(days: int) -> InlineKeyboardMarkup:
    # Чтобы добавить USDT TRC20 — раскомментируйте кнопку (проверка платежа уже реализована)
    return kb(
        [InlineKeyboardButton(text="GRAM(TON)", callback_data=f"pay:cr:gram:{days}",
                              style="success", icon_custom_emoji_id=PE_GRAM)],
        [InlineKeyboardButton(text="$ USDT(TON)", callback_data=f"pay:cr:usdt:{days}", style="success")],
        # [InlineKeyboardButton(text="USDT(TRC20)", callback_data=f"pay:cr:trc:{days}", style="success")],
        [btn("◀️ Назад", f"pay:plan:{days}")],
    )


def invoice_text(method_name: str, amount: str, days: int, fee_note: str = "") -> str:
    return (
        f"{pe(PE_CARD, '💳')} <b>Оплата подписки</b>\n\n"
        f"Сумма: {amount} USDT{fee_note}\n"
        f"Срок: {term_text(days)}\n\n"
        f"Нажмите «Оплатить» для перехода к оплате через {method_name}.\n"
        "После оплаты нажмите «Проверить оплату»."
    )


def invoice_kb(pay_url: str, check_data: str, back_data: str) -> InlineKeyboardMarkup:
    return kb(
        [InlineKeyboardButton(text="Оплатить", url=pay_url, style="success", icon_custom_emoji_id=PE_CARD)],
        [
            InlineKeyboardButton(text="Проверить оплату", callback_data=check_data,
                                 style="primary", icon_custom_emoji_id=PE_CHECK),
            InlineKeyboardButton(text="🆘 Поддержка", url=SUPPORT_URL, style="danger"),
        ],
        [btn("◀️ Назад", back_data)],
    )


def crypto_pay_kb(pay_url, check_data: str, back_data: str) -> InlineKeyboardMarkup:
    rows = []
    if pay_url:
        rows.append([InlineKeyboardButton(text="🦆 Оплатить через Tonkeeper", url=pay_url, style="success")])
    rows.append([
        InlineKeyboardButton(text="✅ Проверить оплату", callback_data=check_data, style="primary"),
        InlineKeyboardButton(text="🆘 Поддержка", url=SUPPORT_URL, style="danger"),
    ])
    rows.append([btn("◀️ Назад", back_data)])
    return kb(*rows)


# ---------- база данных (подписки, счета, платежи) ----------

def db_exec(sql, params=(), fetch=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        if sql.lstrip()[:6].upper() != "SELECT":
            request_db_backup()
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
    finally:
        conn.close()


def init_payments_db():
    db_exec(
        "CREATE TABLE IF NOT EXISTS subscriptions ("
        "user_id INTEGER PRIMARY KEY, expires_at INTEGER NOT NULL)"
    )
    db_exec(
        "CREATE TABLE IF NOT EXISTS invoices ("
        "id TEXT PRIMARY KEY, order_id TEXT, user_id INTEGER, days INTEGER, "
        "amount TEXT, chat_id INTEGER, message_id INTEGER, "
        "status TEXT, created_at INTEGER, provider TEXT DEFAULT 'laveshka')"
    )
    # журнал оплат; ref (id счёта или id платежа Stars) уникален — защита от двойной выдачи
    db_exec(
        "CREATE TABLE IF NOT EXISTS payments ("
        "ref TEXT PRIMARY KEY, user_id INTEGER, days INTEGER, price REAL, "
        "provider TEXT, created_at INTEGER)"
    )
    # транзакции блокчейна, уже засчитанные за какой-то счёт
    db_exec(
        "CREATE TABLE IF NOT EXISTS crypto_txs ("
        "tx_id TEXT PRIMARY KEY, invoice_id TEXT, created_at INTEGER)"
    )
    try:   # скидка, с которой создан счёт (для старых баз — добавляем колонку)
        db_exec("ALTER TABLE invoices ADD COLUMN discount INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass


def save_sub(uid: int):
    """Записывает срок подписки пользователя в bot.db (чтобы она пережила перезапуск)."""
    info = user_data_db.get(uid)
    if not info:
        return
    mark_dirty(uid)
    exp = info.get("expiry")
    ts = int(exp.timestamp()) if exp else 0
    db_exec(
        "INSERT INTO subscriptions(user_id, expires_at) VALUES(?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at",
        (uid, ts),
    )


def load_saved_subs():
    """При старте возвращает активные подписки в память и пересчитывает статистику выручки."""
    now = int(time.time())
    for row in db_exec("SELECT user_id, expires_at FROM subscriptions", fetch="all") or []:
        if row["expires_at"] > now:
            info = get_user(row["user_id"])
            info["expiry"] = datetime.fromtimestamp(row["expires_at"])
            info["is_active"] = True
    for row in db_exec("SELECT days, price FROM payments", fetch="all") or []:
        plan = PLAN_BY_DAYS.get(row["days"])
        if plan:
            admin_stats["purchases"][plan[0]] = admin_stats["purchases"].get(plan[0], 0) + 1
        admin_stats["revenue"] += float(row["price"] or 0)


def get_invoice_row(invoice_id: str):
    return db_exec("SELECT * FROM invoices WHERE id=?", (invoice_id,), "one")


def save_invoice(invoice_id, order_id, call: CallbackQuery, days, amount, provider):
    discount = active_discount(call.from_user.id) if days == DISCOUNT_DAYS else 0
    db_exec(
        "INSERT INTO invoices(id, order_id, user_id, days, amount, chat_id, message_id, status, created_at, provider, discount) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (invoice_id, order_id, call.from_user.id, days, amount,
         call.message.chat.id, call.message.message_id, "pending", int(time.time()), provider, discount),
    )


def fulfill_purchase(uid: int, days: int, provider: str, ref: str, discount: int = 0):
    """Идемпотентно выдаёт подписку за оплату, пишет статистику и реферальный бонус.
    Возвращает (срок_окончания, id_реферера, бонус, новая_ли_оплата)."""
    info = get_user(uid)
    if db_exec("SELECT 1 FROM payments WHERE ref=?", (ref,), "one"):
        return info.get("expiry"), None, 0.0, False   # этот платёж уже был засчитан

    key, plan = PLAN_BY_DAYS[days]
    pct = int(discount or 0) if days == DISCOUNT_DAYS else 0
    price = float(price_with_discount(days, pct))   # реально оплаченная сумма
    db_exec(
        "INSERT INTO payments(ref, user_id, days, price, provider, created_at) VALUES(?,?,?,?,?,?)",
        (ref, uid, days, price, provider, int(time.time())),
    )
    grant_sub(info, days)
    if pct:   # скидка использована
        info.pop("discount", None)
        info["discount_used"] = pct
    save_sub(uid)
    admin_stats["purchases"][key] = admin_stats["purchases"].get(key, 0) + 1
    admin_stats["revenue"] += price

    ref_id, bonus = info.get("referred_by"), 0.0
    if ref_id and ref_id in user_data_db:
        refinfo = user_data_db[ref_id]
        bonus = round(price * REF_PERCENT / 100.0, 4)
        refinfo["balance"] += bonus
        mark_dirty(ref_id)
        if not info.get("ref_counted"):
            info["ref_counted"] = True
            refinfo["ref_buyers"] += 1
    return info["expiry"], ref_id, bonus, True


async def notify_referrer(bot: Bot, ref_id, bonus: float):
    if not ref_id or bonus <= 0:
        return
    try:
        await bot.send_message(ref_id, f"🤝 Ваш реферал купил подписку. Начислено: {bonus:.2f} USDT")
    except Exception:
        pass


# ---------- HTTP-клиенты платёжных систем ----------

_http = None
_inv_locks = {}
_tasks = set()
# для http-прокси адрес передаётся в каждый запрос к платёжным API
REQ_PROXY = PROXY if PROXY and PROXY.startswith("http") else None


def get_http():
    global _http
    if _http is None or _http.closed:
        timeout = aiohttp.ClientTimeout(total=12)   # короче, чем живёт нажатие кнопки
        connector = None
        if PROXY and PROXY.startswith("socks"):
            from aiohttp_socks import ProxyConnector  # pip install aiohttp-socks
            connector = ProxyConnector.from_url(PROXY)
        _http = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _http


async def safe_alert(call: CallbackQuery, text: str):
    """Показать ошибку; если кнопка уже «протухла» — отдельным сообщением."""
    try:
        await call.answer(text, show_alert=True)
    except Exception:
        try:
            await call.message.answer(text)
        except Exception:
            logging.exception("Не удалось показать ошибку пользователю")


async def crypto_request(method: str, params=None):
    async with get_http().post(
        f"{CRYPTO_PAY_BASE}/{method}",
        json=params or {},
        headers={"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN},
        proxy=REQ_PROXY,
    ) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise PayError("bad_response", f"CryptoBot ответил HTTP {resp.status}")
    if not data.get("ok"):
        err = data.get("error") or {}
        name = err.get("name", "error") if isinstance(err, dict) else str(err)
        raise PayError(name, f"CryptoBot: {name}")
    return data["result"]


async def xrocket_request(method: str, path: str, body=None, params=None):
    async with get_http().request(
        method, XROCKET_BASE + path, json=body, params=params, proxy=REQ_PROXY,
        headers={"Authorization": f"Bearer {XROCKET_TOKEN}", "Accept": "application/json"},
    ) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise PayError("bad_response", f"xRocket ответил HTTP {resp.status}")
        if resp.status >= 300:
            d = data if isinstance(data, dict) else {}
            code = str(d.get("type", "error")).split("/")[-1]
            msg = d.get("detail") or d.get("title") or f"HTTP {resp.status}"
            raise PayError(code, f"xRocket: {msg}")
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data


async def lave_request(method: str, path: str, body=None):
    async with get_http().request(
        method, LAVE_BASE + path, json=body, headers={"X-Api-Key": LAVE_API_KEY}, proxy=REQ_PROXY,
    ) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise PayError("bad_response", f"Lave Pay ответил HTTP {resp.status}")
    if not data.get("ok"):
        err = data.get("error") or {}
        raise PayError(err.get("code", "error"), err.get("message", "Ошибка Lave Pay"))
    return data["data"]


# ---------- прямая крипта: курс, API блокчейнов, проверка ----------

_ton_rate_cache = {"rate": None, "ts": 0}


async def get_ton_rate() -> Decimal:
    """Курс 1 TON в USDT (кэш на 60 секунд)."""
    if _ton_rate_cache["rate"] and time.time() - _ton_rate_cache["ts"] < 60:
        return _ton_rate_cache["rate"]

    rate = None
    try:
        async with get_http().get(
            "https://tonapi.io/v2/rates", params={"tokens": "ton", "currencies": "usd"}
        ) as resp:
            data = await resp.json(content_type=None)
        rate = Decimal(str(data["rates"]["TON"]["prices"]["USD"]))
    except Exception as e:
        logging.warning("tonapi rates не отдал курс: %r", e)

    if not rate:
        try:
            async with get_http().get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "the-open-network", "vs_currencies": "usd"},
            ) as resp:
                data = await resp.json(content_type=None)
            rate = Decimal(str(data["the-open-network"]["usd"]))
        except Exception as e:
            logging.warning("coingecko не отдал курс: %r", e)

    if not rate or rate <= 0:
        raise PayError("rate", "Не удалось получить курс TON")
    _ton_rate_cache.update(rate=rate, ts=time.time())
    return rate


async def toncenter_get(path: str, params: dict):
    headers = {"X-API-Key": TONCENTER_KEY} if TONCENTER_KEY else {}
    async with get_http().get(TONCENTER_BASE + path, params=params, headers=headers) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise PayError("bad_response", f"TON Center ответил HTTP {resp.status}")
        if resp.status >= 300:
            raise PayError("toncenter", f"TON Center: HTTP {resp.status} {str(data)[:200]}")
    return data


async def trongrid_get(path: str, params: dict):
    headers = {"TRON-PRO-API-KEY": TRONGRID_KEY} if TRONGRID_KEY else {}
    async with get_http().get(TRONGRID_BASE + path, params=params, headers=headers) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            raise PayError("bad_response", f"TronGrid ответил HTTP {resp.status}")
        if resp.status >= 300:
            raise PayError("trongrid", f"TronGrid: HTTP {resp.status} {str(data)[:200]}")
    return data


def claim_tx(tx_id: str, invoice_id: str) -> bool:
    """Закрепляет транзакцию за счётом. False — её уже засчитали за другой счёт."""
    row = db_exec("SELECT invoice_id FROM crypto_txs WHERE tx_id=?", (tx_id,), "one")
    if row:
        return row["invoice_id"] == invoice_id
    try:
        db_exec(
            "INSERT INTO crypto_txs(tx_id, invoice_id, created_at) VALUES(?,?,?)",
            (tx_id, invoice_id, int(time.time())),
        )
    except sqlite3.IntegrityError:
        return False
    return True


async def check_ton_payment(row) -> bool:
    """Обычные TON: ищем входящий перевод с нужным комментарием и суммой."""
    expected_nano = int(Decimal(row["amount"]) * 10 ** 9)
    data = await toncenter_get(
        "/transactions", {"account": TON_WALLET_GRAM, "limit": 50, "sort": "desc"},
    )
    for tx in data.get("transactions", []):
        msg = tx.get("in_msg") or {}
        if not msg.get("source"):
            continue  # внешнее сообщение, а не перевод
        if (tx.get("description") or {}).get("aborted"):
            continue
        if int(tx.get("now", 0)) < row["created_at"] - 60:
            continue
        decoded = (msg.get("message_content") or {}).get("decoded") or {}
        if str(decoded.get("comment", "")).strip() != row["order_id"]:
            continue
        if int(msg.get("value") or 0) < expected_nano:
            continue
        if claim_tx(tx["hash"], row["id"]):
            return True
    return False


async def check_usdt_ton_payment(row) -> bool:
    """USDT в сети TON: ищем входящий джеттон-перевод точно на нашу сумму."""
    expected = int(Decimal(row["amount"]) * 10 ** 6)
    data = await toncenter_get(
        "/jetton/transfers",
        {"owner_address": TON_WALLET_USDT, "direction": "in", "limit": 50, "sort": "desc"},
    )
    for t in data.get("jetton_transfers", []):
        master = str(t.get("jetton_master", ""))
        if not (master.upper().endswith(USDT_TON_MASTER_HEX) or master == USDT_TON_MASTER):
            continue
        if int(t.get("transaction_now", 0)) < row["created_at"] - 60:
            continue
        if int(t.get("amount") or 0) != expected:
            continue
        if claim_tx(t["transaction_hash"], row["id"]):
            return True
    return False


async def check_trc20_payment(row) -> bool:
    """USDT TRC20: ищем входящий перевод точно на нашу сумму."""
    expected = int(Decimal(row["amount"]) * 10 ** 6)
    data = await trongrid_get(
        f"/v1/accounts/{TRON_WALLET}/transactions/trc20",
        {
            "only_to": "true",
            "limit": 50,
            "contract_address": USDT_TRC20_CONTRACT,
            "min_timestamp": (row["created_at"] - 60) * 1000,
            "order_by": "block_timestamp,desc",
        },
    )
    for t in data.get("data", []):
        if t.get("to") != TRON_WALLET:
            continue
        if (t.get("token_info") or {}).get("address") != USDT_TRC20_CONTRACT:
            continue
        if int(t.get("value") or 0) != expected:
            continue
        if claim_tx(t["transaction_id"], row["id"]):
            return True
    return False


async def fetch_invoice_state(row):
    """Спрашивает у платёжной системы статус счёта.
    Возвращает (status, ok): status — paid / expired / cancelled / pending;
    ok — совпали ли заказ и сумма с тем, что мы выставляли."""
    provider = row["provider"] or "laveshka"

    if provider in CRYPTO_PROVIDERS:
        if provider == "ton":
            found = await check_ton_payment(row)
        elif provider == "usdt_ton":
            found = await check_usdt_ton_payment(row)
        else:
            found = await check_trc20_payment(row)
        if found:
            return "paid", True
        if time.time() > row["created_at"] + INVOICE_TTL:
            return "expired", True
        return "pending", True

    if provider == "cryptobot":
        res = await crypto_request("getInvoices", {"invoice_ids": row["id"][3:]})
        items = res.get("items", []) if isinstance(res, dict) else res
        if not items:
            return "pending", True
        inv = items[0]
        ok = (
            inv.get("payload") == row["order_id"]
            and inv.get("asset") == "USDT"
            and Decimal(str(inv.get("amount"))) == Decimal(row["amount"])
        )
        return inv.get("status"), ok

    if provider == "xrocket":
        inv = await xrocket_request("GET", "/api/v1/invoice", params={"invoiceId": row["id"][3:]})
        ok = (
            inv.get("clientInvoiceId") == row["order_id"]
            and inv.get("priceCurrency") == "USDT"
            and Decimal(str(inv.get("priceAmount"))) == Decimal(row["amount"])
        )
        status = inv.get("status")
        if status in ("active", "partially_paid"):
            status = "pending"
        return status, ok

    inv = await lave_request("GET", f"/invoices/{row['id']}")
    ok = (
        inv.get("order_id") == row["order_id"]
        and Decimal(str(inv.get("amount"))) == Decimal(row["amount"])
    )
    return inv.get("status"), ok


async def process_invoice(bot: Bot, invoice_id: str) -> str:
    """Проверяет счёт и при оплате выдаёт подписку.
    Возвращает: paid (оплачен), done (уже был обработан), pending, expired, cancelled, mismatch."""
    lock = _inv_locks.setdefault(invoice_id, asyncio.Lock())
    async with lock:
        row = get_invoice_row(invoice_id)
        if row is None:
            return "cancelled"
        if row["status"] == "paid":
            return "done"
        if row["status"] != "pending":
            return row["status"]

        status, ok = await fetch_invoice_state(row)

        if status == "paid":
            if not ok:
                logging.error("Счёт %s оплачен, но не совпал заказ/сумма", invoice_id)
                db_exec("UPDATE invoices SET status='mismatch' WHERE id=?", (invoice_id,))
                return "mismatch"
            _exp, ref_id, bonus, fresh = fulfill_purchase(
                row["user_id"], row["days"], row["provider"] or "laveshka", row["id"], (row["discount"] or 0)
            )
            db_exec("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))
            if fresh:
                await notify_referrer(bot, ref_id, bonus)
            return "paid"

        if status in ("expired", "cancelled"):
            db_exec("UPDATE invoices SET status=? WHERE id=?", (status, invoice_id))
            return status
        return "pending"


def to_menu_kb() -> InlineKeyboardMarkup:
    return kb([InlineKeyboardButton(text="В меню", callback_data="menu:back", style="primary")])


async def notify_paid(bot: Bot, row):
    exp = get_user(row["user_id"]).get("expiry")
    try:
        await bot.edit_message_reply_markup(
            chat_id=row["chat_id"], message_id=row["message_id"], reply_markup=None
        )
    except Exception:
        pass
    await bot.send_message(
        row["chat_id"],
        f"✅ Оплата получена!\n\nПодписка активна до {fmt_dt(exp)}.",
        reply_markup=to_menu_kb(),
    )


async def notify_closed(bot: Bot, row, status: str):
    text = "⌛ Счёт истёк. Создайте новый, если хотите оплатить." if status == "expired" else "Счёт отменён."
    try:
        await bot.edit_message_text(
            text, chat_id=row["chat_id"], message_id=row["message_id"],
            reply_markup=kb([btn("◀️ Назад", "pay:methods")]),
        )
    except Exception:
        pass


async def watch_invoice(bot: Bot, invoice_id: str):
    """Фоном проверяет счёт, пока он не оплачен или не истёк."""
    row = get_invoice_row(invoice_id)
    if row is None:
        return
    interval = CRYPTO_POLL_INTERVAL if row["provider"] in CRYPTO_PROVIDERS else POLL_INTERVAL
    deadline = row["created_at"] + INVOICE_TTL + 120
    while time.time() < deadline:
        await asyncio.sleep(interval)
        try:
            result = await process_invoice(bot, invoice_id)
        except Exception as e:
            logging.warning("Проверка счёта %s не удалась: %r", invoice_id, e)
            continue
        row = get_invoice_row(invoice_id)
        if result == "paid":
            await notify_paid(bot, row)
            return
        if result in ("expired", "cancelled"):
            await notify_closed(bot, row, result)
            return
        if result in ("done", "mismatch"):
            return


def start_watch(bot: Bot, invoice_id: str):
    task = asyncio.create_task(watch_invoice(bot, invoice_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def resume_pending_invoices(bot: Bot):
    """После перезапуска продолжаем следить за неоплаченными счетами."""
    for row in db_exec("SELECT id FROM invoices WHERE status='pending'", fetch="all") or []:
        start_watch(bot, row["id"])


# ---------- создание счетов ----------

def new_order_id(user_id: int, days: int) -> str:
    return f"sub_{user_id}_{days}_{int(time.time())}"


async def create_laveshka_invoice(call: CallbackQuery, days: int):
    amount = f"{plan_price(days, call.from_user.id):.2f}"
    user_id = call.from_user.id
    order_id = new_order_id(user_id, days)
    try:
        inv = await lave_request("POST", "/invoices", {
            "amount": amount,
            "description": f"Подписка на {term_text(days)}",
            "order_id": order_id,
            "payload": json.dumps({"user_id": user_id, "days": days}),
            "accept": ["USDT", "GRAM"],
            "ttl": INVOICE_TTL,
        })
    except PayError as e:
        logging.error("Не удалось создать счёт Laveshka: %s %s", e.code, e.message)
        await safe_alert(call, f"Не удалось создать счёт: {e.message}")
        return
    except Exception as e:
        logging.exception("Ошибка связи с Lave Pay: %r", e)
        await safe_alert(call, "Нет связи с Laveshka, попробуйте позже")
        return

    save_invoice(inv["id"], order_id, call, days, amount, "laveshka")
    await show(
        call, invoice_text("Laveshka", amount, days, " (USDT или TON)"),
        invoice_kb(inv["pay_url"], f"pchk:{inv['id']}", f"pay:plan:{days}"),
    )
    await call.answer()
    start_watch(call.bot, inv["id"])


async def create_cryptobot_invoice(call: CallbackQuery, days: int):
    price = plan_price(days, call.from_user.id)
    to_pay = (price * (1 + CRYPTOBOT_FEE)).quantize(Decimal("0.01"), rounding=ROUND_UP)
    amount = f"{to_pay:.2f}"
    user_id = call.from_user.id
    order_id = new_order_id(user_id, days)
    try:
        inv = await crypto_request("createInvoice", {
            "currency_type": "crypto",
            "asset": "USDT",
            "amount": amount,
            "description": f"Подписка на {term_text(days)}",
            "payload": order_id,
            "allow_comments": False,
            "expires_in": INVOICE_TTL,
        })
    except PayError as e:
        logging.error("Не удалось создать счёт CryptoBot: %s", e.message)
        await safe_alert(call, f"Не удалось создать счёт: {e.message}")
        return
    except Exception as e:
        logging.exception("Ошибка связи с CryptoBot: %r", e)
        await safe_alert(call, "Нет связи с CryptoBot, попробуйте позже")
        return

    invoice_id = f"cb_{inv['invoice_id']}"
    pay_url = inv.get("bot_invoice_url") or inv.get("pay_url")
    save_invoice(invoice_id, order_id, call, days, amount, "cryptobot")
    fee_note = f" (+{int(CRYPTOBOT_FEE * 100)}%)" if CRYPTOBOT_FEE else ""
    await show(
        call, invoice_text("CryptoBot", f"{price:.2f}", days, fee_note),
        invoice_kb(pay_url, f"pchk:{invoice_id}", f"pay:plan:{days}"),
    )
    await call.answer()
    start_watch(call.bot, invoice_id)


async def create_xrocket_invoice(call: CallbackQuery, days: int):
    amount = f"{plan_price(days, call.from_user.id):.2f}"
    user_id = call.from_user.id
    order_id = new_order_id(user_id, days)
    try:
        inv = await xrocket_request("POST", "/api/v1/invoices", {
            "priceAmount": amount,
            "priceCurrency": "USDT",
            "clientInvoiceId": order_id,
            "description": f"Подписка на {term_text(days)}",
            "expiresIn": INVOICE_TTL * 1000,   # в миллисекундах
        })
    except PayError as e:
        logging.error("Не удалось создать счёт xRocket: %s %s", e.code, e.message)
        await safe_alert(call, f"Не удалось создать счёт: {e.message}")
        return
    except Exception as e:
        logging.exception("Ошибка связи с xRocket: %r", e)
        await safe_alert(call, "Нет связи с xRocket, попробуйте позже")
        return

    pay_url = (inv.get("links") or {}).get("telegramBotLink")
    if not pay_url or not inv.get("id"):
        logging.error("xRocket вернул неожиданный ответ: %r", inv)
        await safe_alert(call, "xRocket не вернул ссылку на оплату")
        return

    invoice_id = f"xr_{inv['id']}"
    save_invoice(invoice_id, order_id, call, days, amount, "xrocket")
    await show(
        call, invoice_text("xRocket", amount, days),
        invoice_kb(pay_url, f"pchk:{invoice_id}", f"pay:plan:{days}"),
    )
    await call.answer()
    start_watch(call.bot, invoice_id)


def fmt_dec(d: Decimal) -> str:
    return format(d.normalize(), "f")


def new_order_code(days: int) -> str:
    """Короткий уникальный код (он же комментарий к платежу), вида 10204-2."""
    while True:
        code = f"{random.randint(10000, 99999)}-{days}"
        if not db_exec("SELECT 1 FROM invoices WHERE order_id=?", (code,), "one"):
            return code


def unique_amount(provider: str, price: Decimal) -> Decimal:
    """Цена + случайный «хвост» (до 0.009999), чтобы суммы разных неоплаченных
    счетов не совпадали — по ней бот узнаёт платёж."""
    for _ in range(200):
        amount = price + Decimal(random.randint(1, 9999)) / Decimal(10 ** 6)
        busy = db_exec(
            "SELECT 1 FROM invoices WHERE provider=? AND amount=? AND status='pending'",
            (provider, fmt_dec(amount)), "one",
        )
        if not busy:
            return amount
    raise PayError("busy", "Не удалось подобрать уникальную сумму")


def tonkeeper_url(address: str, nano: int, comment: str, jetton: str = None) -> str:
    q = {"amount": nano, "text": comment}
    if jetton:
        q["jetton"] = jetton
    return f"https://app.tonkeeper.com/transfer/{address}?{urlencode(q)}"


async def create_crypto_invoice(call: CallbackQuery, days: int, kind: str):
    price = plan_price(days, call.from_user.id)
    order_id = new_order_code(days)

    try:
        if kind == "gram":
            provider = "ton"
            amount = (price / await get_ton_rate()).quantize(Decimal("0.0001"), rounding=ROUND_UP)
        elif kind == "usdt":
            provider = "usdt_ton"
            amount = unique_amount(provider, price)
        else:
            provider = "usdt_trc20"
            amount = unique_amount(provider, price)
    except Exception as e:
        logging.error("Крипта: не удалось создать счёт: %r", e)
        await call.answer("Не удалось создать счёт, попробуйте позже", show_alert=True)
        return

    amount_s = fmt_dec(amount)
    invoice_id = f"tx_{order_id}"
    save_invoice(invoice_id, order_id, call, days, amount_s, provider)
    comment_line = f"<code>Комментарий: {order_id}</code>"

    if kind == "gram":
        text = (
            f"{pe(PE_GRAM, '💎')} Оплата подписки через GRAM(<b>TON</b>)\n\n"
            f"Сумма: <code>{amount_s} GRAM(TON)</code> (≈ {price:.2f} USDT)\n"
            f"Срок: {term_text(days)}\n\n"
            f"Кошелёк: <code>{TON_WALLET_GRAM}</code>\n"
            f"{comment_line}\n\n"
            "Нажмите кнопку ниже для оплаты через Tonkeeper.\n"
            "Важно: комментарий должен совпадать точно!\n\n"
            "После оплаты нажмите «Проверить оплату»."
        )
        pay_url = tonkeeper_url(TON_WALLET_GRAM, int(amount * 10 ** 9), order_id)
    elif kind == "usdt":
        text = (
            "$ Оплата подписки через USDT (сеть <b>TON</b>)\n\n"
            f"Сумма: <code>{amount_s} USDT</code>\n"
            f"{comment_line}\n\n"
            f"Срок: {term_text(days)}\n\n"
            f"Кошелёк (сеть <b>TON</b>): <code>{TON_WALLET_USDT}</code>\n\n"
            f"Важно: отправьте ровно <code>{amount_s} USDT</code> в сети <b>TON</b>, "
            "все знаки после запятой — по ней система узнаёт именно ваш платёж. "
            "Другая сумма или другая сеть не будут засчитаны.\n\n"
            "После оплаты нажмите «Проверить оплату»."
        )
        pay_url = tonkeeper_url(TON_WALLET_USDT, int(amount * 10 ** 6), order_id, jetton=USDT_TON_MASTER)
    else:  # trc20
        text = (
            f"{pe(PE_DOLLAR, '💵')} Оплата подписки через USDT (TRC20)\n\n"
            f"Сумма: <code>{amount_s} USDT</code>\n"
            f"Срок: {term_text(days)}\n\n"
            f"Кошелёк (сеть TRON / TRC20): <code>{TRON_WALLET}</code>\n\n"
            f"Важно: отправьте ровно <code>{amount_s} USDT</code>, "
            "все знаки после запятой — по ней система узнаёт именно ваш платёж. "
            "Другая сумма не будет засчитана.\n\n"
            "После оплаты нажмите «Проверить оплату»."
        )
        pay_url = None   # Tonkeeper не работает с сетью TRON

    await show(call, text, crypto_pay_kb(pay_url, f"pchk:{invoice_id}", f"pay:m:crypto:{days}"))
    await call.answer()
    start_watch(call.bot, invoice_id)


async def create_stars_invoice(call: CallbackQuery, days: int):
    """Счёт в Telegram Stars выставляет этот же бот — звёзды приходят на него."""
    pct = active_discount(call.from_user.id) if days == DISCOUNT_DAYS else 0
    stars = stars_for(days, pct)
    term = term_text(days)
    payload = f"stars_{call.from_user.id}_{days}_{pct}_{int(time.time())}"
    try:
        await call.bot.send_invoice(
            chat_id=call.message.chat.id,
            title="Подписка",
            description=f"Подписка на {term}",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=f"Подписка на {term}", amount=stars)],
            provider_token="",   # для Stars токен провайдера пустой
        )
    except Exception as e:
        logging.error("Не удалось создать счёт Stars: %r", e)
        await call.answer("Не удалось создать счёт, попробуйте позже", show_alert=True)
        return
    await call.answer()


# ---------- хендлеры ----------

@pay_router.callback_query(F.data == "pay:methods")
async def pay_methods_handler(call: CallbackQuery):
    """Сюда ведут кнопки «Купить / Продлить подписку»: сначала выбор плана."""
    await show(call, plans_text(call.from_user.id), plans_kb())
    await call.answer()


@pay_router.callback_query(F.data.startswith("pay:plan:"))
async def pay_plan_handler(call: CallbackQuery):
    try:
        days = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        days = 0
    if days not in PLAN_BY_DAYS:
        await call.answer("Неизвестный план", show_alert=True)
        return
    await show(call, payment_text(days, call.from_user.id), payment_kb(days))
    await call.answer()


@pay_router.callback_query(F.data.startswith("pay:m:"))
async def pay_method_handler(call: CallbackQuery):
    try:
        _, _, method, days_s = call.data.split(":")
        days = int(days_s)
    except ValueError:
        await call.answer("Неизвестный вариант", show_alert=True)
        return
    if days not in PLAN_BY_DAYS:
        await call.answer("Неизвестный план", show_alert=True)
        return

    if method == "laveshka" and LAVE_API_KEY:
        await create_laveshka_invoice(call, days)
    elif method == "cryptobot" and CRYPTO_PAY_TOKEN:
        await create_cryptobot_invoice(call, days)
    elif method == "xrocket" and XROCKET_TOKEN:
        await create_xrocket_invoice(call, days)
    elif method == "crypto":
        await show(call, crypto_menu_text(), crypto_menu_kb(days))
        await call.answer()
    elif method == "stars":
        await create_stars_invoice(call, days)
    else:
        await call.answer("Этот способ оплаты сейчас недоступен", show_alert=True)


@pay_router.callback_query(F.data.startswith("pay:cr:"))
async def pay_crypto_handler(call: CallbackQuery):
    # pay:cr:gram:7 / pay:cr:usdt:30 / pay:cr:trc:1
    try:
        _, _, kind, days_s = call.data.split(":")
        days = int(days_s)
    except ValueError:
        await call.answer("Неизвестный вариант", show_alert=True)
        return
    if days not in PLAN_BY_DAYS or kind not in ("gram", "usdt", "trc"):
        await call.answer("Неизвестный вариант", show_alert=True)
        return
    await create_crypto_invoice(call, days, kind)


@pay_router.callback_query(F.data.startswith("pchk:"))
async def pay_check_handler(call: CallbackQuery):
    invoice_id = call.data[5:]
    row = get_invoice_row(invoice_id)
    if row is None or row["user_id"] != call.from_user.id:
        await call.answer("Счёт не найден", show_alert=True)
        return
    try:
        result = await process_invoice(call.bot, invoice_id)
    except Exception as e:
        logging.warning("Проверка счёта %s не удалась: %r", invoice_id, e)
        await call.answer("Не удалось проверить оплату, попробуйте ещё раз", show_alert=True)
        return

    row = get_invoice_row(invoice_id)
    if result == "paid":
        await notify_paid(call.bot, row)
        await call.answer()
    elif result == "done":
        await call.answer("Этот счёт уже оплачен ✅", show_alert=True)
    elif result in ("expired", "cancelled"):
        await notify_closed(call.bot, row, result)
        await call.answer()
    elif result == "mismatch":
        await call.answer("Оплата не прошла проверку. Напишите в поддержку.", show_alert=True)
    else:
        await call.answer("Оплата пока не поступила", show_alert=True)


@pay_router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    # Telegram ждёт ответ в течение 10 секунд
    try:
        parts = query.invoice_payload.split("_")
        uid, days = parts[1], parts[2]
        pct = int(parts[3]) if len(parts) == 5 else 0
        valid = (
            0 <= pct <= DISCOUNT_MAX
            and
            query.currency == "XTR"
            and int(uid) == query.from_user.id
            and int(days) in PLAN_BY_DAYS
            and query.total_amount == stars_for(int(days), pct)
        )
    except Exception:
        valid = False
    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Счёт недействителен, создайте новый.")


@pay_router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    sp = message.successful_payment
    try:
        parts = sp.invoice_payload.split("_")
        uid, days = int(parts[1]), int(parts[2])
        pct = int(parts[3]) if len(parts) == 5 else 0
    except Exception:
        logging.error("Stars: странный payload %r", sp.invoice_payload)
        return

    if (
        sp.currency != "XTR"
        or uid != message.from_user.id
        or days not in PLAN_BY_DAYS
        or sp.total_amount != stars_for(days, pct)
    ):
        logging.error("Stars: платёж не прошёл проверку: %r", sp)
        try:
            await message.bot.send_message(
                ADMIN_ID,
                f"⚠️ Платёж Stars не прошёл проверку\nuser: {message.from_user.id}\n"
                f"charge_id: <code>{escape(sp.telegram_payment_charge_id)}</code>",
            )
        except Exception:
            pass
        return

    exp, ref_id, bonus, fresh = fulfill_purchase(uid, days, "stars", sp.telegram_payment_charge_id, pct)
    if not fresh:
        return   # этот платёж уже был обработан
    await notify_referrer(message.bot, ref_id, bonus)
    await message.answer(
        f"✅ Оплата получена!\n\nПодписка активна до {fmt_dt(exp)}.",
        reply_markup=to_menu_kb(),
    )


@pay_router.callback_query(F.data == "disc:apply")
async def disc_apply_handler(call: CallbackQuery):
    uid = call.from_user.id
    if not active_discount(uid):
        await call.answer("⌛ Срок действия скидки истёк", show_alert=True)
        return
    await show(call, payment_text(DISCOUNT_DAYS, uid), payment_kb(DISCOUNT_DAYS))
    await call.answer()


@pay_router.callback_query(F.data.startswith("pay:"))
async def pay_unknown_handler(call: CallbackQuery):
    # кнопки из старых сообщений (pay:cryptobot, pay:ton) → просто открываем выбор плана
    await show(call, plans_text(call.from_user.id), plans_kb())
    await call.answer()


def account_limit(user_info: dict) -> int:
    return ACCOUNT_LIMIT_PAID if is_sub_active(user_info) else ACCOUNT_LIMIT_FREE


def fmt_phone(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    if len(d) == 11 and d[0] in "78":
        return f"+7 {d[1:4]} {d[4:7]} {d[7:]}"
    return p


def account_screen(user_info: dict):
    accs = user_info["accounts"]
    green = pe(E_GREEN, "🟢")
    text = f"{pe(E_USER, '👤')} <b>Ваши аккаунты:</b>\n\n"
    if accs:
        text += "\n".join(f"{green} {fmt_phone(a)}" for a in accs) + "\n\n"
    text += "Выберите аккаунт или добавьте новый:"
    rows = [[acc_btn(a, f"acc:open:{i}")] for i, a in enumerate(accs)]
    rows.append([pbtn("Добавить аккаунт", "acc:add", E_OK, "success"), btn("◀️ Главное меню", "menu:back")])
    return text, kb(*rows)


def add_account_screen(user_info: dict):
    used = len(user_info["accounts"])
    limit = account_limit(user_info)
    text = (
        "➕ <b>Добавление аккаунта</b>\n\n"
        f"📊 У вас {used}/{limit} аккаунтов\n"
        f"Осталось: {max(limit - used, 0)}\n\n"
        "<b>Шаг 1 из 3</b>\n\n"
        "Хотите использовать прокси SOCKS5?\n\n"
        "Если да — введите в формате:\n\n"
        "<code>socks5://host:port</code>\n"
        "<code>socks5://user:pass@host:port</code>"
    )
    markup = kb(
        [url_btn("🛒 Купить аккаунт и прокси", BUY_ACCOUNT_URL)],
        [btn("✅ Да, добавить профиль", "acc:proxy"), btn("⏩ Продолжить", "acc:skip")],
        [btn("🔙 Назад", "menu:back")],
    )
    return text, markup


STEP2_TEXT = (
    "➕ <b>Добавление аккаунта</b>\n\n"
    "<b>Шаг 2 из 3</b>\n\n"
    "Хотите использовать собственный идентификатор API и хэш?\n\n"
    "Получить: https://my.telegram.org\n\n"
    "Если нет — используются стандартные настройки."
)

STEP3_TEXT = (
    "➕ <b>Добавление аккаунта</b>\n\n"
    "<b>Шаг 3 из 3</b>\n\n"
    "Можно отправить файлом: TData (.zip), Telethon .session, Pyrogram .session.\n\n"
    "Или введите номер телефона в международном формате:\n\n"
    "Например: <code>+12345678913</code>"
)


def step2_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("✅ Да, ввести API", "acc:api"), btn("Пропустить", "acc:apiskip"), btn("◀️ Назад", "acc:add")],
    )


def phone_reply_kb() -> ReplyKeyboardMarkup:
    # кнопка «Назад» под «Отправить номер телефона» убрана
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def send_step3(message: Message, state: FSMContext):
    await state.set_state(AccState.phone)
    await message.answer(STEP3_TEXT, reply_markup=phone_reply_kb(), parse_mode="HTML")


async def drop_reply_kb(message: Message):
    """Убирает reply-клавиатуру (её можно снять только отправкой сообщения)."""
    try:
        tmp = await message.answer("вЏі", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass

PROXY_PROMPT = (
    "🌐 <b>Введите прокси SOCKS5</b> в формате:\n\n"
    "<code>socks5://host:port</code>\n"
    "или <code>socks5://user:pass@host:port</code>"
)


async def referrals_screen(bot: Bot, user_id: int, user_info: dict):
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{user_id}"
    text = (
        "🤝 <b>Реферальная программа</b>\n\n"
        "Ваша реферальная ссылка:\n"
        f"<code>{link}</code>\n\n"
        f"👥 Приглашено: {len(user_info['referrals'])}\n"
        f"💰 Из них купили подписку: {user_info['ref_buyers']}\n\n"
        f"💵 Ваш баланс: {user_info['balance']:.2f} USDT\n"
        f"💸 Процент с покупок: {REF_PERCENT:.1f}%\n"
        f"📤 Минимум для вывода: {REF_MIN_WITHDRAW:.1f} USDT\n\n"
        "Вы получаете процент от каждой покупки подписки вашими рефералами!"
    )
    return text, kb([btn("🔙 Главное меню", "menu:back")])


def tools_screen():
    text = "🛠 <b>Инструменты</b>\n\nДополнительные функции для работы с аккаунтами."
    return text, kb(
        [btn("🔍 Парсер сообщений", "tools:parser")],
        [btn("🔥 Прогрев аккаунтов", "tools:warmup")],
        [btn("🔙 Главное меню", "menu:back")],
    )


HELP_TEXT = (
    "ℹ️ <b>Помощь</b>\n\n"
    "📋 Рассылки — сообщения по группам и чатам с ваших аккаунтов\n"
    "🔴 Текст, фото, видео, пересылка постов, кнопки, премиум-эмодзи\n"
    "🔴 Чаты списком или целой папкой Telegram\n"
    "🔴 Интервалы, расписание, скрытый тег и ответная рассылка\n\n"
    "👤 Аккаунты — подключение по номеру или файлом (TData, .session)\n"
    "🔴 Свой прокси для каждого аккаунта\n"
    "🔴 Автоответчик в ЛС и в группах\n\n"
    "🛠️ Инструменты — статистика с графиком, парсер сообщений, прогрев аккаунтов\n\n"
    "💳 Подписка — криптовалюта, рубли (СБП), карта, Telegram Stars, промокоды\n"
    "🤝 Рефералы — приглашайте друзей и получайте % с их оплат\n\n"
    "🚀 Быстрый старт\n"
    "1. «Аккаунты» → «Добавить аккаунт» → номер и код из Telegram\n"
    "2. «Мои рассылки» → «Создать рассылку»\n"
    "3. Добавьте сообщение и чаты, настройте интервал → запуск\n\n"
    "🔒 Чтобы аккаунты не банили\n"
    "🔴 Новые аккаунты сначала прогрейте\n"
    "🔴 Не ставьте слишком маленький интервал\n"
    "🔴 Используйте прокси, лучше свой на каждый аккаунт\n\n"
    "🆘 Поддержка: @durovsor — ответим на любой вопрос"
)


def help_screen():
    policy_emoji = "5296369303661067030"
    terms_emoji = "5435970940670320222"
    if POLICY_URL:
        policy = InlineKeyboardButton(text="Политика конф.", url=POLICY_URL, icon_custom_emoji_id=policy_emoji)
    else:
        policy = InlineKeyboardButton(text="Политика конф.", callback_data="help:policy", icon_custom_emoji_id=policy_emoji)
    if TERMS_URL:
        terms = InlineKeyboardButton(text="Польз. соглашение", url=TERMS_URL, icon_custom_emoji_id=terms_emoji)
    else:
        terms = InlineKeyboardButton(text="Польз. соглашение", callback_data="help:terms", icon_custom_emoji_id=terms_emoji)
    support = InlineKeyboardButton(text="🆘 Поддержка", url=SUPPORT_URL, style="danger")
    return HELP_TEXT, kb(
        [policy, terms],
        [support],
        [btn("◀️ Главное меню", "menu:back")],
    )


# ============================================================
# 👑 АДМИН-ПАНЕЛЬ
# ============================================================
BOT_START = datetime.now()
USERS_PER_PAGE = 8
BC_SEGMENTS = {"all": "👥 Всем", "paid": "💎 Только с подпиской", "nopaid": "🆓 Без подписки"}


class BanMiddleware(BaseMiddleware):
    """Забаненные пользователи не могут пользоваться ботом (админ — всегда может)."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not is_admin(user.id) and user_data_db.get(user.id, {}).get("banned"):
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("🚫 Доступ заблокирован", show_alert=True)
                except Exception:
                    pass
            return None
        return await handler(event, data)


def fmt_dt(dt) -> str:
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "—"


def fmt_uptime() -> str:
    sec = int((datetime.now() - BOT_START).total_seconds())
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m = sec // 60
    return (f"{d}д " if d else "") + f"{h}ч {m}м"


def user_title(uid: int, info: dict) -> str:
    if info.get("username"):
        return "@" + info["username"]
    return info.get("first_name") or str(uid)


def user_icon(info: dict) -> str:
    if info.get("banned"):
        return "🚫"
    if is_sub_active(info):
        return "💎"
    if info.get("free_plan"):
        return "🆓"
    return "в–«пёЏ"


def _all_campaigns():
    for u in user_data_db.values():
        for c in u.get("campaigns", []):
            yield c


def admin_main_text() -> str:
    now = datetime.now()
    users = list(user_data_db.values())
    total = len(users)
    today = sum(1 for u in users if u.get("joined_at") and u["joined_at"].date() == now.date())
    week = sum(1 for u in users if u.get("joined_at") and u["joined_at"] >= now - timedelta(days=7))
    paid = sum(1 for u in users if is_sub_active(u))
    free = sum(1 for u in users if u.get("free_plan") and not is_sub_active(u))
    banned = sum(1 for u in users if u.get("banned"))
    camps = list(_all_campaigns())
    running = sum(1 for c in camps if c.get("running"))
    accs = sum(len(u.get("accounts", [])) for u in users)
    buys = sum(admin_stats["purchases"].values())
    return (
        "👑 <b>Админ-панель</b>\n"
        "в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ\n"
        f"👥 <b>Пользователи:</b> {total}\n"
        f"   сегодня +{today} · за неделю +{week}\n"
        f"💎 С подпиской: {paid}\n"
        f"🆓 Бесплатный тариф: {free}\n"
        f"🚫 В бане: {banned}\n\n"
        f"📢 <b>Рассылки:</b> {len(camps)} (идут сейчас: {running})\n"
        f"👤 <b>Аккаунтов подключено:</b> {accs}\n\n"
        f"💰 <b>Выручка:</b> {admin_stats['revenue']:.2f} USDT ({buys} покупок)\n"
        f"🕒 <b>Аптайм:</b> {fmt_uptime()}"
    )


def admin_main_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("👥 Пользователи", "admin:users:0"), btn("🔎 Найти", "admin:find")],
        [btn("💳 Финансы", "admin:subs"), btn("📢 Рассылка", "admin:bc")],
        [btn("🏆 Топ рефералов", "admin:top"), btn("⚙️ Система", "admin:sys")],
        [btn("📉 Отток платящих", "admin:idle:3:0")],
        [btn("🔄 Обновить", "admin:open")],
        [btn("◀️ Главное меню", "menu:back")],
    )


def users_page(page: int):
    items = sorted(
        user_data_db.items(),
        key=lambda kv: kv[1].get("joined_at") or datetime.min,
        reverse=True,
    )
    pages = max(1, (len(items) + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]
    rows = [
        [btn(f"{user_icon(info)} {user_title(uid, info)[:24]}", f"admin:u:{uid}")]
        for uid, info in chunk
    ]
    nav = []
    if page > 0:
        nav.append(btn("в†ђ", f"admin:users:{page - 1}"))
    nav.append(btn(f"{page + 1}/{pages}", f"admin:users:{page}"))
    if page < pages - 1:
        nav.append(next_btn(f"admin:users:{page + 1}"))
    rows.append(nav)
    rows.append([btn("🔎 Найти", "admin:find"), btn("◀️ Назад", "admin:open")])
    text = (
        f"👥 <b>Пользователи</b> — всего {len(items)}\n"
        "Новые сверху.\n\n"
        "💎 подписка · 🆓 бесплатный · ▫️ без тарифа · 🚫 бан"
    )
    return text, kb(*rows)


def user_card(uid: int):
    info = user_data_db[uid]
    ref_by = info.get("referred_by")
    ref_line = f"{ref_by}" if ref_by else "—"
    camps = info.get("campaigns", [])
    running = sum(1 for c in camps if c.get("running"))
    if is_sub_active(info):
        tariff = f"💎 Подписка до {fmt_dt(info.get('expiry'))}"
    elif info.get("free_plan"):
        tariff = "🆓 Бесплатный тариф"
    else:
        tariff = "▫️ Без тарифа"
    text = (
        f"👤 <b>{escape(info.get('first_name') or '—')}</b>"
        f"{' В· @' + escape(info['username']) if info.get('username') else ''}\n"
        "в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📅 В боте с: {fmt_dt(info.get('joined_at'))}\n"
        f"💳 Тариф: {tariff}\n"
        f"🚫 Статус: {'ЗАБАНЕН' if info.get('banned') else 'активен'}\n\n"
        f"👤 Аккаунтов: {len(info.get('accounts', []))}\n"
        f"📢 Рассылок: {len(camps)} (идут: {running})\n"
        f"🤝 Рефералов: {len(info.get('referrals', []))} (купили: {info.get('ref_buyers', 0)})\n"
        f"💰 Баланс: {info.get('balance', 0.0):.2f} USDT\n"
        f"↪️ Пригласил: {ref_line}"
    )
    markup = kb(
        [btn("➕ 1 день", f"admin:grant:{uid}:1"), btn("➕ 7 дней", f"admin:grant:{uid}:7"), btn("➕ 30 дней", f"admin:grant:{uid}:30")],
        [btn("❌ Отозвать подписку", f"admin:revoke:{uid}")],
        [
            btn("✉️ Написать", f"admin:dm:{uid}"),
            btn("✅ Разбанить" if info.get("banned") else "🚫 Забанить", f"admin:ban:{uid}"),
        ],
        [btn("🎁 Скидка / отток", f"admin:iu:{uid}")],
        [btn("🔄 Обновить", f"admin:u:{uid}"), btn("◀️ Назад", "admin:users:0")],
    )
    return text, markup


def finance_text() -> str:
    p = admin_stats["purchases"]
    total = sum(p.values())
    now = datetime.now()
    users = list(user_data_db.values())
    active = [u for u in users if is_sub_active(u)]
    soon = sum(1 for u in active if u["expiry"] <= now + timedelta(hours=24))
    avg = admin_stats["revenue"] / total if total else 0.0
    return (
        "💳 <b>Финансы и подписки</b>\n"
        "в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ\n"
        f"💰 Выручка: <b>{admin_stats['revenue']:.2f} USDT</b>\n"
        f"🧾 Покупок: {total} (средний чек {avg:.2f} USDT)\n"
        f"   📅 1 день: {p['1d']}\n"
        f"   📅 7 дней: {p['7d']}\n"
        f"   📅 30 дней: {p['30d']}\n\n"
        f"💎 Активных подписок: {len(active)}\n"
        f"⏳ Истекают за 24 часа: {soon}\n"
        f"🆓 На бесплатном тарифе: {sum(1 for u in users if u.get('free_plan') and not is_sub_active(u))}"
    )


def top_refs_text() -> str:
    ranked = sorted(
        ((uid, u) for uid, u in user_data_db.items() if u.get("referrals")),
        key=lambda kv: len(kv[1]["referrals"]),
        reverse=True,
    )[:10]
    if not ranked:
        return "🏆 <b>Топ рефералов</b>\n\nПока никто никого не пригласил."
    lines = ["🏆 <b>Топ рефералов</b>\n"]
    for i, (uid, u) in enumerate(ranked, 1):
        lines.append(
            f"{i}. {escape(user_title(uid, u))} — {len(u['referrals'])} приглашённых, "
            f"купили: {u.get('ref_buyers', 0)}"
        )
    return "\n".join(lines)


def system_text() -> str:
    try:
        from importlib.metadata import version as _v
        ai = _v("aiogram")
    except Exception:
        ai = "?"
    import sys as _sys
    try:
        sessions = len([f for f in os.listdir(SESSIONS_DIR) if f.endswith(".session")])
    except Exception:
        sessions = 0
    running = sum(1 for c in _all_campaigns() if c.get("running"))
    return (
        "⚙️ <b>Система</b>\n"
        "в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ\n"
        f"🕒 Аптайм: {fmt_uptime()}\n"
        f"🐍 Python {_sys.version.split()[0]} · aiogram {ai}\n"
        f"📁 Файлов .session: {sessions}\n"
        f"📢 Рассылок запущено: {running}\n"
        f"👥 Пользователей в памяти: {len(user_data_db)}\n\n"
        "⚠️ Данные хранятся в памяти: при перезапуске бота они сбрасываются."
    )


def bc_recipients(seg: str) -> list:
    out = []
    for uid, u in user_data_db.items():
        if u.get("banned"):
            continue
        paid = is_sub_active(u)
        if seg == "paid" and not paid:
            continue
        if seg == "nopaid" and paid:
            continue
        out.append(uid)
    return out


def grant_sub(info: dict, days: int):
    now = datetime.now()
    base = info["expiry"] if is_sub_active(info) else now
    info["expiry"] = base + timedelta(days=days)
    info["is_active"] = True
    info["free_plan"] = False


# ============================================================
# 📉 ОТТОК ПЛАТЯЩИХ: купили подписку, но перестали рассылать
# ============================================================
IDLE_FILTERS = (3, 7, 14)
DISCOUNT_PRESETS = ((10, 20, 30), (40, 50, 75))


def user_last_send_ts(info: dict) -> float:
    """Время последней УСПЕШНОЙ отправки рассылки пользователя (0 — данных нет)."""
    ts = float(info.get("last_send_ts") or 0)
    for c in info.get("campaigns", []):
        ts = max(ts, float(c.get("last_ok_ts") or 0))
        for t, _src, ok in c.get("events", []):
            if ok and t > ts:
                ts = t
    return ts


def purchase_stats() -> dict:
    """user_id -> (время последней покупки, число покупок, сумма USDT)."""
    out = {}
    rows = db_exec(
        "SELECT user_id, MAX(created_at) AS last_at, COUNT(*) AS n, SUM(price) AS total "
        "FROM payments GROUP BY user_id", fetch="all",
    ) or []
    for r in rows:
        out[r["user_id"]] = (int(r["last_at"] or 0), int(r["n"] or 0), float(r["total"] or 0.0))
    return out


def churn_list(min_days: int) -> list:
    """Платившие пользователи, у которых не было успешных рассылок >= min_days. Свежие «потеряшки» — первыми."""
    now = time.time()
    res = []
    for uid, (last_buy, n, total) in purchase_stats().items():
        info = user_data_db.get(uid) or {}
        if info.get("banned"):
            continue
        ref = max(user_last_send_ts(info), last_buy)
        idle = (now - ref) / 86400.0
        if idle >= min_days:
            res.append((uid, idle, info))
    res.sort(key=lambda x: x[1])
    return res


def idle_page(min_days: int, page: int):
    items = churn_list(min_days)
    pages = max(1, (len(items) + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * USERS_PER_PAGE:(page + 1) * USERS_PER_PAGE]
    rows = []
    for uid, idle, info in chunk:
        icon = "💎" if is_sub_active(info) else "⌛"
        gift = "🎁" if active_discount(uid) else ""
        rows.append([btn(f"{icon}{gift} {user_title(uid, info)[:22]} · {int(idle)} дн.", f"admin:iu:{uid}")])
    rows.append([btn(("✅ " if d == min_days else "") + f"{d} дн.", f"admin:idle:{d}:0") for d in IDLE_FILTERS])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("←", f"admin:idle:{min_days}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", f"admin:idle:{min_days}:{page}"))
        if page < pages - 1:
            nav.append(next_btn(f"admin:idle:{min_days}:{page + 1}"))
        rows.append(nav)
    rows.append([btn("◀️ Назад", "admin:open")])
    text = (
        "📉 <b>Отток платящих</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"Покупали подписку, но не рассылают уже ≥ <b>{min_days} дн.</b>\n"
        f"Найдено: <b>{len(items)}</b>\n\n"
        "💎 подписка активна · ⌛ истекла · 🎁 скидка уже выдана\n"
        "Нажмите на пользователя, чтобы выдать скидку."
    )
    if not items:
        text += "\n\nПока таких нет 👌"
    return text, kb(*rows)


def idle_card(uid: int, back_days: int = 3):
    info = user_data_db.get(uid) or {}
    last_buy, n_buy, total = purchase_stats().get(uid, (0, 0, 0.0))
    last_send = user_last_send_ts(info)
    ref = max(last_send, last_buy)
    idle = (time.time() - ref) / 86400.0 if ref else 0.0
    camps = info.get("campaigns", [])
    running = sum(1 for c in camps if c.get("running"))
    if is_sub_active(info):
        tariff = f"💎 Подписка до {fmt_dt(info.get('expiry'))}"
    elif info.get("free_plan"):
        tariff = "🆓 Бесплатный тариф"
    else:
        tariff = "⌛ Подписка истекла"
    pct = active_discount(uid)
    if pct:
        disc_line = f"🎁 Скидка: <b>{pct}%</b> — до {fmt_ts(info['discount']['expires'])}"
    else:
        disc_line = "🎁 Скидка: не выдана"
    name = escape(info.get("first_name") or "—")
    uname = f" · @{escape(info['username'])}" if info.get("username") else ""
    text = (
        f"📉 <b>{name}</b>{uname}\n"
        "━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💳 Тариф: {tariff}\n"
        f"🛒 Покупок: {n_buy} на {total:.2f} USDT (последняя: {fmt_ts(last_buy)})\n"
        f"📤 Последняя рассылка: {fmt_ts(last_send) if last_send else 'нет данных'}\n"
        f"⏳ Не рассылает: <b>{idle:.0f} дн.</b>\n"
        f"📢 Рассылок: {len(camps)} (идут: {running})\n"
        f"{disc_line}\n\n"
        f"Выберите скидку на 1 месяц — она действует {DISCOUNT_TTL_HOURS} ч. "
        "Пользователь сразу получит сообщение с кнопкой оплаты."
    )
    rows = [[btn(f"{p}%", f"admin:disc:{uid}:{p}") for p in grp] for grp in DISCOUNT_PRESETS]
    rows.append([btn(f"✍️ Свой процент ({DISCOUNT_MIN}–{DISCOUNT_MAX})", f"admin:discx:{uid}")])
    if pct:
        rows.append([btn("🚫 Отозвать скидку", f"admin:discoff:{uid}")])
    rows.append([btn("✉️ Написать", f"admin:dm:{uid}")])
    rows.append([btn("◀️ К списку", f"admin:idle:{back_days}:0")])
    return text, kb(*rows)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(admin_main_text(), reply_markup=admin_main_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:"))
async def admin_cb(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён", show_alert=True)
        return

    parts = call.data.split(":")
    action = parts[1]
    alert = None
    try:
        mark_dirty(int(parts[2]))   # админ мог поменять данные пользователя
    except (IndexError, ValueError):
        pass

    def uid_arg():
        try:
            return int(parts[2])
        except (IndexError, ValueError):
            return None

    if action == "open":
        await state.clear()
        await show(call, admin_main_text(), admin_main_kb())

    elif action == "users":
        await state.clear()
        try:
            page = int(parts[2])
        except (IndexError, ValueError):
            page = 0
        text, markup = users_page(page)
        await show(call, text, markup)

    elif action == "u":
        await state.clear()
        uid = uid_arg()
        if uid in user_data_db:
            text, markup = user_card(uid)
            await show(call, text, markup)
        else:
            alert = "Пользователь не найден"

    elif action == "find":
        await state.set_state(AdminState.search_wait)
        await show(
            call,
            "🔎 <b>Поиск пользователя</b>\n\nОтправьте ID или @username:",
            kb([btn("◀️ Назад", "admin:open")]),
        )

    elif action == "grant":
        uid = uid_arg()
        try:
            days = int(parts[3])
        except (IndexError, ValueError):
            days = 0
        if uid in user_data_db and days > 0:
            grant_sub(user_data_db[uid], days)
            save_sub(uid)
            try:
                await call.bot.send_message(
                    uid,
                    f"🎁 Администратор выдал вам подписку на {days} дн.\n"
                    f"Действует до: {fmt_dt(user_data_db[uid]['expiry'])}",
                )
            except Exception:
                pass
            alert = f"✅ Выдано {days} дн."
            text, markup = user_card(uid)
            await show(call, text, markup)
        else:
            alert = "Пользователь не найден"

    elif action == "revoke":
        uid = uid_arg()
        if uid in user_data_db:
            info = user_data_db[uid]
            info["is_active"] = False
            info["expiry"] = None
            save_sub(uid)
            alert = "✅ Подписка отозвана"
            text, markup = user_card(uid)
            await show(call, text, markup)
        else:
            alert = "Пользователь не найден"

    elif action == "ban":
        uid = uid_arg()
        if uid in user_data_db:
            info = user_data_db[uid]
            info["banned"] = not info.get("banned")
            if info["banned"]:
                for c in info.get("campaigns", []):
                    c["running"] = False
            alert = "🚫 Пользователь забанен, рассылки остановлены" if info["banned"] else "✅ Пользователь разбанен"
            text, markup = user_card(uid)
            await show(call, text, markup)
        else:
            alert = "Пользователь не найден"

    elif action == "dm":
        uid = uid_arg()
        if uid in user_data_db:
            await state.set_state(AdminState.dm_wait)
            await state.update_data(dm_uid=uid)
            await show(
                call,
                f"✉️ Отправьте сообщение для <b>{escape(user_title(uid, user_data_db[uid]))}</b> "
                "(текст, фото, видео — что угодно):",
                kb([btn("◀️ Назад", f"admin:u:{uid}")]),
            )
        else:
            alert = "Пользователь не найден"

    elif action == "subs":
        await show(call, finance_text(), kb([btn("🔄 Обновить", "admin:subs")], [btn("◀️ Назад", "admin:open")]))

    elif action == "top":
        await show(call, top_refs_text(), kb([btn("◀️ Назад", "admin:open")]))

    elif action == "sys":
        await show(
            call,
            system_text(),
            kb(
                [btn("⏹ Остановить все рассылки", "admin:stopall")],
                [btn("🔄 Обновить", "admin:sys"), btn("◀️ Назад", "admin:open")],
            ),
        )

    elif action == "stopall":
        running = sum(1 for c in _all_campaigns() if c.get("running"))
        await show(
            call,
            f"⏹ Остановить <b>все</b> рассылки у всех пользователей?\n\nСейчас идёт: {running}",
            kb([btn("✅ Да, остановить", "admin:stopall_yes"), btn("◀️ Назад", "admin:sys")]),
        )

    elif action == "stopall_yes":
        n = 0
        for c in _all_campaigns():
            if c.get("running"):
                c["running"] = False
                n += 1
        alert = f"⏹ Остановлено рассылок: {n}"
        await show(call, system_text(), kb([btn("⏹ Остановить все рассылки", "admin:stopall")], [btn("◀️ Назад", "admin:open")]))

    elif action == "bc":
        await state.clear()
        rows = [
            [btn(f"{label} ({len(bc_recipients(seg))})", f"admin:bcs:{seg}")]
            for seg, label in BC_SEGMENTS.items()
        ]
        rows.append([btn("◀️ Назад", "admin:open")])
        await show(call, "📢 <b>Рассылка пользователям бота</b>\n\nКому отправить?", kb(*rows))

    elif action == "bcs":
        seg = parts[2] if len(parts) > 2 and parts[2] in BC_SEGMENTS else "all"
        await state.clear()
        await state.set_state(AdminState.broadcast_wait)
        await state.update_data(bc_seg=seg)
        await show(
            call,
            f"✉️ Получатели: <b>{BC_SEGMENTS[seg]}</b> ({len(bc_recipients(seg))})\n\n"
            "Отправьте сообщение (текст, фото, видео и т.д.), которое нужно разослать:",
            kb([btn("◀️ Назад", "admin:bc")]),
        )

    elif action == "bcast_yes":
        data = await state.get_data()
        chat_id, msg_id = data.get("bcast_chat"), data.get("bcast_msg")
        seg = data.get("bc_seg", "all")
        if not chat_id or not msg_id:
            alert = "⚠️ Сообщение не найдено, начните рассылку заново"
            await show(call, admin_main_text(), admin_main_kb())
        else:
            recipients = bc_recipients(seg)
            await call.message.edit_text(f"⏳ Рассылка запущена... (получателей: {len(recipients)})")
            sent = blocked = failed = 0
            for uid in recipients:
                for attempt in range(2):
                    try:
                        await call.bot.copy_message(chat_id=uid, from_chat_id=chat_id, message_id=msg_id)
                        sent += 1
                        break
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(e.retry_after + 1)
                    except TelegramForbiddenError:
                        blocked += 1
                        break
                    except Exception:
                        failed += 1
                        break
                await asyncio.sleep(0.05)
            await state.clear()
            await call.message.edit_text(
                "✅ <b>Рассылка завершена!</b>\n\n"
                f"📬 Доставлено: {sent}\n"
                f"🚪 Заблокировали бота: {blocked}\n"
                f"⚠️ Другие ошибки: {failed}",
                reply_markup=admin_main_kb(),
                parse_mode="HTML",
            )

    elif action == "idle":
        await state.clear()
        try:
            days, page = int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            days, page = IDLE_FILTERS[0], 0
        get_user(call.from_user.id)["idle_days"] = days
        text, markup = idle_page(days, page)
        await show(call, text, markup)

    elif action == "iu":
        await state.clear()
        uid = uid_arg()
        if uid is not None and (uid in user_data_db or uid in purchase_stats()):
            text, markup = idle_card(uid, get_user(call.from_user.id).get("idle_days", IDLE_FILTERS[0]))
            await show(call, text, markup)
        else:
            alert = "Пользователь не найден"

    elif action == "disc":
        uid = uid_arg()
        try:
            pct = int(parts[3])
        except (IndexError, ValueError):
            pct = 0
        if uid is None or not (DISCOUNT_MIN <= pct <= DISCOUNT_MAX) or not (uid in user_data_db or uid in purchase_stats()):
            alert = "Некорректные данные"
        else:
            sent = await grant_discount(call.bot, uid, pct)
            alert = (f"🎁 Скидка {pct}% выдана, сообщение отправлено" if sent
                     else f"⚠️ Скидка {pct}% выдана, но сообщение не доставлено (бот заблокирован?)")
            text, markup = idle_card(uid, get_user(call.from_user.id).get("idle_days", IDLE_FILTERS[0]))
            await show(call, text, markup)

    elif action == "discx":
        uid = uid_arg()
        if uid is not None and (uid in user_data_db or uid in purchase_stats()):
            await state.set_state(AdminState.discount_wait)
            await state.update_data(dc_uid=uid)
            await show(
                call,
                f"✍️ Введите процент скидки от {DISCOUNT_MIN} до {DISCOUNT_MAX} "
                f"для <b>{escape(user_title(uid, user_data_db.get(uid) or {}))}</b>:",
                kb([btn("◀️ Назад", f"admin:iu:{uid}")]),
            )
        else:
            alert = "Пользователь не найден"

    elif action == "discoff":
        uid = uid_arg()
        if uid in user_data_db:
            user_data_db[uid].pop("discount", None)
            mark_dirty(uid)
            alert = "✅ Скидка отозвана"
            text, markup = idle_card(uid, get_user(call.from_user.id).get("idle_days", IDLE_FILTERS[0]))
            await show(call, text, markup)
        else:
            alert = "Пользователь не найден"

    elif action == "bcast_no":
        await state.clear()
        await show(call, admin_main_text(), admin_main_kb())

    await call.answer(alert, show_alert=bool(alert))


@router.message(AdminState.broadcast_wait)
async def admin_broadcast_receive(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(bcast_chat=message.chat.id, bcast_msg=message.message_id)
    data = await state.get_data()
    seg = data.get("bc_seg", "all")
    await message.answer(
        f"Отправить это сообщение? Получатели: <b>{BC_SEGMENTS[seg]}</b>\n\n"
        f"Всего: {len(bc_recipients(seg))}",
        reply_markup=kb([btn("✅ Да, отправить", "admin:bcast_yes"), btn("Отмена", "admin:bcast_no")]),
        parse_mode="HTML",
    )


@router.message(AdminState.discount_wait)
async def admin_discount_receive(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    uid = (await state.get_data()).get("dc_uid")
    t = (message.text or "").strip().rstrip("%").strip()
    if not re.fullmatch(r"\d{1,2}", t) or not (DISCOUNT_MIN <= int(t) <= DISCOUNT_MAX):
        await message.answer(f"❌ Введите целое число от {DISCOUNT_MIN} до {DISCOUNT_MAX}:")
        return
    await state.clear()
    if uid is None:
        await message.answer("Пользователь не найден", reply_markup=admin_main_kb())
        return
    pct = int(t)
    sent = await grant_discount(message.bot, uid, pct)
    head = (f"🎁 Скидка {pct}% выдана, сообщение отправлено." if sent
            else f"⚠️ Скидка {pct}% выдана, но сообщение не доставлено (бот заблокирован?).")
    text, markup = idle_card(uid, get_user(message.from_user.id).get("idle_days", IDLE_FILTERS[0]))
    await message.answer(f"{head}\n\n{text}", reply_markup=markup, parse_mode="HTML")


@router.message(AdminState.search_wait)
async def admin_search_receive(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    q = (message.text or "").strip().lstrip("@").lower()
    found = None
    if q.isdigit() and int(q) in user_data_db:
        found = int(q)
    elif q:
        for uid, info in user_data_db.items():
            if (info.get("username") or "").lower() == q:
                found = uid
                break
    if found is None:
        await message.answer(
            "❌ Не найден. Пользователь должен хотя бы раз написать боту.\nПопробуйте ещё раз:",
            reply_markup=kb([btn("◀️ Назад", "admin:open")]),
        )
        return
    await state.clear()
    text, markup = user_card(found)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(AdminState.dm_wait)
async def admin_dm_receive(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    uid = data.get("dm_uid")
    await state.clear()
    if uid not in user_data_db:
        await message.answer("Пользователь не найден", reply_markup=admin_main_kb())
        return
    try:
        await message.bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
        result = "✅ Сообщение отправлено"
    except Exception as e:
        result = f"❌ Не удалось отправить: {escape(str(e))}"
    await message.answer(result, reply_markup=kb([btn("👤 К пользователю", f"admin:u:{uid}")], [btn("◀️ Назад", "admin:open")]), parse_mode="HTML")


@router.callback_query(F.data.startswith("tools:"))
async def tools_cb(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[1]
    if key == "parser":
        await state.clear()
        get_user(call.from_user.id)["parser_draft"] = None
        text, markup = parser_menu_screen()
        await show(call, text, markup)
        await call.answer()
        return
    if key == "warmup":
        await state.clear()
        text, markup = warmup_menu_screen()
        await show(call, text, markup)
        await call.answer()
        return
    await call.answer("Раздел — в разработке", show_alert=True)


@router.callback_query(F.data.startswith("help:"))
async def help_cb(call: CallbackQuery):
    await call.answer("📄 Документ скоро будет доступен", show_alert=True)


def new_campaign(user_info: dict, name: str) -> dict:
    cid = user_info["next_id"]
    user_info["next_id"] += 1
    return {
        "id": cid,
        "name": name,
        "account": None,
        "cd_cycle": 300,
        "cd_chats": 3,
        "messages": [],
        "chats": [],
        "hours": None,
        "running": False,
        "last_sent": None,
        "hidden_tag": 0,
        "events": [],
        "stats_since": datetime.now().strftime("%d.%m.%Y"),
        "reply_mode": None,
        "greeted": [],
        "no_repeat": True,
        "no_repeat_last_ids": {},
    }


def find_campaign(user_info: dict, tgt):
    if tgt == "w":
        return user_info.get("draft")
    try:
        cid = int(tgt)
    except (TypeError, ValueError):
        return None
    for c in user_info["campaigns"]:
        if c["id"] == cid:
            return c
    return None


def set_cycle(c: dict, seconds: int):
    c["cd_cycle"] = seconds
    for ch in c["chats"]:
        ch["interval"] = seconds


def add_chat_to(c: dict, src: str) -> bool:
    if any(x["src"].lower() == src.lower() for x in c["chats"]):
        return False
    c["chats"].append({"src": src, "interval": c["cd_cycle"]})
    return True


def parse_chat(token: str):
    t = token.strip()
    if not t:
        return None
    if re.fullmatch(r"-?\d{5,20}", t):
        return t
    m = re.fullmatch(r"(?:https?://)?(?:t|telegram)\.me/(?:\+|joinchat/)([A-Za-z0-9_-]+)", t)
    if m:
        return "https://t.me/+" + m.group(1)
    m = re.fullmatch(r"(?:https?://)?(?:t|telegram)\.me/([A-Za-z][A-Za-z0-9_]{3,31})(?:/\d+)?/?", t)
    if m and m.group(1).lower() not in ("addlist", "joinchat"):
        return "@" + m.group(1)
    m = re.fullmatch(r"@?([A-Za-z][A-Za-z0-9_]{3,31})", t)
    if m:
        return "@" + m.group(1)
    return None


def parse_hours(text: str):
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    if not parts:
        return None
    out = []
    for p in parts:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", p)
        if not m:
            return None
        h1, m1, h2, m2 = map(int, m.groups())
        if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
            return None
        out.append(f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}")
    return ", ".join(out)


def extract_forward(msg: Message):
    o = msg.forward_origin
    if o is None:
        return None
    t = str(getattr(o.type, "value", o.type))
    if t == "channel":
        return str(o.chat.id), o.message_id, "channel", o.chat.title or "канала"
    if t == "chat":
        return str(o.sender_chat.id), None, "chat", o.sender_chat.title or "чата"
    if t == "user":
        u = o.sender_user
        kind = "bot" if getattr(u, "is_bot", False) else "user"
        return str(u.id), None, kind, u.full_name or (f"@{u.username}" if u.username else str(u.id))
    if t == "hidden_user":
        return str(o.sender_user_name), None, "user", str(o.sender_user_name)
    return None


def snapshot_content(message: Message):
    """Содержимое пересланного сообщения (текст/фото/видео) — чтобы отправить его от имени аккаунта с подписью «Переслано от»."""
    if message.photo:
        cap = message.caption or ""
        return {"type": "photo", "file_ids": [message.photo[-1].file_id],
                "plain": cap, "html": message.html_text if cap else ""}
    if message.video:
        cap = message.caption or ""
        return {"type": "video", "file_id": message.video.file_id,
                "plain": cap, "html": message.html_text if cap else ""}
    if message.text:
        return {"type": "text", "plain": message.text, "html": message.html_text}
    return None


FWD_KIND_LABEL = {"user": "пользователя", "bot": "бота", "channel": "канала", "chat": "чата"}


def fwd_label(msg: dict) -> str:
    return f"[Переслано] от {FWD_KIND_LABEL.get(msg.get('kind'), 'источника')}"


async def resolve_folder_chats(link: str, client=None) -> list:
    """Читает чаты из папки Telegram (t.me/addlist/...) через аккаунт. Папку не добавляет и никуда не вступает."""
    if client is None:
        raise RuntimeError("не выбран аккаунт для чтения папки")
    from telethon.tl.functions.chatlists import CheckChatlistInviteRequest
    slug = link.rstrip("/").split("/")[-1]
    res = await client(CheckChatlistInviteRequest(slug=slug))
    out = []
    for chat in getattr(res, "chats", None) or []:
        uname = getattr(chat, "username", None)
        if uname:
            out.append("@" + uname)
            continue
        try:
            out.append(str(tg_utils.get_peer_id(chat)))
        except Exception:
            pass
    return out


# Порядок шагов мастера: 1 название → 2 аккаунт → 3 КД между циклами →
# 4 интервал между сообщениями → 5 текст рассылки → 6 чаты → 7 время активности
STEP5_TEXT = (
    "Шаг 5/7: Добавьте сообщения для рассылки\n\n"
    "Вы можете добавить текст, фото или фото с подписью.\n"
    "Несколько сообщений — для рандомизации.\n"
    "Минимум 1 сообщение обязательно."
)

STEP6_TEXT = (
    "Шаг 6/7: Добавьте целевые чаты/группы\n\n"
    "Введите username или ID чата.\n"
    "Минимум 1 чат обязателен."
)

ADD_MSG_TEXT = (
    "✏️ Отправьте текст, фото, видео или игровое эмодзи для рассылки.\n"
    "Можно отправить несколько фото (до 10) — они будут отправлены альбомом.\n\n"
    "💡 Форматирование (жирный, курсив и т.д.) — выделите текст прямо в Telegram, "
    "оно сохранится автоматически."
)

FORWARD_TEXT = (
    "📨 Перешлите любое сообщение из канала, группы или от пользователя.\n"
    "Бот сохранит его и будет использовать при рассылке."
)

ADD_CHAT_TEXT = (
    "🎯 Введите username, ID или ссылку на чат/группу:\n\n"
    "Примеры:\n"
    "🔴 @username\n"
    "🔴 -1001234567890\n"
    "🔴 https://t.me/chatname"
)

FOLDER_TEXT = (
    "📁 Отправьте ссылку на папку чатов:\n\n"
    "Пример:\n"
    "🔴 https://t.me/addlist/xxxxx\n\n"
    "Можно сразу несколько — по одной ссылке на строку (до 20)."
)

TXT_TEXT = (
    "📄 Отправьте .txt файл со списком чатов.\n\n"
    "Формат: каждый чат на новой строке или через пробел.\n\n"
    "Примеры:\n"
    "🔴 @username\n"
    "🔴 -1001234567890\n"
    "🔴 https://t.me/chatname"
)

TIME_PROMPT = (
    "⏰ Введите диапазон времени в формате:\n"
    "10:00-13:00\n\n"
    "Можно указать несколько диапазонов через запятую:\n"
    "10:00-13:00, 18:00-22:00"
)

REPLY_TEXT = (
    "↩️ <b>Ответная рассылка</b>\n\n"
    "Когда включена — бот отвечает на существующие сообщения в чате, а не отправляет новое сообщение.\n\n"
    "Выберите режим:\n"
    "🔴 На последнее — отвечает на самое новое сообщение\n"
    "🔴 На N-е с конца — на конкретную позицию (2–10)\n"
    "🔴 Случайно — случайная позиция из диапазона (макс. 10)"
)


def msg_preview(m: dict, limit: int = 30) -> str:
    t = m["type"]
    if t == "text":
        s = m["plain"]
    elif t == "photo":
        s = "📷 " + (m["plain"] or "Фото")
        if len(m["file_ids"]) > 1:
            s += f" (x{len(m['file_ids'])})"
    elif t == "video":
        s = "🎬 " + (m["plain"] or "Видео")
    elif t == "dice":
        s = f"{m['emoji']} Эмодзи"
    else:
        s = f"Переслано от {m.get('from_name') or m['src']}"
    s = " ".join(s.split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def card_text(c: dict) -> str:
    if c["running"]:
        status = f"{pe(E_GREEN, '🟢')} Активна — идёт отправка"
    else:
        status = f"{pe(E_RED_BULLET, '🔴')} Остановлена"
    hours = f"{c['hours']} ({TIMEZONE_NAME})" if c["hours"] else "24/7 (без ограничений)"
    return (
        f"{pe(E_DOC, '📋')} <b>Рассылка: {escape(c['name'])}</b>\n\n"
        f"Статус: {status}\n"
        f"Аккаунт: {escape(c['account'] or '—')}\n"
        f"Интервал: {c['cd_cycle']} сек\n"
        f"Время активности: {hours}\n"
        f"Сообщений: {len(c['messages'])}\n"
        f"Целевых чатов: {len(c['chats'])}\n"
        f"Последняя отправка: {c['last_sent'] or 'никогда'}\n\n"
        "Выберите действие:"
    )


def card_kb(c: dict) -> InlineKeyboardMarkup:
    cid = c["id"]
    if c["running"]:
        toggle = InlineKeyboardButton(
            text="Остановить", callback_data=f"camp:toggle:{cid}",
            style="danger", icon_custom_emoji_id=E_RED,
        )
    else:
        toggle = InlineKeyboardButton(
            text="Запустить", callback_data=f"camp:toggle:{cid}",
            style="success", icon_custom_emoji_id=E_GREEN,
        )
    return kb(
        [toggle],
        [btn("📝 Сообщения", f"mg:msgs:{cid}"), btn("🎯 Целевые чаты", f"ch:page:{cid}:0")],
        [btn("⏰ Время активности", f"mg:time:{cid}"), btn("👤 Аккаунт", f"mg:acc:{cid}")],
        [InlineKeyboardButton(text="🚀 Увеличить конверсию рассылки", callback_data=f"mg:conv:{cid}", style="success")],
        [btn("📊 Статистика рассылки", f"mg:stats:{cid}")],
        [btn("🚫 Убрать рекламу из рассылки", f"mg:noads:{cid}")],
        [btn("❌ Удалить рассылку", f"mg:delask:{cid}"), btn("⬅️ Назад", "menu:campaigns")],
    )


def reply_menu_kb(cid) -> InlineKeyboardMarkup:
    return kb(
        [btn("На последнее", f"mg:rl:{cid}")],
        [btn("На N-е с конца", f"mg:rn:{cid}")],
        [btn("Случайно", f"mg:rr:{cid}")],
        [btn("◀️ Назад", f"mg:reply:{cid}")],
    )


def conv_screen(c: dict):
    cid = c["id"]
    tag_n = c["hidden_tag"]
    reply_on = bool(c["reply_mode"])
    c.setdefault("no_repeat", True)
    c.setdefault("no_repeat_last_ids", {})
    no_repeat = bool(c.get("no_repeat", True))
    tag_state = f"включён (до {tag_n} уч.)" if tag_n else "выключен"
    text = (
        "🚀 <b>Увеличить конверсию рассылки</b>\n"
        f"📋 {escape(c['name'])}\n\n"
        f"🫥 <b>Скрытый тег</b> — сейчас {tag_state}\n"
        "Сообщение незаметно отмечает до 15 последних активных участников чата — "
        "им приходит уведомление, и сообщение видят больше людей.\n\n"
        f"↩️ <b>Ответная рассылка</b> — сейчас {'включена' if reply_on else 'выключена'}\n"
        "Бот отвечает на свежие сообщения в чате, а не пишет отдельно — такое сообщение "
        "выглядит как часть разговора и меньше теряется в ленте.\n\n"
        f"🔁 <b>Не повторяться</b> — сейчас {'включено' if no_repeat else 'выключено'}\n"
        "Если ваше прошлое сообщение в чате ещё последнее (после него никто не писал), "
        "бот пропускает этот чат и ждёт нового сообщения перед следующей отправкой.\n\n"
        "Нажмите, чтобы настроить:"
    )
    def tb(label, on, data):
        return InlineKeyboardButton(
            text=f"{label}: {'ВКЛ' if on else 'ВЫКЛ'}", callback_data=data,
            style="success" if on else "primary",
        )
    return text, kb(
        [tb("🫥 Скрытый тег", bool(tag_n), f"mg:tag:{cid}")],
        [tb("↩️ Ответная рассылка", reply_on, f"mg:reply:{cid}")],
        [pbtn(f"Не повторяться: {'ВКЛ' if no_repeat else 'ВЫКЛ'}", f"mg:norepeat:{cid}", E_ROTATE, "success" if no_repeat else "primary")],
        [btn("⬅️ Назад", f"camp:open:{cid}")],
    )


def reply_mode_label(mode) -> str:
    if not mode:
        return ""
    if mode[0] == "last":
        return "на последнее сообщение"
    if mode[0] == "nth":
        return f"на {mode[1]}-е с конца"
    return f"случайно ({mode[1]}–{mode[2]} с конца)"


def toggle_screen(c: dict, which: str):
    """Экран отдельной функции конверсии: описание, «Сейчас: …», Включить/Выключить, Назад."""
    cid = c["id"]
    if which == "tag":
        on = bool(c["hidden_tag"])
        text = (
            "🫥 <b>Скрытый тег</b>\n\n"
            "При отправке бот автоматически отмечает до 15 последних участников, которые писали в целевом чате. "
            "Упоминания скрыты и не меняют внешний вид сообщения.\n\n"
            f"Сейчас: {'включён' if on else 'выключен'}"
        )
        on_data, off_data = f"mg:tagon:{cid}", f"mg:tagoff:{cid}"
    elif which == "reply":
        on = bool(c["reply_mode"])
        text = (
            "↩️ <b>Ответная рассылка</b>\n\n"
            "Бот отвечает на свежие сообщения в чате, а не пишет отдельно — такое сообщение "
            "выглядит как часть разговора и меньше теряется в ленте.\n\n"
            f"Сейчас: {'включена (' + reply_mode_label(c['reply_mode']) + ')' if on else 'выключена'}"
        )
        on_data, off_data = f"mg:rmenu:{cid}", f"mg:replyoff:{cid}"
    else:
        on = bool(c.get("no_repeat", True))
        text = (
            "🔁 <b>Не повторяться</b>\n\n"
            "Если ваше прошлое сообщение в чате ещё последнее (после него никто не писал), "
            "бот пропускает этот чат и ждёт нового сообщения перед следующей отправкой.\n\n"
            f"Сейчас: {'включено' if on else 'выключено'}"
        )
        on_data, off_data = f"mg:nron:{cid}", f"mg:nroff:{cid}"
    if on:
        first = pbtn("Выключить", off_data, E_RED_BULLET, "danger")
    else:
        first = pbtn("Включить", on_data, E_GREEN, "success")
    return text, kb([first], [btn("◀️ Назад", f"mg:conv:{cid}")])


def stats_screen(c: dict):
    cid = c["id"]
    now = time.time()
    ev = c.get("events", [])
    today0 = now_local().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    d7, d30 = now - 7 * 86400, now - 30 * 86400

    def errs(since):
        return sum(1 for t, _src, ok in ev if not ok and t >= since)

    e_today, e7, e30 = errs(today0), errs(d7), errs(d30)
    ok7 = sum(1 for t, _src, ok in ev if ok and t >= d7)
    rate = f"{round(ok7 * 100 / (ok7 + e7))}%" if (ok7 + e7) else "—"

    total = len(c["chats"])
    sent_srcs = {src for _t, src, ok in ev if ok}
    was = sum(1 for ch in c["chats"] if ch["src"] in sent_srcs)

    # фактический интервал: медиана пауз между успешными отправками в один и тот же чат
    per_chat = {}
    for t, src, ok in ev:
        if ok and t >= d7:
            per_chat.setdefault(src, []).append(t)
    gaps, all_ts = [], []
    for ts in per_chat.values():
        ts.sort()
        all_ts += ts
        gaps += [b - a for a, b in zip(ts, ts[1:])]
    if len(gaps) >= 3 and all_ts and max(all_ts) - min(all_ts) >= 3600:
        gaps.sort()
        actual = f"≈ {int(gaps[len(gaps) // 2])} сек"
    else:
        actual = "появится примерно через час работы рассылки"

    text = (
        "📊 <b>Статистика рассылки</b>\n"
        f"📋 {escape(c['name'])}\n\n"
        f"❌ Ошибок: сегодня {e_today} · 7 дн. {e7} · 30 дн. {e30}\n"
        f"✅ Успешных отправок за 7 дней: {rate}\n\n"
        f"🎯 Чаты: всего {total}\n"
        f"🔴 Отправка была: {was}\n"
        f"🔴 Ещё ни разу: {total - was}\n\n"
        "⏱ Интервал\n"
        f"🔴 Задан: {c['cd_cycle']} сек\n"
        f"🔴 На деле: {actual}\n\n"
        f"📅 Статистика собирается с {c.get('stats_since', '—')}"
    )
    return text, kb([btn("Обновить", f"mg:stats:{cid}"), btn("◀️ Назад", f"camp:open:{cid}")])


def campaigns_text(user_info: dict) -> str:
    if not user_info["campaigns"]:
        return (
            "📋 <b>Ваши рассылки:</b>\n\n"
            "У вас пока нет рассылок.\n\n"
            "Выберите рассылку или создайте новую:"
        )
    return "📋 <b>Ваши рассылки:</b>\n\nВыберите рассылку или создайте новую:"


def campaigns_kb(user_info: dict) -> InlineKeyboardMarkup:
    rows = []
    for c in user_info["campaigns"]:
        rows.append([InlineKeyboardButton(
            text=str(c["id"]), callback_data=f"camp:open:{c['id']}",
            icon_custom_emoji_id=E_GREEN if c.get("running") else E_RED_BULLET,
        )])
    rows.append([pbtn("Создать рассылку", "camp:create", E_PLUS, "success"), btn("◀️ Главное меню", "menu:back")])
    return kb(*rows)


def message_editor_screen(c: dict, tgt: str, idx: int):
    msg = c["messages"][idx]
    labels = {"text": "Текст", "photo": "Фото", "video": "Видео", "dice": "Эмодзи", "forward": "Пересланное сообщение"}
    kind = labels.get(msg.get("type"), "Сообщение")
    preview = msg_preview(msg, 300)
    if msg.get("type") == "forward":
        preview = f"Переслано из {msg.get('src', 'источника')}"
    bs = msg.get("buttons") or []
    if bs:
        btn_info = f"{pe('5271604874419647061', '🔗')} Кнопки ({len(bs)}/{MAX_MSG_BUTTONS}):\n{buttons_lines(msg)}"
    else:
        btn_info = f"{pe('5271604874419647061', '🔗')} Кнопок нет."
    text = (
        f"{pe(E_PENCIL, '✏️')} <b>Редактирование сообщения</b> ({kind})\n\n"
        f"{escape(preview)}\n\n"
        f"{btn_info}"
    )
    rows = [
        [pbtn("Изменить текст", f"me:text:{tgt}:{idx}", E_PENCIL)],
        [pbtn("Добавить кнопку", f"me:button:{tgt}:{idx}", E_PLUS, "success")],
    ]
    if bs:
        rows.append([pbtn("Убрать кнопки", f"bt:clear:{tgt}:{idx}", E_TRASH, "danger")])
    rows += [
        [InlineKeyboardButton(text="👁️ Предосмотр", callback_data=f"me:preview:{tgt}:{idx}", style="primary")],
        [InlineKeyboardButton(text="Назад", callback_data=f"me:back:{tgt}:{idx}", style="primary", icon_custom_emoji_id=BACK_EMOJI_ID)],
    ]
    return text, kb(*rows)


def msgs_wizard_screen(c: dict, header: str = None):
    msgs = c["messages"]
    add_row = [
        pbtn("Текст/Фото/Видео/Эмодзи", "msg:add:w", E_PLUS),
        pbtn("Переслать", "msg:fwd:w", E_FORWARD),
    ]
    if not msgs:
        text = (f"{header}\n\n" if header else "") + STEP5_TEXT
        return text, kb(add_row, [btn("◀️ Назад", "w:go:cdch")])
    rows = []
    for i, msg in enumerate(msgs):
        rows.append([
            pbtn(str(i + 1), f"w:delmsg:{i}", E_TRASH, "danger"),
            pbtn("Изменить", f"me:open:w:{i}", E_PENCIL),
        ])
        if msg.get("type") == "forward":
            rows.append([pbtn(fwd_label(msg), f"w:delmsg:{i}", E_TRASH, "danger")])
    rows += [add_row, [pbtn("Готово", "w:go:chats", E_OK, "success")], [btn("◀️ Назад", "w:go:cdch")]]
    head = header or f"{OK} Всего сообщений: {len(msgs)}"
    lines = "\n".join(f"{i}. {escape(msg_preview(m, 60))}" for i, m in enumerate(msgs, 1))
    return f"Шаг 5/7\n{head}\n\n{lines}\n\nДобавьте ещё или нажмите «Готово»:", kb(*rows)


def msgs_manager_screen(c: dict, header: str = None):
    cid = c["id"]
    msgs = c["messages"]
    lines = "\n".join(f"{i}. {escape(msg_preview(m, 60))}" for i, m in enumerate(msgs, 1)) or "Сообщений пока нет."
    text = (
        (f"{header}\n\n" if header else "")
        + f"📝 <b>Сообщения рассылки ({len(msgs)} шт.):</b>\n\n{lines}\n\n"
        "Нажмите на сообщение, чтобы удалить его:"
    )
    rows = []
    for i, _msg in enumerate(msgs):
        rows.append([
            pbtn(str(i + 1), f"mg:mdel:{cid}:{i}", E_TRASH, "danger"),
            pbtn("Изменить", f"me:open:{cid}:{i}", E_PENCIL),
        ])
        if _msg.get("type") == "forward":
            rows.append([pbtn(fwd_label(_msg), f"mg:mdel:{cid}:{i}", E_TRASH, "danger")])
    rows += [
        [pbtn("Текст/Фото/Видео/Эмодзи", f"msg:add:{cid}", E_PLUS), pbtn("Переслать", f"msg:fwd:{cid}", E_FORWARD)],
        [btn("📋 Копировать в другую рассылку", f"mg:copy:{cid}")],
        [btn("◀️ Назад", f"camp:open:{cid}")],
    ]
    return text, kb(*rows)


def chats_screen(c: dict, tgt: str, page: int = 0, header: str = None):
    wiz = tgt == "w"
    chats = c["chats"]
    n = len(chats)
    pages = max(1, (n + CHATS_PER_PAGE - 1) // CHATS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    start = page * CHATS_PER_PAGE
    chunk = chats[start:start + CHATS_PER_PAGE]

    rows = []
    if not wiz:
        rows.append([
            pbtn("КД между циклами", f"ch:cdc:{tgt}", E_GREEN, "success"),
            pbtn("КД между чатами", f"ch:cdch:{tgt}", E_GREEN, "success"),
        ])
        rows.append([btn("📤 Выгрузить чаты", f"ch:export:{tgt}")])
    for i, ch in enumerate(chunk, start=start):
        # юз чата: красная кнопка + премиум 🗑 перед юзом
        row = [InlineKeyboardButton(
            text=ch["src"], callback_data=f"ch:ask:{tgt}:{i}:{page}",
            style="danger", icon_custom_emoji_id=E_TRASH,
        )]
        if not wiz:
            row.append(InlineKeyboardButton(
                text=fmt_interval(ch["interval"]), callback_data=f"ch:int:{tgt}:{i}:{page}",
                style="success", icon_custom_emoji_id=E_TIMER,
            ))
        rows.append(row)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("в†ђ", f"ch:page:{tgt}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", f"ch:page:{tgt}:{page}"))
        if page < pages - 1:
            nav.append(next_btn(f"ch:page:{tgt}:{page + 1}"))
        rows.append(nav)
    rows.append([
        pbtn("Добавить чат", f"ch:add:{tgt}", E_PLUS, "success"),
        pbtn("Добавить папку", f"ch:folder:{tgt}", E_FOLDER),
    ])
    rows.append([pbtn("Загрузить .txt", f"ch:txt:{tgt}", E_DOC)])
    if wiz:
        # «Готово» первая, «Назад» вторая — в одном ряду
        bottom = []
        if n:
            bottom.append(pbtn("Готово", "w:go:time", E_OK, "success"))
        bottom.append(btn("◀️ Назад", "w:go:msgs"))
        rows.append(bottom)
    else:
        rows.append([btn("◀️ Назад", f"camp:open:{tgt}")])

    if wiz:
        if n:
            text = f"Шаг 6/7\n{header or f'{OK} Всего чатов: {n}'}\n\nДобавьте ещё или нажмите «Готово»:"
        else:
            text = (f"{header}\n\n" if header else "") + STEP6_TEXT
    else:
        lines = "\n".join(
            f"{i}. {escape(ch['src'])}" for i, ch in enumerate(chunk, start=start + 1)
        ) or "Чатов пока нет."
        text = (
            (f"{header}\n\n" if header else "")
            + f"🎯 <b>Целевые чаты ({n} шт.):</b>\n\n{lines}\n\n"
            "Нажмите на чат, чтобы удалить его:"
        )
    return text, kb(*rows)


def created_text(c: dict) -> str:
    t = f"{OK} <b>Рассылка создана!</b>\n"
    if c["hours"]:
        t += f"Время активности: {c['hours']} ({TIMEZONE_NAME})\n"
    t += "\nНажмите «Запустить рассылку», чтобы начать отправку."
    return t


FIRST_ROUND_WARN = (
    f"{pe(E_WARN, '⚠️')} <b>Важно про первый круг</b>\n"
    "При первом проходе в каждый новый чат сначала отправляется короткое приветствие — "
    "например, «Всем привет» или «Здравствуйте».\n"
    f"{pe(E_WAVE, '👋')} Основные тексты рассылки начнут отправляться со второго круга."
)


async def send_created(target, c: dict):
    """Сначала предупреждение про первый круг, затем «Рассылка создана»."""
    msg = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery):
        try:
            await target.message.delete()
        except Exception:
            pass
    try:
        await msg.answer(FIRST_ROUND_WARN, parse_mode="HTML")
    except Exception:
        logging.exception("send_created: предупреждение не отправилось")
    try:
        await msg.answer(created_text(c), reply_markup=created_kb(c), parse_mode="HTML")
    except Exception:
        logging.exception("send_created: не отправилось сообщение с кнопкой, пробую упрощённо")
        plain = kb(
            [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data=f"camp:launch:{c['id']}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:campaigns")],
        )
        await msg.answer(re.sub(r"<[^>]+>", "", created_text(c)), reply_markup=plain)


def created_kb(c: dict) -> InlineKeyboardMarkup:
    return kb([
        InlineKeyboardButton(
            text="Запустить рассылку", callback_data=f"camp:launch:{c['id']}",
            style="success", icon_custom_emoji_id="5445284980978621387",
        ),
        btn("◀️ Назад", "menu:campaigns"),
    ])


def finalize_draft(user_info: dict, hours):
    d = user_info["draft"]
    d["hours"] = hours
    user_info["campaigns"].append(d)
    user_info["draft"] = None
    return d


async def wiz_show(target, state: FSMContext, user_info: dict, step: str):
    d = user_info.get("draft")

    if step == "list":
        await state.clear()
        user_info["draft"] = None
        await show(target, campaigns_text(user_info), campaigns_kb(user_info))

    elif step == "name":
        await state.clear()
        await state.set_state(CS.name)
        await state.update_data(tgt="w")
        await show(
            target,
            "<b>Создание рассылки</b>\n\nШаг 1/7: Введите название рассылки:",
            kb([btn("◀️ Назад", "w:go:list")]),
        )

    elif step == "account":
        await state.clear()
        accs = user_info["accounts"]
        rows = [[acc_btn(a, f"w:acc:{i}")] for i, a in enumerate(accs)]
        rows.append([btn("◀️ Назад", "w:go:name")])
        text = "Шаг 2/7: Выберите аккаунт для рассылки:"
        if not accs:
            text += "\n\n⚠️ У вас нет добавленных аккаунтов. Добавьте аккаунт в разделе «Аккаунт»."
        await show(target, text, kb(*rows))

    elif step == "cdc":
        await state.clear()
        await state.set_state(CS.cd_cycle)
        await state.update_data(tgt="w")
        await show(
            target,
            "Шаг 3/7: Введите КД между циклами — через сколько снова писать в тот же чат (в секундах):\n\n"
            "Например: 300 (это 5 минут)",
            kb([btn("◀️ Назад", "w:go:account")]),
        )

    elif step == "msgs":
        await state.clear()
        text, markup = msgs_wizard_screen(d)
        await show(target, text, markup)

    elif step == "cdch":
        await state.clear()
        await state.set_state(CS.cd_chats)
        await state.update_data(tgt="w")
        await show(
            target,
            "Шаг 4/7: Введите интервал между сообщениями — паузу между отправками в разные чаты "
            "внутри одного прохода (в секундах, минимум 3):",
            kb([btn("◀️ Назад", "w:go:cdc")]),
        )

    elif step == "chats":
        await state.clear()
        text, markup = chats_screen(d, "w", 0)
        await show(target, text, markup)

    elif step == "time":
        await state.clear()
        await show(
            target,
            "Шаг 7/7: Время активности\n\nХотите настроить часы работы рассылки?\nИли работать 24/7?",
            kb(
                [pbtn("Пропустить (24/7)", "w:skip", E_NEXT), btn("⏰ Настроить", "w:hours")],
                [btn("◀️ Назад", "w:go:chats")],
            ),
        )

    elif step == "hours":
        await state.clear()
        await state.set_state(CS.time_range)
        await state.update_data(tgt="w")
        await show(target, TIME_PROMPT, kb([btn("◀️ Назад", "w:go:time")]))


@router.callback_query(F.data.startswith("w:"))
async def wizard_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    parts = call.data.split(":")
    action = parts[1]
    d = user_info.get("draft")
    alert = None

    if action == "go":
        step = parts[2]
        if step not in ("list", "name") and d is None:
            alert = "⚠️ Сессия создания истекла. Начните заново."
            await state.clear()
            await show(call, campaigns_text(user_info), campaigns_kb(user_info))
        elif step == "chats" and not d["messages"]:
            alert = "Добавьте минимум 1 сообщение"
        elif step == "time" and not d["chats"]:
            alert = "Добавьте минимум 1 чат"
        else:
            await wiz_show(call, state, user_info, step)

    elif action == "acc":
        idx = int(parts[2])
        if d and 0 <= idx < len(user_info["accounts"]):
            d["account"] = user_info["accounts"][idx]
            await wiz_show(call, state, user_info, "cdc")

    elif action == "delmsg":
        idx = int(parts[2])
        if d and 0 <= idx < len(d["messages"]):
            d["messages"].pop(idx)
            header = f"🗑 Сообщение удалено! Всего сообщений: {len(d['messages'])}"
            text, markup = msgs_wizard_screen(d, header)
            await show(call, text, markup)

    elif action == "editmsg":
        idx = int(parts[2])
        if d and 0 <= idx < len(d["messages"]):
            text, markup = message_editor_screen(d, "w", idx)
            await state.clear()
            await show(call, text, markup)

    elif action == "hours":
        if d:
            await wiz_show(call, state, user_info, "hours")

    elif action == "skip":
        if d is None:
            alert = "⚠️ Сессия создания истекла. Начните заново."
        else:
            await state.clear()
            c = finalize_draft(user_info, None)
            await send_created(call, c)

    await call.answer(alert, show_alert=bool(alert))


@router.message(CS.name)
async def on_name(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        await message.answer("❌ Введите название текстом (до 50 символов):")
        return
    if user_info.get("draft") is None:
        user_info["draft"] = new_campaign(user_info, name)
    else:
        user_info["draft"]["name"] = name
    await wiz_show(message, state, user_info, "account")


@router.message(CS.cd_cycle)
async def on_cd_cycle(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt", "w")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return
    val = parse_int(message.text, 30)
    if val is None:
        await message.answer("❌ Введите целое число секунд (минимум 30):")
        return
    set_cycle(c, val)
    if tgt == "w":
        await wiz_show(message, state, user_info, "cdch")
    else:
        await state.clear()
        text, markup = chats_screen(c, tgt, 0, f"{OK} КД между циклами: {val} сек")
        await show(message, text, markup)


@router.message(CS.cd_chats)
async def on_cd_chats(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt", "w")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return
    val = parse_int(message.text, 3)
    if val is None:
        await message.answer("❌ Введите целое число секунд (минимум 3):")
        return
    c["cd_chats"] = val
    if tgt == "w":
        await wiz_show(message, state, user_info, "msgs")
    else:
        await state.clear()
        text, markup = chats_screen(c, tgt, 0, f"{OK} КД между чатами: {val} сек")
        await show(message, text, markup)


@router.message(CS.time_range)
async def on_time_range(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt", "w")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return
    hours = parse_hours(message.text)
    if hours is None:
        await message.answer(
            "❌ Неверный формат. Пример: 10:00-13:00 или 10:00-13:00, 18:00-22:00"
        )
        return
    await state.clear()
    if tgt == "w":
        c = finalize_draft(user_info, hours)
        await send_created(message, c)
    else:
        c["hours"] = hours
        await show(message, card_text(c), card_kb(c))


@router.message(CS.reply_range)
async def on_reply_range(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена.")
        return
    m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", (message.text or "").strip())
    if not m or not (1 <= int(m.group(1)) <= int(m.group(2)) <= 10):
        await message.answer("❌ Неверный формат. Пример: 1-5 (максимум 10)")
        return
    c["reply_mode"] = ("random", int(m.group(1)), int(m.group(2)))
    await state.clear()
    text, markup = toggle_screen(c, "reply")
    await show(message, text, markup)


@router.message(CS.tag_count)
async def on_tag_count(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена.")
        return
    t = (message.text or "").strip()
    if not re.fullmatch(r"\d{1,2}", t) or not (0 <= int(t) <= 15):
        await message.answer("❌ Введите число от 0 до 15:")
        return
    c["hidden_tag"] = int(t)
    await state.clear()
    text, markup = conv_screen(c)
    await show(message, text, markup)


async def send_message_preview(bot: Bot, user_id: int, msg: dict):
    """Отправляет владельцу копию сохранённого сообщения для предварительного просмотра."""
    kind = msg.get("type")
    html = msg.get("html") or ""
    plain = msg.get("plain") or ""
    markup = msg_buttons_markup(msg)
    if kind == "text":
        await bot.send_message(user_id, html or escape(plain), parse_mode="HTML", reply_markup=markup)
    elif kind == "photo":
        file_ids = msg.get("file_ids", [])
        if len(file_ids) > 1:
            media = [
                InputMediaPhoto(
                    media=file_id,
                    caption=html if i == 0 and html else None,
                    parse_mode="HTML" if i == 0 and html else None,
                )
                for i, file_id in enumerate(file_ids)
            ]
            await bot.send_media_group(user_id, media)
        elif file_ids:
            await bot.send_photo(user_id, file_ids[0], caption=html or None, parse_mode="HTML" if html else None, reply_markup=markup)
    elif kind == "video":
        await bot.send_video(user_id, msg["file_id"], caption=html or None, parse_mode="HTML" if html else None, reply_markup=markup)
    elif kind == "dice":
        await bot.send_dice(user_id, emoji=msg.get("emoji", "🎲"))
    elif kind == "forward":
        await bot.copy_message(user_id, msg["from_chat_id"], msg["message_id"])


@router.callback_query(F.data.startswith("me:"))
async def message_editor_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action, tgt, idx = p[1], p[2], int(p[3])
    c = find_campaign(user_info, tgt)
    if c is None or not (0 <= idx < len(c.get("messages", []))):
        await call.answer("Сообщение не найдено", show_alert=True)
        return

    alert = None
    if action == "open":
        await state.clear()
        text, markup = message_editor_screen(c, tgt, idx)
        await show(call, text, markup)
    elif action == "back":
        await state.clear()
        if tgt == "w":
            text, markup = msgs_wizard_screen(c)
        else:
            text, markup = msgs_manager_screen(c)
        await show(call, text, markup)
    elif action == "text":
        old_msg = c["messages"][idx]
        await state.clear()
        if old_msg.get("type") == "forward":
            await state.set_state(CS.add_forward)
            await state.update_data(tgt=tgt, edit_idx=idx)
            prompt = FORWARD_TEXT + "\n\nНовое пересланное сообщение заменит выбранное."
        else:
            await state.set_state(CS.add_message)
            await state.update_data(tgt=tgt, edit_idx=idx)
            prompt = "✏️ <b>Редактирование сообщения</b>\n\nОтправьте новый текст, фото, видео или эмодзи. Новое сообщение заменит выбранное."
        await show(call, prompt, kb([InlineKeyboardButton(text="Назад", callback_data=f"me:open:{tgt}:{idx}", style="primary", icon_custom_emoji_id=BACK_EMOJI_ID)]))
    elif action == "button":
        m0 = c["messages"][idx]
        if not is_sub_active(user_info):
            alert = "Кнопки доступны только на платном тарифе 🔒"
        elif m0.get("type") not in ("text", "photo", "video"):
            alert = "К этому типу сообщений кнопку добавить нельзя."
        elif len(m0.get("buttons") or []) >= MAX_MSG_BUTTONS:
            alert = f"Максимум {MAX_MSG_BUTTONS} кнопки на сообщение."
        else:
            user_info["btn_draft"] = {"tgt": tgt, "idx": idx, "origin": "edit", "kind": "Сообщение"}
            await state.clear()
            await state.set_state(CS.btn_url)
            text, markup = btn_url_screen(tgt, idx)
            await show(call, text, markup)
    elif action == "preview":
        try:
            await send_message_preview(call.bot, call.from_user.id, c["messages"][idx])
            alert = "Предпросмотр отправлен отдельным сообщением."
        except Exception as e:
            alert = f"Не удалось показать предпросмотр: {str(e)[:180]}"
    await call.answer(alert, show_alert=bool(alert))


@router.callback_query(F.data.startswith("msg:"))
async def msg_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action, tgt = p[1], p[2]
    c = find_campaign(user_info, tgt)
    if c is None:
        await call.answer("Рассылка не найдена", show_alert=True)
        return

    alert = None
    back = "w:go:msgs" if tgt == "w" else f"mg:msgs:{tgt}"

    if action == "add":
        await state.clear()
        await state.set_state(CS.add_message)
        await state.update_data(tgt=tgt)
        await show(call, ADD_MSG_TEXT, kb([btn("◀️ Назад", back)]))

    elif action == "fwd":
        if not is_sub_active(user_info):
            alert = "❌ Пересылка сообщений недоступна на бесплатном тарифе. Оформите подписку."
        else:
            await state.clear()
            await state.set_state(CS.add_forward)
            await state.update_data(tgt=tgt)
            await show(call, FORWARD_TEXT, kb([btn("◀️ Назад", back)]))

    await call.answer(alert, show_alert=bool(alert))


@router.message(CS.add_message)
async def on_add_message(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    state_data = await state.get_data()
    tgt = state_data.get("tgt", "w")
    edit_idx = state_data.get("edit_idx")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return

    entry = None
    kind = ""

    if message.photo:
        fid = message.photo[-1].file_id
        gid = message.media_group_id
        if edit_idx is None and gid and c["messages"] and c["messages"][-1].get("group") == gid:
            last = c["messages"][-1]
            if len(last["file_ids"]) < 10:
                last["file_ids"].append(fid)
            if not last["plain"] and message.caption:
                last["plain"] = message.caption
                last["html"] = message.html_text
            return
        entry = {
            "type": "photo", "file_ids": [fid], "group": gid,
            "plain": message.caption or "",
            "html": message.html_text if message.caption else "",
        }
        kind = "Фото добавлено"
    elif message.video:
        entry = {
            "type": "video", "file_id": message.video.file_id,
            "plain": message.caption or "",
            "html": message.html_text if message.caption else "",
        }
        kind = "Видео добавлено"
    elif message.dice:
        entry = {"type": "dice", "emoji": message.dice.emoji}
        kind = "Эмодзи добавлено"
    elif message.text:
        entry = {"type": "text", "plain": message.text, "html": message.html_text}
        kind = "Текст добавлен"
    else:
        await message.answer("❌ Этот тип сообщения не поддерживается. Отправьте текст, фото, видео или эмодзи.")
        return

    if edit_idx is not None:
        if not (0 <= int(edit_idx) < len(c["messages"])): 
            await state.update_data(edit_idx=None)
            await message.answer("⚠️ Сообщение для изменения уже не найдено. Отправьте новое сообщение.")
            return
        old_btns = c["messages"][int(edit_idx)].get("buttons")
        if old_btns and entry.get("type") in ("text", "photo", "video"):
            entry["buttons"] = old_btns
        c["messages"][int(edit_idx)] = entry
        await state.update_data(edit_idx=None)
        kind = "Сообщение изменено"
    else:
        if len(c["messages"]) >= MAX_MESSAGES:
            await message.answer(f"❌ Максимум {MAX_MESSAGES} сообщений в рассылке.")
            return
        c["messages"].append(entry)

    n = len(c["messages"])
    # платный тариф: после нового сообщения предлагаем добавить кнопку со ссылкой
    if edit_idx is None and is_sub_active(user_info) and entry.get("type") in ("text", "photo", "video"):
        new_idx = n - 1
        user_info["btn_draft"] = {"tgt": tgt, "idx": new_idx, "origin": "add", "kind": kind}
        text, markup = btn_question_screen(kind, tgt, new_idx)
        await show(message, text, markup)
        return
    if tgt == "w":
        text, markup = msgs_wizard_screen(c, f"{OK} {kind}! Всего сообщений: {n}")
    else:
        text, markup = msgs_manager_screen(c, f"{OK} {kind}!")
    await show(message, text, markup)


@router.message(CS.add_forward)
async def on_add_forward(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    state_data = await state.get_data()
    tgt = state_data.get("tgt", "w")
    edit_idx = state_data.get("edit_idx")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return

    info = extract_forward(message)
    if info is None:
        await message.answer("❌ Это не пересланное сообщение. Перешлите любое сообщение из канала, группы или от пользователя.")
        return
    src, orig_id, fkind, from_name = info
    content = snapshot_content(message)
    if content is None and not orig_id:
        await message.answer("❌ Это сообщение нельзя переслать: поддерживаются текст, фото и видео. Перешлите другое:")
        return
    forward_entry = {
        "type": "forward", "src": src, "orig_msg_id": orig_id, "kind": fkind,
        "from_name": from_name, "content": content,
        "from_chat_id": message.chat.id, "message_id": message.message_id,
    }
    if edit_idx is not None:
        if not (0 <= int(edit_idx) < len(c["messages"])):
            await state.update_data(edit_idx=None)
            await message.answer("⚠️ Сообщение для изменения уже не найдено. Перешлите новое.")
            return
        c["messages"][int(edit_idx)] = forward_entry
        await state.update_data(edit_idx=None)
    else:
        if len(c["messages"]) >= MAX_MESSAGES:
            await message.answer(f"❌ Максимум {MAX_MESSAGES} сообщений в рассылке.")
            return
        c["messages"].append(forward_entry)
    n = len(c["messages"])
    src_line = f"{src} / сообщение #{orig_id}" if orig_id else src
    if tgt == "w":
        header = f"{OK} Пересылка сохранена! Рассылка будет пересылать сообщение с подписью «Переслано от».\nВсего записей: {n}"
        text, markup = msgs_wizard_screen(c, header)
    else:
        text, markup = msgs_manager_screen(c, f"{OK} Пересылка сохранена! Рассылка будет пересылать сообщение с подписью «Переслано от».")
    await show(message, text, markup)


@router.callback_query(F.data.startswith("ch:"))
async def chats_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action, tgt = p[1], p[2]
    c = find_campaign(user_info, tgt)
    if c is None:
        await call.answer("Рассылка не найдена", show_alert=True)
        return

    alert = None
    back_page = f"ch:page:{tgt}:0"

    if action == "page":
        await state.clear()
        text, markup = chats_screen(c, tgt, int(p[3]))
        await show(call, text, markup)

    elif action in ("add", "folder", "txt"):
        await state.clear()
        st = {"add": CS.add_chat, "folder": CS.add_folder, "txt": CS.add_txt}[action]
        prompt = {"add": ADD_CHAT_TEXT, "folder": FOLDER_TEXT, "txt": TXT_TEXT}[action]
        await state.set_state(st)
        await state.update_data(tgt=tgt)
        await show(call, prompt, kb([btn("◀️ Назад", back_page)]))

    elif action == "ask":
        idx, page = int(p[3]), int(p[4])
        await state.clear()
        await show(
            call,
            "Удалить чат из рассылки?",
            kb([btn("✅ Да, удалить", f"ch:del:{tgt}:{idx}:{page}"), btn("Отмена", f"ch:page:{tgt}:{page}")]),
        )

    elif action == "del":
        idx, page = int(p[3]), int(p[4])
        await state.clear()
        if 0 <= idx < len(c["chats"]):
            c["chats"].pop(idx)
        text, markup = chats_screen(c, tgt, page, f"🗑 Чат удалён! Всего чатов: {len(c['chats'])}")
        await show(call, text, markup)

    elif action == "int":
        idx, page = int(p[3]), int(p[4])
        if not (0 <= idx < len(c["chats"])):
            alert = "Чат не найден"
        else:
            ch = c["chats"][idx]
            await state.clear()
            await state.set_state(CS.chat_interval)
            await state.update_data(tgt=tgt, idx=idx, page=page)
            await show(
                call,
                f"⏱️ <b>Интервал для чата:</b> {escape(ch['src'])}\n\n"
                f"Текущий: {ch['interval']} сек\n\n"
                "Введите интервал в секундах (минимум 30).",
                kb([btn("◀️ Назад", f"ch:page:{tgt}:{page}")]),
            )

    elif action == "cdc":
        await state.clear()
        await state.set_state(CS.cd_cycle)
        await state.update_data(tgt=tgt)
        await show(
            call,
            f"⏱ Введите КД между циклами в секундах (минимум 30).\n\nТекущий: {c['cd_cycle']} сек\n"
            "Значение применится ко всем чатам.",
            kb([btn("◀️ Назад", back_page)]),
        )

    elif action == "cdch":
        await state.clear()
        await state.set_state(CS.cd_chats)
        await state.update_data(tgt=tgt)
        await show(
            call,
            f"⏱ Введите КД между чатами в секундах (минимум 3).\n\nТекущий: {c['cd_chats']} сек",
            kb([btn("◀️ Назад", back_page)]),
        )

    elif action == "export":
        if not c["chats"]:
            alert = "В рассылке нет чатов"
        else:
            data = "\n".join(ch["src"] for ch in c["chats"]).encode("utf-8")
            await call.message.answer_document(
                BufferedInputFile(data, filename=f"chats_{c['id']}.txt"),
                caption=f"📤 Чатов выгружено: {len(c['chats'])}",
            )

    await call.answer(alert, show_alert=bool(alert))


@router.message(CS.add_chat)
async def on_add_chat(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt", "w")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return

    added, bad = 0, 0
    for token in re.split(r"[\s,;]+", (message.text or "").strip()):
        if not token:
            continue
        norm = parse_chat(token)
        if norm is None:
            bad += 1
        elif add_chat_to(c, norm):
            added += 1

    if added == 0 and bad:
        await message.answer("❌ Не удалось распознать чат. Отправьте @username, ID или ссылку:")
        return

    n = len(c["chats"])
    if added == 0:
        header = f"ℹ️ Этот чат уже добавлен. Всего чатов: {n}"
    elif added == 1:
        header = f"{OK} Чат добавлен! Всего чатов: {n}"
    else:
        header = f"{OK} Добавлено чатов: {added}! Всего чатов: {n}"
    text, markup = chats_screen(c, tgt, 0, header)
    await show(message, text, markup)


@router.message(CS.add_folder)
async def on_add_folder(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt", "w")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return

    links = re.findall(r"https?://t\.me/addlist/[A-Za-z0-9_-]+", message.text or "")[:20]
    if not links:
        await message.answer("❌ Не нашёл ссылок на папки. Пример: https://t.me/addlist/xxxxx")
        return

    if not c.get("account"):
        await message.answer("❌ Сначала выберите аккаунт рассылки — папка читается через него.")
        return
    try:
        client = await get_client(user_info, c["account"])
    except Exception as e:
        await message.answer(f"❌ Не удалось подключить аккаунт: <code>{escape(str(e))}</code>")
        return

    added, errors = 0, []
    for link in links:
        try:
            for src in await resolve_folder_chats(link, client):
                if add_chat_to(c, src):
                    added += 1
        except Exception as e:
            errors.append(f"{link}: {e}")
    header = f"{OK} Из папки добавлено чатов: {added}! Всего чатов: {len(c['chats'])}"
    if errors:
        header += "\n⚠️ Не удалось прочитать: " + escape("; ".join(errors)[:300])
    text, markup = chats_screen(c, tgt, 0, header)
    await show(message, text, markup)


@router.message(CS.add_txt)
async def on_add_txt(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    tgt = (await state.get_data()).get("tgt", "w")
    c = find_campaign(user_info, tgt)
    if c is None:
        await state.clear()
        await message.answer("⚠️ Рассылка не найдена. Начните заново.")
        return
    if not message.document:
        await message.answer("❌ Отправьте файл в формате .txt")
        return
    if message.document.file_size and message.document.file_size > 1_000_000:
        await message.answer("❌ Файл слишком большой (максимум 1 МБ).")
        return

    buf = BytesIO()
    await message.bot.download(message.document, destination=buf)
    content = buf.getvalue().decode("utf-8", errors="ignore")

    added = 0
    for token in re.split(r"[\s,;]+", content):
        norm = parse_chat(token) if token else None
        if norm and add_chat_to(c, norm):
            added += 1

    header = f"{OK} Добавлено {added} чатов из файла! Всего чатов: {len(c['chats'])}"
    text, markup = chats_screen(c, tgt, 0, header)
    await show(message, text, markup)


@router.message(CS.chat_interval)
async def on_chat_interval(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    data = await state.get_data()
    tgt, idx, page = data.get("tgt"), data.get("idx", 0), data.get("page", 0)
    c = find_campaign(user_info, tgt)
    if c is None or not (0 <= idx < len(c["chats"])):
        await state.clear()
        await message.answer("⚠️ Чат не найден.")
        return
    val = parse_int(message.text, 30)
    if val is None:
        await message.answer("❌ Введите целое число секунд (минимум 30):")
        return
    c["chats"][idx]["interval"] = val
    await state.clear()
    text, markup = chats_screen(c, tgt, page, f"{OK} Интервал обновлён: {fmt_interval(val)}")
    await show(message, text, markup)



# ============================================================
# 🚀 ДВИЖОК РАССЫЛКИ (отправка через Telethon)
# ============================================================
RUNNERS = {}   # (user_id, campaign_id) -> asyncio.Task
CLIENTS = {}   # phone -> TelegramClient


def make_proxy(url: str):
    if not url:
        return None
    m = re.fullmatch(r"socks5://(?:([^\s:@/]+):([^\s:@/]+)@)?([^\s:@/]+):(\d{2,5})", url)
    if not m:
        return None
    user, pwd, host, port = m.groups()
    if user:
        return ("socks5", host, int(port), True, user, pwd)
    return ("socks5", host, int(port))


async def get_client(user_info: dict, phone: str) -> TelegramClient:
    cl = CLIENTS.get(phone)
    if cl and cl.is_connected():
        return cl
    session_path = os.path.join(SESSIONS_DIR, f"session_{phone.replace('+', '')}")
    api = user_info.get("apis", {}).get(phone)
    cl = TelegramClient(
        session_path, api[0] if api else API_ID, api[1] if api else API_HASH,
        proxy=make_proxy(user_info["proxies"].get(phone)),
    )
    await cl.connect()
    if not await cl.is_user_authorized():
        await cl.disconnect()
        raise RuntimeError("сессия аккаунта не авторизована — добавьте аккаунт заново")
    CLIENTS[phone] = cl
    return cl


def now_local() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TIMEZONE_NAME))
    except Exception:
        return datetime.now(timezone(timedelta(hours=3)))


def in_window(hours) -> bool:
    if not hours:
        return True
    now = now_local()
    cur = now.hour * 60 + now.minute
    for part in hours.split(","):
        a, b = part.strip().split("-")
        h1, m1 = map(int, a.split(":"))
        h2, m2 = map(int, b.split(":"))
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if start <= end:
            if start <= cur <= end:
                return True
        elif cur >= start or cur <= end:
            return True
    return False


async def resolve_target(client: TelegramClient, src: str):
    if src.startswith("@folder_"):
        raise RuntimeError("чаты из папок пока не поддерживаются (заглушка resolve_folder_chats)")
    if src.startswith("https://t.me/+"):
        h = src.rsplit("+", 1)[1]
        info = await client(CheckChatInviteRequest(h))
        if isinstance(info, ChatInviteAlready):
            return info.chat
        upd = await client(ImportChatInviteRequest(h))
        return upd.chats[0]
    if re.fullmatch(r"-?\d+", src):
        return await client.get_entity(int(src))
    return await client.get_entity(src)


async def hidden_tags(client: TelegramClient, entity, n: int) -> str:
    """Невидимые упоминания последних активных участников чата (до n штук)."""
    if n <= 0:
        return ""
    ids = []
    try:
        async for m in client.iter_messages(entity, limit=300):
            if m.out:
                continue
            u = m.sender
            if not isinstance(u, User) or u.bot or u.deleted:
                continue
            if u.id not in ids:
                ids.append(u.id)
            if len(ids) >= n:
                break
    except Exception as e:
        logging.warning(f"hidden_tags: {e}")
        return ""
    return "".join(f'<a href="tg://user?id={uid}">\u200b</a>' for uid in ids)


async def pick_reply_id(client: TelegramClient, entity, mode):
    if not mode:
        return None
    if mode[0] == "last":
        n = 1
    elif mode[0] == "nth":
        n = mode[1]
    else:
        n = random.randint(mode[1], mode[2])
    msgs = await client.get_messages(entity, limit=n)
    return msgs[-1].id if msgs else None


async def download_bot_file(bot: Bot, file_id: str, name: str) -> BytesIO:
    buf = BytesIO()
    await bot.download(file_id, destination=buf)
    buf.seek(0)
    buf.name = name
    return buf


def record_event(c: dict, src: str, ok: bool):
    ev = c.setdefault("events", [])
    if ok:
        c["last_ok_ts"] = time.time()
    ev.append((time.time(), src, ok))
    cutoff = time.time() - 30 * 86400
    if len(ev) > 5000 or (ev and ev[0][0] < cutoff):
        c["events"] = [e for e in ev if e[0] >= cutoff][-5000:]


BOT_USERNAME = ""
BOT_FWD_CACHE = {}     # (id клиента, подпись сообщения) -> id сообщения в диалоге аккаунта с ботом
BOT_STARTED = set()    # id клиентов, которые уже нажали /start у бота
INLINE_PAYLOADS = {}


async def forward_via_bot(bot: Bot, client: TelegramClient, entity, sig_key, send_to_account):
    """Бот кладёт сообщение в диалог аккаунта с ботом (send_to_account(chat_id)), аккаунт пересылает его в чат.
    Пересланное так сообщение сохраняет и кнопки, и исходную подпись «Переслано от …»."""
    sig = (id(client), sig_key)
    bot_peer = await client.get_input_entity(BOT_USERNAME)

    async def forward(acct_msg_id: int):
        return await client.forward_messages(entity, acct_msg_id, from_peer=bot_peer)

    cached = BOT_FWD_CACHE.get(sig)
    if cached:
        try:
            return await forward(cached)
        except tg_errors.FloodWaitError:
            raise
        except Exception:
            BOT_FWD_CACHE.pop(sig, None)   # сообщение в диалоге удалено — создадим заново

    me = await client.get_me()
    if id(client) not in BOT_STARTED:
        await client.send_message(BOT_USERNAME, "/start")
        BOT_STARTED.add(id(client))
        await asyncio.sleep(2)
    last = await client.get_messages(bot_peer, limit=1)
    last_id = last[0].id if last else 0

    await send_to_account(me.id)

    for _ in range(10):
        await asyncio.sleep(0.6)
        new = await client.get_messages(bot_peer, limit=1)
        if new and new[0].id > last_id:
            BOT_FWD_CACHE[sig] = new[0].id
            return await forward(new[0].id)
    raise RuntimeError("сообщение от бота не дошло до аккаунта")


async def send_via_bot_forward(bot: Bot, client: TelegramClient, entity, msg: dict, html: str):
    """Сообщение с URL-кнопками: в чате выглядит как «Переслано от @бота», кнопки остаются."""
    t = msg["type"]
    if not BOT_USERNAME or (t == "photo" and len(msg.get("file_ids", [])) != 1):
        return None
    markup = msg_buttons_markup(msg)
    file_id = msg.get("file_id") or (msg.get("file_ids") or [None])[0]

    async def send_to_account(uid: int):
        if t == "text":
            await bot.send_message(uid, html or " ", reply_markup=markup)
        elif t == "photo":
            await bot.send_photo(uid, file_id, caption=html or None, reply_markup=markup)
        else:
            await bot.send_video(uid, file_id, caption=html or None, reply_markup=markup)

    return await forward_via_bot(bot, client, entity, ("btn", t, html, file_id, repr(msg.get("buttons"))), send_to_account)


async def send_via_inline(client: TelegramClient, entity, msg: dict, html: str, reply_to):
    """Отправка сообщения с настоящими URL-кнопками: аккаунт берёт inline-результат у нашего бота.
    Нужно включить inline-режим у бота (BotFather → /setinline). Возвращает None, если так отправить нельзя."""
    t = msg["type"]
    if not BOT_USERNAME or (t == "photo" and len(msg.get("file_ids", [])) != 1):
        return None
    token = f"{random.getrandbits(48):x}"
    INLINE_PAYLOADS[token] = {
        "type": t, "html": html, "markup": msg_buttons_markup(msg),
        "file_id": msg.get("file_id") or (msg.get("file_ids") or [None])[0], "ts": time.time(),
    }
    for k in [k for k, v in INLINE_PAYLOADS.items() if time.time() - v["ts"] > 300]:
        INLINE_PAYLOADS.pop(k, None)
    try:
        results = await client.inline_query(BOT_USERNAME, token, entity=entity)
        if not results:
            raise RuntimeError("бот не вернул inline-результат (включён ли /setinline у бота?)")
        return await results[0].click(entity, reply_to=reply_to)
    finally:
        INLINE_PAYLOADS.pop(token, None)


@router.inline_query()
async def on_inline_query(q: InlineQuery):
    data = INLINE_PAYLOADS.get((q.query or "").strip())
    if not data:
        await q.answer([], cache_time=0, is_personal=True)
        return
    html, markup, t = data["html"], data["markup"], data["type"]
    if t == "text":
        res = InlineQueryResultArticle(
            id="1", title="Сообщение", reply_markup=markup,
            input_message_content=InputTextMessageContent(message_text=html or " ", parse_mode="HTML", disable_web_page_preview=True),
        )
    elif t == "photo":
        res = InlineQueryResultCachedPhoto(
            id="1", photo_file_id=data["file_id"], caption=html or None,
            parse_mode="HTML" if html else None, reply_markup=markup,
        )
    else:
        res = InlineQueryResultCachedVideo(
            id="1", video_file_id=data["file_id"], title="Видео", caption=html or None,
            parse_mode="HTML" if html else None, reply_markup=markup,
        )
    await q.answer([res], cache_time=0, is_personal=True)


async def send_payload(bot: Bot, client: TelegramClient, entity, msg: dict, reply_to, paid: bool, tag_n: int):
    t = msg["type"]
    html = msg.get("html") or ""
    if t in ("text", "photo", "video"):
        if not paid:
            html += AD_SIGNATURE
        if tag_n:
            html += await hidden_tags(client, entity, tag_n)
        if msg.get("buttons"):
            # настоящие кнопки: 1) пересылка сообщения от бота («Переслано от бота», кнопки сохраняются)
            try:
                res = await send_via_bot_forward(bot, client, entity, msg, html)
                if res is not None:
                    return res
            except tg_errors.FloodWaitError:
                raise
            except Exception as e:
                logging.warning(f"отправка кнопок пересылкой от бота не удалась ({e})")
            # 2) inline-режим бота
            try:
                res = await send_via_inline(client, entity, msg, html, reply_to)
                if res is not None:
                    return res
            except tg_errors.FloodWaitError:
                raise
            except Exception as e:
                logging.warning(f"inline-отправка с кнопками не удалась ({e}) — кнопки пойдут ссылками")
            html += buttons_as_links_html(msg)

    if t == "text":
        return await client.send_message(entity, html, parse_mode="html", reply_to=reply_to, link_preview=False)
    elif t == "photo":
        files = [await download_bot_file(bot, fid, f"photo{i}.jpg") for i, fid in enumerate(msg["file_ids"])]
        return await client.send_file(
            entity, files if len(files) > 1 else files[0],
            caption=html, parse_mode="html", reply_to=reply_to,
        )
    elif t == "video":
        f = await download_bot_file(bot, msg["file_id"], "video.mp4")
        return await client.send_file(entity, f, caption=html, parse_mode="html", reply_to=reply_to, supports_streaming=True)
    elif t == "dice":
        return await client.send_file(entity, InputMediaDice(msg["emoji"]), reply_to=reply_to)
    elif t == "forward":
        # пост из канала — настоящая пересылка; иначе (человек, бот, чат) — текст/медиа с подписью «Переслано от»
        if msg.get("orig_msg_id"):
            try:
                from_peer = await client.get_input_entity(int(msg["src"]))
                return await client.forward_messages(entity, msg["orig_msg_id"], from_peer=from_peer)
            except tg_errors.FloodWaitError:
                raise
            except Exception as e:
                if not msg.get("content"):
                    raise
                logging.warning(f"forward_messages не удалась ({e}), отправляю копией с подписью")
        # настоящая пересылка через бота: в чате «Переслано от …» с исходным автором
        if BOT_USERNAME and msg.get("from_chat_id") and msg.get("message_id"):
            try:
                async def send_to_account(uid: int):
                    await bot.forward_message(uid, msg["from_chat_id"], msg["message_id"])
                return await forward_via_bot(
                    bot, client, entity, ("fwd", msg["from_chat_id"], msg["message_id"]), send_to_account,
                )
            except tg_errors.FloodWaitError:
                raise
            except Exception as e:
                logging.warning(f"пересылка через бота не удалась ({e}), отправляю копией с подписью")
        content = msg.get("content")
        if not content:
            raise RuntimeError("пересылка: нет сохранённого содержимого — перешлите сообщение заново")
        who = escape(msg.get("from_name") or "источника")
        copy_msg = dict(content)
        copy_msg["html"] = f"↪️ Переслано от <b>{who}</b>\n\n" + (content.get("html") or "")
        return await send_payload(bot, client, entity, copy_msg, reply_to, paid, tag_n)
    else:
        raise RuntimeError(f"неизвестный тип сообщения: {t}")


FIRST_GREETINGS = [
    "Всем привет", "Здравствуйте", "Привет всем", "Добрый день",
    "Приветствую", "Всем добрый день", "Доброго времени суток",
]


async def campaign_runner(bot: Bot, user_id: int, cid: int):
    ui = get_user(user_id)
    c = find_campaign(ui, str(cid))
    if c is None:
        return

    async def notify(text: str):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"notify failed: {e}")

    try:
        client = await get_client(ui, c["account"])
        try:
            await client.get_dialogs()  # прогреваем кэш сущностей (нужно для числовых ID)
        except Exception as e:
            logging.warning(f"get_dialogs: {e}")

        entities, next_at, reported = {}, {}, set()
        greeted = c.setdefault("greeted", [])  # чаты, где уже было приветствие
        no_repeat_last_ids = c.setdefault("no_repeat_last_ids", {})
        no_repeat_last_ids.clear()   # новый запуск — шлём заново, не ждём чужих сообщений
        await notify(f"{pe(E_NEXT, '⏩')} Рассылка <b>{escape(c['name'])}</b> начала отправку.")

        while c["running"]:
            if not has_access(ui):
                await handle_access_lost(bot, user_id, ui)
                break
            if not in_window(c["hours"]):
                await asyncio.sleep(30)
                continue

            now = time.monotonic()
            due = [ch for ch in list(c["chats"]) if next_at.get(ch["src"], 0) <= now]
            if not due:
                await asyncio.sleep(1)
                continue

            for ch in due:
                if not c["running"]:
                    break
                src = ch["src"]
                try:
                    if src not in entities:
                        entities[src] = await resolve_target(client, src)
                    entity = entities[src]
                    if c.get("no_repeat", True) and src in no_repeat_last_ids:
                        latest = await client.get_messages(entity, limit=1)
                        last_id = int(no_repeat_last_ids[src])
                        # Повтор разрешается только после нового входящего сообщения от участника.
                        if not latest or latest[0].id <= last_id or latest[0].out:
                            logging.info("[%s] пропуск %s: после предыдущей отправки никто не написал", c['name'], src)
                            next_at[src] = time.monotonic() + max(1, int(ch["interval"]))
                            await asyncio.sleep(max(0, int(c["cd_chats"])))
                            continue
                    if src not in greeted:
                        # первый круг: в новый чат сначала короткое приветствие
                        sent = await client.send_message(entity, random.choice(FIRST_GREETINGS))
                        if getattr(sent, "id", None):
                            no_repeat_last_ids[src] = sent.id
                        greeted.append(src)
                        c["last_sent"] = now_local().strftime("%d.%m.%Y %H:%M")
                        record_event(c, src, True)
                        ui["last_send_ts"] = time.time()
                        reported.discard(src)
                    else:
                        msg = random.choice(c["messages"])
                        reply_to = await pick_reply_id(client, entity, c["reply_mode"]) if msg["type"] != "forward" else None
                        paid = is_sub_active(ui)
                        tag_n = c["hidden_tag"] if paid else 0
                        try:
                            sent = await send_payload(bot, client, entity, msg, reply_to, paid, tag_n)
                        except ValueError:
                            if not tag_n:
                                raise
                            # не удалось отметить участников — отправляем без тегов
                            sent = await send_payload(bot, client, entity, msg, reply_to, paid, 0)
                        sent_items = sent if isinstance(sent, (list, tuple)) else [sent]
                        sent_ids = [getattr(item, "id", None) for item in sent_items if item is not None]
                        if sent_ids:
                            no_repeat_last_ids[src] = max(sent_ids)
                        c["last_sent"] = now_local().strftime("%d.%m.%Y %H:%M")
                        record_event(c, src, True)
                        ui["last_send_ts"] = time.time()
                        reported.discard(src)
                except tg_errors.FloodWaitError as e:
                    logging.warning(f"FloodWait {e.seconds}s")
                    await asyncio.sleep(e.seconds + 1)
                    continue  # повторим этот чат позже, next_at не трогаем
                except Exception as e:
                    logging.error(f"[{c['name']}] ошибка отправки в {src}: {e}")
                    record_event(c, src, False)
                    entities.pop(src, None)
                    if src not in reported:
                        reported.add(src)
                        await notify(f"⚠️ <b>{escape(c['name'])}</b>: не удалось отправить в {escape(src)}\n<code>{escape(str(e))}</code>")
                next_at[src] = time.monotonic() + max(1, int(ch["interval"]))
                await asyncio.sleep(max(0, int(c["cd_chats"])))

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logging.exception("campaign_runner crashed")
        c["running"] = False
        await notify(f"❌ Рассылка <b>{escape(c['name'])}</b> остановлена из-за ошибки:\n<code>{escape(str(e))}</code>")
    finally:
        if RUNNERS.get((user_id, cid)) is asyncio.current_task():
            RUNNERS.pop((user_id, cid), None)


def start_campaign(bot: Bot, user_id: int, user_info: dict, c: dict):
    """Возвращает текст ошибки или None, если рассылка запущена."""
    if not has_access(user_info):
        return "❌ Нужна подписка или бесплатный тариф"
    if not c["account"]:
        return "❌ К рассылке не привязан аккаунт"
    if c["account"] not in user_info["accounts"]:
        return "❌ Аккаунт рассылки не найден — добавьте его заново"
    if not c["messages"]:
        return "❌ Добавьте хотя бы одно сообщение"
    if not c["chats"]:
        return "❌ Добавьте хотя бы один чат"
    key = (user_id, c["id"])
    task = RUNNERS.get(key)
    if task and not task.done():
        c["running"] = True
        return None
    c["running"] = True
    RUNNERS[key] = asyncio.create_task(campaign_runner(bot, user_id, c["id"]))
    return None


def stop_campaign(user_id: int, c: dict):
    c["running"] = False
    task = RUNNERS.pop((user_id, c["id"]), None)
    if task and not task.done():
        task.cancel()


@router.callback_query(F.data.startswith("camp:"))
async def camp_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action = p[1]
    alert = None

    if action == "create":
        user_info["draft"] = None
        await wiz_show(call, state, user_info, "name")
    else:
        c = find_campaign(user_info, p[2]) if len(p) > 2 else None
        if c is None:
            await call.answer("Рассылка не найдена", show_alert=True)
            await show(call, campaigns_text(user_info), campaigns_kb(user_info))
            return
        await state.clear()
        if action == "open":
            await show(call, card_text(c), card_kb(c))
        elif action == "toggle":
            if c["running"]:
                stop_campaign(call.from_user.id, c)
            else:
                alert = start_campaign(call.bot, call.from_user.id, user_info, c)
            await show(call, card_text(c), card_kb(c))
        elif action == "launch":
            alert = start_campaign(call.bot, call.from_user.id, user_info, c)
            if alert:
                await show(call, card_text(c), card_kb(c))
            else:
                await show(call, "🚀 <b>Рассылка запущена!</b>", card_kb(c))

    await call.answer(alert, show_alert=bool(alert))


@router.callback_query(F.data.startswith("mg:"))
async def mg_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action, cid = p[1], p[2]
    c = find_campaign(user_info, cid)
    if c is None:
        await call.answer("Рассылка не найдена", show_alert=True)
        await show(call, campaigns_text(user_info), campaigns_kb(user_info))
        return

    await state.clear()
    alert = None
    back = btn("◀️ Назад", f"camp:open:{cid}")

    if action == "msgs":
        text, markup = msgs_manager_screen(c)
        await show(call, text, markup)

    elif action == "mask":
        idx = int(p[3])
        await show(
            call,
            "Удалить это сообщение из рассылки?",
            kb([btn("✅ Да, удалить", f"mg:mdel:{cid}:{idx}"), btn("Отмена", f"mg:msgs:{cid}")]),
        )

    elif action == "mdel":
        idx = int(p[3])
        if 0 <= idx < len(c["messages"]):
            c["messages"].pop(idx)
        text, markup = msgs_manager_screen(c, "🗑 Сообщение удалено!")
        await show(call, text, markup)

    elif action == "copy":
        others = [x for x in user_info["campaigns"] if x["id"] != c["id"]]
        rows = [[btn(x["name"], f"mg:copyto:{cid}:{x['id']}")] for x in others]
        rows.append([back])
        text = (
            "📋 <b>Копировать сообщения</b>\n\n"
            "Выберите рассылку, в которую скопировать сообщения "
            "(сообщения, которые там уже есть, добавлены не будут):"
        )
        if not others:
            text += "\n\nДругих рассылок пока нет."
        await show(call, text, kb(*rows))

    elif action == "copyto":
        target = find_campaign(user_info, p[3])
        if target:
            for m in c["messages"]:
                if m not in target["messages"] and len(target["messages"]) < MAX_MESSAGES:
                    target["messages"].append(copy.deepcopy(m))
            alert = f"✅ Сохранено в ({target['name'][:40]})"

    elif action == "time":
        await state.set_state(CS.time_range)
        await state.update_data(tgt=cid)
        await show(call, TIME_PROMPT, kb([btn("♾ Работать 24/7", f"mg:time24:{cid}")], [back]))

    elif action == "time24":
        c["hours"] = None
        await show(call, card_text(c), card_kb(c))

    elif action == "acc":
        accs = user_info["accounts"]
        rows = [[acc_btn(a, f"mg:setacc:{cid}:{i}")] for i, a in enumerate(accs)]
        rows.append([back])
        text = "👤 <b>Выберите аккаунт для рассылки:</b>"
        if not accs:
            text += "\n\nУ вас нет добавленных аккаунтов. Добавьте аккаунт в разделе «Аккаунт»."
        await show(call, text, kb(*rows))

    elif action == "setacc":
        idx = int(p[3])
        if 0 <= idx < len(user_info["accounts"]):
            c["account"] = user_info["accounts"][idx]
        await show(call, card_text(c), card_kb(c))

    elif action == "conv":
        text, markup = conv_screen(c)
        await show(call, text, markup)

    elif action == "norepeat":
        text, markup = toggle_screen(c, "norepeat")
        await show(call, text, markup)

    elif action in ("nron", "nroff"):
        c["no_repeat"] = action == "nron"
        c.setdefault("no_repeat_last_ids", {})
        text, markup = toggle_screen(c, "norepeat")
        await show(call, text, markup)

    elif action == "tag":
        text, markup = toggle_screen(c, "tag")
        await show(call, text, markup)

    elif action == "tagon":
        if not is_sub_active(user_info):
            await show(
                call,
                "❌ <b>Скрытый тег недоступен на бесплатном тарифе.</b>\n\n"
                "Перейдите в «Подписка» для активации",
                kb([btn("💎 Подписка", "menu:subscription")], [btn("◀️ Назад", f"mg:conv:{cid}")]),
            )
        else:
            c["hidden_tag"] = 15
            text, markup = toggle_screen(c, "tag")
            await show(call, text, markup)

    elif action == "tagoff":
        c["hidden_tag"] = 0
        text, markup = toggle_screen(c, "tag")
        await show(call, text, markup)

    elif action == "reply":
        text, markup = toggle_screen(c, "reply")
        await show(call, text, markup)

    elif action == "replyoff":
        c["reply_mode"] = None
        text, markup = toggle_screen(c, "reply")
        await show(call, text, markup)

    elif action == "rmenu":
        await show(call, REPLY_TEXT, reply_menu_kb(cid))

    elif action == "rl":
        c["reply_mode"] = ("last",)
        text, markup = toggle_screen(c, "reply")
        await show(call, text, markup)

    elif action == "rn":
        row1 = [btn(str(n), f"mg:rnv:{cid}:{n}") for n in range(1, 8)]
        row2 = [btn(str(n), f"mg:rnv:{cid}:{n}") for n in range(8, 11)]
        await show(
            call,
            "🔢 Выберите позицию с конца (2–10):",
            kb(row1, row2, [btn("◀️ Назад", f"mg:rmenu:{cid}")]),
        )

    elif action == "rnv":
        n = int(p[3])
        if n <= 1:
            c["reply_mode"] = ("last",)
        else:
            c["reply_mode"] = ("nth", n)
        text, markup = toggle_screen(c, "reply")
        await show(call, text, markup)

    elif action == "rr":
        await state.set_state(CS.reply_range)
        await state.update_data(tgt=cid)
        await show(
            call,
            "🎲 Введите диапазон в формате: МИН-МАКС\n\n"
            "Пример: 1-5 (случайное сообщение с 1-й по 5-ю позицию с конца)\n"
            "Максимальное значение: 10",
            kb([btn("◀️ Назад", f"mg:rmenu:{cid}")]),
        )

    elif action == "stats":
        text, markup = stats_screen(c)
        await show(call, text, markup)

    elif action == "noads":
        if is_sub_active(user_info):
            alert = "✅ У вас активна подписка — реклама в рассылках отключена"
        else:
            text, markup = subscription_screen(user_info)
            await show(call, text, markup)

    elif action == "delask":
        await show(
            call,
            f"❓ Вы уверены, что хотите удалить рассылку «{escape(c['name'])}»?",
            kb([btn("✅ Да, удалить", f"mg:del:{cid}"), btn("◀️ Назад", f"camp:open:{cid}")]),
        )

    elif action == "del":
        stop_campaign(call.from_user.id, c)
        user_info["campaigns"] = [x for x in user_info["campaigns"] if x["id"] != c["id"]]
        alert = "✅ Рассылка удалена"
        await show(call, campaigns_text(user_info), campaigns_kb(user_info))

    await call.answer(alert, show_alert=bool(alert))


@router.callback_query(F.data.startswith("acc:"))
async def acc_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action = p[1]
    alert = None

    if action == "add":
        used, limit = len(user_info["accounts"]), account_limit(user_info)
        if used >= limit:
            alert = f"❌ Достигнут лимит аккаунтов ({used}/{limit}). Оформите подписку, чтобы добавить больше."
        else:
            await state.clear()
            text, markup = add_account_screen(user_info)
            await show(call, text, markup)

    elif action == "proxy":
        await state.clear()
        await state.set_state(AccState.proxy)
        await show(call, PROXY_PROMPT, kb([btn("◀️ Назад", "acc:add")]))

    elif action == "skip":
        await state.clear()
        await state.update_data(proxy=None)
        await show(call, STEP2_TEXT, step2_kb())

    elif action == "step2":
        await state.set_state(None)
        await show(call, STEP2_TEXT, step2_kb())

    elif action == "api":
        await state.set_state(AccState.api_id)
        await show(
            call,
            "🔑 <b>Введите идентификатор API</b> (число):\n\nПолучить: https://my.telegram.org",
            kb([btn("◀️ Назад", "acc:step2")]),
        )

    elif action == "apiskip":
        await state.update_data(api_id=None, api_hash=None)
        try:
            await call.message.delete()
        except Exception:
            pass
        await send_step3(call.message, state)

    elif action == "open":
        idx = int(p[2])
        if 0 <= idx < len(user_info["accounts"]):
            phone = user_info["accounts"][idx]
            proxy = user_info["proxies"].get(phone)
            text = (
                f"👤 <b>Аккаунт {escape(phone)}</b>\n\n"
                f"Прокси: {escape(proxy) if proxy else 'не используется'}"
            )
            await show(call, text, kb([btn("🗑 Удалить аккаунт", f"acc:ask:{idx}")], [btn("◀️ Назад", "menu:account")]))

    elif action == "ask":
        idx = int(p[2])
        await show(
            call,
            "Удалить аккаунт?",
            kb([btn("✅ Да, удалить", f"acc:del:{idx}"), btn("Отмена", f"acc:open:{idx}")]),
        )

    elif action == "del":
        idx = int(p[2])
        if 0 <= idx < len(user_info["accounts"]):
            phone = user_info["accounts"].pop(idx)
            user_info["proxies"].pop(phone, None)
            # прогрев удалённого аккаунта останавливаем и очищаем
            stop_warmup(call.from_user.id, user_info, phone)
            user_info.get("warmup", {}).pop(phone, None)
        text, markup = account_screen(user_info)
        await show(call, text, markup)

    await call.answer(alert, show_alert=bool(alert))


@router.message(AccState.proxy)
async def acc_proxy_input(message: Message, state: FSMContext):
    proxy = (message.text or "").strip()
    if not re.fullmatch(r"socks5://(?:[^\s:@/]+:[^\s:@/]+@)?[^\s:@/]+:\d{2,5}", proxy):
        await message.answer(
            "❌ Неверный формат прокси. Пример:\nsocks5://host:port\nили socks5://user:pass@host:port"
        )
        return
    await state.update_data(proxy=proxy)
    await state.set_state(None)
    await message.answer(STEP2_TEXT, reply_markup=step2_kb(), parse_mode="HTML")


@router.message(AccState.api_id)
async def acc_api_id_input(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if not re.fullmatch(r"\d{4,10}", t):
        await message.answer(
            "❌ Идентификатор API — это число. Введите ещё раз:",
            reply_markup=kb([btn("◀️ Назад", "acc:step2")]),
        )
        return
    await state.update_data(api_id=int(t))
    await state.set_state(AccState.api_hash)
    await message.answer("Введите хэш API:", reply_markup=kb([btn("◀️ Назад", "acc:api")]))


@router.message(AccState.api_hash)
async def acc_api_hash_input(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", t):
        await message.answer(
            "❌ Хэш API — 32 символа (цифры и буквы a–f). Введите ещё раз:",
            reply_markup=kb([btn("◀️ Назад", "acc:api")]),
        )
        return
    await state.update_data(api_hash=t)
    await send_step3(message, state)


async def open_login_client(session_path: str, proxy: str = None, api_id: int = None, api_hash: str = None) -> TelegramClient:
    """Подключается к Telegram для входа в аккаунт (с повторными попытками и прокси, если задан)."""
    client = TelegramClient(
        session_path, api_id or API_ID, api_hash or API_HASH,
        proxy=make_proxy(proxy),
        connection_retries=3, retry_delay=2, timeout=15,
        receive_updates=False,
    )
    last = None
    for _ in range(3):
        try:
            await client.connect()
            if client.is_connected():
                return client
        except Exception as e:
            last = e
        await asyncio.sleep(2)
    try:
        await client.disconnect()
    except Exception:
        pass
    raise ConnectionError(
        f"не удалось подключиться к Telegram ({last or 'нет соединения'}). "
        "Проверьте интернет/VPN или добавьте рабочий прокси."
    )


async def safe_disconnect(client):
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass


@router.message(AccState.phone, F.document)
async def acc_session_file(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    data = await state.get_data()
    doc = message.document
    name = (doc.file_name or "").lower()

    if name.endswith(".zip"):
        await message.answer("ℹ️ Импорт TData (.zip) пока не поддерживается. Отправьте Telethon .session или введите номер телефона.")
        return
    if not name.endswith(".session"):
        await message.answer("❌ Отправьте файл .session или введите номер телефона.")
        return
    if doc.file_size and doc.file_size > 5_000_000:
        await message.answer("❌ Файл слишком большой.")
        return
    if len(user_info["accounts"]) >= account_limit(user_info):
        await state.clear()
        await drop_reply_kb(message)
        await message.answer("❌ Достигнут лимит аккаунтов.")
        return

    tmp_base = os.path.join(SESSIONS_DIR, f"import_{message.from_user.id}_{int(time.time())}")
    tmp_file = tmp_base + ".session"
    client = None
    try:
        await message.bot.download(doc, destination=tmp_file)

        con = sqlite3.connect(tmp_file)
        try:
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        finally:
            con.close()
        if "entities" not in tables:
            await message.answer("ℹ️ Это не Telethon .session (формат Pyrogram пока не поддерживается). Отправьте Telethon .session или введите номер телефона.")
            return

        client = await open_login_client(tmp_base, data.get("proxy"), data.get("api_id"), data.get("api_hash"))
        if not await client.is_user_authorized():
            raise RuntimeError("сессия не авторизована (аккаунт вышел или сессия устарела)")
        me = await client.get_me()
        phone = "+" + str(me.phone)
        await safe_disconnect(client)
        client = None

        if phone in user_info["accounts"]:
            await message.answer("ℹ️ Этот аккаунт уже добавлен.")
            return

        final_base = os.path.join(SESSIONS_DIR, f"session_{phone.replace('+', '')}")
        os.replace(tmp_file, final_base + ".session")

        user_info["accounts"].append(phone)

        spawn(backup_sessions())
        if data.get("proxy"):
            user_info["proxies"][phone] = data["proxy"]
        if data.get("api_id") and data.get("api_hash"):
            user_info.setdefault("apis", {})[phone] = (data["api_id"], data["api_hash"])

        await state.clear()
        await drop_reply_kb(message)
        text, markup = account_screen(user_info)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось импортировать сессию: {e}")
    finally:
        await safe_disconnect(client)
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass


@router.message(AccState.phone)
async def acc_phone_input(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    data = await state.get_data()
    proxy = data.get("proxy")

    text_in = (message.text or "").strip()
    if text_in in ("◀️ Назад", "Назад"):
        await drop_reply_kb(message)
        await state.set_state(None)
        await message.answer(STEP2_TEXT, reply_markup=step2_kb(), parse_mode="HTML")
        return

    raw_src = message.contact.phone_number if message.contact else text_in
    raw = re.sub(r"[\s\-()]", "", raw_src or "")
    if not re.fullmatch(r"\+?\d{10,15}", raw):
        await message.answer("❌ Неверный номер. Пример: <code>+12345678913</code>", parse_mode="HTML")
        return
    phone = "+" + raw.lstrip("+")

    if phone in user_info["accounts"]:
        await message.answer("ℹ️ Этот аккаунт уже добавлен. Введите другой номер:")
        return
    if len(user_info["accounts"]) >= account_limit(user_info):
        await state.clear()
        await drop_reply_kb(message)
        await message.answer("❌ Достигнут лимит аккаунтов.")
        return

    wait_msg = await message.answer("⏳ Отправляю код…", reply_markup=ReplyKeyboardRemove())
    safe_phone = phone.replace("+", "")
    session_path = os.path.join(SESSIONS_DIR, f"session_{safe_phone}")
    # удаляем старую (возможно битую) сессию незавершённого входа
    for suffix in (".session", ".session-journal"):
        try:
            os.remove(session_path + suffix)
        except OSError:
            pass
    client = None

    try:
        client = await open_login_client(session_path, proxy, data.get("api_id"), data.get("api_hash"))
        sent_code = await client.send_code_request(phone)

        await state.update_data(
            phone=phone,
            phone_code_hash=sent_code.phone_code_hash,
            session_path=session_path
        )
        await safe_disconnect(client)

        await state.update_data(digits="")
        await state.set_state(AccState.code)
        await message.answer(code_text(""), reply_markup=code_kb(), parse_mode="HTML")

    except Exception as e:
        await safe_disconnect(client)
        hint = "" if isinstance(e, ConnectionError) else "\nПроверьте правильность номера."
        await message.answer(f"❌ Ошибка отправки кода: {e}{hint}")
        await state.clear()
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass


CODE_LEN = 5
KEYCAPS = [str(n) for n in range(10)]


def code_text(digits: str) -> str:
    shown = "в—ѕ" * len(digits) + "в—Ѕ" * (CODE_LEN - len(digits))
    return (
        f"{pe(E_PHONE, '📱')} <b>Код отправлен!</b>\n\n"
        f"{pe(E_PHONE2, '📲')} Проверьте приложение Telegram на других ваших устройствах или в веб-версии Telegram — код придет туда.\n\n"
        f"{pe(E_NUM, '🔢')} Введите код с помощью кнопок:\n\n"
        f"Код: {shown}"
    )


def code_kb() -> InlineKeyboardMarkup:
    def d(n):
        return btn(KEYCAPS[n], f"code:d:{n}")
    return kb(
        [d(1), d(2), d(3)],
        [d(4), d(5), d(6)],
        [d(7), d(8), d(9)],
        # мусорка: красная + премиум-иконка (Telegram не принимает кнопку без текста)
        [pbtn("Стереть", "code:clear", E_TRASH, "danger"), d(0), btn("⌫", "code:bs")],
        [btn("◀️ Назад", "code:back"), btn("✅ Подтвердить", "code:ok")],
    )


@router.message(AccState.code)
async def acc_code_text_blocked(message: Message):
    # Код, отправленный текстом в Telegram, аннулируется самим Telegram — поэтому только кнопки.
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer("⚠️ Вводите код только кнопками под сообщением с кодом — так Telegram его не аннулирует.")


@router.callback_query(F.data.startswith("code:"), AccState.code)
async def code_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    action = call.data.split(":")[1]
    data = await state.get_data()
    digits = data.get("digits", "")

    if action == "back":
        await state.clear()
        text, markup = account_screen(user_info)
        await show(call, text, markup)
        await call.answer()
        return

    if action == "ok":
        if len(digits) < CODE_LEN:
            await call.answer(f"Нужен {CODE_LEN}-значный код", show_alert=True)
            return

        phone = data.get("phone")
        phone_code_hash = data.get("phone_code_hash")
        session_path = data.get("session_path")
        proxy = data.get("proxy")
        client = None

        try:
            client = await open_login_client(session_path, proxy, data.get("api_id"), data.get("api_hash"))
            await client.sign_in(phone=phone, code=digits, phone_code_hash=phone_code_hash)
            await safe_disconnect(client)

            user_info["accounts"].append(phone)

            spawn(backup_sessions())
            if data.get("api_id") and data.get("api_hash"):
                user_info.setdefault("apis", {})[phone] = (data["api_id"], data["api_hash"])
            if proxy:
                user_info["proxies"][phone] = proxy

            await state.clear()
            text, markup = account_screen(user_info)
            await show(call, text, markup)
            await call.answer()

        except SessionPasswordNeededError:
            await safe_disconnect(client)
            await state.set_state(AccState.password)
            await show(
                call,
                "🛡️ Требуется пароль для двухфакторной аутентификации.\n\nВведите пароль:",
                kb([btn("◀️ Назад", "menu:account")]),
            )
            await call.answer()

        except tg_errors.PhoneCodeInvalidError:
            await safe_disconnect(client)
            await state.update_data(digits="")
            await show(call, code_text(""), code_kb())
            await call.answer("❌ Неверный код, введите заново", show_alert=True)

        except tg_errors.PhoneCodeExpiredError:
            await safe_disconnect(client)
            await state.clear()
            text, markup = account_screen(user_info)
            await show(call, text, markup)
            await call.answer("❌ Код истёк. Добавьте аккаунт заново и запросите новый код.", show_alert=True)

        except Exception as e:
            await safe_disconnect(client)
            await state.clear()
            text, markup = account_screen(user_info)
            await show(call, text, markup)
            await call.answer(f"❌ Ошибка: {e}"[:190], show_alert=True)
        return

    # цифры / стирание
    if action == "d":
        if len(digits) >= CODE_LEN:
            await call.answer()
            return
        digits += call.data.split(":")[2]
    elif action == "bs":
        digits = digits[:-1]
    elif action == "clear":
        digits = ""

    await state.update_data(digits=digits)
    await show(call, code_text(digits), code_kb())
    await call.answer()


@router.callback_query(F.data.startswith("code:"))
async def code_cb_expired(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    text, markup = account_screen(user_info)
    await show(call, text, markup)
    await call.answer("Сессия ввода кода истекла. Добавьте аккаунт заново.", show_alert=True)


@router.message(AccState.password)
async def acc_password_input(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()

    phone = data.get("phone")
    session_path = data.get("session_path")
    proxy = data.get("proxy")
    user_info = get_user(message.from_user.id)

    client = None

    try:
        client = await open_login_client(session_path, proxy, data.get("api_id"), data.get("api_hash"))
        await client.sign_in(password=password)
        await safe_disconnect(client)

        user_info["accounts"].append(phone)

        spawn(backup_sessions())
        if data.get("api_id") and data.get("api_hash"):
            user_info.setdefault("apis", {})[phone] = (data["api_id"], data["api_hash"])
        if proxy:
            user_info["proxies"][phone] = proxy

        await state.clear()
        text, markup = account_screen(user_info)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        await safe_disconnect(client)
        await message.answer(f"❌ Неверный пароль: {e}\nПопробуйте начать добавление сначала.")
        await state.clear()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    await state.clear()
    user_id = message.from_user.id
    name = message.from_user.first_name or message.from_user.username or "друг"

    is_new = user_id not in user_data_db
    user_info = get_user(user_id)
    user_info["username"] = message.from_user.username
    user_info["first_name"] = name

    arg = command.args or ""
    if is_new and arg.startswith("ref_") and arg[4:].isdigit():
        ref_id = int(arg[4:])
        if ref_id != user_id and ref_id in user_data_db:
            user_info["referred_by"] = ref_id
            user_data_db[ref_id]["referrals"].append(user_id)

    await message.answer(
        main_menu_text(name),
        reply_markup=main_menu_kb(is_admin(user_id)),
        parse_mode="HTML",
    )

    if not user_info["has_received_promo"] and not user_info["promo_used"]:
        user_info["has_received_promo"] = True

        promo_text = (
            f"{pe('5377599075237502153', '🎟')} <b>Промокод в подарок!</b>\n"
            f"{pe('5389038097860144794', '🔥')} 1 день бесплатного доступа — специально для тебя:\n"
            "<code>free</code>\n\n"
            f"{pe('5438496463044752972', '⭐')} Активируй в разделе «Подписка»"
        )
        promo_msg = await message.answer(promo_text, parse_mode="HTML")
        user_info["promo_message_id"] = promo_msg.message_id

        try:
            await message.bot.pin_chat_message(
                chat_id=message.chat.id,
                message_id=promo_msg.message_id
            )
        except Exception as e:
            logging.error(f"Не удалось закрепить сообщение: {e}")


@router.callback_query(F.data.startswith("menu:"))
async def menu_router(call: CallbackQuery, state: FSMContext):
    await state.clear()
    section = call.data.split(":")[1]
    user_id = call.from_user.id
    user_info = get_user(user_id)

    if section == "back":
        name = call.from_user.first_name or call.from_user.username or "друг"
        await call.message.edit_text(
            main_menu_text(name),
            reply_markup=main_menu_kb(is_admin(user_id)),
            parse_mode="HTML",
        )
    elif section == "subscription":
        text, markup = subscription_screen(user_info)
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif section == "campaigns":
        if has_access(user_info):
            await show(call, campaigns_text(user_info), campaigns_kb(user_info))
        else:
            text, markup = subscription_screen(user_info)
            await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif section == "account":
        text, markup = account_screen(user_info)
        await show(call, text, markup)
    elif section == "referrals":
        text, markup = await referrals_screen(call.bot, user_id, user_info)
        await show(call, text, markup)
    elif section == "tools":
        text, markup = tools_screen()
        await show(call, text, markup)
    elif section == "help":
        text, markup = help_screen()
        await show(call, text, markup)
    else:
        await call.message.edit_text(
            "Раздел в разработке.",
            reply_markup=kb([btn("◀️ Назад", "menu:back")]),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data.startswith("sub:"))
async def sub_router(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":")[1]
    user_info = get_user(call.from_user.id)

    if action == "promo":
        await state.set_state(PromoState.waiting_for_promo)
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:subscription")]
        ])
        await call.message.edit_text(
            "🎟 <b>Введите промокод:</b>",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
    elif action == "free":
        if user_info.get("free_plan"):
            await call.answer("ℹ️ Бесплатный тариф уже активирован", show_alert=True)
            return
        await call.message.edit_text(
            free_plan_text(),
            reply_markup=free_plan_kb(),
            parse_mode="HTML"
        )
    elif action == "free_on":
        if user_info.get("free_plan"):
            await call.answer("ℹ️ Бесплатный тариф уже активирован", show_alert=True)
            return
        user_info["free_plan"] = True
        await call.answer("✅ Бесплатный тариф активирован", show_alert=True)
        text, markup = subscription_screen(user_info)
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        return
    await call.answer()


@router.message(PromoState.waiting_for_promo)
async def process_promo_input(message: Message, state: FSMContext):
    promo_text = (message.text or "").strip().lower()
    user_id = message.from_user.id
    user_info = get_user(user_id)

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:subscription")]
    ])

    if promo_text == "free":
        if user_info["promo_used"]:
            await message.answer(
                "❌ <b>Вы уже использовали этот промокод!</b>",
                reply_markup=back_kb,
                parse_mode="HTML"
            )
            return

        await state.clear()
        user_info["promo_used"] = True
        user_info["is_active"] = True
        user_info["free_plan"] = False

        grant_sub(user_info, 1)
        expiry_date = user_info["expiry"]
        save_sub(user_id)
        expiry_str = expiry_date.strftime("%d.%m.%Y %H:%M")

        if user_info["promo_message_id"]:
            try:
                await message.bot.delete_message(
                    chat_id=message.chat.id,
                    message_id=user_info["promo_message_id"]
                )
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение с промокодом: {e}")
            user_info["promo_message_id"] = None

        success_text = (
            "✅ <b>Промокод активирован!</b>\n"
            "Добавлено дней: 1\n"
            f"Подписка активна до: {expiry_str}"
        )
        await message.answer(success_text, reply_markup=active_sub_kb(), parse_mode="HTML")
    else:
        await message.answer(
            "❌ <b>Неверный промокод!</b>\nПопробуйте ввести ещё раз:",
            reply_markup=back_kb,
            parse_mode="HTML"
        )



# ============================================================
# 🔗 КНОПКИ ПОД СООБЩЕНИЯМИ РАССЫЛКИ (платный тариф)
# ============================================================
MAX_MSG_BUTTONS = 3
STYLE_DOTS = {"primary": "🔵", "danger": "🔴", "success": "🟢", None: "⚪"}
COLOR_CODES = {"p": "primary", "d": "danger", "s": "success", "n": None}


def normalize_url(raw: str):
    """https://site.ru, t.me/channel, @username -> нормальная https-ссылка (или None)."""
    t = (raw or "").strip()
    m = re.fullmatch(r"@([A-Za-z][A-Za-z0-9_]{3,31})", t)
    if m:
        return f"https://t.me/{m.group(1)}"
    t2 = re.sub(r"^https?://", "", t, flags=re.IGNORECASE)
    if re.fullmatch(r"(?:t|telegram)\.me/\S+", t2, re.IGNORECASE):
        return "https://" + t2
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)+(?:[/?#]\S*)?", t2):
        return "https://" + t2
    return None


def buttons_lines(msg: dict) -> str:
    return "\n".join(
        f"{STYLE_DOTS.get(b.get('style'), 'вљЄ')} {escape(b['text'])} в†’ {escape(b['url'])}"
        for b in (msg.get("buttons") or [])
    )


def msg_buttons_markup(msg: dict):
    """Настоящие inline-кнопки — для предпросмотра, который шлёт сам бот."""
    bs = msg.get("buttons") or []
    if not bs:
        return None
    rows = []
    for b in bs:
        kw = {"text": b["text"], "url": b["url"]}
        if b.get("style"):
            kw["style"] = b["style"]
        else:
            kw["text"] = b["text"] + PLAIN_MARK
        rows.append([InlineKeyboardButton(**kw)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buttons_as_links_html(msg: dict) -> str:
    """Аккаунт (Telethon) не может отправлять inline-кнопки, поэтому в рассылке кнопки идут ссылками под текстом."""
    bs = msg.get("buttons") or []
    if not bs:
        return ""
    lines = [f'🔗 <a href="{escape(b["url"], quote=True)}">{escape(b["text"])}</a>' for b in bs]
    return "\n\n" + "\n".join(lines)


def btn_question_screen(kind: str, tgt: str, idx: int):
    text = f"✅ {kind}!\n\n🔗 Добавить кнопку?\nПод сообщением будет кнопка со ссылкой."
    return text, kb([
        pbtn("ДА", f"bt:yes:{tgt}:{idx}", E_OK, "success"),
        pbtn("Пропустить", f"bt:skip:{tgt}:{idx}", E_PLAY, "danger"),
    ])


def btn_url_screen(tgt: str, idx: int):
    text = (
        "🔗 Отправьте ссылку или @username для кнопки.\n\n"
        "Например: <code>https://site.ru</code>, <code>t.me/channel</code> или <code>@username</code>"
    )
    return text, kb([pbtn("Пропустить", f"bt:skip:{tgt}:{idx}", E_PLAY, "primary")])


def btn_color_screen(label: str, tgt: str, idx: int):
    def b(text, code, style=None):
        kw = {"text": text, "callback_data": f"bt:c:{tgt}:{idx}:{code}"}
        if style:
            kw["style"] = style
        return InlineKeyboardButton(**kw)
    return "🎨 Выберите цвет кнопки — нажмите на подходящую:", kb(
        [b(label, "p", "primary")],
        [b(label, "d", "danger")],
        [b(label, "s", "success")],
        [b(label + PLAIN_MARK, "n")],
    )


def btn_summary_screen(msg: dict, tgt: str, idx: int):
    n = len(msg.get("buttons") or [])
    text = f"✅ Кнопка добавлена ({n}/{MAX_MSG_BUTTONS}).\n\n{buttons_lines(msg)}"
    return text, kb(
        [pbtn("Добавить ещё", f"bt:more:{tgt}:{idx}", E_PLUS, "primary")],
        [InlineKeyboardButton(text="👁️ Предосмотр", callback_data=f"bt:prev:{tgt}:{idx}", style="primary")],
        [pbtn("Продолжить", f"bt:done:{tgt}:{idx}", E_OK, "success")],
    )


async def bt_leave(target, state: FSMContext, user_info: dict, c: dict, tgt: str, idx: int):
    """Выход из мастера кнопки: назад к списку сообщений (или к редактору сообщения)."""
    d = user_info.get("btn_draft") or {}
    same = d.get("tgt") == tgt and d.get("idx") == idx
    origin = d.get("origin", "add") if same else "add"
    kind = (d.get("kind") if same else None) or "Сообщение добавлено"
    user_info["btn_draft"] = None
    await state.clear()
    if origin == "edit":
        text, markup = message_editor_screen(c, tgt, idx)
    else:
        # как и раньше: после добавления сообщения можно сразу слать следующее
        await state.set_state(CS.add_message)
        await state.update_data(tgt=tgt)
        n = len(c["messages"])
        if tgt == "w":
            text, markup = msgs_wizard_screen(c, f"{OK} {kind}! Всего сообщений: {n}")
        else:
            text, markup = msgs_manager_screen(c, f"{OK} {kind}!")
    await show(target, text, markup)


@router.callback_query(F.data.startswith("bt:"))
async def bt_cb(call: CallbackQuery, state: FSMContext):
    user_info = get_user(call.from_user.id)
    p = call.data.split(":")
    action, tgt, idx = p[1], p[2], int(p[3])
    c = find_campaign(user_info, tgt)
    if c is None or not (0 <= idx < len(c.get("messages", []))):
        await call.answer("Сообщение не найдено", show_alert=True)
        return
    msg = c["messages"][idx]
    alert = None

    if action in ("yes", "more"):
        if not is_sub_active(user_info):
            alert = "Кнопки доступны только на платном тарифе 🔒"
        elif msg.get("type") not in ("text", "photo", "video"):
            alert = "К этому типу сообщений кнопку добавить нельзя."
        elif len(msg.get("buttons") or []) >= MAX_MSG_BUTTONS:
            alert = f"Максимум {MAX_MSG_BUTTONS} кнопки на сообщение."
        else:
            d = user_info.get("btn_draft")
            if not (d and d.get("tgt") == tgt and d.get("idx") == idx):
                user_info["btn_draft"] = {"tgt": tgt, "idx": idx, "origin": "add", "kind": "Сообщение добавлено"}
            await state.clear()
            await state.set_state(CS.btn_url)
            text, markup = btn_url_screen(tgt, idx)
            await show(call, text, markup)

    elif action in ("skip", "done"):
        await bt_leave(call, state, user_info, c, tgt, idx)

    elif action == "c":
        d = user_info.get("btn_draft")
        if not d or not d.get("url") or not d.get("text"):
            alert = "Сессия устарела — начните добавление кнопки заново."
        elif len(msg.get("buttons") or []) >= MAX_MSG_BUTTONS:
            alert = f"Максимум {MAX_MSG_BUTTONS} кнопки на сообщение."
        else:
            msg.setdefault("buttons", []).append({
                "text": d["text"], "url": d["url"], "style": COLOR_CODES.get(p[4]),
            })
            d["url"] = d["text"] = None
            text, markup = btn_summary_screen(msg, tgt, idx)
            await show(call, text, markup)

    elif action == "prev":
        try:
            await send_message_preview(call.bot, call.from_user.id, msg)
            alert = "Предпросмотр отправлен отдельным сообщением."
        except Exception as e:
            alert = f"Не удалось показать предпросмотр: {str(e)[:180]}"

    elif action == "clear":
        msg["buttons"] = []
        text, markup = message_editor_screen(c, tgt, idx)
        await show(call, text, markup)

    await call.answer(alert, show_alert=bool(alert))


@router.message(CS.btn_url)
async def on_btn_url(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    d = user_info.get("btn_draft")
    if not d:
        await state.clear()
        await message.answer("⚠️ Сессия устарела. Откройте сообщение и добавьте кнопку заново.")
        return
    url = normalize_url(message.text or "")
    if not url:
        await message.answer(
            "❌ Не похоже на ссылку. Пример: <code>https://site.ru</code>, "
            "<code>t.me/channel</code> или <code>@username</code>"
        )
        return
    d["url"] = url
    await state.set_state(CS.btn_text)
    await message.answer(f"✅ Ссылка: {escape(url)}\n\n✏️ Введите текст кнопки (до 40 символов):")


@router.message(CS.btn_text)
async def on_btn_text(message: Message, state: FSMContext):
    user_info = get_user(message.from_user.id)
    d = user_info.get("btn_draft")
    if not d or not d.get("url"):
        await state.clear()
        await message.answer("⚠️ Сессия устарела. Откройте сообщение и добавьте кнопку заново.")
        return
    label = " ".join((message.text or "").split())
    if not label or len(label) > 40:
        await message.answer("❌ Текст кнопки — от 1 до 40 символов. Введите ещё раз:")
        return
    d["text"] = label
    await state.set_state(None)
    text, markup = btn_color_screen(label, d["tgt"], d["idx"])
    await message.answer(text, reply_markup=markup)


# ============================================================
# ❗ НАПОМИНАНИЕ ОБ ОКОНЧАНИИ ПОДПИСКИ (за 23:55 до конца)
# ============================================================
SUB_REMIND_BEFORE = timedelta(hours=23, minutes=55)
REMIND_TEXT = (
    "❗️ <b>Подписка заканчивается завтра!</b>\n\n"
    "Продлите сейчас, чтобы не потерять доступ к функциям."
)


# ------------------------------------------------------------
# ⚠️ ПОДПИСКА ИСТЕКЛА: останавливаем всё и показываем экран с двумя кнопками
# ------------------------------------------------------------
def sub_expired_text(stopped: int) -> str:
    return (
        f"{pe(E_WARN, '⚠️')} <b>Ваша подписка истекла.</b>\n\n"
        f"{pe(E_BAN, '⛔️')} Остановлено рассылок: {stopped}\n"
        "Доступ к авторассылкам и автоответчику ограничен.\n\n"
        f"{pe(E_ROTATE, '🔄')} Продлите подписку или включите бесплатный тариф\n"
        "для продолжения работы."
    )


def sub_expired_kb() -> InlineKeyboardMarkup:
    # по одной кнопке в ряд, обе зелёные (success) с премиум-иконками
    return kb(
        [pbtn("Продлить подписку", "pay:methods", PREMIUM_IDS["💳"], "success")],
        [pbtn("Включить бесплатный тариф", "sub:free", PREMIUM_IDS["🆓"], "success")],
    )


def stop_everything_for_user(user_id: int, ui: dict) -> int:
    """Останавливает рассылки, автоответчики (парсеры) и прогревы пользователя.
    Возвращает число остановленных рассылок. Текущую задачу (если вызвали из неё) не отменяет."""
    cur = asyncio.current_task()
    stopped = 0
    for c in ui.get("campaigns", []):
        if c.get("running"):
            stopped += 1
        c["running"] = False
        key = (user_id, c["id"])
        t = RUNNERS.get(key)
        if t is not None and t is not cur:
            RUNNERS.pop(key, None)
            if not t.done():
                t.cancel()
    for p in parsers_of(ui):
        if p.get("running"):
            stop_parser(user_id, p)
    for phone, w in list(ui.get("warmup", {}).items()):
        if w.get("running"):
            if WARM_TASKS.get((user_id, phone)) is cur:
                w["running"] = False
            else:
                stop_warmup(user_id, ui, phone)
    return stopped


async def handle_access_lost(bot: Bot, user_id: int, ui: dict):
    """Подписка закончилась (и бесплатный тариф не включён): всё останавливаем и один раз уведомляем."""
    exp = ui.get("expiry")
    already = exp is not None and ui.get("expiry_notified") == exp
    ui["expiry_notified"] = exp
    ui["is_active"] = False
    stopped = stop_everything_for_user(user_id, ui)   # без await — гонки между задачами исключены
    if already:
        return
    try:
        await bot.send_message(user_id, sub_expired_text(stopped), reply_markup=sub_expired_kb())
    except Exception as e:
        logging.warning(f"Уведомление об окончании подписки не доставлено {user_id}: {e}")


async def subscription_reminder_loop(bot: Bot):
    while True:
        try:
            now = datetime.now()
            for uid, ui in list(user_data_db.items()):
                exp = ui.get("expiry")
                if exp and exp <= now:
                    # срок вышел: один раз останавливаем всё и шлём экран «подписка истекла»
                    if ui.get("expiry_notified") != exp:
                        if ui.get("free_plan"):
                            ui["is_active"] = False
                            ui["expiry_notified"] = exp
                        else:
                            await handle_access_lost(bot, uid, ui)
                    continue
                if not (ui.get("is_active") and exp and exp > now):
                    continue
                if exp - now > SUB_REMIND_BEFORE or ui.get("reminded_expiry") == exp:
                    continue
                ui["reminded_expiry"] = exp  # одно напоминание на каждый срок подписки
                try:
                    await bot.send_message(
                        uid, REMIND_TEXT,
                        reply_markup=kb([btn("💳 Продлить подписку", "pay:methods")]),
                    )
                except Exception as e:
                    logging.warning(f"Напоминание о подписке не доставлено {uid}: {e}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("subscription_reminder_loop")
        await asyncio.sleep(30)


# ============================================================
# 🔎 ПАРСЕР СООБЩЕНИЙ
# ============================================================
PARSER_MAX_ACTIVE = 3
PARSER_MAX_CHATS = 20
# False — автоответ уходит ответом на сообщение автора прямо в группе (по умолчанию)
# True  — автоответ уходит автору в личные сообщения
AUTOREPLY_IN_DM = False

PARSER_TASKS = {}   # (user_id, parser_id) -> asyncio.Task (запуск)
PARSERS = {}        # (user_id, parser_id) -> {"client", "handler"}

PARSER_INTRO = (
    "🔎 <b>Парсер сообщений</b>\n\n"
    "Слушает выбранные чаты и присылает вам сообщения, которые совпали с заданными ключевыми словами.\n\n"
    "<b>Как это работает:</b>\n"
    "1️⃣ Выбираете аккаунт и чаты для отслеживания\n"
    "2️⃣ Задаёте ключевые слова — на что реагировать\n"
    "3️⃣ Задаёте стоп-слова — что игнорировать (необязательно)\n"
    "4️⃣ По желанию — автоответ в чат на совпадение (один раз на автора)\n\n"
    "Каждый найденный автор — уведомление и автоответ ровно один раз, "
    "повторно тот же человек больше не потревожит.\n\n"
    f"Лимит: до {PARSER_MAX_ACTIVE} активных парсеров, до {PARSER_MAX_CHATS} чатов на аккаунт."
)
PS_STEP2_TEXT = (
    "Шаг 2/4: Отправьте чат для отслеживания (ссылку, @username или ID).\n"
    "Можно добавить несколько — по одному сообщению за раз."
)
PS_STEP3_TEXT = "Шаг 3/4: Введите ключевые слова через запятую — сообщение должно содержать хотя бы одно из них:"
PS_STEP4_TEXT = (
    "Шаг 4/4: Введите стоп-слова через запятую (сообщения с ними будут игнорироваться) — "
    "или нажмите «Пропустить»:"
)
PS_ASK_TEXT = "Отправлять автоответ в чат при совпадении? Уходит только один раз на каждого автора."
PS_REPLY_TEXT = "Введите текст автоответа (уйдёт в чат один раз на каждого автора совпадения):"


def parser_menu_screen():
    return PARSER_INTRO, kb(
        [pbtn("Настроить парсер", "ps:new", E_GEAR, "success")],
        [pbtn("Мои парсеры", "ps:list", E_DOC, "primary")],
        [btn("◀️ Назад", "menu:tools")],
    )


def parsers_of(ui: dict) -> list:
    return ui.setdefault("parsers", [])


def find_parser(ui: dict, pid):
    for p in parsers_of(ui):
        if str(p["id"]) == str(pid):
            return p
    return None


def active_parsers(ui: dict) -> list:
    return [p for p in parsers_of(ui) if p.get("running")]


def free_accounts(ui: dict) -> list:
    busy = {p["account"] for p in active_parsers(ui)}
    return [a for a in ui["accounts"] if a not in busy]


def _norm_text(s: str) -> str:
    return (s or "").lower().replace("ё", "е")


def parse_words(text: str) -> list:
    out, seen = [], set()
    for w in re.split(r"[,\n;]+", text or ""):
        w = " ".join(w.split())
        if w and _norm_text(w) not in seen:
            seen.add(_norm_text(w))
            out.append(w[:64])
    return out[:100]


def parser_match(text: str, keywords: list, stops: list) -> bool:
    """Нужно хотя бы одно ключевое слово и ни одного стоп-слова."""
    t = _norm_text(text)
    if not any(_norm_text(k) in t for k in keywords):
        return False
    return not any(_norm_text(s) in t for s in stops)


def parser_summary(p: dict) -> str:
    return (
        f"Аккаунт: {escape(p['account'])}\n"
        f"Чатов: {len(p['chats'])}\n"
        f"Ключевые слова: {escape(', '.join(p['keywords']))}\n"
        f"Стоп-слова: {escape(', '.join(p['stop']) or '—')}\n"
        f"Автоответ: {'включён' if p['reply'] else 'выключен'}\n"
        f"Найдено авторов: {len(p.get('seen', ()))}"
    )


def parsers_list_screen(ui: dict):
    ps = parsers_of(ui)
    text = "📋 <b>Мои парсеры</b>\n\n" + ("Выберите парсер:" if ps else "Пока не настроено ни одного.")
    rows = []
    for p in ps:
        rows.append([InlineKeyboardButton(
            text=f"Парсер #{p['id']} · {p['account']}", callback_data=f"ps:open:{p['id']}",
            style="primary", icon_custom_emoji_id=E_GREEN if p.get("running") else E_RED_BULLET,
        )])
    rows.append([pbtn("Новый парсер", "ps:new", E_PLUS, "success")])
    rows.append([btn("◀️ Назад", "ps:menu")])
    return text, kb(*rows)


def parser_card_screen(p: dict):
    status = f"{pe(E_GREEN, '🟢')} Работает" if p.get("running") else f"{pe(E_RED_BULLET, '🔴')} Остановлен"
    text = f"🔎 <b>Парсер #{p['id']}</b>\n\nСтатус: {status}\n{parser_summary(p)}"
    if p.get("running"):
        toggle = pbtn("Остановить", f"ps:toggle:{p['id']}", E_RED, "danger")
    else:
        toggle = pbtn("Запустить", f"ps:toggle:{p['id']}", E_GREEN, "success")
    return text, kb(
        [toggle],
        [pbtn("Удалить", f"ps:del:{p['id']}", E_TRASH, "danger")],
        [btn("◀️ Назад", "ps:list")],
    )


def ps_chats_screen(d: dict, header: str = None):
    chats = d["chats"]
    n = len(chats)
    rows = [[InlineKeyboardButton(
        text=src, callback_data=f"ps:cdel:{i}", style="danger", icon_custom_emoji_id=E_TRASH,
    )] for i, src in enumerate(chats)]
    rows.append([
        pbtn("Добавить папку", "ps:folder", E_FOLDER, "primary"),
        pbtn("Загрузить .txt", "ps:txt", E_DOC, "primary"),
    ])
    if n:
        rows.append([pbtn("Готово", "ps:chdone", E_OK, "success")])
    rows.append([pbtn("Отмена", "ps:cancel", E_CROSS, "danger")])
    if n:
        text = f"{header or f'✅ Всего чатов: {n}'}\n\nДобавьте ещё или нажмите «Готово»:"
    else:
        text = (f"{header}\n\n" if header else "") + PS_STEP2_TEXT
    return text, kb(*rows)


def ps_ask_screen():
    return PS_ASK_TEXT, kb(
        [pbtn("Да", "ps:ar:1", E_OK, "success"), pbtn("Нет", "ps:ar:0", E_BAN, "primary")],
        [pbtn("Отмена", "ps:ar:cancel", E_CROSS, "danger")],
    )


async def ps_to_chats(target, state: FSMContext, d: dict, header: str = None):
    await state.set_state(PS.chats)
    text, markup = ps_chats_screen(d, header)
    await show(target, text, markup)


async def ps_to_keywords(target, state: FSMContext):
    await state.set_state(PS.keywords)
    await show(target, PS_STEP3_TEXT, kb([btn("◀️ Назад", "ps:chats")]))


async def ps_to_stop(target, state: FSMContext):
    await state.set_state(PS.stopwords)
    await show(target, PS_STEP4_TEXT, kb(
        [pbtn("Пропустить", "ps:skip4", E_PLAY, "primary")],
        [pbtn("Отмена", "ps:s4cancel", E_CROSS, "danger")],
    ))


async def ps_to_ask(target, state: FSMContext):
    await state.set_state(None)
    text, markup = ps_ask_screen()
    await show(target, text, markup)


# ---------- работа с Telegram ----------
async def ensure_joined(client: TelegramClient, entity, member_ids: set):
    """Чтобы получать сообщения, аккаунт должен состоять в канале/группе."""
    if isinstance(entity, Channel) and tg_utils.get_peer_id(entity) not in member_ids:
        await client(JoinChannelRequest(entity))


async def parser_boot(bot: Bot, user_id: int, pid: int):
    ui = get_user(user_id)
    p = find_parser(ui, pid)
    if p is None:
        return
    key = (user_id, pid)

    async def notify(text: str):
        try:
            await bot.send_message(user_id, text)
        except Exception as e:
            logging.error(f"parser notify failed: {e}")

    try:
        client = await get_client(ui, p["account"])
        member_ids = set()
        try:
            member_ids = {dlg.id for dlg in await client.get_dialogs()}
        except Exception as e:
            logging.warning(f"parser get_dialogs: {e}")

        ids, problems = set(), []
        for src in list(p["chats"]):
            if not p.get("running"):
                return
            try:
                entity = await resolve_target(client, src)
                await ensure_joined(client, entity, member_ids)
                ids.add(tg_utils.get_peer_id(entity))
            except tg_errors.UserAlreadyParticipantError:
                try:
                    ids.add(tg_utils.get_peer_id(await resolve_target(client, src)))
                except Exception as e:
                    problems.append(f"{src}: {e}")
            except tg_errors.FloodWaitError as e:
                problems.append(f"{src}: Telegram просит подождать {e.seconds} сек")
            except Exception as e:
                problems.append(f"{src}: {e}")
            await asyncio.sleep(1.5)

        if not p.get("running"):
            return
        if not ids:
            p["running"] = False
            lines = "\n".join(escape(x) for x in problems[:10])
            await notify(f"❌ <b>Парсер #{pid}</b> не запущен: не удалось подключиться ни к одному чату.\n<code>{lines}</code>")
            return

        async def handler(event):
            try:
                await parser_on_message(bot, user_id, pid, ids, client, event)
            except Exception:
                logging.exception("parser handler")

        client.add_event_handler(handler, events.NewMessage(incoming=True))
        PARSERS[key] = {"client": client, "handler": handler}

        text = f"✅ <b>Парсер #{pid}</b> запущен. Слушаю чатов: {len(ids)} из {len(p['chats'])}."
        if problems:
            text += "\n\n⚠️ Не удалось подключить:\n<code>" + "\n".join(escape(x) for x in problems[:10]) + "</code>"
        await notify(text)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logging.exception("parser_boot")
        p["running"] = False
        await notify(f"❌ <b>Парсер #{pid}</b> не запущен:\n<code>{escape(str(e))}</code>")
    finally:
        PARSER_TASKS.pop(key, None)


async def parser_on_message(bot: Bot, user_id: int, pid: int, ids: set, client: TelegramClient, event):
    ui = get_user(user_id)
    p = find_parser(ui, pid)
    if p is None or not p.get("running") or event.chat_id not in ids:
        return
    if not has_access(ui):
        return
    text = event.raw_text or ""
    if not text or not parser_match(text, p["keywords"], p["stop"]):
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot:
        return
    seen = p.setdefault("seen", set())
    if sender.id in seen:      # автор уже был: ни уведомления, ни автоответа повторно
        return
    seen.add(sender.id)

    name = " ".join(x for x in (sender.first_name, sender.last_name) if x) or "—"
    uname = f"@{sender.username}" if sender.username else "—"
    note = (
        "📥 <b>Сообщение от:</b>\n"
        f"👤 Имя: {escape(name)}\n"
        f"🔗 Username: {escape(uname)}\n"
        f"🆔 ID: {sender.id}\n\n"
        f"💬 {escape(text[:3000])}"
    )
    try:
        await bot.send_message(user_id, note)
    except Exception as e:
        logging.error(f"parser: не удалось отправить уведомление: {e}")

    if p.get("reply") and p.get("reply_html"):
        try:
            if AUTOREPLY_IN_DM:
                await client.send_message(sender, p["reply_html"], parse_mode="html", link_preview=False)
            else:
                await event.reply(p["reply_html"], parse_mode="html", link_preview=False)
        except tg_errors.FloodWaitError as e:
            logging.warning(f"parser autoreply FloodWait {e.seconds}s")
        except Exception as e:
            logging.warning(f"parser autoreply failed: {e}")
            try:
                await bot.send_message(user_id, f"⚠️ Автоответ для {sender.id} не отправлен:\n<code>{escape(str(e))[:300]}</code>")
            except Exception:
                pass


def start_parser(bot: Bot, user_id: int, ui: dict, p: dict):
    """Возвращает текст ошибки или None, если парсер запускается."""
    if not has_access(ui):
        return "❌ Нужна подписка или бесплатный тариф"
    if p["account"] not in ui["accounts"]:
        return "❌ Аккаунт парсера не найден — добавьте его заново"
    if p.get("running"):
        return None
    if len(active_parsers(ui)) >= PARSER_MAX_ACTIVE:
        return f"❌ Лимит: до {PARSER_MAX_ACTIVE} активных парсеров"
    if any(o is not p and o.get("running") and o["account"] == p["account"] for o in parsers_of(ui)):
        return "❌ Этот аккаунт уже занят другим парсером"
    p["running"] = True
    PARSER_TASKS[(user_id, p["id"])] = asyncio.create_task(parser_boot(bot, user_id, p["id"]))
    return None


def stop_parser(user_id: int, p: dict):
    p["running"] = False
    key = (user_id, p["id"])
    task = PARSER_TASKS.pop(key, None)
    if task and not task.done():
        task.cancel()
    info = PARSERS.pop(key, None)
    if info:
        try:
            info["client"].remove_event_handler(info["handler"])
        except Exception as e:
            logging.warning(f"remove_event_handler: {e}")


async def ps_finalize(target, state: FSMContext, ui: dict, user_id: int, bot: Bot):
    d = ui.get("parser_draft")
    await state.clear()
    if not d:
        text, markup = parser_menu_screen()
        await show(target, text, markup)
        return
    ui["parser_next_id"] = ui.get("parser_next_id", 0) + 1
    p = {
        "id": ui["parser_next_id"], "account": d["account"], "chats": list(d["chats"]),
        "keywords": list(d["keywords"]), "stop": list(d["stop"]),
        "reply": bool(d["reply"]), "reply_text": d.get("reply_text", ""), "reply_html": d.get("reply_html", ""),
        "running": False, "seen": set(),
    }
    parsers_of(ui).append(p)
    ui["parser_draft"] = None
    err = start_parser(bot, user_id, ui, p)
    if err:
        head = f"🔎 <b>Парсер #{p['id']} создан, но не запущен</b>\n{err}"
    else:
        head = f"✅ <b>Парсер #{p['id']} настроен</b>\nЗапускаю — пришлю сообщение, когда будет готово."
    await show(target, f"{head}\n\n{parser_summary(p)}", kb(
        [pbtn("Мои парсеры", "ps:list", E_DOC, "primary")],
        [btn("◀️ Назад", "ps:menu")],
    ))


# ---------- кнопки ----------
@router.callback_query(F.data.startswith("ps:"))
async def ps_cb(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    ui = get_user(user_id)
    p = call.data.split(":")
    action = p[1]
    alert = None
    d = ui.get("parser_draft")

    draft_actions = {
        "cdel", "folder", "txt", "chats", "chdone", "cancel",
        "skip4", "s4cancel", "ar", "ask",
    }
    if action in draft_actions and d is None:
        await state.clear()
        text, markup = parser_menu_screen()
        await show(call, text, markup)
        await call.answer("Настройка устарела — начните заново.", show_alert=True)
        return

    if action == "menu":
        await state.clear()
        ui["parser_draft"] = None
        text, markup = parser_menu_screen()
        await show(call, text, markup)

    elif action == "list":
        await state.clear()
        ui["parser_draft"] = None
        text, markup = parsers_list_screen(ui)
        await show(call, text, markup)

    elif action == "new":
        await state.clear()
        ui["parser_draft"] = None
        if len(active_parsers(ui)) >= PARSER_MAX_ACTIVE:
            text = f"❌ Достигнут лимит: до {PARSER_MAX_ACTIVE} активных парсеров.\nОтключите один из них в «Мои парсеры»."
            _t, markup = parser_menu_screen()
            await show(call, text, markup)
        else:
            free = free_accounts(ui)
            if not free:
                text = (
                    "❌ Нет свободного аккаунта для нового парсера.\n"
                    "Добавьте аккаунт в разделе «Аккаунты» — или отключите парсер на уже занятом."
                )
                _t, markup = parser_menu_screen()
                await show(call, text, markup)
            else:
                rows = [[pbtn(a if a.startswith("+") else "+" + a, f"ps:acc:{ui['accounts'].index(a)}", E_PHONE2, "primary")] for a in free]
                rows.append([btn("◀️ Назад", "ps:menu")])
                await show(call, "🔎 <b>Настройка парсера</b>\n\nШаг 1/4: Выберите аккаунт, который будет слушать чаты:", kb(*rows))

    elif action == "acc":
        idx = int(p[2])
        accs = ui["accounts"]
        if not (0 <= idx < len(accs)) or accs[idx] not in free_accounts(ui):
            alert = "Этот аккаунт недоступен"
        else:
            ui["parser_draft"] = {
                "account": accs[idx], "chats": [], "keywords": [], "stop": [],
                "reply": False, "reply_text": "", "reply_html": "",
            }
            await ps_to_chats(call, state, ui["parser_draft"])

    elif action == "cdel":
        i = int(p[2])
        if 0 <= i < len(d["chats"]):
            d["chats"].pop(i)
        await ps_to_chats(call, state, d, f"🗑 Чат удалён! Всего: {len(d['chats'])}" if d["chats"] else None)

    elif action == "chats":
        await ps_to_chats(call, state, d)

    elif action in ("folder", "txt"):
        await state.set_state(PS.folder if action == "folder" else PS.txt)
        await show(call, FOLDER_TEXT if action == "folder" else TXT_TEXT, kb([btn("◀️ Назад", "ps:chats")]))

    elif action == "chdone":
        if not d["chats"]:
            alert = "Добавьте хотя бы один чат"
        else:
            await ps_to_keywords(call, state)

    elif action == "cancel":
        await state.clear()
        ui["parser_draft"] = None
        text, markup = parser_menu_screen()
        await show(call, text, markup)

    elif action == "skip4":
        d["stop"] = []
        await ps_to_ask(call, state)

    elif action == "s4cancel":
        await ps_to_chats(call, state, d)

    elif action == "ask":
        await ps_to_ask(call, state)

    elif action == "ar":
        val = p[2]
        if val == "cancel":
            await ps_to_stop(call, state)
        elif val == "1":
            d["reply"] = True
            await state.set_state(PS.reply_text)
            await show(call, PS_REPLY_TEXT, kb([btn("◀️ Назад", "ps:ask")]))
        else:
            d["reply"], d["reply_text"], d["reply_html"] = False, "", ""
            await ps_finalize(call, state, ui, user_id, call.bot)

    elif action == "open":
        pr = find_parser(ui, p[2])
        if pr is None:
            alert = "Парсер не найден"
        else:
            text, markup = parser_card_screen(pr)
            await show(call, text, markup)

    elif action == "toggle":
        pr = find_parser(ui, p[2])
        if pr is None:
            alert = "Парсер не найден"
        else:
            if pr.get("running"):
                stop_parser(user_id, pr)
            else:
                alert = start_parser(call.bot, user_id, ui, pr)
            text, markup = parser_card_screen(pr)
            await show(call, text, markup)

    elif action == "del":
        pr = find_parser(ui, p[2])
        if pr is not None:
            stop_parser(user_id, pr)
            ui["parsers"] = [x for x in parsers_of(ui) if x is not pr]
            alert = "✅ Парсер удалён"
        text, markup = parsers_list_screen(ui)
        await show(call, text, markup)

    await call.answer(alert, show_alert=bool(alert))


# ---------- ввод пользователя ----------
def _ps_chat_header(added: int, bad: int, n: int, limit_hit: bool) -> str:
    if added == 0:
        head = f"ℹ️ Этот чат уже добавлен. Всего: {n}"
    elif added == 1:
        head = f"✅ Чат добавлен! Всего: {n}"
    else:
        head = f"✅ Добавлено чатов: {added}! Всего: {n}"
    if limit_hit:
        head += f"\n⚠️ Лимит — {PARSER_MAX_CHATS} чатов на аккаунт."
    return head


@router.message(PS.chats)
async def ps_on_chat(message: Message, state: FSMContext):
    ui = get_user(message.from_user.id)
    d = ui.get("parser_draft")
    if d is None:
        await state.clear()
        text, markup = parser_menu_screen()
        await show(message, text, markup)
        return
    tokens = [t for t in re.split(r"[\s,;]+", (message.text or "").strip()) if t]
    if not tokens:
        await message.answer("❌ Отправьте чат текстом: @username, ID или ссылку.")
        return
    added, bad, limit_hit = 0, 0, False
    for token in tokens:
        norm = parse_chat(token)
        if norm is None:
            bad += 1
        elif any(x.lower() == norm.lower() for x in d["chats"]):
            continue
        elif len(d["chats"]) >= PARSER_MAX_CHATS:
            limit_hit = True
            break
        else:
            d["chats"].append(norm)
            added += 1
    if added == 0 and bad and not limit_hit:
        await message.answer("❌ Не удалось распознать чат. Отправьте @username, ID или ссылку:")
        return
    await ps_to_chats(message, state, d, _ps_chat_header(added, bad, len(d["chats"]), limit_hit))


@router.message(PS.folder)
async def ps_on_folder(message: Message, state: FSMContext):
    ui = get_user(message.from_user.id)
    d = ui.get("parser_draft")
    if d is None:
        await state.clear()
        return
    links = re.findall(r"https?://t\.me/addlist/[A-Za-z0-9_-]+", message.text or "")[:20]
    if not links:
        await message.answer("❌ Не нашёл ссылок на папки. Пример: https://t.me/addlist/xxxxx")
        return
    try:
        client = await get_client(ui, d["account"])
    except Exception as e:
        await message.answer(f"❌ Не удалось подключить аккаунт: <code>{escape(str(e))}</code>")
        return
    added, errors, limit_hit = 0, [], False
    for link in links:
        try:
            for src in await resolve_folder_chats(link, client):
                if any(x.lower() == src.lower() for x in d["chats"]):
                    continue
                if len(d["chats"]) >= PARSER_MAX_CHATS:
                    limit_hit = True
                    break
                d["chats"].append(src)
                added += 1
        except Exception as e:
            errors.append(f"{link}: {e}")
    head = f"✅ Из папки добавлено чатов: {added}! Всего: {len(d['chats'])}"
    if limit_hit:
        head += f"\n⚠️ Лимит — {PARSER_MAX_CHATS} чатов на аккаунт."
    if errors:
        head += "\n⚠️ Не удалось прочитать: " + escape("; ".join(errors)[:300])
    await ps_to_chats(message, state, d, head)


@router.message(PS.txt)
async def ps_on_txt(message: Message, state: FSMContext):
    ui = get_user(message.from_user.id)
    d = ui.get("parser_draft")
    if d is None:
        await state.clear()
        return
    if not message.document:
        await message.answer("❌ Отправьте файл в формате .txt")
        return
    if message.document.file_size and message.document.file_size > 1_000_000:
        await message.answer("❌ Файл слишком большой (максимум 1 МБ).")
        return
    buf = BytesIO()
    await message.bot.download(message.document, destination=buf)
    content = buf.getvalue().decode("utf-8", errors="ignore")
    added, limit_hit = 0, False
    for token in re.split(r"[\s,;]+", content):
        norm = parse_chat(token) if token else None
        if not norm or any(x.lower() == norm.lower() for x in d["chats"]):
            continue
        if len(d["chats"]) >= PARSER_MAX_CHATS:
            limit_hit = True
            break
        d["chats"].append(norm)
        added += 1
    head = f"✅ Добавлено {added} чатов из файла! Всего: {len(d['chats'])}"
    if limit_hit:
        head += f"\n⚠️ Лимит — {PARSER_MAX_CHATS} чатов на аккаунт."
    await ps_to_chats(message, state, d, head)


@router.message(PS.keywords)
async def ps_on_keywords(message: Message, state: FSMContext):
    ui = get_user(message.from_user.id)
    d = ui.get("parser_draft")
    if d is None:
        await state.clear()
        return
    words = parse_words(message.text)
    if not words:
        await message.answer("❌ Введите хотя бы одно ключевое слово (через запятую):")
        return
    d["keywords"] = words
    await ps_to_stop(message, state)


@router.message(PS.stopwords)
async def ps_on_stopwords(message: Message, state: FSMContext):
    ui = get_user(message.from_user.id)
    d = ui.get("parser_draft")
    if d is None:
        await state.clear()
        return
    words = parse_words(message.text)
    if not words:
        await message.answer("❌ Введите стоп-слова через запятую или нажмите «Пропустить».")
        return
    d["stop"] = words
    await ps_to_ask(message, state)


@router.message(PS.reply_text)
async def ps_on_reply_text(message: Message, state: FSMContext):
    ui = get_user(message.from_user.id)
    d = ui.get("parser_draft")
    if d is None:
        await state.clear()
        return
    if not message.text or len(message.text) > 4000:
        await message.answer("❌ Отправьте текст автоответа (до 4000 символов):")
        return
    d["reply_text"] = message.text
    d["reply_html"] = message.html_text
    await ps_finalize(message, state, ui, message.from_user.id, message.bot)


# ============================================================
# 🔥 ПРОГРЕВ АККАУНТОВ
# ============================================================
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

WARMUP_DAYS = 10
WARM_HOURS = (9, 23)   # активность только в это время (по TIMEZONE_NAME)

# каналы для подписок — добавляй сюда новые (например, из @Fe_ADS_Robot / @pr_gramapp)
WARMUP_CHANNELS = """
@DeveloperLead @pervsport @woman_science @tricolor_sport @prokoni_ru @rbsportmma
@sport_comiteti @fitmost @sportfts @science_nos @naukapublishersru @vodkaandmeldonium
@bombardiralmet @sportsuspilne @fsskbr07 @lysenkovtv2 @sciencebaikal @krasota_sports
@bogomolbets @nauka_gpntb_so_ran @csnkov @kinash_sport @nizhnysport @nenavizhubeg
@festivalnaukiru @drsqazaqstan @gospub_sport @scienceinward @kunshtmagazine @nauka_factov
@alexb_books @psbsport @redakciya_nauka @saigon_sport @roditelmgu @science_lib
@sportlandmsk @rehab_mikhail @kapper_kaz @mmadream @naukapobezhdat @sportvrach
@mangazeya_sport @LaLiga_Lg @sportexpress @sportai @tsutmb @rhana_online
@mypervie_nauka @science4cats @cliff_legal @asasfond @vzletolympmo @sport_yakutia @bogachevsport
""".split()

# чаты/группы для вступления
WARMUP_CHATS = [x for x in (parse_chat(u) for u in """
https://t.me/crypto_exchangea https://t.me/usdtcryptoeuro https://t.me/gorbushka_group
https://t.me/gorbushka_opt https://t.me/kznchat16 https://t.me/obmen_armeniya
""".split()) if x]

# план по дням: (мин, макс) действий за день
WARMUP_PLAN = {
    1:  dict(subs=(10, 15), reacts=(10, 20), joins=(0, 0), comments=(0, 0)),
    2:  dict(subs=(10, 15), reacts=(20, 30), joins=(3, 5), comments=(0, 0)),
    3:  dict(subs=(0, 0),   reacts=(20, 30), joins=(5, 5), comments=(2, 3)),
    4:  dict(subs=(10, 10), reacts=(30, 30), joins=(0, 0), comments=(3, 5)),
    5:  dict(subs=(10, 10), reacts=(30, 50), joins=(0, 0), comments=(5, 5)),
    6:  dict(subs=(10, 10), reacts=(30, 50), joins=(0, 0), comments=(5, 10)),
    7:  dict(subs=(10, 10), reacts=(30, 50), joins=(0, 0), comments=(5, 10)),
    8:  dict(subs=(20, 30), reacts=(30, 50), joins=(0, 0), comments=(10, 10)),
    9:  dict(subs=(20, 30), reacts=(30, 50), joins=(0, 0), comments=(10, 10)),
    10: dict(subs=(20, 30), reacts=(30, 50), joins=(0, 0), comments=(10, 10)),
}

WARM_REACTIONS = ["👍", "🔥", "❤", "👏"]
WARM_PHRASES = [
    "Интересно", "Согласен", "Спасибо за информацию", "Полезно", "👍",
    "Хорошая тема", "Понятно, спасибо", "Актуально", "Любопытно", "Точно подмечено",
]

WARM_TASKS = {}   # (user_id, phone) -> asyncio.Task


def warm_of(ui: dict, phone: str) -> dict:
    return ui.setdefault("warmup", {}).setdefault(phone, {
        "running": False, "done": False, "day": 1, "day_date": None,
        "subs": 0, "joins": 0, "reactions": 0, "comments": 0,
        "last": "- (-)", "tried": [], "ok_channels": [], "ok_chats": [],
        "quota": None,
    })


def warm_reset(w: dict):
    w.update({
        "running": False, "done": False, "day": 1, "day_date": None,
        "subs": 0, "joins": 0, "reactions": 0, "comments": 0,
        "last": "- (-)", "tried": [], "ok_channels": [], "ok_chats": [], "quota": None,
    })


def warmup_menu_screen():
    text = (
        "🔥 <b>Прогрев аккаунтов</b>\n\n"
        "Имитирует живую активность на аккаунте: подписки на каналы, чтение ленты, реакции, "
        "смена онлайн/оффлайн статуса и т.д. — чтобы аккаунт выглядел органично.\n\n"
        "Работает независимо от рассылки и парсера — можно держать прогрев включённым на аккаунте, "
        "который параллельно рассылает или парсит, они друг другу не мешают.\n\n"
        "<b>Этапы:</b>\n"
        "1️⃣ Первый день — тихий старт. Если аккаунт в боте уже больше суток, этот этап пропускается\n"
        "2️⃣ Активный прогрев — переписки с другими аккаунтами, групповые чаты, голосовые, звонки, "
        "истории, реакции и подписки на каналы"
    )
    return text, kb(
        [InlineKeyboardButton(text="📱 Мои аккаунты", callback_data="wu:list", style="primary")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tools")],
    )


def warmup_list_screen(ui: dict):
    text = "📋 <b>Прогрев по аккаунтам</b>\n\n🟢 — прогрев включён, ⚫️ — выключен"
    rows = []
    for i, phone in enumerate(ui["accounts"]):
        if warm_of(ui, phone)["running"]:
            rows.append([InlineKeyboardButton(
                text=fmt_phone(phone), callback_data=f"wu:open:{i}",
                style="primary", icon_custom_emoji_id=E_GREEN)])
        else:
            rows.append([InlineKeyboardButton(
                text="вљ«пёЏ " + fmt_phone(phone), callback_data=f"wu:open:{i}", style="primary")])
    if not ui["accounts"]:
        text += "\n\nУ вас нет добавленных аккаунтов."
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="wu:menu")])
    return text, kb(*rows)


def warmup_card_screen(ui: dict, idx: int):
    phone = ui["accounts"][idx]
    w = warm_of(ui, phone)
    head = f"🔥 <b>Прогрев: {escape(fmt_phone(phone))}</b>\n\n"
    if w["running"]:
        stage = "1 — первичный" if w["day"] == 1 else "2 — активный"
        text = head + (
            "Статус: 🟢 включён\n"
            f"Этап: {stage}\n"
            f"День прогрева: {w['day']}\n"
            f"Подписок на каналы: {w['subs']}\n"
            f"Вступлений в чаты: {w['joins']}\n"
            f"Реакций: {w['reactions']}\n"
            f"Комментариев: {w['comments']}\n"
            f"Последнее действие: {escape(w['last'])}"
        )
        first = InlineKeyboardButton(text="⏸️ Остановить прогрев", callback_data=f"wu:stop:{idx}", style="primary")
    else:
        text = head + "Статус: ⚫️ выключен"
        first = InlineKeyboardButton(text="Начать прогрев", callback_data=f"wu:start:{idx}", style="primary")
    return text, kb([first], [InlineKeyboardButton(text="◀️ Назад", callback_data="wu:list")])


def _roll(rng) -> int:
    return random.randint(rng[0], rng[1])


def warm_update_day(w: dict):
    """Переход на новый день и пересчёт дневных квот."""
    today = now_local().date().isoformat()
    if w["day_date"] is None:
        w["day_date"] = today
    elif w["day_date"] != today:
        w["day"] += 1
        w["day_date"] = today
        w["quota"] = None
    if w["quota"] is None and w["day"] <= WARMUP_DAYS:
        plan = WARMUP_PLAN[w["day"]]
        need = {k: _roll(v) for k, v in plan.items()}
        w["quota"] = {"need": need, "done": {k: 0 for k in need}}


async def warm_set_online(client, online: bool):
    try:
        await client(UpdateStatusRequest(offline=not online))
    except Exception:
        pass


async def warm_action(client, w: dict, kind: str):
    """Одно действие. Возвращает текст действия, 'empty' (источники кончились) или None (пока нечего делать)."""
    if kind in ("subs", "joins"):
        pool_src = WARMUP_CHANNELS if kind == "subs" else WARMUP_CHATS
        pool = [c for c in pool_src if c not in w["tried"]]
        if not pool:
            return "empty"
        src = random.choice(pool)
        w["tried"].append(src)
        try:
            ent = await resolve_target(client, src)
            try:
                await client(JoinChannelRequest(ent))
            except tg_errors.UserAlreadyParticipantError:
                pass
        except tg_errors.FloodWaitError:
            raise
        except Exception as e:
            logging.warning(f"warmup join {src}: {e}")
            return None
        if kind == "subs":
            w["ok_channels"].append(src)
            w["subs"] += 1
            return f"подписка {src}"
        w["ok_chats"].append(src)
        w["joins"] += 1
        return f"вступление {src}"

    if kind == "reacts":
        srcs = w["ok_channels"] + w["ok_chats"]
        if not srcs:
            return None
        src = random.choice(srcs)
        ent = await resolve_target(client, src)
        msgs = await client.get_messages(ent, limit=15)
        if not msgs:
            return None
        try:
            await client.send_read_acknowledge(ent, max_id=msgs[0].id)   # «читаем ленту»
        except Exception:
            pass
        m = random.choice(msgs)
        await client(SendReactionRequest(
            peer=ent, msg_id=m.id, reaction=[ReactionEmoji(emoticon=random.choice(WARM_REACTIONS))]))
        w["reactions"] += 1
        return f"реакция в {src}"

    if kind == "comments":
        if not w["ok_chats"]:
            return None
        src = random.choice(w["ok_chats"])
        ent = await resolve_target(client, src)
        msgs = [m for m in await client.get_messages(ent, limit=30) if m.text and not m.out]
        if not msgs:
            return None
        await client.send_message(ent, random.choice(WARM_PHRASES), reply_to=random.choice(msgs).id)
        w["comments"] += 1
        return f"комментарий в {src}"
    return None


async def warmup_runner(bot: Bot, user_id: int, phone: str):
    ui = get_user(user_id)
    w = warm_of(ui, phone)

    async def notify(text: str):
        try:
            await bot.send_message(user_id, text)
        except Exception as e:
            logging.error(f"warmup notify: {e}")

    errors_in_row = 0
    try:
        client = await get_client(ui, phone)
        while w["running"]:
            if not has_access(ui):
                await handle_access_lost(bot, user_id, ui)
                break

            warm_update_day(w)
            if w["day"] > WARMUP_DAYS:
                w["running"], w["done"] = False, True
                await notify(f"✅ Прогрев {fmt_phone(phone)} завершён ({WARMUP_DAYS} дней).")
                break

            hour = now_local().hour
            if not (WARM_HOURS[0] <= hour < WARM_HOURS[1]):
                await warm_set_online(client, False)
                await asyncio.sleep(600)
                continue

            q = w["quota"]
            todo = [k for k in q["need"] if q["done"][k] < q["need"][k]]
            if not todo:
                await warm_set_online(client, False)
                await asyncio.sleep(900)     # дневная норма выполнена — ждём следующий день
                continue

            kind = random.choice(todo)
            try:
                await warm_set_online(client, True)
                res = await warm_action(client, w, kind)
                errors_in_row = 0
                if res == "empty":
                    q["done"][kind] = q["need"][kind]          # источники кончились
                elif res:
                    q["done"][kind] += 1
                    w["last"] = f"{res} ({now_local().strftime('%H:%M')})"
            except tg_errors.FloodWaitError as e:
                await asyncio.sleep(e.seconds + 5)
                continue
            except Exception as e:
                errors_in_row += 1
                logging.warning(f"warmup {phone} {kind}: {e}")
                if errors_in_row >= 8:
                    w["running"] = False
                    await notify(f"❌ Прогрев {fmt_phone(phone)} остановлен из-за ошибок:\n{str(e)[:300]}")
                    break

            if random.random() < 0.4:
                await warm_set_online(client, False)
            lo, hi = (90, 300) if kind in ("subs", "joins") else (30, 150)
            await asyncio.sleep(random.uniform(lo, hi))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logging.exception("warmup_runner")
        w["running"] = False
        await notify(f"❌ Прогрев {fmt_phone(phone)} не запущен:\n{str(e)[:300]}")
    finally:
        if WARM_TASKS.get((user_id, phone)) is asyncio.current_task():
            WARM_TASKS.pop((user_id, phone), None)


def start_warmup(bot: Bot, user_id: int, ui: dict, phone: str):
    if not has_access(ui):
        return "❌ Нужна подписка или бесплатный тариф"
    w = warm_of(ui, phone)
    if w["running"]:
        return None
    if w["done"]:
        warm_reset(w)
    if w["day_date"]:                        # возобновление: тот же день, без скачка дней
        w["day_date"] = now_local().date().isoformat()
    w["running"] = True
    WARM_TASKS[(user_id, phone)] = asyncio.create_task(warmup_runner(bot, user_id, phone))
    return None


def stop_warmup(user_id: int, ui: dict, phone: str):
    w = warm_of(ui, phone)
    w["running"] = False
    task = WARM_TASKS.pop((user_id, phone), None)
    if task and not task.done():
        task.cancel()


@router.callback_query(F.data.startswith("wu:"))
async def warmup_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    ui = get_user(user_id)
    p = call.data.split(":")
    action = p[1]
    alert = None

    if action == "menu":
        text, markup = warmup_menu_screen()
        await show(call, text, markup)
    elif action == "list":
        text, markup = warmup_list_screen(ui)
        await show(call, text, markup)
    elif action in ("open", "start", "stop"):
        idx = int(p[2])
        if not (0 <= idx < len(ui["accounts"])):
            alert = "Аккаунт не найден"
            text, markup = warmup_list_screen(ui)
        else:
            phone = ui["accounts"][idx]
            if action == "start":
                alert = start_warmup(call.bot, user_id, ui, phone)
            elif action == "stop":
                stop_warmup(user_id, ui, phone)
            text, markup = warmup_card_screen(ui, idx)
        await show(call, text, markup)
    await call.answer(alert, show_alert=bool(alert))


async def resume_running(bot: Bot) -> None:
    """После перезапуска/деплоя поднимает всё, что работало до остановки."""
    n_c = n_p = n_w = 0
    for uid, ui in list(user_data_db.items()):
        if ui.get("banned"):
            for c in ui.get("campaigns", []):
                c["running"] = False
            continue
        for c in ui.get("campaigns", []):
            if c.get("running"):
                err = start_campaign(bot, uid, ui, c)
                if err:
                    c["running"] = False
                    logging.warning("Рассылка %s/%s не возобновлена: %s", uid, c.get("id"), err)
                else:
                    n_c += 1
        for p in parsers_of(ui):
            if p.get("running"):
                p["running"] = False          # start_parser игнорирует уже «запущенный» парсер
                if start_parser(bot, uid, ui, p) is None:
                    n_p += 1
        for phone, w in list(ui.get("warmup", {}).items()):
            if w.get("running"):
                w["running"] = False
                if start_warmup(bot, uid, ui, phone) is None:
                    n_w += 1
    print(f"▶️ Возобновлено: рассылок {n_c}, парсеров {n_p}, прогревов {n_w}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # --- диагностика: цветные кнопки требуют aiogram >= 3.25 (Bot API 9.4) ---
    try:
        from importlib.metadata import version as _pkg_version
        _v = _pkg_version("aiogram")
        _parts = tuple(int(x) for x in re.findall(r"\d+", _v)[:2])
        print(f"в„№пёЏ aiogram {_v}")
        if _parts < (3, 25):
            print("⚠️ aiogram СТАРЫЙ: цветные кнопки и иконки не заработают. "
                  "Выполни: pip install -U aiogram")
    except Exception as _e:
        print(f"⚠️ Не удалось определить версию aiogram: {_e}")

    if not BOT_TOKEN or not API_ID or not API_HASH:
        raise RuntimeError(
            "Не заданы BOT_TOKEN, API_ID или API_HASH. "
            "Установите их в переменных окружения перед запуском."
        )

    session = AiohttpSession(proxy=PROXY) if PROXY else AiohttpSession()

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    bot.session.middleware(PremiumUIMiddleware())
    global BOT_USERNAME
    try:
        BOT_USERNAME = (await bot.me()).username or ""
    except Exception as e:
        print(f"⚠️ Не удалось получить username бота: {e}")

    # проверяем ID премиум-эмодзи: невалидные будут убираться по одному,
    # а остальные останутся премиум
    await validate_premium_ids(bot)

    if REDIS_URL:
        from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder
        storage = RedisStorage(get_redis(), key_builder=DefaultKeyBuilder(prefix=f"{REDIS_PREFIX}fsm"))
        await get_redis().ping()
        print("💾 Redis подключён: данные переживут перезапуск")
    else:
        storage = MemoryStorage()
        print("⚠️ REDIS_URL не задан: данные в памяти, при перезапуске часть состояния будет потеряна!")
    dp = Dispatcher(storage=storage)

    await restore_files_from_redis()      # .session и bot.db — обратно на диск
    init_payments_db()
    loaded = await load_all_users()       # пользователи — обратно в память
    if loaded:
        print(f"💾 Пользователей загружено из Redis: {loaded}")
    load_saved_subs()
    resume_pending_invoices(bot)

    asyncio.create_task(subscription_reminder_loop(bot))
    if REDIS_URL:
        spawn(persist_loop())
        spawn(session_backup_loop())
    await resume_running(bot)             # рассылки/парсеры/прогрев, что шли до остановки

    dp.include_router(pay_router)   # раньше основного router: платежи не перехватят хендлеры состояний
    dp.include_router(router)
    dp.message.outer_middleware(BanMiddleware())
    dp.callback_query.outer_middleware(BanMiddleware())
    dp.message.outer_middleware(PersistMiddleware())
    dp.callback_query.outer_middleware(PersistMiddleware())

    print("✅ Бот запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await flush_all()                 # штатная остановка/деплой: сохраняем всё
        if _http is not None and not _http.closed:
            await _http.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("⛔ Бот остановлен")
