# Исторический вариант Cloud Functions

Текущая выкладка: ВМ + Docker + YDB + Lockbox. См. README.md.

# Выкладка существующего бота: Cloud Functions + YDB

Для сборки нужен Python 3.11+; Docker, Colima и Container Registry не нужны.
Команды выполнять в терминале, где задан BOT_TOKEN; значение в чат и файлы не передавать.
Каталог по умолчанию берётся из `yc config get folder-id`. Проверен каталог yawork: b1g9vfarnf66183rqfb3.

## Выкладка

```bash
cd /Users/kivlva/_WORKDUMMY/_AI/TG/cur_converter_bot
export YC_FOLDER_ID=b1g9vfarnf66183rqfb3
sh deploy/setup.sh
```

Если BOT_TOKEN не задан, в zsh перед запуском:

```bash
read -rs 'BOT_TOKEN?Токен BotFather: '
export BOT_TOKEN
```

Скрипт упаковывает код и requirements.txt в ZIP, создаёт YDB, Lockbox, сервисный аккаунт и Cloud Function. YC устанавливает зависимости при создании версии python312 с точкой входа index.handler. Функция обрабатывает Update и вызывает Bot API; polling и HTTP-сервер в ней не запускаются. Локальный polling работает прежней командой RUN_MODE=polling.

Публичный доступ не включается. Для вызова функции используется сервисный аккаунт триггера с functions.functionInvoker. Токен Lockbox передаётся через stdin и подключается к версии как BOT_TOKEN. Предоплаченная производительность YDB выключена; лимит хранения новой базы 1 GB. Ресурсы тарифицируются по условиям YC.

Скрипт не создаёт Telegram-триггер и не переключает бота автоматически. Установленный yc не поддерживает создание этого триггера; этот шаг скрипт не выполняет.

## Telegram-триггер

Это исторический альтернативный вариант, не текущая выкладка. В использованной консоли YC Telegram отсутствовал среди типов триггеров. Не выбирайте Message Queue вместо Telegram. Создание Telegram-триггера требует отдельного поддерживаемого API или Terraform; подготовленного скрипта этого шага здесь нет. Terraform может сохранять bot token в state. Не создавайте триггер одновременно с работающим polling.

## Проверка и последующие обновления

- /start, /set_currencies, выбор VND и конвертация.
- У разных пользователей независимые настройки.
- Повторный запуск setup.sh создаёт новую версию функции с той же YDB; выбранные валюты должны сохраниться. Триггер повторно создавать не нужно.
- Проверить логи функции: нет ошибок YDB, Lockbox и Telegram.
- Уже потерянные после локальных перезапусков настройки MemoryStore не восстановятся. После перехода настройки нужно выбрать один раз; далее они будут храниться в YDB.

Офлайн-тесты проверяют обработчик функции и ZIP. Версия Cloud Function, YDB, Lockbox и сервисный аккаунт были созданы; доставка Telegram-триггера не проверялась. Текущий бот работает на ВМ через polling.

Источники:
- https://yandex.cloud/en/docs/functions/quickstart/create-function/python-function-quickstart
- https://yandex.cloud/en/docs/functions/lang/python/handler
- https://yandex.cloud/en/docs/functions/operations/trigger/telegram-trigger-create
- https://yandex.cloud/en/docs/ydb/operations/connection
