"""Снимок курсов: Frankfurter v2 и запасной URL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Awaitable, Callable, Literal

from cur_converter_bot.catalog import CODES

SourceName = Literal["frankfurter", "fallback"]
Notice = Literal["fresh", "cached", "unavailable"]

FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"
FALLBACK_URL = "https://latest.currency-api.pages.dev/v1/currencies/usd.json"
CACHE_TTL = timedelta(hours=6)


class RateSourceError(Exception):
    pass


@dataclass(frozen=True)
class FxSnapshot:
    per_usd: dict[str, Decimal]
    rate_date: str
    fetched_at: datetime
    source: SourceName


@dataclass(frozen=True)
class Quote:
    snapshot: FxSnapshot | None
    notice: Notice


Fetcher = Callable[[datetime], Awaitable[FxSnapshot]]


def _require_catalog(per_usd: dict[str, Decimal]) -> dict[str, Decimal]:
    missing = [code for code in CODES if code not in per_usd]
    if missing:
        raise RateSourceError(f"missing {','.join(missing)}")
    if any(not value.is_finite() or value <= 0 for value in per_usd.values()):
        raise RateSourceError("rates must be finite and positive")
    if per_usd["USD"] != 1:
        raise RateSourceError("USD rate must equal one")
    return per_usd


def _rate(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise RateSourceError("invalid rate") from exc


def _date(value: object) -> str:
    if not isinstance(value, str):
        raise RateSourceError("invalid rate date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise RateSourceError("invalid rate date") from exc


def parse_frankfurter(payload: object, fetched_at: datetime) -> FxSnapshot:
    if not isinstance(payload, list) or not payload:
        raise RateSourceError("empty frankfurter payload")
    per_usd: dict[str, Decimal] = {"USD": Decimal(1)}
    rate_date = ""
    for row in payload:
        if not isinstance(row, dict):
            raise RateSourceError("frankfurter row")
        quote = str(row.get("quote", "")).upper()
        if row.get("base") != "USD" or quote in per_usd or "rate" not in row:
            raise RateSourceError("invalid frankfurter row")
        row_date = _date(row.get("date"))
        rate_date = min(rate_date, row_date) if rate_date else row_date
        per_usd[quote] = _rate(row["rate"])
    if not rate_date:
        raise RateSourceError("frankfurter date")
    return FxSnapshot(_require_catalog(per_usd), rate_date, fetched_at, "frankfurter")


def parse_fallback(payload: object, fetched_at: datetime) -> FxSnapshot:
    if not isinstance(payload, dict):
        raise RateSourceError("fallback payload")
    table = payload.get("usd")
    if not isinstance(table, dict):
        raise RateSourceError("fallback usd")
    per_usd: dict[str, Decimal] = {"USD": Decimal(1)}
    for code, value in table.items():
        per_usd[str(code).upper()] = _rate(value)
    rate_date = _date(payload.get("date"))
    if not rate_date:
        raise RateSourceError("fallback date")
    return FxSnapshot(_require_catalog(per_usd), rate_date, fetched_at, "fallback")


def frankfurter_request_url(base_url: str = FRANKFURTER_URL) -> str:
    quotes = ",".join(code.lower() for code in CODES if code != "USD")
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}base=usd&quotes={quotes}"


class RateBook:
    def __init__(self, primary: Fetcher, fallback: Fetcher, ttl: timedelta = CACHE_TTL) -> None:
        self._primary = primary
        self._fallback = fallback
        self._ttl = ttl

    async def quote(self, store: object, now: datetime) -> Quote:
        snapshot = await store.get_snapshot()  # type: ignore[attr-defined]
        if snapshot is not None:
            try:
                _require_catalog(snapshot.per_usd)
            except RateSourceError:
                snapshot = None
        if snapshot is not None and now - snapshot.fetched_at < self._ttl:
            return Quote(snapshot, "fresh")
        try:
            fresh = await self._load(self._primary, now)
        except RateSourceError:
            if snapshot is not None:
                return Quote(snapshot, "cached")
            try:
                fresh = await self._load(self._fallback, now)
            except RateSourceError:
                return Quote(None, "unavailable")
        await store.save_snapshot(fresh)  # type: ignore[attr-defined]
        return Quote(fresh, "fresh")

    async def _load(self, fetcher: Fetcher, now: datetime) -> FxSnapshot:
        try:
            return await fetcher(now)
        except RateSourceError:
            raise
        except Exception as exc:
            raise RateSourceError(str(exc)) from exc
