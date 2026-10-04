"""Доставка ответа и HTTP-вход триггера Telegram."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from aiohttp import web

from cur_converter_bot.flow import Flow, Reply

WEBHOOK_PATH = "/telegram"


class Outbox(Protocol):
    async def send(self, chat_id: int, text: str, *, reply_keyboard: bool) -> None: ...

    async def send_picker(self, chat_id: int, text: str, selected: tuple[str, ...], *, region: str = "home") -> None: ...

    async def edit_picker(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        selected: tuple[str, ...],
        *,
        region: str = "home",
    ) -> None: ...

    async def close_picker(self, chat_id: int, message_id: int, text: str) -> None: ...

    async def answer_callback(self, callback_id: str, text: str, *, show_alert: bool) -> None: ...


async def present(
    outbox: Outbox,
    reply: Reply,
    *,
    chat_id: int,
    message_id: int | None,
    callback_id: str | None,
) -> None:
    if reply.action == "ignore":
        return
    if reply.action == "ack":
        if callback_id is not None:
            await outbox.answer_callback(callback_id, "", show_alert=False)
        return
    if reply.action == "alert":
        if callback_id is not None:
            await outbox.answer_callback(callback_id, reply.text, show_alert=True)
        return
    if reply.action == "welcome":
        await outbox.send(chat_id, reply.text, reply_keyboard=True)
    elif reply.action == "text":
        await outbox.send(chat_id, reply.text, reply_keyboard=False)
    elif reply.action == "picker":
        await outbox.send_picker(chat_id, reply.text, reply.selected, region=reply.region)
    elif reply.action == "edit_picker" and message_id is not None:
        await outbox.edit_picker(chat_id, message_id, reply.text, reply.selected, region=reply.region)
    elif reply.action == "close_picker" and message_id is not None:
        await outbox.close_picker(chat_id, message_id, reply.text)
    if callback_id is not None:
        await outbox.answer_callback(callback_id, "", show_alert=False)


async def consume(flow: Flow, outbox: Outbox, payload: object, now: datetime) -> bool:
    if not isinstance(payload, dict):
        return False
    update_id = payload.get("update_id")
    if not isinstance(update_id, int):
        return False
    message = payload.get("message")
    if isinstance(message, dict):
        return await _consume_message(flow, outbox, update_id, message, now)
    callback = payload.get("callback_query")
    if isinstance(callback, dict):
        return await _consume_callback(flow, outbox, update_id, callback, now)
    return True


async def _deliver(
    flow: Flow,
    outbox: Outbox,
    update_id: int,
    reply: Reply,
    *,
    chat_id: int,
    message_id: int | None,
    callback_id: str | None,
) -> None:
    try:
        await present(
            outbox,
            reply,
            chat_id=chat_id,
            message_id=message_id,
            callback_id=callback_id,
        )
    except Exception:
        if reply.action != "edit_picker":
            await flow.release_update(update_id)
        raise


def _user(payload: dict) -> dict:
    user = payload.get("from")
    if not isinstance(user, dict):
        user = payload.get("from_user")
    return user if isinstance(user, dict) else {}


async def _consume_message(
    flow: Flow,
    outbox: Outbox,
    update_id: int,
    message: dict,
    now: datetime,
) -> bool:
    user = _user(message)
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    if not isinstance(user.get("id"), int) or not isinstance(chat.get("id"), int):
        return False
    reply = await flow.handle_text(
        user_id=user["id"],
        chat_type=str(chat.get("type", "")),
        update_id=update_id,
        text=str(message.get("text") or ""),
        now=now,
    )
    await _deliver(
        flow,
        outbox,
        update_id,
        reply,
        chat_id=chat["id"],
        message_id=None,
        callback_id=None,
    )
    return True


async def _consume_callback(
    flow: Flow,
    outbox: Outbox,
    update_id: int,
    callback: dict,
    now: datetime,
) -> bool:
    user = _user(callback)
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    callback_id = callback.get("id")
    if not isinstance(user.get("id"), int) or not isinstance(chat.get("id"), int):
        return False
    if not isinstance(callback_id, str):
        return False
    reply = await flow.handle_callback(
        user_id=user["id"],
        chat_type=str(chat.get("type", "")),
        update_id=update_id,
        data=str(callback.get("data") or ""),
        now=now,
    )
    message_id = message.get("message_id") if isinstance(message.get("message_id"), int) else None
    await _deliver(
        flow,
        outbox,
        update_id,
        reply,
        chat_id=chat["id"],
        message_id=message_id,
        callback_id=callback_id,
    )
    return True


def create_app(flow: Flow, outbox: Outbox, clock=None) -> web.Application:
    async def handle(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.Response(status=400, text="bad json")
        now = clock() if clock is not None else datetime.now(timezone.utc)
        if not await consume(flow, outbox, payload, now):
            return web.Response(status=400, text="bad update")
        return web.Response(status=200, text="ok")

    application = web.Application()
    application.router.add_post(WEBHOOK_PATH, handle)
    application.router.add_post("/", handle)
    return application
