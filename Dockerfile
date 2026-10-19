FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Копируем список библиотек и устанавливаем Python-пакеты
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем браузер Chromium и ВСЕ его системные зависимости одной командой
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "bot.py"]
