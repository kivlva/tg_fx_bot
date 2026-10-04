import socket
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe

from cur_converter_bot import telegram_network as network

BAD = "149.154.166.110"
GOOD = "149.154.167.220"


@pytest.fixture
async def routes(monkeypatch):
    resolver = network.TelegramResolver((GOOD,))
    resolver._system.resolve = AsyncMock(return_value=[{"host": BAD}])
    monkeypatch.setattr(network, "doh_addresses", lambda url: ([BAD], 60))
    probe = AsyncMock(side_effect=lambda ip: ip == GOOD)
    monkeypatch.setattr(network, "tls_available", probe)
    yield resolver, probe
    await resolver.close()


async def test_unreachable_dns_address_uses_tls_verified_fallback(routes):
    resolver, probe = routes
    result = await resolver.resolve(network.HOST, 443)
    assert [r["host"] for r in result] == [GOOD]
    assert result[0]["hostname"] == network.HOST
    assert result[0]["family"] == socket.AF_INET
    assert probe.await_count == 2  # duplicate DNS answers are probed once


async def test_dns_recovers_without_restart(routes):
    resolver, probe = routes
    await resolver.resolve(network.HOST, 443)
    resolver.invalidate()
    probe.side_effect = lambda ip: ip == BAD
    result = await resolver.resolve(network.HOST, 443)
    assert [r["host"] for r in result] == [BAD]


async def test_fallback_not_used_without_successful_tls(routes):
    resolver, probe = routes
    probe.side_effect = None
    probe.return_value = False
    with pytest.raises(OSError, match="No verified"):
        await resolver.resolve(network.HOST, 443)


async def test_verified_cache_avoids_probe_per_request(routes):
    resolver, probe = routes
    await resolver.resolve(network.HOST, 443)
    await resolver.resolve(network.HOST, 443)
    assert probe.await_count == 2


async def test_all_dns_sources_fail_but_verified_fallback_works(routes, monkeypatch):
    resolver, probe = routes
    resolver._system.resolve.side_effect = OSError("DNS down")
    def unavailable(url):
        raise TimeoutError()
    monkeypatch.setattr(network, "doh_addresses", unavailable)
    assert (await resolver.resolve(network.HOST, 443))[0]["host"] == GOOD


async def test_non_telegram_hosts_use_system_resolver(routes):
    resolver, probe = routes
    result = await resolver.resolve("example.com", 80)
    assert result == [{"host": BAD}]
    probe.assert_not_awaited()


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "not-an-ip", "::1"])
async def test_private_or_invalid_fallback_rejected(ip):
    with pytest.raises(ValueError):
        network.TelegramResolver((ip,))


async def test_session_creation_does_not_close_resolver():
    session = network.ResilientTelegramSession((GOOD,))
    try:
        client = await session.create_session()
        assert not session._telegram_resolver._closed
        assert client.connector._resolver is session._telegram_resolver
        assert not client.connector.use_dns_cache
    finally:
        await session.close()
    assert session._telegram_resolver._closed


async def test_network_failure_refreshes_routes_without_replaying_method(monkeypatch):
    session = network.ResilientTelegramSession((GOOD,))
    request = AsyncMock(side_effect=TelegramNetworkError(method=GetMe(), message="timeout"))
    monkeypatch.setattr(network.AiohttpSession, "make_request", request)
    session._telegram_resolver._expires = float("inf")
    try:
        with pytest.raises(TelegramNetworkError):
            await session.make_request(None, GetMe())
        request.assert_awaited_once()
        assert session._telegram_resolver._expires == 0
        assert session._should_reset_connector
        await session.create_session()
        assert not session._telegram_resolver._closed
    finally:
        await session.close()


async def test_http_client_connects_to_resolver_address_without_hosts_override(routes):
    import aiohttp
    resolver, probe = routes

    async def respond(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    resolver._discover = AsyncMock(return_value=(["127.0.0.1"], 60))
    probe.side_effect = None
    probe.return_value = True
    server = await __import__('asyncio').start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)) as client:
            async with client.get(f"http://{network.HOST}:{port}", timeout=5) as response:
                assert await response.text() == "ok"
    finally:
        server.close()
        await server.wait_closed()


async def test_expired_routes_return_immediately_while_refresh_waits(routes):
    import asyncio
    resolver, probe = routes
    await resolver.resolve(network.HOST, 443)
    gate = asyncio.Event()
    started = asyncio.Event()

    async def slow_discovery():
        started.set()
        await gate.wait()
        return [BAD], 60

    resolver._discover = slow_discovery
    probe.side_effect = lambda ip: ip == BAD
    resolver._expires = 0
    result = await asyncio.wait_for(resolver.resolve(network.HOST, 443), timeout=0.5)
    assert result[0]["host"] == GOOD
    await asyncio.wait_for(started.wait(), timeout=1)
    # Even a caller arriving during the background lock must not wait.
    again = await asyncio.wait_for(resolver.resolve(network.HOST, 443), timeout=0.5)
    assert again[0]["host"] == GOOD
    task = resolver._refresh_task
    gate.set()
    await task
    assert (await resolver.resolve(network.HOST, 443))[0]["host"] == BAD


async def test_failed_background_probe_retains_route_but_network_error_forces_check(routes):
    resolver, probe = routes
    await resolver.resolve(network.HOST, 443)
    probe.side_effect = None
    probe.return_value = False
    resolver._expires = 0
    assert (await resolver.resolve(network.HOST, 443))[0]["host"] == GOOD
    await resolver._refresh_task
    assert resolver._addresses == [GOOD]
    resolver.invalidate()
    with pytest.raises(OSError, match="No verified"):
        await resolver.resolve(network.HOST, 443)


async def test_closing_resolver_cancels_background_discovery(routes):
    import asyncio
    resolver, probe = routes
    await resolver.resolve(network.HOST, 443)
    started = asyncio.Event()

    async def blocked():
        started.set()
        await asyncio.Event().wait()

    resolver._discover = blocked
    resolver._expires = 0
    await resolver.resolve(network.HOST, 443)
    await started.wait()
    task = resolver._refresh_task
    await resolver.close()
    assert task.done()
