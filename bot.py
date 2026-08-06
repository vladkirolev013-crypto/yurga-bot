import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime, timedelta
import threading
import time
import logging
import re

# ========== НАСТРОЙКИ ==========
TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'

# СПИСОК МОДЕРАТОРОВ (владельцев)
MODERATOR_IDS = [
    8746212340,  # Твой ID
]

# НОМЕР СБП (пока заглушка, потом подставишь свой)
SBP_PHONE = '+7XXXXXXXXXX'

bot = telebot.TeleBot(TOKEN)

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            
            # Таблица users
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
            
            # Таблица orders с новыми статусами
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
            
            # Таблица assignments
            c.execute('''CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                user_id INTEGER,
                payout INTEGER,
                confirmed INTEGER DEFAULT 0,
                confirmed_at TEXT,
                photo_file_id TEXT
            )''')
            
            # Таблица для сообщений (чат между пользователями)
            c.execute('''CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER,
                to_user_id INTEGER,
                order_id INTEGER,
                text TEXT,
                created_at TEXT,
                read INTEGER DEFAULT 0
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
    
    def close(self):
        try:
            self.conn.close()
        except Exception as e:
            logging.error(f"Ошибка close: {e}")

db = Database()

# ========== СТАТУСЫ ЗАКАЗОВ ==========
ORDER_STATUSES = {
    'open': '🟢 Открыт',
    'in_progress': '🟡 Сбор работников',
    'ready_to_pay': '💰 Ожидает оплаты',
    'paid': '✅ Оплачен',
    'working': '🔧 Работы ведутся',
    'waiting_approval': '📸 Ждёт подтверждения',
    'waiting_payout': '💵 Ждёт выплаты',
    'completed': '✅ Завершён',
    'cancelled': '❌ Отменён'
}

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
                row['status'], row['photo_file_id'], row['created_at'],
                row['paid_at'], row['completed_at']
            ]
        return None
    except Exception as e:
        logging.error(f"Ошибка get_order: {e}")
        return None

def get_assignments(order_id):
    try:
        c = db.execute("SELECT user_id, confirmed FROM assignments WHERE order_id = ?", (order_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['user_id'], row['confirmed']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_assignments: {e}")
        return []

def get_assignments_with_photo(order_id):
    try:
        c = db.execute("SELECT user_id, photo_file_id FROM assignments WHERE order_id = ? AND photo_file_id IS NOT NULL", (order_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [row['user_id'] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_assignments_with_photo: {e}")
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

def get_worker_orders(user_id):
    try:
        c = db.execute('''SELECT o.id, o.status, a.payout, o.zakazchik_name, o.address, a.confirmed
                     FROM assignments a 
                     JOIN orders o ON a.order_id = o.id 
                     WHERE a.user_id = ?
                     ORDER BY o.created_at DESC''', (user_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['status'], row['payout'], row['zakazchik_name'], row['address'], row['confirmed']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_worker_orders: {e}")
        return []

def get_customer_orders(zakazchik_id):
    try:
        c = db.execute("SELECT id, total_sum, status, created_at FROM orders WHERE zakazchik_id = ? ORDER BY created_at DESC", (zakazchik_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['total_sum'], row['status'], row['created_at']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_customer_orders: {e}")
        return []

def get_workers_for_order(order_id):
    try:
        c = db.execute("SELECT user_id FROM assignments WHERE order_id = ?", (order_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [row['user_id'] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_workers_for_order: {e}")
        return []

def update_order_status(order_id, status):
    try:
        db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка update_order_status: {e}")
        return False

def confirm_worker_on_place(order_id, user_id):
    try:
        db.execute("UPDATE assignments SET confirmed = 1, confirmed_at = ? WHERE order_id = ? AND user_id = ?", 
                  (datetime.now().isoformat(), order_id, user_id))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка confirm_worker_on_place: {e}")
        return False

def set_order_photo(order_id, photo_file_id):
    try:
        db.execute("UPDATE orders SET photo_file_id = ? WHERE id = ?", (photo_file_id, order_id))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка set_order_photo: {e}")
        return False

def set_worker_photo(order_id, user_id, photo_file_id):
    try:
        db.execute("UPDATE assignments SET photo_file_id = ? WHERE order_id = ? AND user_id = ?", 
                  (photo_file_id, order_id, user_id))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка set_worker_photo: {e}")
        return False

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

def block_user_by_phone(phone):
    try:
        db.execute("UPDATE users SET blocked = 1 WHERE phone = ?", (phone,))
        db.commit()
        return 1
    except Exception as e:
        logging.error(f"Ошибка block_user_by_phone: {e}")
        return 0

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
        return True
    except Exception as e:
        logging.error(f"Ошибка rate_customer: {e}")
        return False

# ========== ФУНКЦИИ ДЛЯ СООБЩЕНИЙ ==========
def save_message(from_user_id, to_user_id, order_id, text):
    try:
        db.execute("INSERT INTO messages (from_user_id, to_user_id, order_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
                  (from_user_id, to_user_id, order_id, text, datetime.now().isoformat()))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка save_message: {e}")
        return False

def get_unread_messages(user_id):
    try:
        c = db.execute("SELECT id, from_user_id, order_id, text, created_at FROM messages WHERE to_user_id = ? AND read = 0 ORDER BY created_at DESC", (user_id,))
        if c is None:
            return []
        rows = c.fetchall()
        return [[row['id'], row['from_user_id'], row['order_id'], row['text'], row['created_at']] for row in rows]
    except Exception as e:
        logging.error(f"Ошибка get_unread_messages: {e}")
        return []

def mark_messages_read(user_id):
    try:
        db.execute("UPDATE messages SET read = 1 WHERE to_user_id = ?", (user_id,))
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка mark_messages_read: {e}")
        return False

# ========== КЛАВИАТУРЫ ==========
_main_kb = None
_worker_kb = None
_customer_kb = None
_moderator_kb = None
_blocked_kb = None

def get_main_kb(telegram_id=None):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    if telegram_id and telegram_id in MODERATOR_IDS:
        kb.row(KeyboardButton("🛡️ Я модератор"))
    return kb

def get_worker_kb():
    global _worker_kb
    if _worker_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("📋 Мои заказы"))
        kb.row(KeyboardButton("👤 Профиль"), KeyboardButton("🔄 Сменить смену"))
        kb.row(KeyboardButton("📞 Связаться с модератором"), KeyboardButton("⬅️ Назад"))
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
        kb.row(KeyboardButton("🔓 Разблокировка"), KeyboardButton("📨 Сообщения"))
        kb.row(KeyboardButton("⬅️ Назад"))
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
        kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_{order_id}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{order_id}"))
    return kb

def confirm_take_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📍 Я на месте", callback_data=f"confirm_place_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отказаться", callback_data=f"cancel_take_{order_id}"))
    kb.add(InlineKeyboardButton("📞 Связаться", callback_data=f"contact_mod_{order_id}"))
    return kb

def payment_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Я оплатил", callback_data=f"i_paid_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{order_id}"))
    kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_{order_id}"))
    return kb

def worker_photo_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📸 Отправить фото", callback_data=f"send_photo_{order_id}"))
    kb.add(InlineKeyboardButton("📞 Связаться", callback_data=f"contact_mod_{order_id}"))
    return kb

def approve_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Работа выполнена", callback_data=f"approve_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{order_id}"))
    kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_{order_id}"))
    return kb

def moderator_payment_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"confirm_payment_{order_id}"))
    kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_{order_id}"))
    return kb

def moderator_payout_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Выплатил работникам", callback_data=f"confirm_payout_{order_id}"))
    kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_{order_id}"))
    return kb

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==========
reg_data = {}
order_data = {}
msg_data = {}

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
            bot.reply_to(message, "⛔ Ваш аккаунт заблокирован.", reply_markup=get_blocked_kb())
            return
        
        # Проверяем непрочитанные сообщения
        unread = get_unread_messages(uid)
        if unread and uid not in MODERATOR_IDS:
            count = len(unread)
            bot.send_message(message.chat.id, f"📨 У вас {count} непрочитанных сообщений. Нажмите '📨 Сообщения' в меню (если есть) или напишите модератору.")
        
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
        selected_role = role_map[message.text]
        
        if selected_role == 'moderator' and uid not in MODERATOR_IDS:
            bot.reply_to(message, "❌ У вас нет прав модератора.")
            return
        
        update_user(uid, 'role', selected_role)
        
        if selected_role == 'rabotnik':
            bot.reply_to(message, "✅ Вы переключились на роль работника!", reply_markup=get_worker_kb())
        elif selected_role == 'zakazchik':
            bot.reply_to(message, "✅ Вы переключились на роль заказчика!", reply_markup=get_customer_kb())
        else:
            bot.reply_to(message, "✅ Вы переключились на панель модератора!", reply_markup=get_moderator_kb())
            
    except Exception as e:
        logging.error(f"Ошибка в role_choice: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ИСПРАВЛЕННАЯ КНОПКА НАЗАД ==========
@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back_to_main(message):
    try:
        uid = message.from_user.id
        # Всегда показываем главное меню, независимо от роли
        bot.reply_to(message, "📱 Главное меню:\n\nВыберите роль:", reply_markup=get_main_kb(uid))
    except Exception as e:
        logging.error(f"Ошибка в back_to_main: {e}")
        bot.reply_to(message, "📱 Главное меню:", reply_markup=get_main_kb(None))

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
        
        if role == 'rabotnik':
            text = """📜 УСЛОВИЯ СЕРВИСА (ДЛЯ РАБОТНИКОВ)

1. Сервис - посредник между заказчиками и работниками
2. Вы берёте заказ только если готовы выполнить его качественно
3. ОБЯЗАТЕЛЬНО подтвердите, что вы на месте (кнопка "Я на месте")
4. Без подтверждения "на месте" - заказчик не оплачивает, вы не получаете выплату
5. После выполнения работы отправьте ФОТО выполненной работы
6. Без фото - заказчик не подтвердит выполнение, вы не получите выплату
7. Сервис гарантирует выплату после подтверждения заказчиком
8. Сервис не отвечает за травмы, кражи, качество вашей работы

✅ Принимаете условия?"""
        else:
            text = """📜 УСЛОВИЯ СЕРВИСА (ДЛЯ ЗАКАЗЧИКОВ)

1. Сервис - посредник между заказчиками и работниками
2. После создания заказа работники сами решают брать его или нет
3. После комплектации заказа вы переводите деньги на СБП сервиса
4. Деньги хранятся на счёте сервиса до полного выполнения заказа
5. Если работники сорвали сделку - деньги возвращаются в полном объёме
6. После выполнения работы вы подтверждаете её качество
7. Только после вашего подтверждения мы переводим деньги работникам
8. Сервис не отвечает за качество работы, травмы, кражи

✅ Принимаете условия?"""
        
        bot.send_message(message.chat.id, text, reply_markup=kb)
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
            msg = bot.reply_to(message, "📝 Введите ваше ФИО:")
            bot.register_next_step_handler(msg, get_worker_name, uid)
        else:
            msg = bot.reply_to(message, "📝 Введите ваше ФИО:")
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
        msg = bot.reply_to(message, "💳 Введите номер карты для выплат:")
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
            bot.reply_to(message, "❌ Эта функция только для работников.")
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
            bot.reply_to(message, "❌ Эта функция только для работников.")
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        if user[10] == 0:
            bot.reply_to(message, "❌ Пройдите регистрацию.")
            return
        
        c = db.execute("SELECT id, payout_per_person, address, hours, people FROM orders WHERE status = 'open' ORDER BY created_at DESC")
        if c is None:
            bot.reply_to(message, "📭 Нет свободных заказов.")
            return
        rows = c.fetchall()
        
        if not rows:
            bot.reply_to(message, "📭 Нет свободных заказов.")
            return
        
        for row in rows:
            text = (
                f"🆔 Заказ #{row['id']}\n"
                f"💵 Выплата: {row['payout_per_person']} ₽\n"
                f"📍 Адрес: {row['address']}\n"
                f"⏱ Часы: {row['hours']} ч.\n"
                f"👥 Нужно: {row['people']} чел."
            )
            bot.send_message(
                message.chat.id,
                text,
                reply_markup=order_inline_kb(row['id'], is_customer=False)
            )
    except Exception as e:
        logging.error(f"Ошибка в free_orders: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_worker_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            bot.reply_to(message, "❌ Эта функция только для работников.")
            return
        
        orders = get_worker_orders(user[0])
        if not orders:
            bot.reply_to(message, "📭 У вас нет активных заказов.")
            return
        
        for o in orders:
            status_text = ORDER_STATUSES.get(o[1], o[1])
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"📊 Статус: {status_text}\n"
                f"💵 Выплата: {o[2]} ₽\n"
                f"👤 Заказчик: {o[3]}\n"
                f"📍 Адрес: {o[4]}"
            )
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{o[0]}"))
            bot.send_message(message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Ошибка в my_worker_orders: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            bot.reply_to(message, "❌ Эта функция только для работников.")
            return
        
        c = db.execute("SELECT SUM(payout) FROM assignments WHERE user_id = ?", (user[0],))
        if c:
            total = c.fetchone()[0] or 0
        else:
            total = 0
        
        c = db.execute("SELECT COUNT(*) FROM assignments WHERE user_id = ?", (user[0],))
        if c:
            count = c.fetchone()[0] or 0
        else:
            count = 0
        
        bot.reply_to(
            message,
            f"💰 ВАШИ ВЫПЛАТЫ\n\n"
            f"💵 Всего выплачено: {total} ₽\n"
            f"👥 Количество заказов: {count}"
        )
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

@bot.message_handler(func=lambda m: m.text == '📞 Связаться с модератором')
def contact_moderator_worker(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            bot.reply_to(message, "❌ Эта функция только для работников.")
            return
        
        if user[11] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=get_blocked_kb())
            return
        
        msg = bot.reply_to(message, "📝 Напишите сообщение модератору:")
        bot.register_next_step_handler(msg, send_to_moderator, uid)
    except Exception as e:
        logging.error(f"Ошибка в contact_moderator_worker: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def send_to_moderator(message, uid):
    try:
        user = get_user(uid)
        text = f"📩 СООБЩЕНИЕ ОТ РАБОТНИКА\n\nОт: {user[2] or 'без имени'} (ID {user[0]})\nТелефон: {user[3] or 'не указан'}\n\n{message.text}"
        
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, text)
            except:
                pass
        
        bot.reply_to(message, "✅ Сообщение отправлено модератору.", reply_markup=get_worker_kb())
    except Exception as e:
        logging.error(f"Ошибка в send_to_moderator: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ЗАКАЗЧИК ==========

@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            bot.reply_to(message, "❌ Эта функция только для заказчиков.")
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
        
        total = hours * people * 500
        commission = hours * people * 50
        payout = (total - commission) // people
        
        name = user[2] if user[2] else "Заказчик"
        address = order_data[uid]['address']
        
        conn = db.conn
        c = conn.cursor()
        c.execute('''INSERT INTO orders 
                     (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user[0], name, address, hours, people, total, commission, payout, 'open', datetime.now().isoformat()))
        conn.commit()
        order_id = c.lastrowid
        
        del order_data[uid]
        
        # ===== ЗАКАЗЧИКУ =====
        bot.reply_to(
            message, 
            f"✅ ЗАКАЗ #{order_id} СОЗДАН!\n\n"
            f"📍 Адрес: {address}\n"
            f"⏱ Часы: {hours} ч.\n"
            f"👥 Нужно: {people} чел.\n"
            f"💰 Сумма к оплате: {total} ₽\n\n"
            f"📌 Ожидайте, пока работники соберутся.\n"
            f"Вы получите уведомление, когда все будут на месте.",
            reply_markup=get_customer_kb()
        )
        
        # ===== РАБОТНИКАМ =====
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
        
        # ===== МОДЕРАТОРУ =====
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
                    f"📊 Комиссия: {commission} ₽\n"
                    f"💵 Выплата: {payout} ₽/чел"
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
            bot.reply_to(message, "❌ Эта функция только для заказчиков.")
            return
        
        orders = get_customer_orders(user[0])
        if not orders:
            bot.reply_to(message, "📭 У вас нет заказов.")
            return
        
        for o in orders:
            status_text = ORDER_STATUSES.get(o[2], o[2])
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"💰 Сумма: {o[1]} ₽\n"
                f"📊 Статус: {status_text}"
            )
            kb = InlineKeyboardMarkup()
            workers = get_workers_for_order(o[0])
            if workers:
                kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{o[0]}"))
            bot.send_message(message.chat.id, text, reply_markup=kb)
    except Exception as e:
        logging.error(f"Ошибка в my_orders_customer: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            bot.reply_to(message, "❌ Эта функция только для заказчиков.")
            return
        
        msg = bot.reply_to(message, "📝 Опишите вашу жалобу:")
        bot.register_next_step_handler(msg, send_complaint, uid)
    except Exception as e:
        logging.error(f"Ошибка в complain: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def send_complaint(message, uid):
    try:
        user = get_user(uid)
        text = f"⚠️ ЖАЛОБА\n\nОт: {user[2] or 'без имени'} (ID {user[0]})\nТелефон: {user[3] or 'не указан'}\n\n{message.text}"
        
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

@bot.message_handler(func=lambda m: m.text in [
    '💰 Выплаты', '🟡 Активные', '✅ Завершённые', '👥 Работники', 
    '🏢 Заказчики', '📊 Статистика', '⭐ Оценить работника', '⭐ Оценить заказчика',
    '⚖️ Арбитраж', '🔒 Блокировка', '🔓 Разблокировка', '📨 Сообщения'
] and m.from_user.id in MODERATOR_IDS)
def moderator_commands(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'moderator':
            bot.reply_to(message, "❌ У вас нет прав модератора.")
            return
        
        text = message.text
        
        if text == '💰 Выплаты':
            c = db.execute("SELECT SUM(payout) FROM assignments")
            total = c.fetchone()[0] if c else 0
            c = db.execute("SELECT COUNT(*) FROM assignments")
            count = c.fetchone()[0] if c else 0
            bot.reply_to(message, f"💰 ВСЕГО ВЫПЛАЧЕНО\n\n💵 {total} ₽\n👥 {count} выплат")
        
        elif text == '🟡 Активные':
            c = db.execute("SELECT * FROM orders WHERE status NOT IN ('completed', 'cancelled') ORDER BY created_at DESC")
            if c is None:
                bot.reply_to(message, "🟡 Нет активных заказов.")
                return
            rows = c.fetchall()
            if not rows:
                bot.reply_to(message, "🟡 Нет активных заказов.")
                return
            for row in rows:
                status_text = ORDER_STATUSES.get(row['status'], row['status'])
                msg_text = (
                    f"🆔 Заказ #{row['id']}\n"
                    f"👤 Заказчик: {row['zakazchik_name']}\n"
                    f"📍 Адрес: {row['address']}\n"
                    f"📊 Статус: {status_text}\n"
                    f"💰 Сумма: {row['total_sum']} ₽\n"
                    f"💵 Выплата: {row['payout_per_person']} ₽/чел"
                )
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{row['id']}"))
                workers = get_workers_for_order(row['id'])
                if workers:
                    kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{row['id']}"))
                bot.send_message(message.chat.id, msg_text, reply_markup=kb)
        
        elif text == '✅ Завершённые':
            c = db.execute("SELECT * FROM orders WHERE status = 'completed' ORDER BY created_at DESC")
            if c is None:
                bot.reply_to(message, "✅ Нет завершённых заказов.")
                return
            rows = c.fetchall()
            if not rows:
                bot.reply_to(message, "✅ Нет завершённых заказов.")
                return
            for row in rows:
                msg_text = (
                    f"✅ Заказ #{row['id']}\n"
                    f"👤 Заказчик: {row['zakazchik_name']}\n"
                    f"📍 Адрес: {row['address']}\n"
                    f"💰 Сумма: {row['total_sum']} ₽"
                )
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("📞 Написать заказчику", callback_data=f"contact_customer_order_{row['id']}"))
                workers = get_workers_for_order(row['id'])
                if workers:
                    kb.add(InlineKeyboardButton("📞 Написать работнику", callback_data=f"contact_worker_order_{row['id']}"))
                bot.send_message(message.chat.id, msg_text, reply_markup=kb)
        
        elif text == '👥 Работники':
            workers = get_all_workers()
            if not workers:
                bot.reply_to(message, "👥 Нет работников.")
                return
            msg_text = "👥 РАБОТНИКИ:\n\n"
            for w in workers[:20]:
                status = "🟢" if w[5] else "🔴"
                block = "🔒" if w[4] else "✅"
                msg_text += f"{status} {block} ID {w[0]}: {w[1]}\n"
                msg_text += f"   📞 {w[2]}, ⭐ {w[3]}\n"
            bot.reply_to(message, msg_text)
        
        elif text == '🏢 Заказчики':
            customers = get_all_customers()
            if not customers:
                bot.reply_to(message, "🏢 Нет заказчиков.")
                return
            msg_text = "🏢 ЗАКАЗЧИКИ:\n\n"
            for c in customers[:20]:
                block = "🔒" if c[4] else "✅"
                msg_text += f"{block} ID {c[0]}: {c[1]}\n"
                msg_text += f"   📞 {c[2]}, ⭐ {c[3]}\n"
            bot.reply_to(message, msg_text)
        
        elif text == '📊 Статистика':
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
            c = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'cancelled'")
            cancelled = c.fetchone()[0] if c else 0
            c = db.execute("SELECT SUM(payout) FROM assignments")
            total_payouts = c.fetchone()[0] if c else 0
            
            msg_text = (
                f"📊 СТАТИСТИКА\n\n"
                f"👥 Всего: {total_users}\n"
                f"👷 Работников: {workers}\n"
                f"🏢 Заказчиков: {customers}\n\n"
                f"📦 Заказов: {total_orders}\n"
                f"✅ Завершённых: {completed}\n"
                f"❌ Отменённых: {cancelled}\n\n"
                f"💰 Выплачено: {total_payouts} ₽"
            )
            bot.reply_to(message, msg_text)
        
        elif text == '⭐ Оценить работника':
            msg = bot.reply_to(message, "Введите ID работника:")
            bot.register_next_step_handler(msg, mod_rate_get_user)
        
        elif text == '⭐ Оценить заказчика':
            msg = bot.reply_to(message, "Введите ID заказчика:")
            bot.register_next_step_handler(msg, mod_rate_customer_get)
        
        elif text == '⚖️ Арбитраж':
            c = db.execute("SELECT id, zakazchik_name, address, status FROM orders WHERE status IN ('waiting_approval', 'waiting_payout')")
            if c is None:
                bot.reply_to(message, "⚖️ Нет заказов для арбитража.")
                return
            rows = c.fetchall()
            if not rows:
                bot.reply_to(message, "⚖️ Нет заказов для арбитража.")
                return
            msg_text = "⚖️ АРБИТРАЖ\n\n"
            for row in rows:
                msg_text += f"🆔 #{row['id']} | {row['zakazchik_name']}\n📍 {row['address']}\nСтатус: {row['status']}\n\n"
            msg_text += "/arbitrate ID refund|penalty|ban"
            bot.reply_to(message, msg_text)
        
        elif text == '🔒 Блокировка':
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton("По ID"), KeyboardButton("По телефону"))
            kb.row(KeyboardButton("⬅️ Назад"))
            msg = bot.reply_to(message, "🔒 Выберите способ:", reply_markup=kb)
            bot.register_next_step_handler(msg, mod_block_choose_method)
        
        elif text == '🔓 Разблокировка':
            msg = bot.reply_to(message, "Введите ID пользователя:")
            bot.register_next_step_handler(msg, mod_unblock_by_id)
        
        elif text == '📨 Сообщения':
            unread = get_unread_messages(uid)
            if not unread:
                bot.reply_to(message, "📨 Нет новых сообщений.")
                return
            
            mark_messages_read(uid)
            msg_text = "📨 НОВЫЕ СООБЩЕНИЯ:\n\n"
            for msg in unread[:10]:
                from_user = get_user_by_id(msg[1])
                from_name = from_user[2] if from_user else "Неизвестный"
                order_text = f" (заказ #{msg[2]})" if msg[2] != 0 else ""
                msg_text += f"От: {from_name}{order_text}\n{msg[3]}\n{msg[4][:16]}\n\n"
            
            if len(unread) > 10:
                msg_text += f"\n... и ещё {len(unread)-10} сообщений"
            
            msg_text += "\n📌 Чтобы ответить - используйте кнопки 'Написать' в заказах"
            bot.reply_to(message, msg_text)
            
    except Exception as e:
        logging.error(f"Ошибка в moderator_commands: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ МОДЕРАТОРА ==========

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
        msg = bot.reply_to(message, f"⭐ {row['name']} (рейтинг: {row['rating']})", reply_markup=kb)
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
        new_rating = c.fetchone()[0] if c else "неизвестно"
        bot.reply_to(message, f"✅ Рейтинг: {new_rating}", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_apply: {e}")
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
        msg = bot.reply_to(message, f"⭐ {row['name']} (рейтинг: {row['customer_rating']})", reply_markup=kb)
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
        rate_customer(customer_id, delta)
        c = db.execute("SELECT customer_rating FROM users WHERE id = ?", (customer_id,))
        new_rating = c.fetchone()[0] if c else "неизвестно"
        bot.reply_to(message, f"✅ Рейтинг заказчика: {new_rating}", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_apply: {e}")
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
            msg = bot.reply_to(message, "Введите номер телефона:")
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
        bot.reply_to(message, f"✅ {row['name']} заблокирован.", reply_markup=get_moderator_kb())
        try:
            bot.send_message(row['telegram_id'], "⛔ Вы заблокированы.")
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
                        bot.send_message(row['telegram_id'], "⛔ Вы заблокированы.")
                    except:
                        pass
            else:
                bot.reply_to(message, "❌ Пользователь не найден.", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "❌ Пользователь не найден.", reply_markup=get_moderator_kb())
    except Exception as e:
        logging.error(f"Ошибка в mod_block_by_phone: {e}")
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
        bot.reply_to(message, f"✅ {row['name']} разблокирован.", reply_markup=get_moderator_kb())
        try:
            bot.send_message(row['telegram_id'], "✅ Вы разблокированы.")
        except:
            pass
    except Exception as e:
        logging.error(f"Ошибка в mod_unblock_by_id: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    try:
        if message.from_user.id not in MODERATOR_IDS:
            bot.reply_to(message, "❌ Нет прав.")
            return
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "❌ /arbitrate ID refund|penalty|ban")
            return
        try:
            order_id = int(parts[1])
        except:
            bot.reply_to(message, "❌ ID должно быть числом.")
            return
        action = parts[2].lower()
        order = get_order(order_id)
        if not order:
            bot.reply_to(message, "❌ Заказ не найден.")
            return
        if action == 'refund':
            db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            db.commit()
            bot.reply_to(message, f"✅ Заказ #{order_id} отменён, деньги возвращены.")
        elif action == 'penalty':
            add_rating(order[1], -1)
            bot.reply_to(message, f"✅ Заказчику #{order[1]} снижен рейтинг.")
        elif action == 'ban':
            db.execute("UPDATE users SET blocked = 1 WHERE id = ?", (order[1],))
            db.commit()
            bot.reply_to(message, f"✅ Заказчик #{order[1]} заблокирован.")
        else:
            bot.reply_to(message, "❌ Доступно: refund, penalty, ban")
    except Exception as e:
        logging.error(f"Ошибка в arbitrate_command: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ОБРАБОТЧИК ОТПРАВКИ СООБЩЕНИЙ ==========

@bot.callback_query_handler(func=lambda call: call.data.startswith('send_msg_'))
def handle_send_message(call):
    try:
        data = call.data.split('_')
        target_user_id = int(data[2])
        order_id = int(data[3]) if len(data) > 3 else 0
        
        user = get_user(call.from_user.id)
        if not user:
            bot.answer_callback_query(call.id, "❌ Нажмите /start", show_alert=True)
            return
        
        target_user = get_user_by_id(target_user_id)
        if not target_user:
            bot.answer_callback_query(call.id, "❌ Пользователь не найден", show_alert=True)
            return
        
        msg_data[call.from_user.id] = {'target': target_user_id, 'order_id': order_id}
        
        bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
        bot.send_message(
            call.message.chat.id,
            f"📝 Напишите сообщение для {target_user[2] or 'пользователя'}:\n"
            f"(для отмены отправьте /cancel)"
        )
    except Exception as e:
        logging.error(f"Ошибка в handle_send_message: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)

@bot.message_handler(commands=['cancel'])
def cancel_message(message):
    try:
        if message.from_user.id in msg_data:
            del msg_data[message.from_user.id]
            bot.reply_to(message, "❌ Отправка сообщения отменена.", reply_markup=get_main_kb(message.from_user.id))
        else:
            bot.reply_to(message, "❌ Нет активной отправки.")
    except Exception as e:
        logging.error(f"Ошибка в cancel_message: {e}")
        bot.reply_to(message, "❌ Ошибка.")

# ========== ПРИЁМ СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЕЙ ==========
@bot.message_handler(func=lambda m: m.from_user.id in msg_data)
def handle_user_message(message):
    try:
        uid = message.from_user.id
        if uid not in msg_data:
            return
        
        target_user_id = msg_data[uid]['target']
        order_id = msg_data[uid]['order_id']
        
        target_user = get_user_by_id(target_user_id)
        if not target_user:
            bot.reply_to(message, "❌ Пользователь не найден.")
            del msg_data[uid]
            return
        
        # Сохраняем сообщение в БД
        save_message(uid, target_user_id, order_id, message.text)
        
        # Отправляем уведомление получателю
        try:
            order_text = f" по заказу #{order_id}" if order_id != 0 else ""
            bot.send_message(
                target_user[1],
                f"📩 НОВОЕ СООБЩЕНИЕ{order_text}\n\n"
                f"От: {get_user(uid)[2] or 'Пользователь'}\n"
                f"{message.text}\n\n"
                f"📌 Чтобы ответить - используйте кнопку 'Написать' в меню заказа."
            )
        except:
            pass
        
        bot.reply_to(message, "✅ Сообщение отправлено!")
        
        # Если это модератор, то не удаляем данные, чтобы он мог писать снова
        if uid not in MODERATOR_IDS:
            del msg_data[uid]
        
        # Возвращаем меню
        user = get_user(uid)
        if user:
            if user[6] == 'rabotnik':
                bot.reply_to(message, "👷 Меню работника:", reply_markup=get_worker_kb())
            elif user[6] == 'zakazchik':
                bot.reply_to(message, "🏢 Меню заказчика:", reply_markup=get_customer_kb())
            elif user[6] == 'moderator' and uid in MODERATOR_IDS:
                bot.reply_to(message, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
        
    except Exception as e:
        logging.error(f"Ошибка в handle_user_message: {e}")
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
        
        # ========== СВЯЗЬ С МОДЕРАТОРОМ (из заказа) ==========
        if data.startswith('contact_mod_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if order:
                msg_data[user_id] = {'target': MODERATOR_IDS[0], 'order_id': order_id}
                bot.answer_callback_query(call.id, "📝 Напишите сообщение модератору", show_alert=False)
                bot.send_message(
                    call.message.chat.id,
                    f"📝 Напишите сообщение модератору по заказу #{order_id}:\n"
                    f"(для отмены отправьте /cancel)"
                )
        
        # ========== СВЯЗЬ С ЗАКАЗЧИКОМ ==========
        elif data.startswith('contact_customer_order_'):
            order_id = int(data.split('_')[3])
            order = get_order(order_id)
            if order:
                target_id = order[1]
                msg_data[user_id] = {'target': target_id, 'order_id': order_id}
                target_user = get_user_by_id(target_id)
                target_name = target_user[2] if target_user else "заказчиком"
                bot.answer_callback_query(call.id, f"📝 Напишите {target_name}", show_alert=False)
                bot.send_message(
                    call.message.chat.id,
                    f"📝 Напишите сообщение заказчику по заказу #{order_id}:\n"
                    f"(для отмены отправьте /cancel)"
                )
        
        # ========== СВЯЗЬ С РАБОТНИКОМ ==========
        elif data.startswith('contact_worker_order_'):
            order_id = int(data.split('_')[3])
            workers = get_workers_for_order(order_id)
            if workers:
                if len(workers) > 1:
                    kb = InlineKeyboardMarkup()
                    for w_id in workers:
                        w = get_user_by_id(w_id)
                        if w:
                            kb.add(InlineKeyboardButton(f"👤 {w[2] or 'Работник'}", callback_data=f"send_msg_{w_id}_{order_id}"))
                    bot.send_message(call.message.chat.id, "👥 Выберите работника:", reply_markup=kb)
                    bot.answer_callback_query(call.id)
                else:
                    target_id = workers[0]
                    msg_data[user_id] = {'target': target_id, 'order_id': order_id}
                    target_user = get_user_by_id(target_id)
                    target_name = target_user[2] if target_user else "работником"
                    bot.answer_callback_query(call.id, f"📝 Напишите {target_name}", show_alert=False)
                    bot.send_message(
                        call.message.chat.id,
                        f"📝 Напишите сообщение работнику по заказу #{order_id}:\n"
                        f"(для отмены отправьте /cancel)"
                    )
            else:
                bot.answer_callback_query(call.id, "❌ Нет работников у этого заказа", show_alert=True)
        
        # ========== ОБЫЧНАЯ ОТПРАВКА ==========
        elif data.startswith('contact_customer_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if order:
                target_id = order[1]
                msg_data[user_id] = {'target': target_id, 'order_id': order_id}
                bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
                bot.send_message(
                    call.message.chat.id,
                    f"📝 Напишите сообщение по заказу #{order_id}:\n"
                    f"(для отмены отправьте /cancel)"
                )
        
        elif data.startswith('contact_worker_'):
            order_id = int(data.split('_')[2])
            workers = get_workers_for_order(order_id)
            if workers:
                target_id = workers[0]
                msg_data[user_id] = {'target': target_id, 'order_id': order_id}
                bot.answer_callback_query(call.id, "📝 Напишите сообщение", show_alert=False)
                bot.send_message(
                    call.message.chat.id,
                    f"📝 Напишите сообщение по заказу #{order_id}:\n"
                    f"(для отмены отправьте /cancel)"
                )
            else:
                bot.answer_callback_query(call.id, "❌ Нет работников", show_alert=True)

        # ========== ВЗЯТЬ ЗАКАЗ ==========
        elif data.startswith('take_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            
            if user[6] != 'rabotnik':
                bot.answer_callback_query(call.id, "❌ Только для работников", show_alert=True)
                return
            
            # Проверяем, есть ли уже активные заказы у работника
            worker_orders = get_worker_orders(user[0])
            for wo in worker_orders:
                # Исключаем финальные статусы - можно брать новый заказ
                if wo[1] in ['waiting_approval', 'waiting_payout']:
                    continue
                if wo[1] in ['open', 'in_progress', 'ready_to_pay', 'paid', 'working']:
                    bot.answer_callback_query(
                        call.id, 
                        f"❌ У вас уже есть активный заказ #{wo[0]}.\nЗавершите его или откажитесь.", 
                        show_alert=True
                    )
                    return
            
            assigned = get_assignments(order_id)
            if user[0] in [a[0] for a in assigned]:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли этот заказ", show_alert=True)
                return
            
            # Добавляем в assignments
            db.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", 
                      (order_id, user[0], order[8]))
            db.commit()
            
            # Проверяем комплектность
            new_assigned = get_assignments(order_id)
            confirmed_count = sum(1 for a in new_assigned if a[1] == 1)
            total_workers = order[5]
            
            if len(new_assigned) >= total_workers:
                update_order_status(order_id, 'ready_to_pay')
                
                # Уведомляем заказчика
                try:
                    text = (
                        f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                        f"👥 Все {total_workers} работников собраны.\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"💰 Сумма к оплате: {order[6]} ₽\n"
                        f"💳 Переведите по СБП: {SBP_PHONE}\n\n"
                        f"📌 ПОЧЕМУ ОПЛАТА СЕЙЧАС?\n\n"
                        f"1️⃣ ЗАСТРАХОВАТЬ ВАШИ СРЕДСТВА\n"
                        f"   Деньги хранятся на нашем счёте до полного выполнения заказа.\n"
                        f"   Если работники сорвут сделку - мы вернём вам ВСЮ сумму.\n\n"
                        f"2️⃣ ГАРАНТИРОВАТЬ ВЫПЛАТУ РАБОТНИКАМ\n"
                        f"   Работники знают, что деньги уже зарезервированы.\n"
                        f"   Это мотивирует их выполнить работу качественно и в срок.\n\n"
                        f"3️⃣ ЗАЩИТИТЬ ОТ МОШЕННИКОВ\n"
                        f"   Мы не передаём деньги работникам до вашего подтверждения.\n\n"
                        f"✅ Ваши деньги в безопасности! Мы - гарант сделки."
                    )
                    bot.send_message(order[1], text, reply_markup=payment_kb(order_id))
                except:
                    pass
                
                # Уведомляем работников
                for worker_id in get_workers_for_order(order_id):
                    try:
                        worker = get_user_by_id(worker_id)
                        if worker:
                            bot.send_message(
                                worker[1],
                                f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                                f"👥 Все {total_workers} работников на месте.\n"
                                f"📍 Адрес: {order[3]}\n"
                                f"💰 Ваша выплата: {order[8]} ₽\n"
                                f"📌 Ожидайте подтверждения оплаты от заказчика."
                            )
                    except:
                        pass
                
                # Уведомляем модератора
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(
                            m,
                            f"📊 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                            f"👤 Заказчик: {order[2]}\n"
                            f"📍 Адрес: {order[3]}\n"
                            f"👥 Работников: {total_workers}\n"
                            f"💰 Сумма: {order[6]} ₽\n"
                            f"📊 Комиссия: {order[7]} ₽"
                        )
                    except:
                        pass
                
                bot.answer_callback_query(
                    call.id, 
                    f"✅ Заказ #{order_id} укомплектован!\nЗаказчик оплачивает.", 
                    show_alert=True
                )
            else:
                bot.answer_callback_query(
                    call.id, 
                    f"✅ Вы взяли заказ #{order_id}!\nОсталось {total_workers - len(new_assigned)} чел.", 
                    show_alert=True
                )
            
            # Показываем работнику кнопку "Я на месте"
            bot.edit_message_text(
                f"✅ Вы взяли заказ #{order_id}!\n\n"
                f"📍 ВАЖНО! Подтвердите, что вы на месте.\n\n"
                f"После вашего подтверждения:\n"
                f"💰 Заказчик переведёт деньги на счёт сервиса\n"
                f"📌 Это гарантирует вашу выплату\n\n"
                f"Если вы НЕ нажмёте 'Я на месте':\n"
                f"❌ Заказчик не сможет оплатить\n"
                f"❌ Вы не получите выплату\n\n"
                f"Вы уверены, что готовы выполнить заказ?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=confirm_take_kb(order_id)
            )
        
        # ========== ПОДТВЕРДИТЬ "НА МЕСТЕ" ==========
        elif data.startswith('confirm_place_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order:
                bot.answer_callback_query(call.id, "❌ Заказ не найден", show_alert=True)
                return
            
            if order[9] not in ['open', 'in_progress', 'ready_to_pay']:
                bot.answer_callback_query(call.id, "❌ Заказ уже не в этой стадии", show_alert=True)
                return
            
            confirm_worker_on_place(order_id, user[0])
            
            bot.answer_callback_query(call.id, "✅ Вы подтвердили, что на месте!", show_alert=True)
            bot.edit_message_text(
                f"✅ Вы подтвердили, что на месте!\n\n"
                f"📌 Что дальше?\n"
                f"1. Дождитесь, пока все работники соберутся\n"
                f"2. Заказчик оплатит заказ\n"
                f"3. Вы получите уведомление о начале работы\n\n"
                f"💰 Ваша выплата: {order[8]} ₽",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Проверяем, все ли подтвердили
            assigned = get_assignments(order_id)
            all_confirmed = all(a[1] == 1 for a in assigned)
            
            if all_confirmed and order[9] == 'open':
                # Обновляем статус, если ещё не обновили
                update_order_status(order_id, 'ready_to_pay')
                
                # Уведомляем заказчика
                try:
                    text = (
                        f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                        f"👥 Все работники подтвердили, что они на месте.\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"💰 Сумма к оплате: {order[6]} ₽\n"
                        f"💳 Переведите по СБП: {SBP_PHONE}\n\n"
                        f"📌 ПОЧЕМУ ОПЛАТА СЕЙЧАС?\n\n"
                        f"1️⃣ ЗАСТРАХОВАТЬ ВАШИ СРЕДСТВА\n"
                        f"   Деньги хранятся на нашем счёте до полного выполнения заказа.\n"
                        f"   Если работники сорвут сделку - мы вернём вам ВСЮ сумму.\n\n"
                        f"2️⃣ ГАРАНТИРОВАТЬ ВЫПЛАТУ РАБОТНИКАМ\n"
                        f"   Работники знают, что деньги уже зарезервированы.\n"
                        f"   Это мотивирует их выполнить работу качественно и в срок.\n\n"
                        f"3️⃣ ЗАЩИТИТЬ ОТ МОШЕННИКОВ\n"
                        f"   Мы не передаём деньги работникам до вашего подтверждения.\n\n"
                        f"✅ Ваши деньги в безопасности! Мы - гарант сделки."
                    )
                    bot.send_message(order[1], text, reply_markup=payment_kb(order_id))
                except:
                    pass
                
                # Уведомляем работников
                for worker_id in get_workers_for_order(order_id):
                    try:
                        worker = get_user_by_id(worker_id)
                        if worker:
                            bot.send_message(
                                worker[1],
                                f"🔔 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                                f"👥 Все работники на месте.\n"
                                f"📍 Адрес: {order[3]}\n"
                                f"💰 Ваша выплата: {order[8]} ₽\n"
                                f"📌 Ожидайте подтверждения оплаты от заказчика."
                            )
                    except:
                        pass
                
                # Уведомляем модератора
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(
                            m,
                            f"📊 ЗАКАЗ #{order_id} УКОМПЛЕКТОВАН!\n\n"
                            f"👤 Заказчик: {order[2]}\n"
                            f"📍 Адрес: {order[3]}\n"
                            f"👥 Работников: {order[5]}\n"
                            f"💰 Сумма: {order[6]} ₽\n"
                            f"📊 Комиссия: {order[7]} ₽"
                        )
                    except:
                        pass
        
        # ========== ОТКАЗАТЬСЯ ОТ ЗАКАЗА ==========
        elif data.startswith('cancel_take_'):
            order_id = int(data.split('_')[2])
            
            db.execute("DELETE FROM assignments WHERE order_id = ? AND user_id = ?", (order_id, user[0]))
            db.commit()
            
            bot.answer_callback_query(call.id, "❌ Вы отказались от заказа", show_alert=True)
            bot.edit_message_text(
                "❌ Вы отказались от заказа",
                call.message.chat.id,
                call.message.message_id
            )
        
        # ========== ЗАКАЗЧИК ОПЛАТИЛ ==========
        elif data.startswith('i_paid_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'ready_to_pay':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе оплаты", show_alert=True)
                return
            
            if user[0] != order[1]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            update_order_status(order_id, 'paid')
            db.execute("UPDATE orders SET paid_at = ? WHERE id = ?", (datetime.now().isoformat(), order_id))
            db.commit()
            
            bot.answer_callback_query(call.id, "✅ Оплата подтверждена! Ожидайте подтверждения.", show_alert=True)
            bot.edit_message_text(
                f"✅ Вы подтвердили оплату заказа #{order_id}!\n\n"
                f"📌 Ожидайте подтверждения от сервиса.\n"
                f"После этого работники приступят к работе.",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Уведомляем модератора
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(
                        m,
                        f"💰 ЗАКАЗ #{order_id} ОПЛАЧЕН!\n\n"
                        f"👤 Заказчик: {order[2]}\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"💰 Сумма: {order[6]} ₽\n\n"
                        f"📌 Подтвердите оплату:",
                        reply_markup=moderator_payment_kb(order_id)
                    )
                except:
                    pass
        
        # ========== МОДЕРАТОР ПОДТВЕРЖДАЕТ ОПЛАТУ ==========
        elif data.startswith('confirm_payment_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'paid':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе оплаты", show_alert=True)
                return
            
            if user[0] not in MODERATOR_IDS:
                bot.answer_callback_query(call.id, "❌ Нет прав", show_alert=True)
                return
            
            update_order_status(order_id, 'working')
            db.commit()
            
            bot.answer_callback_query(call.id, f"✅ Оплата заказа #{order_id} подтверждена!", show_alert=True)
            bot.edit_message_text(
                f"✅ Оплата заказа #{order_id} подтверждена!\n\n"
                f"📌 Работники приступают к работе.",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Уведомляем работников
            for worker_id in get_workers_for_order(order_id):
                try:
                    worker = get_user_by_id(worker_id)
                    if worker:
                        bot.send_message(
                            worker[1],
                            f"✅ ЗАКАЗ #{order_id} ОПЛАЧЕН!\n\n"
                            f"💰 Ваша выплата: {order[8]} ₽\n"
                            f"📌 Деньги зарезервированы на счёте сервиса.\n\n"
                            f"🔧 МОЖНО ПРИСТУПАТЬ К РАБОТЕ!\n"
                            f"📍 Адрес: {order[3]}\n"
                            f"⏱ Часы: {order[4]} ч.\n\n"
                            f"📸 После выполнения отправьте фото:",
                            reply_markup=worker_photo_kb(order_id)
                        )
                except:
                    pass
            
            # Уведомляем заказчика
            try:
                bot.send_message(
                    order[1],
                    f"✅ ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН!\n\n"
                    f"📍 Адрес: {order[3]}\n"
                    f"⏱ Часы: {order[4]} ч.\n"
                    f"👥 Работников: {order[5]}\n\n"
                    f"📌 Работники приступили к работе.\n"
                    f"Вы получите уведомление, когда она будет выполнена."
                )
            except:
                pass
        
        # ========== ОТПРАВИТЬ ФОТО (работник) ==========
        elif data.startswith('send_photo_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'working':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе работы", show_alert=True)
                return
            
            assigned = get_assignments(order_id)
            if user[0] not in [a[0] for a in assigned]:
                bot.answer_callback_query(call.id, "❌ Вы не взяли этот заказ", show_alert=True)
                return
            
            bot.answer_callback_query(call.id, "📸 Отправьте фото выполненной работы", show_alert=True)
            bot.send_message(
                call.message.chat.id,
                f"📸 Отправьте фото выполненной работы для заказа #{order_id}\n\n"
                f"📍 Адрес: {order[3]}\n"
                f"⏱ Часы: {order[4]} ч.\n\n"
                f"📌 Фото обязательно для подтверждения заказчиком."
            )
            order_data[f'waiting_photo_{user[0]}_{order_id}'] = True
        
        # ========== ЗАКАЗЧИК ОДОБРЯЕТ РАБОТУ ==========
        elif data.startswith('approve_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'waiting_approval':
                bot.answer_callback_query(call.id, "❌ Заказ не ждёт подтверждения", show_alert=True)
                return
            
            if user[0] != order[1]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            update_order_status(order_id, 'waiting_payout')
            db.execute("UPDATE orders SET completed_at = ? WHERE id = ?", (datetime.now().isoformat(), order_id))
            db.commit()
            
            bot.answer_callback_query(call.id, "✅ Работа подтверждена!", show_alert=True)
            bot.edit_message_text(
                f"✅ Заказ #{order_id} выполнен!\n\n"
                f"💰 Вы перевели: {order[6]} ₽\n"
                f"📌 Работники получат оплату после подтверждения сервиса.\n\n"
                f"Спасибо за доверие!",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Уведомляем модератора
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(
                        m,
                        f"✅ ЗАКАЗ #{order_id} ВЫПОЛНЕН!\n\n"
                        f"👤 Заказчик подтвердил выполнение.\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"💰 Сумма: {order[6]} ₽\n"
                        f"📊 Комиссия: {order[7]} ₽\n"
                        f"💵 Выплата работникам: {order[8]} ₽/чел\n\n"
                        f"📌 Переведите деньги работникам и подтвердите:",
                        reply_markup=moderator_payout_kb(order_id)
                    )
                except:
                    pass
            
            # Уведомляем работников
            for worker_id in get_workers_for_order(order_id):
                try:
                    worker = get_user_by_id(worker_id)
                    if worker:
                        bot.send_message(
                            worker[1],
                            f"✅ Заказ #{order_id} одобрен заказчиком!\n\n"
                            f"💵 Ваша выплата: {order[8]} ₽\n"
                            f"📌 Ожидайте перевода от сервиса."
                        )
                except:
                    pass
        
        # ========== ЗАКАЗЧИК ОТКЛОНЯЕТ РАБОТУ ==========
        elif data.startswith('reject_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'waiting_approval':
                bot.answer_callback_query(call.id, "❌ Заказ не ждёт подтверждения", show_alert=True)
                return
            
            if user[0] != order[1]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            bot.answer_callback_query(call.id, "❌ Работа отклонена", show_alert=True)
            bot.edit_message_text(
                f"❌ Работа по заказу #{order_id} отклонена.\n\n"
                f"📌 Свяжитесь с модератором для решения ситуации.",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Уведомляем модератора
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(
                        m,
                        f"❌ ЗАКАЗ #{order_id} ОТКЛОНЁН ЗАКАЗЧИКОМ!\n\n"
                        f"👤 Заказчик: {order[2]}\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"📌 Требуется арбитраж."
                    )
                except:
                    pass
        
        # ========== МОДЕРАТОР ВЫПЛАТИЛ РАБОТНИКАМ ==========
        elif data.startswith('confirm_payout_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'waiting_payout':
                bot.answer_callback_query(call.id, "❌ Заказ не в статусе выплаты", show_alert=True)
                return
            
            if user[0] not in MODERATOR_IDS:
                bot.answer_callback_query(call.id, "❌ Нет прав", show_alert=True)
                return
            
            update_order_status(order_id, 'completed')
            db.commit()
            
            bot.answer_callback_query(call.id, f"✅ Выплата по заказу #{order_id} подтверждена!", show_alert=True)
            bot.edit_message_text(
                f"✅ Выплата по заказу #{order_id} подтверждена!\n\n"
                f"📌 Заказ завершён.",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Уведомляем заказчика
            try:
                bot.send_message(
                    order[1],
                    f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n\n"
                    f"💰 Работники получили оплату.\n"
                    f"Спасибо за доверие!"
                )
            except:
                pass
            
            # Уведомляем работников
            for worker_id in get_workers_for_order(order_id):
                try:
                    worker = get_user_by_id(worker_id)
                    if worker:
                        bot.send_message(
                            worker[1],
                            f"✅ ЗАКАЗ #{order_id} ЗАВЕРШЁН!\n\n"
                            f"💵 Вы получили выплату: {order[8]} ₽\n"
                            f"Спасибо за работу!"
                        )
                except:
                    pass
        
        # ========== ОТМЕНА ЗАКАЗА (заказчик) ==========
        elif data.startswith('cancel_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[1] != user[0]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            if user[6] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            
            if order[9] not in ['open', 'in_progress', 'ready_to_pay']:
                bot.answer_callback_query(call.id, "❌ Нельзя отменить", show_alert=True)
                return
            
            update_order_status(order_id, 'cancelled')
            db.commit()
            
            bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} отменён!", show_alert=True)
            bot.edit_message_text(
                f"❌ ЗАКАЗ #{order_id} ОТМЕНЁН",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Уведомляем работников
            for worker_id in get_workers_for_order(order_id):
                try:
                    worker = get_user_by_id(worker_id)
                    if worker:
                        bot.send_message(
                            worker[1],
                            f"❌ Заказ #{order_id} отменён заказчиком."
                        )
                except:
                    pass
            
            # Уведомляем модератора
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(m, f"❌ Заказ #{order_id} отменён заказчиком")
                except:
                    pass
        
        # ========== ЗАВЕРШЕНИЕ ЗАКАЗА (заказчик) ==========
        elif data.startswith('complete_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[1] != user[0]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            if user[6] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            
            if order[9] != 'working':
                bot.answer_callback_query(call.id, "❌ Заказ не в работе", show_alert=True)
                return
            
            workers_with_photo = get_assignments_with_photo(order_id)
            if not workers_with_photo:
                bot.answer_callback_query(
                    call.id, 
                    "❌ Работники ещё не отправили фото выполненной работы.\nДождитесь фото.", 
                    show_alert=True
                )
                return
            
            update_order_status(order_id, 'waiting_approval')
            db.commit()
            
            bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} ожидает подтверждения!", show_alert=True)
            bot.edit_message_text(
                f"📸 Заказ #{order_id} выполнен!\n\n"
                f"📍 Адрес: {order[3]}\n"
                f"⏱ Часы: {order[4]} ч.\n\n"
                f"✅ Подтвердите, что работа выполнена качественно:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=approve_kb(order_id)
            )
        
        else:
            bot.answer_callback_query(call.id, "❌ Неизвестная команда", show_alert=True)
            
    except Exception as e:
        logging.error(f"Ошибка в callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# ========== ОБРАБОТЧИК ФОТО ==========

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "❌ Нажмите /start")
            return
        
        # Проверяем, ждём ли мы фото от этого пользователя
        waiting_key = f'waiting_photo_{uid}_'
        order_id = None
        
        for key in list(order_data.keys()):
            if key.startswith(waiting_key):
                order_id = int(key.split('_')[3])
                break
        
        if not order_id:
            bot.reply_to(message, "❌ Нет активного запроса на фото.\nИспользуйте кнопку '📸 Отправить фото'.")
            return
        
        # Удаляем состояние ожидания (безопасно, даже если ключа нет)
        order_data.pop(f'waiting_photo_{uid}_{order_id}', None)
        
        # Сохраняем фото
        photo_file_id = message.photo[-1].file_id
        set_worker_photo(order_id, user[0], photo_file_id)
        
        bot.reply_to(message, f"✅ Фото для заказа #{order_id} сохранено!\n\nОжидайте подтверждения от заказчика.")
        
        # Проверяем, все ли работники отправили фото
        order = get_order(order_id)
        if order:
            workers_in_order = get_workers_for_order(order_id)
            workers_with_photo = get_assignments_with_photo(order_id)
            
            if len(workers_with_photo) == len(workers_in_order):
                # Все отправили фото - уведомляем заказчика
                try:
                    bot.send_message(
                        order[1],
                        f"📸 Все работники отправили фото по заказу #{order_id}!\n\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"⏱ Часы: {order[4]} ч.\n\n"
                        f"✅ Подтвердите, что работа выполнена качественно:",
                        reply_markup=approve_kb(order_id)
                    )
                except:
                    pass
                
                # Обновляем статус
                if order[9] == 'working':
                    update_order_status(order_id, 'waiting_approval')
                    
                    # Уведомляем модератора
                    for m in MODERATOR_IDS:
                        try:
                            bot.send_message(
                                m,
                                f"📸 Все работники отправили фото по заказу #{order_id}!\n\n"
                                f"👤 Заказчик: {order[2]}\n"
                                f"📍 Адрес: {order[3]}\n"
                                f"📌 Ожидаем подтверждения от заказчика."
                            )
                        except:
                            pass
        
    except Exception as e:
        logging.error(f"Ошибка в handle_photo: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ЗАБЛОКИРОВАННЫЙ ==========

@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator_blocked(message):
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
        logging.error(f"Ошибка в contact_moderator_blocked: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== FALLBACK ==========

@bot.message_handler(func=lambda m: True)
def fallback(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "Нажмите /start для начала работы.", reply_markup=get_main_kb(uid))
            return
        
        if user[6] == 'moderator' and uid in MODERATOR_IDS:
            bot.reply_to(message, "🛡️ Панель модератора:", reply_markup=get_moderator_kb())
        elif user[6] == 'rabotnik':
            bot.reply_to(message, "👷 Меню работника:", reply_markup=get_worker_kb())
        elif user[6] == 'zakazchik':
            bot.reply_to(message, "🏢 Меню заказчика:", reply_markup=get_customer_kb())
        else:
            bot.reply_to(message, "Используйте кнопки меню.", reply_markup=get_main_kb(uid))
    except Exception as e:
        logging.error(f"Ошибка в fallback: {e}")
        bot.reply_to(message, "Используйте кнопки меню.", reply_markup=get_main_kb(None))

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    logging.info("🚀 Бот запущен!")
    print("🤖 Бот Юрга-Подработка запущен!")
    print(f"📊 Модераторы: {MODERATOR_IDS}")
    print(f"💳 СБП: {SBP_PHONE}")
    print("✅ Готов к работе!")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            logging.error(f"⚠️ Ошибка в polling: {e}")
            print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
