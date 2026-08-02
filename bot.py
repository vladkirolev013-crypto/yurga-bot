import telebot
import os
import sqlite3
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    print("❌ Ошибка: BOT_TOKEN не задан!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# === ЗАМЕНИ НА СВОЙ ID И ID НАПАРНИКА ===
MODERATOR_IDS = [8746212340]  # <-- ВСТАВЬ СВОИ ЦИФРЫ

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
        registered_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        title TEXT,
        description TEXT,
        price INTEGER,
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
    c.execute("SELECT username, first_name, role, balance, completed_orders, rating FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_active_orders():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, creator_id, title, description, price, contacts, created_at FROM orders WHERE status = 'active' ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_orders():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, creator_id, title, status, price, executor_id, created_at FROM orders ORDER BY created_at DESC")
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

def save_order(creator_id, title, description, price, contacts):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''INSERT INTO orders (creator_id, title, description, price, contacts, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (creator_id, title, description, price, contacts, datetime.now().isoformat()))
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

def notify_workers_and_moderators(order_id, title, price, creator_name):
    workers = get_workers()
    text = f"🔔 Новый заказ!\n\nНазвание: {title}\nЦена: {price}₽\nЗаказчик: {creator_name}\n\nЧтобы откликнуться, используй кнопки."
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

# === ГЛАВНОЕ МЕНЮ ===
def main_menu(user_id):
    role = get_user_role(user_id)
    markup = InlineKeyboardMarkup(row_width=2)
    btn_orders = InlineKeyboardButton("📋 Заказы", callback_data="menu_orders")
    btn_profile = InlineKeyboardButton("👤 Профиль", callback_data="menu_profile")
    btns = [btn_orders, btn_profile]

    if role == 'customer':
        btn_new = InlineKeyboardButton("➕ Новый заказ", callback_data="menu_new_order")
        btns.append(btn_new)
    elif role == 'worker':
        btn_take = InlineKeyboardButton("✅ Откликнуться", callback_data="menu_take")
        btns.append(btn_take)
    elif role == 'moderator':
        btn_mod = InlineKeyboardButton("🛡️ Панель модератора", callback_data="menu_moderate")
        btns.append(btn_mod)

    markup.add(*btns)
    return markup

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

    markup = InlineKeyboardMarkup(row_width=2)
    btn1 = InlineKeyboardButton("👷 Работник", callback_data="role_worker")
    btn2 = InlineKeyboardButton("🏢 Заказчик", callback_data="role_customer")
    btns = [btn1, btn2]
    if user_id in MODERATOR_IDS:
        btn3 = InlineKeyboardButton("🛡️ Модератор", callback_data="role_moderator")
        btns.append(btn3)
    markup.add(*btns)

    bot.send_message(
        message.chat.id,
        f"🤖 Привет, {first_name}!\n\nВыбери свою роль:",
        reply_markup=markup
    )

# === ВЫБОР РОЛИ ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('role_'))
def role_callback(call):
    user_id = call.from_user.id
    role = call.data.split('_')[1]
    roles_map = {
        "worker": "👷 Работник",
        "customer": "🏢 Заказчик",
        "moderator": "🛡️ Модератор"
    }
    if role == 'moderator' and user_id not in MODERATOR_IDS:
        bot.answer_callback_query(call.id, "❌ Нет прав.")
        return
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ Ты выбрал роль: {roles_map[role]}")
    bot.edit_message_text(
        f"✅ Ты теперь {roles_map[role]}.\n\nИспользуй меню.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.send_message(call.message.chat.id, "📱 Главное меню:", reply_markup=main_menu(user_id))

# === ОБРАБОТЧИК ВСЕХ КНОПОК МЕНЮ ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def menu_callback(call):
    user_id = call.from_user.id
    action = call.data.split('_')[1]
    bot.answer_callback_query(call.id)

    if action == 'orders':
        orders = get_active_orders()
        if not orders:
            bot.send_message(call.message.chat.id, "📭 Активных заказов нет.")
            return
        text = "📋 Активные заказы:\n\n"
        for o in orders:
            text += f"🔹 {o[2]}\n   Описание: {o[3]}\n   Цена: {o[4]}₽\n   Контакты: {o[5]}\n   Создан: {o[6][:10]}\n\n"
        bot.send_message(call.message.chat.id, text)

    elif action == 'profile':
        data = get_user_data(user_id)
        if not data:
            bot.send_message(call.message.chat.id, "❌ Ошибка профиля.")
            return
        username, first_name, role, balance, completed, rating = data
        role_map = {"worker": "👷 Работник", "customer": "🏢 Заказчик", "moderator": "🛡️ Модератор"}
        text = (f"👤 Профиль\n\nИмя: {first_name}\nUsername: @{username}\nРоль: {role_map.get(role, role)}\n💰 Баланс: {balance}₽\n✅ Выполнено: {completed}\n⭐ Рейтинг: {rating:.1f}")
        bot.send_message(call.message.chat.id, text)

    elif action == 'new_order':
        role = get_user_role(user_id)
        if role != 'customer':
            bot.send_message(call.message.chat.id, "❌ Только для заказчиков.")
            return
        msg = bot.send_message(call.message.chat.id, "Введите название заказа (или /cancel для отмены):")
        bot.register_next_step_handler(msg, get_order_title, user_id)

    elif action == 'take':
        role = get_user_role(user_id)
        if role != 'worker':
            bot.send_message(call.message.chat.id, "❌ Только для работников.")
            return
        msg = bot.send_message(call.message.chat.id, "Введите ID заказа (из /orders):")
        bot.register_next_step_handler(msg, take_order_by_id, user_id)

    elif action == 'moderate':
        if user_id not in MODERATOR_IDS:
            bot.send_message(call.message.chat.id, "❌ Нет прав.")
            return
        orders = get_all_orders()
        if not orders:
            bot.send_message(call.message.chat.id, "📭 Заказов нет.")
            return
        text = "📋 Все заказы:\n\n"
        for o in orders:
            status = o[4]
            executor = o[5] if o[5] else "не назначен"
            text += f"ID: {o[0]}, Название: {o[2]}, Статус: {status}, Исполнитель: {executor}\n"
        text += "\nЧтобы завершить заказ, нажми кнопку ниже."
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton("✅ Завершить заказ", callback_data="mod_complete")
        markup.add(btn)
        bot.send_message(call.message.chat.id, text, reply_markup=markup)

# === ОТДЕЛЬНЫЙ ОБРАБОТЧИК ДЛЯ "ЗАВЕРШИТЬ ЗАКАЗ" ===
@bot.callback_query_handler(func=lambda call: call.data == 'mod_complete')
def mod_complete_callback(call):
    user_id = call.from_user.id
    if user_id not in MODERATOR_IDS:
        bot.answer_callback_query(call.id, "❌ Нет прав.")
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Введите ID заказа для завершения:")
    bot.register_next_step_handler(msg, complete_order_by_id, user_id)

# === ФУНКЦИИ СОЗДАНИЯ ЗАКАЗА ===
def get_order_title(message, user_id):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    title = message.text
    msg = bot.send_message(message.chat.id, "Введите описание (или /cancel):")
    bot.register_next_step_handler(msg, get_order_description, user_id, title)

def get_order_description(message, user_id, title):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    description = message.text
    msg = bot.send_message(message.chat.id, "Введите цену (только число):")
    bot.register_next_step_handler(msg, get_order_price, user_id, title, description)

def get_order_price(message, user_id, title, description):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    try:
        price = int(message.text)
    except:
        bot.reply_to(message, "❌ Это не число. Попробуйте ещё раз.")
        msg = bot.send_message(message.chat.id, "Цена (руб):")
        bot.register_next_step_handler(msg, get_order_price, user_id, title, description)
        return
    msg = bot.send_message(message.chat.id, "Введите контакты (телефон, Telegram) или /cancel:")
    bot.register_next_step_handler(msg, get_order_contacts, user_id, title, description, price)

def get_order_contacts(message, user_id, title, description, price):
    if message.text == '/cancel':
        bot.reply_to(message, "❌ Отменено.")
        return
    contacts = message.text
    order_id = save_order(user_id, title, description, price, contacts)
    bot.reply_to(message, f"✅ Заказ создан! ID: {order_id}")
    creator_name = message.from_user.first_name or "Пользователь"
    notify_workers_and_moderators(order_id, title, price, creator_name)
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=main_menu(user_id))

# === ОТКЛИК ПО ID ===
def take_order_by_id(message, user_id):
    try:
        order_id = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.")
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[5] != 'active':
        bot.reply_to(message, "❌ Заказ уже не активен.")
        return
    responses = get_responses_for_order(order_id)
    if any(r[0] == user_id for r in responses):
        bot.reply_to(message, "❌ Ты уже откликнулся.")
        return
    add_response(order_id, user_id)
    bot.reply_to(message, "✅ Отклик отправлен!")
    creator_id = order[1]
    try:
        bot.send_message(creator_id, f"🔔 На заказ «{order[2]}» откликнулся @{message.from_user.username or 'без username'}.")
    except:
        pass
    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=main_menu(user_id))

# === ЗАВЕРШЕНИЕ ЗАКАЗА (модератор) ===
def complete_order_by_id(message, moderator_id):
    try:
        order_id = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.")
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[5] != 'active':
        bot.reply_to(message, "❌ Заказ уже завершён.")
        return
    responses = get_responses_for_order(order_id)
    if not responses:
        bot.reply_to(message, "❌ На заказ никто не откликнулся.")
        return
    executor_id = responses[0][0]
    price = order[4]
    commission = 50
    worker_payment = price - commission

    update_order_status(order_id, 'completed', executor_id)
    add_balance(executor_id, worker_payment)
    increment_completed(executor_id)

    try:
        markup = InlineKeyboardMarkup()
        for i in range(1, 6):
            btn = InlineKeyboardButton(str(i), callback_data=f"rate_{executor_id}_{i}_{order_id}")
            markup.add(btn)
        bot.send_message(order[1], f"⭐ Оцени работу исполнителя по заказу «{order[2]}» (1–5):", reply_markup=markup)
    except:
        pass

    try:
        bot.send_message(executor_id, f"✅ Заказ «{order[2]}» выполнен! Начислено {worker_payment}₽ (комиссия {commission}₽).")
    except:
        pass

    bot.reply_to(message, f"✅ Заказ #{order_id} завершён. Исполнитель получил {worker_payment}₽.")

    executor_balance = get_user_data(executor_id)[3]
    if executor_balance >= 5000:
        try:
            bot.send_message(executor_id, "⚠️ Внимание! Баланс превысил 5000₽. Рекомендуем оформить ИП или самозанятость.")
        except:
            pass

    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"🛡️ Заказ #{order_id} завершён модератором.")
        except:
            pass

    bot.send_message(message.chat.id, "📱 Главное меню:", reply_markup=main_menu(moderator_id))

# === ОБРАБОТКА ОЦЕНКИ ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('rate_'))
def rate_callback(call):
    _, worker_id, rating, order_id = call.data.split('_')
    worker_id = int(worker_id)
    rating = int(rating)
    update_rating(worker_id, rating)
    bot.answer_callback_query(call.id, "✅ Спасибо за оценку!")
    bot.edit_message_text("⭐ Оценка сохранена.", chat_id=call.message.chat.id, message_id=call.message.message_id)

# === КОМАНДА /new_order (на случай, если кнопка не работает) ===
@bot.message_handler(commands=['new_order'])
def cmd_new_order(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'customer':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    msg = bot.send_message(message.chat.id, "Введите название заказа (или /cancel):")
    bot.register_next_step_handler(msg, get_order_title, user_id)

# === /help ===
@bot.message_handler(commands=['help'])
def send_help(message):
    bot.send_message(message.chat.id, "📱 Используй меню.", reply_markup=main_menu(message.from_user.id))

# === ЗАПУСК ===
print("✅ Бот запущен и слушает...")
try:
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
