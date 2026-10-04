#!/bin/sh
set +x
set -eu

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$APP_DIR"
for tool in yc python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Не найдена команда $tool. Облачные ресурсы не создавались." >&2; exit 1; }
done
if [ -z "${BOT_TOKEN:-}" ]; then
  echo "Нужен BOT_TOKEN в окружении. Значение не передавайте в аргументах." >&2
  exit 1
fi
YC_FOLDER_ID=${YC_FOLDER_ID:-$(yc config get folder-id)}
if [ -z "$YC_FOLDER_ID" ]; then
  echo "Нужен YC_FOLDER_ID или folder-id в конфигурации yc." >&2
  exit 1
fi
NAME=${BOT_RESOURCE_NAME:-cur-converter-bot}
PACKAGE_DIR=$(mktemp -d)
trap 'rm -rf "$PACKAGE_DIR"' EXIT HUP INT TERM
python3 deploy/package_function.py "$PACKAGE_DIR/function.zip"
export BOT_TOKEN
cloud() { yc --folder-id "$YC_FOLDER_ID" "$@"; }
cloud resource-manager folder get --id "$YC_FOLDER_ID" >/dev/null

if ! cloud iam service-account get --name "$NAME" >/dev/null 2>&1; then
  cloud iam service-account create --name "$NAME" >/dev/null
fi
SA_ID=$(cloud iam service-account get --name "$NAME" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

if ! cloud ydb database get --name "$NAME" >/dev/null 2>&1; then
  cloud ydb database create --name "$NAME" --serverless \
    --sls-provisioned-rcu 0 --sls-storage-size 1GB >/dev/null
fi
YDB_ID=$(cloud ydb database get --name "$NAME" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
cloud ydb database add-access-binding --id "$YDB_ID" \
  --role ydb.editor --subject "serviceAccount:$SA_ID" >/dev/null
YDB_INFO=$(cloud ydb database get --name "$NAME" --format json | python3 deploy/ydb_connection.py)
YDB_ENDPOINT=$(printf '%s\n' "$YDB_INFO" | sed -n '1p')
YDB_PATH=$(printf '%s\n' "$YDB_INFO" | sed -n '2p')

secret_payload() {
  python3 -c 'import json,os; print(json.dumps([{"key":"BOT_TOKEN","text_value":os.environ["BOT_TOKEN"]}]))'
}
if ! cloud lockbox secret get --name "$NAME-token" >/dev/null 2>&1; then
  secret_payload | cloud lockbox secret create --name "$NAME-token" --payload - >/dev/null
else
  secret_payload | cloud lockbox secret add-version --name "$NAME-token" --payload - >/dev/null
fi
SECRET_ID=$(cloud lockbox secret get --name "$NAME-token" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
SECRET_VERSION=$(cloud lockbox secret get --name "$NAME-token" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["current_version"]["id"])')
cloud lockbox secret add-access-binding --id "$SECRET_ID" \
  --role lockbox.payloadViewer --subject "serviceAccount:$SA_ID" >/dev/null

if ! cloud serverless function get --name "$NAME" >/dev/null 2>&1; then
  cloud serverless function create --name "$NAME" >/dev/null
fi
FUNCTION_ID=$(cloud serverless function get --name "$NAME" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
cloud serverless function add-access-binding --id "$FUNCTION_ID" \
  --role functions.functionInvoker --subject "serviceAccount:$SA_ID" >/dev/null

cloud serverless function version create \
  --function-id "$FUNCTION_ID" --runtime python312 --entrypoint index.handler \
  --source-path "$PACKAGE_DIR/function.zip" --service-account-id "$SA_ID" \
  --memory 512M --execution-timeout 120s --concurrency 1 \
  --environment "RUN_MODE=function,YDB_ENDPOINT=${YDB_ENDPOINT},YDB_DATABASE=${YDB_PATH}" \
  --secret "environment-variable=BOT_TOKEN,id=${SECRET_ID},version-id=${SECRET_VERSION},key=BOT_TOKEN"

printf 'Каталог: %s\nФункция: %s\nСервисный аккаунт: %s\n' "$YC_FOLDER_ID" "$FUNCTION_ID" "$SA_ID"
echo "Версия функции готова. Telegram-триггер ещё не создан: бот пока не переключён."
echo "Cloud Functions — альтернативный вариант. Telegram-триггер в этом скрипте не создаётся."
echo "Текущая выкладка на ВМ: sudo sh deploy/update_vm.sh. См. README.md."
