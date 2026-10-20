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
ADMIN_CHAT_ID = None  
MIN_PRICE_LIMIT = 800 # Жесткий минимум (800 ₸)

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
# 2. Улучшенный парсинг Kaspi по SKU
# ---------------------------------------------------------
async def fetch_kaspi_top_price(page, sku, model_name):
    try:
        search_query = str(sku).strip() if pd.notna(sku) and str(sku).strip() else str(model_name).strip()
        url = f"https://kaspi.kz/shop/search/?text={search_query}"
        
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(2) # Даем странице прогрузиться
        
        # Пробуем найти цены через разные селекторы Kaspi
        price_selectors = [
            ".item-card__prices-price",
            ".item-card__price-value",
            "a.item-card__mers-link",
            ".merchants-count"
        ]
        
        top_price = None
        seller_count = 1

        # Ищем карточку товара
        cards = await page.query_selector_all(".item-card")
        if cards:
            # Берем первый найденный товар в выдаче
            first_card = cards[0]
            
            # Ищем цену внутри первой карточки
            price_elem = await first_card.query_selector(".item-card__prices-price, [class*='price']")
            if price_elem:
                price_text = await price_elem.inner_text()
                clean_digits = ''.join(filter(str.isdigit, price_text))
                if clean_digits:
                    top_price = int(clean_digits)
            
            # Проверяем количество продавцов, если есть такой элемент
            merchants_elem = await first_card.query_selector("a.item-card__mers-link, [class*='merchants']")
            if merchants_elem:
                m_text = await merchants_elem.inner_text()
                m_digits = ''.join(filter(str.isdigit, m_text))
                if m_digits:
                    seller_count = int(m_digits)
                else:
                    seller_count = 2 # Если ссылка на продавцов есть, значит их больше 1
            else:
                seller_count = 1 # Если плашки нет, возможно продавец один

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
        "🔍 **Запущен улучшенный тест по SKU (100 товаров)!**\nПарсер начал работу..."
    )
    
    kaspi_file = "kaspi-price-list.xlsx"
    if not os.path.exists(kaspi_file):
        await bot.send_message(chat_id, "⚠️ Файл `kaspi-price-list.xlsx` не найден.")
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

            # Тестируем на первых 100 товарах
            test_df = df_kaspi.head(100)

            for idx, row in test_df.iterrows():
                sku = str(row.get('SKU', '')).strip()
                model = str(row.get('model', 'Товар')).strip()
                current_price = float(row.get('price', 0))
                
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
            f"✅ **Тест с улучшенным парсером завершён!**\n\n"
            f"📦 Проверено товаров: `100`\n"
            f"🎯 Обновлено цен под 1-е место: `{updated_count}`\n"
            f"🛡 Без изменений (нет конкурентов / не найдено): `{unchanged_count}`\n"
            f"⚠️ Демпинг ниже {MIN_PRICE_LIMIT} ₸: `{len(problem_items)}`"
        )
        await bot.send_message(chat_id, msg)
        
        file_to_send = FSInputFile(output_file)
        await bot.send_document(chat_id, file_to_send, caption="📄 Обновленный прайс-лист")

        if problem_items:
            report_text = f"🚨 **Товары с демпингом ниже {MIN_PRICE_LIMIT} ₸:**\n\n"
            for item in problem_items[:15]:
                report_text += f"• **{item['sku']}** — {item['model']}\n  └ 📉 Конкурент: `{item['top_price']} ₸`\n"
            await bot.send_message(chat_id, report_text)

    except Exception as e:
        err_msg = f"❌ Ошибка: {str(e)}"
        print(err_msg)
        await bot.send_message(chat_id, err_msg)

# ---------------------------------------------------------
# 4. Команды Telegram
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global ADMIN_CHAT_ID
    ADMIN_CHAT_ID = message.chat.id
    await message.answer("🤖 Бот с улучшенным поиском по SKU готов к работе. Отправьте файл `kaspi-price-list.xlsx`.")

@dp.message(Command("reprice"))
async def cmd_reprice(message: types.Message):
    await run_test_repricing(message.chat.id)

@dp.message()
async def handle_docs(message: types.Message):
    if message.document and message.document.file_name.endswith('.xlsx'):
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, "kaspi-price-list.xlsx")
        await message.answer("💾 Файл получен! Запускаю улучшенный парсинг по SKU...")
        await run_test_repricing(message.chat.id)
    else:
        await message.answer("Пожалуйста, отправьте `.xlsx` файл.")

# ---------------------------------------------------------
# 5. Запуск
# ---------------------------------------------------------
async def main():
    print("--- Улучшенный бот запущен! ---")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
