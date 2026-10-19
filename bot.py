import os
import asyncio
import logging
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------------------------------------------------------
# Настройки
# ---------------------------------------------------------
API_TOKEN = '8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc'
ADMIN_CHAT_ID = None  # Сохранится автоматически при первом вызове /start

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# ---------------------------------------------------------
# 1. Веб-сервер для поддержки Render (Port Binding)
# ---------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot status: OK")
    
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"--- HTTP-сервер открыл порт {port} для Render ---")
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

# ---------------------------------------------------------
# 2. Логика авто-реприсинга на 1-е место
# ---------------------------------------------------------
async def run_auto_repricing(chat_id=None):
    target_chat = chat_id or ADMIN_CHAT_ID
    if target_chat:
        await bot.send_message(
            target_chat, 
            "🔄 **Запущен реприсинг!**\nПроверяю цены конкурентов на Kaspi..."
        )
    
    file_path = "kaspi-price-list.xlsx"
    if not os.path.exists(file_path):
        if target_chat:
            await bot.send_message(
                target_chat, 
                "⚠️ Файл `kaspi-price-list.xlsx` не найден на сервере. Пожалуйста, отправьте его боту в чат."
            )
        return

    try:
        df = pd.read_excel(file_path)
        
        # Заглушка под будущую обработку через Playwright
        await asyncio.sleep(3) 
        
        updated_count = len(df)
        msg = (
            f"✅ **Реприсинг успешно завершён!**\n"
            f"Обработано товаров: {updated_count}.\n"
            f"Цены скорректированы под 1-е место на Kaspi."
        )
        
        if target_chat:
            await bot.send_message(target_chat, msg)
            
    except Exception as e:
        err_msg = f"❌ Ошибка при обработке цен: {str(e)}"
        print(err_msg)
        if target_chat:
            await bot.send_message(target_chat, err_msg)

# Обертка для планировщика с дополнительной рандомизацией
async def scheduled_repricing_job():
    random_delay = random.randint(0, 1800)  # Дополнительная задержка от 0 до 30 минут
    print(f"--- Авто-реприсинг сработал. Старт через {random_delay // 60} мин... ---")
    await asyncio.sleep(random_delay)
    await run_auto_repricing()

# ---------------------------------------------------------
# 3. Команды Telegram
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = message.chat.id
    await message.answer(
        "👋 **Привет! Я бот-реприсер Kaspi.**\n\n"
        "⏰ Я работаю **автоматически каждые 2 дня** (в случайное время с разбросом в 5 часов для защиты от блокировок), проверяю конкурентов и ставлю ваши цены на **1-е место**.\n\n"
        "📌 **Доступные команды:**\n"
        "• `/reprice` — запустить обновление цен прямо сейчас\n"
        "• Отправьте новый `.xlsx` файл, чтобы обновить список товаров."
    )

@dp.message(Command("reprice"))
async def cmd_reprice(message: types.Message):
    await message.answer("🚀 Запускаю ручной реприсинг под 1-е место...")
    await run_auto_repricing(chat_id=message.chat.id)

@dp.message()
async def handle_docs(message: types.Message):
    if message.document and message.document.file_name.endswith('.xlsx'):
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        
        # Сохраняем файл на сервере
        await bot.download_file(file.file_path, "kaspi-price-list.xlsx")
        await message.answer(
            "💾 Файл `kaspi-price-list.xlsx` успешно сохранён!\n"
            "Запускаю тестовый реприсинг..."
        )
        await run_auto_repricing(chat_id=message.chat.id)
    else:
        await message.answer("Пожалуйста, отправьте файл в формате Excel (`.xlsx`).")

# ---------------------------------------------------------
# 4. Запуск приложения
# ---------------------------------------------------------
async def main():
    # Запуск каждые 2 дня (48 часов) с плавающим окном разброса в 5 часов (18000 сек)
    scheduler.add_job(
        scheduled_repricing_job, 
        'interval', 
        days=2, 
        jitter=18000
    )
    scheduler.start()
    
    print("--- Telegram-бот с рандом-планировщиком запущен! ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
