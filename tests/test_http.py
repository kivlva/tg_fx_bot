from aiohttp.test_utils import TestClient, TestServer

from cur_converter_bot.delivery import create_app
from cur_converter_bot.flow import Flow
from cur_converter_bot.rates import RateBook
from cur_converter_bot.storage import MemoryStore
from tests.helpers import NOW, CountingBook


class RecordingOutbox:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, bool]] = []
        self.edits: list[tuple[str, ...]] = []
        self.callbacks: list[tuple[str, str, bool]] = []

    async def send(self, chat_id: int, text: str, *, reply_keyboard: bool) -> None:
        self.sent.append((chat_id, text, reply_keyboard))

    async def send_picker(self, chat_id: int, text: str, selected: tuple[str, ...], *, region: str = "home") -> None:
        self.sent.append((chat_id, text, False))

    async def edit_picker(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        selected: tuple[str, ...],
        *,
        region: str = "home",
    ) -> None:
        self.edits.append(selected)

    async def close_picker(self, chat_id: int, message_id: int, text: str) -> None:
        self.sent.append((chat_id, text, False))

    async def answer_callback(self, callback_id: str, text: str, *, show_alert: bool) -> None:
        self.callbacks.append((callback_id, text, show_alert))


def _message(update_id: int, text: str, chat_type: str = "private", *, sender_key: str = "from") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "text": text,
            sender_key: {"id": 5},
            "chat": {"id": 5, "type": chat_type},
        },
    }


def _callback(update_id: int, data: str, *, sender_key: str = "from") -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb-{update_id}",
            "data": data,
            sender_key: {"id": 5},
            "message": {
                "message_id": 10,
                "chat": {"id": 5, "type": "private"},
            },
        },
    }


async def test_http_accepts_update_and_ignores_duplicate_toggle():
    store = MemoryStore()
    book = CountingBook()
    outbox = RecordingOutbox()
    app = create_app(Flow(store, RateBook(book.primary, book.fallback)), outbox, lambda: NOW)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        started = await client.post("/telegram", json=_message(1, "/start"))
        assert started.status == 200
        assert outbox.sent[0][2] is True

        first = await client.post("/telegram", json=_callback(2, "t:THB"))
        assert first.status == 200
        assert outbox.edits[-1] == ("USD", "LKR", "RUB", "EUR")

        second = await client.post("/telegram", json=_callback(2, "t:THB"))
        assert second.status == 200
        user = await store.get_user(5)
        assert user is not None
        assert user.currencies == ("USD", "LKR", "RUB", "EUR")
        assert outbox.callbacks[-1][1] == ""

        bad = await client.post("/telegram", data="not-json")
        assert bad.status == 400
        empty = await client.post("/telegram", json={})
        assert empty.status == 400
    finally:
        await client.close()


async def test_failed_send_can_be_retried():
    store = MemoryStore()
    book = CountingBook()
    outbox = RecordingOutbox()

    calls = 0

    async def fail_once(chat_id: int, text: str, *, reply_keyboard: bool) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("send failed")
        outbox.sent.append((chat_id, text, reply_keyboard))

    outbox.send = fail_once  # type: ignore[method-assign]
    app = create_app(Flow(store, RateBook(book.primary, book.fallback)), outbox, lambda: NOW)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        first = await client.post("/telegram", json=_message(1, "/start"))
        assert first.status == 500
        second = await client.post("/telegram", json=_message(1, "/start"))
        assert second.status == 200
        assert outbox.sent[0][2] is True
    finally:
        await client.close()


async def test_aiogram_sender_field_still_starts_the_bot():
    store = MemoryStore()
    book = CountingBook()
    outbox = RecordingOutbox()
    app = create_app(Flow(store, RateBook(book.primary, book.fallback)), outbox, lambda: NOW)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.post(
            "/telegram",
            json=_message(1, "/start", sender_key="from_user"),
        )
        assert response.status == 200
        assert outbox.sent
        assert "конвертер" in outbox.sent[0][1]
    finally:
        await client.close()


async def test_aiogram_sender_field_toggles_currency_once():
    store = MemoryStore()
    book = CountingBook()
    outbox = RecordingOutbox()
    app = create_app(Flow(store, RateBook(book.primary, book.fallback)), outbox, lambda: NOW)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        started = await client.post(
            "/telegram",
            json=_message(1, "/start", sender_key="from_user"),
        )
        assert started.status == 200

        first = await client.post(
            "/telegram",
            json=_callback(2, "t:THB", sender_key="from_user"),
        )
        assert first.status == 200
        assert outbox.edits[-1] == ("USD", "LKR", "RUB", "EUR")

        second = await client.post(
            "/telegram",
            json=_callback(2, "t:THB", sender_key="from_user"),
        )
        assert second.status == 200
        user = await store.get_user(5)
        assert user is not None
        assert user.currencies == ("USD", "LKR", "RUB", "EUR")
    finally:
        await client.close()
