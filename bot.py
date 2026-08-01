import telebot
import os

TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🤖 Привет! Я бот для подработки в Юрге.\n\nВыбери свою роль:\n1. 👷 Я работник\n2. 🏢 Я заказчик\n3. 🛡️ Я модератор")

print("✅ Бот запущен на Render!")
bot.polling(none_stop=True)
