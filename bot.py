import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime
import threading
import time
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'

# ========== СПИСОК МОДЕРАТОРОВ ==========
# Добавь сюда ID всех модераторов (твой и напарника)
MODERATOR_IDS = [
    8746212340,  # Твой ID
    # 123456789,  # ID напарника - добавь сюда
]

bot = telebot.TeleBot(TOKEN)

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
            self.conn = sqlite3.connect('rabota.db', check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
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
                created_at TEXT
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                user_id INTEGER,
                payout INTEGER
            )''')
            
            self.conn.commit()
            logging.info("✅ База данных инициализирована")
        except Exception as e:
            logging.error(f"❌ Ошибка инициализации БД: {e}")
    
    def execute(self, query, params=()):
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            return cursor
        except Exception as e:
            logging.error(f"Ошибка execute: {e}")
            return None
    
    def commit(self):
        try:
            self.conn.commit()
        except Exception as e:
            logging.error(f"Ошибка commit: {e}")

db = Database()

# ========== ФУНКЦИИ РАБОТЫ С БД ==========
def get_user(telegram_id):
    try:
        c = db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        if c is None:
            return None
        row = c.fetchone()
        if row:
            return [
                row['id'], row['telegram_id'], row['name'], row['phone'], 
                row['bank'], row['initials'], row['role'], row['rating'], 
                row['customer_rating'], row['on_shift'], row['agreement_accepted'], 
                row['blocked']
            ]
        return None
    except Exception as e:
        logging.error(f"Ошибка get_user: {e}")
        return None

def get_user_by_id(user_id):
    try:
        c = db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        if c is None:
            return None
        row = c.fetchone()
        if row:
            return [
                row['id'], row['telegram_id'], row['name'], row['phone'], 
                row['bank'], row['initials'], row['role'], row['rating'], 
                row['customer_rating'], row['on_shift'], row['agreement_accepted'], 
                row['blocked']
            ]
        return None
    except Exception as e:
        logging.error(f"Ошибка get_user_by_id: {e}")
        return None

def update_user(telegram_id, field, value):
    try:
        db.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка update_user: {e}")
        return False

def get_order(order_id):
    try:
        c = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        if c is None:
            return None
        row = c.fetchone()
        if row:
            return [
                row['id'], row['zakazchik_id'], row['zakazchik_name'], 
                row['address'], row['hours'], row['people'], 
                row['total_sum'], row['commission'], row['payout_per_person'], 
                row['status'], row['created_at']
            ]
        return None
    except Exception as e:
        logging.error(f"Ошибка get_order: {e}")
        return None

def get_open_orders():
    try:
        c = db.execute("SELECT id, payout_per_person FROM orders WHERE status = 'open' ORDER BY created_at DESC")
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['payout_per_person']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_open_orders: {e}")
        return []

def get_assignments(order_id):
    try:
        c = db.execute("SELECT user_id FROM assignments WHERE order_id = ?", (order_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [row['user_id'] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_assignments: {e}")
        return []

def get_workers():
    try:
        c = db.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND on_shift = 1 AND blocked = 0")
        if c is None:
            return []
        rows = c.fetchall()
        return [row['telegram_id'] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_workers: {e}")
        return []

def cancel_order(order_id):
    try:
        db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'open'", (order_id,))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка cancel_order: {e}")
        return False

def add_rating(user_id, delta):
    try:
        db.execute("UPDATE users SET rating = rating + ? WHERE id = ?", (delta, user_id))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка add_rating: {e}")
        return False

def rate_customer(customer_id, delta):
    try:
        db.execute("UPDATE users SET customer_rating = customer_rating + ? WHERE id = ?", (delta, customer_id))
        db.commit()
        c = db.execute("SELECT customer_rating, telegram_id FROM users WHERE id = ?", (customer_id,))
        if c:
            row = c.fetchone()
            if row:
                return [row['customer_rating'], row['telegram_id']]
        return None
    except Exception as e:
        logging.error(f"Ошибка rate_customer: {e}")
        return None

def block_user_by_phone(phone):
    try:
        db.execute("UPDATE users SET blocked = 1 WHERE phone = ?", (phone,))
        db.commit()
        return 1
    except Exception as e:
        logging.error(f"Ошибка block_user_by_phone: {e}")
        return 0

def get_all_workers():
    try:
        c = db.execute("SELECT id, name, phone, rating, blocked, on_shift FROM users WHERE role = 'rabotnik' ORDER BY rating DESC")
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['name'], row['phone'], row['rating'], row['blocked'], row['on_shift']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_all_workers: {e}")
        return []

def get_all_customers():
    try:
        c = db.execute("SELECT id, name, phone, customer_rating, blocked FROM users WHERE role = 'zakazchik' ORDER BY customer_rating DESC")
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['name'], row['phone'], row['customer_rating'], row['blocked']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_all_customers: {e}")
        return []

def get_customer_orders_with_details(zakazchik_id):
    try:
        c = db.execute("""SELECT o.id, o.total_sum, o.status, o.payout_per_person, o.people,
                            COUNT(a.user_id) as taken
                     FROM orders o
                     LEFT JOIN assignments a ON o.id = a.order_id
                     WHERE o.zakazchik_id = ?
                     GROUP BY o.id
                     ORDER BY o.created_at DESC""", (zakazchik_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['total_sum'], row['status'], row['payout_per_person'], row['people'], row['taken']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_customer_orders_with_details: {e}")
        return []

def get_worker_orders(user_id):
    try:
        c = db.execute('''SELECT o.id, o.status, a.payout, o.zakazchik_name, o.address
                     FROM assignments a 
                     JOIN orders o ON a.order_id = o.id 
                     WHERE a.user_id = ?
                     ORDER BY o.created_at DESC''', (user_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['status'], row['payout'], row['zakazchik_name'], row['address']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_worker_orders: {e}")
        return []

# ========== КЛАВИАТУРЫ ==========
_main_kb = None
_worker_kb = None
_customer_kb = None
_moderator_kb = None
_blocked_kb = None

def get_main_kb(telegram_id=None):
    global _main_kb
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    
    if telegram_id and telegram_id in MODERATOR_IDS:
        kb.row(KeyboardButton("🛡️ Я модератор"))
    
    _main_kb = kb
    return _main_kb

def get_worker_kb():
    global _worker_kb
    if _worker_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
        kb.row(KeyboardButton("🔄 Сменить смену"), KeyboardButton("⬅️ Назад"))
        _worker_kb = kb
    return _worker_kb

def get_customer_kb():
    global _customer_kb
    if _customer_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📝 Создать заказ"))
        kb.row(KeyboardButton("📋 Мои заказы"), KeyboardButton("👤 Профиль"))
        kb.row(KeyboardButton("⚠️ Пожаловаться"), KeyboardButton("⬅️ Назад"))
        _customer_kb = kb
    return _customer_kb

def get_moderator_kb():
    global _moderator_kb
    if _moderator_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
        kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
        kb.row(KeyboardButton("🏢 Заказчики"), KeyboardButton("📊 Статистика"))
        kb.row(KeyboardButton("⭐ Оценить работника"), KeyboardButton("⭐ Оценить заказчика"))
        kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блокировка"))
        kb.row(KeyboardButton("🔓 Разблокировка"), KeyboardButton("⬅️ Назад"))
        _moderator_kb = kb
    return _moderator_kb

def get_blocked_kb():
    global _blocked_kb
    if _blocked_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📞 Связь с модератором"))
        _blocked_kb = kb
    return _blocked_kb

def order_inline_kb(order_id, is_customer=False):
    kb = InlineKeyboardMarkup()
    if is_customer:
        kb.add(InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{order_id}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{order_id}"))
    return kb

def confirm_take_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_take_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_take"))
    return kb

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
reg_data = {}
order_data = {}

# ========== ОБРАБОТЧИКИ СООБЩЕНИЙ ==========

@bot.message_handler(commands=['start'])
def start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            db.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (uid,))
            db.commit()
            bot.reply_to(message, "👋 Добро пожаловать в бот Юрга-Подработка!\n\nВыберите свою роль:", reply_markup=get_main_kb(uid))
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Ваш аккаунт заблокирован модератором.\nДля связи нажмите кнопку ниже:", reply_markup=get_blocked_kb())
            return
        
        role = user[6]
        if role == 'rabotnik':
            status = "на смене 🟢" if user[9] else "не на смене 🔴"
            bot.reply_to(message, f"👷 Меню работника\n\nСтатус: {status}", reply_markup=get_worker_kb())
        elif role == 'zakazchik':
            bot.reply_to(message, "🏢 Меню заказчика", reply_markup=get_customer_kb())
        elif role == 'moderator':
            bot.reply_to(message, "🛡️ Панель модератора", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "👋 Выберите роль:", reply_markup=get_main_kb(uid))
    except Exception as e:
        logging.error(f"Ошибка в start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "❌ Нажмите /start")
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        role_map = {'👷 Я работник': 'rabotnik', '🏢 Я заказчик': 'zakazchik', '🛡️ Я модератор': 'moderator'}
        role = role_map[message.text]
        
        if role == 'moderator' and uid not in MODERATOR_IDS:
            bot.reply_to(message, "❌ У вас нет прав модератора.")
            return
        
        update_user(uid, 'role', role)
        
        if role == 'rabotnik':
            bot.reply_to(message, "✅ Роль работника выбрана!", reply_markup=get_worker_kb())
        elif role == 'zakazchik':
            bot.reply_to(message, "✅ Роль заказчика выбрана!", reply_markup=get_customer_kb())
        else:
            bot.reply_to(message, "✅ Добро пожаловать в панель модератора!", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в role_choice: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back_to_main(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if user and user[6] == 'moderator' and uid in MODERATOR_IDS:
            bot.reply_to(message, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "📱 Главное меню:", reply_markup=get_main_kb(uid))
    except Exception as e:
        logging.error(f"Ошибка в back_to_main: {e}")
        bot.reply_to(message, "❌ Ошибка.", reply_markup=get_main_kb(None))

# ========== РЕГИСТРАЦИЯ ==========
@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def reg_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "❌ Нажмите /start")
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        if user[10] == 1:
            bot.reply_to(message, "✅ Вы уже зарегистрированы!")
            return
        
        role = user[6]
        if role not in ('rabotnik', 'zakazchik'):
            bot.reply_to(message, "❌ Сначала выберите роль через главное меню.")
            return
        
        reg_data[uid] = {}
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("✅ Принимаю"), KeyboardButton("❌ Отмена"))
        bot.send_message(message.chat.id,
            "📜 УСЛОВИЯ СЕРВИСА\n\n"
            "1. Сервис - посредник между заказчиками и работниками\n"
            "2. Гарантируем выплату работникам при выполнении заказа\n"
            "3. Гарантируем возврат денег заказчикам при неявке работников\n"
            "4. Сервис не отвечает за качество работы, травмы, кражи\n"
            "5. Оплата наличными отменяет все гарантии\n\n"
            "✅ Принимаете условия?", reply_markup=kb)
    except Exception as e:
        logging.error(f"Ошибка в reg_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text in ['✅ Принимаю', '❌ Отмена'])
def handle_agreement(message):
    try:
        uid = message.from_user.id
        
        if message.text == '❌ Отмена':
            bot.reply_to(message, "❌ Регистрация отменена.", reply_markup=get_main_kb(uid))
            if uid in reg_data:
                del reg_data[uid]
            return
        
        user = get_user(uid)
        if not user:
            bot.reply_to(message, "❌ Нажмите /start")
            return
        
        update_user(uid, 'agreement_accepted', 1)
        role = user[6]
        
        if role == 'rabotnik':
            msg = bot.reply_to(message, "📝 Введите ваше ФИО (например: Иванов Иван Иванович):")
            bot.register_next_step_handler(msg, get_worker_name, uid)
        else:
            msg = bot.reply_to(message, "📝 Введите ваше ФИО (например: Иванов Иван Иванович):")
            bot.register_next_step_handler(msg, get_customer_name, uid)
    except Exception as e:
        logging.error(f"Ошибка в handle_agreement: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_worker_name(message, uid):
    try:
        reg_data[uid]['name'] = message.text
        msg = bot.reply_to(message, "📞 Введите номер телефона (в формате +7XXXXXXXXXX):")
        bot.register_next_step_handler(msg, get_worker_phone, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_worker_name: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_worker_phone(message, uid):
    try:
        reg_data[uid]['phone'] = message.text
        msg = bot.reply_to(message, "💳 Введите реквизиты карты для выплат (номер карты):")
        bot.register_next_step_handler(msg, get_worker_bank, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_worker_phone: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_worker_bank(message, uid):
    try:
        reg_data[uid]['bank'] = message.text
        msg = bot.reply_to(message, "📝 Введите инициалы (например: Иванов И.И.):")
        bot.register_next_step_handler(msg, finish_worker_reg, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_worker_bank: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def finish_worker_reg(message, uid):
    try:
        db.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
                  (reg_data[uid]['name'], reg_data[uid]['phone'], reg_data[uid]['bank'], message.text, uid))
        db.commit()
        del reg_data[uid]
        bot.reply_to(message, "✅ Регистрация завершена! Вы на смене 🟢", reply_markup=get_worker_kb())
    except Exception as e:
        logging.error(f"Ошибка в finish_worker_reg: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_customer_name(message, uid):
    try:
        reg_data[uid]['name'] = message.text
        msg = bot.reply_to(message, "📞 Введите номер телефона (в формате +7XXXXXXXXXX):")
        bot.register_next_step_handler(msg, get_customer_phone, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_customer_name: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_customer_phone(message, uid):
    try:
        reg_data[uid]['phone'] = message.text
        finish_customer_reg(message, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_customer_phone: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def finish_customer_reg(message, uid):
    try:
        db.execute("UPDATE users SET name=?, phone=? WHERE telegram_id=?",
                  (reg_data[uid]['name'], reg_data[uid]['phone'], uid))
        db.commit()
        del reg_data[uid]
        bot.reply_to(message, "✅ Регистрация завершена! Можете создавать заказы.", reply_markup=get_customer_kb())
    except Exception as e:
        logging.error(f"Ошибка в finish_customer_reg: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== РАБОТНИК ==========

@bot.message_handler(func=lambda m: m.text == '🔄 Сменить смену')
def toggle_shift(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        if user[10] == 0:
            bot.reply_to(message, "❌ Пройдите регистрацию.")
            return
        
        current_shift = user[9]
        new_shift = 0 if current_shift == 1 else 1
        update_user(uid, 'on_shift', new_shift)
        
        status = "на смене 🟢" if new_shift == 1 else "не на смене 🔴"
        bot.reply_to(message, f"🔄 Статус смены изменён!\n\nВы {status}", reply_markup=get_worker_kb())
    except Exception as e:
        logging.error(f"Ошибка в toggle_shift: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        if user[10] == 0:
            bot.reply_to(message, "❌ Пройдите регистрацию.")
            return
        
        orders = get_open_orders()
        if not orders:
            bot.reply_to(message, "📭 Нет свободных заказов.")
            return
        
        for o in orders:
            order = get_order(o[0])
            if not order:
                continue
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"💵 Выплата: {o[1]} ₽\n"
                f"📍 Адрес: {order[3]}\n"
                f"⏱ Часы: {order[4]} ч.\n"
                f"👥 Нужно: {order[5]} чел.\n"
                f"📊 Статус: {'🟢 Открыт' if order[9] == 'open' else '🟡 В работе'}"
            )
            bot.send_message(
                message.chat.id,
                text,
                reply_markup=order_inline_kb(o[0], is_customer=False)
            )
    except Exception as e:
        logging.error(f"Ошибка в free_orders: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            return
        
        orders = get_worker_orders(user[0])
        if not orders:
            bot.reply_to(message, "💰 У вас пока нет выплат.")
            return
        
        total = 0
        text = "💰 ВАШИ ВЫПЛАТЫ:\n\n"
        for o in orders:
            status_map = {'open': '🟢 Ожидает', 'in_progress': '🟡 В работе', 'completed': '✅ Выплачено', 'cancelled': '❌ Отменён'}
            text += f"Заказ #{o[0]}: {o[2]}₽, {status_map.get(o[1], o[1])}\n"
            if o[1] == 'completed':
                total += o[2]
        
        text += f"\n💰 Итого выплачено: {total}₽"
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Ошибка в my_payouts: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '👤 Профиль')
def profile(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        role_names = {'rabotnik': '👷 Работник', 'zakazchik': '🏢 Заказчик', 'moderator': '🛡️ Модератор'}
        text = (
            f"👤 ПРОФИЛЬ\n\n"
            f"Имя: {user[2] or 'не указано'}\n"
            f"Телефон: {user[3] or 'не указан'}\n"
            f"Роль: {role_names.get(user[6], user[6])}\n"
            f"Рейтинг: {user[7]}\n"
            f"Соглашение: {'✅ Да' if user[10] else '❌ Нет'}\n"
            f"Блокировка: {'🔒 Да' if user[11] else '✅ Нет'}"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Ошибка в profile: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ЗАКАЗЧИК ==========
@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        if user[10] == 0:
            bot.reply_to(message, "❌ Пройдите регистрацию.")
            return
        
        order_data[uid] = {}
        msg = bot.reply_to(message, "📍 Введите адрес выполнения работы:")
        bot.register_next_step_handler(msg, get_order_address, uid)
    except Exception as e:
        logging.error(f"Ошибка в create_order_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_order_address(message, uid):
    try:
        order_data[uid]['address'] = message.text
        msg = bot.reply_to(message, "⏱ Введите количество часов (число):")
        bot.register_next_step_handler(msg, get_order_hours, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_order_address: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_order_hours(message, uid):
    try:
        hours = int(message.text)
        if hours <= 0:
            raise ValueError("Часы должны быть > 0")
        order_data[uid]['hours'] = hours
        msg = bot.reply_to(message, "👥 Введите количество человек:")
        bot.register_next_step_handler(msg, get_order_people, uid)
    except ValueError:
        bot.reply_to(message, "❌ Введите положительное число.")
        msg = bot.reply_to(message, "⏱ Введите количество часов (число):")
        bot.register_next_step_handler(msg, get_order_hours, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_order_hours: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_order_people(message, uid):
    try:
        people = int(message.text)
        if people <= 0:
            raise ValueError("Количество должно быть > 0")
        
        user = get_user(uid)
        if not user:
            bot.reply_to(message, "❌ Пользователь не найден.")
            return
        
        hours = order_data[uid]['hours']
        
        # Расчёт сумм
        total = hours * people * 500
        commission = hours * people * 50
        payout = (total - commission) // people
        
        name = user[2] if user[2] else "Заказчик"
        address = order_data[uid]['address']
        
        conn = db.conn
        c = conn.cursor()
        c.execute('''INSERT INTO orders 
                     (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user[0], name, address, hours, people, total, commission, payout, datetime.now().isoformat()))
        conn.commit()
        order_id = c.lastrowid
        
        del order_data[uid]
        
        # ========== ЗАКАЗЧИКУ - БЕЗ СУММЫ ВЫПЛАТЫ ==========
        bot.reply_to(
            message, 
            f"✅ ЗАКАЗ #{order_id} СОЗДАН!\n\n"
            f"💰 Сумма к оплате: {total} ₽\n"
            f"🙏 Работникам будет выплачено\n"
            f"📍 Адрес: {address}\n"
            f"⏱ Часы: {hours} ч.\n"
            f"👥 Человек: {people}",
            reply_markup=get_customer_kb()
        )
        
        # ========== РАБОТНИКАМ - ТОЛЬКО ВЫПЛАТА ==========
        workers = get_workers()
        if workers:
            text = (
                f"🔔 НОВЫЙ ЗАКАЗ!\n"
                f"🆔 #{order_id}\n"
                f"💵 Выплата: {payout} ₽\n"
                f"📍 Адрес: {address}\n"
                f"⏱ Часы: {hours} ч.\n"
                f"👥 Нужно: {people} чел."
            )
            for w in workers:
                try:
                    bot.send_message(w, text)
                except Exception as e:
                    logging.error(f"Ошибка отправки уведомления работнику {w}: {e}")
        
        # ========== МОДЕРАТОРАМ - ПОЛНАЯ ИНФОРМАЦИЯ С КОМИССИЕЙ ==========
        for m in MODERATOR_IDS:
            try:
                bot.send_message(
                    m,
                    f"📊 НОВЫЙ ЗАКАЗ #{order_id}\n\n"
                    f"👤 Заказчик: {name} (ID {user[0]})\n"
                    f"📍 Адрес: {address}\n"
                    f"⏱ Часы: {hours} ч.\n"
                    f"👥 Человек: {people}\n"
                    f"💰 Сумма: {total} ₽\n"
                    f"📊 Комиссия сервиса: {commission} ₽\n"
                    f"💵 Выплата работнику: {payout} ₽/чел\n"
                    f"📊 Итого к выплате: {payout * people} ₽"
                )
            except:
                pass
                
    except ValueError:
        bot.reply_to(message, "❌ Введите положительное число.")
        msg = bot.reply_to(message, "👥 Введите количество человек:")
        bot.register_next_step_handler(msg, get_order_people, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_order_people: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_customer(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            return
        
        orders = get_customer_orders_with_details(user[0])
        if not orders:
            bot.reply_to(message, "📭 У вас нет заказов.")
            return
        
        status_map = {
            'open': '🟢 Открыт',
            'in_progress': '🟡 В работе',
            'completed': '✅ Завершён',
            'cancelled': '❌ Отменён'
        }
        
        for o in orders:
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"💰 Сумма: {o[1]} ₽\n"
                f"📊 Статус: {status_map.get(o[2], o[2])}\n"
                f"👥 Работников: {o[5]}/{o[4]}"
            )
            
            if o[2] in ('open', 'in_progress'):
                bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=order_inline_kb(o[0], is_customer=True)
                )
            else:
                bot.send_message(message.chat.id, text)
    except Exception as e:
        logging.error(f"Ошибка в my_orders_customer: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            return
        
        msg = bot.reply_to(message, "📝 Опишите вашу жалобу:")
        bot.register_next_step_handler(msg, send_complaint, uid)
    except Exception as e:
        logging.error(f"Ошибка в complain: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def send_complaint(message, uid):
    try:
        user = get_user(uid)
        text = f"⚠️ ЖАЛОБА\n\nОт: {user[2] or 'без имени'} (ID {uid})\nТелефон: {user[3] or 'не указан'}\n\n{message.text}"
        
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, text)
            except:
                pass
        
        bot.reply_to(message, "✅ Жалоба отправлена модератору.", reply_markup=get_customer_kb())
    except Exception as e:
        logging.error(f"Ошибка в send_complaint: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== МОДЕРАТОР ==========
@bot.message_handler(func=lambda m: m.text == '💰 Выплаты' and m.from_user.id in MODERATOR_IDS)
def mod_payouts(message):
    try:
        c = db.execute("SELECT SUM(payout) FROM assignments")
        if c:
            total = c.fetchone()[0] or 0
        else:
            total = 0
            
        c = db.execute("SELECT COUNT(*) FROM assignments")
        if c:
            count = c.fetchone()[0] or 0
        else:
            count = 0
        
        bot.reply_to(
            message,
            f"💰 СТАТИСТИКА ВЫПЛАТ\n\n"
            f"💵 Всего выплачено: {total} ₽\n"
            f"👥 Количество выплат: {count}"
        )
    except Exception as e:
        logging.error(f"Ошибка в mod_payouts: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🟡 Активные' and m.from_user.id in MODERATOR_IDS)
def mod_active(message):
    try:
        c = db.execute("SELECT * FROM orders WHERE status IN ('open', 'in_progress') ORDER BY created_at DESC")
        if c is None:
            bot.reply_to(message, "🟡 Нет активных заказов.")
            return
        rows = c.fetchall()
        
        if not rows:
            bot.reply_to(message, "🟡 Нет активных заказов.")
            return
        
        for row in rows:
            text = (
                f"🆔 Заказ #{row['id']}\n"
                f"👤 Заказчик: {row['zakazchik_name']}\n"
                f"📍 Адрес: {row['address']}\n"
                f"⏱ Часы: {row['hours']}, 👥 {row['people']} чел.\n"
                f"💰 Сумма: {row['total_sum']} ₽\n"
                f"📊 Комиссия: {row['commission']} ₽\n"
                f"💵 Выплата: {row['payout_per_person']} ₽/чел\n"
                f"📊 Статус: {'🟢 Открыт' if row['status'] == 'open' else '🟡 В работе'}"
            )
            bot.send_message(message.chat.id, text)
    except Exception as e:
        logging.error(f"Ошибка в mod_active: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '✅ Завершённые' and m.from_user.id in MODERATOR_IDS)
def mod_completed(message):
    try:
        c = db.execute("SELECT * FROM orders WHERE status = 'completed' ORDER BY created_at DESC")
        if c is None:
            bot.reply_to(message, "✅ Нет завершённых заказов.")
            return
        rows = c.fetchall()
        
        if not rows:
            bot.reply_to(message, "✅ Нет завершённых заказов.")
            return
        
        for row in rows:
            text = (
                f"✅ Заказ #{row['id']}\n"
                f"👤 Заказчик: {row['zakazchik_name']}\n"
                f"📍 Адрес: {row['address']}\n"
                f"⏱ Часы: {row['hours']}, 👥 {row['people']} чел.\n"
                f"💰 Сумма: {row['total_sum']} ₽\n"
                f"📊 Комиссия: {row['commission']} ₽\n"
                f"💵 Выплата: {row['payout_per_person']} ₽/чел"
            )
            bot.send_message(message.chat.id, text)
    except Exception as e:
        logging.error(f"Ошибка в mod_completed: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '👥 Работники' and m.from_user.id in MODERATOR_IDS)
def mod_workers(message):
    try:
        workers = get_all_workers()
        if not workers:
            bot.reply_to(message, "👥 Нет работников.")
            return
        
        text = "👥 СПИСОК РАБОТНИКОВ:\n\n"
        for w in workers[:20]:
            status = "🟢" if w[5] else "🔴"
            block = "🔒" if w[4] else "✅"
            text += f"{status} {block} ID {w[0]}: {w[1]}\n"
            text += f"   📞 {w[2]}, ⭐ {w[3]}\n"
        
        if len(workers) > 20:
            text += f"\n... и ещё {len(workers)-20} работников"
        
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Ошибка в mod_workers: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🏢 Заказчики' and m.from_user.id in MODERATOR_IDS)
def mod_customers(message):
    try:
        customers = get_all_customers()
        if not customers:
            bot.reply_to(message, "🏢 Нет заказчиков.")
            return
        
        text = "🏢 СПИСОК ЗАКАЗЧИКОВ:\n\n"
        for c in customers[:20]:
            block = "🔒" if c[4] else "✅"
            text += f"{block} ID {c[0]}: {c[1]}\n"
            text += f"   📞 {c[2]}, ⭐ {c[3]}\n"
        
        if len(customers) > 20:
            text += f"\n... и ещё {len(customers)-20} заказчиков"
        
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Ошибка в mod_customers: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📊 Статистика' and m.from_user.id in MODERATOR_IDS)
def mod_stats(message):
    try:
        c = db.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM users WHERE role = 'rabotnik'")
        workers = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM users WHERE role = 'zakazchik'")
        customers = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM orders")
        total_orders = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
        completed = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'open'")
        open_orders = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'in_progress'")
        in_progress = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'cancelled'")
        cancelled = c.fetchone()[0] if c else 0
        
        c = db.execute("SELECT SUM(payout) FROM assignments")
        total_payouts = c.fetchone()[0] if c else 0
        if total_payouts is None:
            total_payouts = 0
        
        c = db.execute("SELECT SUM(commission) FROM orders WHERE status = 'completed'")
        total_commission = c.fetchone()[0] if c else 0
        if total_commission is None:
            total_commission = 0
        
        text = (
            f"📊 СТАТИСТИКА\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"👷 Работников: {workers}\n"
            f"🏢 Заказчиков: {customers}\n\n"
            f"📦 Всего заказов: {total_orders}\n"
            f"🟢 Открытых: {open_orders}\n"
            f"🟡 В работе: {in_progress}\n"
            f"✅ Завершённых: {completed}\n"
            f"❌ Отменённых: {cancelled}\n\n"
            f"💰 Выплачено: {total_payouts} ₽\n"
            f"📊 Комиссия собрана: {total_commission} ₽"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Ошибка в mod_stats: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить работника' and m.from_user.id in MODERATOR_IDS)
def mod_rate_start(message):
    try:
        msg = bot.reply_to(message, "Введите ID работника (число):")
        bot.register_next_step_handler(msg, mod_rate_get_user)
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_get_user(message):
    try:
        try:
            user_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        
        c = db.execute("SELECT id, name, rating FROM users WHERE id = ? AND role = 'rabotnik'", (user_id,))
        if c is None:
            bot.reply_to(message, "❌ Работник не найден.", reply_markup=get_moderator_kb())
            return
        row = c.fetchone()
        
        if not row:
            bot.reply_to(message, "❌ Работник не найден.", reply_markup=get_moderator_kb())
            return
        
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = bot.reply_to(
            message,
            f"⭐ Оценка для {row['name']}\n"
            f"Текущий рейтинг: {row['rating']}\n\n"
            f"Выберите оценку:",
            reply_markup=kb
        )
        bot.register_next_step_handler(msg, mod_rate_apply, row['id'])
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_get_user: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_apply(message, user_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=get_moderator_kb())
            return
        
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        add_rating(user_id, delta)
        
        c = db.execute("SELECT rating FROM users WHERE id = ?", (user_id,))
        if c:
            new_rating = c.fetchone()[0]
        else:
            new_rating = "неизвестно"
        
        bot.reply_to(message, f"✅ Рейтинг обновлён: {new_rating}", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_apply: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить заказчика' and m.from_user.id in MODERATOR_IDS)
def mod_rate_customer_start(message):
    try:
        msg = bot.reply_to(message, "Введите ID заказчика (число):")
        bot.register_next_step_handler(msg, mod_rate_customer_get)
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_customer_get(message):
    try:
        try:
            customer_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        
        c = db.execute("SELECT id, name, customer_rating FROM users WHERE id = ? AND role = 'zakazchik'", (customer_id,))
        if c is None:
            bot.reply_to(message, "❌ Заказчик не найден.", reply_markup=get_moderator_kb())
            return
        row = c.fetchone()
        
        if not row:
            bot.reply_to(message, "❌ Заказчик не найден.", reply_markup=get_moderator_kb())
            return
        
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = bot.reply_to(
            message,
            f"⭐ Оценка для {row['name']}\n"
            f"Текущий рейтинг: {row['customer_rating']}\n\n"
            f"Выберите оценку:",
            reply_markup=kb
        )
        bot.register_next_step_handler(msg, mod_rate_customer_apply, row['id'])
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_get: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_customer_apply(message, customer_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=get_moderator_kb())
            return
        
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        row = rate_customer(customer_id, delta)
        
        if row:
            bot.reply_to(message, f"✅ Рейтинг заказчика обновлён: {row[0]}", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "❌ Ошибка", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_apply: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⚖️ Арбитраж' and m.from_user.id in MODERATOR_IDS)
def mod_arbitration(message):
    try:
        c = db.execute("SELECT id, zakazchik_name, address, status FROM orders WHERE status IN ('in_progress', 'completed')")
        if c is None:
            bot.reply_to(message, "⚖️ Нет заказов для арбитража.")
            return
        rows = c.fetchall()
        
        if not rows:
            bot.reply_to(message, "⚖️ Нет заказов для арбитража.")
            return
        
        text = "⚖️ ДОСТУПНЫЕ ЗАКАЗЫ\n\n"
        for row in rows:
            text += f"🆔 #{row['id']} | {row['zakazchik_name']} | {row['address']}\nСтатус: {row['status']}\n\n"
        
        text += "📝 Команды:\n/arbitrate ID refund|penalty|ban\n\n"
        text += "refund - вернуть деньги\n"
        text += "penalty - понизить рейтинг заказчика\n"
        text += "ban - заблокировать заказчика"
        
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Ошибка в mod_arbitration: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    try:
        if message.from_user.id not in MODERATOR_IDS:
            return
        
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "❌ Использование: /arbitrate ID refund|penalty|ban")
            return
        
        try:
            order_id = int(parts[1])
        except:
            bot.reply_to(message, "❌ ID должен быть числом.")
            return
        
        action = parts[2].lower()
        order = get_order(order_id)
        
        if not order:
            bot.reply_to(message, "❌ Заказ не найден.")
            return
        
        if action == 'refund':
            db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            db.commit()
            bot.reply_to(message, f"✅ Заказ #{order_id} отменён, деньги возвращены заказчику.")
            
        elif action == 'penalty':
            add_rating(order[1], -1)
            bot.reply_to(message, f"✅ Заказчику #{order[1]} снижен рейтинг.")
            
        elif action == 'ban':
            db.execute("UPDATE users SET blocked = 1 WHERE id = ?", (order[1],))
            db.commit()
            bot.reply_to(message, f"✅ Заказчик #{order[1]} заблокирован.")
            
        else:
            bot.reply_to(message, "❌ Неизвестное действие. Доступны: refund, penalty, ban.")
    except Exception as e:
        logging.error(f"Ошибка в arbitrate_command: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🔒 Блокировка' and m.from_user.id in MODERATOR_IDS)
def mod_block(message):
    try:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("По ID"), KeyboardButton("По телефону"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = bot.reply_to(message, "🔒 Выберите способ блокировки:", reply_markup=kb)
        bot.register_next_step_handler(msg, mod_block_choose_method)
    except Exception as e:
        logging.error(f"Ошибка в mod_block: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_block_choose_method(message):
    try:
        if message.text == '⬅️ Назад':
            bot.reply_to(message, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
            return
        
        if message.text == 'По ID':
            msg = bot.reply_to(message, "Введите ID пользователя:")
            bot.register_next_step_handler(msg, mod_block_by_id)
        elif message.text == 'По телефону':
            msg = bot.reply_to(message, "Введите номер телефона (в формате +7XXXXXXXXXX):")
            bot.register_next_step_handler(msg, mod_block_by_phone)
        else:
            bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_block_choose_method: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_block_by_id(message):
    try:
        try:
            user_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        
        c = db.execute("SELECT id, name, telegram_id FROM users WHERE id = ?", (user_id,))
        if c is None:
            bot.reply_to(message, "❌ Пользователь не найден.", reply_markup=get_moderator_kb())
            return
        row = c.fetchone()
        
        if not row:
            bot.reply_to(message, "❌ Пользователь не найден.", reply_markup=get_moderator_kb())
            return
        
        db.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
        db.commit()
        
        bot.reply_to(message, f"✅ Пользователь {row['name']} (ID {row['id']}) заблокирован.", reply_markup=get_moderator_kb())
        
        try:
            bot.send_message(row['telegram_id'], "⛔ Ваш аккаунт заблокирован модератором.\nДля связи нажмите '📞 Связь с модератором'.")
        except:
            pass
    except Exception as e:
        logging.error(f"Ошибка в mod_block_by_id: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_block_by_phone(message):
    try:
        phone = message.text
        db.execute("UPDATE users SET blocked = 1 WHERE phone = ?", (phone,))
        db.commit()
        
        c = db.execute("SELECT id, name, telegram_id FROM users WHERE phone = ?", (phone,))
        if c:
            rows = c.fetchall()
            if rows:
                bot.reply_to(message, f"✅ Заблокировано {len(rows)} пользователей.", reply_markup=get_moderator_kb())
                for row in rows:
                    try:
                        bot.send_message(row['telegram_id'], "⛔ Ваш аккаунт заблокирован модератором.\nДля связи нажмите '📞 Связь с модератором'.")
                    except:
                        pass
            else:
                bot.reply_to(message, "❌ Пользователь с таким номером не найден.", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "❌ Пользователь с таким номером не найден.", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_block_by_phone: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🔓 Разблокировка' and m.from_user.id in MODERATOR_IDS)
def mod_unblock(message):
    try:
        msg = bot.reply_to(message, "Введите ID пользователя для разблокировки:")
        bot.register_next_step_handler(msg, mod_unblock_by_id)
    except Exception as e:
        logging.error(f"Ошибка в mod_unblock: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_unblock_by_id(message):
    try:
        try:
            user_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Введите число.", reply_markup=get_moderator_kb())
            return
        
        c = db.execute("SELECT id, name, telegram_id FROM users WHERE id = ? AND blocked = 1", (user_id,))
        if c is None:
            bot.reply_to(message, "❌ Заблокированный пользователь не найден.", reply_markup=get_moderator_kb())
            return
        row = c.fetchone()
        
        if not row:
            bot.reply_to(message, "❌ Заблокированный пользователь не найден.", reply_markup=get_moderator_kb())
            return
        
        db.execute("UPDATE users SET blocked = 0 WHERE id = ?", (user_id,))
        db.commit()
        
        bot.reply_to(message, f"✅ Пользователь {row['name']} (ID {row['id']}) разблокирован.", reply_markup=get_moderator_kb())
        
        try:
            bot.send_message(row['telegram_id'], "✅ Ваш аккаунт разблокирован модератором!")
        except:
            pass
    except Exception as e:
        logging.error(f"Ошибка в mod_unblock_by_id: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== CALLBACK ОБРАБОТЧИК ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        user = get_user(user_id)
        
        if not user:
            bot.answer_callback_query(call.id, "❌ Нажмите /start", show_alert=True)
            return
        
        if user[11] == 1:
            bot.answer_callback_query(call.id, "⛔ Вы заблокированы", show_alert=True)
            return
        
        if data.startswith('take_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            
            if user[6] != 'rabotnik':
                bot.answer_callback_query(call.id, "❌ Только для работников", show_alert=True)
                return
            
            assigned = get_assignments(order_id)
            if user[0] in assigned:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли этот заказ", show_alert=True)
                return
            
            try:
                bot.edit_message_text(
                    f"⚠️ ПОДТВЕРДИТЕ ВЗЯТИЕ ЗАКАЗА #{order_id}\n\n"
                    f"💵 Выплата: {order[8]} ₽\n"
                    f"📍 Адрес: {order[3]}\n"
                    f"⏱ Часы: {order[4]} ч.\n"
                    f"👥 Нужно: {order[5]} чел.\n\n"
                    f"Вы уверены?",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=confirm_take_kb(order_id)
                )
                bot.answer_callback_query(call.id)
            except Exception as e:
                logging.error(f"Ошибка при показе подтверждения: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        
        elif data.startswith('confirm_take_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            
            assigned = get_assignments(order_id)
            if user[0] in assigned:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли", show_alert=True)
                return
            
            db.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", 
                      (order_id, user[0], order[8]))
            db.commit()
            
            new_assigned = get_assignments(order_id)
            if len(new_assigned) >= order[5]:
                db.execute("UPDATE orders SET status = 'in_progress' WHERE id = ?", (order_id,))
                db.commit()
                
                try:
                    bot.send_message(order[1], f"🔔 Заказ #{order_id} укомплектован! Все {order[5]} работников собраны.")
                except:
                    pass
                
                bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} укомплектован!", show_alert=True)
            else:
                bot.answer_callback_query(call.id, f"✅ Вы взяли заказ #{order_id}! Осталось {order[5] - len(new_assigned)} чел.", show_alert=True)
            
            try:
                bot.edit_message_text(
                    f"✅ ВЫ ВЗЯЛИ ЗАКАЗ #{order_id}\n\n"
                    f"💵 Выплата: {order[8]} ₽\n"
                    f"📍 Адрес: {order[3]}\n"
                    f"📊 Статус: {'Укомплектован' if len(new_assigned) >= order[5] else 'Ожидает работников'}",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения: {e}")
            
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(m, f"👷 {user[2]} взял заказ #{order_id}")
                except:
                    pass
        
        elif data.startswith('cancel_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[1] != user[0]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            if user[6] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            
            if order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Можно отменить только открытый заказ", show_alert=True)
                return
            
            if cancel_order(order_id):
                bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} отменён!", show_alert=True)
                try:
                    bot.edit_message_text(
                        f"❌ ЗАКАЗ #{order_id} ОТМЕНЁН\n\n"
                        f"Заказчик: {order[2]}",
                        call.message.chat.id,
                        call.message.message_id
                    )
                except Exception as e:
                    logging.error(f"Ошибка обновления сообщения: {e}")
                
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(m, f"❌ Заказ #{order_id} отменён заказчиком {user[2]}")
                    except:
                        pass
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка при отмене", show_alert=True)
        
        elif data.startswith('complete_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[1] != user[0]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            if user[6] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            
            if order[9] == 'completed':
                bot.answer_callback_query(call.id, "❌ Уже завершён", show_alert=True)
                return
            
            db.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
            db.commit()
            
            bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} завершён!", show_alert=True)
            try:
                bot.edit_message_text(
                    f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН\n\n"
                    f"💰 Сумма: {order[6]} ₽",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения: {e}")
            
            assigned = get_assignments(order_id)
            for worker_id in assigned:
                try:
                    worker = get_user_by_id(worker_id)
                    if worker:
                        bot.send_message(worker[1], f"✅ Заказ #{order_id} завершён! Ваша выплата: {order[8]} ₽")
                except:
                    pass
            
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(m, f"✅ Заказ #{order_id} завершён заказчиком {user[2]}")
                except:
                    pass
        
        elif data == 'cancel_take':
            try:
                bot.edit_message_text(
                    "❌ Взятие отменено",
                    call.message.chat.id,
                    call.message.message_id
                )
                bot.answer_callback_query(call.id)
            except Exception as e:
                logging.error(f"Ошибка отмены взятия: {e}")
        
        else:
            bot.answer_callback_query(call.id, "❌ Неизвестная команда", show_alert=True)
            
    except Exception as e:
        logging.error(f"Ошибка в callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# ========== ЗАБЛОКИРОВАННЫЙ ==========
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[11] == 0:
            return
        
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, f"📞 Пользователь {uid} ({user[2] or 'без имени'}) просит связи.")
            except:
                pass
        
        bot.reply_to(message, "✅ Запрос отправлен модератору.")
    except Exception as e:
        logging.error(f"Ошибка в contact_moderator: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== FALLBACK ==========
@bot.message_handler(func=lambda m: True)
def fallback(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if user and user[6] == 'moderator' and uid in MODERATOR_IDS:
            bot.reply_to(message, "Используйте кнопки панели модератора.", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "Используйте кнопки меню.", reply_markup=get_main_kb(uid))
    except Exception as e:
        logging.error(f"Ошибка в fallback: {e}")

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    logging.info("🚀 Бот запущен!")
    print("🤖 Бот Юрга-Подработка запущен!")
    print(f"📊 Модераторы: {MODERATOR_IDS}")
    print("✅ Готов к работе!")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            logging.error(f"⚠️ Ошибка в polling: {e}")
            print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
