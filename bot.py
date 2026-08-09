import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime, timedelta
import threading
import time
import logging
import os
import sys
import random
import json
from contextlib import contextmanager
import gspread
from oauth2client.service_account import ServiceAccountCredentials

TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("❌ TOKEN не задан!")

MODERATOR_IDS = os.getenv('MODERATOR_IDS', '8746212340')
MODERATOR_IDS = [int(x.strip()) for x in MODERATOR_IDS.split(',')]

SBP_PHONE = os.getenv('SBP_PHONE', '+7XXXXXXXXXX')
COMMISSION_PER_HOUR = int(os.getenv('COMMISSION_PER_HOUR', '50'))
PRICE_PER_HOUR = int(os.getenv('PRICE_PER_HOUR', '500'))
BOT_NAME = os.getenv('BOT_NAME', 'Юрга-Подработка')

bot = telebot.TeleBot(TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ===================== БАЗА ДАННЫХ =====================
class Database:
    _instance = None
    _lock = threading.Lock()
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_db()
        return cls._instance
    def _init_db(self):
        try:
            self.conn = sqlite3.connect('rabota.db', check_same_thread=False, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
            c = self.conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                name TEXT,
                phone TEXT,
                bank TEXT,
                initials TEXT,
                role TEXT,
                rating INTEGER DEFAULT 10,
                customer_rating INTEGER DEFAULT 10,
                on_shift INTEGER DEFAULT 1,
                agreement_accepted INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                notify INTEGER DEFAULT 1
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zakazchik_id INTEGER,
                zakazchik_name TEXT,
                address TEXT,
                work_description TEXT,
                hours INTEGER,
                people INTEGER,
                total_sum INTEGER,
                commission INTEGER,
                payout_per_person INTEGER,
                status TEXT DEFAULT 'open',
                photo_file_id TEXT,
                created_at TEXT,
                paid_at TEXT,
                completed_at TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                user_id INTEGER,
                payout INTEGER,
                confirmed INTEGER DEFAULT 0,
                confirmed_at TEXT,
                photo_file_id TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                order_id INTEGER,
                text TEXT,
                created_at TEXT,
                read INTEGER DEFAULT 0
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS temp_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                state TEXT,
                data TEXT,
                created_at TEXT,
                expires_at TEXT
            )''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_notify ON users(notify)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_zakazchik_id ON orders(zakazchik_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_assignments_order_id ON assignments(order_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_to_user_id ON messages(to_user_id)")
            self.conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            raise
    @contextmanager
    def transaction(self):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                cursor = self.conn.cursor()
                yield cursor
                self.conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(random.uniform(0.3, 0.8))
                    continue
                self.conn.rollback()
                raise
            except Exception as e:
                self.conn.rollback()
                raise

db = Database()

# ===================== БЕЗОПАСНАЯ ОТПРАВКА =====================
def safe_send(chat_id, text, **kwargs):
    if not chat_id:
        return None
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки {chat_id}: {e}")
        return None

def safe_edit(text, chat_id, msg_id, **kwargs):
    try:
        return bot.edit_message_text(text, chat_id, msg_id, **kwargs)
    except Exception as e:
        logger.error(f"❌ Ошибка редактирования: {e}")
        return None

def safe_send_photo(chat_id, photo, caption=None, **kwargs):
    try:
        return bot.send_photo(chat_id, photo, caption=caption, **kwargs)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки фото {chat_id}: {e}")
        return None

# ===================== ФУНКЦИИ БД =====================
def get_user(telegram_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = c.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ Ошибка get_user: {e}")
        return None

def get_user_by_id(user_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = c.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ Ошибка get_user_by_id: {e}")
        return None

def update_user(telegram_id, field, value):
    try:
        with db.transaction() as c:
            c.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка update_user: {e}")
        return False

def get_order(order_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            row = c.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ Ошибка get_order: {e}")
        return None

def get_assignments(order_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT user_id, confirmed FROM assignments WHERE order_id = ?", (order_id,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_assignments: {e}")
        return []

def get_workers():
    try:
        with db.transaction() as c:
            c.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND blocked = 0 AND agreement_accepted = 1 AND notify = 1")
            return [row['telegram_id'] for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_workers: {e}")
        return []

def get_workers_for_order(order_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT user_id FROM assignments WHERE order_id = ?", (order_id,))
            return [row['user_id'] for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_workers_for_order: {e}")
        return []

def get_assignments_with_photo(order_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT user_id FROM assignments WHERE order_id = ? AND photo_file_id IS NOT NULL", (order_id,))
            return [row['user_id'] for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_assignments_with_photo: {e}")
        return []

def get_worker_orders(user_id):
    try:
        with db.transaction() as c:
            c.execute('''SELECT o.id, o.status, a.payout, o.zakazchik_name, o.address, o.work_description, a.confirmed
                     FROM assignments a JOIN orders o ON a.order_id = o.id 
                     WHERE a.user_id = ? ORDER BY o.created_at DESC LIMIT 100''', (user_id,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_worker_orders: {e}")
        return []

def get_customer_orders(zakazchik_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT id, total_sum, status, created_at, address, work_description FROM orders WHERE zakazchik_id = ? ORDER BY created_at DESC LIMIT 100", (zakazchik_id,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_customer_orders: {e}")
        return []

def update_order_status(order_id, status):
    try:
        with db.transaction() as c:
            c.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка update_order_status: {e}")
        return False

def confirm_worker_on_place(order_id, user_id):
    try:
        with db.transaction() as c:
            c.execute("UPDATE assignments SET confirmed = 1, confirmed_at = ? WHERE order_id = ? AND user_id = ?", 
                     (datetime.now().isoformat(), order_id, user_id))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка confirm_worker_on_place: {e}")
        return False

def set_worker_photo(order_id, user_id, photo_file_id):
    try:
        with db.transaction() as c:
            c.execute("UPDATE assignments SET photo_file_id = ? WHERE order_id = ? AND user_id = ?", 
                     (photo_file_id, order_id, user_id))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка set_worker_photo: {e}")
        return False

def add_rating(user_id, delta):
    try:
        with db.transaction() as c:
            c.execute("UPDATE users SET rating = rating + ? WHERE id = ?", (delta, user_id))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка add_rating: {e}")
        return False

def rate_customer(customer_id, delta):
    try:
        with db.transaction() as c:
            c.execute("UPDATE users SET customer_rating = customer_rating + ? WHERE id = ?", (delta, customer_id))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка rate_customer: {e}")
        return False

def save_message(from_user_id, to_user_id, order_id, text):
    try:
        with db.transaction() as c:
            c.execute("INSERT INTO messages (from_user_id, to_user_id, order_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
                     (from_user_id, to_user_id, order_id, text, datetime.now().isoformat()))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка save_message: {e}")
        return False

def get_unread_messages(user_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT id, from_user_id, order_id, text, created_at FROM messages WHERE to_user_id = ? AND read = 0 ORDER BY created_at DESC LIMIT 50", (user_id,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_unread_messages: {e}")
        return []

def mark_messages_read(user_id):
    try:
        with db.transaction() as c:
            c.execute("UPDATE messages SET read = 1 WHERE to_user_id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка mark_messages_read: {e}")
        return False

def get_all_workers(limit=50):
    try:
        with db.transaction() as c:
            c.execute("SELECT id, name, phone, rating, blocked, on_shift, notify FROM users WHERE role = 'rabotnik' ORDER BY rating DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_all_workers: {e}")
        return []

def get_all_customers(limit=50):
    try:
        with db.transaction() as c:
            c.execute("SELECT id, name, phone, customer_rating, blocked FROM users WHERE role = 'zakazchik' ORDER BY customer_rating DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_all_customers: {e}")
        return []

def get_active_orders(limit=50):
    try:
        with db.transaction() as c:
            c.execute("SELECT * FROM orders WHERE status NOT IN ('completed', 'cancelled') ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_active_orders: {e}")
        return []

def save_state(user_id, state, data=None, ttl_minutes=30):
    try:
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
        with db.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO temp_states (user_id, state, data, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, state, data or '{}', created_at, expires_at)
            )
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка save_state: {e}")
        return False

def get_state(user_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT state, data FROM temp_states WHERE user_id = ? AND expires_at > datetime('now')", (user_id,))
            row = c.fetchone()
            return (row['state'], row['data']) if row else (None, None)
    except Exception as e:
        logger.error(f"❌ Ошибка get_state: {e}")
        return None, None

def clear_state(user_id):
    try:
        with db.transaction() as c:
            c.execute("DELETE FROM temp_states WHERE user_id = ?", (user_id,))
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка clear_state: {e}")
        return False

# ===================== GOOGLE SHEETS =====================
def get_google_sheet():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not creds_json:
            logger.error("❌ GOOGLE_CREDENTIALS не заданы")
            return None
        try:
            creds_dict = json.loads(creds_json)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга GOOGLE_CREDENTIALS: {e}")
            return None
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet_id = os.getenv('SPREADSHEET_ID')
        if not sheet_id:
            logger.error("❌ SPREADSHEET_ID не задан")
            return None
        return client.open_by_key(sheet_id)
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        return None

def write_order_to_sheet(order_data):
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        worksheet = sheet.worksheet('Заказы')
        row = [
            order_data.get('id', ''),
            order_data.get('created_at', ''),
            order_data.get('zakazchik_name', ''),
            order_data.get('phone', ''),
            order_data.get('address', ''),
            order_data.get('work_description', ''),
            order_data.get('hours', ''),
            order_data.get('people', ''),
            order_data.get('total_sum', ''),
            order_data.get('commission', ''),
            order_data.get('payout_per_person', ''),
            order_data.get('status', 'Open'),
            order_data.get('paid_at', ''),
            order_data.get('completed_at', '')
        ]
        worksheet.append_row(row)
        logger.info(f"✅ Заказ #{order_data.get('id')} записан в Google Sheets")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка записи заказа в Google Sheets: {e}")
        return False

def write_user_to_sheet(user_data):
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        worksheet = sheet.worksheet('Пользователи')
        row = [
            user_data.get('telegram_id', ''),
            user_data.get('name', ''),
            user_data.get('phone', ''),
            user_data.get('role', ''),
            user_data.get('registered_at', '')
        ]
        worksheet.append_row(row)
        logger.info(f"✅ Пользователь {user_data.get('telegram_id')} записан в Google Sheets")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка записи пользователя в Google Sheets: {e}")
        return False

def write_payout_to_sheet(payout_data):
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        worksheet = sheet.worksheet('Выплаты')
        row = [
            payout_data.get('date', ''),
            payout_data.get('order_id', ''),
            payout_data.get('customer_name', ''),
            payout_data.get('address', ''),
            payout_data.get('worker_name', ''),
            payout_data.get('amount', ''),
            payout_data.get('moderator_name', '')
        ]
        worksheet.append_row(row)
        logger.info(f"✅ Выплата по заказу #{payout_data.get('order_id')} записана в Google Sheets")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка записи выплаты в Google Sheets: {e}")
        return False

def write_commission_to_sheet(commission_data):
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        worksheet = sheet.worksheet('Комиссия')
        row = [
            commission_data.get('date', ''),
            commission_data.get('order_id', ''),
            commission_data.get('amount', '')
        ]
        worksheet.append_row(row)
        logger.info(f"✅ Комиссия по заказу #{commission_data.get('order_id')} записана в Google Sheets")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка записи комиссии в Google Sheets: {e}")
        return False

def update_order_status_in_sheet(order_id, status, paid_at=None, completed_at=None):
    try:
        sheet = get_google_sheet()
        if not sheet:
            return False
        worksheet = sheet.worksheet('Заказы')
        try:
            cell = worksheet.find(str(order_id))
        except gspread.exceptions.CellNotFound:
            logger.warning(f"⚠️ Заказ #{order_id} не найден в Google Sheets")
            return False
        row_num = cell.row
        worksheet.update_cell(row_num, 12, status)
        if paid_at:
            worksheet.update_cell(row_num, 13, paid_at)
        if completed_at:
            worksheet.update_cell(row_num, 14, completed_at)
        logger.info(f"✅ Статус заказа #{order_id} обновлён в Google Sheets")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса заказа в Google Sheets: {e}")
        return False

# ===================== КЛАВИАТУРЫ =====================
def get_main_kb(telegram_id=None):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    if telegram_id and telegram_id in MODERATOR_IDS:
        kb.row(KeyboardButton("🛡️ Я модератор"))
    return kb

def get_worker_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
    kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("📋 Мои заказы"))
    kb.row(KeyboardButton("👤 Профиль"), KeyboardButton("🔄 Сменить смену"))
    kb.row(KeyboardButton("🔔 Уведомления"), KeyboardButton("📞 Связаться с модератором"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def get_customer_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📝 Создать заказ"))
    kb.row(KeyboardButton("📋 Мои заказы"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("📞 Связаться с модератором"), KeyboardButton("⚠️ Пожаловаться"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def get_moderator_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    kb.row(KeyboardButton("🏢 Заказчики"), KeyboardButton("📊 Статистика"))
    kb.row(KeyboardButton("⭐ Оценить работника"), KeyboardButton("⭐ Оценить заказчика"))
    kb.row(KeyboardButton("🔒 Блокировка"), KeyboardButton("🔓 Разблокировка"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def get_blocked_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📞 Связь с модератором"))
    return kb

def order_inline_kb(order_id, is_customer=False):
    kb = InlineKeyboardMarkup()
    if is_customer:
        kb.add(InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{order_id}"))
        kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{order_id}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{order_id}"))
        kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{order_id}"))
    return kb

def confirm_take_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📍 Я на месте", callback_data=f"confirm_place_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отказаться", callback_data=f"cancel_take_{order_id}"))
    return kb

def payment_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Я оплатил", callback_data=f"i_paid_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{order_id}"))
    return kb

def worker_photo_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📸 Отправить фото", callback_data=f"send_photo_{order_id}"))
    return kb

def approve_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Работа выполнена", callback_data=f"approve_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}"))
    return kb

def moderator_payment_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"confirm_payment_{order_id}"))
    return kb

def moderator_payout_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Выплатил работникам", callback_data=f"confirm_payout_{order_id}"))
    return kb

# ===================== ОБРАБОТЧИКИ КОМАНД =====================
@bot.message_handler(commands=['start'])
def start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            with db.transaction() as c:
                c.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (uid,))
            safe_send(message.chat.id, f"👋 Добро пожаловать в бот {BOT_NAME}!\n\nВыберите свою роль:", reply_markup=get_main_kb(uid))
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Ваш аккаунт заблокирован.", reply_markup=get_blocked_kb())
            return
        role = user['role']
        if role == 'rabotnik':
            status = "на смене 🟢" if user['on_shift'] else "не на смене 🔴"
            notify_status = "вкл" if user['notify'] else "выкл"
            safe_send(message.chat.id, f"👷 Меню работника\n\nСтатус: {status}\nУведомления: {notify_status}", reply_markup=get_worker_kb())
        elif role == 'zakazchik':
            safe_send(message.chat.id, "🏢 Меню заказчика", reply_markup=get_customer_kb())
        elif role == 'moderator':
            safe_send(message.chat.id, "🛡️ Панель модератора", reply_markup=get_moderator_kb())
        else:
            safe_send(message.chat.id, "👋 Выберите роль:", reply_markup=get_main_kb(uid))
    except Exception as e:
        logger.error(f"❌ Ошибка в start: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Нажмите /start")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        role_map = {'👷 Я работник': 'rabotnik', '🏢 Я заказчик': 'zakazchik', '🛡️ Я модератор': 'moderator'}
        selected_role = role_map[message.text]
        if selected_role == 'moderator' and uid not in MODERATOR_IDS:
            safe_send(message.chat.id, "❌ У вас нет прав модератора.")
            return
        update_user(uid, 'role', selected_role)
        if selected_role == 'rabotnik':
            safe_send(message.chat.id, "✅ Вы переключились на роль работника!", reply_markup=get_worker_kb())
        elif selected_role == 'zakazchik':
            safe_send(message.chat.id, "✅ Вы переключились на роль заказчика!", reply_markup=get_customer_kb())
        else:
            safe_send(message.chat.id, "✅ Вы переключились на панель модератора!", reply_markup=get_moderator_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в role_choice: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back_to_main(message):
    try:
        uid = message.from_user.id
        safe_send(message.chat.id, "📱 Главное меню:\n\nВыберите роль:", reply_markup=get_main_kb(uid))
    except Exception as e:
        logger.error(f"❌ Ошибка в back_to_main: {e}")
        safe_send(message.chat.id, "📱 Главное меню:", reply_markup=get_main_kb(None))

# ===================== РЕГИСТРАЦИЯ =====================
@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def reg_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['agreement_accepted'] == 1:
            safe_send(message.chat.id, "✅ Вы уже зарегистрированы!")
            return
        role = user['role']
        if role not in ('rabotnik', 'zakazchik'):
            safe_send(message.chat.id, "❌ Сначала выберите роль через главное меню.")
            return
        save_state(uid, 'registration', '{}')
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("✅ Принимаю"), KeyboardButton("❌ Отмена"))
        if role == 'rabotnik':
            text = "📜 УСЛОВИЯ СЕРВИСА (ДЛЯ РАБОТНИКОВ)\n\n1. Вы берёте заказ только если готовы его выполнить.\n2. ОБЯЗАТЕЛЬНО подтвердите, что вы на месте (кнопка 'Я на месте').\n3. После работы отправьте ФОТО выполненной работы.\n4. Без фото и подтверждения заказчик не сможет подтвердить работу, и вы не получите выплату.\n5. Сервис гарантирует выплату после подтверждения заказчиком.\n6. Сервис не отвечает за травмы, кражи, качество вашей работы.\n\n✅ Принимаете условия?"
        else:
            text = "📜 УСЛОВИЯ СЕРВИСА (ДЛЯ ЗАКАЗЧИКОВ)\n\n🔹 Вы платите ДО начала работы — деньги замораживаются на счёте сервиса.\n🔹 Это гарантирует, что работники получат оплату после выполнения.\n🔹 После того как работники подтвердят, что они на месте, вы переводите деньги.\n🔹 Если работа выполнена качественно, вы подтверждаете это — деньги перечисляются работникам.\n🔹 Если работа выполнена плохо или не выполнена — вы можете отклонить, и мы вернём вам деньги (после проверки модератором).\n🔹 Сервис защищает и вас, и работников от недобросовестных исполнителей.\n\n✅ Принимаете условия?"
        safe_send(message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"❌ Ошибка в reg_start: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text in ['✅ Принимаю', '❌ Отмена'])
def handle_agreement(message):
    try:
        uid = message.from_user.id
        if message.text == '❌ Отмена':
            clear_state(uid)
            safe_send(message.chat.id, "❌ Регистрация отменена.", reply_markup=get_main_kb(uid))
            return
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Нажмите /start")
            return
        update_user(uid, 'agreement_accepted', 1)
        role = user['role']
        if role == 'rabotnik':
            msg = safe_send(message.chat.id, "📝 Введите ваше ФИО:")
            bot.register_next_step_handler(msg, get_worker_name, uid)
        else:
            msg = safe_send(message.chat.id, "📝 Введите ваше ФИО:")
            bot.register_next_step_handler(msg, get_customer_name, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_agreement: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_worker_name(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['name'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📞 Введите номер телефона (+7XXXXXXXXXX):")
        bot.register_next_step_handler(msg, get_worker_phone, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_worker_name: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_worker_phone(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['phone'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "💳 Введите номер карты для выплат:")
        bot.register_next_step_handler(msg, get_worker_bank, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_worker_phone: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_worker_bank(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['bank'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📝 Введите инициалы (Иванов И.И.):")
        bot.register_next_step_handler(msg, finish_worker_reg, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_worker_bank: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def finish_worker_reg(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        with db.transaction() as c:
            c.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
                     (data_obj.get('name'), data_obj.get('phone'), data_obj.get('bank'), message.text, uid))
        clear_state(uid)
        safe_send(message.chat.id, "✅ Регистрация завершена! Вы на смене 🟢", reply_markup=get_worker_kb())
        user_data = {
            'telegram_id': uid,
            'name': data_obj.get('name'),
            'phone': data_obj.get('phone'),
            'role': 'rabotnik',
            'registered_at': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        write_user_to_sheet(user_data)
    except Exception as e:
        logger.error(f"❌ Ошибка в finish_worker_reg: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_customer_name(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['name'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📞 Введите номер телефона (+7XXXXXXXXXX):")
        bot.register_next_step_handler(msg, get_customer_phone, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_customer_name: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_customer_phone(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['phone'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        finish_customer_reg(message, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_customer_phone: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def finish_customer_reg(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        with db.transaction() as c:
            c.execute("UPDATE users SET name=?, phone=? WHERE telegram_id=?",
                     (data_obj.get('name'), data_obj.get('phone'), uid))
        clear_state(uid)
        safe_send(message.chat.id, "✅ Регистрация заказчика завершена!", reply_markup=get_customer_kb())
        user_data = {
            'telegram_id': uid,
            'name': data_obj.get('name'),
            'phone': data_obj.get('phone'),
            'role': 'zakazchik',
            'registered_at': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        write_user_to_sheet(user_data)
    except Exception as e:
        logger.error(f"❌ Ошибка в finish_customer_reg: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== РАБОТНИК =====================
@bot.message_handler(func=lambda m: m.text == '🔄 Сменить смену')
def toggle_shift(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Только для работников.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        new_shift = 0 if user['on_shift'] == 1 else 1
        update_user(uid, 'on_shift', new_shift)
        status = "на смене 🟢" if new_shift == 1 else "не на смене 🔴"
        safe_send(message.chat.id, f"🔄 Статус: {status}", reply_markup=get_worker_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в toggle_shift: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🔔 Уведомления')
def toggle_notify(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Только для работников.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        new_notify = 0 if user['notify'] == 1 else 1
        update_user(uid, 'notify', new_notify)
        status = "включены" if new_notify == 1 else "выключены"
        safe_send(message.chat.id, f"🔔 Уведомления {status}", reply_markup=get_worker_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в toggle_notify: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Только для работников.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['agreement_accepted'] == 0:
            safe_send(message.chat.id, "❌ Вы не зарегистрированы. Нажмите '📝 Регистрация'.")
            return
        with db.transaction() as c:
            c.execute("SELECT id, payout_per_person, address, work_description, hours, people FROM orders WHERE status = 'open' ORDER BY created_at DESC LIMIT 20")
            rows = c.fetchall()
        if not rows:
            safe_send(message.chat.id, "📭 Нет свободных заказов.")
            return
        for row in rows:
            text = f"🆔 Заказ #{row['id']}\n💵 {row['payout_per_person']} ₽\n📍 {row['address']}\n📝 {row['work_description']}\n⏱ {row['hours']} ч.\n👥 {row['people']} чел."
            safe_send(message.chat.id, text, reply_markup=order_inline_kb(row['id'], is_customer=False))
    except Exception as e:
        logger.error(f"❌ Ошибка в free_orders: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Нажмите /start")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        if user['role'] == 'rabotnik':
            orders = get_worker_orders(user['id'])
            if not orders:
                safe_send(message.chat.id, "📭 Нет активных заказов.")
                return
            for o in orders:
                status_text = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'ready_to_pay': '💰 Ожидает оплаты', 
                              'paid': '✅ Оплачен', 'working': '🔧 Работы ведутся', 'waiting_approval': '📸 Ждёт подтверждения',
                              'waiting_payout': '💵 Ждёт выплаты', 'completed': '✅ Завершён'}.get(o['status'], o['status'])
                text = f"🆔 Заказ #{o['id']}\n📊 {status_text}\n💵 {o['payout']} ₽\n👤 {o['zakazchik_name']}\n📍 {o['address']}\n📝 {o['work_description']}"
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{o['id']}"))
                safe_send(message.chat.id, text, reply_markup=kb)
        elif user['role'] == 'zakazchik':
            orders = get_customer_orders(user['id'])
            if not orders:
                safe_send(message.chat.id, "📭 У вас нет заказов.")
                return
            for o in orders:
                status_text = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'ready_to_pay': '💰 Ожидает оплаты', 
                              'paid': '✅ Оплачен', 'working': '🔧 Работы ведутся', 'waiting_approval': '📸 Ждёт подтверждения',
                              'waiting_payout': '💵 Ждёт выплаты', 'completed': '✅ Завершён', 'cancelled': '❌ Отменён'}.get(o['status'], o['status'])
                text = f"🆔 Заказ #{o['id']}\n💰 {o['total_sum']} ₽\n📊 {status_text}\n📍 {o['address']}\n📝 {o['work_description']}"
                kb = InlineKeyboardMarkup()
                workers = get_workers_for_order(o['id'])
                if workers:
                    kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{o['id']}"))
                if o['status'] not in ('completed', 'cancelled'):
                    kb.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{o['id']}"))
                safe_send(message.chat.id, text, reply_markup=kb)
        else:
            safe_send(message.chat.id, "❌ Неизвестная роль.")
    except Exception as e:
        logger.error(f"❌ Ошибка в my_orders: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Только для работников.")
            return
        with db.transaction() as c:
            c.execute("SELECT SUM(payout) FROM assignments WHERE user_id = ?", (user['id'],))
            total = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM assignments WHERE user_id = ?", (user['id'],))
            count = c.fetchone()[0] or 0
        safe_send(message.chat.id, f"💰 ВАШИ ВЫПЛАТЫ\n\n💵 Всего: {total} ₽\n👥 Заказов: {count}")
    except Exception as e:
        logger.error(f"❌ Ошибка в my_payouts: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '👤 Профиль')
def profile(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        role_names = {'rabotnik': '👷 Работник', 'zakazchik': '🏢 Заказчик', 'moderator': '🛡️ Модератор'}
        text = f"👤 ПРОФИЛЬ\n\nИмя: {user['name'] or 'не указано'}\nТелефон: {user['phone'] or 'не указан'}\nРоль: {role_names.get(user['role'], user['role'])}\nРейтинг: {user['rating']}"
        safe_send(message.chat.id, text)
    except Exception as e:
        logger.error(f"❌ Ошибка в profile: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📞 Связаться с модератором')
def contact_moderator_worker(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['role'] not in ('rabotnik', 'zakazchik'):
            safe_send(message.chat.id, "❌ Эта функция недоступна.")
            return
        msg = safe_send(message.chat.id, "📝 Напишите сообщение модератору:")
        bot.register_next_step_handler(msg, send_to_moderator, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в contact_moderator_worker: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def send_to_moderator(message, uid):
    try:
        user = get_user(uid)
        text = f"📩 СООБЩЕНИЕ ОТ {user['role']}\n\nОт: {user['name'] or 'без имени'} (ID {user['id']})\nТелефон: {user['phone'] or 'не указан'}\n\n{message.text}"
        for m in MODERATOR_IDS:
            safe_send(m, text)
        safe_send(message.chat.id, "✅ Сообщение отправлено модератору.", reply_markup=get_worker_kb() if user['role']=='rabotnik' else get_customer_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в send_to_moderator: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== ЗАКАЗЧИК =====================
@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'zakazchik':
            safe_send(message.chat.id, "❌ Только для заказчиков.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['agreement_accepted'] == 0:
            safe_send(message.chat.id, "❌ Вы не зарегистрированы. Нажмите '📝 Регистрация'.")
            return
        save_state(uid, 'create_order', '{}')
        msg = safe_send(message.chat.id, "📍 Введите адрес выполнения работы:")
        bot.register_next_step_handler(msg, get_order_address, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в create_order_start: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_order_address(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['address'] = message.text
        save_state(uid, 'create_order', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📝 Введите описание работы (что нужно сделать):")
        bot.register_next_step_handler(msg, get_order_description, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_order_address: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_order_description(message, uid):
    try:
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['work_description'] = message.text
        save_state(uid, 'create_order', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "⏱ Введите количество часов (число):")
        bot.register_next_step_handler(msg, get_order_hours, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_order_description: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_order_hours(message, uid):
    try:
        hours = int(message.text)
        if hours <= 0: raise ValueError
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        data_obj['hours'] = hours
        save_state(uid, 'create_order', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "👥 Введите количество человек:")
        bot.register_next_step_handler(msg, get_order_people, uid)
    except:
        safe_send(message.chat.id, "❌ Введите положительное число.")
        msg = safe_send(message.chat.id, "⏱ Введите количество часов:")
        bot.register_next_step_handler(msg, get_order_hours, uid)

def get_order_people(message, uid):
    try:
        people = int(message.text)
        if people <= 0: raise ValueError
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Пользователь не найден.")
            return
        state, data = get_state(uid)
        data_obj = json.loads(data) if data else {}
        address = data_obj.get('address', '')
        work_description = data_obj.get('work_description', '')
        hours = data_obj.get('hours', 1)
        total = hours * people * PRICE_PER_HOUR
        commission = hours * people * COMMISSION_PER_HOUR
        payout = (total - commission) // people
        with db.transaction() as c:
            c.execute('''INSERT INTO orders (zakazchik_id, zakazchik_name, address, work_description, hours, people, total_sum, commission, payout_per_person, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     (user['id'], user['name'] or 'Заказчик', address, work_description, hours, people, total, commission, payout, 'open', datetime.now().isoformat()))
            order_id = c.lastrowid
        clear_state(uid)
        safe_send(message.chat.id, f"✅ ЗАКАЗ #{order_id} СОЗДАН!\n\n📍 {address}\n📝 {work_description}\n⏱ {hours} ч.\n👥 {people} чел.\n💰 {total} ₽", reply_markup=get_customer_kb())
        
        order_data = {
            'id': order_id,
            'created_at': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'zakazchik_name': user['name'] or 'Заказчик',
            'phone': user['phone'] or 'не указан',
            'address': address,
            'work_description': work_description,
            'hours': hours,
            'people': people,
            'total_sum': total,
            'commission': commission,
            'payout_per_person': payout,
            'status': 'Open'
        }
        write_order_to_sheet(order_data)
        
        workers = get_workers()
        if workers:
            text = f"🔔 НОВЫЙ ЗАКАЗ!\n🆔 #{order_id}\n💵 {payout} ₽\n📍 {address}\n📝 {work_description}\n⏱ {hours} ч.\n👥 {people} чел."
            for w in workers:
                safe_send(w, text)
        for m in MODERATOR_IDS:
            safe_send(m, f"📊 НОВЫЙ ЗАКАЗ #{order_id}\n\n👤 {user['name'] or 'Заказчик'}\n📍 {address}\n📝 {work_description}\n⏱ {hours} ч.\n👥 {people} чел.\n💰 {total} ₽")
    except:
        safe_send(message.chat.id, "❌ Введите положительное число.")
        msg = safe_send(message.chat.id, "👥 Введите количество человек:")
        bot.register_next_step_handler(msg, get_order_people, uid)

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'zakazchik':
            safe_send(message.chat.id, "❌ Только для заказчиков.")
            return
        msg = safe_send(message.chat.id, "📝 Опишите жалобу:")
        bot.register_next_step_handler(msg, send_complaint, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в complain: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def send_complaint(message, uid):
    try:
        user = get_user(uid)
        text = f"⚠️ ЖАЛОБА\n\nОт: {user['name'] or 'без имени'}\nТелефон: {user['phone'] or 'не указан'}\n\n{message.text}"
        for m in MODERATOR_IDS:
            safe_send(m, text)
        safe_send(message.chat.id, "✅ Жалоба отправлена.", reply_markup=get_customer_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в send_complaint: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== МОДЕРАТОР =====================
@bot.message_handler(func=lambda m: m.text in ['💰 Выплаты', '🟡 Активные', '✅ Завершённые', '👥 Работники', '🏢 Заказчики', '📊 Статистика', '⭐ Оценить работника', '⭐ Оценить заказчика', '🔒 Блокировка', '🔓 Разблокировка'] and m.from_user.id in MODERATOR_IDS)
def moderator_commands(message):
    try:
        uid = message.from_user.id
        text = message.text
        
        if text == '💰 Выплаты':
            with db.transaction() as c:
                c.execute("SELECT SUM(payout) FROM assignments")
                total = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM assignments")
                count = c.fetchone()[0] or 0
            safe_send(message.chat.id, f"💰 ВСЕГО ВЫПЛАЧЕНО\n\n💵 {total} ₽\n👥 {count} выплат")
        
        elif text == '🟡 Активные':
            orders = get_active_orders()
            if not orders:
                safe_send(message.chat.id, "🟡 Нет активных заказов.")
                return
            for row in orders[:10]:
                safe_send(message.chat.id, f"🆔 Заказ #{row['id']}\n👤 {row['zakazchik_name']}\n📍 {row['address']}\n📝 {row['work_description']}\n📊 {row['status']}\n💰 {row['total_sum']} ₽")
        
        elif text == '✅ Завершённые':
            with db.transaction() as c:
                c.execute("SELECT id, zakazchik_name, address, work_description, total_sum FROM orders WHERE status = 'completed' ORDER BY created_at DESC LIMIT 20")
                rows = c.fetchall()
            if not rows:
                safe_send(message.chat.id, "✅ Нет завершённых заказов.")
                return
            for row in rows:
                safe_send(message.chat.id, f"✅ Заказ #{row['id']}\n👤 {row['zakazchik_name']}\n📍 {row['address']}\n📝 {row['work_description']}\n💰 {row['total_sum']} ₽")
        
        elif text == '👥 Работники':
            workers = get_all_workers()
            if not workers:
                safe_send(message.chat.id, "👥 Нет работников.")
                return
            msg = "👥 РАБОТНИКИ:\n\n"
            for w in workers[:20]:
                status = "🟢" if w['on_shift'] else "🔴"
                block = "🔒" if w['blocked'] else "✅"
                notify = "🔔" if w['notify'] else "🔕"
                msg += f"{status} {block} {notify} ID {w['id']}: {w['name']}\n📞 {w['phone']}, ⭐ {w['rating']}\n"
            safe_send(message.chat.id, msg)
        
        elif text == '🏢 Заказчики':
            customers = get_all_customers()
            if not customers:
                safe_send(message.chat.id, "🏢 Нет заказчиков.")
                return
            msg = "🏢 ЗАКАЗЧИКИ:\n\n"
            for c in customers[:20]:
                block = "🔒" if c['blocked'] else "✅"
                msg += f"{block} ID {c['id']}: {c['name']}\n📞 {c['phone']}, ⭐ {c['customer_rating']}\n"
            safe_send(message.chat.id, msg)
        
        elif text == '📊 Статистика':
            with db.transaction() as c:
                c.execute("SELECT COUNT(*) FROM users")
                total = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM users WHERE role = 'rabotnik'")
                workers = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM users WHERE role = 'zakazchik'")
                customers = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM orders")
                orders = c.fetchone()[0] or 0
            safe_send(message.chat.id, f"📊 СТАТИСТИКА\n\n👥 Всего: {total}\n👷 Работников: {workers}\n🏢 Заказчиков: {customers}\n📦 Заказов: {orders}")
        
        elif text == '⭐ Оценить работника':
            msg = safe_send(message.chat.id, "Введите ID работника:")
            bot.register_next_step_handler(msg, mod_rate_get_user)
        
        elif text == '⭐ Оценить заказчика':
            msg = safe_send(message.chat.id, "Введите ID заказчика:")
            bot.register_next_step_handler(msg, mod_rate_customer_get)
        
        elif text == '🔒 Блокировка':
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton("По ID"), KeyboardButton("По телефону"))
            kb.row(KeyboardButton("⬅️ Назад"))
            msg = safe_send(message.chat.id, "🔒 Выберите способ:", reply_markup=kb)
            bot.register_next_step_handler(msg, mod_block_choose_method)
        
        elif text == '🔓 Разблокировка':
            msg = safe_send(message.chat.id, "Введите ID пользователя:")
            bot.register_next_step_handler(msg, mod_unblock_by_id)
        
    except Exception as e:
        logger.error(f"❌ Ошибка в moderator_commands: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ МОДЕРАТОРА =====================
def mod_rate_get_user(message):
    try:
        try:
            user_id = int(message.text)
        except:
            safe_send(message.chat.id, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        with db.transaction() as c:
            c.execute("SELECT id, name, rating FROM users WHERE id = ? AND role = 'rabotnik'", (user_id,))
            row = c.fetchone()
        if not row:
            safe_send(message.chat.id, "❌ Работник не найден.", reply_markup=get_moderator_kb())
            return
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = safe_send(message.chat.id, f"⭐ {row['name']} (рейтинг: {row['rating']})", reply_markup=kb)
        bot.register_next_step_handler(msg, mod_rate_apply, row['id'])
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_rate_get_user: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_rate_apply(message, user_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            safe_send(message.chat.id, "❌ Нажмите кнопку.", reply_markup=get_moderator_kb())
            return
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        add_rating(user_id, delta)
        with db.transaction() as c:
            c.execute("SELECT rating FROM users WHERE id = ?", (user_id,))
            new_rating = c.fetchone()[0] or 0
        safe_send(message.chat.id, f"✅ Рейтинг: {new_rating}", reply_markup=get_moderator_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_rate_apply: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_rate_customer_get(message):
    try:
        try:
            customer_id = int(message.text)
        except:
            safe_send(message.chat.id, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        with db.transaction() as c:
            c.execute("SELECT id, name, customer_rating FROM users WHERE id = ? AND role = 'zakazchik'", (customer_id,))
            row = c.fetchone()
        if not row:
            safe_send(message.chat.id, "❌ Заказчик не найден.", reply_markup=get_moderator_kb())
            return
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = safe_send(message.chat.id, f"⭐ {row['name']} (рейтинг: {row['customer_rating']})", reply_markup=kb)
        bot.register_next_step_handler(msg, mod_rate_customer_apply, row['id'])
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_rate_customer_get: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_rate_customer_apply(message, customer_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            safe_send(message.chat.id, "❌ Нажмите кнопку.", reply_markup=get_moderator_kb())
            return
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        rate_customer(customer_id, delta)
        with db.transaction() as c:
            c.execute("SELECT customer_rating FROM users WHERE id = ?", (customer_id,))
            new_rating = c.fetchone()[0] or 0
        safe_send(message.chat.id, f"✅ Рейтинг заказчика: {new_rating}", reply_markup=get_moderator_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_rate_customer_apply: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_block_choose_method(message):
    try:
        if message.text == '⬅️ Назад':
            safe_send(message.chat.id, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
            return
        if message.text == 'По ID':
            msg = safe_send(message.chat.id, "Введите ID пользователя:")
            bot.register_next_step_handler(msg, mod_block_by_id)
        elif message.text == 'По телефону':
            msg = safe_send(message.chat.id, "Введите номер телефона:")
            bot.register_next_step_handler(msg, mod_block_by_phone)
        else:
            safe_send(message.chat.id, "❌ Нажмите кнопку.", reply_markup=get_moderator_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_block_choose_method: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_block_by_id(message):
    try:
        try:
            user_id = int(message.text)
        except:
            safe_send(message.chat.id, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        with db.transaction() as c:
            c.execute("SELECT id, name, telegram_id FROM users WHERE id = ?", (user_id,))
            row = c.fetchone()
        if not row:
            safe_send(message.chat.id, "❌ Пользователь не найден.", reply_markup=get_moderator_kb())
            return
        with db.transaction() as c:
            c.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
        safe_send(message.chat.id, f"✅ {row['name']} заблокирован.", reply_markup=get_moderator_kb())
        safe_send(row['telegram_id'], "⛔ Вы заблокированы.")
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_block_by_id: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_block_by_phone(message):
    try:
        phone = message.text
        with db.transaction() as c:
            c.execute("UPDATE users SET blocked = 1 WHERE phone = ?", (phone,))
            c.execute("SELECT id, name, telegram_id FROM users WHERE phone = ?", (phone,))
            rows = c.fetchall()
        if rows:
            safe_send(message.chat.id, f"✅ Заблокировано {len(rows)} пользователей.", reply_markup=get_moderator_kb())
            for row in rows:
                safe_send(row['telegram_id'], "⛔ Вы заблокированы.")
        else:
            safe_send(message.chat.id, "❌ Пользователь не найден.", reply_markup=get_moderator_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_block_by_phone: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def mod_unblock_by_id(message):
    try:
        try:
            user_id = int(message.text)
        except:
            safe_send(message.chat.id, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        with db.transaction() as c:
            c.execute("SELECT id, name, telegram_id FROM users WHERE id = ? AND blocked = 1", (user_id,))
            row = c.fetchone()
        if not row:
            safe_send(message.chat.id, "❌ Заблокированный пользователь не найден.", reply_markup=get_moderator_kb())
            return
        with db.transaction() as c:
            c.execute("UPDATE users SET blocked = 0 WHERE id = ?", (user_id,))
        safe_send(message.chat.id, f"✅ {row['name']} разблокирован.", reply_markup=get_moderator_kb())
        safe_send(row['telegram_id'], "✅ Вы разблокированы.")
    except Exception as e:
        logger.error(f"❌ Ошибка в mod_unblock_by_id: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== CALLBACK =====================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        if call.message is None:
            bot.answer_callback_query(call.id, "⏳ Сообщение устарело", show_alert=True)
            return
        data = call.data
        user_id = call.from_user.id
        user = get_user(user_id)
        if not user or user['blocked'] == 1:
            bot.answer_callback_query(call.id, "⛔ Доступ запрещён", show_alert=True)
            return

        if data.startswith('contact_mod_'):
            order_id = int(data.split('_')[2])
            save_state(user_id, 'msg_to_mod', str(order_id), 60)
            bot.answer_callback_query(call.id, "📝 Напишите сообщение модератору", show_alert=False)
            safe_send(call.message.chat.id, f"📝 Напишите сообщение модератору по заказу #{order_id}:\n(для отмены отправьте /cancel)")

        elif data.startswith('contact_customer_order_'):
            parts = data.split('_')
            if len(parts) < 4:
                bot.answer_callback_query(call.id, "❌ Ошибка формата", show_alert=True)
                return
            order_id = int(parts[3])
            order = get_order(order_id)
            if order:
                save_state(user_id, 'msg_to_user', f"{order['zakazchik_id']}|{order_id}", 60)
                bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
                safe_send(call.message.chat.id, f"📝 Напишите сообщение по заказу #{order_id}:\n(для отмены отправьте /cancel)")

        elif data.startswith('contact_worker_order_'):
            parts = data.split('_')
            if len(parts) < 4:
                bot.answer_callback_query(call.id, "❌ Ошибка формата", show_alert=True)
                return
            order_id = int(parts[3])
            workers = get_workers_for_order(order_id)
            if workers:
                if len(workers) > 1:
                    kb = InlineKeyboardMarkup()
                    for w_id in workers:
                        w = get_user_by_id(w_id)
                        if w:
                            kb.add(InlineKeyboardButton(f"👤 {w['name'] or 'Работник'}", callback_data=f"send_msg_{w_id}_{order_id}"))
                    safe_send(call.message.chat.id, "👥 Выберите работника:", reply_markup=kb)
                    bot.answer_callback_query(call.id)
                else:
                    save_state(user_id, 'msg_to_user', f"{workers[0]}|{order_id}", 60)
                    bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
                    safe_send(call.message.chat.id, f"📝 Напишите сообщение по заказу #{order_id}:\n(для отмены отправьте /cancel)")
            else:
                bot.answer_callback_query(call.id, "❌ Нет работников", show_alert=True)

        elif data.startswith('send_msg_'):
            parts = data.split('_')
            if len(parts) < 4:
                bot.answer_callback_query(call.id, "❌ Ошибка формата", show_alert=True)
                return
            target_id = int(parts[2])
            order_id = int(parts[3]) if len(parts) > 3 else 0
            save_state(user_id, 'msg_to_user', f"{target_id}|{order_id}", 60)
            bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
            safe_send(call.message.chat.id, f"📝 Напишите сообщение:\n(для отмены отправьте /cancel)")

        elif data.startswith('take_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order['status'] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            if user['role'] != 'rabotnik':
                bot.answer_callback_query(call.id, "❌ Только для работников", show_alert=True)
                return
            if user['agreement_accepted'] == 0:
                bot.answer_callback_query(call.id, "❌ Вы не зарегистрированы. Пройдите регистрацию в меню работника.", show_alert=True)
                return
            assigned = get_assignments(order_id)
            if user['id'] in [a['user_id'] for a in assigned]:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли этот заказ", show_alert=True)
                return
            with db.transaction() as c:
                c.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", (order_id, user['id'], order['payout_per_person']))
            new_assigned = get_assignments(order_id)
            if len(new_assigned) >= order['people']:
                update_order_status(order_id, 'ready_to_pay')
                text = f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👥 Все работники собраны.\n📍 {order['address']}\n📝 {order['work_description']}\n💰 {order['total_sum']} ₽\n💳 Переведите по СБП: {SBP_PHONE}"
                safe_send(order['zakazchik_id'], text, reply_markup=payment_kb(order_id))
                for worker_id in get_workers_for_order(order_id):
                    worker = get_user_by_id(worker_id)
                    if worker:
                        safe_send(worker['telegram_id'], f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n📍 {order['address']}\n📝 {order['work_description']}\n💰 {order['payout_per_person']} ₽")
                for m in MODERATOR_IDS:
                    safe_send(m, f"📊 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n👤 {order['zakazchik_name']}\n📍 {order['address']}\n📝 {order['work_description']}\n👥 {order['people']} чел.\n💰 {order['total_sum']} ₽")
                bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} укомплектован!", show_alert=True)
            else:
                bot.answer_callback_query(call.id, f"✅ Вы взяли заказ #{order_id}!", show_alert=True)
            safe_edit(f"✅ Вы взяли заказ #{order_id}!\n📍 Подтвердите, что вы на месте.", call.message.chat.id, call.message.message_id, reply_markup=confirm_take_kb(order_id))

        elif data.startswith('confirm_place_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] not in ['open', 'in_progress', 'ready_to_pay']:
                bot.answer_callback_query(call.id, "❌ Заказ уже не в этой стадии", show_alert=True)
                return
            confirm_worker_on_place(order_id, user['id'])
            bot.answer_callback_query(call.id, "✅ Вы подтвердили, что на месте!", show_alert=True)
            safe_edit(f"✅ Вы на месте!\n💰 Ваша выплата: {order['payout_per_person']} ₽", call.message.chat.id, call.message.message_id)
            assigned = get_assignments(order_id)
            if all(a['confirmed'] == 1 for a in assigned) and order['status'] == 'open':
                update_order_status(order_id, 'ready_to_pay')
                text = f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👥 Все работники подтвердили место.\n📍 {order['address']}\n📝 {order['work_description']}\n💰 {order['total_sum']} ₽\n💳 {SBP_PHONE}"
                safe_send(order['zakazchik_id'], text, reply_markup=payment_kb(order_id))
                for worker_id in get_workers_for_order(order_id):
                    worker = get_user_by_id(worker_id)
                    if worker:
                        safe_send(worker['telegram_id'], f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n📍 {order['address']}\n📝 {order['work_description']}\n💰 {order['payout_per_person']} ₽")
                for m in MODERATOR_IDS:
                    safe_send(m, f"📊 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n👤 {order['zakazchik_name']}\n📍 {order['address']}\n📝 {order['work_description']}\n👥 {order['people']} чел.\n💰 {order['total_sum']} ₽")

        elif data.startswith('cancel_take_'):
            order_id = int(data.split('_')[2])
            with db.transaction() as c:
                c.execute("DELETE FROM assignments WHERE order_id = ? AND user_id = ?", (order_id, user['id']))
            bot.answer_callback_query(call.id, "❌ Отказ от заказа", show_alert=True)
            safe_edit("❌ Вы отказались от заказа", call.message.chat.id, call.message.message_id)

        elif data.startswith('i_paid_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'ready_to_pay':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе оплаты", show_alert=True)
                return
            if user['id'] != order['zakazchik_id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            update_order_status(order_id, 'paid')
            with db.transaction() as c:
                c.execute("UPDATE orders SET paid_at = ? WHERE id = ?", (datetime.now().isoformat(), order_id))
            bot.answer_callback_query(call.id, "✅ Оплата подтверждена!", show_alert=True)
            safe_edit(f"✅ Оплата заказа #{order_id} подтверждена!", call.message.chat.id, call.message.message_id)
            for m in MODERATOR_IDS:
                safe_send(m, f"💰 ЗАКАЗ #{order_id} ОПЛАЧЕН!\n👤 {order['zakazchik_name']}\n📍 {order['address']}\n📝 {order['work_description']}\n💰 {order['total_sum']} ₽", reply_markup=moderator_payment_kb(order_id))

        elif data.startswith('confirm_payment_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'paid':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе оплаты", show_alert=True)
                return
            if user['id'] not in MODERATOR_IDS:
                bot.answer_callback_query(call.id, "❌ Нет прав", show_alert=True)
                return
            update_order_status(order_id, 'working')
            bot.answer_callback_query(call.id, "✅ Оплата подтверждена!", show_alert=True)
            safe_edit(f"✅ Оплата заказа #{order_id} подтверждена!", call.message.chat.id, call.message.message_id)
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"✅ ЗАКАЗ #{order_id} ОПЛАЧЕН!\n📍 {order['address']}\n📝 {order['work_description']}\n⏱ {order['hours']} ч.\n📸 После выполнения отправьте фото:", reply_markup=worker_photo_kb(order_id))
            safe_send(order['zakazchik_id'], f"✅ ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН!\n📍 {order['address']}\n📝 {order['work_description']}\n⏱ {order['hours']} ч.")

        elif data.startswith('send_photo_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'working':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе работы", show_alert=True)
                return
            save_state(user['id'], f'waiting_photo_{order_id}', '{}', 60)
            bot.answer_callback_query(call.id, "📸 Отправьте фото выполненной работы", show_alert=True)
            safe_send(call.message.chat.id, f"📸 Отправьте фото для заказа #{order_id}")

        elif data.startswith('approve_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'waiting_approval':
                bot.answer_callback_query(call.id, "❌ Заказ не ждёт подтверждения", show_alert=True)
                return
            if user['id'] != order['zakazchik_id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            update_order_status(order_id, 'waiting_payout')
            with db.transaction() as c:
                c.execute("UPDATE orders SET completed_at = ? WHERE id = ?", (datetime.now().isoformat(), order_id))
            bot.answer_callback_query(call.id, "✅ Работа подтверждена!", show_alert=True)
            safe_edit(f"✅ Заказ #{order_id} выполнен!", call.message.chat.id, call.message.message_id)
            for m in MODERATOR_IDS:
                safe_send(m, f"✅ ЗАКАЗ #{order_id} ВЫПОЛНЕН!\n📍 {order['address']}\n📝 {order['work_description']}\n💰 {order['total_sum']} ₽\n💵 {order['payout_per_person']} ₽/чел", reply_markup=moderator_payout_kb(order_id))
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"✅ Заказ #{order_id} одобрен!\n💵 {order['payout_per_person']} ₽")

        elif data.startswith('reject_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'waiting_approval':
                bot.answer_callback_query(call.id, "❌ Заказ не ждёт подтверждения", show_alert=True)
                return
            if user['id'] != order['zakazchik_id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            bot.answer_callback_query(call.id, "❌ Работа отклонена", show_alert=True)
            safe_edit(f"❌ Работа по заказу #{order_id} отклонена.", call.message.chat.id, call.message.message_id)
            for m in MODERATOR_IDS:
                safe_send(m, f"❌ ЗАКАЗ #{order_id} ОТКЛОНЁН!\n👤 {order['zakazchik_name']}")

        elif data.startswith('confirm_payout_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'waiting_payout':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе выплаты", show_alert=True)
                return
            if user['id'] not in MODERATOR_IDS:
                bot.answer_callback_query(call.id, "❌ Нет прав", show_alert=True)
                return
            update_order_status(order_id, 'completed')
            bot.answer_callback_query(call.id, "✅ Выплата подтверждена!", show_alert=True)
            safe_edit(f"✅ Выплата по заказу #{order_id} подтверждена!", call.message.chat.id, call.message.message_id)
            safe_send(order['zakazchik_id'], f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n💰 Работники получили оплату.")
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n💵 {order['payout_per_person']} ₽")
            if order:
                for worker_id in get_workers_for_order(order_id):
                    worker = get_user_by_id(worker_id)
                    if worker:
                        payout_data = {
                            'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
                            'order_id': order_id,
                            'customer_name': order['zakazchik_name'],
                            'address': order['address'],
                            'worker_name': worker['name'] or 'Работник',
                            'amount': order['payout_per_person'],
                            'moderator_name': user['name'] or 'Модератор'
                        }
                        write_payout_to_sheet(payout_data)
                commission_data = {
                    'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
                    'order_id': order_id,
                    'amount': order['commission']
                }
                write_commission_to_sheet(commission_data)
                update_order_status_in_sheet(order_id, 'Completed', completed_at=datetime.now().strftime('%d.%m.%Y %H:%M'))

        elif data.startswith('cancel_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order['zakazchik_id'] != user['id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            if order['status'] in ('completed', 'cancelled'):
                bot.answer_callback_query(call.id, "❌ Этот заказ уже завершён или отменён", show_alert=True)
                return
            update_order_status(order_id, 'cancelled')
            bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} отменён!", show_alert=True)
            safe_edit(f"❌ ЗАКАЗ #{order_id} ОТМЕНЁН", call.message.chat.id, call.message.message_id)
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"❌ Заказ #{order_id} отменён заказчиком.")
            update_order_status_in_sheet(order_id, 'Cancelled')

        elif data.startswith('complete_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order['zakazchik_id'] != user['id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            if order['status'] != 'working':
                bot.answer_callback_query(call.id, "❌ Заказ не в работе", show_alert=True)
                return
            workers_with_photo = get_assignments_with_photo(order_id)
            if not workers_with_photo:
                bot.answer_callback_query(call.id, "❌ Работники ещё не отправили фото.", show_alert=True)
                return
            update_order_status(order_id, 'waiting_approval')
            bot.answer_callback_query(call.id, f"✅ Заказ ожидает подтверждения!", show_alert=True)
            safe_edit(f"📸 Заказ #{order_id} выполнен!\n✅ Подтвердите качество:", call.message.chat.id, call.message.message_id, reply_markup=approve_kb(order_id))
            update_order_status_in_sheet(order_id, 'Waiting approval')

        else:
            bot.answer_callback_query(call.id, "❌ Неизвестная команда", show_alert=True)
    except Exception as e:
        logger.error(f"❌ Ошибка в callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# ===================== ОБРАБОТЧИК ФОТО =====================
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Нажмите /start")
            return
        state, data = get_state(uid)
        if not state or not state.startswith('waiting_photo_'):
            safe_send(message.chat.id, "❌ Нет активного запроса на фото.")
            return
        order_id = int(state.split('_')[2])
        photo_file_id = message.photo[-1].file_id
        set_worker_photo(order_id, user['id'], photo_file_id)
        clear_state(uid)
        safe_send(message.chat.id, f"✅ Фото для заказа #{order_id} сохранено!")
        order = get_order(order_id)
        if order:
            workers_in_order = get_workers_for_order(order_id)
            workers_with_photo = get_assignments_with_photo(order_id)
            if len(workers_with_photo) == len(workers_in_order):
                safe_send(order['zakazchik_id'], f"📸 Все работники отправили фото!\n✅ Подтвердите выполнение:", reply_markup=approve_kb(order_id))
                if order['status'] == 'working':
                    update_order_status(order_id, 'waiting_approval')
                    for m in MODERATOR_IDS:
                        safe_send(m, f"📸 Все работники отправили фото по заказу #{order_id}!")
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_photo: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== ОБРАБОТЧИК СООБЩЕНИЙ =====================
@bot.message_handler(commands=['cancel'])
def cancel_message(message):
    try:
        clear_state(message.from_user.id)
        safe_send(message.chat.id, "❌ Отправка отменена.", reply_markup=get_main_kb(message.from_user.id))
    except Exception as e:
        logger.error(f"❌ Ошибка в cancel_message: {e}")
        safe_send(message.chat.id, "❌ Ошибка.")

@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    try:
        uid = message.from_user.id
        if not message.text:
            return
        state, data = get_state(uid)
        if not state:
            return
        if state == 'msg_to_mod':
            order_id = int(data)
            text = f"📩 СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ\n\nОт: {message.from_user.first_name} (ID {uid})\nПо заказу #{order_id}\n\n{message.text}"
            for m in MODERATOR_IDS:
                safe_send(m, text)
            safe_send(message.chat.id, "✅ Сообщение отправлено модератору.")
            clear_state(uid)
        elif state == 'msg_to_user':
            parts = data.split('|')
            target_id = int(parts[0])
            order_id = int(parts[1]) if len(parts) > 1 else 0
            target_user = get_user_by_id(target_id)
            if target_user:
                order_text = f" по заказу #{order_id}" if order_id != 0 else ""
                safe_send(target_user['telegram_id'], f"📩 НОВОЕ СООБЩЕНИЕ{order_text}\n\nОт: {message.from_user.first_name}\n\n{message.text}")
                safe_send(message.chat.id, "✅ Сообщение отправлено!")
            else:
                safe_send(message.chat.id, "❌ Пользователь не найден.")
            clear_state(uid)
        elif state.startswith('waiting_photo_'):
            pass
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_user_message: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== БЛОКИРОВАННЫЙ =====================
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator_blocked(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['blocked'] == 0:
            return
        for m in MODERATOR_IDS:
            safe_send(m, f"📞 Пользователь {uid} ({user['name'] or 'без имени'}) просит связи.")
        safe_send(message.chat.id, "✅ Запрос отправлен модератору.")
    except Exception as e:
        logger.error(f"❌ Ошибка в contact_moderator_blocked: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ===================== ЗАПУСК =====================
def start_bot():
    while True:
        try:
            logger.info("🚀 Бот запущен!")
            print(f"🤖 Бот {BOT_NAME} запущен!")
            print(f"📊 Модераторы: {MODERATOR_IDS}")
            print(f"💳 СБП: {SBP_PHONE}")
            print("✅ Готов к работе!")
            bot.polling(none_stop=True, interval=1, timeout=60, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"⚠️ Ошибка в polling: {e}")
            print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)

if __name__ == "__main__":
    start_bot()
