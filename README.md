# Telegram FX Bot

Telegram-бот для конвертации валют. Текущая реализация использует aiogram, поддерживает 31 валюту, включая VND, и выбор до пяти валют через региональные группы. В облаке персональный выбор хранится в YDB.

## Локальный запуск

Требуется Python 3.11+. На ВМ используется Docker с Python 3.12.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Передайте BOT_TOKEN через окружение, не сохраняйте значение в файлы и команды. Затем:

```sh
RUN_MODE=polling .venv/bin/python -m cur_converter_bot
```

Без YDB локальный запуск использует MemoryStore: выбор теряется после завершения процесса. С YDB_ENDPOINT и YDB_DATABASE используются постоянные настройки YDB и credentials сервисного аккаунта из metadata ВМ. Одновременно должен работать только один polling-процесс для одного токена.

## Запуск и обновление на ВМ

Текущая схема: ВМ Ubuntu + Docker + YDB + Lockbox. Привяжите к ВМ сервисный аккаунт с доступом к YDB и роли lockbox.payloadViewer для нужного секрета. Lockbox должен содержать текстовый ключ BOT_TOKEN. Значение читается в память при запуске контейнера.

```sh
sudo sh deploy/update_vm.sh
```

Скрипт собирает новый образ, проверяет доступ к Telegram до остановки действующего бота, сохраняет прежний контейнер для отката и запускает новый. После запуска проверяйте логи, /start, конвертацию и сохранение валют после перезапуска. Команды отката выводятся скриптом. Автоматического отката после ошибки приложения пока нет.

Скрипт содержит значения ресурсов текущего развёртывания; для другой установки задайте LOCKBOX_SECRET_ID, YDB_ENDPOINT и YDB_DATABASE. Это идентификаторы, не секретные значения. При запуске через sudo передавайте эти переменные явно через env.

DNS и резервные маршруты Telegram описаны в [DOCS/TELEGRAM_NETWORK.md](DOCS/TELEGRAM_NETWORK.md). TELEGRAM_FALLBACK_IPS — проверенные для вашей сети резервные IP, их доступность не гарантируется постоянно. Обновление включается TELEGRAM_RESILIENT_DNS=1 и не требует --add-host.

## Проверка

```sh
.venv/bin/python -m pytest -q
```

Тесты используют локальный HTTP-сервер; отдельного бота и подключения к облачной YDB не требуют.

## Структура

- src/cur_converter_bot/catalog.py — коды, названия, флаги и группы валют.
- src/cur_converter_bot/flow.py — сценарии диалога.
- src/cur_converter_bot/storage.py — MemoryStore и YDB.
- src/cur_converter_bot/rates.py — получение и кеширование курсов.
- src/cur_converter_bot/telegram_network.py — выбор доступных HTTPS-маршрутов Telegram.
- deploy/vm_entrypoint.py — загрузка токена из Lockbox.
- deploy/update_vm.sh — обновление контейнера и подготовка отката.

Исторический вариант Cloud Functions оставлен в deploy/setup.sh и function.py; он не используется в текущей выкладке.
