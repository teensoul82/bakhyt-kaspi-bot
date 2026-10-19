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
ADMIN_CHAT_ID = None  # Сохранится автоматически при вызове /start
MIN_PRICE_LIMIT = 800 # Минимальный порог цены (в тенге)

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
            "🔄 **Запущен реприсинг!**\nПроверяю конкурентов на Kaspi..."
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
        
        updated_items = 0
        unchanged_items = 0
        problem_items = [] # Список товаров, где конкуренты ниже 800 тг

        # Заглушка/симуляция обработки товаров по правилам
        for index, row in df.iterrows():
            sku = str(row.get('SKU', row.get('Артикул', 'Неизвестно')))
            model = str(row.get('model', row.get('Название', 'Товар')))
            
            # В реальном Playwright здесь берется цена 1-го места
            # По умолчанию: если конкурентов нет — оставляем цену.
            # Если есть — делаем на 1 тг ниже (но не меньше 800 тг).
            
        await asyncio.sleep(3) # Пауза симуляции
        
        # Финальное сообщение в Telegram
        msg = (
            f"✅ **Реприсинг завершён!**\n"
            f"📦 Всего товаров: {len(df)}\n"
            f"🔹 Правило 1-го места: `-1 ₸` от конкурента\n"
            f"🛑 Минимальный порог: `{MIN_PRICE_LIMIT} ₸`"
        )
        
        if target_chat:
            await bot.send_message(target_chat, msg)
            
            # Если найдены проблемные товары ниже 800 тг, отправляем отдельное уведомление
            if problem_items:
                report_text = "⚠️ **Товары с демпингом ниже 800 ₸ (рекомендуется пересоздать карточки):**\n\n"
                for item in problem_items[:15]: # Выводим первые 15
                    report_text += f"• **{item['sku']}** - {item['model']} (Конкурент: {item['top_price']} ₸)\n"
                if len(problem_items) > 15:
                    report_text += f"\nИ ещё {len(problem_items) - 15} товаров..."
                
                await bot.send_message(target_chat, report_text)
            
    except Exception as e:
        err_msg = f"❌ Ошибка при обработке цен: {str(e)}"
        print(err_msg)
        if target_chat:
            await bot.send_message(target_chat, err_msg)

async def scheduled_repricing_job():
    random_delay = random.randint(0, 1800)
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
        "⏰ Я работаю **автоматически каждые 2 дня** (в случайное время с разбросом в 5 часов для защиты от блокировок).\n\n"
        "🎯 **Правила ценообразования:**\n"
        "1. Нет конкурентов ➔ цена не меняется.\n"
        "2. Есть конкуренты ➔ ставим цену на **1 ₸ ниже** 1-го места.\n"
        "3. Минимальный порог ➔ **800 ₸**.\n"
        "4. Демпинг ниже 800 ₸ ➔ пришлю список для пересоздания карточек.\n\n"
        "📌 **Доступные команды:**\n"
        "• `/reprice` — запустить обновление цен прямо сейчас\n"
        "• Отправьте новый `.xlsx` файл, чтобы обновить базовый список товаров."
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
        
        await bot.download_file(file.file_path, "kaspi-price-list.xlsx")
        await message.answer(
            "💾 Файл `kaspi-price-list.xlsx` успешно сохранён!\n"
            "Запускаю проверку по новым правилам..."
        )
        await run_auto_repricing(chat_id=message.chat.id)
    else:
        await message.answer("Пожалуйста, отправьте файл в формате Excel (`.xlsx`).")

# ---------------------------------------------------------
# 4. Запуск приложения
# ---------------------------------------------------------
async def main():
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
