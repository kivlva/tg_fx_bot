"""Клавиатуры и отправка через Bot API. Long polling только для локального прогона."""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)

from cur_converter_bot.catalog import REGIONS, EXTRA_BUTTON, HELP_BUTTON, PICK_BUTTON, flag
from cur_converter_bot.delivery import WEBHOOK_PATH, consume, create_app
from cur_converter_bot.flow import Flow


def reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=EXTRA_BUTTON)],
            [KeyboardButton(text=PICK_BUTTON)],
            [KeyboardButton(text=HELP_BUTTON)],
        ],
        resize_keyboard=True,
    )


def inline_keyboard(selected: tuple[str, ...], region: str = "home") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    suffix = "" if region == "home" else f":{region}"
    selected_buttons = [
        InlineKeyboardButton(text=f"✅ {flag(code)} {code}", callback_data=f"t:{code}{suffix}")
        for code in selected
    ]
    rows.extend(selected_buttons[i:i + 2] for i in range(0, len(selected_buttons), 2))
    if region == "home":
        buttons = [InlineKeyboardButton(text=name, callback_data=f"g:{key}")
                   for key, (name, codes) in REGIONS.items()]
        rows.extend(buttons[i:i + 2] for i in range(0, len(buttons), 2))
        rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="ok")])
    else:
        rows.append([InlineKeyboardButton(text=f"Добавить · {REGIONS[region][0]}", callback_data="noop")])
        buttons = [InlineKeyboardButton(text=f"{flag(code)} {code}", callback_data=f"t:{code}:{region}")
                   for code in REGIONS[region][1] if code not in selected]
        rows.extend(buttons[i:i + 2] for i in range(0, len(buttons), 2))
        rows.append([
            InlineKeyboardButton(text="← Регионы", callback_data="g:home"),
            InlineKeyboardButton(text="✅ Готово", callback_data="ok"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_reply_keyboard = reply_keyboard


class TelegramOutbox:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, chat_id: int, text: str, *, reply_keyboard: bool) -> None:
        markup = _reply_keyboard() if reply_keyboard else None
        await self._bot.send_message(chat_id, text, reply_markup=markup)

    async def send_picker(self, chat_id: int, text: str, selected: tuple[str, ...], *, region: str = "home") -> None:
        await self._bot.send_message(chat_id, text, reply_markup=inline_keyboard(selected, region))

    async def edit_picker(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        selected: tuple[str, ...],
        *,
        region: str = "home",
    ) -> None:
        await self._edit(text, chat_id, message_id, inline_keyboard(selected, region))

    async def close_picker(self, chat_id: int, message_id: int, text: str) -> None:
        await self._edit(text, chat_id, message_id, None)

    async def _edit(self, text, chat_id, message_id, markup) -> None:
        try:
            await self._bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, reply_markup=markup
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in exc.message.lower():
                raise

    async def answer_callback(self, callback_id: str, text: str, *, show_alert: bool) -> None:
        await self._bot.answer_callback_query(callback_id, text=text or None, show_alert=show_alert)


def build_dispatcher(flow: Flow) -> Dispatcher:
    dispatcher = Dispatcher()

    async def on_event(event: object, event_update: Update, bot: Bot) -> None:
        payload = event_update.model_dump(mode="json", by_alias=True, exclude_none=True)
        await consume(flow, TelegramOutbox(bot), payload, datetime.now(timezone.utc))

    dispatcher.message.register(on_event)
    dispatcher.callback_query.register(on_event)

    return dispatcher


async def set_command_menu(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать работу"),
            BotCommand(command="set_currencies", description="Выбрать валюты"),
            BotCommand(command="help", description="Помощь"),
        ],
        request_timeout=10,
    )


def http_application(flow: Flow, bot: Bot):
    return create_app(flow, TelegramOutbox(bot))


__all__ = ["WEBHOOK_PATH", "build_dispatcher", "http_application", "set_command_menu"]
