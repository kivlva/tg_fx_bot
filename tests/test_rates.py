from datetime import timedelta

from cur_converter_bot.rates import RateBook, RateSourceError, parse_fallback, parse_frankfurter
from tests.helpers import NOW, STALE, CountingBook, sample_rates, snapshot

from cur_converter_bot.storage import MemoryStore


def test_parse_frankfurter_rows():
    payload = [
        {"date": "2026-10-03", "base": "USD", "quote": "EUR", "rate": 0.88541},
        {"date": "2026-10-03", "base": "USD", "quote": "RUB", "rate": 83.52},
    ]
    payload.extend(
        {"date": "2026-10-03", "base": "USD", "quote": code, "rate": 1}
        for code in sample_rates()
        if code not in {"USD", "EUR", "RUB"}
    )
    parsed = parse_frankfurter(payload, NOW)
    assert parsed.per_usd["EUR"]
    assert parsed.per_usd["USD"] == 1
    assert parsed.rate_date == "2026-10-03"
    assert parsed.source == "frankfurter"


def test_parse_fallback_table():
    table = {code.lower(): str(value) for code, value in sample_rates().items()}
    parsed = parse_fallback({"date": "2026-10-02", "usd": table}, NOW)
    assert parsed.source == "fallback"
    assert parsed.per_usd["LKR"] == sample_rates()["LKR"]


async def test_fresh_snapshot_does_not_call_network():
    store = MemoryStore()
    await store.save_snapshot(snapshot(NOW))
    book = CountingBook(primary_error=RateSourceError("down"))
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW + timedelta(hours=1))
    assert quote.notice == "fresh"
    assert book.primary_calls == 0
    assert book.fallback_calls == 0


async def test_stale_snapshot_is_replaced():
    store = MemoryStore()
    await store.save_snapshot(snapshot(STALE))
    book = CountingBook()
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW)
    assert quote.notice == "fresh"
    assert book.primary_calls == 1
    assert quote.snapshot.fetched_at == NOW


async def test_primary_timeout_uses_saved_copy():
    store = MemoryStore()
    await store.save_snapshot(snapshot(STALE))

    async def timeout(now):
        raise TimeoutError("slow")

    async def unused(now):
        raise AssertionError("fallback")

    quote = await RateBook(timeout, unused).quote(store, NOW)
    assert quote.notice == "cached"


async def test_primary_failure_uses_saved_copy():
    store = MemoryStore()
    await store.save_snapshot(snapshot(STALE))
    book = CountingBook(primary_error=RateSourceError("down"))
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW)
    assert quote.notice == "cached"
    assert book.fallback_calls == 0


async def test_empty_store_uses_fallback_once_then_unavailable():
    store = MemoryStore()
    book = CountingBook(
        primary_error=RateSourceError("down"),
        fallback_error=RateSourceError("down"),
    )
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW)
    assert quote.notice == "unavailable"
    assert quote.snapshot is None
    assert book.primary_calls == 1
    assert book.fallback_calls == 1


async def test_empty_store_saves_fallback():
    store = MemoryStore()
    book = CountingBook(primary_error=RateSourceError("down"))
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW)
    assert quote.notice == "fresh"
    assert quote.snapshot.source == "fallback"
    assert book.fallback_calls == 1


async def test_snapshot_from_old_catalog_is_refreshed_before_vnd_conversion():
    old = snapshot(NOW)
    del old.per_usd["VND"]
    store = MemoryStore()
    await store.save_snapshot(old)
    book = CountingBook()
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW)
    assert book.primary_calls == 1
    assert "VND" in quote.snapshot.per_usd


async def test_old_catalog_snapshot_cannot_be_used_when_sources_are_down():
    old = snapshot(NOW)
    del old.per_usd["VND"]
    store = MemoryStore()
    await store.save_snapshot(old)
    book = CountingBook(primary_error=RateSourceError("down"), fallback_error=RateSourceError("down"))
    quote = await RateBook(book.primary, book.fallback).quote(store, NOW)
    assert quote.notice == "unavailable"
    assert book.fallback_calls == 1
