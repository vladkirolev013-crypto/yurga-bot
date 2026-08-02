import telebot
import sqlite3
import time
from datetime import datetime
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# ===== КОНФИГ =====
TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'
MODERATOR_IDS = [8746212340]  # твой ID

bot = telebot.TeleBot(TOKEN)
user_state = {}

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

def get_user_by_id(user_id):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def update_field(telegram_id, field, value):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
    conn.commit()
    conn.close()

def update_field_by_id(user_id, field, value):
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

def create_order(zakazchik_id, zakazchik_name, address, hours, people, total, commission, payout):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute('''INSERT INTO orders 
                 (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (zakazchik_id, zakazchik_name, address, hours, people, total, commission, payout, datetime.now().isoformat()))
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

def get_assignments(order_id):
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
    c.execute('''SELECT o.id, o.address, o.hours, o.people, o.total_sum, o.status, a.payout 
                 FROM assignments a JOIN orders o ON a.order_id = o.id 
                 WHERE a.user_id = ?''', (user_id,))
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

def block_by_name(name):
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
    kb.row(KeyboardButton("📝 Создать заказ"), KeyboardButton("📋 Мои зака
