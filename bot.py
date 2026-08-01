import telebot
import os
import time

TOKEN = os.getenv('BOT_TOKEN')
if TOKEN is None:
    print("Ошибка: переменная BOT_TOKEN не задана!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для подработки в Юрге. Система на связи!")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, "Я тебя слышу: " + message.text)

print("Бот запущен и слушает...")

# Убираем вебхук, чтобы избежать конфликта
try:
    bot.remove_webhook()
except:
    pass

# Бесконечный цикл с перезапуском при ошибке
while True:
    try:
        bot.polling(none_stop=True, interval=1, timeout=30)
    except Exception as e:
        print(f"Ошибка: {e}. Перезапуск через 5 секунд...")
        time.sleep(5)
