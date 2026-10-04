import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import ydb
from aiohttp.test_utils import TestClient, TestServer

from cur_converter_bot.delivery import create_app
from cur_converter_bot.flow import Flow
from cur_converter_bot.rates import RateBook
from cur_converter_bot.storage import MemoryStore, YdbStore
from tests.helpers import NOW, CountingBook
from tests.test_http import RecordingOutbox, _message


spec = importlib.util.spec_from_file_location("ydb_connection", Path(__file__).parents[1] / "deploy/ydb_connection.py")
connection_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connection_module)


def test_yc_endpoint_is_split_into_sdk_endpoint_and_database():
    assert connection_module.connection({"endpoint": "grpcs://example:2135/?database=/ru-central1/cloud/db"}) == (
        "grpcs://example:2135", "/ru-central1/cloud/db"
    )
    assert connection_module.connection({"endpoint": "grpcs://example:2135", "database_path": "/cloud/db"}) == (
        "grpcs://example:2135", "/cloud/db"
    )


@pytest.mark.parametrize("data", [{}, {"endpoint": "grpcs://example:2135"}, {"endpoint": "http://example/?database=/db"}])
def test_incomplete_connection_is_rejected(data):
    with pytest.raises(ValueError):
        connection_module.connection(data)


def schema_store(session):
    store = object.__new__(YdbStore)
    store._ydb = ydb
    store._database = "/cloud/db"
    store._pool = SimpleNamespace(retry_operation_sync=lambda operation: operation(session))
    return store


def test_schema_uses_absolute_paths_and_confirms_existing_table():
    session = Mock()
    session.create_table.side_effect = ydb.SchemeError("already exists")
    schema_store(session).ensure_schema()
    assert [call.args[0] for call in session.create_table.call_args_list] == [
        "/cloud/db/user_settings", "/cloud/db/fx_snapshot", "/cloud/db/processed_updates"
    ]
    assert session.describe_table.call_count == 3


def test_schema_errors_are_not_silently_ignored():
    session = Mock()
    session.create_table.side_effect = ydb.SchemeError("failed")
    session.describe_table.side_effect = ydb.SchemeError("not found")
    with pytest.raises(ydb.SchemeError):
        schema_store(session).ensure_schema()


async def test_container_root_accepts_update_from_console_trigger():
    store = MemoryStore()
    book = CountingBook()
    outbox = RecordingOutbox()
    client = TestClient(TestServer(create_app(Flow(store, RateBook(book.primary, book.fallback)), outbox, lambda: NOW)))
    await client.start_server()
    try:
        response = await client.post("/", json=_message(1, "/start"))
        assert response.status == 200
        assert (await store.get_user(5)) is not None
        assert outbox.sent[0][2] is True
    finally:
        await client.close()
