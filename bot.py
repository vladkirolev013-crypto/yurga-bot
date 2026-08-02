import telebot
import sqlite3
import time
from datetime import datetime
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# === ТОКЕН (по ТЗ) ===
TOKEN = '8540395731:AAE_8joM9fqLeJm3Q1odG-4Okz1O5iRrVNc'
bot = telebot.TeleBot(TOKEN)

# === ТВОЙ ID МОДЕРАТОРА ===
MODERATOR_IDS = [8746212340]  # <-- заменено на твой ID

# === СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ (для регистрации) ===
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
    # Проверка на бан
    c.execute("SELECT rating, telegram_id FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    if row and row[0] <= 5:
        c.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
        conn.commit()
        try:
            bot.send_message(row[1], "⚠️ Ваш рейтинг упал до 5 или ниже. Вы заблокированы. Для связи с модератором нажмите '📞 Связь с модератором'.")
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

def get_user_by_name(name):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE name LIKE ?", ('%' + name + '%',))
    row = c.fetchone()
    conn.close()
    return row

# === КЛАВИАТУРЫ ===
def main_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    keyboard.row(KeyboardButton("🛡️ Я модератор"))
    return keyboard

def worker_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
    keyboard.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
    keyboard.row(KeyboardButton("🔴 Отдыхаю"), KeyboardButton("⬅️ Назад"))
    return keyboard

def customer_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("📝 Создать заказ"), KeyboardButton("📋 Мои заказы"))
    keyboard.row(KeyboardButton("👤 Профиль"), KeyboardButton("⚠️ Пожаловаться"))
    keyboard.row(KeyboardButton("⬅️ Назад"))
    return keyboard

def moderator_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    keyboard.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    keyboard.row(KeyboardButton("📊 Статистика"), KeyboardButton("⭐ Оценить"))
    keyboard.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блок"))
    keyboard.row(KeyboardButton("⬅️ Назад"))
    return keyboard

def blocked_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("📞 Связь с модератором"))
    return keyboard

# === /start ===
@bot.message_handler(commands=['start'])
def start(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        # Создаём запись с минимальными данными
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, "👋 Добро пожаловать! Выберите свою роль:", reply_markup=main_menu())
    else:
        if user[11] == 1:  # blocked
            bot.reply_to(message, "⛔ Вы заблокированы. Свяжитесь с модератором.", reply_markup=blocked_menu())
            return
        role = user[7]
        if role == 'rabotnik':
            bot.reply_to(message, "👋 С возвращением, работник!", reply_markup=worker_menu())
        elif role == 'zakazchik':
            bot.reply_to(message, "👋 С возвращением, заказчик!", reply_markup=customer_menu())
        elif role == 'moderator':
            bot.reply_to(message, "👋 С возвращением, модератор!", reply_markup=moderator_menu())
        else:
            bot.reply_to(message, "Выберите свою роль:", reply_markup=main_menu())

# === ОБРАБОТКА ВЫБОРА РОЛИ ===
@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        bot.reply_to(message, "Сначала нажмите /start")
        return
    if user[11] == 1:  # blocked
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    role_map = {
        '👷 Я работник': 'rabotnik',
        '🏢 Я заказчик': 'zakazchik',
        '🛡️ Я модератор': 'moderator'
    }
    role = role_map[message.text]
    if role == 'moderator' and telegram_id not in MODERATOR_IDS:
        bot.reply_to(message, "❌ У вас нет прав модератора.")
        return

    update_user_field(telegram_id, 'role', role)
    if role == 'rabotnik':
        bot.reply_to(message, "✅ Вы выбрали роль работника. Меню:", reply_markup=worker_menu())
    elif role == 'zakazchik':
        bot.reply_to(message, "✅ Вы выбрали роль заказчика. Меню:", reply_markup=customer_menu())
    else:
        bot.reply_to(message, "✅ Вы выбрали роль модератора. Меню:", reply_markup=moderator_menu())

# === ОБРАБОТКА КНОПКИ "Назад" ===
@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back_to_main(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user:
        role = user[7]
        if role == 'rabotnik':
            bot.reply_to(message, "Главное меню работника:", reply_markup=worker_menu())
        elif role == 'zakazchik':
            bot.reply_to(message, "Главное меню заказчика:", reply_markup=customer_menu())
        elif role == 'moderator':
            bot.reply_to(message, "Главное меню модератора:", reply_markup=moderator_menu())
        else:
            bot.reply_to(message, "Главное меню:", reply_markup=main_menu())
    else:
        bot.reply_to(message, "Начните с /start", reply_markup=main_menu())

# === РЕГИСТРАЦИЯ (пошагово) ===
@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def register_start(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        bot.reply_to(message, "Начните с /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 1:  # agreement_accepted
        bot.reply_to(message, "✅ Вы уже зарегистрированы. Если хотите обновить данные, обратитесь к модератору.")
        return

    # Сохраняем роль для определения типа регистрации
    role = user[7]
    if role not in ['rabotnik', 'zakazchik']:
        bot.reply_to(message, "❌ Сначала выберите роль через главное меню.")
        return

    # Показываем соглашение
    if role == 'rabotnik':
        agreement_text = (
            "📜 СОГЛАШЕНИЕ ДЛЯ РАБОТНИКА\n\n"
            "Сервис является посредником. Он гарантирует выплату и проверку заказчика. "
            "Сервис НЕ несёт ответственности за условия работы, травмы, порчу имущества, споры между сторонами. "
            "Работник обязан явиться вовремя, выполнить работу качественно, сообщить о проблемах модератору."
        )
    else:  # zakazchik
        agreement_text = (
            "📜 СОГЛАШЕНИЕ ДЛЯ ЗАКАЗЧИКА\n\n"
            "Сервис является посредником. Он гарантирует явку работника и возврат денег при неявке. "
            "Сервис НЕ несёт ответственности за качество работы, порчу имущества, кражи. "
            "Заказчик обязан оплатить через сервис (не наличными!), обеспечить безопасные условия труда, оценить работу. "
            "Оплата наличными = отмена гарантий."
        )

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("✅ Принимаю условия"), KeyboardButton("❌ Отмена"))
    bot.send_message(message.chat.id, agreement_text, reply_markup=keyboard)
    user_state[telegram_id] = {'step': 'agreement'}

@bot.message_handler(func=lambda m: m.text in ['✅ Принимаю условия', '❌ Отмена'])
def handle_agreement(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        bot.reply_to(message, "Начните с /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    if message.text == '❌ Отмена':
        bot.reply_to(message, "❌ Регистрация отменена.", reply_markup=main_menu())
        if telegram_id in user_state:
            del user_state[telegram_id]
        return

    # Принял условия
    update_user_field(telegram_id, 'agreement_accepted', 1)
    role = user[7]
    if role == 'rabotnik':
        user_state[telegram_id] = {'step': 'worker_name'}
        msg = bot.reply_to(message, "Введите ваше полное имя (ФИО):", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, worker_register_name, telegram_id)
    else:  # zakazchik
        user_state[telegram_id] = {'step': 'customer_name'}
        msg = bot.reply_to(message, "Введите ваше полное имя (ФИО):", reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, customer_register_name, telegram_id)

def worker_register_name(message, telegram_id):
    name = message.text
    user_state[telegram_id]['name'] = name
    msg = bot.reply_to(message, "Введите ваш номер телефона (в свободном формате):")
    bot.register_next_step_handler(msg, worker_register_phone, telegram_id)

def worker_register_phone(message, telegram_id):
    phone = message.text
    user_state[telegram_id]['phone'] = phone
    msg = bot.reply_to(message, "Введите номер банковской карты (или другие реквизиты):")
    bot.register_next_step_handler(msg, worker_register_bank, telegram_id)

def worker_register_bank(message, telegram_id):
    bank = message.text
    user_state[telegram_id]['bank'] = bank
    msg = bot.reply_to(message, "Введите ваши инициалы (например, И.И. Иванов):")
    bot.register_next_step_handler(msg, worker_register_initials, telegram_id)

def worker_register_initials(message, telegram_id):
    initials = message.text
    # Сохраняем все данные
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET name = ?, phone = ?, bank = ?, initials = ?, on_shift = 1 WHERE telegram_id = ?",
              (user_state[telegram_id]['name'], user_state[telegram_id]['phone'], user_state[telegram_id]['bank'], initials, telegram_id))
    conn.commit()
    conn.close()
    del user_state[telegram_id]
    bot.reply_to(message, "✅ Вы успешно зарегистрированы как работник! Вы на смене.", reply_markup=worker_menu())

def customer_register_name(message, telegram_id):
    name = message.text
    user_state[telegram_id]['name'] = name
    msg = bot.reply_to(message, "Введите ваш номер телефона (в свободном формате):")
    bot.register_next_step_handler(msg, customer_register_phone, telegram_id)

def customer_register_phone(message, telegram_id):
    phone = message.text
    user_state[telegram_id]['phone'] = phone
    msg = bot.reply_to(message, "Введите ваш район (например, Центральный, Заводской):")
    bot.register_next_step_handler(msg, customer_register_district, telegram_id)

def customer_register_district(message, telegram_id):
    district = message.text
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET name = ?, phone = ?, district = ? WHERE telegram_id = ?",
              (user_state[telegram_id]['name'], user_state[telegram_id]['phone'], district, telegram_id))
    conn.commit()
    conn.close()
    del user_state[telegram_id]
    bot.reply_to(message, "✅ Вы успешно зарегистрированы как заказчик!", reply_markup=customer_menu())

# === МЕНЮ РАБОТНИКА ===
# Свободные заказы
@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def list_open_orders(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Эта функция только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Сначала пройдите регистрацию (кнопка 'Регистрация').")
        return

    orders = get_open_orders()
    if not orders:
        bot.reply_to(message, "📭 Активных заказов нет.")
        return

    for order in orders:
        order_id = order[0]
        address = order[3]
        hours = order[4]
        people = order[5]
        total = order[6]
        payout = order[8]  # payout_per_person
        zakazchik_name = order[2]
        # Показываем заказ
        text = (f"🆔 Заказ #{order_id}\n"
                f"📍 Адрес: {address}\n"
                f"⏱ Часы: {hours}\n"
                f"👥 Человек: {people}\n"
                f"💰 Общая сумма: {total}₽\n"
                f"💵 Выплата каждому: {payout}₽\n"
                f"👤 Заказчик: {zakazchik_name}\n")
        # Кнопка "Забрать"
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(KeyboardButton(f"✅ Забрать #{order_id}"))
        keyboard.row(KeyboardButton("⬅️ Назад"))
        bot.send_message(message.chat.id, text, reply_markup=keyboard)

# Обработка "Забрать #номер"
@bot.message_handler(func=lambda m: m.text.startswith('✅ Забрать #'))
def take_order(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Сначала пройдите регистрацию.")
        return

    try:
        order_id = int(m.text.split('#')[1])
    except:
        bot.reply_to(message, "❌ Неверный формат.")
        return

    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[9] != 'open':  # status index 9
        bot.reply_to(message, "❌ Этот заказ уже не актуален.")
        return

    # Проверяем, не взял ли уже этот работник этот заказ
    assignments = get_assignments_for_order(order_id)
    if any(a[0] == user[0] for a in assignments):
        bot.reply_to(message, "❌ Вы уже взяли этот заказ.")
        return

    # Назначаем
    payout = order[8]  # payout_per_person
    add_assignment(order_id, user[0], payout)

    # Проверяем, все ли люди назначены
    people = order[5]
    if len(assignments) + 1 >= people:
        # все собраны, меняем статус на in_progress
        update_order_status(order_id, 'in_progress')
        bot.reply_to(message, f"✅ Заказ #{order_id} полностью укомплектован! Статус: в работе.")
        # Уведомляем заказчика
        try:
            bot.send_message(order[1], f"🔔 Заказ #{order_id} полностью укомплектован. Работники приступят.")
        except:
            pass
    else:
        bot.reply_to(message, f"✅ Вы взяли заказ #{order_id}. Ожидаем остальных работников ({people - len(assignments) - 1} чел.)")

# Мои выплаты
@bot.message_handler(func=lambda m: m.text == '💰 Мои выплаты')
def my_payouts(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    orders = get_worker_orders(user[0])
    if not orders:
        bot.reply_to(message, "💰 У вас пока нет выполненных заказов.")
        return

    total = 0
    text = "💰 Ваши выплаты:\n\n"
    for o in orders:
        order_id, address, hours, people, total_sum, status, payout = o
        text += f"🆔 Заказ #{order_id}: {address}, {hours}ч, {people}чел, выплата {payout}₽, статус {status}\n"
        if status == 'completed':
            total += payout
    text += f"\n💰 Общая сумма выплат: {total}₽"
    bot.reply_to(message, text)

# Профиль работника / заказчика (общая)
@bot.message_handler(func=lambda m: m.text == '👤 Профиль')
def profile(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None:
        bot.reply_to(message, "Начните с /start")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    name = user[2] or "не указано"
    phone = user[3] or "не указан"
    role = user[7]
    rating = user[8]
    on_shift = user[9]
    agreement = user[10]
    blocked = user[11]
    role_names = {'rabotnik': 'Работник', 'zakazchik': 'Заказчик', 'moderator': 'Модератор'}
    text = (f"👤 Профиль\n\n"
            f"Имя: {name}\n"
            f"Телефон: {phone}\n"
            f"Роль: {role_names.get(role, role)}\n"
            f"Рейтинг: {rating}\n"
            f"На смене: {'Да' if on_shift else 'Нет'}\n"
            f"Соглашение: {'Принято' if agreement else 'Не принято'}\n"
            f"Блокировка: {'Да' if blocked else 'Нет'}")
    bot.reply_to(message, text)

# На смене / Отдыхаю
@bot.message_handler(func=lambda m: m.text in ['🔴 Отдыхаю', '🟢 На смене'])
def toggle_shift(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'rabotnik':
        bot.reply_to(message, "❌ Только для работников.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    if message.text == '🔴 Отдыхаю':
        update_user_field(telegram_id, 'on_shift', 0)
        # меняем кнопку на "🟢 На смене"
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        keyboard.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
        keyboard.row(KeyboardButton("🟢 На смене"), KeyboardButton("⬅️ Назад"))
        bot.reply_to(message, "🔴 Вы перешли в режим отдыха. Заказы не приходят.", reply_markup=keyboard)
    else:  # "🟢 На смене"
        update_user_field(telegram_id, 'on_shift', 1)
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
        keyboard.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
        keyboard.row(KeyboardButton("🔴 Отдыхаю"), KeyboardButton("⬅️ Назад"))
        bot.reply_to(message, "🟢 Вы снова на смене!", reply_markup=keyboard)

# === МЕНЮ ЗАКАЗЧИКА ===
# Создать заказ
@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return
    if user[10] == 0:
        bot.reply_to(message, "❌ Сначала пройдите регистрацию (кнопка 'Регистрация').")
        return

    user_state[telegram_id] = {'step': 'order_address'}
    msg = bot.reply_to(message, "Введите адрес работы:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, order_address, telegram_id)

def order_address(message, telegram_id):
    address = message.text
    user_state[telegram_id]['address'] = address
    msg = bot.reply_to(message, "Введите количество часов (число):")
    bot.register_next_step_handler(msg, order_hours, telegram_id)

def order_hours(message, telegram_id):
    try:
        hours = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число. Попробуйте снова.")
        msg = bot.reply_to(message, "Введите количество часов (число):")
        bot.register_next_step_handler(msg, order_hours, telegram_id)
        return
    user_state[telegram_id]['hours'] = hours
    msg = bot.reply_to(message, "Введите количество человек (число):")
    bot.register_next_step_handler(msg, order_people, telegram_id)

def order_people(message, telegram_id):
    try:
        people = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число. Попробуйте снова.")
        msg = bot.reply_to(message, "Введите количество человек (число):")
        bot.register_next_step_handler(msg, order_people, telegram_id)
        return
    hours = user_state[telegram_id]['hours']
    address = user_state[telegram_id]['address']
    total_sum = hours * people * 500
    commission = hours * people * 50
    payout_per_person = (total_sum - commission) // people  # целое число

    # Сохраняем заказ
    user = get_user(telegram_id)
    zakazchik_name = user[2] if user[2] else "Заказчик"
    order_id = create_order(user[0], zakazchik_name, address, hours, people, total_sum, commission, payout_per_person)
    del user_state[telegram_id]

    # Подтверждение
    bot.reply_to(message, f"✅ Заказ #{order_id} создан!\n"
                          f"📍 Адрес: {address}\n"
                          f"⏱ Часы: {hours}\n"
                          f"👥 Человек: {people}\n"
                          f"💰 Общая сумма: {total_sum}₽\n"
                          f"💵 Выплата каждому работнику: {payout_per_person}₽\n"
                          f"Комиссия сервиса: {commission}₽",
                 reply_markup=customer_menu())

    # Рассылка работникам на смене
    workers = get_workers_on_shift()
    if workers:
        text = (f"🔔 Новый заказ!\n"
                f"📍 Адрес: {address}\n"
                f"⏱ Часы: {hours}\n"
                f"👥 Человек: {people}\n"
                f"💵 Выплата: {payout_per_person}₽/чел\n"
                f"⭐ Рейтинг заказчика: {user[8]}\n"
                f"Для просмотра нажмите 'Свободные заказы'")
        for w in workers:
            try:
                bot.send_message(w, text)
            except:
                pass

# Мои заказы (заказчик)
@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_customer(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    orders = get_customer_orders(user[0])
    if not orders:
        bot.reply_to(message, "📭 У вас нет заказов.")
        return

    for order in orders:
        status_map = {'open': '🟢 Открыт', 'in_progress': '🟡 В работе', 'completed': '✅ Завершён'}
        text = (f"🆔 Заказ #{order[0]}\n"
                f"Адрес: {order[3]}\n"
                f"Часы: {order[4]}, чел: {order[5]}\n"
                f"Сумма: {order[6]}₽\n"
                f"Статус: {status_map.get(order[9], order[9])}\n")
        # Если заказ в работе или открыт, можно завершить (только для заказчика)
        if order[9] in ('open', 'in_progress'):
            keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
            keyboard.row(KeyboardButton(f"✅ Завершить #{order[0]}"))
            keyboard.row(KeyboardButton("⬅️ Назад"))
            bot.send_message(message.chat.id, text, reply_markup=keyboard)
        else:
            bot.send_message(message.chat.id, text)

# Завершить заказ (заказчик)
@bot.message_handler(func=lambda m: m.text.startswith('✅ Завершить #'))
def complete_order_customer(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    try:
        order_id = int(m.text.split('#')[1])
    except:
        bot.reply_to(message, "❌ Неверный формат.")
        return

    order = get_order(order_id)
    if not order or order[1] != user[0]:
        bot.reply_to(message, "❌ Это не ваш заказ.")
        return
    if order[9] == 'completed':
        bot.reply_to(message, "❌ Заказ уже завершён.")
        return

    update_order_status(order_id, 'completed')
    # Начисляем выплаты работникам (уже есть в assignments)
    bot.reply_to(message, f"✅ Заказ #{order_id} завершён. Спасибо!")

# Жалоба
@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[7] != 'zakazchik':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    if user[11] == 1:
        bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_menu())
        return

    msg = bot.reply_to(message, "Опишите вашу жалобу (текст). Модератор получит сообщение.", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, send_complaint, telegram_id)

def send_complaint(message, telegram_id):
    complaint_text = message.text
    user = get_user(telegram_id)
    text = f"⚠️ ЖАЛОБА от заказчика {user[2] if user[2] else 'без имени'} (ID {telegram_id}):\n{complaint_text}"
    for mod_id in MODERATOR_IDS:
        try:
            bot.send_message(mod_id, text)
        except:
            pass
    bot.reply_to(message, "✅ Жалоба отправлена модератору.", reply_markup=customer_menu())

# === МЕНЮ МОДЕРАТОРА ===
# Выплаты (просмотр всех выплат, статистика)
@bot.message_handler(func=lambda m: m.text == '💰 Выплаты')
def moderator_payouts(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    # Просто покажем общую сумму всех выплат
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT SUM(payout) FROM assignments")
    total = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM assignments")
    count = c.fetchone()[0] or 0
    conn.close()
    bot.reply_to(message, f"💰 Общая сумма выплат: {total}₽\n"
                          f"👥 Количество выплат: {count}")

# Активные заказы
@bot.message_handler(func=lambda m: m.text == '🟡 Активные')
def moderator_active_orders(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status IN ('open', 'in_progress') ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "🟡 Активных заказов нет.")
        return
    for order in rows:
        text = (f"🆔 Заказ #{order[0]}\n"
                f"Заказчик: {order[2]}\n"
                f"Адрес: {order[3]}\n"
                f"Часы: {order[4]}, чел: {order[5]}\n"
                f"Сумма: {order[6]}, комиссия: {order[7]}\n"
                f"Статус: {order[9]}\n")
        bot.send_message(message.chat.id, text)

# Завершённые заказы
@bot.message_handler(func=lambda m: m.text == '✅ Завершённые')
def moderator_completed_orders(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status = 'completed' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "✅ Завершённых заказов нет.")
        return
    for order in rows:
        text = (f"🆔 Заказ #{order[0]}\n"
                f"Заказчик: {order[2]}\n"
                f"Адрес: {order[3]}\n"
                f"Часы: {order[4]}, чел: {order[5]}\n"
                f"Сумма: {order[6]}, комиссия: {order[7]}\n")
        bot.send_message(message.chat.id, text)

# Работники (список)
@bot.message_handler(func=lambda m: m.text == '👥 Работники')
def moderator_workers(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    workers = get_workers_list()
    if not workers:
        bot.reply_to(message, "👥 Работников нет.")
        return
    text = "👥 Список работников:\n\n"
    for w in workers:
        text += f"ID: {w[0]}, Имя: {w[1]}, Рейтинг: {w[2]}, Блок: {'да' if w[3] else 'нет'}\n"
    bot.reply_to(message, text)

# Статистика (общая)
@bot.message_handler(func=lambda m: m.text == '📊 Статистика')
def moderator_statistics(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
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
    completed_orders = c.fetchone()[0]
    conn.close()
    text = (f"📊 Статистика:\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"👷 Работников: {workers}\n"
            f"🏢 Заказчиков: {customers}\n"
            f"📦 Всего заказов: {total_orders}\n"
            f"✅ Завершённых: {completed_orders}")
    bot.reply_to(message, text)

# Оценить (модератор ставит +1, 0, -1)
@bot.message_handler(func=lambda m: m.text == '⭐ Оценить')
def moderator_rate_start(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    msg = bot.reply_to(message, "Введите ID пользователя (число) из списка работников.", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, moderator_rate_get_user)

def moderator_rate_get_user(message):
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
        bot.reply_to(message, "❌ Можно оценивать только работников.", reply_markup=moderator_menu())
        return
    # Запоминаем user_id для оценки
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
    keyboard.row(KeyboardButton("⬅️ Назад"))
    msg = bot.reply_to(message, f"Выберите оценку для работника {user[2]} (текущий рейтинг: {user[8]}):", reply_markup=keyboard)
    bot.register_next_step_handler(msg, moderator_rate_apply, user_id)

def moderator_rate_apply(message, user_id):
    if message.text not in ['➕ +1', '➖ -1', '⏺ 0']:
        bot.reply_to(message, "❌ Нажмите одну из кнопок.", reply_markup=moderator_menu())
        return
    delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
    add_rating(user_id, delta)
    user = get_user_by_id(user_id)
    bot.reply_to(message, f"✅ Оценка применена. Новый рейтинг работника: {user[8]}", reply_markup=moderator_menu())

# Арбитраж
@bot.message_handler(func=lambda m: m.text == '⚖️ Арбитраж')
def moderator_arbitration(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    # Показываем список заказов in_progress и completed для возможного арбитража
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
        text += f"ID: {r[0]}, Заказчик: {r[1]}, Адрес: {r[2]}, Статус: {r[3]}\n"
    text += "\nДля арбитража введите /arbitrate ID_заказа действие (например: /arbitrate 1 refund)"
    bot.reply_to(message, text)

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "❌ Используйте: /arbitrate ID_заказа действие (refund, penalty, ban)")
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
        # Возврат денег заказчику (отмена заказа)
        update_order_status(order_id, 'completed')  # или можно отменить
        bot.reply_to(message, f"✅ Заказ #{order_id} отменён, деньги возвращены заказчику.")
    elif action == 'penalty':
        # Штраф: снять баллы с работников? или с заказчика? Упростим: снизим рейтинг заказчика
        zakazchik_id = order[1]
        add_rating(zakazchik_id, -1)  # снимаем 1 балл
        bot.reply_to(message, f"✅ Заказчику #{zakazchik_id} снижен рейтинг на 1.")
    elif action == 'ban':
        # Блокировка заказчика
        zakazchik_id = order[1]
        update_user_field_by_id(zakazchik_id, 'blocked', 1)
        bot.reply_to(message, f"✅ Заказчик #{zakazchik_id} заблокирован.")
    else:
        bot.reply_to(message, "❌ Неизвестное действие. Доступны: refund, penalty, ban.")

# Блокировка пользователя
@bot.message_handler(func=lambda m: m.text == '🔒 Блок')
def moderator_block(message):
    if message.from_user.id not in MODERATOR_IDS:
        return
    msg = bot.reply_to(message, "Введите имя пользователя (часть имени) для блокировки:", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, block_user)

def block_user(message):
    name = message.text
    affected = block_user_by_name(name)
    if affected > 0:
        bot.reply_to(message, f"✅ Заблокировано {affected} пользователей.", reply_markup=moderator_menu())
    else:
        bot.reply_to(message, "❌ Пользователи не найдены.", reply_markup=moderator_menu())

# === ЗАБЛОКИРОВАННЫЙ ПОЛЬЗОВАТЕЛЬ ===
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator(message):
    telegram_id = message.from_user.id
    user = get_user(telegram_id)
    if user is None or user[11] == 0:
        return
    for mod_id in MODERATOR_IDS:
        try:
            bot.send_message(mod_id, f"📞 Пользователь {telegram_id} (имя: {user[2]}) запросил связь с модератором.")
        except:
            pass
    bot.reply_to(message, "✅ Ваш запрос отправлен модератору. Ожидайте.")

# === ОБРАБОТЧИК ВСЕХ ТЕКСТОВЫХ СООБЩЕНИЙ (защита от спама) ===
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.reply_to(message, "Пожалуйста, используйте кнопки меню.", reply_markup=main_menu())

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
