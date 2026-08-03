import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import sqlite3
import time
from datetime import datetime
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'
MODERATOR_IDS = [8746212340]
bot = telebot.TeleBot(TOKEN)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        
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
        
        # Таблица orders
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
        
        # Таблица assignments
        c.execute('''CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            user_id INTEGER,
            payout INTEGER
        )''')
        
        conn.commit()
        conn.close()
        logging.info("✅ База данных инициализирована")
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка инициализации БД: {e}")
        return False

init_db()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user(telegram_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logging.error(f"Ошибка get_user: {e}")
        return None

def get_user_by_id(user_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logging.error(f"Ошибка get_user_by_id: {e}")
        return None

def update_user(telegram_id, field, value):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Ошибка update_user: {e}")
        return False

def get_order(order_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logging.error(f"Ошибка get_order: {e}")
        return None

def get_open_orders():
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT id, payout_per_person FROM orders WHERE status = 'open' ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Ошибка get_open_orders: {e}")
        return []

def get_assignments(order_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM assignments WHERE order_id = ?", (order_id,))
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logging.error(f"Ошибка get_assignments: {e}")
        return []

def get_workers():
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM users WHERE role = 'rabotnik' AND on_shift = 1 AND blocked = 0")
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logging.error(f"Ошибка get_workers: {e}")
        return []

def cancel_order(order_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'open'", (order_id,))
        affected = c.rowcount
        conn.commit()
        conn.close()
        return affected > 0
    except Exception as e:
        logging.error(f"Ошибка cancel_order: {e}")
        return False

def add_rating(user_id, delta):
    try:
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
                bot.send_message(row[1], "⚠️ Рейтинг ≤ 5. Вы заблокированы.")
            except:
                pass
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Ошибка add_rating: {e}")
        return False

def rate_customer(customer_id, delta):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE users SET customer_rating = customer_rating + ? WHERE id = ?", (delta, customer_id))
        conn.commit()
        c.execute("SELECT customer_rating, telegram_id FROM users WHERE id = ?", (customer_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logging.error(f"Ошибка rate_customer: {e}")
        return None

def block_user_by_phone(phone):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE users SET blocked = 1 WHERE phone = ?", (phone,))
        affected = c.rowcount
        conn.commit()
        conn.close()
        return affected
    except Exception as e:
        logging.error(f"Ошибка block_user_by_phone: {e}")
        return 0

def get_all_workers():
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT id, name, phone, rating, blocked, on_shift FROM users WHERE role = 'rabotnik' ORDER BY rating DESC")
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Ошибка get_all_workers: {e}")
        return []

def get_all_customers():
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT id, name, phone, customer_rating, blocked FROM users WHERE role = 'zakazchik' ORDER BY customer_rating DESC")
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Ошибка get_all_customers: {e}")
        return []

def get_customer_orders_with_details(zakazchik_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("""SELECT o.id, o.total_sum, o.status, o.payout_per_person, o.people,
                            COUNT(a.user_id) as taken
                     FROM orders o
                     LEFT JOIN assignments a ON o.id = a.order_id
                     WHERE o.zakazchik_id = ?
                     GROUP BY o.id
                     ORDER BY o.created_at DESC""", (zakazchik_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Ошибка get_customer_orders_with_details: {e}")
        return []

def get_worker_orders(user_id):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute('''SELECT o.id, o.status, a.payout, o.zakazchik_name, o.address
                     FROM assignments a 
                     JOIN orders o ON a.order_id = o.id 
                     WHERE a.user_id = ?
                     ORDER BY o.created_at DESC''', (user_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error(f"Ошибка get_worker_orders: {e}")
        return []

# ========== КЛАВИАТУРЫ ==========
def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("👷 Я работник"), KeyboardButton("🏢 Я заказчик"))
    kb.row(KeyboardButton("🛡️ Я модератор"))
    return kb

def worker_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📝 Регистрация"), KeyboardButton("📋 Свободные заказы"))
    kb.row(KeyboardButton("💰 Мои выплаты"), KeyboardButton("👤 Профиль"))
    kb.row(KeyboardButton("⬅️ Назад"))
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
    kb.row(KeyboardButton("🏢 Заказчики"), KeyboardButton("📊 Статистика"))
    kb.row(KeyboardButton("⭐ Оценить"), KeyboardButton("⭐ Оценить заказчика"))
    kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блок"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

def blocked_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📞 Связь с модератором"))
    return kb

def order_inline_kb(order_id, is_customer=False):
    kb = InlineKeyboardMarkup()
    if is_customer:
        kb.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{order_id}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{order_id}"))
    else:
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{order_id}"))
    return kb

def confirm_take_kb(order_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_take_{order_id}"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_take"))
    return kb

# ========== ОБРАБОТЧИКИ CALLBACK ==========
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data
        user_id = call.from_user.id
        user = get_user(user_id)
        
        if not user:
            bot.answer_callback_query(call.id, "❌ Нажмите /start", show_alert=True)
            return
        
        if user[10] == 1:
            bot.answer_callback_query(call.id, "⛔ Вы заблокированы", show_alert=True)
            return
        
        # Взятие заказа
        if data.startswith('take_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            
            if user[6] != 'rabotnik':
                bot.answer_callback_query(call.id, "❌ Только для работников", show_alert=True)
                return
            
            assigned = get_assignments(order_id)
            if user[0] in assigned:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли этот заказ", show_alert=True)
                return
            
            # Показываем подтверждение
            try:
                bot.edit_message_text(
                    f"⚠️ Подтвердите взятие заказа #{order_id}\n"
                    f"💵 Выплата: {order[8]} ₽\n"
                    f"📍 Адрес: {order[3]}\n"
                    f"⏱ Часы: {order[4]} ч.\n"
                    f"👥 Нужно: {order[5]} чел.",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=confirm_take_kb(order_id)
                )
                bot.answer_callback_query(call.id)
            except Exception as e:
                logging.error(f"Ошибка при показе подтверждения: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        
        # Подтверждение взятия
        elif data.startswith('confirm_take_'):
            order_id = int(data.split('_')[2])
            order = get_order(order_id)
            
            if not order or order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
                return
            
            assigned = get_assignments(order_id)
            if user[0] in assigned:
                bot.answer_callback_query(call.id, "❌ Вы уже взяли", show_alert=True)
                return
            
            # Добавляем в assignments
            try:
                conn = sqlite3.connect('rabota.db')
                c = conn.cursor()
                c.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", 
                          (order_id, user[0], order[8]))
                conn.commit()
                conn.close()
                
                # Проверяем комплектность
                new_assigned = get_assignments(order_id)
                if len(new_assigned) >= order[5]:
                    conn = sqlite3.connect('rabota.db')
                    c = conn.cursor()
                    c.execute("UPDATE orders SET status = 'in_progress' WHERE id = ?", (order_id,))
                    conn.commit()
                    conn.close()
                    
                    # Уведомляем заказчика
                    try:
                        bot.send_message(order[1], f"🔔 Заказ #{order_id} укомплектован! Все {order[5]} работников собраны.")
                    except:
                        pass
                    
                    bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} укомплектован!", show_alert=True)
                else:
                    bot.answer_callback_query(call.id, f"✅ Вы взяли заказ #{order_id}! Осталось {order[5] - len(new_assigned)} чел.", show_alert=True)
                
                # Обновляем сообщение
                try:
                    bot.edit_message_text(
                        f"✅ Вы взяли заказ #{order_id}\n"
                        f"💵 Выплата: {order[8]} ₽\n"
                        f"📍 Адрес: {order[3]}\n"
                        f"📊 Статус: {'Укомплектован' if len(new_assigned) >= order[5] else 'Ожидает работников'}",
                        call.message.chat.id,
                        call.message.message_id
                    )
                except:
                    pass
                
                # Уведомляем модератора
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(m, f"👷 {user[2]} взял заказ #{order_id}")
                    except:
                        pass
                
            except Exception as e:
                logging.error(f"Ошибка при подтверждении взятия: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        
        # Отмена заказа
        elif data.startswith('cancel_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[1] != user[0]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            if user[6] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            
            if order[9] != 'open':
                bot.answer_callback_query(call.id, "❌ Можно отменить только открытый заказ", show_alert=True)
                return
            
            if cancel_order(order_id):
                bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} отменён!", show_alert=True)
                try:
                    bot.edit_message_text(
                        f"❌ Заказ #{order_id} отменён\n"
                        f"Заказчик: {order[2]}",
                        call.message.chat.id,
                        call.message.message_id
                    )
                except:
                    pass
                
                # Уведомляем модератора
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(m, f"❌ Заказ #{order_id} отменён заказчиком {user[2]}")
                    except:
                        pass
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка при отмене", show_alert=True)
        
        # Завершение заказа
        elif data.startswith('complete_'):
            order_id = int(data.split('_')[1])
            order = get_order(order_id)
            
            if not order or order[1] != user[0]:
                bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
                return
            
            if user[6] != 'zakazchik':
                bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
                return
            
            if order[9] == 'completed':
                bot.answer_callback_query(call.id, "❌ Уже завершён", show_alert=True)
                return
            
            try:
                conn = sqlite3.connect('rabota.db')
                c = conn.cursor()
                c.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
                conn.commit()
                conn.close()
                
                bot.answer_callback_query(call.id, f"✅ Заказ #{order_id} завершён!", show_alert=True)
                try:
                    bot.edit_message_text(
                        f"✅ Заказ #{order_id} завершён\n"
                        f"💰 Сумма: {order[6]} ₽",
                        call.message.chat.id,
                        call.message.message_id
                    )
                except:
                    pass
                
                # Уведомляем всех работников
                assigned = get_assignments(order_id)
                for worker_id in assigned:
                    try:
                        worker = get_user_by_id(worker_id)
                        if worker:
                            bot.send_message(worker[1], f"✅ Заказ #{order_id} завершён! Ваша выплата: {order[8]} ₽")
                    except:
                        pass
                
                # Уведомляем модератора
                for m in MODERATOR_IDS:
                    try:
                        bot.send_message(m, f"✅ Заказ #{order_id} завершён заказчиком {user[2]}")
                    except:
                        pass
                        
            except Exception as e:
                logging.error(f"Ошибка при завершении заказа: {e}")
                bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        
        # Отмена взятия
        elif data == 'cancel_take':
            try:
                bot.edit_message_text(
                    "❌ Взятие отменено",
                    call.message.chat.id,
                    call.message.message_id
                )
                bot.answer_callback_query(call.id)
            except:
                pass
        
        else:
            bot.answer_callback_query(call.id, "❌ Неизвестная команда", show_alert=True)
            
    except Exception as e:
        logging.error(f"Ошибка в callback: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@bot.message_handler(commands=['start'])
def start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            conn = sqlite3.connect('rabota.db')
            c = conn.cursor()
            c.execute("INSERT INTO users (telegram_id) VALUES (?)", (uid,))
            conn.commit()
            conn.close()
            bot.reply_to(message, "👋 Выберите роль:", reply_markup=main_kb())
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
            return
        
        role = user[6]
        if role == 'rabotnik':
            bot.reply_to(message, "👷 Меню работника:", reply_markup=worker_kb())
        elif role == 'zakazchik':
            bot.reply_to(message, "🏢 Меню заказчика:", reply_markup=customer_kb())
        elif role == 'moderator':
            bot.reply_to(message, "🛡️ Меню модератора:", reply_markup=moderator_kb())
        else:
            bot.reply_to(message, "👋 Выберите роль:", reply_markup=main_kb())
            
    except Exception as e:
        logging.error(f"Ошибка в /start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ВЫБОР РОЛИ
@bot.message_handler(func=lambda m: m.text in ['👷 Я работник', '🏢 Я заказчик', '🛡️ Я модератор'])
def role_choice(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "❌ Нажмите /start")
            return
        
        if user[10] == 1:
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
            
    except Exception as e:
        logging.error(f"Ошибка в role_choice: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# НАЗАД
@bot.message_handler(func=lambda m: m.text == '⬅️ Назад')
def back_to_main(message):
    bot.reply_to(message, "📱 Главное меню:", reply_markup=main_kb())

# РЕГИСТРАЦИЯ
reg_data = {}

@bot.message_handler(func=lambda m: m.text == '📝 Регистрация')
def reg_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user:
            bot.reply_to(message, "❌ Нажмите /start")
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
            return
        
        if user[9] == 1:
            bot.reply_to(message, "✅ Вы уже зарегистрированы.")
            return
        
        role = user[6]
        if role not in ('rabotnik', 'zakazchik'):
            bot.reply_to(message, "❌ Сначала выберите роль через главное меню.")
            return
        
        reg_data[uid] = {}
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("✅ Принимаю"), KeyboardButton("❌ Отмена"))
        bot.send_message(message.chat.id,
            "📜 Условия сервиса:\n\n"
            "1. Сервис - посредник между заказчиками и работниками\n"
            "2. Гарантируем выплату работникам при выполнении заказа\n"
            "3. Гарантируем возврат денег заказчикам при неявке работников\n"
            "4. Сервис не отвечает за качество работы, травмы, кражи\n"
            "5. Оплата наличными отменяет все гарантии\n\n"
            "✅ Принимаете условия?", reply_markup=kb)
            
    except Exception as e:
        logging.error(f"Ошибка в reg_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text in ['✅ Принимаю', '❌ Отмена'])
def handle_agreement(message):
    try:
        uid = message.from_user.id
        
        if message.text == '❌ Отмена':
            bot.reply_to(message, "❌ Регистрация отменена.", reply_markup=main_kb())
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
        msg = bot.reply_to(message, "📞 Введите номер телефона:")
        bot.register_next_step_handler(msg, get_worker_phone, uid)
    except Exception as e:
        logging.error(f"Ошибка в get_worker_name: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_worker_phone(message, uid):
    try:
        reg_data[uid]['phone'] = message.text
        msg = bot.reply_to(message, "💳 Введите реквизиты карты для выплат:")
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
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE users SET name=?, phone=?, bank=?, initials=?, on_shift=1 WHERE telegram_id=?",
                  (reg_data[uid]['name'], reg_data[uid]['phone'], reg_data[uid]['bank'], message.text, uid))
        conn.commit()
        conn.close()
        del reg_data[uid]
        bot.reply_to(message, "✅ Регистрация завершена! Вы на смене.", reply_markup=worker_kb())
    except Exception as e:
        logging.error(f"Ошибка в finish_worker_reg: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def get_customer_name(message, uid):
    try:
        reg_data[uid]['name'] = message.text
        msg = bot.reply_to(message, "📞 Введите номер телефона:")
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
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE users SET name=?, phone=? WHERE telegram_id=?",
                  (reg_data[uid]['name'], reg_data[uid]['phone'], uid))
        conn.commit()
        conn.close()
        del reg_data[uid]
        bot.reply_to(message, "✅ Регистрация завершена! Можете создавать заказы.", reply_markup=customer_kb())
    except Exception as e:
        logging.error(f"Ошибка в finish_customer_reg: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== РАБОТНИК ==========
@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'rabotnik':
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
            return
        
        if user[9] == 0:
            bot.reply_to(message, "❌ Пройдите регистрацию.")
            return
        
        orders = get_open_orders()
        if not orders:
            bot.reply_to(message, "📭 Нет свободных заказов.")
            return
        
        for o in orders:
            order = get_order(o[0])
            if not order:
                continue
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"💵 Выплата: {o[1]} ₽\n"
                f"📍 Адрес: {order[3]}\n"
                f"⏱ Часы: {order[4]} ч.\n"
                f"👥 Нужно: {order[5]} чел.\n"
                f"📊 Статус: {'🟢 Открыт' if order[9] == 'open' else '🟡 В работе'}"
            )
            bot.send_message(
                message.chat.id,
                text,
                reply_markup=order_inline_kb(o[0], is_customer=False)
            )
            
    except Exception as e:
        logging.error(f"Ошибка в free_orders: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

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
        text = "💰 Ваши выплаты:\n\n"
        for o in orders:
            status_map = {'open': '🟢 Ожидает', 'in_progress': '🟡 В работе', 'completed': '✅ Выплачено', 'cancelled': '❌ Отменён'}
            text += f"Заказ #{o[0]}: {o[2]}₽, {status_map.get(o[3], o[3])}\n"
            if o[1] == 'completed':
                total += o[2]
        
        text += f"\n💰 Итого выплачено: {total}₽"
        bot.reply_to(message, text)
        
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
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
            return
        
        role_names = {'rabotnik': '👷 Работник', 'zakazchik': '🏢 Заказчик', 'moderator': '🛡️ Модератор'}
        text = (
            f"👤 Профиль\n\n"
            f"Имя: {user[2] or 'не указано'}\n"
            f"Телефон: {user[3] or 'не указан'}\n"
            f"Роль: {role_names.get(user[6], user[6])}\n"
            f"Рейтинг: {user[7]}\n"
            f"Соглашение: {'✅ Да' if user[9] else '❌ Нет'}\n"
            f"Блокировка: {'🔒 Да' if user[10] else '✅ Нет'}"
        )
        bot.reply_to(message, text)
        
    except Exception as e:
        logging.error(f"Ошибка в profile: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ЗАКАЗЧИК ==========
order_data = {}

@bot.message_handler(func=lambda m: m.text == '📝 Создать заказ')
def create_order_start(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            return
        
        if user[10] == 1:
            bot.reply_to(message, "⛔ Вы заблокированы.", reply_markup=blocked_kb())
            return
        
        if user[9] == 0:
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
        hours = order_data[uid]['hours']
        
        # Расчёт сумм
        total = hours * people * 500
        commission = hours * people * 50
        payout = (total - commission) // people
        
        name = user[2] if user[2] else "Заказчик"
        
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute('''INSERT INTO orders 
                     (zakazchik_id, zakazchik_name, address, hours, people, total_sum, commission, payout_per_person, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user[0], name, order_data[uid]['address'], hours, people, total, commission, payout, datetime.now().isoformat()))
        conn.commit()
        order_id = c.lastrowid
        conn.close()
        
        del order_data[uid]
        
        bot.reply_to(
            message, 
            f"✅ Заказ #{order_id} создан!\n\n"
            f"💰 Сумма к оплате: {total} ₽\n"
            f"💵 Выплата работнику: {payout} ₽/чел\n"
            f"📊 Комиссия сервиса: {commission} ₽\n"
            f"📍 Адрес: {order_data[uid]['address'] if uid in order_data else order[3]}\n"
            f"⏱ Часы: {hours} ч.\n"
            f"👥 Человек: {people}",
            reply_markup=customer_kb()
        )
        
        # Уведомляем всех работников
        workers = get_workers()
        if workers:
            text = (
                f"🔔 Новый заказ!\n"
                f"🆔 #{order_id}\n"
                f"💵 Выплата: {payout} ₽\n"
                f"📍 Адрес: {order_data[uid]['address'] if uid in order_data else order[3]}\n"
                f"⏱ Часы: {hours} ч.\n"
                f"👥 Нужно: {people} чел."
            )
            for w in workers:
                try:
                    bot.send_message(w, text)
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
            return
        
        orders = get_customer_orders_with_details(user[0])
        if not orders:
            bot.reply_to(message, "📭 У вас нет заказов.")
            return
        
        status_map = {
            'open': '🟢 Открыт',
            'in_progress': '🟡 В работе',
            'completed': '✅ Завершён',
            'cancelled': '❌ Отменён'
        }
        
        for o in orders:
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"💰 Сумма: {o[1]} ₽\n"
                f"📊 Статус: {status_map.get(o[2], o[2])}\n"
                f"👥 Работников: {o[4]}/{o[5]}\n"
                f"💵 Выплата: {o[3]} ₽/чел"
            )
            
            if o[2] in ('open', 'in_progress'):
                bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=order_inline_kb(o[0], is_customer=True)
                )
            else:
                bot.send_message(message.chat.id, text)
                
    except Exception as e:
        logging.error(f"Ошибка в my_orders_customer: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⚠️ Пожаловаться')
def complain(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[6] != 'zakazchik':
            return
        
        msg = bot.reply_to(message, "📝 Опишите вашу жалобу:")
        bot.register_next_step_handler(msg, send_complaint, uid)
        
    except Exception as e:
        logging.error(f"Ошибка в complain: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def send_complaint(message, uid):
    try:
        user = get_user(uid)
        text = f"⚠️ ЖАЛОБА\n\nОт: {user[2] or 'без имени'} (ID {uid})\nТелефон: {user[3] or 'не указан'}\n\n{message.text}"
        
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, text)
            except:
                pass
        
        bot.reply_to(message, "✅ Жалоба отправлена модератору.", reply_markup=customer_kb())
        
    except Exception as e:
        logging.error(f"Ошибка в send_complaint: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== МОДЕРАТОР ==========
@bot.message_handler(func=lambda m: m.text == '💰 Выплаты' and m.from_user.id in MODERATOR_IDS)
def mod_payouts(message):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT SUM(payout) FROM assignments")
        total = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM assignments")
        count = c.fetchone()[0] or 0
        conn.close()
        
        bot.reply_to(
            message,
            f"💰 Статистика выплат\n\n"
            f"💵 Всего выплачено: {total} ₽\n"
            f"👥 Количество выплат: {count}"
        )
    except Exception as e:
        logging.error(f"Ошибка в mod_payouts: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🟡 Активные' and m.from_user.id in MODERATOR_IDS)
def mod_active(message):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE status IN ('open', 'in_progress')")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            bot.reply_to(message, "🟡 Нет активных заказов.")
            return
        
        for o in rows:
            text = (
                f"🆔 Заказ #{o[0]}\n"
                f"👤 Заказчик: {o[2]}\n"
                f"📍 Адрес: {o[3]}\n"
                f"⏱ Часы: {o[4]}, 👥 {o[5]} чел.\n"
                f"💰 Сумма: {o[6]} ₽\n"
                f"📊 Комиссия: {o[7]} ₽\n"
                f"💵 Выплата: {o[8]} ₽/чел\n"
                f"📊 Статус: {'🟢 Открыт' if o[9] == 'open' else '🟡 В работе'}"
            )
            bot.send_message(message.chat.id, text)
            
    except Exception as e:
        logging.error(f"Ошибка в mod_active: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '✅ Завершённые' and m.from_user.id in MODERATOR_IDS)
def mod_completed(message):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE status = 'completed'")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            bot.reply_to(message, "✅ Нет завершённых заказов.")
            return
        
        for o in rows:
            text = (
                f"✅ Заказ #{o[0]}\n"
                f"👤 Заказчик: {o[2]}\n"
                f"📍 Адрес: {o[3]}\n"
                f"⏱ Часы: {o[4]}, 👥 {o[5]} чел.\n"
                f"💰 Сумма: {o[6]} ₽\n"
                f"📊 Комиссия: {o[7]} ₽"
            )
            bot.send_message(message.chat.id, text)
            
    except Exception as e:
        logging.error(f"Ошибка в mod_completed: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '👥 Работники' and m.from_user.id in MODERATOR_IDS)
def mod_workers(message):
    try:
        workers = get_all_workers()
        if not workers:
            bot.reply_to(message, "👥 Нет работников.")
            return
        
        text = "👥 Список работников:\n\n"
        for w in workers[:20]:
            status = "🟢" if w[5] else "🔴"
            block = "🔒" if w[4] else "✅"
            text += f"{status} {block} ID {w[0]}: {w[1]}\n"
            text += f"   📞 {w[2]}, ⭐ {w[3]}\n"
        
        if len(workers) > 20:
            text += f"\n... и ещё {len(workers)-20} работников"
        
        bot.reply_to(message, text)
        
    except Exception as e:
        logging.error(f"Ошибка в mod_workers: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🏢 Заказчики' and m.from_user.id in MODERATOR_IDS)
def mod_customers(message):
    try:
        customers = get_all_customers()
        if not customers:
            bot.reply_to(message, "🏢 Нет заказчиков.")
            return
        
        text = "🏢 Список заказчиков:\n\n"
        for c in customers[:20]:
            block = "🔒" if c[4] else "✅"
            text += f"{block} ID {c[0]}: {c[1]}\n"
            text += f"   📞 {c[2]}, ⭐ {c[3]}\n"
        
        if len(customers) > 20:
            text += f"\n... и ещё {len(customers)-20} заказчиков"
        
        bot.reply_to(message, text)
        
    except Exception as e:
        logging.error(f"Ошибка в mod_customers: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '📊 Статистика' and m.from_user.id in MODERATOR_IDS)
def mod_stats(message):
    try:
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
        
        c.execute("SELECT COUNT(*) FROM orders WHERE status = 'open'")
        open_orders = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM orders WHERE status = 'in_progress'")
        in_progress = c.fetchone()[0]
        
        c.execute("SELECT SUM(payout) FROM assignments")
        total_payouts = c.fetchone()[0] or 0
        
        conn.close()
        
        text = (
            f"📊 СТАТИСТИКА\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"👷 Работников: {workers}\n"
            f"🏢 Заказчиков: {customers}\n\n"
            f"📦 Всего заказов: {total_orders}\n"
            f"🟢 Открытых: {open_orders}\n"
            f"🟡 В работе: {in_progress}\n"
            f"✅ Завершённых: {completed}\n\n"
            f"💰 Выплачено: {total_payouts} ₽"
        )
        bot.reply_to(message, text)
        
    except Exception as e:
        logging.error(f"Ошибка в mod_stats: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить' and m.from_user.id in MODERATOR_IDS)
def mod_rate_start(message):
    try:
        msg = bot.reply_to(message, "Введите ID работника (число):")
        bot.register_next_step_handler(msg, mod_rate_get_user)
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_get_user(message):
    try:
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
        msg = bot.reply_to(
            message,
            f"⭐ Оценка для {row[1]}\n"
            f"Текущий рейтинг: {row[2]}\n\n"
            f"Выберите оценку:",
            reply_markup=kb
        )
        bot.register_next_step_handler(msg, mod_rate_apply, row[0])
        
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_get_user: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_apply(message, user_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=moderator_kb())
            return
        
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        add_rating(user_id, delta)
        
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT rating FROM users WHERE id = ?", (user_id,))
        new_rating = c.fetchone()[0]
        conn.close()
        
        bot.reply_to(message, f"✅ Рейтинг обновлён: {new_rating}", reply_markup=moderator_kb())
        
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_apply: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⭐ Оценить заказчика' and m.from_user.id in MODERATOR_IDS)
def mod_rate_customer_start(message):
    try:
        msg = bot.reply_to(message, "Введите ID заказчика (число):")
        bot.register_next_step_handler(msg, mod_rate_customer_get)
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_start: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_customer_get(message):
    try:
        try:
            customer_id = int(message.text)
        except:
            bot.reply_to(message, "❌ Введите число.", reply_markup=moderator_kb())
            return
        
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT id, name, customer_rating FROM users WHERE id = ? AND role = 'zakazchik'", (customer_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            bot.reply_to(message, "❌ Заказчик не найден.", reply_markup=moderator_kb())
            return
        
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
        kb.row(KeyboardButton("⬅️ Назад"))
        msg = bot.reply_to(
            message,
            f"⭐ Оценка для {row[1]}\n"
            f"Текущий рейтинг: {row[2]}\n\n"
            f"Выберите оценку:",
            reply_markup=kb
        )
        bot.register_next_step_handler(msg, mod_rate_customer_apply, row[0])
        
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_get: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def mod_rate_customer_apply(message, customer_id):
    try:
        if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
            bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=moderator_kb())
            return
        
        delta = {'➕ +1': 1, '➖ -1': -1, '⏺ 0': 0}[message.text]
        row = rate_customer(customer_id, delta)
        
        if row:
            bot.reply_to(message, f"✅ Рейтинг заказчика обновлён: {row[0]}", reply_markup=moderator_kb())
        else:
            bot.reply_to(message, "❌ Ошибка", reply_markup=moderator_kb())
            
    except Exception as e:
        logging.error(f"Ошибка в mod_rate_customer_apply: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '⚖️ Арбитраж' and m.from_user.id in MODERATOR_IDS)
def mod_arbitration(message):
    try:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("SELECT id, zakazchik_name, address, status FROM orders WHERE status IN ('in_progress', 'completed')")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            bot.reply_to(message, "⚖️ Нет заказов для арбитража.")
            return
        
        text = "⚖️ ДОСТУПНЫЕ ЗАКАЗЫ\n\n"
        for r in rows:
            text += f"🆔 #{r[0]} | {r[1]} | {r[2]}\nСтатус: {r[3]}\n\n"
        
        text += "📝 Команды:\n/arbitrate ID refund|penalty|ban\n\n"
        text += "refund - вернуть деньги\n"
        text += "penalty - понизить рейтинг заказчика\n"
        text += "ban - заблокировать заказчика"
        
        bot.reply_to(message, text)
        
    except Exception as e:
        logging.error(f"Ошибка в mod_arbitration: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(commands=['arbitrate'])
def arbitrate_command(message):
    try:
        if message.from_user.id not in MODERATOR_IDS:
            return
        
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "❌ Использование: /arbitrate ID refund|penalty|ban")
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
            conn = sqlite3.connect('rabota.db')
            c = conn.cursor()
            c.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Заказ #{order_id} отменён, деньги возвращены заказчику.")
            
        elif action == 'penalty':
            add_rating(order[1], -1)
            bot.reply_to(message, f"✅ Заказчику #{order[1]} снижен рейтинг.")
            
        elif action == 'ban':
            conn = sqlite3.connect('rabota.db')
            c = conn.cursor()
            c.execute("UPDATE users SET blocked = 1 WHERE id = ?", (order[1],))
            conn.commit()
            conn.close()
            bot.reply_to(message, f"✅ Заказчик #{order[1]} заблокирован.")
            
        else:
            bot.reply_to(message, "❌ Неизвестное действие. Доступны: refund, penalty, ban.")
            
    except Exception as e:
        logging.error(f"Ошибка в arbitrate_command: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

@bot.message_handler(func=lambda m: m.text == '🔒 Блок' and m.from_user.id in MODERATOR_IDS)
def mod_block(message):
    try:
        msg = bot.reply_to(message, "📞 Введите номер телефона для блокировки:")
        bot.register_next_step_handler(msg, block_user_by_phone_step)
    except Exception as e:
        logging.error(f"Ошибка в mod_block: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

def block_user_by_phone_step(message):
    try:
        phone = message.text
        affected = block_user_by_phone(phone)
        
        if affected:
            bot.reply_to(message, f"✅ Заблокировано {affected} пользователей.", reply_markup=moderator_kb())
            
            # Уведомляем заблокированных
            conn = sqlite3.connect('rabota.db')
            c = conn.cursor()
            c.execute("SELECT telegram_id FROM users WHERE phone = ? AND blocked = 1", (phone,))
            users = c.fetchall()
            conn.close()
            
            for user in users:
                try:
                    bot.send_message(user[0], "⛔ Вас заблокировал модератор. Нажмите '📞 Связь с модератором' для связи.")
                except:
                    pass
        else:
            bot.reply_to(message, "❌ Пользователь с таким номером не найден.", reply_markup=moderator_kb())
            
    except Exception as e:
        logging.error(f"Ошибка в block_user_by_phone_step: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== ЗАБЛОКИРОВАННЫЙ ==========
@bot.message_handler(func=lambda m: m.text == '📞 Связь с модератором')
def contact_moderator(message):
    try:
        uid = message.from_user.id
        user = get_user(uid)
        
        if not user or user[10] == 0:
            return
        
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, f"📞 Пользователь {uid} ({user[2] or 'без имени'}) просит связи.")
            except:
                pass
        
        bot.reply_to(message, "✅ Запрос отправлен модератору.")
        
    except Exception as e:
        logging.error(f"Ошибка в contact_moderator: {e}")
        bot.reply_to(message, "❌ Ошибка. Попробуйте позже.")

# ========== FALLBACK ==========
@bot.message_handler(func=lambda m: True)
def fallback(message):
    try:
        bot.reply_to(message, "Используйте кнопки меню.", reply_markup=main_kb())
    except:
        pass

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    logging.info("🚀 Бот запущен!")
    print("🤖 Бот Юрга-Подработка запущен!")
    print(f"📊 Модераторы: {MODERATOR_IDS}")
    print("✅ Готов к работе!")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            logging.error(f"⚠️ Ошибка в polling: {e}")
            print(f"⚠️ Ошибка: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
