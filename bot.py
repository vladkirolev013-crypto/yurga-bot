import telebot
import sqlite3
from datetime import datetime
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'
bot = telebot.TeleBot(TOKEN)

MODERATOR_IDS = [8746212340]

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        role TEXT,
        phone TEXT,
        bank TEXT,
        balance INTEGER DEFAULT 0,
        completed_orders INTEGER DEFAULT 0,
        rating REAL DEFAULT 0.0,
        rating_count INTEGER DEFAULT 0,
        registered_at TEXT,
        agreement BOOLEAN DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        title TEXT,
        address TEXT,
        price_per_hour INTEGER,
        hours INTEGER,
        people INTEGER,
        total_price INTEGER,
        contacts TEXT,
        status TEXT DEFAULT 'active',
        executor_id INTEGER,
        completed_at TEXT,
        created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        worker_id INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_user_role(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_user_data(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT username, first_name, role, phone, balance, completed_orders, rating, agreement FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_active_orders():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, creator_id, title, address, price_per_hour, hours, people, total_price, contacts, created_at FROM orders WHERE status = 'active' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_my_orders(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, title, status, total_price, created_at FROM orders WHERE creator_id = ? ORDER BY created_at DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_orders():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, creator_id, title, status, total_price, executor_id, created_at FROM orders ORDER BY created_at DESC")
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

def update_order_status(order_id, status, executor_id=None):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    if status == 'completed':
        c.execute("UPDATE orders SET status = ?, executor_id = ?, completed_at = ? WHERE id = ?",
                  (status, executor_id, datetime.now().isoformat(), order_id))
    else:
        c.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def save_order(creator_id, title, address, price_per_hour, hours, people, total_price, contacts):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''INSERT INTO orders 
                 (creator_id, title, address, price_per_hour, hours, people, total_price, contacts, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (creator_id, title, address, price_per_hour, hours, people, total_price, contacts, datetime.now().isoformat()))
    conn.commit()
    order_id = c.lastrowid
    conn.close()
    return order_id

def add_response(order_id, worker_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("INSERT INTO responses (order_id, worker_id, created_at) VALUES (?, ?, ?)",
              (order_id, worker_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_responses_for_order(order_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT worker_id, created_at FROM responses WHERE order_id = ?", (order_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_workers():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE role = 'worker'")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_balance(user_id, amount):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def increment_completed(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET completed_orders = completed_orders + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def update_rating(worker_id, rating):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET rating = ((rating * rating_count) + ?) / (rating_count + 1), rating_count = rating_count + 1 WHERE user_id = ?",
              (rating, worker_id))
    conn.commit()
    conn.close()

def update_user_phone_name(user_id, first_name, phone):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET first_name = ?, phone = ? WHERE user_id = ?", (first_name, phone, user_id))
    conn.commit()
    conn.close()

def update_user_agreement(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET agreement = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, role, phone, balance, completed_orders FROM users")
    rows = c.fetchall()
    conn.close()
    return rows

def notify_workers_and_moderators(order_id, title, total_price, creator_name):
    workers = get_workers()
    text = f"🔔 Новый заказ!\n\nНазвание: {title}\nОбщая стоимость: {total_price}₽\nЗаказчик: {creator_name}\n\nЧтобы откликнуться, используй кнопки."
    for w in workers:
        try:
            bot.send_message(w, text)
        except:
            pass
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"🛡️ Модератор: новый заказ!\n{text}")
        except:
            pass

# === КЛАВИАТУРА ===
def get_main_keyboard(user_id):
    role = get_user_role(user_id)
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    if role == 'customer':
        keyboard.row(KeyboardButton("📝 Создать заказ"), KeyboardButton("📋 Мои заказы"))
        keyboard.row(KeyboardButton("👤 Профиль"), KeyboardButton("📝 Регистрация"))
    elif role == 'worker':
        keyboard.row(KeyboardButton("📋 Все заказы"), KeyboardButton("✅ Откликнуться"))
        keyboard.row(KeyboardButton("📌 Мои отклики"), KeyboardButton("👤 Профиль"))
        keyboard.row(KeyboardButton("📝 Регистрация"))
    elif role == 'moderator':
        keyboard.row(KeyboardButton("🛡️ Все заказы"), KeyboardButton("✅ Завершить заказ"))
        keyboard.row(KeyboardButton("👥 Все пользователи"), KeyboardButton("👤 Профиль"))
        keyboard.row(KeyboardButton("📝 Регистрация"))
    else:
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(KeyboardButton("👷 Работник"), KeyboardButton("🏢 Заказчик"))
        if user_id in MODERATOR_IDS:
            keyboard.row(KeyboardButton("🛡️ Модератор"))
    return keyboard

# === /start ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Нет username"
    first_name = message.from_user.first_name or ""

    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, username, first_name, balance, registered_at) VALUES (?, ?, ?, 0, ?)",
                  (user_id, username, first_name, datetime.now().isoformat()))
        conn.commit()
    conn.close()

    role = get_user_role(user_id)
    if role:
        bot.send_message(message.chat.id, f"👋 С возвращением, {first_name}!", reply_markup=get_main_keyboard(user_id))
    else:
        keyboard = get_main_keyboard(user_id)
        bot.send_message(message.chat.id, f"🤖 Привет, {first_name}!\n\nВыбери свою роль, нажав кнопку:", reply_markup=keyboard)

# === ОБРАБОТКА ВЫБОРА РОЛИ ===
@bot.message_handler(func=lambda message: message.text in ['👷 Работник', '🏢 Заказчик', '🛡️ Модератор'])
def role_choice(message):
    user_id = message.from_user.id
    role_map = {
        '👷 Работник': 'worker',
        '🏢 Заказчик': 'customer',
        '🛡️ Модератор': 'moderator'
    }
    role = role_map[message.text]
    if role == 'moderator' and user_id not in MODERATOR_IDS:
        bot.reply_to(message, "❌ Нет прав.")
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"✅ Ты выбрал роль: {message.text}")
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(user_id))

# === ОБРАБОТЧИКИ КНОПОК МЕНЮ ===
@bot.message_handler(func=lambda message: message.text == "📝 Создать заказ")
def cmd_create_order(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'customer':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    data = get_user_data(user_id)
    if not data or not data[1] or not data[3]:
        bot.reply_to(message, "❌ Сначала пройдите регистрацию (меню Регистрация).")
        return
    if not data[7]:
        bot.reply_to(message, "❌ Вы не приняли условия соглашения. Зайдите в Регистрацию и поставьте галочку.")
        return
    msg = bot.send_message(message.chat.id, "Введите название заказа (или /cancel для отмены):")
    bot.register_next_step_handler(msg, get_order_title, user_id)

@bot.message_handler(func=lambda message: message.text == "📋 Мои заказы")
def cmd_my_orders(message):
    user_id = message.from_user.id
    orders = get_my_orders(user_id)
    if not orders:
        bot.reply_to(message, "📭 У вас пока нет заказов.")
    else:
        text = "📋 Ваши заказы:\n\n"
        for o in orders:
            status_map = {'active': '🟢 Активен', 'completed': '✅ Завершён'}
            text += f"ID: {o[0]}, Название: {o[1]}, Статус: {status_map.get(o[2], o[2])}, Сумма: {o[3]}₽, Создан: {o[4][:10]}\n"
        bot.reply_to(message, text)

@bot.message_handler(func=lambda message: message.text == "👤 Профиль")
def cmd_profile(message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if not data:
        bot.reply_to(message, "❌ Ошибка профиля.")
        return
    username, first_name, role, phone, balance, completed, rating, agreement = data
    role_map = {"worker": "👷 Работник", "customer": "🏢 Заказчик", "moderator": "🛡️ Модератор"}
    text = f"👤 Профиль\n\nИмя: {first_name or 'не указано'}\nUsername: @{username}\nРоль: {role_map.get(role, role)}"
    if role != 'moderator':
        text += f"\n📞 Телефон: {phone or 'не указан'}"
    text += f"\n💰 Баланс: {balance}₽\n✅ Выполнено заказов: {completed}\n⭐ Рейтинг: {rating:.1f}"
    if role != 'moderator':
        text += f"\n📜 Согласие: {'да' if agreement else 'нет'}"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda message: message.text == "📝 Регистрация")
def cmd_register(message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if data and data[1] and data[3]:
        bot.reply_to(message, f"✅ Вы уже зарегистрированы как {data[1]}, телефон {data[3]}. Хотите обновить данные?")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔄 Обновить", callback_data="register_force"))
        bot.send_message(message.chat.id, "Нажмите кнопку, чтобы обновить:", reply_markup=markup)
        return
    start_registration(message, user_id)

@bot.message_handler(func=lambda message: message.text == "📋 Все заказы")
def cmd_all_orders(message):
    orders = get_active_orders()
    if not orders:
        bot.reply_to(message, "📭 Активных заказов нет.")
        return
    text = "📋 Активные заказы:\n\n"
    for o in orders:
        text += f"🔹 {o[2]}\n   Адрес: {o[3]}\n   Цена за час: {o[4]}₽\n   Часы: {o[5]}, чел: {o[6]}\n   Итого: {o[7]}₽\n   Контакты: {o[8]}\n   Создан: {o[9][:10]}\n\n"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda message: message.text == "✅ Откликнуться")
def cmd_take(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'worker':
        bot.reply_to(message, "❌ Только для работников.")
        return
    data = get_user_data(user_id)
    if not data or not data[1] or not data[3]:
        bot.reply_to(message, "❌ Сначала пройдите регистрацию (меню Регистрация).")
        return
    msg = bot.send_message(message.chat.id, "Введите ID заказа, на который хотите откликнуться (из списка /orders):")
    bot.register_next_step_handler(msg, take_order_by_id, user_id)

@bot.message_handler(func=lambda message: message.text == "📌 Мои отклики")
def cmd_my_responses(message):
    user_id = message.from_user.id
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT order_id, status, created_at FROM responses WHERE worker_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(message, "📭 Вы ещё не откликались на заказы.")
        return
    text = "📌 Ваши отклики:\n\n"
    for r in rows:
        status_map = {'pending': '⏳ Ожидает', 'accepted': '✅ Принят', 'rejected': '❌ Отклонён'}
        text += f"Заказ ID: {r[0]}, Статус: {status_map.get(r[1], r[1])}, Создан: {r[2][:10]}\n"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda message: message.text == "🛡️ Все заказы" and message.from_user.id in MODERATOR_IDS)
def cmd_moderate(message):
    orders = get_all_orders()
    if not orders:
        bot.reply_to(message, "📭 Заказов нет.")
        return
    text = "📋 Все заказы:\n\n"
    for o in orders:
        status = o[3]
        executor = o[5] if o[5] else "не назначен"
        text += f"ID: {o[0]}, Название: {o[2]}, Статус: {status}, Исполнитель: {executor}\n"
    bot.reply_to(message, text)
    bot.send_message(message.chat.id, "Чтобы завершить заказ, отправьте /complete ID_заказа")

@bot.message_handler(func=lambda message: message.text == "✅ Завершить заказ" and message.from_user.id in MODERATOR_IDS)
def cmd_complete(message):
    msg = bot.send_message(message.chat.id, "Введите ID заказа для завершения:")
    bot.register_next_step_handler(msg, complete_order_by_id, message.from_user.id)

@bot.message_handler(func=lambda message: message.text == "👥 Все пользователи" and message.from_user.id in MODERATOR_IDS)
def cmd_users(message):
    users = get_all_users()
    if not users:
        bot.reply_to(message, "👥 Пользователей пока нет.")
        return
    text = "👥 Все пользователи:\n\n"
    for u in users:
        text += f"ID: {u[0]}, Имя: {u[2]}, Роль: {u[3]}, Телефон: {u[4] or 'нет'}, Баланс: {u[5]}, Выполнено: {u[6]}\n"
    bot.reply_to(message, text)

# === РЕГИСТРАЦИЯ ===
def start_registration(message, user_id):
    role = get_user_role(user_id)
    if role == 'moderator':
        msg = bot.send_message(message.chat.id, "Введите ваше Имя (только имя):")
        bot.register_next_step_handler(msg, register_moderator_name, user_id)
    else:
        msg = bot.send_message(message.chat.id, "Введите ваши Имя и Отчество (например: Алексей Сергеевич):")
        bot.register_next_step_handler(msg, register_name, user_id)

def register_name(message, user_id):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Регистрация отменена.")
        return
    full_name = message.text
    msg = bot.send_message(message.chat.id, "Введите ваш номер телефона (например: +7 999 123-45-67):")
    bot.register_next_step_handler(msg, register_phone, user_id, full_name)

def register_phone(message, user_id, full_name):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Регистрация отменена.")
        return
    phone = message.text
    update_user_phone_name(user_id, full_name, phone)
    markup = InlineKeyboardMarkup()
    btn_agree = InlineKeyboardButton("✅ Согласен(на)", callback_data="agree_yes")
    markup.add(btn_agree)
    bot.send_message(message.chat.id, 
        "📜 Перед продолжением примите условия:\n\n"
        "Я подтверждаю, что вся ответственность за качество выполнения работ, а также за возможные травмы, кражи и иные риски лежит на заказчике и исполнителе. "
        "Модератор выступает только в роли посредника и не несёт ответственности за указанные обстоятельства. "
        "Претензии по финансовым расчётам принимаются в установленном порядке.\n\n"
        "Нажмите кнопку, чтобы согласиться:",
        reply_markup=markup)

def register_moderator_name(message, user_id):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Регистрация отменена.")
        return
    name = message.text
    update_user_phone_name(user_id, name, None)
    bot.reply_to(message, "✅ Вы успешно зарегистрированы как модератор.")
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(user_id))

# === ОБРАБОТКА СОГЛАСИЯ ===
@bot.callback_query_handler(func=lambda call: call.data == 'agree_yes')
def agree_callback(call):
    user_id = call.from_user.id
    update_user_agreement(user_id)
    bot.answer_callback_query(call.id, "✅ Согласие принято!")
    bot.edit_message_text("✅ Спасибо! Вы приняли условия.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(call.message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(user_id))

@bot.callback_query_handler(func=lambda call: call.data == 'register_force')
def register_force_callback(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id)
    start_registration(call.message, user_id)

# === СОЗДАНИЕ ЗАКАЗА (шаги) ===
def get_order_title(message, user_id):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Создание заказа отменено.")
        return
    title = message.text
    msg = bot.send_message(message.chat.id, "Введите адрес работы:")
    bot.register_next_step_handler(msg, get_order_address, user_id, title)

def get_order_address(message, user_id, title):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    address = message.text
    msg = bot.send_message(message.chat.id, "Введите цену за 1 человеко-час (в рублях):")
    bot.register_next_step_handler(msg, get_order_price, user_id, title, address)

def get_order_price(message, user_id, title, address):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    try:
        price = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число. Попробуйте снова.")
        msg = bot.send_message(message.chat.id, "Цена за час (руб):")
        bot.register_next_step_handler(msg, get_order_price, user_id, title, address)
        return
    msg = bot.send_message(message.chat.id, "На сколько часов работа?")
    bot.register_next_step_handler(msg, get_order_hours, user_id, title, address, price)

def get_order_hours(message, user_id, title, address, price):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    try:
        hours = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число часов.")
        msg = bot.send_message(message.chat.id, "Часы:")
        bot.register_next_step_handler(msg, get_order_hours, user_id, title, address, price)
        return
    msg = bot.send_message(message.chat.id, "Сколько человек нужно?")
    bot.register_next_step_handler(msg, get_order_people, user_id, title, address, price, hours)

def get_order_people(message, user_id, title, address, price, hours):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    try:
        people = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число человек.")
        msg = bot.send_message(message.chat.id, "Количество человек:")
        bot.register_next_step_handler(msg, get_order_people, user_id, title, address, price, hours)
        return
    total_price = price * hours * people
    data = get_user_data(user_id)
    contacts = data[3] if data and data[3] else "не указан"
    markup = InlineKeyboardMarkup()
    btn = InlineKeyboardButton("✅ Подтвердить заказ", callback_data=f"confirm_order_{user_id}_{title}_{address}_{price}_{hours}_{people}_{total_price}")
    markup.add(btn)
    bot.send_message(message.chat.id, 
        f"📊 Итоговая стоимость: {total_price}₽\n\n"
        f"Ваш контактный телефон: {contacts}\n\n"
        f"Для подтверждения нажмите кнопку:",
        reply_markup=markup)

# === ПОДТВЕРЖДЕНИЕ ЗАКАЗА ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_order_'))
def confirm_order_callback(call):
    data = call.data.split('_')
    user_id = int(data[2])
    title = data[3]
    address = data[4]
    price = int(data[5])
    hours = int(data[6])
    people = int(data[7])
    total_price = int(data[8])
    user_data = get_user_data(user_id)
    contacts = user_data[3] if user_data and user_data[3] else "не указан"
    order_id = save_order(user_id, title, address, price, hours, people, total_price, contacts)
    bot.answer_callback_query(call.id, "✅ Заказ создан!")
    bot.edit_message_text(f"✅ Заказ создан!\n\nID: {order_id}\nНазвание: {title}\nАдрес: {address}\nЦена за час: {price}₽\nЧасы: {hours}\nЧеловек: {people}\nОбщая стоимость: {total_price}₽\nКонтакты: {contacts}",
                          chat_id=call.message.chat.id, message_id=call.message.message_id)
    creator_name = user_data[1] if user_data and user_data[1] else "Пользователь"
    notify_workers_and_moderators(order_id, title, total_price, creator_name)
    bot.send_message(call.message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(user_id))

# === ОТКЛИК ПО ID ===
def take_order_by_id(message, user_id):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    try:
        order_id = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.")
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[8] != 'active':
        bot.reply_to(message, "❌ Заказ уже не активен.")
        return
    responses = get_responses_for_order(order_id)
    if any(r[0] == user_id for r in responses):
        bot.reply_to(message, "❌ Вы уже откликнулись на этот заказ.")
        return
    add_response(order_id, user_id)
    bot.reply_to(message, "✅ Отклик отправлен!")
    creator_id = order[1]
    try:
        bot.send_message(creator_id, f"🔔 На ваш заказ «{order[2]}» откликнулся работник @{message.from_user.username or 'без username'}.")
    except:
        pass
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"🛡️ Отклик на заказ #{order_id} от @{message.from_user.username or 'без username'}.")
        except:
            pass
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(user_id))

# === ЗАВЕРШЕНИЕ ЗАКАЗА (модератор) ===
def complete_order_by_id(message, moderator_id):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    try:
        order_id = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.")
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[8] != 'active':
        bot.reply_to(message, "❌ Заказ уже завершён.")
        return
    responses = get_responses_for_order(order_id)
    if not responses:
        bot.reply_to(message, "❌ На заказ никто не откликнулся.")
        return
    executor_id = responses[0][0]
    total_price = order[7]
    commission = 50
    worker_payment = total_price - commission

    update_order_status(order_id, 'completed', executor_id)
    add_balance(executor_id, worker_payment)
    increment_completed(executor_id)

    try:
        markup = InlineKeyboardMarkup()
        for i in range(1, 6):
            btn = InlineKeyboardButton(str(i), callback_data=f"rate_{executor_id}_{i}_{order_id}")
            markup.add(btn)
        bot.send_message(order[1], f"⭐ Оцените работу исполнителя по заказу «{order[2]}» (1–5):", reply_markup=markup)
    except:
        pass

    try:
        bot.send_message(executor_id, f"✅ Заказ «{order[2]}» выполнен! Начислено {worker_payment}₽ (комиссия {commission}₽).")
    except:
        pass

    bot.reply_to(message, f"✅ Заказ #{order_id} завершён. Исполнитель получил {worker_payment}₽.")

    executor_data = get_user_data(executor_id)
    if executor_data:
        executor_balance = executor_data[4]
        if executor_balance >= 5000:
            try:
                bot.send_message(executor_id, "⚠️ Внимание! Ваш баланс превысил 5000₽. Рекомендуем оформить ИП или самозанятость.")
            except:
                pass

    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"🛡️ Заказ #{order_id} завершён модератором.")
        except:
            pass

    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(moderator_id))

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('rate_'))
def rate_callback(call):
    _, worker_id, rating, order_id = call.data.split('_')
    worker_id = int(worker_id)
    rating = int(rating)
    update_rating(worker_id, rating)
    bot.answer_callback_query(call.id, "✅ Спасибо за оценку!")
    bot.edit_message_text("⭐ Оценка сохранена.", chat_id=call.message.chat.id, message_id=call.message.message_id)

# === КОМАНДА /cancel ===
@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    bot.reply_to(message, "❌ Текущее действие отменено. Используйте меню для продолжения.")
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=get_main_keyboard(message.from_user.id))

# === /help ===
@bot.message_handler(commands=['help'])
def send_help(message):
    bot.send_message(message.chat.id, "📱 Используйте меню для управления.", reply_markup=get_main_keyboard(message.from_user.id))

# === ЗАПУСК ===
print("✅ Бот запущен и слушает...")
try:
    bot.delete_webhook()
    bot.remove_webhook()
except:
    pass

while True:
    try:
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
        import time
        time.sleep(5)
