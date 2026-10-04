from cur_converter_bot.catalog import (
    BEFORE_START,
    DEFAULT_CURRENCIES,
    EXTRA_BUTTON,
    EXTRA_HINT,
    PICK_BUTTON,
    RATES_CACHED,
    RATES_UNAVAILABLE,
    TOO_MANY,
)
from cur_converter_bot.flow import Flow
from cur_converter_bot.rates import RateBook, RateSourceError
from cur_converter_bot.storage import MemoryStore
from tests.helpers import NOW, STALE, CountingBook, snapshot


def _flow(book: CountingBook, store: MemoryStore | None = None) -> tuple[Flow, MemoryStore]:
    store = store or MemoryStore()
    return Flow(store, RateBook(book.primary, book.fallback)), store


async def test_message_before_start_does_not_create_user():
    flow, store = _flow(CountingBook())
    reply = await flow.handle_text(
        user_id=1, chat_type="private", update_id=1, text="100 usd", now=NOW
    )
    assert reply.text == BEFORE_START
    assert await store.get_user(1) is None


async def test_group_message_is_silent():
    flow, store = _flow(CountingBook())
    reply = await flow.handle_text(
        user_id=1, chat_type="group", update_id=1, text="/start", now=NOW
    )
    assert reply.action == "ignore"
    assert await store.get_user(1) is None


async def test_local_flow_start_selection_and_conversion():
    book = CountingBook()
    flow, store = _flow(book)
    started = await flow.handle_text(
        user_id=7, chat_type="private", update_id=1, text="/start", now=NOW
    )
    assert started.action == "welcome"
    assert started.selected == DEFAULT_CURRENCIES
    assert "100 usd" in started.text

    opened = await flow.handle_text(
        user_id=7, chat_type="private", update_id=2, text=PICK_BUTTON, now=NOW
    )
    assert opened.action == "picker"

    blocked = await flow.handle_callback(
        user_id=7, chat_type="private", update_id=3, data="t:AED", now=NOW
    )
    assert blocked.action == "alert"
    assert blocked.text == TOO_MANY

    removed = await flow.handle_callback(
        user_id=7, chat_type="private", update_id=4, data="t:THB", now=NOW
    )
    assert removed.action == "edit_picker"
    assert removed.selected == ("USD", "LKR", "RUB", "EUR")

    again = await flow.handle_callback(
        user_id=7, chat_type="private", update_id=4, data="t:THB", now=NOW
    )
    assert again.action == "edit_picker"
    assert again.selected == ("USD", "LKR", "RUB", "EUR")
    saved = await store.get_user(7)
    assert saved is not None
    assert saved.currencies == ("USD", "LKR", "RUB", "EUR")

    done = await flow.handle_callback(
        user_id=7, chat_type="private", update_id=5, data="ok", now=NOW
    )
    assert done.action == "close_picker"
    assert "EUR" in done.text

    converted = await flow.handle_text(
        user_id=7, chat_type="private", update_id=6, text="7.21 usd", now=NOW
    )
    assert "7.21 🇺🇸 USD (без конвертации)" in converted.text
    assert "2,163.00 🇱🇰 LKR" in converted.text
    assert "648.90 🇷🇺 RUB" in converted.text
    assert "6.49 🇪🇺 EUR" in converted.text
    assert "THB" not in converted.text
    assert book.primary_calls == 1

    hint = await flow.handle_text(
        user_id=7, chat_type="private", update_id=7, text=EXTRA_BUTTON, now=NOW
    )
    assert hint.text == EXTRA_HINT


async def test_bad_amount_does_not_request_rates():
    book = CountingBook()
    flow, _store = _flow(book)
    await flow.handle_text(user_id=1, chat_type="private", update_id=1, text="/start", now=NOW)
    reply = await flow.handle_text(
        user_id=1, chat_type="private", update_id=2, text="0 usd", now=NOW
    )
    assert "больше нуля" in reply.text
    assert book.primary_calls == 0


async def test_cached_and_unavailable_notices():
    store = MemoryStore()
    await store.create_user(1, "stamp")
    await store.save_snapshot(snapshot(STALE))
    cached_book = CountingBook(primary_error=RateSourceError("down"))
    flow = Flow(store, RateBook(cached_book.primary, cached_book.fallback))
    cached = await flow.handle_text(
        user_id=1, chat_type="private", update_id=1, text="1000 lkr", now=NOW
    )
    assert RATES_CACHED in cached.text
    assert "LKR (без конвертации)" in cached.text

    empty = MemoryStore()
    await empty.create_user(2, "stamp")
    down = CountingBook(
        primary_error=RateSourceError("down"),
        fallback_error=RateSourceError("down"),
    )
    flow_down = Flow(empty, RateBook(down.primary, down.fallback))
    missing = await flow_down.handle_text(
        user_id=2, chat_type="private", update_id=1, text="10 eur", now=NOW
    )
    assert missing.text == RATES_UNAVAILABLE


async def test_save_conflict_does_not_apply_second_writer():
    store = MemoryStore()
    await store.create_user(1, "first")
    current = await store.get_user(1)
    assert current is not None
    lost = await store.save_currencies(1, ("USD",), "other", "second")
    assert lost is None
    kept = await store.get_user(1)
    assert kept is not None
    assert kept.currencies == current.currencies
    claimed = await store.claim_update(9)
    assert claimed is True
    assert await store.claim_update(9) is False
