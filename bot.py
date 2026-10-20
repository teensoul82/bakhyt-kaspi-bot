import os
import time
import random
import threading
import pandas as pd
import requests
from bs4 import BeautifulSoup
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot

# ================= НАСТРОЙКИ =================
TELEGRAM_BOT_TOKEN = "8696192191:AAGQnMUKuKMTVjyESIar6G9_QzSI5Mws1Pc"  # <--- Вставьте сюда токен от @BotFather
KASPI_TOKEN = "hmsuburlSShdYJ0cTBBMwZ9cdZApuLhsdHztmPxQsnI="          # <--- Вставьте сюда ваш X-Auth-Token от Kaspi
TELEGRAM_CHAT_ID = ""                 # Оставьте пустым, бот пришлет ID по команде /start
DEFAULT_MIN_PRICE = 1000
# =============================================

# Инициализация бота
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Обработка команды /start для получения Chat ID
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    bot.reply_to(message, f"Привет! Ваш Chat ID: {chat_id}\nСкопируйте это число и вставьте в код в переменную TELEGRAM_CHAT_ID.")

# Функция парсинга цен конкурентов с Kaspi
def get_competitor_price(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://kaspi.kz/"
        }
        response = requests.get(url, headers=headers, timeout=15)
        
        # Если статус не 200 или страница заблокирована
        if response.status_code != 200:
            print(f"[Блокировка/Ошибка] Код ответа Kaspi для {url}: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        prices = []
        
        # Универсальный поиск цен со знаком тенге или в блоках цен
        import re
        text = soup.get_text()
        matches = re.findall(r'(\d{2,6}\s*)[₸тг]', text)
        for m in matches:
            clean = "".join(filter(str.isdigit, m))
            if clean:
                val = float(clean)
                if 100 <= val <= 10000000: # Разумный диапазон цен
                    prices.append(val)
                    
        if prices:
            found_price = min(prices)
            print( найдена цена: {found_price})
            return found_price
            
        return None
    except Exception as e:
        print(f"[Ошибка парсинга {url}]: {e}")
        return None


# Отправка обновленных цен в Kaspi API
def send_to_kaspi_api(result_df):
    url = "https://kaspi.kz/shop/api/v2/products"
    headers = {
        "X-Auth-Token": KASPI_TOKEN,
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/vnd.api+json"
    }
    
    success_all = True
    for _, row in result_df.iterrows():
        sku = row['Артикул']
        new_price = row['Новая_цена']
        
        payload = {
            "data": {
                "type": "products",
                "attributes": {
                    "sku": sku,
                    "price": new_price
                }
            }
        }
        
        try:
            response = requests.put(url, json=payload, headers=headers, timeout=10)
            if response.status_code not in [200, 201, 204]:
                print(f"[Kaspi API Ошибка] SKU {sku}: статус {response.status_code}, ответ: {response.text}")
                success_all = False
        except Exception as e:
            print(f"[Kaspi API Сбой связи] SKU {sku}: {e}")
            success_all = False
            
    return success_all

# Отправка отчета в Telegram
def send_telegram_report(batch_number, result_df, success_api):
    if not TELEGRAM_CHAT_ID:
        return 
    try:
        updated_count = len(result_df[result_df['Статус'].str.contains('Снижено', na=False)])
        text = f"📊 **Отчет по пачке №{batch_number}**\n\n" \
               f"📦 Обработано товаров: {len(result_df)}\n" \
               f"📉 Изменено цен: {updated_count}\n" \
               f"🌐 Отправка в Kaspi API: {'Успешно ✅' if success_api else 'Ошибка ❌'}"
        
        bot.send_message(TELEGRAM_CHAT_ID, text, parse_mode="Markdown")
        
        report_filename = f"report_batch_{batch_number}.csv"
        with open(report_filename, 'rb') as f:
            bot.send_document(TELEGRAM_CHAT_ID, f)
    except Exception as e:
        print(f"[Ошибка отправки в Telegram]: {e}")

# Логика обработки пачки товаров
def process_batch(batch_df, batch_number):
    print(f"\n================ СТАРТ ПАЧКИ №{batch_number} ({len(batch_df)} товаров) ================")
    processed_rows = []
    total_count = len(batch_df)
    
    for idx, row in batch_df.iterrows():
        current_num = len(processed_rows) + 1
        
        # Всеядный поиск колонки со ссылкой
        link_col = next((col for col in row.index if str(col).strip().lower() in ['id', 'ссылка', 'url', 'link']), row.index[0])
        url = str(row[link_col]).strip()
        
                # Универсальный поиск колонки с артикулом/SKU
        sku_col = next((col for col in row.index if str(col).strip().lower() in ['артикул', 'sku', 'код', 'code']), None)
        sku = str(row[sku_col]).strip() if sku_col and pd.notnull(row[sku_col]) else 'N/A'

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
                for i in range(0, len(df), batch_size):
                    batch_df = df.iloc[i:i+batch_size]
                    batch_num = (i // batch_size) + 1
                    process_batch(batch_df, batch_num)
            else:
                print("Файл price-list.csv не найден!")
            
            time.sleep(10800) # Повтор каждые 3 часа
        except Exception as e:
            print(f"[Ошибка в фоновом реприсере]: {e}")
            time.sleep(60)

# HTTP-сервер для Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Kaspi Repricer Bot is running live!")
    def log_message(self, format, *args):
        return

# --- ГЛАВНЫЙ СТАРТ ---
if __name__ == "__main__":
    t_repricer = threading.Thread(target=run_repricer_background, daemon=True)
    t_repricer.start()
    
    t_bot = threading.Thread(target=lambda: bot.infinity_polling(none_stop=True, interval=3, skip_pending=True), daemon=True)
    t_bot.start()
    
    print("--- Улучшенный бот и фоновые задачи запущены! ---")
    
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"--- HTTP-сервер открыл порт {port} для Render ---")
    server.serve_forever()
