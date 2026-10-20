import time
import random
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup

# ==================== НАСТРОЙКИ ====================
EXCEL_FILE = "price-list.xlsx"
KASPI_API_TOKEN = "ВАШ_API_ТОКЕН"  # 👈 Вставьте ваш токен из кабинета Kaspi
KASPI_API_URL = "https://kaspi.kz/shop/api/v2/offers"

DEFAULT_MIN_PRICE = 800  # Защитный минимум
PAUSE_BETWEEN_BATCHES_MINUTES = 35  # Пауза 35 минут

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
}

def get_competitor_price(url):
    """Считывает минимальную цену среди конкурентов по прямой ссылке"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        price_elements = soup.find_all(class_=re.compile(r'sellers-table__price|sellers-list__price|price'))
        prices = []
        
        for elem in price_elements:
            text = elem.text.strip()
            clean_price = re.sub(r'[^\d]', '', text)
            if clean_price and clean_price.isdigit():
                prices.append(int(clean_price))
                
        if prices:
            return min(prices)
            
    except Exception as e:
        print(f"[Ошика ссылки] {url}: {e}")
        
    return None

def send_to_kaspi_api(batch_df):
    """Отправка обновленных цен в Kaspi API"""
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": KASPI_API_TOKEN
    }
    
    offers_payload = [
        {
            "sku": str(row['Артикул']),
            "price": int(row['calculated_price'])
        }
        for _, row in batch_df.iterrows()
    ]
    
    payload = {"data": offers_payload}
    print(f"\n[Kaspi API] Отправляем новые цены для {len(offers_payload)} товаров...")
    
    try:
        res = requests.post(KASPI_API_URL, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            print(f"[Успех] Цены обновлены!")
            return True
        else:
            print(f"[Ошибка API {res.status_code}]: {res.text}")
    except Exception as err:
        print(f"[Ошибка сети]: {err}")
        
    return False

def process_batch(batch_df, batch_number):
    print(f"\n=== Запуск пачки №{batch_number} ({len(batch_df)} товаров) ===")
    processed_rows = []
    
    for idx, row in batch_df.iterrows():
        url = str(row['id']).strip()
        sku = str(row['Артикул']).strip()
        min_price = float(row['min_price']) if pd.notnull(row['min_price']) else DEFAULT_MIN_PRICE
        min_price = max(min_price, DEFAULT_MIN_PRICE)
        
        # Задержка 4–7 секунд между ссылками
        time.sleep(random.uniform(4.0, 7.0))
        
        competitor_price = get_competitor_price(url)
        
        if competitor_price:
            target_price = competitor_price - 1
            final_price = max(target_price, min_price)
            print(f"[{idx+1}/{len(batch_df)}] SKU: {sku} | Конкурент: {competitor_price} ₸ -> Ставим: {int(final_price)} ₸")
        else:
            final_price = min_price
            print(f"[{idx+1}/{len(batch_df)}] SKU: {sku} | Конкурентов нет -> Ставим минимум: {int(final_price)} ₸")
            
        row['calculated_price'] = final_price
        processed_rows.append(row)
        
    result_df = pd.DataFrame(processed_rows)
    send_to_kaspi_api(result_df)

def main():
    df = pd.read_excel(EXCEL_FILE, sheet_name=0)
    df.columns = df.iloc[0].values
    df = df.iloc[1:].reset_index(drop=True)
    
    # 1. Первые 250 товаров
    batch_1 = df.iloc[:250].copy()
    # 2. Оставшиеся 125 товаров
    batch_2 = df.iloc[250:].copy()
    
    # Обработка первой пачки
    process_batch(batch_1, batch_number=1)
    
    if len(batch_2) > 0:
        print(f"\n⏳ Пачка №1 готова! Ждем {PAUSE_BETWEEN_BATCHES_MINUTES} минут перед второй пачкой...")
        time.sleep(PAUSE_BETWEEN_BATCHES_MINUTES * 60)
        
        # Обработка второй пачки
        process_batch(batch_2, batch_number=2)
        
    print("\n🎉 Готово! Все 375 товаров проверены и обновлены.")

if __name__ == "__main__":
    main()
