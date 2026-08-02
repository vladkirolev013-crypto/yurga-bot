import telebot
import sqlite3
import time
from datetime import datetime
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# === ТОКЕН ===
TOKEN = '8540395731:AAE_8joM9fqLeJm3Q1odG-4Okz1O5iRrVNc'
bot = telebot.TeleBot(TOKEN)

# === ID МОДЕРАТОРА ===
MODERATOR_IDS = [8746212340]  # твой ID

# === СОСТОЯНИЯ ===
user_state = {}

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        name TEXT,
        phone TEXT,
        bank TEXT,
        initials TEXT,
        district TEXT,
        role TEXT,
        rating INTEGER DEFAULT 10,
        on_shift INTEGER DEFAULT 0,
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
        created_at TEXT,
        moderator_rating INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        user_id INTEGER,
        payout INTEGER
    )''')
    conn.commit()
    conn.close()

init_db()

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_user(telegram_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_by_id(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_user_field(telegram_id, field, value):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
    conn.commit()
    conn.close()

def update_user_field_by_id(user_id, field, value):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
    conn.commit()
    conn.close()

def get_open_orders():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status = 'open' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_order(order_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_order_status(order_id, status):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def create_order(zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''INSERT INTO orders 
                 (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, datetime.now().isoformat()))
    conn.commit()
    order_id = c.lastrowid
    conn.close()
    return order_id

def add_assignment(order_id, user_id, payout):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", (order_id, user_id, payout))
    conn.commit()
    conn.close()

def get_assignments_for_order(order_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT user_id, payout FROM assignments WHERE order_id = ?", (order_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_workers_on_shift():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND on_shift = 1 AND blocked = 0")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_worker_orders(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT o.id, o.address, o.hours, o.people, o.total_sum, o.status, a.payout FROM assignments a JOIN orders o ON a.order_id = o.id WHERE a.user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_customer_orders(zakazchik_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE zakazchik_id = ? ORDER BY created_at DESC", (zakazchik_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_users():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, telegram_id, name, phone, role, rating, blocked FROM users")
    rows = c.fetchall()
    conn.close()
    return rows

def get_workers_list():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, name, rating, blocked FROM users WHERE role = 'rabotnik'")
    rows = c.fetchall()
    conn.close()
    return rows

def add_rating(user_id, delta):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET rating = rating + ? WHERE id = ?", (delta, user_id))
    conn.commit()
    c.execute("SELECT rating, telegram_id FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    if row and row[0] <= 5:
        c.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
        conn.commit()
        try:
            bot.send_message(row[1], "⚠️ Ваш рейтинг упал до 5. Вы заблокированы. Нажмите '📞 Связь с модератором'.")
        except:
            pass
    conn.close()

def block_user_by_name(name):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET blocked = 1 WHERE name LIKE ?", ('%' + name + '%',))
    conn.commit()
    affected = c.rowcount
    conn.close()
    return affected

# === КЛАВИАТУРЫ ===
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    kb.row(KeyboardButton("🛡️ Я модератор"))
    return kb

def worker_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
    kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("🔴 Отдыхаю"), KeyboardButton("⬅️ Назад"))
    return kb

def customer_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Создать заказ"), KeyboardButton("📋 Мои заказы"))
    kb.row(KeyboardButton("👤 Профиль"), KeyboardButton("⚠️ Пожаловаться"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def moderator_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    kb.row(KeyboardButton("📊 Статистика"), KeyboardButton("⭐ Оценить"))
    kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блок"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def blocked_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📞 Связь с модератором"))
    return kb

# === /start ===
@bot.message_handler(commands=['start'])
def start(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, "👋 Добро пожаловать! Выберите роль:", reply_markup=main_menu())
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    role = user[7]
    if role == 'rabotnik':
        bot.reply_to(message, "👋 С возвращением, работник!", reply_markup=worker_menu())
    elif role == 'zakazchik':
        bot.reply_to(message, "👋 С возвращением, заказчик!", reply_markup=customer_menu())
    elif role == 'moderator':
        bot.reply_to(message, "👋 С возвращением, модератор!", reply_markup=moderator_menu())
    else:
        bot.reply_to(message, "Выберите роль:", reply_markup=main_menu())

# === ВЫБОР РОЛИ ===
@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        bot.reply_to(message, "Нажмите /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    role_map = {
        '👷 Я работник': 'rabotnik',
        '🏢 Я заказчик': 'zakazchik',
        '🛡️ Я модератор': 'moderator'
    }
    role = role_map[message.text]
    if role == 'moderator' and telegram_id not in MODERATOR_IDS:
        bot.reply_to(message, "❌ Нет прав.")
        return
    update_user_field(telegram_id, 'role', role)
    if role == 'rabotnik':
        bot.reply_to(message, "✅ Вы работник.", reply_markup=worker_menu())
    elif role == 'zakazchik':
        bot.reply_to(message, "✅ Вы заказчик.", reply_markup=customer_menu())
    else:
        bot.reply_to(message, "✅ Вы модератор.", reply_markup=moderator_menu())

# === НАЗАД ===
@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user:
        bot.reply_to(message, "Начните с /start", reply_markup=main_menu())
        return
    role = user[7]
    if role == 'rabotnik':
        bot.reply_to(message, "Меню работника:", reply_markup=worker_menu())
    elif role == 'zakazchik':
        bot.reply_to(message, "Меню заказчика:", reply_markup=customer_menu())
    elif role == 'moderator':
        bot.reply_to(message, "Меню модератора:", reply_markup=moderator_menu())
    else:
        bot.reply_to(message, "Главное меню:", reply_markup=main_menu())

# === РЕГИСТРАЦИЯ ===
@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def register_start(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user:
        bot.reply_to(message, "Нажмите /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 1:
        bot.reply_to(message, "✅ Вы уже зарегистрированы.")
        return
    role = user[7]
    if role not in ('rabotnik', 'zakazchik'):
        bot.reply_to(message, "❌ Сначала выберите роль.")
        return
    if role == 'rabotnik':
        text = "📜 СОГЛАШЕНИЕ ДЛЯ РАБОТНИКА\n\nСервис — посредник. Гарантирует выплату, проверку заказчика. НЕ отвечает за условия работы, травмы, споры. Работник обязан явиться вовремя, выполнить работу, сообщить о проблемах."
    else:
        text = "📜 СОГЛАШЕНИЕ ДЛЯ ЗАКАЗЧИКА\n\nСервис — посредник. Гарантирует явку работника и возврат денег при неявке. НЕ отвечает за качество работы, порчу, кражи. Заказчик обязан оплатить через сервис (не наличными!), дать безопасные условия, оценить работу. Оплата наличными = отмена гарантии."
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("✅ Принимаю условия"), KeyboardButton("❌ Отмена"))
    bot.send_message(message.chat.id, text, reply_markup=kb)
    user_state[telegram_id] = {'step': 'agreement'}

@bot.message_handler(func=lambda m: m.text in ('✅ Принимаю условия', '❌ Отмена'))
def handle_agreement(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user:
        bot.reply_to(message, "Нажмите /start")
        return
    if message.text == '❌ Отмена':
        bot.reply_to(message, "Регистрация отменена.", reply_markup=main_menu())
        if telegram_id in user_state:
            del user_state[telegram_id]
        return
    update_user_field(telegram_id, 'agreement_accepted', 1)
    role = user[7]
    if role == 'rabotnik':
        user_state[telegram_id] = {'step': 'worker_name'}
        msg = bot.reply_to(message, "Введите ФИО:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, worker_register_name, telegram_id)
    else:
        user_state[telegram_id] = {'step': 'customer_name'}
        msg = bot.reply_to(message, "Введите ФИО:", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, customer_register_name, telegram_id)

def worker_register_name(message, telegram_id):
    user_state[telegram_id]['name'] = message.text
    msg = bot.reply_to(message, "Введите телефон:")
    bot.register_next_step_handler(msg, worker_register_phone, telegram_id)

def worker_register_phone(message, telegram_id):
    user_state[telegram_id]['phone'] = message.text
    msg = bot.reply_to(message, "Введите реквизиты банка (карта):")
    bot.register_next_step_handler(msg, worker_register_bank, telegram_id)

def worker_register_bank(message, telegram_id):
    user_state[telegram_id]['bank'] = message.text
    msg = bot.reply_to(message, "Введите инициалы (например, И.И. Иванов):")
    bot.register_next_step_handler(msg, worker_register_initials, telegram_id)

def worker_register_initials(message, telegram_id):
    initials = message.text
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
              (user_state[telegram_id]['name'], user_state[telegram_id]['phone'], user_state[telegram_id]['bank'], initials, telegram_id))
    conn.commit()
    conn.close()
    del user_state[telegram_id]
    bot.reply_to(message, "✅ Регистрация завершена! Вы на смене.", reply_markup=worker_menu())

def customer_register_name(message, telegram_id):
    user_state[telegram_id]['name'] = message.text
    msg = bot.reply_to(message, "Введите телефон:")
    bot.register_next_step_handler(msg, customer_register_phone, telegram_id)

def customer_register_phone(message, telegram_id):
    user_state[telegram_id]['phone'] = message.text
    msg = bot.reply_to(message, "Введите район:")
    bot.register_next_step_handler(msg, customer_register_district, telegram_id)

def customer_register_district(message, telegram_id):
    district = message.text
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET name=?, phone=?, district=? WHERE telegram_id=?",
              (user_state[telegram_id]['name'], user_state[telegram_id]['phone'], district, telegram_id))
    conn.commit()
    conn.close()
    del user_state[telegram_id]
    bot.reply_to(message, "✅ Регистрация завершена!", reply_markup=customer_menu())

# === РАБОТНИКИ ===
@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Пройдите регистрацию.")
        return
    orders = get_open_orders()
    if not orders:
        bot.reply_to(message, "📭 Нет заказов.")
        return
    for o in orders:
        text = f"🆔 Заказ #{o[0]}\n📍 {o[3]}\n⏱ {o[4]}ч, 👥 {o[5]}чел\n💰 {o[6]}₽, 💵 {o[8]}₽/чел\n👤 {o[2]}"
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton(f"✅ Забрать #{o[0]}"))
        kb.row(KeyboardButton("⬅️ Назад"))
        bot.send_message(message.chat.id, text, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text.startswith('✅ Забрать #'))
def take_order(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    try:
        order_id = int(message.text.split('#')[1])
    except:
        bot.reply_to(message, "❌ Ошибка формата.")
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[9] != 'open':
        bot.reply_to(message, "❌ Заказ уже не актуален.")
        return
    assignments = get_assignments_for_order(order_id)
    if any(a[0] == user[0] for a in assignments):
        bot.reply_to(message, "❌ Вы уже взяли этот заказ.")
        return
    add_assignment(order_id, user[0], order[8])
    people = order[5]
    if len(assignments) + 1 >= people:
        update_order_status(order_id, 'in_progress')
        bot.reply_to(message, f"✅ Заказ #{order_id} укомплектован!")
        try:
            bot.send_message(order[1], f"🔔 Заказ #{order_id} полностью укомплектован.")
        except:
            pass
    else:
        bot.reply_to(message, f"✅ Вы взяли заказ #{order_id}. Осталось {people - len(assignments) - 1} чел.")

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    orders = get_worker_orders(user[0])
    if not orders:
        bot.reply_to(message, "💰 Нет выплат.")
        return
    total = 0
    text = "💰 Ваши выплаты:\n"
    for o in orders:
        text += f"Заказ #{o[0]}: {o[1]}, {o[2]}ч, {o[3]}чел, выплата {o[6]}₽, статус {o[5]}\n"
        if o[5] == 'completed':
            total += o[6]
    text += f"\n💰 Итого: {total}₽"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text == '👤 Профиль')
def profile(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user:
        bot.reply_to(message, "Нажмите /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    role_names = {'rabotnik': 'Работник', 'zakazchik': 'Заказчик', 'moderator': 'Модератор'}
    text = f"👤 Профиль\nИмя: {user[2] or 'не указано'}\nТелефон: {user[3] or 'не указан'}\nРоль: {role_names.get(user[7], user[7])}\nРейтинг: {user[8]}\nНа смене: {'Да' if user[9] else 'Нет'}\nСоглашение: {'Да' if user[10] else 'Нет'}\nБлок: {'Да' if user[11] else 'Нет'}"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text in ('🔴 Отдыхаю', '🟢 На смене'))
def toggle_shift(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if message.text == '🔴 Отдыхаю':
        update_user_field(telegram_id, 'on_shift', 0)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
        kb.row(KeyboardButton("🟢 На смене"), KeyboardButton("⬅️ Назад"))
        bot.reply_to(message, "🔴 Вы отдыхаете.", reply_markup=kb)
    else:
        update_user_field(telegram_id, 'on_shift', 1)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
        kb.row(KeyboardButton("🔴 Отдыхаю"), KeyboardButton("⬅️ Назад"))
        bot.reply_to(message, "🟢 Вы на смене.", reply_markup=kb)

# === ЗАКАЗЧИКИ ===
@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Пройдите регистрацию.")
        return
    user_state[telegram_id] = {'step': 'order_address'}
    msg = bot.reply_to(message, "Введите адрес:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, order_address, telegram_id)

def order_address(message, telegram_id):
    user_state[telegram_id]['address'] = message.text
    msg = bot.reply_to(message, "Введите часы (число):")
    bot.register_next_step_handler(msg, order_hours, telegram_id)

def order_hours(message, telegram_id):
    try:
        hours = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.")
        msg = bot.reply_to(message, "Введите часы (число):")
        bot.register_next_step_handler(msg, order_hours, telegram_id)
        return
    user_state[telegram_id]['hours'] = hours
    msg = bot.reply_to(message, "Введите количество человек:")
    bot.register_next_step_handler(msg, order_people, telegram_id)

def order_people(message, telegram_id):
    try:
        people = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.")
        msg = bot.reply_to(message, "Введите количество человек:")
        bot.register_next_step_handler(msg, order_people, telegram_id)
        return
    hours = user_state[telegram_id]['hours']
    address = user_state[telegram_id]['address']
    total = hours * people * 500
    commission = hours * people * 50
    payout = (total - commission) // people
    user = get_user(telegram_id)
    order_id = create_order(user[0], user[2] or "Заказчик", address, hours, people, total, commission, payout)
    del user_state[telegram_id]
    bot.reply_to(message, f"✅ Заказ #{order_id} создан!\n📍 {address}\n⏱ {hours}ч, 👥 {people}чел\n💰 {total}₽, комиссия {commission}₽\n💵 Выплата каждому: {payout}₽", reply_markup=customer_menu())
    workers = get_workers_on_shift()
    if workers:
        text = f"🔔 Новый заказ!\n📍 {address}\n⏱ {hours}ч, 👥 {people}чел\n💵 {payout}₽/чел\n⭐ Рейтинг заказчика: {user[8]}\nСмотрите 'Свободные заказы'"
        for w in workers:
            try:
                bot.send_message(w, text)
            except:
                pass

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_customer(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    orders = get_customer_orders(user[0])
    if not orders:
        bot.reply_to(message, "📭 У вас нет заказов.")
        return
    for o in orders:
        status_map = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'completed': '✅ Завершён'}
        text = f"🆔 Заказ #{o[0]}\n📍 {o[3]}\n⏱ {o[4]}ч, 👥 {o[5]}чел\n💰 {o[6]}₽\nСтатус: {status_map.get(o[9], o[9])}"
        if o[9] in ('open', 'in_progress'):
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton(f"✅ Завершить #{o[0]}"))
            kb.row(KeyboardButton("⬅️ Назад"))
            bot.send_message(message.chat.id, text, reply_markup=kb)
        else:
            bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text.startswith('✅ Завершить #'))
def complete_order_customer(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    try:
        order_id = int(message.text.split('#')[1])
    except:
        bot.reply_to(message, "❌ Ошибка.")
        return
    order = get_order(order_id)
    if not order or order[1] != user[0]:
        bot.reply_to(message, "❌ Это не ваш заказ.")
        return
    if order[9] == 'completed':
        bot.reply_to(message, "❌ Уже завершён.")
        return
    update_order_status(order_id, 'completed')
    bot.reply_to(message, f"✅ Заказ #{order_id} завершён!", reply_markup=customer_menu())

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    msg = bot.reply_to(message, "Опишите жалобу:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, send_complaint, telegram_id)

def send_complaint(message, telegram_id):
    user = get_user(telegram_id)
    text = f"⚠️ Жалоба от {user[2] or 'без имени'} (ID {telegram_id}):\n{message.text}"
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, text)
        except:
            pass
    bot.reply_to(message, "✅ Отправлено модератору.", reply_markup=customer_menu())

# === МОДЕРАТОР ===
@bot.message_handler(func=lambda m: m.text == '💰 Выплаты' and m.from_user.id in MODERATOR_IDS)
def mod_payouts(message):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT SUM(payout) FROM assignments")
    total = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM assignments")
    count = c.fetchone()[0] or 0
    conn.close()
    bot.reply_to(message, f"💰 Всего выплат: {total}₽\n👥 Количество: {count}")

@bot.message_handler(func=lambda m: m.text == '🟡 Активные' and m.from_user.id in MODERATOR_IDS)
def mod_active(message):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status IN ('open', 'in_progress')")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "🟡 Нет активных заказов.")
        return
    for o in rows:
        text = f"🆔 Заказ #{o[0]}\nЗаказчик: {o[2]}\nАдрес: {o[3]}\nЧасы: {o[4]}, чел: {o[5]}\nСумма: {o[6]}, комиссия: {o[7]}\nСтатус: {o[9]}"
        bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == '✅ Завершённые' and m.from_user.id in MODERATOR_IDS)
def mod_completed(message):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status = 'completed'")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "✅ Нет завершённых заказов.")
        return
    for o in rows:
        text = f"🆔 Заказ #{o[0]}\nЗаказчик: {o[2]}\nАдрес: {o[3]}\nЧасы: {o[4]}, чел: {o[5]}\nСумма: {o[6]}, комиссия: {o[7]}"
        bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == '👥 Работники' and m.from_user.id in MODERATOR_IDS)
def mod_workers(message):
    workers = get_workers_list()
    if not workers:
        bot.reply_to(message, "👥 Нет работников.")
        return
    text = "👥 Работники:\n"
    for w in workers:
        text += f"ID {w[0]}, {w[1]}, рейтинг {w[2]}, блок {'да' if w[3] else 'нет'}\n"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text == '📊 Статистика' and m.from_user.id in MODERATOR_IDS)
def mod_stats(message):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'rabotnik'")
    workers = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE role = 'zakazchik'")
    customers = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders")
    total_orders = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
    completed = c.fetchone()[0]
    conn.close()
    text = f"📊 Статистика\n👥 Пользователей: {total_users}\n👷 Работников: {workers}\n🏢 Заказчиков: {customers}\n📦 Заказов: {total_orders}\n✅ Завершённых: {completed}"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить' and m.from_user.id in MODERATOR_IDS)
def mod_rate_start(message):
    msg = bot.reply_to(message, "Введите ID работника (число):", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, mod_rate_get_user)

def mod_rate_get_user(message):
    try:
        user_id = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.", reply_markup=moderator_menu())
        return
    user = get_user_by_id(user_id)
    if not user:
        bot.reply_to(message, "❌ Пользователь не найден.", reply_markup=moderator_menu())
        return
    if user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только работники.", reply_markup=moderator_menu())
        return
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
    kb.row(KeyboardButton("⬅️ Назад"))
    msg = bot.reply_to(message, f"Оценка для {user[2]} (текущий {user[8]}):", reply_markup=kb)
    bot.register_next_step_handler(msg, mod_rate_apply, user_id)

def mod_rate_apply(message, user_id):
    if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
        bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=moderator_menu())
        return
    delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
    add_rating(user_id, delta)
    user = get_user_by_id(user_id)
    bot.reply_to(message, f"✅ Рейтинг обновлён: {user[8]}", reply_markup=moderator_menu())

@bot.message_handler(func=lambda m: m.text == '⚖️ Арбитраж' and m.from_user.id in MODERATOR_IDS)
def mod_arbitration(message):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, zakazchik_name, address, status FROM orders WHERE status IN ('in_progress', 'completed')")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "⚖️ Нет заказов для арбитража.")
        return
    text = "⚖️ Заказы:\n"
    for r in rows:
        text += f"ID {r[0]}, {r[1]}, {r[2]}, статус {r[3]}\n"
    text += "\nКоманды: /arbitrate ID refund | penalty | ban"
    bot.reply_to(message, text)

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "❌ /arbitrate ID refund/penalty/ban")
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
        update_order_status(order_id, 'completed')
        bot.reply_to(message, f"✅ Заказ #{order_id} отменён, деньги возвращены.")
    elif action == 'penalty':
        zakazchik_id = order[1]
        add_rating(zakazchik_id, -1)
        bot.reply_to(message, f"✅ Заказчику #{zakazchik_id} снижен рейтинг на 1.")
    elif action == 'ban':
        zakazchik_id = order[1]
        update_user_field_by_id(zakazchik_id, 'blocked', 1)
        bot.reply_to(message, f"✅ Заказчик #{zakazchik_id} заблокирован.")
    else:
        bot.reply_to(message, "❌ Действие: refund, penalty, ban.")

@bot.message_handler(func=lambda m: m.text == '🔒 Блок' and m.from_user.id in MODERATOR_IDS)
def mod_block(message):
    msg = bot.reply_to(message, "Введите имя (часть) для блокировки:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, block_user)

def block_user(message):
    name = message.text
    affected = block_user_by_name(name)
    if affected:
        bot.reply_to(message, f"✅ Заблокировано {affected} пользователей.", reply_markup=moderator_menu())
    else:
        bot.reply_to(message, "❌ Не найдено.", reply_markup=moderator_menu())

# === ЗАБЛОКИРОВАННЫЙ ===
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if not user or user[11] == 0:
        return
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"📞 Пользователь {telegram_id} ({user[2]}) просит связи.")
        except:
            pass
    bot.reply_to(message, "✅ Запрос отправлен.")

# === FALLBACK ===
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.reply_to(message, "Используйте кнопки меню.", reply_markup=main_menu())

# === ЗАПУСК ===
print("✅ Бот запущен и слушает...")
try:
    bot.delete_webhook()
except:
    pass

while True:
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
        time.sleep(5)
