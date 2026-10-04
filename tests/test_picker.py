from unittest.mock import AsyncMock

from cur_converter_bot.catalog import CODES, DEFAULT_CURRENCIES, NAMES, REGIONS, TOO_MANY, LAST_ONE
from cur_converter_bot.delivery import consume, present
from cur_converter_bot.flow import Flow
from cur_converter_bot.rates import RateBook
from cur_converter_bot.storage import MemoryStore
from cur_converter_bot.telegram_io import TelegramOutbox, inline_keyboard
from tests.helpers import NOW, CountingBook
from tests.test_http import _callback


def buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_every_currency_is_accessible_in_exactly_one_region():
    grouped = [code for _, codes in REGIONS.values() for code in codes]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) == set(CODES) == set(NAMES)
    accessible = set()
    for region in REGIONS:
        markup = inline_keyboard((), region)
        accessible.update(b.callback_data.split(":")[1] for b in buttons(markup)
                          if b.callback_data.startswith("t:"))
    assert accessible == set(CODES)


def test_selected_currencies_are_visible_above_regions_and_not_duplicated():
    selected = ("USD", "VND", "EUR")
    home = buttons(inline_keyboard(selected))
    assert [b.text for b in home[:3]] == ["✅ 🇺🇸 USD", "✅ 🇻🇳 VND", "✅ 🇪🇺 EUR"]
    assert {b.callback_data for b in home if b.callback_data.startswith("g:")} == {
        f"g:{region}" for region in REGIONS
    }
    regional = buttons(inline_keyboard(selected, "asia"))
    assert [b.callback_data for b in regional[:3]] == ["t:USD:asia", "t:VND:asia", "t:EUR:asia"]
    assert sum(b.callback_data == "t:VND:asia" for b in regional) == 1
    assert "t:JPY:asia" in {b.callback_data for b in regional}
    assert regional[-2].callback_data == "g:home"
    assert all(len(b.callback_data.encode()) <= 64 for b in regional)


async def test_navigation_add_remove_repeat_and_done():
    store = MemoryStore()
    book = CountingBook()
    flow = Flow(store, RateBook(book.primary, book.fallback))
    await store.create_user(5, "initial")
    async def click(update_id, data):
        return await flow.handle_callback(user_id=5, chat_type="private", update_id=update_id, data=data, now=NOW)
    reply = await click(1, "g:asia")
    assert reply.region == "asia" and "Выбрано 5 из 5" in reply.text
    assert "Изменения сохраняются сразу" in reply.text
    assert (await store.get_user(5)).currencies == DEFAULT_CURRENCIES
    reply = await click(2, "t:THB:asia")
    assert reply.region == "asia" and "Выбрано 4 из 5" in reply.text
    reply = await click(3, "t:VND:asia")
    assert reply.region == "asia" and reply.selected[-1] == "VND"
    assert "Вьетнамский донг" in reply.text
    repeated = await click(3, "t:VND:asia")
    assert repeated.selected == reply.selected and repeated.region == "asia"
    blocked = await click(4, "t:JPY:asia")
    assert blocked.action == "alert" and blocked.text == TOO_MANY
    home = await click(5, "g:home")
    assert home.region == "home" and home.selected == reply.selected
    assert (await click(5, "g:home")).selected == home.selected
    done = await click(6, "ok")
    assert done.action == "close_picker" and "VND" in done.text
    assert book.primary_calls == 0


async def test_invalid_region_and_last_currency_leave_settings_unchanged():
    store = MemoryStore()
    await store.create_user(5, "initial")
    await store.save_currencies(5, ("VND",), "initial", "single")
    book = CountingBook()
    flow = Flow(store, RateBook(book.primary, book.fallback))
    for index, data in enumerate(("g:unknown", "t:USD:unknown", "t:USD:asia:extra")):
        reply = await flow.handle_callback(user_id=5, chat_type="private", update_id=index, data=data, now=NOW)
        assert reply.action == "ack"
    last = await flow.handle_callback(user_id=5, chat_type="private", update_id=4, data="t:VND:asia", now=NOW)
    assert last.action == "alert" and last.text == LAST_ONE
    assert (await store.get_user(5)).currencies == ("VND",)


async def test_delivery_builds_keyboard_for_requested_region():
    store = MemoryStore()
    await store.create_user(5, "initial")
    book = CountingBook()
    flow = Flow(store, RateBook(book.primary, book.fallback))
    bot = AsyncMock()
    assert await consume(flow, TelegramOutbox(bot), _callback(1, "g:asia"), NOW)
    markup = bot.edit_message_text.call_args.kwargs["reply_markup"]
    assert "t:VND:asia" in {b.callback_data for b in buttons(markup)}
    bot.answer_callback_query.assert_awaited_once()
    reply = await flow.handle_text(user_id=5, chat_type="private", update_id=2, text="/set_currencies", now=NOW)
    await present(TelegramOutbox(bot), reply, chat_id=5, message_id=None, callback_id=None)
    markup = bot.send_message.call_args.kwargs["reply_markup"]
    assert "g:asia" in {b.callback_data for b in buttons(markup)}
