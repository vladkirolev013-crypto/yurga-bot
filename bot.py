import telebot
import sqlite3
import time
from datetime import datetime
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# ===== КОНФИГ =====
TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'
MODERATOR_IDS = [8746212340]  # твой ID

bot = telebot.TeleBot(TOKEN)

# ===== БАЗА ДАННЫХ =====
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
        created_at TEXT
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

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def get_user(telegram_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_user(telegram_id, field, value):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
    conn.commit()
    conn.close()

def get_order(order_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_open_orders():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status = 'open' ORDER BY created_at DESC")
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

def get_worker_orders(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''SELECT o.id, o.address, o.hours, o.people, o.total_sum, o.status, a.payout 
                 FROM assignments a JOIN orders o ON a.order_id = o.id 
                 WHERE a.user_id = ?''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_assignments(order_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM assignments WHERE order_id = ?", (order_id,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_workers_on_shift():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND on_shift = 1 AND blocked = 0")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

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

# ===== КЛАВИАТУРЫ =====
def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    kb.row(KeyboardButton("🛡️ Я модератор"))
    return kb

def worker_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
    kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("🔴 Отдыхаю"), KeyboardButton("⬅️ Назад"))
    return kb

def customer_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📝 Создать заказ"))
    kb.row(KeyboardButton("📋 Мои заказы"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("⚠️ Пожаловаться"), KeyboardButton("⬅️ Назад"))
    return kb

def moderator_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    kb.row(KeyboardButton("📊 Статистика"), KeyboardButton("⭐ Оценить"))
    kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блок"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def blocked_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📞 Связь с модератором"))
    return kb

# ===== /start =====
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    user = get_user(uid)
    if user is None:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("INSERT INTO users (telegram_id) VALUES (?)", (uid,))
        conn.commit()
        conn.close()
        bot.reply_to(message, "👋 Добро пожаловать! Выберите роль:", reply_markup=main_kb())
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
        return
    role = user[7]
    if role == 'rabotnik':
        bot.reply_to(message, "👋 Работник!", reply_markup=worker_kb())
    elif role == 'zakazchik':
        bot.reply_to(message, "👋 Заказчик!", reply_markup=customer_kb())
    elif role == 'moderator':
        bot.reply_to(message, "👋 Модератор!", reply_markup=moderator_kb())
    else:
        bot.reply_to(message, "Выберите роль:", reply_markup=main_kb())

# ===== ВЫБОР РОЛИ =====
@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    uid = message.from_user.id
    user = get_user(uid)
    if user is None:
        bot.reply_to(message, "Нажмите /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
        return
    role_map = {'👷 Я работник': 'rabotnik', '🏢 Я заказчик': 'zakazchik', '🛡️ Я модератор': 'moderator'}
    role = role_map[message.text]
    if role == 'moderator' and uid not in MODERATOR_IDS:
        bot.reply_to(message, "❌ Нет прав.")
        return
    update_user(uid, 'role', role)
    if role == 'rabotnik':
        bot.reply_to(message, "✅ Вы работник.", reply_markup=worker_kb())
    elif role == 'zakazchik':
        bot.reply_to(message, "✅ Вы заказчик.", reply_markup=customer_kb())
    else:
        bot.reply_to(message, "✅ Вы модератор.", reply_markup=moderator_kb())

# ===== НАЗАД =====
@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user:
        bot.reply_to(message, "Начните с /start", reply_markup=main_kb())
        return
    role = user[7]
    if role == 'rabotnik':
        bot.reply_to(message, "Меню работника:", reply_markup=worker_kb())
    elif role == 'zakazchik':
        bot.reply_to(message, "Меню заказчика:", reply_markup=customer_kb())
    elif role == 'moderator':
        bot.reply_to(message, "Меню модератора:", reply_markup=moderator_kb())
    else:
        bot.reply_to(message, "Главное меню:", reply_markup=main_kb())

# ===== РЕГИСТРАЦИЯ =====
reg_data = {}
@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def register_start(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user:
        bot.reply_to(message, "Нажмите /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
        return
    if user[10] == 1:
        bot.reply_to(message, "✅ Вы уже зарегистрированы.")
        return
    if user[7] not in ['rabotnik', 'zakazchik']:
        bot.reply_to(message, "❌ Сначала выберите роль.")
        return
    reg_data[uid] = {}
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("✅ Принимаю"), KeyboardButton("❌ Отмена"))
    bot.send_message(message.chat.id, "📜 Чтобы продолжить, примите условия работы сервиса. Нажмите '✅ Принимаю' или '❌ Отмена'.", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in ['✅ Принимаю', '❌ Отмена'])
def handle_agreement(message):
    uid = message.from_user.id
    if message.text == '❌ Отмена':
        bot.reply_to(message, "Регистрация отменена.", reply_markup=main_kb())
        if uid in reg_data:
            del reg_data[uid]
        return
    user = get_user(uid)
    if not user:
        bot.reply_to(message, "Нажмите /start")
        return
    update_user(uid, 'agreement_accepted', 1)
    role = user[7]
    if role == 'rabotnik':
        msg = bot.reply_to(message, "Введите ваше полное имя (ФИО):")
        bot.register_next_step_handler(msg, get_worker_name, uid)
    else:
        msg = bot.reply_to(message, "Введите ваше полное имя (ФИО):")
        bot.register_next_step_handler(msg, get_customer_name, uid)

def get_worker_name(message, uid):
    reg_data[uid]['name'] = message.text
    msg = bot.reply_to(message, "Введите ваш номер телефона (например, +7 999 123-45-67):")
    bot.register_next_step_handler(msg, get_worker_phone, uid)

def get_worker_phone(message, uid):
    reg_data[uid]['phone'] = message.text
    msg = bot.reply_to(message, "Введите номер карты или реквизиты для выплат:")
    bot.register_next_step_handler(msg, get_worker_bank, uid)

def get_worker_bank(message, uid):
    reg_data[uid]['bank'] = message.text
    msg = bot.reply_to(message, "Введите инициалы (например, И.И. Иванов):")
    bot.register_next_step_handler(msg, finish_worker_reg, uid)

def finish_worker_reg(message, uid):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
              (reg_data[uid]['name'], reg_data[uid]['phone'], reg_data[uid]['bank'], message.text, uid))
    conn.commit()
    conn.close()
    del reg_data[uid]
    bot.reply_to(message, "✅ Регистрация завершена! Вы на смене и можете брать заказы.", reply_markup=worker_kb())

def get_customer_name(message, uid):
    reg_data[uid]['name'] = message.text
    msg = bot.reply_to(message, "Введите ваш номер телефона (например, +7 999 123-45-67):")
    bot.register_next_step_handler(msg, get_customer_phone, uid)

def get_customer_phone(message, uid):
    reg_data[uid]['phone'] = message.text
    msg = bot.reply_to(message, "Введите ваш район (город, улицу):")
    bot.register_next_step_handler(msg, finish_customer_reg, uid)

def finish_customer_reg(message, uid):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET name=?, phone=?, district=? WHERE telegram_id=?",
              (reg_data[uid]['name'], reg_data[uid]['phone'], message.text, uid))
    conn.commit()
    conn.close()
    del reg_data[uid]
    bot.reply_to(message, "✅ Регистрация завершена! Теперь вы можете создавать заказы.", reply_markup=customer_kb())

# ===== РАБОТНИК =====
@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Пройдите регистрацию (кнопка 'Регистрация').")
        return
    orders = get_open_orders()
    if not orders:
        bot.reply_to(message, "📭 Нет заказов.")
        return
    for o in orders:
        text = f"🆔 Заказ #{o[0]}\n📍 {o[3]}\n⏱ {o[4]}ч\n👥 {o[5]}чел\n💰 {o[6]}₽\n💵 {o[8]}₽/чел"
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton(f"✅ Забрать #{o[0]}"))
        kb.row(KeyboardButton("⬅️ Назад"))
        bot.send_message(message.chat.id, text, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text.startswith('✅ Забрать #'))
def take_order(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    try:
        order_id = int(message.text.split('#')[1])
    except:
        bot.reply_to(message, "❌ Ошибка.")
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[9] != 'open':
        bot.reply_to(message, "❌ Заказ уже не актуален.")
        return
    assigned = get_assignments(order_id)
    if user[0] in assigned:
        bot.reply_to(message, "❌ Вы уже взяли этот заказ.")
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", (order_id, user[0], order[8]))
    conn.commit()
    conn.close()
    if len(assigned) + 1 >= order[5]:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'in_progress' WHERE id = ?", (order_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ Заказ #{order_id} укомплектован!")
        try:
            bot.send_message(order[1], f"🔔 Заказ #{order_id} полностью укомплектован.")
        except:
            pass
    else:
        bot.reply_to(message, f"✅ Вы взяли заказ #{order_id}. Осталось {order[5] - len(assigned) - 1} чел.")

@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    orders = get_worker_orders(user[0])
    if not orders:
        bot.reply_to(message, "💰 У вас пока нет выплат.")
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
    uid = message.from_user.id
    user = get_user(uid)
    if not user:
        bot.reply_to(message, "Нажмите /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
        return
    role_names = {'rabotnik':'Работник','zakazchik':'Заказчик','moderator':'Модератор'}
    text = f"👤 Профиль\nИмя: {user[2] or 'не указано'}\nТелефон: {user[3] or 'не указан'}\nРоль: {role_names.get(user[7], user[7])}\nРейтинг: {user[8]}\nНа смене: {'Да' if user[9] else 'Нет'}\nСоглашение: {'Да' if user[10] else 'Нет'}\nБлок: {'Да' if user[11] else 'Нет'}"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text in ('🔴 Отдыхаю', '🟢 На смене'))
def toggle_shift(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if message.text == '🔴 Отдыхаю':
        update_user(uid, 'on_shift', 0)
        bot.reply_to(message, "🔴 Вы отдыхаете.", reply_markup=worker_kb())
    else:
        update_user(uid, 'on_shift', 1)
        bot.reply_to(message, "🟢 Вы на смене.", reply_markup=worker_kb())

# ===== ЗАКАЗЧИК =====
order_data = {}
@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Пройдите регистрацию (кнопка 'Регистрация').")
        return
    order_data[uid] = {}
    msg = bot.reply_to(message, "Введите адрес работы:")
    bot.register_next_step_handler(msg, get_order_address, uid)

def get_order_address(message, uid):
    order_data[uid]['address'] = message.text
    msg = bot.reply_to(message, "Введите количество часов (число):")
    bot.register_next_step_handler(msg, get_order_hours, uid)

def get_order_hours(message, uid):
    try:
        order_data[uid]['hours'] = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число. Попробуйте снова.")
        msg = bot.reply_to(message, "Введите количество часов (число):")
        bot.register_next_step_handler(msg, get_order_hours, uid)
        return
    msg = bot.reply_to(message, "Введите количество человек (число):")
    bot.register_next_step_handler(msg, get_order_people, uid)

def get_order_people(message, uid):
    try:
        people = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число. Попробуйте снова.")
        msg = bot.reply_to(message, "Введите количество человек (число):")
        bot.register_next_step_handler(msg, get_order_people, uid)
        return
    user = get_user(uid)
    hours = order_data[uid]['hours']
    address = order_data[uid]['address']
    total = hours * people * 500
    commission = hours * people * 50
    payout = (total - commission) // people
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''INSERT INTO orders (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (user[0], user[2] or "Заказчик", address, hours, people, total, commission, payout, datetime.now().isoformat()))
    conn.commit()
    order_id = c.lastrowid
    conn.close()
    del order_data[uid]
    bot.reply_to(message, f"✅ Заказ #{order_id} создан!\n📍 {address}\n⏱ {hours}ч\n👥 {people}чел\n💰 {total}₽\n💵 Выплата каждому: {payout}₽\nКомиссия сервиса: {commission}₽", reply_markup=customer_kb())
    workers = get_workers_on_shift()
    if workers:
        text = f"🔔 Новый заказ!\n📍 {address}\n⏱ {hours}ч\n👥 {people}чел\n💵 {payout}₽/чел\nСмотрите 'Свободные заказы'"
        for w in workers:
            try:
                bot.send_message(w, text)
            except:
                pass

@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_customer(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    orders = get_customer_orders(user[0])
    if not orders:
        bot.reply_to(message, "📭 У вас нет заказов.")
        return
    for o in orders:
        status_map = {'open':'🟢 Открыт','in_progress':'🟡 В работе','completed':'✅ Завершён'}
        text = f"🆔 Заказ #{o[0]}\n📍 {o[3]}\n⏱ {o[4]}ч\n👥 {o[5]}чел\n💰 {o[6]}₽\nСтатус: {status_map.get(o[9], o[9])}"
        if o[9] in ('open', 'in_progress'):
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row(KeyboardButton(f"✅ Завершить #{o[0]}"))
            kb.row(KeyboardButton("⬅️ Назад"))
            bot.send_message(message.chat.id, text, reply_markup=kb)
        else:
            bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text.startswith('✅ Завершить #'))
def complete_order_customer(message):
    uid = message.from_user.id
    user = get_user(uid)
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
        bot.reply_to(message, "❌ Заказ уже завершён.")
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"✅ Заказ #{order_id} завершён!", reply_markup=customer_kb())

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    msg = bot.reply_to(message, "Опишите вашу жалобу (текст):")
    bot.register_next_step_handler(msg, send_complaint, uid)

def send_complaint(message, uid):
    user = get_user(uid)
    text = f"⚠️ Жалоба от заказчика {user[2] or 'без имени'} (ID {uid}):\n{message.text}"
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, text)
        except:
            pass
    bot.reply_to(message, "✅ Жалоба отправлена модератору.", reply_markup=customer_kb())

# ===== МОДЕРАТОР =====
@bot.message_handler(func=lambda m: m.text == '💰 Выплаты' and m.from_user.id in MODERATOR_IDS)
def mod_payouts(message):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT SUM(payout) FROM assignments")
    total = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM assignments")
    count = c.fetchone()[0] or 0
    conn.close()
    bot.reply_to(message, f"💰 Всего выплат: {total}₽\n👥 Количество выплат: {count}")

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
    text = "👥 Список работников:\n"
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
    text = f"📊 Статистика\n👥 Всего пользователей: {total_users}\n👷 Работников: {workers}\n🏢 Заказчиков: {customers}\n📦 Всего заказов: {total_orders}\n✅ Завершённых: {completed}"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить' and m.from_user.id in MODERATOR_IDS)
def mod_rate_start(message):
    msg = bot.reply_to(message, "Введите ID работника (число) из списка /workers:")
    bot.register_next_step_handler(msg, mod_rate_get_user)

def mod_rate_get_user(message):
    try:
        user_id = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.", reply_markup=moderator_kb())
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, name, rating FROM users WHERE id = ? AND role = 'rabotnik'", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        bot.reply_to(message, "❌ Работник не найден.", reply_markup=moderator_kb())
        return
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
    kb.row(KeyboardButton("⬅️ Назад"))
    msg = bot.reply_to(message, f"Оценка для {row[1]} (текущий рейтинг: {row[2]}):", reply_markup=kb)
    bot.register_next_step_handler(msg, mod_rate_apply, row[0])

def mod_rate_apply(message, user_id):
    if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
        bot.reply_to(message, "❌ Нажмите одну из кнопок.", reply_markup=moderator_kb())
        return
    delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
    add_rating(user_id, delta)
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT rating FROM users WHERE id = ?", (user_id,))
    new_rating = c.fetchone()[0]
    conn.close()
    bot.reply_to(message, f"✅ Рейтинг обновлён: {new_rating}", reply_markup=moderator_kb())

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
    text = "⚖️ Заказы для арбитража:\n"
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
        bot.reply_to(message, "❌ Используйте: /arbitrate ID refund/penalty/ban")
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
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ Заказ #{order_id} отменён, деньги возвращены заказчику.")
    elif action == 'penalty':
        add_rating(order[1], -1)
        bot.reply_to(message, f"✅ Заказчику #{order[1]} снижен рейтинг на 1.")
    elif action == 'ban':
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE users SET blocked = 1 WHERE id = ?", (order[1],))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ Заказчик #{order[1]} заблокирован.")
    else:
        bot.reply_to(message, "❌ Неизвестное действие. Доступны: refund, penalty, ban.")

@bot.message_handler(func=lambda m: m.text == '🔒 Блок' and m.from_user.id in MODERATOR_IDS)
def mod_block(message):
    msg = bot.reply_to(message, "Введите имя пользователя (часть имени) для блокировки:")
    bot.register_next_step_handler(msg, block_user)

def block_user(message):
    name = message.text
    affected = block_user_by_name(name)
    if affected:
        bot.reply_to(message, f"✅ Заблокировано {affected} пользователей.", reply_markup=moderator_kb())
    else:
        bot.reply_to(message, "❌ Пользователи не найдены.", reply_markup=moderator_kb())

# ===== ЗАБЛОКИРОВАННЫЙ =====
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator(message):
    uid = message.from_user.id
    user = get_user(uid)
    if not user or user[11] == 0:
        return
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"📞 Пользователь {uid} ({user[2]}) запросил связь с модератором.")
        except:
            pass
    bot.reply_to(message, "✅ Ваш запрос отправлен. Ожидайте ответа.")

# ===== FALLBACK =====
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.reply_to(message, "Используйте кнопки меню.", reply_markup=main_kb())

# ===== ЗАПУСК =====
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
