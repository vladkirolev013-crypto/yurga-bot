import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
from datetime import datetime
import threading
import time

TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'
MODERATOR_IDS = [8746212340]
bot = telebot.TeleBot(TOKEN)

# ========== ОПТИМИЗАЦИЯ БД ==========
# Используем постоянное соединение
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
        print("✅ БД инициализирована")
    
    def execute(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor
    
    def commit(self):
        self.conn.commit()
    
    def close(self):
        self.conn.close()

db = Database()

# ========== БЫСТРЫЕ ФУНКЦИИ ==========
def get_user(telegram_id):
    try:
        c = db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return c.fetchone()
    except:
        return None

def get_user_by_id(user_id):
    try:
        c = db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return c.fetchone()
    except:
        return None

def update_user(telegram_id, field, value):
    try:
        db.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
        db.commit()
        return True
    except:
        return False

def get_order(order_id):
    try:
        c = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        return c.fetchone()
    except:
        return None

def get_open_orders():
    try:
        c = db.execute("SELECT id, payout_per_person FROM orders WHERE status = 'open' ORDER BY created_at DESC")
        return c.fetchall()
    except:
        return []

def get_assignments(order_id):
    try:
        c = db.execute("SELECT user_id FROM assignments WHERE order_id = ?", (order_id,))
        return [r[0] for r in c.fetchall()]
    except:
        return []

def get_workers():
    try:
        c = db.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND on_shift = 1 AND blocked = 0")
        return [r[0] for r in c.fetchall()]
    except:
        return []

def cancel_order(order_id):
    try:
        db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'open'", (order_id,))
        db.commit()
        return True
    except:
        return False

def add_rating(user_id, delta):
    try:
        db.execute("UPDATE users SET rating = rating + ? WHERE id = ?", (delta, user_id))
        db.commit()
        c = db.execute("SELECT rating, telegram_id FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        if row and row[0] <= 5:
            db.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
            db.commit()
            try:
                bot.send_message(row[1], "⚠️ Рейтинг ≤ 5. Вы заблокированы.")
            except:
                pass
        return True
    except:
        return False

def rate_customer(customer_id, delta):
    try:
        db.execute("UPDATE users SET customer_rating = customer_rating + ? WHERE id = ?", (delta, customer_id))
        db.commit()
        c = db.execute("SELECT customer_rating, telegram_id FROM users WHERE id = ?", (customer_id,))
        return c.fetchone()
    except:
        return None

def block_user_by_phone(phone):
    try:
        db.execute("UPDATE users SET blocked = 1 WHERE phone = ?", (phone,))
        db.commit()
        return 1
    except:
        return 0

def get_all_workers():
    try:
        c = db.execute("SELECT id, name, phone, rating, blocked, on_shift FROM users WHERE role = 'rabotnik' ORDER BY rating DESC")
        return c.fetchall()
    except:
        return []

def get_all_customers():
    try:
        c = db.execute("SELECT id, name, phone, customer_rating, blocked FROM users WHERE role = 'zakazchik' ORDER BY customer_rating DESC")
        return c.fetchall()
    except:
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
        return c.fetchall()
    except:
        return []

def get_worker_orders(user_id):
    try:
        c = db.execute('''SELECT o.id, o.status, a.payout, o.zakazchik_name, o.address
                     FROM assignments a 
                     JOIN orders o ON a.order_id = o.id 
                     WHERE a.user_id = ?
                     ORDER BY o.created_at DESC''', (user_id,))
        return c.fetchall()
    except:
        return []

# ========== БЫСТРЫЕ КЛАВИАТУРЫ (кэшируем) ==========
_main_kb = None
_worker_kb = None
_customer_kb = None
_moderator_kb = None
_blocked_kb = None

def get_main_kb():
    global _main_kb
    if _main_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
        kb.row(KeyboardButton("🛡️ Я модератор"))
        _main_kb = kb
    return _main_kb

def get_worker_kb():
    global _worker_kb
    if _worker_kb is None:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
        kb.row(KeyboardButton("⬅️ Назад"))
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
        kb.row(KeyboardButton("⭐ Оценить"), KeyboardButton("⭐ Оценить заказчика"))
        kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блок"))
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
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять", callback_data=f"take_{order_id}"))
    return kb

def confirm_take_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Да", callback_data=f"confirm_take_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Нет", callback_data="cancel_take"))
    return kb

# ========== ОБРАБОТЧИКИ ==========
@bot.message_handler(commands=['start'])
def start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            db.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (uid,))
            db.commit()
            bot.reply_to(message, "👋 Выберите роль:", reply_markup=get_main_kb())
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Заблокированы.", reply_markup=get_blocked_kb())
            return
        
        role = user[6]
        if role == 'rabotnik':
            bot.reply_to(message, "👷 Меню:", reply_markup=get_worker_kb())
        elif role == 'zakazchik':
            bot.reply_to(message, "🏢 Меню:", reply_markup=get_customer_kb())
        elif role == 'moderator':
            bot.reply_to(message, "🛡️ Меню:", reply_markup=get_moderator_kb())
        else:
            bot.reply_to(message, "👋 Выберите роль:", reply_markup=get_main_kb())
    except:
        pass

@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "❌ /start")
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Заблокированы.", reply_markup=get_blocked_kb())
            return
        
        role_map = {'👷 Я работник': 'rabotnik', '🏢 Я заказчик': 'zakazchik', '🛡️ Я модератор': 'moderator'}
        role = role_map[message.text]
        
        if role == 'moderator' and uid not in MODERATOR_IDS:
            bot.reply_to(message, "❌ Нет прав.")
            return
        
        update_user(uid, 'role', role)
        
        if role == 'rabotnik':
            bot.reply_to(message, "✅ Работник.", reply_markup=get_worker_kb())
        elif role == 'zakazchik':
            bot.reply_to(message, "✅ Заказчик.", reply_markup=get_customer_kb())
        else:
            bot.reply_to(message, "✅ Модератор.", reply_markup=get_moderator_kb())
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back_to_main(message):
    bot.reply_to(message, "📱 Главное:", reply_markup=get_main_kb())

# ========== РЕГИСТРАЦИЯ ==========
reg_data = {}

@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def reg_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[10] == 1 or user[9] == 1:
            return
        
        role = user[6]
        if role not in ('rabotnik', 'zakazchik'):
            bot.reply_to(message, "❌ Выберите роль.")
            return
        
        reg_data[uid] = {}
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("✅ Да"), KeyboardButton("❌ Нет"))
        bot.send_message(message.chat.id,
            "📜 Условия сервиса:\n"
            "1. Сервис - посредник\n"
            "2. Гарантия выплат\n"
            "3. Ответственность сторон\n"
            "4. Оплата наличными - без гарантий\n\n"
            "✅ Принимаете?", reply_markup=kb)
    except:
        pass

@bot.message_handler(func=lambda m: m.text in ['✅ Да', '❌ Нет'])
def handle_agreement(message):
    try:
        uid = message.from_user.id
        
        if message.text == '❌ Нет':
            bot.reply_to(message, "❌ Отмена.", reply_markup=get_main_kb())
            if uid in reg_data:
                del reg_data[uid]
            return
        
        user = get_user(uid)
        if not user:
            return
        
        update_user(uid, 'agreement_accepted', 1)
        role = user[6]
        
        if role == 'rabotnik':
            msg = bot.reply_to(message, "📝 ФИО:")
            bot.register_next_step_handler(msg, get_worker_name, uid)
        else:
            msg = bot.reply_to(message, "📝 ФИО:")
            bot.register_next_step_handler(msg, get_customer_name, uid)
    except:
        pass

def get_worker_name(message, uid):
    try:
        reg_data[uid]['name'] = message.text
        msg = bot.reply_to(message, "📞 Телефон:")
        bot.register_next_step_handler(msg, get_worker_phone, uid)
    except:
        pass

def get_worker_phone(message, uid):
    try:
        reg_data[uid]['phone'] = message.text
        msg = bot.reply_to(message, "💳 Карта:")
        bot.register_next_step_handler(msg, get_worker_bank, uid)
    except:
        pass

def get_worker_bank(message, uid):
    try:
        reg_data[uid]['bank'] = message.text
        msg = bot.reply_to(message, "📝 Инициалы:")
        bot.register_next_step_handler(msg, finish_worker_reg, uid)
    except:
        pass

def finish_worker_reg(message, uid):
    try:
        db.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
                  (reg_data[uid]['name'], reg_data[uid]['phone'], reg_data[uid]['bank'], message.text, uid))
        db.commit()
        del reg_data[uid]
        bot.reply_to(message, "✅ Регистрация завершена!", reply_markup=get_worker_kb())
    except:
        pass

def get_customer_name(message, uid):
    try:
        reg_data[uid]['name'] = message.text
        msg = bot.reply_to(message, "📞 Телефон:")
        bot.register_next_step_handler(msg, get_customer_phone, uid)
    except:
        pass

def get_customer_phone(message, uid):
    try:
        reg_data[uid]['phone'] = message.text
        finish_customer_reg(message, uid)
    except:
        pass

def finish_customer_reg(message, uid):
    try:
        db.execute("UPDATE users SET name=?, phone=? WHERE telegram_id=?",
                  (reg_data[uid]['name'], reg_data[uid]['phone'], uid))
        db.commit()
        del reg_data[uid]
        bot.reply_to(message, "✅ Регистрация завершена!", reply_markup=get_customer_kb())
    except:
        pass

# ========== РАБОТНИК ==========
@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user[6] != 'rabotnik' or user[10] == 1 or user[9] == 0:
            return
        
        orders = get_open_orders()
        if not orders:
            bot.reply_to(message, "📭 Нет заказов.")
            return
        
        for o in orders:
            order = get_order(o[0])
            if not order:
                continue
            text = f"🆔 #{o[0]}\n💵 {o[1]} ₽\n📍 {order[3]}\n⏱ {order[4]} ч\n👥 {order[5]} чел"
            bot.send_message(message.chat.id, text, reply_markup=order_inline_kb(o[0], False))
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user[6] != 'rabotnik':
            return
        
        orders = get_worker_orders(user[0])
        if not orders:
            bot.reply_to(message, "💰 Нет выплат.")
            return
        
        total = 0
        text = "💰 Выплаты:\n"
        for o in orders:
            status = {'open':'🟢','in_progress':'🟡','completed':'✅','cancelled':'❌'}.get(o[1], '❓')
            text += f"{status} #{o[0]}: {o[2]}₽\n"
            if o[1] == 'completed':
                total += o[2]
        text += f"\n💰 Итого: {total}₽"
        bot.reply_to(message, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '👤 Профиль')
def profile(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user:
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Заблокированы.", reply_markup=get_blocked_kb())
            return
        
        roles = {'rabotnik':'👷 Работник','zakazchik':'🏢 Заказчик','moderator':'🛡️ Модератор'}
        text = f"👤 Профиль\n\nИмя: {user[2] or '-'}\nТелефон: {user[3] or '-'}\nРоль: {roles.get(user[6], '-')}\nРейтинг: {user[7]}\nСоглашение: {'✅' if user[9] else '❌'}\nБлок: {'🔒' if user[10] else '✅'}"
        bot.reply_to(message, text)
    except:
        pass

# ========== ЗАКАЗЧИК ==========
order_data = {}

@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user[6] != 'zakazchik' or user[10] == 1 or user[9] == 0:
            return
        
        order_data[uid] = {}
        msg = bot.reply_to(message, "📍 Адрес:")
        bot.register_next_step_handler(msg, get_order_address, uid)
    except:
        pass

def get_order_address(message, uid):
    try:
        order_data[uid]['address'] = message.text
        msg = bot.reply_to(message, "⏱ Часы:")
        bot.register_next_step_handler(msg, get_order_hours, uid)
    except:
        pass

def get_order_hours(message, uid):
    try:
        hours = int(message.text)
        if hours <= 0:
            raise ValueError
        order_data[uid]['hours'] = hours
        msg = bot.reply_to(message, "👥 Человек:")
        bot.register_next_step_handler(msg, get_order_people, uid)
    except:
        msg = bot.reply_to(message, "⏱ Часы (число):")
        bot.register_next_step_handler(msg, get_order_hours, uid)

def get_order_people(message, uid):
    try:
        people = int(message.text)
        if people <= 0:
            raise ValueError
        
        user = get_user(uid)
        hours = order_data[uid]['hours']
        total = hours * people * 500
        commission = hours * people * 50
        payout = (total - commission) // people
        name = user[2] if user[2] else "Заказчик"
        
        db.execute('''INSERT INTO orders 
                     (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user[0], name, order_data[uid]['address'], hours, people, total, commission, payout, datetime.now().isoformat()))
        db.commit()
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        del order_data[uid]
        
        bot.reply_to(message, f"✅ Заказ #{order_id} создан!\n💰 {total} ₽\n💵 {payout} ₽/чел", reply_markup=get_customer_kb())
        
        # Уведомляем работников (асинхронно)
        workers = get_workers()
        if workers:
            text = f"🔔 Новый заказ #{order_id}\n💵 {payout} ₽\n📍 {order_data[uid]['address'] if uid in order_data else ''}\n⏱ {hours} ч\n👥 {people} чел"
            for w in workers:
                try:
                    bot.send_message(w, text)
                except:
                    pass
    except:
        msg = bot.reply_to(message, "👥 Человек (число):")
        bot.register_next_step_handler(msg, get_order_people, uid)

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_customer(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user[6] != 'zakazchik':
            return
        
        orders = get_customer_orders_with_details(user[0])
        if not orders:
            bot.reply_to(message, "📭 Нет заказов.")
            return
        
        status_map = {'open':'🟢 Открыт','in_progress':'🟡 В работе','completed':'✅ Завершён','cancelled':'❌ Отменён'}
        
        for o in orders:
            text = f"🆔 #{o[0]}\n💰 {o[1]} ₽\n📊 {status_map.get(o[2], o[2])}\n👥 {o[4]}/{o[5]}\n💵 {o[3]} ₽/чел"
            if o[2] in ('open', 'in_progress'):
                bot.send_message(message.chat.id, text, reply_markup=order_inline_kb(o[0], True))
            else:
                bot.send_message(message.chat.id, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user[6] != 'zakazchik':
            return
        
        msg = bot.reply_to(message, "📝 Текст жалобы:")
        bot.register_next_step_handler(msg, send_complaint, uid)
    except:
        pass

def send_complaint(message, uid):
    try:
        user = get_user(uid)
        text = f"⚠️ ЖАЛОБА\n\nОт: {user[2] or 'без имени'} (ID {uid})\nТел: {user[3] or '-'}\n\n{message.text}"
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, text)
            except:
                pass
        bot.reply_to(message, "✅ Отправлено.", reply_markup=get_customer_kb())
    except:
        pass

# ========== МОДЕРАТОР ==========
@bot.message_handler(func=lambda m: m.text == '💰 Выплаты' and m.from_user.id in MODERATOR_IDS)
def mod_payouts(message):
    try:
        total = db.execute("SELECT SUM(payout) FROM assignments").fetchone()[0] or 0
        count = db.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] or 0
        bot.reply_to(message, f"💰 Выплаты:\n💵 {total} ₽\n👥 {count}")
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '🟡 Активные' and m.from_user.id in MODERATOR_IDS)
def mod_active(message):
    try:
        rows = db.execute("SELECT * FROM orders WHERE status IN ('open', 'in_progress')").fetchall()
        if not rows:
            bot.reply_to(message, "🟡 Нет активных.")
            return
        for o in rows:
            text = f"🆔 #{o[0]}\n👤 {o[2]}\n📍 {o[3]}\n⏱ {o[4]}ч 👥 {o[5]}чел\n💰 {o[6]}₽\n💵 {o[8]}₽/чел\n📊 {o[9]}"
            bot.send_message(message.chat.id, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '✅ Завершённые' and m.from_user.id in MODERATOR_IDS)
def mod_completed(message):
    try:
        rows = db.execute("SELECT * FROM orders WHERE status = 'completed'").fetchall()
        if not rows:
            bot.reply_to(message, "✅ Нет завершённых.")
            return
        for o in rows:
            text = f"✅ #{o[0]}\n👤 {o[2]}\n📍 {o[3]}\n⏱ {o[4]}ч\n💰 {o[6]}₽"
            bot.send_message(message.chat.id, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '👥 Работники' and m.from_user.id in MODERATOR_IDS)
def mod_workers(message):
    try:
        workers = get_all_workers()
        if not workers:
            bot.reply_to(message, "👥 Нет работников.")
            return
        text = "👥 Работники:\n"
        for w in workers[:20]:
            status = "🟢" if w[5] else "🔴"
            block = "🔒" if w[4] else "✅"
            text += f"{status}{block} {w[0]}: {w[1]} ⭐{w[3]}\n"
        bot.reply_to(message, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '🏢 Заказчики' and m.from_user.id in MODERATOR_IDS)
def mod_customers(message):
    try:
        customers = get_all_customers()
        if not customers:
            bot.reply_to(message, "🏢 Нет заказчиков.")
            return
        text = "🏢 Заказчики:\n"
        for c in customers[:20]:
            block = "🔒" if c[4] else "✅"
            text += f"{block} {c[0]}: {c[1]} ⭐{c[3]}\n"
        bot.reply_to(message, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '📊 Статистика' and m.from_user.id in MODERATOR_IDS)
def mod_stats(message):
    try:
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        workers = db.execute("SELECT COUNT(*) FROM users WHERE role = 'rabotnik'").fetchone()[0]
        customers = db.execute("SELECT COUNT(*) FROM users WHERE role = 'zakazchik'").fetchone()[0]
        total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        completed = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'").fetchone()[0]
        open_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status = 'open'").fetchone()[0]
        total_payouts = db.execute("SELECT SUM(payout) FROM assignments").fetchone()[0] or 0
        
        text = f"📊 СТАТИСТИКА\n\n👥 Всего: {total_users}\n👷 Работников: {workers}\n🏢 Заказчиков: {customers}\n\n📦 Заказов: {total_orders}\n🟢 Открытых: {open_orders}\n✅ Завершённых: {completed}\n\n💰 Выплачено: {total_payouts}₽"
        bot.reply_to(message, text)
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить' and m.from_user.id in MODERATOR_IDS)
def mod_rate_start(message):
    try:
        msg = bot.reply_to(message, "ID работника:")
        bot.register_next_step_handler(msg, mod_rate_get_user)
    except:
        pass

def mod_rate_get_user(message):
    try:
        try:
            user_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Число.", reply_markup=get_moderator_kb())
            return
        
        row = db.execute("SELECT id, name, rating FROM users WHERE id = ? AND role = 'rabotnik'", (user_id,)).fetchone()
        if not row:
            bot.reply_to(message, "❌ Не найден.", reply_markup=get_moderator_kb())
            return
        
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = bot.reply_to(message, f"⭐ {row[1]} (рейтинг: {row[2]})", reply_markup=kb)
        bot.register_next_step_handler(msg, mod_rate_apply, row[0])
    except:
        pass

def mod_rate_apply(message, user_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            return
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        add_rating(user_id, delta)
        new_rating = db.execute("SELECT rating FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        bot.reply_to(message, f"✅ Рейтинг: {new_rating}", reply_markup=get_moderator_kb())
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить заказчика' and m.from_user.id in MODERATOR_IDS)
def mod_rate_customer_start(message):
    try:
        msg = bot.reply_to(message, "ID заказчика:")
        bot.register_next_step_handler(msg, mod_rate_customer_get)
    except:
        pass

def mod_rate_customer_get(message):
    try:
        try:
            customer_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Число.", reply_markup=get_moderator_kb())
            return
        
        row = db.execute("SELECT id, name, customer_rating FROM users WHERE id = ? AND role = 'zakazchik'", (customer_id,)).fetchone()
        if not row:
            bot.reply_to(message, "❌ Не найден.", reply_markup=get_moderator_kb())
            return
        
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = bot.reply_to(message, f"⭐ {row[1]} (рейтинг: {row[2]})", reply_markup=kb)
        bot.register_next_step_handler(msg, mod_rate_customer_apply, row[0])
    except:
        pass

def mod_rate_customer_apply(message, customer_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            return
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        row = rate_customer(customer_id, delta)
        if row:
            bot.reply_to(message, f"✅ Рейтинг: {row[0]}", reply_markup=get_moderator_kb())
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '⚖️ Арбитраж' and m.from_user.id in MODERATOR_IDS)
def mod_arbitration(message):
    try:
        rows = db.execute("SELECT id, zakazchik_name, address, status FROM orders WHERE status IN ('in_progress', 'completed')").fetchall()
        if not rows:
            bot.reply_to(message, "⚖️ Нет заказов.")
            return
        text = "⚖️ ЗАКАЗЫ:\n"
        for r in rows:
            text += f"#{r[0]} {r[1]} {r[2]} ({r[3]})\n"
        text += "\n/arbitrate ID refund|penalty|ban"
        bot.reply_to(message, text)
    except:
        pass

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    try:
        if message.from_user.id not in MODERATOR_IDS:
            return
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "❌ /arbitrate ID refund|penalty|ban")
            return
        try:
            order_id = int(parts[1])
        except:
            bot.reply_to(message, "❌ ID число.")
            return
        action = parts[2].lower()
        order = get_order(order_id)
        if not order:
            bot.reply_to(message, "❌ Не найден.")
            return
        if action == 'refund':
            db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            db.commit()
            bot.reply_to(message, f"✅ Отменён.")
        elif action == 'penalty':
            add_rating(order[1], -1)
            bot.reply_to(message, f"✅ Рейтинг понижен.")
        elif action == 'ban':
            db.execute("UPDATE users SET blocked = 1 WHERE id = ?", (order[1],))
            db.commit()
            bot.reply_to(message, f"✅ Заблокирован.")
        else:
            bot.reply_to(message, "❌ Доступно: refund, penalty, ban")
    except:
        pass

@bot.message_handler(func=lambda m: m.text == '🔒 Блок' and m.from_user.id in MODERATOR_IDS)
def mod_block(message):
    try:
        msg = bot.reply_to(message, "📞 Телефон:")
        bot.register_next_step_handler(msg, block_user_by_phone_step)
    except:
        pass

def block_user_by_phone_step(message):
    try:
        phone = message.text
        if block_user_by_phone(phone):
            bot.reply_to(message, "✅ Заблокирован.", reply_markup=get_moderator_kb())
            users = db.execute("SELECT telegram_id FROM users WHERE phone = ? AND blocked = 1", (phone,)).fetchall()
            for user in users:
                try:
                    bot.send_message(user[0], "⛔ Заблокирован.")
                except:
                    pass
        else:
            bot.reply_to(message, "❌ Не найден.", reply_markup=get_moderator_kb())
    except:
        pass

# ========== CALLBACK ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        user = get_user(user_id)
        
        if not user or user[10] == 1:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
            return
        
        # Взятие
        if data.startswith('take_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order[9] != 'open' or user[6] != 'rabotnik':
                bot.answer_callback_query(call.id, "❌ Недоступно", show_alert=True)
                return
            assigned = get_assignments(order_id)
            if user[0] in assigned:
                bot.answer_callback_query(call.id, "❌ Уже взяли", show_alert=True)
                return
            try:
                bot.edit_message_text(
                    f"⚠️ Взять #{order_id}?\n💵 {order[8]} ₽",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=confirm_take_kb(order_id)
                )
                bot.answer_callback_query(call.id)
            except:
                pass
        
        # Подтверждение
        elif data.startswith('confirm_take_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            if not order or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Недоступно", show_alert=True)
                return
            assigned = get_assignments(order_id)
            if user[0] in assigned:
                bot.answer_callback_query(call.id, "❌ Уже взяли", show_alert=True)
                return
            db.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", 
                      (order_id, user[0], order[8]))
            db.commit()
            new_assigned = get_assignments(order_id)
            if len(new_assigned) >= order[5]:
                db.execute("UPDATE orders SET status = 'in_progress' WHERE id = ?", (order_id,))
                db.commit()
                try:
                    bot.send_message(order[1], f"🔔 Заказ #{order_id} укомплектован!")
                except:
                    pass
                bot.answer_callback_query(call.id, f"✅ Укомплектован!", show_alert=True)
            else:
                bot.answer_callback_query(call.id, f"✅ Взяли! Осталось {order[5] - len(new_assigned)} чел.", show_alert=True)
            try:
                bot.edit_message_text(
                    f"✅ Взяли #{order_id}\n💵 {order[8]} ₽\n📊 {'Укомплектован' if len(new_assigned) >= order[5] else 'Ожидает'}",
                    call.message.chat.id,
                    call.message.message_id
                )
            except:
                pass
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(m, f"👷 {user[2]} взял #{order_id}")
                except:
                    pass
        
        # Отмена
        elif data.startswith('cancel_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order[1] != user[0] or user[6] != 'zakazchik' or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Нельзя", show_alert=True)
                return
            if cancel_order(order_id):
                bot.answer_callback_query(call.id, f"✅ Отменён!", show_alert=True)
                try:
                    bot.edit_message_text(f"❌ Отменён #{order_id}", call.message.chat.id, call.message.message_id)
                except:
                    pass
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(m, f"❌ Отменён #{order_id} заказчиком")
                    except:
                        pass
        
        # Завершение
        elif data.startswith('complete_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            if not order or order[1] != user[0] or user[6] != 'zakazchik' or order[9] == 'completed':
                bot.answer_callback_query(call.id, "❌ Нельзя", show_alert=True)
                return
            db.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
            db.commit()
            bot.answer_callback_query(call.id, f"✅ Завершён!", show_alert=True)
            try:
                bot.edit_message_text(f"✅ Завершён #{order_id}", call.message.chat.id, call.message.message_id)
            except:
                pass
            assigned = get_assignments(order_id)
            for worker_id in assigned:
                try:
                    worker = get_user_by_id(worker_id)
                    if worker:
                        bot.send_message(worker[1], f"✅ #{order_id} завершён! {order[8]}₽")
                except:
                    pass
            for m in MODERATOR_IDS:
                try:
                    bot.send_message(m, f"✅ #{order_id} завершён заказчиком")
                except:
                    pass
        
        # Отмена взятия
        elif data == 'cancel_take':
            try:
                bot.edit_message_text("❌ Отменено", call.message.chat.id, call.message.message_id)
                bot.answer_callback_query(call.id)
            except:
                pass
    except:
        pass

# ========== БЛОКИРОВКА ==========
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        if not user or user[10] == 0:
            return
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, f"📞 {uid} ({user[2]}) просит связи")
            except:
                pass
        bot.reply_to(message, "✅ Отправлено.")
    except:
        pass

# ========== FALLBACK ==========
@bot.message_handler(func=lambda m: True)
def fallback(message):
    try:
        bot.reply_to(message, "Используйте кнопки.", reply_markup=get_main_kb())
    except:
        pass

# ========== ЗАПУСК ==========
print("🚀 Бот запущен!")
print(f"📊 Модераторы: {MODERATOR_IDS}")

while True:
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")
        time.sleep(5)
