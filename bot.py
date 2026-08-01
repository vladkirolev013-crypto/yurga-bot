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
    c.execute("SELECT username, first_name, role, balance, completed_orders FROM users WHERE user_id = ?", (user_id,))
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

# === УВЕДОМЛЕНИЕ ВСЕМ РАБОТНИКАМ ===
def notify_workers(order_id, title, price):
    workers = get_workers()
    if not workers:
        return
    text = f"🔔 Новый заказ!\n\nНазвание: {title}\nЦена: {price}₽\n\nЧтобы откликнуться, отправьте команду /take_{order_id}"
    for w in workers:
        try:
            bot.send_message(w, text)
        except:
            pass

# === КОМАНДА /start ===
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
    btn3 = InlineKeyboardButton("🛡️ Модератор", callback_data="role_moderator")
    markup.add(btn1, btn2, btn3)

    bot.send_message(
        message.chat.id,
        f"🤖 Привет, {first_name}!\n\n"
        "Я бот для подработки в Юрге.\n"
        "Выбери свою роль:",
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
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ Ты выбрал роль: {roles_map[role]}")
    bot.edit_message_text(
        f"✅ Ты теперь {roles_map[role]}.\n\nИспользуй /help для списка команд.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# === СОЗДАНИЕ ЗАКАЗА (только заказчик) ===
@bot.message_handler(commands=['new_order'])
def new_order(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'customer':
        bot.reply_to(message, "❌ Только для заказчиков.")
        return
    msg = bot.send_message(message.chat.id, "Название заказа:")
    bot.register_next_step_handler(msg, get_order_title, user_id)

def get_order_title(message, user_id):
    title = message.text
    msg = bot.send_message(message.chat.id, "Описание:")
    bot.register_next_step_handler(msg, get_order_description, user_id, title)

def get_order_description(message, user_id, title):
    description = message.text
    msg = bot.send_message(message.chat.id, "Цена (руб):")
    bot.register_next_step_handler(msg, get_order_price, user_id, title, description)

def get_order_price(message, user_id, title, description):
    try:
        price = int(message.text)
    except:
        bot.reply_to(message, "❌ Введи число.")
        return
    msg = bot.send_message(message.chat.id, "Контакты (телефон, Telegram):")
    bot.register_next_step_handler(msg, get_order_contacts, user_id, title, description, price)

def get_order_contacts(message, user_id, title, description, price):
    contacts = message.text
    order_id = save_order(user_id, title, description, price, contacts)
    bot.reply_to(message, f"✅ Заказ создан! ID: {order_id}")

    # Уведомление работникам
    notify_workers(order_id, title, price)

# === ПРОСМОТР ЗАКАЗОВ ===
@bot.message_handler(commands=['orders'])
def list_orders(message):
    orders = get_active_orders()
    if not orders:
        bot.reply_to(message, "📭 Активных заказов нет.")
        return
    text = "📋 Активные заказы:\n\n"
    for o in orders:
        text += f"🔹 {o[2]}\n   Описание: {o[3]}\n   Цена: {o[4]}₽\n   Контакты: {o[5]}\n   Создан: {o[6][:10]}\n\n"
    bot.reply_to(message, text)

# === ОТКЛИК НА ЗАКАЗ (работник) ===
@bot.message_handler(commands=['take'])
def take_order(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ Используй: /take ID_заказа")
        return
    try:
        order_id = int(parts[1])
    except:
        bot.reply_to(message, "❌ ID должно быть числом.")
        return

    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'worker':
        bot.reply_to(message, "❌ Только работники могут откликаться.")
        return

    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[5] != 'active':
        bot.reply_to(message, "❌ Заказ уже не активен.")
        return

    # Проверяем, не откликался ли уже
    responses = get_responses_for_order(order_id)
    if any(r[0] == user_id for r in responses):
        bot.reply_to(message, "❌ Ты уже откликнулся на этот заказ.")
        return

    add_response(order_id, user_id)
    bot.reply_to(message, "✅ Ты откликнулся на заказ! Заказчик получит уведомление.")

    # Уведомление заказчику
    creator_id = order[1]
    try:
        bot.send_message(creator_id, f"🔔 На твой заказ «{order[2]}» откликнулся работник @{message.from_user.username or 'без username'}.")
    except:
        pass

# === ПРОФИЛЬ ===
@bot.message_handler(commands=['profile'])
def profile(message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if not data:
        bot.reply_to(message, "❌ Ты не зарегистрирован. Напиши /start")
        return
    username, first_name, role, balance, completed = data
    role_map = {"worker": "👷 Работник", "customer": "🏢 Заказчик", "moderator": "🛡️ Модератор"}
    text = (f"👤 Профиль\n\n"
            f"Имя: {first_name}\n"
            f"Username: @{username}\n"
            f"Роль: {role_map.get(role, role)}\n"
            f"💰 Баланс: {balance}₽\n"
            f"✅ Выполнено заказов: {completed}")
    bot.reply_to(message, text)

# === МОДЕРАТОРСКАЯ ПАНЕЛЬ ===
@bot.message_handler(commands=['moderate'])
def moderate(message):
    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'moderator':
        bot.reply_to(message, "❌ Доступно только модератору.")
        return

    orders = get_all_orders()
    if not orders:
        bot.reply_to(message, "📭 Заказов нет.")
        return

    text = "📋 Все заказы:\n\n"
    for o in orders:
        status = o[4]
        executor = o[5] if o[5] else "не назначен"
        text += f"ID: {o[0]}, Название: {o[2]}, Статус: {status}, Исполнитель: {executor}\n"
    text += "\nЧтобы отметить заказ выполненным, используй:\n/complete ID_заказа"
    bot.reply_to(message, text)

@bot.message_handler(commands=['complete'])
def complete_order(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ Используй: /complete ID_заказа")
        return
    try:
        order_id = int(parts[1])
    except:
        bot.reply_to(message, "❌ ID должно быть числом.")
        return

    user_id = message.from_user.id
    role = get_user_role(user_id)
    if role != 'moderator':
        bot.reply_to(message, "❌ Только модератор.")
        return

    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ Заказ не найден.")
        return
    if order[5] != 'active':
        bot.reply_to(message, "❌ Заказ уже завершён или отменён.")
        return

    # Найти исполнителя (берем первого откликнувшегося, если есть)
    responses = get_responses_for_order(order_id)
    if not responses:
        bot.reply_to(message, "❌ На заказ никто не откликнулся.")
        return

    executor_id = responses[0][0]  # первый отклик
    price = order[4]
    commission = 50  # комиссия сервиса
    worker_payment = price - commission

    # Обновляем статус заказа
    update_order_status(order_id, 'completed', executor_id)

    # Начисляем исполнителю
    add_balance(executor_id, worker_payment)
    increment_completed(executor_id)

    # Уведомляем исполнителя
    try:
        bot.send_message(executor_id, f"✅ Заказ «{order[2]}» выполнен! Тебе начислено {worker_payment}₽ (комиссия {commission}₽).")
    except:
        pass

    # Уведомляем заказчика
    try:
        bot.send_message(order[1], f"✅ Заказ «{order[2]}» выполнен. Спасибо за работу!")
    except:
        pass

    bot.reply_to(message, f"✅ Заказ #{order_id} отмечен выполненным. Исполнитель получил {worker_payment}₽.")

    # Проверка порога легализации (5000₽ в день)
    executor_balance = get_user_data(executor_id)[3]
    if executor_balance >= 5000:
        try:
            bot.send_message(executor_id, "⚠️ Внимание! Твой баланс превысил 5000₽. Рекомендуем задуматься об оформлении ИП или самозанятости.")
        except:
            pass

# === HELP ===
@bot.message_handler(commands=['help'])
def send_help(message):
    role = get_user_role(message.from_user.id)
    text = "📖 Доступные команды:\n/start — начать\n/orders — все активные заказы\n/profile — твой профиль\n"
    if role == 'customer':
        text += "/new_order — создать заказ\n"
    if role == 'worker':
        text += "/take ID — откликнуться на заказ\n"
    if role == 'moderator':
        text += "/moderate — панель модератора\n/complete ID — отметить выполненным\n"
    bot.reply_to(message, text)

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
