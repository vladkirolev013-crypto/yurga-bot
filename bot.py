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
        registered_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        title TEXT,
        description TEXT,
        price INTEGER,
        status TEXT,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# === КОМАНДА /start ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "Нет username"
    first_name = message.from_user.first_name or ""

    # Сохраняем пользователя, если его нет
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, username, first_name, registered_at) VALUES (?, ?, ?, ?)",
                  (user_id, username, first_name, datetime.now().isoformat()))
        conn.commit()
    conn.close()

    # Кнопки выбора роли
    markup = InlineKeyboardMarkup(row_width=2)
    btn1 = InlineKeyboardButton("👷 Работник", callback_data="role_worker")
    btn2 = InlineKeyboardButton("🏢 Заказчик", callback_data="role_customer")
    btn3 = InlineKeyboardButton("🛡️ Модератор", callback_data="role_moderator")
    markup.add(btn1, btn2, btn3)

    bot.send_message(
        message.chat.id,
        f"🤖 Привет, {first_name}!\n\n"
        "Я бот для подработки в Юрге.\n"
        "Выбери свою роль, чтобы начать:",
        reply_markup=markup
    )

# === ОБРАБОТКА ВЫБОРА РОЛИ ===
@bot.callback_query_handler(func=lambda call: call.data.startswith('role_'))
def role_callback(call):
    user_id = call.from_user.id
    role = call.data.split('_')[1]
    roles_map = {
        "worker": "👷 Работник",
        "customer": "🏢 Заказчик",
        "moderator": "🛡️ Модератор"
    }

    # Обновляем роль в БД
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, f"✅ Ты выбрал роль: {roles_map[role]}")
    bot.edit_message_text(
        f"✅ Отлично! Ты теперь {roles_map[role]}.\n\n"
        "Функции для этой роли скоро появятся.\n"
        "Пока ты можешь использовать /help для справки.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

# === КОМАНДА /help ===
@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message,
        "📖 Доступные команды:\n"
        "/start — начать работу\n"
        "/help — эта справка\n\n"
        "Скоро добавятся:\n"
        "— Создание заказов\n"
        "— Просмотр заказов\n"
        "— Рейтинг и отзывы"
    )

# === ЗАПУСК БОТА ===
print("✅ Бот запущен и слушает...")

# Убираем вебхук, если был
try:
    bot.remove_webhook()
except:
    pass

# Бесконечный цикл с перезапуском
while True:
    try:
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
        import time
        time.sleep(5)
