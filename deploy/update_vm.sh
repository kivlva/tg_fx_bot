#!/bin/sh
set +x
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
IMAGE="cur-converter-bot:$(date -u +%Y%m%d%H%M%S)"
BACKUP="cur-converter-bot-backup-$(date -u +%Y%m%d%H%M%S)"
FALLBACK_IPS=${TELEGRAM_FALLBACK_IPS:-149.154.167.220}
docker build -t "$IMAGE" .
# Probe from the new image before interrupting the working bot, without its token.
docker run --rm -i --network host --entrypoint python \
  -e TELEGRAM_RESILIENT_DNS=1 -e "TELEGRAM_FALLBACK_IPS=$FALLBACK_IPS" "$IMAGE" - <<'PY'
import asyncio
from cur_converter_bot.telegram_network import build_telegram_session

async def check():
    session = build_telegram_session()
    try:
        client = await session.create_session()
        async with client.head("https://api.telegram.org", allow_redirects=False, timeout=20) as response:
            if not 200 <= response.status < 400:
                raise SystemExit("Telegram HTTPS check failed")
            print("Telegram HTTPS OK:", response.status)
    finally:
        await session.close()

asyncio.run(check())
PY
if docker container inspect cur-converter-bot >/dev/null 2>&1; then
  docker stop cur-converter-bot >/dev/null
  docker rename cur-converter-bot "$BACKUP"
  echo "Предыдущий контейнер сохранён: $BACKUP"
fi
docker run -d --name cur-converter-bot --restart unless-stopped --network host \
  --log-opt max-size=10m --log-opt max-file=3 \
  -e RUN_MODE=polling -e TELEGRAM_RESILIENT_DNS=1 \
  -e "TELEGRAM_FALLBACK_IPS=$FALLBACK_IPS" \
  -e "LOCKBOX_SECRET_ID=${LOCKBOX_SECRET_ID:-e6qvccv5g1chp9rb3sfr}" \
  -e "YDB_ENDPOINT=${YDB_ENDPOINT:-grpcs://ydb.serverless.yandexcloud.net:2135}" \
  -e "YDB_DATABASE=${YDB_DATABASE:-/ru-central1/b1g54odv2ftoe8aet43a/etni0gibk6opsl2hvlha}" \
  "$IMAGE"
echo "Контейнер обновлён без --add-host. Проверьте /start и docker logs."
echo "Для отката к сохранённому контейнеру (если он был создан):"
printf 'sudo docker rm -f cur-converter-bot\nsudo docker rename %s cur-converter-bot\nsudo docker start cur-converter-bot\n' "$BACKUP"
