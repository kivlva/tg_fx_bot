"""Точка входа: HTTP для контейнера или long polling локально."""

from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramServerError, TelegramRetryAfter

from cur_converter_bot.telegram_network import build_telegram_session
from cur_converter_bot.flow import Flow
from cur_converter_bot.rates import (
    FALLBACK_URL,
    FRANKFURTER_URL,
    CACHE_TTL,
    RateBook,
    RateSourceError,
    parse_fallback,
    parse_frankfurter,
    frankfurter_request_url,
)
from cur_converter_bot.storage import MemoryStore, YdbStore
from cur_converter_bot.telegram_io import (
    build_dispatcher,
    http_application,
    set_command_menu,
)


def _require_token() -> str:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN is not set")
    return token


def build_store():
    endpoint = os.environ.get("YDB_ENDPOINT", "").strip()
    database = os.environ.get("YDB_DATABASE", "").strip()
    if bool(endpoint) != bool(database):
        raise SystemExit("YDB_ENDPOINT and YDB_DATABASE must be set together")
    if not endpoint and os.environ.get("RUN_MODE", "http").strip() != "polling":
        raise SystemExit("HTTP mode requires YDB_ENDPOINT and YDB_DATABASE")
    if endpoint and database:
        store = YdbStore(endpoint, database)
        store.ensure_schema()
        return store
    return MemoryStore()


def build_rates() -> RateBook:
    import aiohttp

    frankfurter = os.environ.get("FRANKFURTER_URL", FRANKFURTER_URL).strip()
    fallback = os.environ.get("FALLBACK_FX_URL", FALLBACK_URL).strip()
    timeout = aiohttp.ClientTimeout(total=10)

    async def primary(now):
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(frankfurter_request_url(frankfurter)) as response:
                if response.status != 200:
                    raise RateSourceError(f"frankfurter status {response.status}")
                payload = await response.json(content_type=None)
        return parse_frankfurter(payload, now)

    async def secondary(now):
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(fallback) as response:
                if response.status != 200:
                    raise RateSourceError(f"fallback status {response.status}")
                payload = await response.json(content_type=None)
        return parse_fallback(payload, now)

    ttl_raw = os.environ.get("FX_CACHE_TTL_SECONDS", "").strip()
    ttl = CACHE_TTL
    if ttl_raw:
        from datetime import timedelta

        ttl = timedelta(seconds=int(ttl_raw))
    return RateBook(primary, secondary, ttl)


async def _wait_for_telegram(bot: Bot) -> None:
    while True:
        try:
            await asyncio.wait_for(bot.me(), timeout=10)
            return
        except (TelegramNetworkError, TelegramServerError, TimeoutError):
            logging.getLogger(__name__).warning(
                "Telegram недоступен. Повтор подключения через 5 секунд; проверь сеть/VPN."
            )
            await asyncio.sleep(5)
        except TelegramRetryAfter as exc:
            logging.getLogger(__name__).warning("Telegram ограничил запросы; ждём %s секунд.", exc.retry_after)
            await asyncio.sleep(exc.retry_after)


async def _serve() -> None:
    token = _require_token()
    mode = os.environ.get("RUN_MODE", "http").strip()
    if mode not in {"http", "polling"}:
        raise SystemExit("RUN_MODE must be http or polling")
    store = build_store()
    flow = Flow(store, build_rates())
    async with Bot(token, session=build_telegram_session()) as bot:
        if mode == "polling":
            await _wait_for_telegram(bot)
        try:
            await set_command_menu(bot)
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter):
            logging.getLogger(__name__).warning(
                "Меню команд сейчас не обновилось. Продолжаем запуск; команды доступны вручную."
            )
        if mode == "polling":
            dispatcher = build_dispatcher(flow)
            await dispatcher.start_polling(bot, close_bot_session=False)
            return
        port = int(os.environ.get("PORT", "8080"))
        application = http_application(flow, bot)
        runner = web.AppRunner(application)
        await runner.setup()
        try:
            await web.TCPSite(runner, "0.0.0.0", port).start()
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
