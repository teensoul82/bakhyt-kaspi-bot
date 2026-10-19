import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# Токен вашего бота
API_TOKEN = '8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc'

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# 1. Простейший веб-сервер для удовлетворения требований Render по привязке порта (Port Binding)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot status: OK")
    
    def log_message(self, format, *args):
        # Отключаем логирование HTTP-запросов, чтобы не засорять консоль Render
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"--- HTTP-сервер открыл порт {port} для Render ---")
    server.serve_forever()

# Запускаем HTTP-сервер в фоновом потоке в момент импорта файла
threading.Thread(target=start_health_server, daemon=True).start()


# 2. Обработчики команд и сообщений Telegram
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Отправь мне Excel-файл с товарами, и я подготовлю XML для Kaspi.")

@dp.message()
async def handle_docs(message: types.Message):
    if message.document:
        await message.answer("Файл получен! Начинаю обработку...")
    else:
        await message.answer("Пожалуйста, отправьте Excel-файл (.xlsx).")

async def main():
    print("--- Telegram-бот запущен и ожидает файлы... ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
