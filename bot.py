import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime
import threading
import time
import logging
import os
import sys
import random
from contextlib import contextmanager

# ========================================
# НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ========================================

TOKEN = os.getenv('TOKEN')
if not TOKEN:
    raise ValueError("❌ Ошибка: TOKEN не задан! Добавь переменную окружения TOKEN в Railway.")

MODERATOR_IDS = os.getenv('MODERATOR_IDS', '8746212340')
MODERATOR_IDS = [int(x.strip()) for x in MODERATOR_IDS.split(',')]

SBP_PHONE = os.getenv('SBP_PHONE', '+7XXXXXXXXXX')
COMMISSION_PER_HOUR = int(os.getenv('COMMISSION_PER_HOUR', '50'))
PRICE_PER_HOUR = int(os.getenv('PRICE_PER_HOUR', '500'))
CONFIRM_TIMEOUT = int(os.getenv('CONFIRM_TIMEOUT', '30'))
BOT_NAME = os.getenv('BOT_NAME', 'Юрга-Подработка')

bot = telebot.TeleBot(TOKEN)

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ========== КЛАСС БАЗЫ ДАННЫХ ==========
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
            self.conn.execute("PRAGMA cache_size=10000")
            self.conn.execute("PRAGMA temp_store=MEMORY")
            
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
                blocked INTEGER DEFAULT 0
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zakazchik_id INTEGER,
                zakazchik_name TEXT,
                address TEXT,
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
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_on_shift ON users(on_shift)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_zakazchik_id ON orders(zakazchik_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_assignments_order_id ON assignments(order_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_assignments_user_id ON assignments(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_to_user_id ON messages(to_user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_read ON messages(read)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_temp_states_user_id ON temp_states(user_id)")
            
            c.execute("DELETE FROM temp_states WHERE expires_at < datetime('now')")
            
            self.conn.commit()
            logger.info("✅ База данных инициализирована с WAL и индексами")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            raise
    
    @contextmanager
    def transaction(self):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                cursor = self.conn.cursor()
                yield cursor
                self.conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"⚠️ БД заблокирована, попытка {attempt+1}/{max_retries}")
                    time.sleep(random.uniform(0.1, 0.5))
                    continue
                raise
            except Exception as e:
                self.conn.rollback()
                raise
    
    def execute(self, query, params=()):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                self.conn.commit()
                return cursor
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"⚠️ БД заблокирована, попытка {attempt+1}/{max_retries}")
                    time.sleep(random.uniform(0.1, 0.5))
                    continue
                raise

db = Database()

# ========== БЕЗОПАСНЫЕ ФУНКЦИИ ОТПРАВКИ ==========
def safe_send(chat_id, text, **kwargs):
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

# ========== ФУНКЦИИ РАБОТЫ С БД ==========
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
            c.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND on_shift = 1 AND blocked = 0")
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
            c.execute('''SELECT o.id, o.status, a.payout, o.zakazchik_name, o.address, a.confirmed
                     FROM assignments a 
                     JOIN orders o ON a.order_id = o.id 
                     WHERE a.user_id = ?
                     ORDER BY o.created_at DESC LIMIT 100''', (user_id,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_worker_orders: {e}")
        return []

def get_customer_orders(zakazchik_id):
    try:
        with db.transaction() as c:
            c.execute("SELECT id, total_sum, status, created_at FROM orders WHERE zakazchik_id = ? ORDER BY created_at DESC LIMIT 100", (zakazchik_id,))
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
            c.execute("SELECT id, name, phone, rating, blocked, on_shift FROM users WHERE role = 'rabotnik' ORDER BY rating DESC LIMIT ?", (limit,))
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

def get_completed_orders(limit=50):
    try:
        with db.transaction() as c:
            c.execute("SELECT * FROM orders WHERE status = 'completed' ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"❌ Ошибка get_completed_orders: {e}")
        return []

def save_state(user_id, state, data=None, ttl_minutes=30):
    try:
        expires_at = datetime.now().isoformat()
        with db.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO temp_states (user_id, state, data, created_at, expires_at) VALUES (?, ?, ?, ?, datetime(?, '+? minutes'))",
                (user_id, state, data or '{}', expires_at, expires_at, ttl_minutes)
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
            if row:
                return row['state'], row['data']
            return None, None
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
# ========================================
# КЛАВИАТУРЫ
# ========================================

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
    kb.row(KeyboardButton("📞 Связаться с модератором"), KeyboardButton("⬅️ Назад"))
    return kb

def get_customer_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📝 Создать заказ"))
    kb.row(KeyboardButton("📋 Мои заказы"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("⚠️ Пожаловаться"), KeyboardButton("⬅️ Назад"))
    return kb

def get_moderator_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    kb.row(KeyboardButton("🏢 Заказчики"), KeyboardButton("📊 Статистика"))
    kb.row(KeyboardButton("⭐ Оценить работника"), KeyboardButton("⭐ Оценить заказчика"))
    kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блокировка"))
    kb.row(KeyboardButton("🔓 Разблокировка"), KeyboardButton("📨 Сообщения"))
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
        kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_{order_id}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{order_id}"))
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

# ========================================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# ========================================

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
        
        unread = get_unread_messages(uid)
        if unread and uid not in MODERATOR_IDS:
            safe_send(message.chat.id, f"📨 У вас {len(unread)} непрочитанных сообщений.")
        
        role = user['role']
        if role == 'rabotnik':
            status = "на смене 🟢" if user['on_shift'] else "не на смене 🔴"
            safe_send(message.chat.id, f"👷 Меню работника\n\nСтатус: {status}", reply_markup=get_worker_kb())
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

# ========================================
# РЕГИСТРАЦИЯ
# ========================================

@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def reg_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Нажмите /start")
            return
        if user['blocked'] == 1:
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
            text = """📜 УСЛОВИЯ СЕРВИСА (ДЛЯ РАБОТНИКОВ)\n\n1. Сервис - посредник между заказчиками и работниками\n2. Вы берёте заказ только если готовы выполнить его качественно\n3. ОБЯЗАТЕЛЬНО подтвердите, что вы на месте (кнопка "Я на месте")\n4. Без подтверждения "на месте" - заказчик не оплачивает, вы не получаете выплату\n5. После выполнения работы отправьте ФОТО выполненной работы\n6. Без фото - заказчик не подтвердит выполнение, вы не получите выплату\n7. Сервис гарантирует выплату после подтверждения заказчиком\n8. Сервис не отвечает за травмы, кражи, качество вашей работы\n\n✅ Принимаете условия?"""
        else:
            text = """📜 УСЛОВИЯ СЕРВИСА (ДЛЯ ЗАКАЗЧИКОВ)\n\n1. Сервис - посредник между заказчиками и работниками\n2. После создания заказа работники сами решают брать его или нет\n3. После комплектации заказа вы переводите деньги на СБП сервиса\n4. Деньги хранятся на счёте сервиса до полного выполнения заказа\n5. Если работники сорвали сделку - деньги возвращаются в полном объёме\n6. После выполнения работы вы подтверждаете её качество\n7. Только после вашего подтверждения мы переводим деньги работникам\n8. Сервис не отвечает за качество работы, травмы, кражи\n\n✅ Принимаете условия?"""
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
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
        data_obj['name'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📞 Введите номер телефона (в формате +7XXXXXXXXXX):")
        bot.register_next_step_handler(msg, get_worker_phone, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_worker_name: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_worker_phone(message, uid):
    try:
        state, data = get_state(uid)
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
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
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
        data_obj['bank'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📝 Введите инициалы (например: Иванов И.И.):")
        bot.register_next_step_handler(msg, finish_worker_reg, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_worker_bank: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def finish_worker_reg(message, uid):
    try:
        state, data = get_state(uid)
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
        with db.transaction() as c:
            c.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
                     (data_obj.get('name'), data_obj.get('phone'), data_obj.get('bank'), message.text, uid))
        clear_state(uid)
        safe_send(message.chat.id, "✅ Регистрация завершена! Вы на смене 🟢", reply_markup=get_worker_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в finish_worker_reg: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_customer_name(message, uid):
    try:
        state, data = get_state(uid)
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
        data_obj['name'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "📞 Введите номер телефона (в формате +7XXXXXXXXXX):")
        bot.register_next_step_handler(msg, get_customer_phone, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_customer_name: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_customer_phone(message, uid):
    try:
        state, data = get_state(uid)
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
        data_obj['phone'] = message.text
        save_state(uid, 'registration', json.dumps(data_obj))
        finish_customer_reg(message, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_customer_phone: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def finish_customer_reg(message, uid):
    try:
        state, data = get_state(uid)
        if not data:
            data = '{}'
        import json
        data_obj = json.loads(data)
        with db.transaction() as c:
            c.execute("UPDATE users SET name=?, phone=? WHERE telegram_id=?",
                     (data_obj.get('name'), data_obj.get('phone'), uid))
        clear_state(uid)
        safe_send(message.chat.id, "✅ Регистрация завершена! Можете создавать заказы.", reply_markup=get_customer_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в finish_customer_reg: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")
# ========================================
# РАБОТНИК
# ========================================

@bot.message_handler(func=lambda m: m.text == '🔄 Сменить смену')
def toggle_shift(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Эта функция только для работников.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['agreement_accepted'] == 0:
            safe_send(message.chat.id, "❌ Пройдите регистрацию.")
            return
        current_shift = user['on_shift']
        new_shift = 0 if current_shift == 1 else 1
        update_user(uid, 'on_shift', new_shift)
        status = "на смене 🟢" if new_shift == 1 else "не на смене 🔴"
        safe_send(message.chat.id, f"🔄 Статус смены изменён!\n\nВы {status}", reply_markup=get_worker_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в toggle_shift: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Эта функция только для работников.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['agreement_accepted'] == 0:
            safe_send(message.chat.id, "❌ Пройдите регистрацию.")
            return
        
        with db.transaction() as c:
            c.execute("SELECT id, payout_per_person, address, hours, people FROM orders WHERE status = 'open' ORDER BY created_at DESC LIMIT 20")
            rows = c.fetchall()
        
        if not rows:
            safe_send(message.chat.id, "📭 Нет свободных заказов.")
            return
        
        for row in rows:
            text = (f"🆔 Заказ #{row['id']}\n💵 Выплата: {row['payout_per_person']} ₽\n📍 Адрес: {row['address']}\n⏱ Часы: {row['hours']} ч.\n👥 Нужно: {row['people']} чел.")
            safe_send(message.chat.id, text, reply_markup=order_inline_kb(row['id'], is_customer=False))
    except Exception as e:
        logger.error(f"❌ Ошибка в free_orders: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_worker_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Эта функция только для работников.")
            return
        orders = get_worker_orders(user['id'])
        if not orders:
            safe_send(message.chat.id, "📭 У вас нет активных заказов.")
            return
        for o in orders:
            status_text = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'ready_to_pay': '💰 Ожидает оплаты', 
                          'paid': '✅ Оплачен', 'working': '🔧 Работы ведутся', 'waiting_approval': '📸 Ждёт подтверждения',
                          'waiting_payout': '💵 Ждёт выплаты', 'completed': '✅ Завершён', 'cancelled': '❌ Отменён'}.get(o['status'], o['status'])
            text = f"🆔 Заказ #{o['id']}\n📊 Статус: {status_text}\n💵 Выплата: {o['payout']} ₽\n👤 Заказчик: {o['zakazchik_name']}\n📍 Адрес: {o['address']}"
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{o['id']}"))
            safe_send(message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"❌ Ошибка в my_worker_orders: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Эта функция только для работников.")
            return
        with db.transaction() as c:
            c.execute("SELECT SUM(payout) FROM assignments WHERE user_id = ?", (user['id'],))
            total = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM assignments WHERE user_id = ?", (user['id'],))
            count = c.fetchone()[0] or 0
        safe_send(message.chat.id, f"💰 ВАШИ ВЫПЛАТЫ\n\n💵 Всего выплачено: {total} ₽\n👥 Количество заказов: {count}")
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
        text = (f"👤 ПРОФИЛЬ\n\nИмя: {user['name'] or 'не указано'}\nТелефон: {user['phone'] or 'не указан'}\n"
                f"Роль: {role_names.get(user['role'], user['role'])}\nРейтинг: {user['rating']}\nСоглашение: {'✅ Да' if user['agreement_accepted'] else '❌ Нет'}\nБлокировка: {'🔒 Да' if user['blocked'] else '✅ Нет'}")
        safe_send(message.chat.id, text)
    except Exception as e:
        logger.error(f"❌ Ошибка в profile: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📞 Связаться с модератором')
def contact_moderator_worker(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'rabotnik':
            safe_send(message.chat.id, "❌ Эта функция только для работников.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        msg = safe_send(message.chat.id, "📝 Напишите сообщение модератору:")
        bot.register_next_step_handler(msg, send_to_moderator, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в contact_moderator_worker: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def send_to_moderator(message, uid):
    try:
        user = get_user(uid)
        text = f"📩 СООБЩЕНИЕ ОТ РАБОТНИКА\n\nОт: {user['name'] or 'без имени'} (ID {user['id']})\nТелефон: {user['phone'] or 'не указан'}\n\n{message.text}"
        for m in MODERATOR_IDS:
            safe_send(m, text)
        safe_send(message.chat.id, "✅ Сообщение отправлено модератору.", reply_markup=get_worker_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в send_to_moderator: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ========================================
# ЗАКАЗЧИК
# ========================================

@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'zakazchik':
            safe_send(message.chat.id, "❌ Эта функция только для заказчиков.")
            return
        if user['blocked'] == 1:
            safe_send(message.chat.id, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        if user['agreement_accepted'] == 0:
            safe_send(message.chat.id, "❌ Пройдите регистрацию.")
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
        import json
        data_obj = json.loads(data) if data else {}
        data_obj['address'] = message.text
        save_state(uid, 'create_order', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "⏱ Введите количество часов (число, минимум 1):")
        bot.register_next_step_handler(msg, get_order_hours, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_order_address: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_order_hours(message, uid):
    try:
        hours = int(message.text)
        if hours <= 0:
            raise ValueError
        state, data = get_state(uid)
        import json
        data_obj = json.loads(data) if data else {}
        data_obj['hours'] = hours
        save_state(uid, 'create_order', json.dumps(data_obj))
        msg = safe_send(message.chat.id, "👥 Введите количество человек (минимум 1):")
        bot.register_next_step_handler(msg, get_order_people, uid)
    except ValueError:
        safe_send(message.chat.id, "❌ Введите положительное число.")
        msg = safe_send(message.chat.id, "⏱ Введите количество часов (число):")
        bot.register_next_step_handler(msg, get_order_hours, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_order_hours: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def get_order_people(message, uid):
    try:
        people = int(message.text)
        if people <= 0:
            raise ValueError
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "❌ Пользователь не найден.")
            return
        state, data = get_state(uid)
        import json
        data_obj = json.loads(data) if data else {}
        hours = data_obj.get('hours', 1)
        address = data_obj.get('address', '')
        total = hours * people * PRICE_PER_HOUR
        commission = hours * people * COMMISSION_PER_HOUR
        payout = (total - commission) // people
        with db.transaction() as c:
            c.execute('''INSERT INTO orders (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                     (user['id'], user['name'] or 'Заказчик', address, hours, people, total, commission, payout, 'open', datetime.now().isoformat()))
            order_id = c.lastrowid
        clear_state(uid)
        safe_send(message.chat.id, f"✅ ЗАКАЗ #{order_id} СОЗДАН!\n\n📍 Адрес: {address}\n⏱ Часы: {hours} ч.\n👥 Нужно: {people} чел.\n💰 Сумма к оплате: {total} ₽\n\n📌 Ожидайте, пока работники соберутся.", reply_markup=get_customer_kb())
        workers = get_workers()
        if workers:
            text = f"🔔 НОВЫЙ ЗАКАЗ!\n🆔 #{order_id}\n💵 Выплата: {payout} ₽\n📍 Адрес: {address}\n⏱ Часы: {hours} ч.\n👥 Нужно: {people} чел."
            for w in workers:
                safe_send(w, text)
        for m in MODERATOR_IDS:
            safe_send(m, f"📊 НОВЫЙ ЗАКАЗ #{order_id}\n\n👤 Заказчик: {user['name'] or 'Заказчик'} (ID {user['id']})\n📍 Адрес: {address}\n⏱ Часы: {hours} ч.\n👥 Человек: {people}\n💰 Сумма: {total} ₽\n📊 Комиссия: {commission} ₽\n💵 Выплата: {payout} ₽/чел")
    except ValueError:
        safe_send(message.chat.id, "❌ Введите положительное число.")
        msg = safe_send(message.chat.id, "👥 Введите количество человек:")
        bot.register_next_step_handler(msg, get_order_people, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в get_order_people: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_customer(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'zakazchik':
            safe_send(message.chat.id, "❌ Эта функция только для заказчиков.")
            return
        orders = get_customer_orders(user['id'])
        if not orders:
            safe_send(message.chat.id, "📭 У вас нет заказов.")
            return
        for o in orders:
            status_text = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'ready_to_pay': '💰 Ожидает оплаты', 
                          'paid': '✅ Оплачен', 'working': '🔧 Работы ведутся', 'waiting_approval': '📸 Ждёт подтверждения',
                          'waiting_payout': '💵 Ждёт выплаты', 'completed': '✅ Завершён', 'cancelled': '❌ Отменён'}.get(o['status'], o['status'])
            text = f"🆔 Заказ #{o['id']}\n💰 Сумма: {o['total_sum']} ₽\n📊 Статус: {status_text}"
            kb = InlineKeyboardMarkup()
            workers = get_workers_for_order(o['id'])
            if workers:
                kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{o['id']}"))
            safe_send(message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"❌ Ошибка в my_orders_customer: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'zakazchik':
            safe_send(message.chat.id, "❌ Эта функция только для заказчиков.")
            return
        msg = safe_send(message.chat.id, "📝 Опишите вашу жалобу:")
        bot.register_next_step_handler(msg, send_complaint, uid)
    except Exception as e:
        logger.error(f"❌ Ошибка в complain: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

def send_complaint(message, uid):
    try:
        user = get_user(uid)
        text = f"⚠️ ЖАЛОБА\n\nОт: {user['name'] or 'без имени'} (ID {user['id']})\nТелефон: {user['phone'] or 'не указан'}\n\n{message.text}"
        for m in MODERATOR_IDS:
            safe_send(m, text)
        safe_send(message.chat.id, "✅ Жалоба отправлена модератору.", reply_markup=get_customer_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в send_complaint: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ========================================
# МОДЕРАТОР (краткая версия, остальное в callback)
# ========================================

@bot.message_handler(func=lambda m: m.text in ['💰 Выплаты', '🟡 Активные', '✅ Завершённые', '👥 Работники', '🏢 Заказчики', '📊 Статистика', '⭐ Оценить работника', '⭐ Оценить заказчика', '⚖️ Арбитраж', '🔒 Блокировка', '🔓 Разблокировка', '📨 Сообщения'] and m.from_user.id in MODERATOR_IDS)
def moderator_commands(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user['role'] != 'moderator':
            safe_send(message.chat.id, "❌ У вас нет прав модератора.")
            return
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
            for row in orders:
                status_text = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'ready_to_pay': '💰 Ожидает оплаты', 
                              'paid': '✅ Оплачен', 'working': '🔧 Работы ведутся', 'waiting_approval': '📸 Ждёт подтверждения',
                              'waiting_payout': '💵 Ждёт выплаты'}.get(row['status'], row['status'])
                msg_text = f"🆔 Заказ #{row['id']}\n👤 Заказчик: {row['zakazchik_name']}\n📍 Адрес: {row['address']}\n📊 Статус: {status_text}\n💰 Сумма: {row['total_sum']} ₽\n💵 Выплата: {row['payout_per_person']} ₽/чел"
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{row['id']}"))
                workers = get_workers_for_order(row['id'])
                if workers:
                    kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{row['id']}"))
                safe_send(message.chat.id, msg_text, reply_markup=kb)
        elif text == '✅ Завершённые':
            orders = get_completed_orders()
            if not orders:
                safe_send(message.chat.id, "✅ Нет завершённых заказов.")
                return
            for row in orders[:10]:
                msg_text = f"✅ Заказ #{row['id']}\n👤 Заказчик: {row['zakazchik_name']}\n📍 Адрес: {row['address']}\n💰 Сумма: {row['total_sum']} ₽"
                safe_send(message.chat.id, msg_text)
        elif text == '👥 Работники':
            workers = get_all_workers()
            if not workers:
                safe_send(message.chat.id, "👥 Нет работников.")
                return
            msg_text = "👥 РАБОТНИКИ:\n\n"
            for w in workers[:20]:
                status = "🟢" if w['on_shift'] else "🔴"
                block = "🔒" if w['blocked'] else "✅"
                msg_text += f"{status} {block} ID {w['id']}: {w['name']}\n📞 {w['phone']}, ⭐ {w['rating']}\n"
            safe_send(message.chat.id, msg_text)
        elif text == '🏢 Заказчики':
            customers = get_all_customers()
            if not customers:
                safe_send(message.chat.id, "🏢 Нет заказчиков.")
                return
            msg_text = "🏢 ЗАКАЗЧИКИ:\n\n"
            for c in customers[:20]:
                block = "🔒" if c['blocked'] else "✅"
                msg_text += f"{block} ID {c['id']}: {c['name']}\n📞 {c['phone']}, ⭐ {c['customer_rating']}\n"
            safe_send(message.chat.id, msg_text)
        elif text == '📊 Статистика':
            with db.transaction() as c:
                c.execute("SELECT COUNT(*) FROM users")
                total_users = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM users WHERE role = 'rabotnik'")
                workers = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM users WHERE role = 'zakazchik'")
                customers = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM orders")
                total_orders = c.fetchone()[0] or 0
                c.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
                completed = c.fetchone()[0] or 0
                c.execute("SELECT SUM(payout) FROM assignments")
                total_payouts = c.fetchone()[0] or 0
            msg_text = f"📊 СТАТИСТИКА\n\n👥 Всего: {total_users}\n👷 Работников: {workers}\n🏢 Заказчиков: {customers}\n📦 Заказов: {total_orders}\n✅ Завершённых: {completed}\n💰 Выплачено: {total_payouts} ₽"
            safe_send(message.chat.id, msg_text)
        elif text == '⭐ Оценить работника':
            msg = safe_send(message.chat.id, "Введите ID работника:")
            bot.register_next_step_handler(msg, mod_rate_get_user)
        elif text == '⭐ Оценить заказчика':
            msg = safe_send(message.chat.id, "Введите ID заказчика:")
            bot.register_next_step_handler(msg, mod_rate_customer_get)
        elif text == '⚖️ Арбитраж':
            with db.transaction() as c:
                c.execute("SELECT id, zakazchik_name, address, status FROM orders WHERE status IN ('waiting_approval', 'waiting_payout') LIMIT 20")
                rows = c.fetchall()
            if not rows:
                safe_send(message.chat.id, "⚖️ Нет заказов для арбитража.")
                return
            msg_text = "⚖️ АРБИТРАЖ\n\n"
            for row in rows:
                msg_text += f"🆔 #{row['id']} | {row['zakazchik_name']}\n📍 {row['address']}\nСтатус: {row['status']}\n\n"
            msg_text += "Используй /arbitrate ID refund|penalty|ban"
            safe_send(message.chat.id, msg_text)
        elif text == '🔒 Блокировка':
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton("По ID"), KeyboardButton("По телефону"))
            kb.row(KeyboardButton("⬅️ Назад"))
            msg = safe_send(message.chat.id, "🔒 Выберите способ:", reply_markup=kb)
            bot.register_next_step_handler(msg, mod_block_choose_method)
        elif text == '🔓 Разблокировка':
            msg = safe_send(message.chat.id, "Введите ID пользователя:")
            bot.register_next_step_handler(msg, mod_unblock_by_id)
        elif text == '📨 Сообщения':
            unread = get_unread_messages(uid)
            if not unread:
                safe_send(message.chat.id, "📨 Нет новых сообщений.")
                return
            mark_messages_read(uid)
            msg_text = "📨 НОВЫЕ СООБЩЕНИЯ:\n\n"
            for msg in unread[:10]:
                from_user = get_user_by_id(msg['from_user_id'])
                from_name = from_user['name'] if from_user else "Неизвестный"
                order_text = f" (заказ #{msg['order_id']})" if msg['order_id'] != 0 else ""
                msg_text += f"От: {from_name}{order_text}\n{msg['text']}\n\n"
            if len(unread) > 10:
                msg_text += f"\n... и ещё {len(unread)-10} сообщений"
            safe_send(message.chat.id, msg_text)
    except Exception as e:
        logger.error(f"❌ Ошибка в moderator_commands: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")
# ========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ МОДЕРАТОРА
# ========================================

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

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    try:
        if message.from_user.id not in MODERATOR_IDS:
            safe_send(message.chat.id, "❌ Нет прав.")
            return
        parts = message.text.split()
        if len(parts) < 3:
            safe_send(message.chat.id, "❌ /arbitrate ID refund|penalty|ban")
            return
        try:
            order_id = int(parts[1])
        except:
            safe_send(message.chat.id, "❌ ID должно быть числом.")
            return
        action = parts[2].lower()
        order = get_order(order_id)
        if not order:
            safe_send(message.chat.id, "❌ Заказ не найден.")
            return
        if action == 'refund':
            update_order_status(order_id, 'cancelled')
            safe_send(message.chat.id, f"✅ Заказ #{order_id} отменён, деньги возвращены.")
        elif action == 'penalty':
            add_rating(order['zakazchik_id'], -1)
            safe_send(message.chat.id, f"✅ Заказчику #{order['zakazchik_id']} снижен рейтинг.")
        elif action == 'ban':
            with db.transaction() as c:
                c.execute("UPDATE users SET blocked = 1 WHERE id = ?", (order['zakazchik_id'],))
            safe_send(message.chat.id, f"✅ Заказчик #{order['zakazchik_id']} заблокирован.")
        else:
            safe_send(message.chat.id, "❌ Доступно: refund, penalty, ban")
    except Exception as e:
        logger.error(f"❌ Ошибка в arbitrate_command: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ========================================
# CALLBACK ОБРАБОТЧИК
# ========================================

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        if call.message is None:
            bot.answer_callback_query(call.id, "⏳ Сообщение устарело", show_alert=True)
            return
        data = call.data
        user_id = call.from_user.id
        user = get_user(user_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ Нажмите /start", show_alert=True)
            return
        if user['blocked'] == 1:
            bot.answer_callback_query(call.id, "⛔ Вы заблокированы", show_alert=True)
            return
        
        # contact_mod
        if data.startswith('contact_mod_'):
            order_id = int(data.split('_')[2])
            save_state(user_id, 'msg_to_mod', str(order_id), 60)
            bot.answer_callback_query(call.id, "📝 Напишите сообщение модератору", show_alert=False)
            safe_send(call.message.chat.id, f"📝 Напишите сообщение модератору по заказу #{order_id}:\n(для отмены отправьте /cancel)")
        
        elif data.startswith('contact_customer_order_'):
            order_id = int(data.split('_')[3])
            order = get_order(order_id)
            if order:
                save_state(user_id, 'msg_to_user', f"{order['zakazchik_id']}|{order_id}", 60)
                bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
                safe_send(call.message.chat.id, f"📝 Напишите сообщение по заказу #{order_id}:\n(для отмены отправьте /cancel)")
        
        elif data.startswith('contact_worker_order_'):
            order_id = int(data.split('_')[3])
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
            target_id = int(parts[2])
            order_id = int(parts[3]) if len(parts) > 3 else 0
            save_state(user_id, 'msg_to_user', f"{target_id}|{order_id}", 60)
            bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
            safe_send(call.message.chat.id, f"📝 Напишите сообщение:\n(для отмены отправьте /cancel)")
        
        # take
        elif data.startswith('take_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order['status'] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            if user['role'] != 'rabotnik':
                bot.answer_callback_query(call.id, "❌ Только для работников", show_alert=True)
                return
            worker_orders = get_worker_orders(user['id'])
            for wo in worker_orders:
                if wo['status'] in ['open', 'in_progress', 'ready_to_pay', 'paid', 'working']:
                    bot.answer_callback_query(call.id, f"❌ У вас уже есть активный заказ #{wo['id']}.\nЗавершите его.", show_alert=True)
                    return
            assigned = get_assignments(order_id)
            if user['id'] in [a['user_id'] for a in assigned]:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли этот заказ", show_alert=True)
                return
            with db.transaction() as c:
                c.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", (order_id, user['id'], order['payout_per_person']))
            new_assigned = get_assignments(order_id)
            total_workers = order['people']
            if len(new_assigned) >= total_workers:
                update_order_status(order_id, 'ready_to_pay')
                text = f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👥 Все {total_workers} работников собраны.\n📍 Адрес: {order['address']}\n💰 Сумма к оплате: {order['total_sum']} ₽\n💳 Переведите по СБП: {SBP_PHONE}\n\n✅ Ваши деньги в безопасности!"
                safe_send(order['zakazchik_id'], text, reply_markup=payment_kb(order_id))
                for worker_id in get_workers_for_order(order_id):
                    worker = get_user_by_id(worker_id)
                    if worker:
                        safe_send(worker['telegram_id'], f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👥 Все работники на месте.\n📍 Адрес: {order['address']}\n💰 Ваша выплата: {order['payout_per_person']} ₽")
                for m in MODERATOR_IDS:
                    safe_send(m, f"📊 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👤 Заказчик: {order['zakazchik_name']}\n📍 Адрес: {order['address']}\n👥 Работников: {total_workers}\n💰 Сумма: {order['total_sum']} ₽")
                bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} укомплектован!", show_alert=True)
            else:
                bot.answer_callback_query(call.id, f"✅ Вы взяли заказ #{order_id}!\nОсталось {total_workers - len(new_assigned)} чел.", show_alert=True)
            safe_edit(f"✅ Вы взяли заказ #{order_id}!\n\n📍 Подтвердите, что вы на месте.\n\nЕсли вы НЕ нажмёте 'Я на месте':\n❌ Заказчик не сможет оплатить\n❌ Вы не получите выплату", call.message.chat.id, call.message.message_id, reply_markup=confirm_take_kb(order_id))
        
        # confirm_place
        elif data.startswith('confirm_place_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] not in ['open', 'in_progress', 'ready_to_pay']:
                bot.answer_callback_query(call.id, "❌ Заказ уже не в этой стадии", show_alert=True)
                return
            confirm_worker_on_place(order_id, user['id'])
            bot.answer_callback_query(call.id, "✅ Вы подтвердили, что на месте!", show_alert=True)
            safe_edit(f"✅ Вы подтвердили, что на месте!\n\n💰 Ваша выплата: {order['payout_per_person']} ₽", call.message.chat.id, call.message.message_id)
            assigned = get_assignments(order_id)
            all_confirmed = all(a['confirmed'] == 1 for a in assigned)
            if all_confirmed and order['status'] == 'open':
                update_order_status(order_id, 'ready_to_pay')
                text = f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👥 Все работники подтвердили, что они на месте.\n📍 Адрес: {order['address']}\n💰 Сумма к оплате: {order['total_sum']} ₽\n💳 Переведите по СБП: {SBP_PHONE}\n\n✅ Ваши деньги в безопасности!"
                safe_send(order['zakazchik_id'], text, reply_markup=payment_kb(order_id))
                for worker_id in get_workers_for_order(order_id):
                    worker = get_user_by_id(worker_id)
                    if worker:
                        safe_send(worker['telegram_id'], f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👥 Все работники на месте.\n📍 Адрес: {order['address']}\n💰 Ваша выплата: {order['payout_per_person']} ₽")
                for m in MODERATOR_IDS:
                    safe_send(m, f"📊 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n👤 Заказчик: {order['zakazchik_name']}\n📍 Адрес: {order['address']}\n👥 Работников: {order['people']}\n💰 Сумма: {order['total_sum']} ₽")
        
        # cancel_take
        elif data.startswith('cancel_take_'):
            order_id = int(data.split('_')[2])
            with db.transaction() as c:
                c.execute("DELETE FROM assignments WHERE order_id = ? AND user_id = ?", (order_id, user['id']))
            bot.answer_callback_query(call.id, "❌ Вы отказались от заказа", show_alert=True)
            safe_edit("❌ Вы отказались от заказа", call.message.chat.id, call.message.message_id)
        
        # i_paid
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
            safe_edit(f"✅ Вы подтвердили оплату заказа #{order_id}!\n\n📌 Ожидайте подтверждения от сервиса.", call.message.chat.id, call.message.message_id)
            for m in MODERATOR_IDS:
                safe_send(m, f"💰 ЗАКАЗ #{order_id} ОПЛАЧЕН!\n\n👤 Заказчик: {order['zakazchik_name']}\n📍 Адрес: {order['address']}\n💰 Сумма: {order['total_sum']} ₽\n\n📌 Подтвердите оплату:", reply_markup=moderator_payment_kb(order_id))
        
        # confirm_payment
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
            bot.answer_callback_query(call.id, f"✅ Оплата заказа #{order_id} подтверждена!", show_alert=True)
            safe_edit(f"✅ Оплата заказа #{order_id} подтверждена!", call.message.chat.id, call.message.message_id)
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"✅ ЗАКАЗ #{order_id} ОПЛАЧЕН!\n\n💰 Ваша выплата: {order['payout_per_person']} ₽\n📍 Адрес: {order['address']}\n⏱ Часы: {order['hours']} ч.\n\n📸 После выполнения отправьте фото:", reply_markup=worker_photo_kb(order_id))
            safe_send(order['zakazchik_id'], f"✅ ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН!\n\n📍 Адрес: {order['address']}\n⏱ Часы: {order['hours']} ч.\n👥 Работников: {order['people']}")
        
        # send_photo
        elif data.startswith('send_photo_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order['status'] != 'working':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе работы", show_alert=True)
                return
            assigned = get_assignments(order_id)
            if user['id'] not in [a['user_id'] for a in assigned]:
                bot.answer_callback_query(call.id, "❌ Вы не взяли этот заказ", show_alert=True)
                return
            bot.answer_callback_query(call.id, "📸 Отправьте фото выполненной работы", show_alert=True)
            save_state(user['id'], f'waiting_photo_{order_id}', '{}', 60)
            safe_send(call.message.chat.id, f"📸 Отправьте фото выполненной работы для заказа #{order_id}")
        
        # approve
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
                safe_send(m, f"✅ ЗАКАЗ #{order_id} ВЫПОЛНЕН!\n\n👤 Заказчик подтвердил выполнение.\n📍 Адрес: {order['address']}\n💰 Сумма: {order['total_sum']} ₽\n💵 Выплата: {order['payout_per_person']} ₽/чел\n\n📌 Переведите деньги работникам:", reply_markup=moderator_payout_kb(order_id))
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"✅ Заказ #{order_id} одобрен заказчиком!\n\n💵 Ваша выплата: {order['payout_per_person']} ₽")
        
        # reject
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
            safe_edit(f"❌ Работа по заказу #{order_id} отклонена.\n\n📌 Свяжитесь с модератором.", call.message.chat.id, call.message.message_id)
            for m in MODERATOR_IDS:
                safe_send(m, f"❌ ЗАКАЗ #{order_id} ОТКЛОНЁН!\n\n👤 Заказчик: {order['zakazchik_name']}\n📍 Адрес: {order['address']}")
        
        # confirm_payout
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
            bot.answer_callback_query(call.id, f"✅ Выплата подтверждена!", show_alert=True)
            safe_edit(f"✅ Выплата по заказу #{order_id} подтверждена!", call.message.chat.id, call.message.message_id)
            safe_send(order['zakazchik_id'], f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n\n💰 Работники получили оплату.")
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n\n💵 Вы получили выплату: {order['payout_per_person']} ₽")
        
        # cancel
        elif data.startswith('cancel_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order['zakazchik_id'] != user['id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            if user['role'] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            if order['status'] not in ['open', 'in_progress', 'ready_to_pay']:
                bot.answer_callback_query(call.id, "❌ Нельзя отменить", show_alert=True)
                return
            update_order_status(order_id, 'cancelled')
            bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} отменён!", show_alert=True)
            safe_edit(f"❌ ЗАКАЗ #{order_id} ОТМЕНЁН", call.message.chat.id, call.message.message_id)
            for worker_id in get_workers_for_order(order_id):
                worker = get_user_by_id(worker_id)
                if worker:
                    safe_send(worker['telegram_id'], f"❌ Заказ #{order_id} отменён заказчиком.")
            for m in MODERATOR_IDS:
                safe_send(m, f"❌ Заказ #{order_id} отменён заказчиком")
        
        # complete
        elif data.startswith('complete_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order['zakazchik_id'] != user['id']:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            if user['role'] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
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
            safe_edit(f"📸 Заказ #{order_id} выполнен!\n\n✅ Подтвердите, что работа выполнена качественно:", call.message.chat.id, call.message.message_id, reply_markup=approve_kb(order_id))
        else:
            bot.answer_callback_query(call.id, "❌ Неизвестная команда", show_alert=True)
    except Exception as e:
        logger.error(f"❌ Ошибка в callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# ========================================
# ОБРАБОТЧИК ФОТО
# ========================================

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
            safe_send(message.chat.id, "❌ Нет активного запроса на фото.\nИспользуйте кнопку '📸 Отправить фото'.")
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
                safe_send(order['zakazchik_id'], f"📸 Все работники отправили фото по заказу #{order_id}!\n\n✅ Подтвердите выполнение:", reply_markup=approve_kb(order_id))
                if order['status'] == 'working':
                    update_order_status(order_id, 'waiting_approval')
                    for m in MODERATOR_IDS:
                        safe_send(m, f"📸 Все работники отправили фото по заказу #{order_id}!\n\n👤 Заказчик: {order['zakazchik_name']}\n📍 Адрес: {order['address']}")
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_photo: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ========================================
# ОТПРАВКА СООБЩЕНИЙ
# ========================================

@bot.message_handler(commands=['cancel'])
def cancel_message(message):
    try:
        clear_state(message.from_user.id)
        safe_send(message.chat.id, "❌ Отправка сообщения отменена.", reply_markup=get_main_kb(message.from_user.id))
    except Exception as e:
        logger.error(f"❌ Ошибка в cancel_message: {e}")
        safe_send(message.chat.id, "❌ Ошибка.")

@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    try:
        uid = message.from_user.id
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
            # Обрабатывается в handle_photo
            pass
        else:
            user = get_user(uid)
            if user:
                if user['role'] == 'rabotnik':
                    safe_send(message.chat.id, "👷 Меню работника:", reply_markup=get_worker_kb())
                elif user['role'] == 'zakazchik':
                    safe_send(message.chat.id, "🏢 Меню заказчика:", reply_markup=get_customer_kb())
                elif user['role'] == 'moderator' and uid in MODERATOR_IDS:
                    safe_send(message.chat.id, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_user_message: {e}")
        safe_send(message.chat.id, "❌ Ошибка. Попробуйте позже.")

# ========================================
# БЛОКИРОВАННЫЙ
# ========================================

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

# ========================================
# FALLBACK
# ========================================

@bot.message_handler(func=lambda m: True)
def fallback(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            safe_send(message.chat.id, "Нажмите /start для начала работы.", reply_markup=get_main_kb(uid))
            return
        if user['role'] == 'moderator' and uid in MODERATOR_IDS:
            safe_send(message.chat.id, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
        elif user['role'] == 'rabotnik':
            safe_send(message.chat.id, "👷 Меню работника:", reply_markup=get_worker_kb())
        elif user['role'] == 'zakazchik':
            safe_send(message.chat.id, "🏢 Меню заказчика:", reply_markup=get_customer_kb())
        else:
            safe_send(message.chat.id, "Используйте кнопки меню.", reply_markup=get_main_kb(uid))
    except Exception as e:
        logger.error(f"❌ Ошибка в fallback: {e}")
        safe_send(message.chat.id, "Используйте кнопки меню.", reply_markup=get_main_kb(None))

# ========================================
# ЗАПУСК С АВТОПЕРЕЗАПУСКОМ
# ========================================

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
            continue

if __name__ == "__main__":
    start_bot()
