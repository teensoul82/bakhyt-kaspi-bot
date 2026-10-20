import os
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from playwright.async_api import async_playwright

# ---------------------------------------------------------
# Настройки
# ---------------------------------------------------------
API_TOKEN = '8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc'
ADMIN_CHAT_ID = None  # Сохранится автоматически при вызове /start
MIN_PRICE_LIMIT = 800 # Минимальный порог цены (в тенге)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

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
# 2. Быстрый парсинг Kaspi по SKU
# ---------------------------------------------------------
async def fetch_kaspi_top_price(page, sku, model_name):
    try:
        search_query = str(sku).strip() if pd.notna(sku) and str(sku).strip() else str(model_name).strip()
        url = f"https://kaspi.kz/shop/search/?text={search_query}"
        
        await page.goto(url, wait_until="domcontentloaded", timeout=12000)
        await asyncio.sleep(1)
        
        offers = await page.query_selector_all(".item-card__prices-price")
        if not offers:
            first_price_elem = await page.query_selector(".item-card__decription .item-card__prices-price")
            if first_price_elem:
                price_text = await first_price_elem.inner_text()
                clean_price = int(''.join(filter(str.isdigit, price_text)))
                return clean_price, 2
            return None, 1

        first_price_text = await offers[0].inner_text()
        top_price = int(''.join(filter(str.isdigit, first_price_text)))
        seller_count = len(offers)
        
        return top_price, seller_count
    except Exception as e:
        print(f"Ошибка парсинга SKU {sku}: {e}")
        return None, 1

# ---------------------------------------------------------
# 3. Тестовый запуск реприсинга (на 100 товаров)
# ---------------------------------------------------------
async def run_test_repricing(chat_id):
    await bot.send_message(
        chat_id, 
        "🧪 **Запущен тест на первых 100 товарах!**\nОткрываю браузер Playwright..."
    )
    
    kaspi_file = "kaspi-price-list.xlsx"
    if not os.path.exists(kaspi_file):
        await bot.send_message(
            chat_id, 
            "⚠️ Файл `kaspi-price-list.xlsx` не найден. Пожалуйста, отправьте его боту."
        )
        return

    try:
        df_kaspi = pd.read_excel(kaspi_file)
        problem_items = []
        updated_count = 0
        unchanged_count = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Ограничиваем тест ровно первыми 100 товарами
            test_df = df_kaspi.head(100)

            for idx, row in test_df.iterrows():
                sku = str(row.get('SKU', '')).strip()
                model = str(row.get('model', 'Товар')).strip()
                
                top_price, seller_count = await fetch_kaspi_top_price(page, sku, model)

                if top_price is None or seller_count <= 1:
                    unchanged_count += 1
                else:
                    new_price = top_price - 1
                    
                    if top_price < MIN_PRICE_LIMIT:
                        df_kaspi.at[idx, 'price'] = MIN_PRICE_LIMIT
                        problem_items.append({
                            'sku': sku,
                            'model': model,
                            'top_price': top_price
                        })
                        updated_count += 1
                    else:
                        target_price = max(new_price, MIN_PRICE_LIMIT)
                        df_kaspi.at[idx, 'price'] = int(target_price)
                        updated_count += 1

            await browser.close()

        output_file = "kaspi-price-list-updated.xlsx"
        df_kaspi.to_excel(output_file, index=False)

        msg = (
            f"✅ **Тест на 100 товарах завершён!**\n\n"
            f"📦 Проверено товаров: `100`\n"
            f"🎯 Изменено цен (-1 ₸): `{updated_count}`\n"
            f"🛡 Без изменений (нет конкурентов): `{unchanged_count}`\n"
            f"⚠️ Демпинг ниже {MIN_PRICE_LIMIT} ₸: `{len(problem_items)}`"
        )
        await bot.send_message(chat_id, msg)
        
        file_to_send = FSInputFile(output_file)
        await bot.send_document(chat_id, file_to_send, caption="📄 Прайс-лист после теста 100 товаров")

        if problem_items:
            report_text = f"🚨 **Товары с демпингом ниже {MIN_PRICE_LIMIT} ₸:**\n\n"
            for item in problem_items[:15]:
                report_text += f"• **{item['sku']}** — {item['model']}\n  └ 📉 Конкурент: `{item['top_price']} ₸`\n"
            await bot.send_message(chat_id, report_text)

    except Exception as e:
        err_msg = f"❌ Ошибка во время теста: {str(e)}"
        print(err_msg)
        await bot.send_message(chat_id, err_msg)

# ---------------------------------------------------------
# 4. Команды Telegram
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = message.chat.id
    await message.answer(
        "🧪 **Тест реприсера на 100 товарах!**\n\n"
        "Отправьте файл `kaspi-price-list.xlsx`, и бот проверит первые 100 позиций за пару минут."
    )

@dp.message(Command("reprice"))
async def cmd_reprice(message: types.Message):
    await run_test_repricing(message.chat.id)

@dp.message()
async def handle_docs(message: types.Message):
    if message.document and message.document.file_name.endswith('.xlsx'):
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, "kaspi-price-list.xlsx")
        await message.answer("💾 Файл получен! Запускаю тест на 100 товаров...")
        await run_test_repricing(message.chat.id)
    else:
        await message.answer("Пожалуйста, отправьте `.xlsx` файл.")

# ---------------------------------------------------------
# 5. Запуск
# ---------------------------------------------------------
async def main():
    print("--- Тестовый бот на 100 товаров запущен! ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
