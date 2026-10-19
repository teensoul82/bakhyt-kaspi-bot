import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiohttp import web

# Токен вашего бота
API_TOKEN = '8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc'

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Микро веб-сервер для проверки портов Render
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Отправь мне Excel-файл с товарами, и я подготовлю XML для Kaspi.")

@dp.message()
async def handle_docs(message: types.Message):
    if message.document:
        await message.answer("Файл получен! Начинаю обработку...")
        # Здесь будет логика обработки файла
    else:
        await message.answer("Пожалуйста, отправьте Excel-файл (.xlsx).")

async def main():
    # Запускаем веб-сервер для Render
    await start_web_server()
    print("Бот запущен и ждет файлы...")
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
