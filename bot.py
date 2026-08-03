import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
import sqlite3
import time
from datetime import datetime

TOKEN = '8866034224:AAHwRqkDACIpSuK6fypCTJFChnfwii0RgEo'
MODERATOR_IDS = [8746212340]
bot = telebot.TeleBot(TOKEN)

# ========== ОБНОВЛЁННАЯ БД ==========
def init_db():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    # users - добавил customer_rating
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
    # orders - добавил cancelled
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
    # assignments - без изменений
    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        user_id INTEGER,
        payout INTEGER
    )''')
    conn.commit()
    conn.close()
init_db()

# ========== НОВЫЕ ФУНКЦИИ ==========
def cancel_order(oid):
    """Отмена заказа (только если open)"""
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'open'", (oid,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_order_by_id(oid):
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id = ?", (oid,))
    row = c.fetchone()
    conn.close()
    return row

def get_customer_orders_with_details(zakazchik_id):
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

def get_worker_orders_with_details(user_id):
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

def get_all_workers():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, name, phone, rating, blocked, on_shift FROM users WHERE role = 'rabotnik' ORDER BY rating DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_customers():
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, name, phone, customer_rating, blocked FROM users WHERE role = 'zakazchik' ORDER BY customer_rating DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def rate_customer(customer_id, delta):
    """Оценка заказчика (используется модератором)"""
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE users SET customer_rating = customer_rating + ? WHERE id = ?", (delta, customer_id))
    conn.commit()
    c.execute("SELECT customer_rating, telegram_id FROM users WHERE id = ?", (customer_id,))
    row = c.fetchone()
    conn.close()
    return row

# ========== НОВЫЕ КЛАВИАТУРЫ ==========
def order_inline_kb(oid, user_id, is_customer=False):
    """Инлайн-кнопки для заказа"""
    kb = InlineKeyboardMarkup()
    if is_customer:
        kb.add(InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{oid}"))
        kb.add(InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{oid}"))
    else:
        # Для работника
        kb.add(InlineKeyboardButton("📋 Взять заказ", callback_data=f"take_{oid}"))
    kb.add(InlineKeyboardButton("📞 Связаться", callback_data=f"contact_{oid}"))
    return kb

def confirm_take_kb(oid):
    """Подтверждение взятия заказа"""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_take_{oid}"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_take"))
    return kb

# ========== ОБРАБОТЧИКИ CALLBACK ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith('take_'))
def handle_take_order(call):
    uid = call.from_user.id
    oid = int(call.data.split('_')[1])
    user = get_user(uid)
    
    if not user or user[6] != 'rabotnik':
        bot.answer_callback_query(call.id, "❌ Только для работников", show_alert=True)
        return
    
    if user[10] == 1:
        bot.answer_callback_query(call.id, "⛔ Вы заблокированы", show_alert=True)
        return
    
    order = get_order(oid)
    if not order or order[9] != 'open':
        bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
        return
    
    # Проверяем, не взял ли уже
    assigned = get_assignments(oid)
    if user[0] in assigned:
        bot.answer_callback_query(call.id, "❌ Вы уже взяли этот заказ", show_alert=True)
        return
    
    # Показываем подтверждение
    bot.edit_message_text(
        f"⚠️ Подтвердите взятие заказа #{oid}\n"
        f"Выплата: {order[8]} ₽\n"
        f"Адрес: {order[3]}\n"
        f"Работа: {order[4]} ч.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=confirm_take_kb(oid)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_take_'))
def confirm_take(call):
    uid = call.from_user.id
    oid = int(call.data.split('_')[2])
    user = get_user(uid)
    order = get_order(oid)
    
    if not order or order[9] != 'open':
        bot.answer_callback_query(call.id, "❌ Заказ уже не доступен", show_alert=True)
        return
    
    assigned = get_assignments(oid)
    if user[0] in assigned:
        bot.answer_callback_query(call.id, "❌ Вы уже взяли", show_alert=True)
        return
    
    # Добавляем в assignments
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("INSERT INTO assignments (order_id, user_id, payout) VALUES (?, ?, ?)", 
              (oid, user[0], order[8]))
    conn.commit()
    conn.close()
    
    # Проверяем, укомплектован ли заказ
    new_assigned = get_assignments(oid)
    if len(new_assigned) >= order[5]:
        conn = sqlite3.connect('rabota.db')
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'in_progress' WHERE id = ?", (oid,))
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, f"✅ Заказ #{oid} укомплектован!", show_alert=True)
        # Уведомляем заказчика
        try:
            bot.send_message(order[1], f"🔔 Заказ #{oid} укомплектован! Все {order[5]} работников собраны.")
        except:
            pass
    else:
        bot.answer_callback_query(call.id, f"✅ Вы взяли заказ #{oid}! Осталось {order[5] - len(new_assigned)} чел.", show_alert=True)
    
    # Обновляем сообщение
    bot.edit_message_text(
        f"✅ Вы взяли заказ #{oid}\n"
        f"Выплата: {order[8]} ₽\n"
        f"Статус: {'Укомплектован' if len(new_assigned) >= order[5] else 'Ожидает работников'}",
        call.message.chat.id,
        call.message.message_id
    )
    
    # Уведомляем модератора
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"👷 {user[2]} взял заказ #{oid}")
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def handle_cancel_order(call):
    uid = call.from_user.id
    oid = int(call.data.split('_')[1])
    user = get_user(uid)
    order = get_order(oid)
    
    if not user or user[6] != 'zakazchik':
        bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
        return
    
    if not order or order[1] != user[0]:
        bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
        return
    
    if order[9] != 'open':
        bot.answer_callback_query(call.id, "❌ Можно отменить только открытый заказ", show_alert=True)
        return
    
    if cancel_order(oid):
        bot.answer_callback_query(call.id, f"✅ Заказ #{oid} отменён!", show_alert=True)
        bot.edit_message_text(
            f"❌ Заказ #{oid} отменён\n"
            f"Заказчик: {order[2]}",
            call.message.chat.id,
            call.message.message_id
        )
        # Уведомляем модератора
        for m in MODERATOR_IDS:
            try:
                bot.send_message(m, f"❌ Заказ #{oid} отменён заказчиком {user[2]}")
            except:
                pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('complete_'))
def handle_complete_order(call):
    uid = call.from_user.id
    oid = int(call.data.split('_')[1])
    user = get_user(uid)
    order = get_order(oid)
    
    if not user or user[6] != 'zakazchik':
        bot.answer_callback_query(call.id, "❌ Только для заказчиков", show_alert=True)
        return
    
    if not order or order[1] != user[0]:
        bot.answer_callback_query(call.id, "❌ Это не ваш заказ", show_alert=True)
        return
    
    if order[9] == 'completed':
        bot.answer_callback_query(call.id, "❌ Уже завершён", show_alert=True)
        return
    
    # Завершаем заказ
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (oid,))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, f"✅ Заказ #{oid} завершён!", show_alert=True)
    bot.edit_message_text(
        f"✅ Заказ #{oid} завершён\n"
        f"Сумма: {order[6]} ₽",
        call.message.chat.id,
        call.message.message_id
    )
    
    # Уведомляем всех работников, кто взял заказ
    assigned = get_assignments(oid)
    for worker_id in assigned:
        try:
            worker = get_user(worker_id)
            if worker:
                bot.send_message(worker[1], f"✅ Заказ #{oid} завершён! Ваша выплата: {order[8]} ₽")
        except:
            pass
    
    # Уведомляем модератора
    for m in MODERATOR_IDS:
        try:
            bot.send_message(m, f"✅ Заказ #{oid} завершён заказчиком {user[2]}")
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_take')
def cancel_take(call):
    bot.edit_message_text(
        "❌ Взятие отменено",
        call.message.chat.id,
        call.message.message_id
    )

# ========== ОБНОВЛЁННЫЙ МОДЕРАТОР ==========
@bot.message_handler(func=lambda m: m.text == '👥 Работники' and m.from_user.id in MODERATOR_IDS)
def mod_workers_detailed(message):
    workers = get_all_workers()
    if not workers:
        bot.reply_to(message, "👥 Нет работников.")
        return
    
    text = "👥 Список работников:\n\n"
    for w in workers[:20]:  # Ограничим для читаемости
        status = "🟢" if w[5] else "🔴"  # on_shift
        block = "🔒" if w[4] else "✅"
        text += f"{status} {block} ID {w[0]}: {w[1]}\n"
        text += f"   📞 {w[2]}, ⭐ {w[3]}\n"
    if len(workers) > 20:
        text += f"\n... и ещё {len(workers)-20} работников"
    bot.reply_to(message, text)

@bot.message_handler(func=lambda m: m.text == '🏢 Заказчики' and m.from_user.id in MODERATOR_IDS)
def mod_customers(message):
    customers = get_all_customers()
    if not customers:
        bot.reply_to(message, "🏢 Нет заказчиков.")
        return
    
    text = "🏢 Список заказчиков:\n\n"
    for c in customers[:20]:
        block = "🔒" if c[4] else "✅"
        text += f"{block} ID {c[0]}: {c[1]}\n"
        text += f"   📞 {c[2]}, ⭐ {c[3]}\n"
    bot.reply_to(message, text)

# ========== ОБНОВЛЁННЫЙ КОД ДЛЯ РАБОТНИКА ==========
@bot.message_handler(func=lambda m: m.text == '📋 Свободные заказы')
def free_orders_improved(message):
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
            f"📍 {order[3]}\n"
            f"⏱ {order[4]} ч, 👥 {order[5]} чел.\n"
            f"📊 Статус: {'🟢 Открыт' if order[9] == 'open' else '🟡 В работе'}"
        )
        bot.send_message(
            message.chat.id,
            text,
            reply_markup=order_inline_kb(o[0], uid, is_customer=False)
        )

# ========== ОБНОВЛЁННЫЙ КОД ДЛЯ ЗАКАЗЧИКА ==========
@bot.message_handler(func=lambda m: m.text == '📋 Мои заказы')
def my_orders_improved(message):
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
                reply_markup=order_inline_kb(o[0], uid, is_customer=True)
            )
        else:
            bot.send_message(message.chat.id, text)

# ========== ОБНОВЛЁННЫЙ МОДЕРАТОР - ОЦЕНКА ЗАКАЗЧИКОВ ==========
@bot.message_handler(func=lambda m: m.text == '⭐ Оценить заказчика' and m.from_user.id in MODERATOR_IDS)
def mod_rate_customer_start(message):
    msg = bot.reply_to(message, "Введите ID заказчика (число):")
    bot.register_next_step_handler(msg, mod_rate_customer_get)

def mod_rate_customer_get(message):
    try:
        cid = int(message.text)
    except:
        bot.reply_to(message, "❌ Введите число.", reply_markup=moderator_kb())
        return
    
    conn = sqlite3.connect('rabota.db')
    c = conn.cursor()
    c.execute("SELECT id, name, customer_rating FROM users WHERE id = ? AND role = 'zakazchik'", (cid,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        bot.reply_to(message, "❌ Заказчик не найден.", reply_markup=moderator_kb())
        return
    
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("➕ +1"), KeyboardButton("➖ -1"), KeyboardButton("⏺ 0"))
    kb.row(KeyboardButton("⬅️ Назад"))
    msg = bot.reply_to(message, f"Оценка для {row[1]} (рейтинг: {row[2]}):", reply_markup=kb)
    bot.register_next_step_handler(msg, mod_rate_customer_apply, row[0])

def mod_rate_customer_apply(message, customer_id):
    if message.text not in ('➕ +1', '➖ -1', '⏺ 0'):
        bot.reply_to(message, "❌ Нажмите кнопку.", reply_markup=moderator_kb())
        return
    
    delta = {'➕ +1':1, '➖ -1':-1, '⏺ 0':0}[message.text]
    row = rate_customer(customer_id, delta)
    if row:
        bot.reply_to(message, f"✅ Рейтинг заказчика: {row[0]}", reply_markup=moderator_kb())
    else:
        bot.reply_to(message, "❌ Ошибка", reply_markup=moderator_kb())

# ========== ОБНОВЛЁННАЯ КЛАВИАТУРА МОДЕРАТОРА ==========
def moderator_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 Выплаты"), KeyboardButton("🟡 Активные"))
    kb.row(KeyboardButton("✅ Завершённые"), KeyboardButton("👥 Работники"))
    kb.row(KeyboardButton("🏢 Заказчики"), KeyboardButton("📊 Статистика"))
    kb.row(KeyboardButton("⭐ Оценить"), KeyboardButton("⭐ Оценить заказчика"))
    kb.row(KeyboardButton("⚖️ Арбитраж"), KeyboardButton("🔒 Блок"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb

# ========== ЗАПУСК ==========
print("✅ Бот запущен с улучшениями!")
if __name__ == "__main__":
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}. Перезапуск через 5 сек...")
            time.sleep(5)
