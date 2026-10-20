import os
import time
import random
import requests
import pandas as pd
from bs4 import BeautifulSoup
import telegram

# --- НАСТРОЙКИ (ЗАМЕНИТЕ СВОИ ТОКЕНЫ ЗДЕСЬ) ---
KASPI_TOKEN = "hmsuburlSShdYJ0cTBBMwZ9cdZApuLhsdHztmPxQsnI="
TELEGRAM_TOKEN = "8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc"
TELEGRAM_CHAT_ID = "7663437881"
DEFAULT_MIN_PN = 1000

def get_competitor_price(url):
    try:
        url = str(url).strip()
        if not url.startswith('http'):
            url = "https://" + url if not url.startswith('/') else "https:" + url

        # Извлекаем SKU / ID товара из ссылки для запроса к внутреннему API Kaspi
        import re
        match_id = re.search(r'-([0-9]{6,})/?(\?|$)', url)
        if not match_id:
            return None
        product_id = match_id.group(1)

        # Мобильный API-эндпоинт Kaspi для цен (не блокируется Cloudflare)
        api_url = f"https://kaspi.kz/yml/offer-view/v1/offers/{product_id}?cityId=750000000&limit=10"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": url,
            "X-Requested-With": "XMLHttpRequest"
        }
        
        response = requests.get(api_url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            offers = data.get('offers', [])
            if offers:
                prices = [offer.get('price') for offer in offers if offer.get('price')]
                if prices:
                    return float(min(prices))

        # Запасной вариант через HTML, если API недоступен
        resp_html = requests.get(url, headers=headers, timeout=15)
        if resp_html.status_code == 200:
            soup = BeautifulSoup(resp_html.text, 'html.parser')
            text = soup.get_text()
            matches = re.findall(r'(\d{2,6}\s*)[₸тг]', text)
            prices = []
            for m in matches:
                clean = "".join(filter(str.isdigit, m))
                if clean:
                    val = float(clean)
                    if 100 <= val <= 10000000:
                        prices.append(val)
            if prices:
                return min(prices)

        return None
    except Exception as e:
        return None


def send_to_kaspi_api(df):
    # Здесь ваша функция отправки в API Kaspi
    return True

def send_telegram_report(batch_number, df, success):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        text = f"📦 Пачка №{batch_number} обработана. Статус API: {success}"
        # bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print(f"Ошибка Telegram: {e}")

def process_batch(batch_df, batch_number, total_count):
    processed_rows = []
    
    for idx, row in batch_df.iterrows():
        current_num = len(processed_rows) + 1
        
        # Поиск колонки со ссылкой
        link_col = next((col for col in row.index if 'ссылк' in str(col).lower() or 'url' in str(col).lower()), None)
        if not link_col:
            continue
        url = str(row[link_col]).strip()
        
        # Поиск SKU / Артикула
        sku_col = next((col for col in row.index if 'артикул' in str(col).lower() or 'sku' in str(col).lower()), None)
        sku = str(row[sku_col]).strip() if sku_col and pd.notnull(row[sku_col]) else "N/A"
        
        title = str(row['Название']).strip() if 'Название' in row else "Товар"
        
        min_price_val = row.get('min_price', DEFAULT_MIN_PN)
        min_price = float(min_price_val) if pd.notnull(min_price_val) else DEFAULT_MIN_PN
        
        time.sleep(random.uniform(2.0, 4.0))
        competitor_price = get_competitor_price(url)
        
        if competitor_price:
            target_price = competitor_price - 1
            if target_price < min_price:
                final_price = min_price
                status = f"Сработал мин. порог ({int(min_price)} ₸)"
            else:
                final_price = target_price
                status = f"Снижено на 1 ₸ от конкурента ({competitor_price} ₸)"
            
            print(f"[{current_num}/{total_count}] SKU: {sku} | Конкурент найден: {competitor_price} -> Итог: {int(final_price)} ₸")
            
            processed_rows.append({
                'Артикул': sku, 
                'Название': title, 
                'Мин_цена': int(min_price),
                'Цена_конкурента': competitor_price,
                'Новая_цена': int(final_price), 
                'Статус': status
            })
        else:
            # КОНКУРЕНТОВ НЕТ: цена НЕ меняется, товар пропускаем
            print(f"[{current_num}/{total_count}] SKU: {sku} | Конкурентов нет -> Цена не меняется")
            continue

    if processed_rows:
        result_df = pd.DataFrame(processed_rows)
        report_filename = f"report_batch_{batch_number}.csv"
        result_df.to_csv(report_filename, index=False, encoding='utf-8-sig')
        
        success_api = send_to_kaspi_api(result_df)
        send_telegram_report(batch_number, result_df, success_api)
        print(f"[ОТЧЕТ] Пачка №{batch_number} обработана.")

# Фоновый цикл реприсера
def run_repricer_background():
    time.sleep(10)
    print("🤖 Фоновый реприсер запущен!")
    while True:
        try:
            if os.path.exists("price-list.csv"):
                df = pd.read_csv("price-list.csv")
                batch_size = 250
                total_rows = len(df)
                
                for i in range(0, total_rows, batch_size):
                    batch_df = df.iloc[i:i+batch_size]
                    batch_num = (i // batch_size) + 1
                    process_batch(batch_df, batch_num, total_rows)
                    
            time.sleep(300) # пауза между прогонами прайса
        except Exception as e:
            print(f"Ошибка в фоновом цикле: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_repricer_background()
