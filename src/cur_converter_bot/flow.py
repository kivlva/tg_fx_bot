"""Диалог бота без привязки к Telegram."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from cur_converter_bot.catalog import (
    BEFORE_START,
    CODE_SET,
    CURRENCY_HINT,
    EXTRA_BUTTON,
    EXTRA_HINT,
    HELP_BUTTON,
    LAST_ONE,
    PICK_BUTTON,
    RATES_UNAVAILABLE,
    REGIONS,
    TOO_MANY,
    picker_text,
    saved_text,
    welcome_text,
)
from cur_converter_bot.convert import ParseFailure, conversion_text, parse_amount
from cur_converter_bot.rates import RateBook
from cur_converter_bot.storage import Store

Action = Literal[
    "ignore",
    "ack",
    "text",
    "welcome",
    "picker",
    "edit_picker",
    "close_picker",
    "alert",
]


@dataclass(frozen=True)
class Reply:
    action: Action
    text: str = ""
    selected: tuple[str, ...] = ()
    region: str = "home"


def _stamp(now: datetime) -> str:
    return f"{now.astimezone(timezone.utc).isoformat(timespec='microseconds')}:{uuid4().hex}"


def _command(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return stripped
    head, _, tail = stripped.partition(" ")
    name, _, _bot = head.partition("@")
    return name if not tail else f"{name} {tail}"


class Flow:
    def __init__(self, store: Store, rates: RateBook) -> None:
        self._store = store
        self._rates = rates

    async def handle_text(
        self,
        *,
        user_id: int,
        chat_type: str,
        update_id: int,
        text: str,
        now: datetime,
    ) -> Reply:
        if chat_type != "private":
            return Reply("ignore")
        if not await self._store.claim_update(update_id):
            return Reply("ignore")
        try:
            return await self._text(user_id, _command(text), now)
        except Exception:
            await self._store.release_update(update_id)
            raise

    async def handle_callback(
        self,
        *,
        user_id: int,
        chat_type: str,
        update_id: int,
        data: str,
        now: datetime,
    ) -> Reply:
        if chat_type != "private":
            return Reply("ack")
        if data.startswith("t:"):
            parts = data.split(":")
            if len(parts) not in {2, 3}:
                return Reply("ack")
            code = parts[1]
            region = parts[2] if len(parts) == 3 else "home"
            if region != "home" and region not in REGIONS:
                return Reply("ack")
            if code not in CODE_SET:
                return Reply("alert", CURRENCY_HINT)
            settings, status = await self._store.toggle_currency(
                user_id, code, update_id, _stamp(now)
            )
            if settings is None:
                return Reply("text", BEFORE_START)
            if status == "too_many":
                return Reply("alert", TOO_MANY, settings.currencies)
            if status == "last_one":
                return Reply("alert", LAST_ONE, settings.currencies)
            return Reply("edit_picker", picker_text(settings.currencies, region), settings.currencies, region)
        if not await self._store.claim_update(update_id):
            return await self._replay_callback(user_id, data)
        try:
            return await self._callback(user_id, data)
        except Exception:
            await self._store.release_update(update_id)
            raise

    async def _text(self, user_id: int, text: str, now: datetime) -> Reply:
        if text == "/start":
            settings = await self._store.create_user(user_id, _stamp(now))
            return Reply("welcome", welcome_text(settings.currencies), settings.currencies)
        settings = await self._store.get_user(user_id)
        if settings is None:
            return Reply("text", BEFORE_START)
        if text in {"/help", HELP_BUTTON}:
            return Reply("welcome", welcome_text(settings.currencies), settings.currencies)
        if text in {"/set_currencies", PICK_BUTTON}:
            return Reply("picker", picker_text(settings.currencies), settings.currencies)
        if text == EXTRA_BUTTON:
            return Reply("text", EXTRA_HINT)
        parsed = parse_amount(text)
        if isinstance(parsed, ParseFailure):
            return Reply("text", parsed.text)
        quote = await self._rates.quote(self._store, now)
        if quote.notice == "unavailable" or quote.snapshot is None:
            return Reply("text", RATES_UNAVAILABLE)
        body = conversion_text(
            parsed.amount,
            parsed.code,
            settings.currencies,
            quote.snapshot.per_usd,
            cached=quote.notice == "cached",
        )
        return Reply("text", body)

    async def _callback(
        self,
        user_id: int,
        data: str,
    ) -> Reply:
        settings = await self._store.get_user(user_id)
        if settings is None:
            return Reply("text", BEFORE_START)
        if data == "ok":
            return Reply("close_picker", saved_text(settings.currencies), settings.currencies)
        if data.startswith("g:"):
            region = data[2:]
            if region == "home" or region in REGIONS:
                return Reply("edit_picker", picker_text(settings.currencies, region), settings.currencies, region)
        return Reply("ack")

    async def release_update(self, update_id: int) -> None:
        await self._store.release_update(update_id)

    async def _replay_callback(self, user_id: int, data: str) -> Reply:
        return await self._callback(user_id, data)
