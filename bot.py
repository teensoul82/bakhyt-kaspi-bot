import os
import time
import random
import threading
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = "8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc"  # 👈 Ваш старый токен телеграм-бота
KASPI_API_TOKEN = "hmsuburlSShdYJ0cTBBMwZ9cdZApuLhsdHztmPxQsnI="      # 👈 Ваш токен от кабинета Kaspi

CSV_FILE = "price-list.csv"
KASPI_API_URL = "https://kaspi.kz/shop/api/v2/offers"
DEFAULT_MIN_PRICE = 800
PAUSE_BETWEEN_BATCHES_MINUTES = 35

# Инициализация телеграм-бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
}

# --- 1. ФУНКЦИИ РЕПРИСЕРА ---
def get_competitor_price(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        price_elements = soup.find_all(class_=re.compile(r'sellers-table__price|sellers-list__price|price'))
        prices = []
        for elem in price_elements:
            clean_price = re.sub(r'[^\d]', '', elem.text.strip())
            if clean_price and clean_price.isdigit():
                prices.append(int(clean_price))
        if prices:
            return min(prices)
    except Exception as e:
        print(f"[Ошибка чтения ссылки] {url}: {e}")
    return None

def send_to_kaspi_api(batch_df):
    headers = {"Content-Type": "application/json", "X-Auth-Token": KASPI_API_TOKEN}
    offers_payload = [{"sku": str(row['Артикул']), "price": int(row['Новая_цена'])} for _, row in batch_df.iterrows()]
    payload = {"data": offers_payload}
    print(f"\n[Kaspi API] Отправляем новые цены для {len(offers_payload)} товаров...")
    try:
        res = requests.post(KASPI_API_URL, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            print(f"[Успех API] Цены пачки успешно обновлены!")
            return True
        else:
            print(f"[Ошибка API {res.status_code}]: {res.text}")
    except Exception as err:
        print(f"[Ошибка сети API]: {err}")
    return False

def process_batch(batch_df, batch_number):
    print(f"\n================ СТАРТ ПАЧКИ №{batch_number} ({len(batch_df)} товаров) ================")
    processed_rows = []
    total_count = len(batch_df)
    
    for idx, row in batch_df.iterrows():
        current_num = len(processed_rows) + 1
        url = str(row['id']).strip()
        sku = str(row['Артикул']).strip()
        title = str(row['Название']).strip() if 'Название' in row else ''
        min_price_val = row.get('min_price', DEFAULT_MIN_PRICE)
        min_price = float(min_price_val) if pd.notnull(min_price_val) else DEFAULT_MIN_PRICE
        min_price = max(min_price, DEFAULT_MIN_PRICE)
        
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
        else:
            final_price = min_price
            status = "Конкурентов нет / Мин. порог"
            
        print(f"[{current_num}/{total_count}] SKU: {sku} | Конкурент: {competitor_price if competitor_price else 'Нет'} -> Итог: {int(final_price)} ₸ ({status})")
            
        processed_rows.append({
            'Артикул': sku, 'Название': title, 'Мин_цена': int(min_price),
            'Цена_конкурента': competitor_price if competitor_price else 'Не найден',
            'Новая_цена': int(final_price), 'Статус': status, 'Ссылка': url
        })
        
    result_df = pd.DataFrame(processed_rows)
    
    # Сохраняем локально отчет в CSV
    report_filename = f"report_batch_{batch_number}.csv"
    result_df.to_csv(report_filename, index=False, encoding='utf-8-sig')
    
    # Отправляем в Kaspi API
    success_api = send_to_kaspi_api(result_df)
    
    # Отправляем отчет в Телеграм
    send_telegram_report(batch_number, result_df, success_api)
    print(f"[ОТЧЕТ] Пачка №{batch_number} обработана и отправлена в Telegram.")

def run_repricer_background():
    """Фоновый цикл реприсинга"""
    print("🤖 Фоновый реприсер запущен!")
    time.sleep(10)  # Даем боту время спокойно стартовать
    while True:
        try:
            if os.path.exists(CSV_FILE):
                try:
                    df = pd.read_csv(CSV_FILE)
                except Exception:
                    df = pd.read_csv(CSV_FILE, header=1)
                df.columns = [str(c).strip() for c in df.columns]
                
                batch_1 = df.iloc[:250].copy()
                batch_2 = df.iloc[250:].copy()
                
                process_batch(batch_1, batch_number=1)
                
                if len(batch_2) > 0:
                    print(f"\n⏳ Пачка №1 завершена. Ожидание {PAUSE_BETWEEN_BATCHES_MINUTES} минут...")
                    time.sleep(PAUSE_BETWEEN_BATCHES_MINUTES * 60)
                    process_batch(batch_2, batch_number=2)
                    
                print("\n🎉 Цикл реприсинга завершен. Следующий запуск через 24 часа.")
            else:
                print(f"[Предупреждение] Файл {CSV_FILE} не найден на сервере.")
        except Exception as e:
            print(f"[Ошибка в фоновом реприсере]: {e}")
            
        # Повторять проверку цен раз в сутки
        time.sleep(86400)


# --- 2. TELEGRAM КОМАНДЫ ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Бот и автоматический реприсер успешно работают на сервере.")


# --- 3. HTTP СЕРВЕР ДЛЯ RENDER (чтобы хостинг не усыплял порт) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Kaspi Repricer Bot is running live!")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"--- HTTP-сервер открыл порт {port} для Render ---")
    server.serve_forever()


# --- 4. ГЛАВНЫЙ СТАРТ ---
if __name__ == "__main__":
    # Запускаем фоновый реприсер в отдельном потоке
    t_repricer = threading.Thread(target=run_repricer_background, daemon=True)
    t_repricer.start()
    
    # Запускаем Телеграм-бота в отдельном потоке
    t_bot = threading.Thread(target=lambda: bot.infinity_polling(none_stop=True, interval=3), daemon=True)
    t_bot.start()
    
    print("--- Улучшенный бот и фоновые задачи запущены! ---")
    
    # HTTP-сервер запускаем в ОСНОВНОМ потоке (чтобы Render сразу видел открытый порт)
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"--- HTTP-сервер открыл порт {port} для Render ---")
    server.serve_forever()

