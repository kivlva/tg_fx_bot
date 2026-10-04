"""Вход Telegram-триггера Yandex Cloud Functions."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramServerError, TelegramRetryAfter

from cur_converter_bot.__main__ import _require_token, build_rates, build_store
from cur_converter_bot.delivery import consume
from cur_converter_bot.flow import Flow
from cur_converter_bot.telegram_io import TelegramOutbox, set_command_menu

_store = None
_store_lock = threading.Lock()
_menu_configured = False


def _get_store():
    global _store
    with _store_lock:
        if _store is None:
            import os
            if not os.environ.get("YDB_ENDPOINT") or not os.environ.get("YDB_DATABASE"):
                raise RuntimeError("Cloud Functions requires YDB_ENDPOINT and YDB_DATABASE")
            _store = build_store()
        return _store


def update_payload(event: object) -> object:
    if isinstance(event, dict) and "httpMethod" in event:
        body = event.get("body", "")
        try:
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body, validate=True).decode("utf-8")
            return json.loads(body)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("Invalid Telegram update body") from exc
    return event


async def handler(event: object, context: object) -> dict:
    global _menu_configured
    payload = update_payload(event)
    if not isinstance(payload, dict) or type(payload.get("update_id")) is not int:
        raise ValueError("Invalid Telegram update")
    token = _require_token()
    store = await asyncio.to_thread(_get_store)
    flow = Flow(store, build_rates())
    async with Bot(token, session=AiohttpSession(timeout=15)) as bot:
        if not _menu_configured:
            try:
                await set_command_menu(bot)
                _menu_configured = True
            except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter):
                logging.getLogger(__name__).warning("Меню команд не обновилось; обрабатываем сообщение.")
        if not await consume(flow, TelegramOutbox(bot), payload, datetime.now(timezone.utc)):
            raise ValueError("Invalid Telegram update")
    return {"statusCode": 200, "body": "ok"}
