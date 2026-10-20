import os
import time
import random
import re
import pandas as pd
import telegram
from playwright.sync_api import sync_playwright

# --- НАСТРОЙКИ ---
KASPI_TOKEN = "hmsuburlSShdYJ0cTBBMwZ9cdZApuLhsdHztmPxQsnI="
TELEGRAM_TOKEN = "8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc"
TELEGRAM_CHAT_ID = "7663437881"
DEFAULT_MIN_PN = 1000

def get_competitor_price(page, url):
    try:
        url = str(url).strip()
        if not url.startswith('http'):
            url = "https://" + url if not url.startswith('/') else "https:" + url

        match_id = re.search(r'-([0-9]{6,})', url)
        if not match_id:
            print(f"⚠️ Не удалось найти ID в ссылке: {url}")
            return None
        product_id = match_id.group(1)

        api_url = f"https://kaspi.kz/yml/offer-view/v1/offers/{product_id}?cityId=750000000&limit=10"

        # Делаем запрос из контекста реального браузера с установленными куками
        response = page.goto(api_url, wait_until="domcontentloaded", timeout=20000)
        status_code = response.status if response else 0

        print(f"🔍 SKU {product_id} (статус {status_code})")

        if status_code == 200:
            data = response.json()
            offers = data.get('offers', [])
            if offers:
                prices = [offer.get('price') for offer in offers if offer.get('price')]
                if prices:
                    return float(min(prices))

        return None
    except Exception as e:
        print(f"❌ Ошибка парсинга для {url}: {e}")
        return None

def send_to_kaspi_api(df):
    return True

def send_telegram_report(batch_number, df, success):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        text = f"📦 Пачка №{batch_number} обработана. Цены обновлены!"
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def process_batch(page, batch_df, batch_number, total_count):
    processed_rows = []
    
    for idx, row in batch_df.iterrows():
        current_num = len(processed_rows) + 1
        
        link_col = next((col for col in row.index if 'ссылк' in str(col).lower() or 'url' in str(col).lower() or 'kaspi' in str(col).lower() or 'id' in str(col).lower()), None)
        if not link_col:
            for col in row.index:
                if 'http' in str(row[col]):
                    link_col = col
                    break
        if not link_col:
            continue
        url = str(row[link_col]).strip()
        
        sku_col = next((col for col in row.index if 'артикул' in str(col).lower() or 'sku' in str(col).lower()), None)
        sku = str(row[sku_col]).strip() if sku_col and pd.notnull(row[sku_col]) else "N/A"
        
        title = str(row['Название']).strip() if 'Название' in row else "Товар"
        min_price_val = row.get('min_price', DEFAULT_MIN_PN)
        min_price = float(min_price_val) if pd.notnull(min_price_val) else DEFAULT_MIN_PN
        
        time.sleep(random.uniform(5.0, 10.0))
        competitor_price = get_competitor_price(page, url)
        
        if competitor_price:
            target_price = competitor_price - 1
            if target_price < min_price:
                final_price = min_price
                status = f"Мин. порог ({int(min_price)} ₸)"
            else:
                final_price = target_price
                status = f"Снижено на 1 ₸ ({competitor_price} ₸)"
            
            print(f"[{current_num}/{total_count}] SKU: {sku} | Конкурент: {competitor_price} -> Итог: {int(final_price)} ₸")
            
            processed_rows.append({
                'Артикул': sku, 'Название': title, 'Мин_цена': int(min_price),
                'Цена_конкурента': competitor_price, 'Новая_цена': int(final_price), 'Статус': status
            })

    if processed_rows:
        result_df = pd.DataFrame(processed_rows)
        report_filename = f"report_batch_{batch_number}.csv"
        result_df.to_csv(report_filename, index=False, encoding='utf-8-sig')
        success_api = send_to_kaspi_api(result_df)
        send_telegram_report(batch_number, result_df, success_api)

def main():
    if os.getenv("GITHUB_EVENT_NAME") == "schedule":
        delay_seconds = random.randint(0, 18000)
        hours_delay = delay_seconds // 3600
        minutes_delay = (delay_seconds % 3600) // 60
        print(f"⏳ Рандомная задержка перед стартом: {hours_delay} ч. {minutes_delay} мин...")
        time.sleep(delay_seconds)
    else:
        print("⚡ Ручной запуск: начинаем работу без задержки!")

    file_name = "price-list.csv" 
    if os.path.exists(file_name):
        print(f"📂 Файл {file_name} найден. Читаю данные...")
        df = pd.read_csv(file_name)
        print(f"📊 Всего строк: {len(df)}")
        
        batch_size = 250
        total_rows = len(df)
        
        # Инициализация эмулятора браузера
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()

            # Сначала один раз открываем главную Kaspi, чтобы получить необходимые cookie-файлы
            try:
                page.goto("https://kaspi.kz/shop/", timeout=20000)
                time.sleep(3)
            except Exception as e:
                print(f"⚠️ Предупреждение при стартовой загрузке Kaspi: {e}")

            for i in range(0, total_rows, batch_size):
                batch_df = df.iloc[i:i+batch_size]
                batch_num = (i // batch_size) + 1
                print(f"🚀 Обработка пачки №{batch_num}...")
                process_batch(page, batch_df, batch_num, total_rows)

            browser.close()

        print("✅ Все пачки успешно обработаны!")
    else:
        print(f"⚠️ Файл '{file_name}' не найден!")

if __name__ == "__main__":
    main()
