import time
import random
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup

# ==================== НАСТРОЙКИ ====================
# Если файл называется price-list.csv:
CSV_FILE = "price-list.csv"
KASPI_API_TOKEN = "hmsuburlSShdYJ0cTBBMwZ9cdZApuLhsdHztmPxQsnI="  # 👈 Вставьте ваш токен из кабинета Kaspi
KASPI_API_URL = "https://kaspi.kz/shop/api/v2/offers"

DEFAULT_MIN_PRICE = 800  # Защитный минимум
PAUSE_BETWEEN_BATCHES_MINUTES = 35  # Пауза 35 минут между пачками

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
        print(f"[Ошибка чтения ссылки] {url}: {e}")
        
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
            "price": int(row['Новая_цена'])
        }
        for _, row in batch_df.iterrows()
    ]
    
    payload = {"data": offers_payload}
    print(f"\n[Kaspi API] Отправляем новые цены для {len(offers_payload)} товаров...")
    
    try:
        res = requests.post(KASPI_API_URL, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            print(f"[Успех API] Все цены пачки успешно обновлены в Kaspi!")
            return True
        else:
            print(f"[Ошибка API {res.status_code}]: {res.text}")
    except Exception as err:
        print(f"[Ошибка сети при запросе к API]: {err}")
        
    return False

def process_batch(batch_df, batch_number):
    print(f"\n================ СТАРТ ПАЧКИ №{batch_number} ({len(batch_df)} товаров) ================")
    processed_rows = []
    
    for idx, row in batch_df.iterrows():
        url = str(row['id']).strip()
        sku = str(row['Артикул']).strip()
        title = str(row['Название']).strip() if 'Название' in row else ''
        
        # Получаем личный мин. порог или ставим 800 по умолчанию
        min_price_val = row.get('min_price', DEFAULT_MIN_PRICE)
        min_price = float(min_price_val) if pd.notnull(min_price_val) else DEFAULT_MIN_PRICE
        min_price = max(min_price, DEFAULT_MIN_PRICE)
        
        # Задержка 4–7 секунд между переходами по ссылкам
        time.sleep(random.uniform(4.0, 7.0))
        
        competitor_price = get_competitor_price(url)
        
        if competitor_price:
            target_price = competitor_price - 1
            if target_price < min_price:
                final_price = min_price
                status = f"Сработал мин. порог ({int(min_price)} ₸)"
            else:
                final_price = target_price
                status = f"Снижено на 1 ₸ от конкурента ({competitor_price} ₸)"
            print(f"[{idx+1}/{len(batch_df)}] SKU: {sku} | Конкурент: {competitor_price} ₸ -> Ставим: {int(final_price)} ₸ ({status})")
        else:
            final_price = min_price
            status = "Конкурентов нет / Мин. порог"
            print(f"[{idx+1}/{len(batch_df)}] SKU: {sku} | Конкурентов нет -> Ставим минимум: {int(final_price)} ₸")
            
        processed_rows.append({
            'Артикул': sku,
            'Название': title,
            'Мин_цена': int(min_price),
            'Цена_конкурента': competitor_price if competitor_price else 'Не найден',
            'Новая_цена': int(final_price),
            'Статус': status,
            'Ссылка': url
        })
        
    result_df = pd.DataFrame(processed_rows)
    
    # Отправляем рассчитанную пачку в Kaspi API
    send_to_kaspi_api(result_df)
    
    # Сохраняем отчет в CSV
    report_filename = f"report_batch_{batch_number}.csv"
    result_df.to_csv(report_filename, index=False, encoding='utf-8-sig')
    print(f"[ОТЧЕТ] Результаты пачки №{batch_number} сохранены в файл {report_filename}")

def main():
    # Загружаем CSV файл
    try:
        df = pd.read_csv(CSV_FILE)
    except Exception:
        # Если первая строка была с мета-заголовком:
        df = pd.read_csv(CSV_FILE, header=1)
        
    # Нормализация наименований колонок
    df.columns = [str(c).strip() for c in df.columns]
    
    # 1. Первые 250 товаров
    batch_1 = df.iloc[:250].copy()
    # 2. Оставшиеся товары (125)
    batch_2 = df.iloc[250:].copy()
    
    # Обработка первой пачки
    process_batch(batch_1, batch_number=1)
    
    if len(batch_2) > 0:
        print(f"\n⏳ Пачка №1 завершена. Пауза {PAUSE_BETWEEN_BATCHES_MINUTES} минут перед пачкой №2...")
        time.sleep(PAUSE_BETWEEN_BATCHES_MINUTES * 60)
        
        # Обработка второй пачки
        process_batch(batch_2, batch_number=2)
        
    print("\n🎉 Все товары успешно проверены и обновлены!")

if __name__ == "__main__":
    main()
