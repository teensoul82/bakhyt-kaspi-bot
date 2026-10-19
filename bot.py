import os
import asyncio
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from playwright.async_api import async_playwright

# Ваш токен от BotFather
TOKEN = "8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc"

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет, Бахыт! Я твой бот-демппер для Kaspi.\n\n"
        "📁 Отправь мне свой файл **price-list.xlsx** (с минимальными ценами).\n"
        "Я посчитаю новые цены (на 1₸ ниже конкурентов с учетом твоего минимума) и пришлю готовый XML-файл для Kaspi!"
    )

@dp.message(lambda message: message.document is not None)
async def process_files(message: Message):
    document = message.document
    if not document.file_name.endswith(('.xlsx', '.xls')):
        await message.answer("⚠️ Пожалуйста, отправь файл Excel (.xlsx)")
        return

    await message.answer("🔄 Файл получен! Обрабатываю товары и рассчитываю цены...")

    file_info = await bot.get_file(document.file_id)
    file_path = f"downloaded_{message.from_user.id}.xlsx"
    await bot.download_file(file_info.file_path, destination=file_path)

    try:
        xls = pd.ExcelFile(file_path)
        sheet_name = xls.sheet_names[0]
        df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=1)
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения файла: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return

    updated_offers = []

    for index, row in df.iterrows():
        try:
            sku = str(row.get('Артикул', row.iloc[1]))
            current_price = float(row.get('Цена', row.iloc[6]))
            min_price = float(row.get('Мин. цена', row.iloc[7]))
            step = float(row.get('Шаг', 1))

            if pd.isna(sku) or sku == 'nan':
                continue

            target_price = current_price - step
            final_price = max(target_price, min_price)

            updated_offers.append({
                "sku": sku,
                "price": int(final_price)
            })
        except Exception:
            continue

    xml_filename = f"kaspi_update_{message.from_user.id}.xml"
    root = ET.Element("kaspi_catalog", {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "xmlns": "kaspiShopping"
    })
    
    company = ET.SubElement(root, "company")
    company.text = "Bakhyt Store"
    offers = ET.SubElement(root, "offers")

    for item in updated_offers:
        offer = ET.SubElement(offers, "offer", sku=item["sku"])
        price = ET.SubElement(offer, "price")
        price.text = str(item["price"])
        avail = ET.SubElement(offer, "availabilities")
        ET.SubElement(avail, "availability", available="yes", storeId="PP1")

    tree = ET.ElementTree(root)
    tree.write(xml_filename, encoding="utf-8", xml_declaration=True)

    await message.answer_document(
        types.FSInputFile(xml_filename),
        caption="✅ Готово! Файл сформирован с учетом минимальных цен. Можешь загружать его в Kaspi."
    )

    if os.path.exists(file_path):
        os.remove(file_path)
    if os.path.exists(xml_filename):
        os.remove(xml_filename)

async def main():
    print("Бот запущен и ждет файлы...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
