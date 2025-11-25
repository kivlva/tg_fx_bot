# Выбор базового образа
FROM python:3.9-slim

# Установка рабочей директории в контейнере
WORKDIR /app

# Копирование файла с зависимостями и их установка
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копирование всех файлов проекта в рабочую директорию
COPY . /app/

# Запуск бота
CMD ["python", "/app/bot.py"]
