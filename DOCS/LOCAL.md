# Локальный запуск

Токен бота задаётся только переменной окружения `BOT_TOKEN`. В репозиторий и в ZIP его не кладут. Ниже нет примера настоящего токена.

Из каталога `cur_converter_bot`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
read -rs BOT_TOKEN
export BOT_TOKEN
RUN_MODE=polling .venv/bin/python -m cur_converter_bot
```

`RUN_MODE=polling` включает long polling. В текущей выкладке YC бот работает на отдельной ВМ в Docker с YDB и Lockbox. Обновление: `sudo sh deploy/update_vm.sh`. Сетевая настройка: DOCS/TELEGRAM_NETWORK.md.

Пока триггер в облаке не создан, polling можно держать включённым. Когда триггер уже забирает апдейты, локальный polling нужно остановить: у бота один получатель.

Проверка без Telegram и без сети:

```bash
.venv/bin/pytest
```

Тест сценария проходит `/start`, смену набора валют и одну конвертацию на фиксированном снимке курсов.

При временной недоступности Telegram polling повторяет подключение с паузой и пишет предупреждение. При ошибке токена запуск завершается. Сбой обновления меню не останавливает polling: команды можно отправлять вручную. Сбой обновления меню также не останавливает обработку Update в Cloud Functions.
