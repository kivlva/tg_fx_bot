import base64
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SetMyCommands

from cur_converter_bot import function
from cur_converter_bot.rates import RateBook
from cur_converter_bot.storage import MemoryStore
from tests.helpers import CountingBook
from tests.test_http import RecordingOutbox, _message, _callback


@pytest.fixture
def function_env(monkeypatch):
    store = MemoryStore()
    outbox = RecordingOutbox()
    book = CountingBook()
    bot = AsyncMock()
    bot.__aenter__.return_value = bot
    monkeypatch.setenv("BOT_TOKEN", "123456:FAKE_TEST_TOKEN")
    monkeypatch.setattr(function, "_store", None)
    monkeypatch.setattr(function, "_menu_configured", False)
    monkeypatch.setattr(function, "_get_store", lambda: store)
    monkeypatch.setattr(function, "Bot", lambda *args, **kwargs: bot)
    monkeypatch.setattr(function, "TelegramOutbox", lambda bot: outbox)
    monkeypatch.setattr(function, "set_command_menu", AsyncMock())
    monkeypatch.setattr(function, "build_rates", lambda: RateBook(book.primary, book.fallback))
    return store, outbox, bot


async def test_function_start_select_convert_and_duplicate(function_env):
    store, outbox, bot = function_env
    assert (await function.handler(_message(1, "/start"), None))["statusCode"] == 200
    await function.handler(_callback(2, "t:THB:asia"), None)
    await function.handler(_callback(3, "t:VND:asia"), None)
    selected = (await store.get_user(5)).currencies
    assert selected[-1] == "VND"
    await function.handler(_callback(3, "t:VND:asia"), None)
    assert (await store.get_user(5)).currencies == selected
    await function.handler(_message(4, "1 usd"), None)
    assert "VND" in outbox.sent[-1][1]
    assert bot.__aexit__.await_count == 5
    function.set_command_menu.assert_awaited_once()


@pytest.mark.parametrize("encoded", [False, True])
async def test_function_accepts_http_body(function_env, encoded):
    body = json.dumps(_message(1, "/start"))
    if encoded:
        body = base64.b64encode(body.encode()).decode()
    result = await function.handler({"httpMethod": "POST", "body": body, "isBase64Encoded": encoded}, None)
    assert result["statusCode"] == 200
    assert function_env[1].sent


@pytest.mark.parametrize("event", [None, {}, {"update_id": True}, {"httpMethod": "POST", "body": "bad"},
                                  {"httpMethod": "POST", "body": "***", "isBase64Encoded": True}])
async def test_invalid_function_event_fails_before_opening_session(function_env, event):
    with pytest.raises(ValueError):
        await function.handler(event, None)
    function_env[2].__aenter__.assert_not_awaited()


async def test_function_delivery_failure_propagates_and_retry_succeeds(function_env):
    store, outbox, bot = function_env
    outbox.send = AsyncMock(side_effect=[RuntimeError("temporary delivery failure"), None])
    with pytest.raises(RuntimeError):
        await function.handler(_message(1, "/start"), None)
    assert (await function.handler(_message(1, "/start"), None))["statusCode"] == 200
    assert outbox.send.await_count == 2
    assert bot.__aexit__.await_count == 2


async def test_function_menu_timeout_does_not_drop_update(function_env, monkeypatch):
    monkeypatch.setattr(function, "set_command_menu", AsyncMock(side_effect=TelegramNetworkError(
        method=SetMyCommands(commands=[]), message="timeout")))
    await function.handler(_message(1, "/start"), None)
    assert function_env[1].sent
    assert function._menu_configured is False


def test_function_initializes_persistent_store_once(monkeypatch):
    store = object()
    create = Mock(return_value=store)
    monkeypatch.setattr(function, "_store", None)
    monkeypatch.setattr(function, "build_store", create)
    monkeypatch.setenv("YDB_ENDPOINT", "endpoint")
    monkeypatch.setenv("YDB_DATABASE", "/database")
    assert function._get_store() is store
    assert function._get_store() is store
    create.assert_called_once()


def test_function_refuses_memory_store_without_ydb(monkeypatch):
    monkeypatch.setattr(function, "_store", None)
    monkeypatch.delenv("YDB_ENDPOINT", raising=False)
    monkeypatch.delenv("YDB_DATABASE", raising=False)
    with pytest.raises(RuntimeError, match="requires YDB"):
        function._get_store()


def test_function_zip_contains_only_code_and_dependencies(tmp_path):
    project = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location("package_function", project / "deploy/package_function.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "function.zip"
    module.package(project, output)
    with ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {"index.py", "requirements.txt", "cur_converter_bot/function.py"} <= names
        assert all(name.endswith(".py") or name == "requirements.txt" for name in names)
        assert not any(".env" in name or "tests/" in name or "__pycache__" in name for name in names)
        requirements = archive.read("requirements.txt").decode()
        assert "aiogram" in requirements and "ydb" in requirements and "pytest" not in requirements
