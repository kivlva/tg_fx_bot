import asyncio
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText

from cur_converter_bot.__main__ import build_store
from cur_converter_bot.catalog import DEFAULT_CURRENCIES
from cur_converter_bot.flow import Flow
from cur_converter_bot.rates import RateBook, RateSourceError, parse_fallback, parse_frankfurter
from cur_converter_bot.storage import MemoryStore
from cur_converter_bot.telegram_io import TelegramOutbox
from tests.helpers import NOW, CountingBook, sample_rates


async def test_real_outbox_builds_welcome_keyboard():
    bot = AsyncMock()
    outbox = TelegramOutbox(bot)
    await outbox.send(1, "welcome", reply_keyboard=True)
    markup = bot.send_message.call_args.kwargs["reply_markup"]
    assert len(markup.keyboard) == 3
    await outbox.send(1, "conversion", reply_keyboard=False)
    assert bot.send_message.call_args.kwargs["reply_markup"] is None


@pytest.mark.parametrize("close", [False, True])
async def test_repeated_picker_edit_is_successful(close):
    bot = AsyncMock()
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="x"), message="Bad Request: message is not modified"
    )
    outbox = TelegramOutbox(bot)
    if close:
        await outbox.close_picker(1, 2, "saved")
    else:
        await outbox.edit_picker(1, 2, "picker", DEFAULT_CURRENCIES)
    bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="x"), message="Bad Request: message to edit not found"
    )
    with pytest.raises(TelegramBadRequest):
        await outbox.close_picker(1, 2, "saved")


async def test_unknown_callback_does_not_corrupt_user():
    store = MemoryStore()
    await store.create_user(1, "initial")
    await store.save_currencies(1, ("USD",), "initial", "one")
    book = CountingBook()
    flow = Flow(store, RateBook(book.primary, book.fallback))
    reply = await flow.handle_callback(
        user_id=1, chat_type="private", update_id=3, data="t:XXX", now=NOW
    )
    assert reply.action == "alert"
    assert (await store.get_user(1)).currencies == ("USD",)
    reply = await flow.handle_text(
        user_id=1, chat_type="private", update_id=4, text="1 usd", now=NOW
    )
    assert "без конвертации" in reply.text


async def test_parallel_toggles_and_duplicates_preserve_all_changes():
    store = MemoryStore()
    await store.create_user(1, "initial")
    book = CountingBook()
    flows = [Flow(store, RateBook(book.primary, book.fallback)) for _ in range(2)]
    async def toggle(flow, update_id, code):
        return await flow.handle_callback(
            user_id=1, chat_type="private", update_id=update_id, data=f"t:{code}", now=NOW
        )
    await asyncio.gather(toggle(flows[0], 2, "THB"), toggle(flows[1], 3, "EUR"))
    assert (await store.get_user(1)).currencies == ("USD", "LKR", "RUB")
    await asyncio.gather(toggle(flows[0], 4, "AED"), toggle(flows[1], 4, "AED"))
    assert (await store.get_user(1)).currencies == ("USD", "LKR", "RUB", "AED")


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "bad"])
@pytest.mark.parametrize("source", ["primary", "fallback"])
def test_invalid_rates_are_rejected(value, source):
    values = sample_rates()
    values["LKR"] = value
    if source == "primary":
        payload = [dict(date="2026-10-03", base="USD", quote=code, rate=str(rate))
                   for code, rate in values.items() if code != "USD"]
        parser = parse_frankfurter
    else:
        payload = {"date": "2026-10-03", "usd": {c.lower(): str(v) for c, v in values.items()}}
        parser = parse_fallback
    with pytest.raises(RateSourceError):
        parser(payload, NOW)


def test_wrong_base_and_missing_rates_are_rejected():
    rows = [dict(date="2026-10-03", base="EUR", quote=c, rate=1)
            for c in sample_rates() if c != "USD"]
    with pytest.raises(RateSourceError):
        parse_frankfurter(rows, NOW)
    for row in rows:
        row["base"] = "USD"
    rows.pop()
    with pytest.raises(RateSourceError):
        parse_frankfurter(rows, NOW)


@pytest.mark.parametrize("date", ["", "yesterday", "2026-99-99", None])
def test_invalid_rate_dates_are_rejected(date):
    table = {c.lower(): str(v) for c, v in sample_rates().items()}
    with pytest.raises(RateSourceError):
        parse_fallback({"date": date, "usd": table}, NOW)


def test_http_requires_complete_ydb_configuration(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "http")
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)
    monkeypatch.delenv("YDB_DATABASE", raising=False)
    with pytest.raises(SystemExit, match="HTTP mode requires"):
        build_store()
    monkeypatch.setenv("YDB_ENDPOINT", "endpoint")
    with pytest.raises(SystemExit, match="must be set together"):
        build_store()
    monkeypatch.delenv("YDB_ENDPOINT")
    monkeypatch.setenv("RUN_MODE", "polling")
    assert isinstance(build_store(), MemoryStore)


async def test_failed_edit_retry_does_not_toggle_again():
    from cur_converter_bot.delivery import consume
    from tests.test_http import RecordingOutbox, _callback
    store = MemoryStore()
    await store.create_user(5, "initial")
    book = CountingBook()
    flow = Flow(store, RateBook(book.primary, book.fallback))
    outbox = RecordingOutbox()
    edit = AsyncMock(side_effect=RuntimeError("temporary failure"))
    outbox.edit_picker = edit
    with pytest.raises(RuntimeError):
        await consume(flow, outbox, _callback(2, "t:THB"), NOW)
    assert (await store.get_user(5)).currencies == ("USD", "LKR", "RUB", "EUR")
    edit.side_effect = None
    assert await consume(flow, outbox, _callback(2, "t:THB"), NOW)
    assert (await store.get_user(5)).currencies == ("USD", "LKR", "RUB", "EUR")
    assert len(outbox.callbacks) == 1


@pytest.mark.parametrize("seconds,calls", [(21599, 0), (21600, 1), (21601, 1)])
async def test_cache_expiry_boundary(seconds, calls):
    from datetime import timedelta
    from tests.helpers import snapshot
    store = MemoryStore()
    await store.save_snapshot(snapshot(NOW))
    book = CountingBook()
    await RateBook(book.primary, book.fallback).quote(store, NOW + timedelta(seconds=seconds))
    assert book.primary_calls == calls


async def test_polling_dispatcher_routes_start_toggle_and_conversion(monkeypatch):
    from aiogram import Bot
    from aiogram.types import Update
    from cur_converter_bot import telegram_io
    from tests.test_http import RecordingOutbox, _message, _callback
    store = MemoryStore()
    book = CountingBook()
    outbox = RecordingOutbox()
    monkeypatch.setattr(telegram_io, "TelegramOutbox", lambda bot: outbox)
    dispatcher = telegram_io.build_dispatcher(Flow(store, RateBook(book.primary, book.fallback)))
    assert set(dispatcher.resolve_used_update_types()) == {"message", "callback_query"}
    bot = Bot("123456:FAKE_TEST_TOKEN")
    async def feed(payload):
        event = payload.get("message") or payload["callback_query"]
        event["from"].update(is_bot=False, first_name="Test")
        message = payload.get("message") or event["message"]
        message["date"] = 0
        if "callback_query" in payload:
            event["chat_instance"] = "test-chat"
        await dispatcher.feed_update(bot, Update.model_validate(payload))
    try:
        await feed(_message(1, "/start"))
        assert (await store.get_user(5)).currencies == DEFAULT_CURRENCIES
        assert outbox.sent[-1][2] is True
        await feed(_callback(2, "t:THB"))
        assert outbox.edits[-1] == ("USD", "LKR", "RUB", "EUR")
        await feed(_message(3, "7.21 usd"))
        assert "2,163.00" in outbox.sent[-1][1]
        assert book.primary_calls == 1
        sent = len(outbox.sent)
        await feed(_message(4, "/start", chat_type="group"))
        assert len(outbox.sent) == sent
    finally:
        await bot.session.close()
        await dispatcher.storage.close()
