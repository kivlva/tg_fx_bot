import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.methods import GetMe

from cur_converter_bot import __main__ as entry


async def test_connection_timeout_retries_without_exiting(monkeypatch):
    bot = Mock()
    bot.me = AsyncMock(side_effect=[TimeoutError(), TelegramNetworkError(method=GetMe(), message="timeout"), object()])
    sleep = AsyncMock()
    monkeypatch.setattr(entry.asyncio, "sleep", sleep)
    await entry._wait_for_telegram(bot)
    assert bot.me.await_count == 3
    assert sleep.await_count == 2


async def test_invalid_token_is_not_retried(monkeypatch):
    bot = Mock()
    bot.me = AsyncMock(side_effect=TelegramUnauthorizedError(method=GetMe(), message="Unauthorized"))
    sleep = AsyncMock()
    monkeypatch.setattr(entry.asyncio, "sleep", sleep)
    with pytest.raises(TelegramUnauthorizedError):
        await entry._wait_for_telegram(bot)
    sleep.assert_not_awaited()


async def test_menu_timeout_does_not_stop_polling_and_session_closes(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456:FAKE_TEST_TOKEN")
    monkeypatch.setenv("RUN_MODE", "polling")
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)
    monkeypatch.delenv("YDB_DATABASE", raising=False)
    bot = AsyncMock()
    bot.__aenter__.return_value = bot
    monkeypatch.setattr(entry, "Bot", lambda token, **kwargs: bot)
    monkeypatch.setattr(entry, "set_command_menu", AsyncMock(side_effect=TelegramNetworkError(method=GetMe(), message="timeout")))
    dispatcher = Mock()
    dispatcher.start_polling = AsyncMock()
    monkeypatch.setattr(entry, "build_dispatcher", lambda flow: dispatcher)
    await entry._serve()
    dispatcher.start_polling.assert_awaited_once_with(bot, close_bot_session=False)
    bot.__aexit__.assert_awaited_once()


async def test_cancellation_while_connecting_closes_session(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456:FAKE_TEST_TOKEN")
    monkeypatch.setenv("RUN_MODE", "polling")
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)
    monkeypatch.delenv("YDB_DATABASE", raising=False)
    bot = AsyncMock()
    bot.__aenter__.return_value = bot
    bot.me.side_effect = asyncio.CancelledError()
    monkeypatch.setattr(entry, "Bot", lambda token, **kwargs: bot)
    with pytest.raises(asyncio.CancelledError):
        await entry._serve()
    bot.__aexit__.assert_awaited_once()
