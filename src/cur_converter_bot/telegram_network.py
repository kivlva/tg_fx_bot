"""Resolve Telegram through independent DNS sources and verify reachable TLS routes."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
import ssl
import time
import urllib.request
from contextlib import suppress

import aiohttp
import certifi
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError

HOST = "api.telegram.org"
DOH = ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query")
logger = logging.getLogger(__name__)


def public_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and address.is_global
    except ValueError:
        return False


def doh_addresses(url: str) -> tuple[list[str], int]:
    request = urllib.request.Request(
        f"{url}?name={HOST}&type=A", headers={"Accept": "application/dns-json"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=3) as response:
        payload = json.loads(response.read(65536))
    if payload.get("Status") != 0:
        raise ValueError("DNS response failed")
    answers = [a for a in payload.get("Answer", [])
               if a.get("type") == 1 and public_ipv4(a.get("data", ""))]
    return [a["data"] for a in answers], min([int(a.get("TTL", 60)) for a in answers] or [60])


class FixedAddressResolver(AbstractResolver):
    def __init__(self, address):
        self.address = address

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [dict(hostname=host, host=self.address, port=port, family=socket.AF_INET,
                     proto=socket.IPPROTO_TCP, flags=socket.AI_NUMERICHOST)]

    async def close(self):
        pass


async def tls_available(address: str) -> bool:
    connector = aiohttp.TCPConnector(
        resolver=FixedAddressResolver(address), use_dns_cache=False,
        ssl=ssl.create_default_context(cafile=certifi.where()),
    )
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=4)) as client:
            async with client.head(f"https://{HOST}", allow_redirects=False) as response:
                return 200 <= response.status < 400
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False


class TelegramResolver(AbstractResolver):
    def __init__(self, fallback_ips: tuple[str, ...] = ()):
        if any(not public_ipv4(ip) for ip in fallback_ips) or len(fallback_ips) > 4:
            raise ValueError("TELEGRAM_FALLBACK_IPS must contain at most 4 public IPv4 addresses")
        self._fallback = fallback_ips
        self._system = DefaultResolver()
        self._lock = asyncio.Lock()
        self._addresses: list[str] = []
        self._expires = 0.0
        self._closed = False
        self._force_refresh = True
        self._refresh_task = None

    def invalidate(self):
        self._expires = 0.0
        self._force_refresh = True
        if self._refresh_task is not None:
            self._refresh_task.cancel()

    async def _discover(self):
        async def system():
            records = await asyncio.wait_for(self._system.resolve(HOST, 443, socket.AF_INET), 3)
            return [r["host"] for r in records if public_ipv4(r["host"])], 60

        results = await asyncio.gather(
            system(), *(asyncio.to_thread(doh_addresses, url) for url in DOH),
            return_exceptions=True,
        )
        addresses, ttl = [], 60
        for source, result in zip(("system", "Google", "Cloudflare"), results):
            if isinstance(result, Exception):
                logger.warning("Telegram DNS source %s failed: %s", source, type(result).__name__)
                continue
            found, source_ttl = result
            logger.info("Telegram DNS %s: %s", source, ", ".join(found) or "no IPv4")
            addresses.extend(found)
            ttl = min(ttl, max(1, source_ttl))
        # Retain previously verified routes during temporary DNS outages, but recheck TLS.
        addresses = list(dict.fromkeys(addresses))[:8]
        addresses = list(dict.fromkeys(addresses + self._addresses[:2] + list(self._fallback)))[:14]
        return addresses, ttl

    async def _refresh(self):
        candidates, ttl = await self._discover()
        available = await asyncio.gather(*(tls_available(ip) for ip in candidates))
        working = [ip for ip, ok in zip(candidates, available) if ok]
        for ip, ok in zip(candidates, available):
            logger.info("Telegram HTTPS route %s: %s", ip, "available" if ok else "unavailable")
        if not working:
            raise OSError("No verified HTTPS route to Telegram")
        self._addresses = working
        self._expires = time.monotonic() + ttl
        self._force_refresh = False

    async def _background_refresh(self):
        try:
            async with self._lock:
                if not self._closed:
                    await self._refresh()
        except asyncio.CancelledError:
            return
        except Exception as error:
            self._expires = time.monotonic() + 15
            logger.warning("Telegram background route check failed: %s", type(error).__name__)

    def _records(self, host, port):
        return [dict(hostname=host, host=ip, port=port, family=socket.AF_INET,
                     proto=socket.IPPROTO_TCP, flags=socket.AI_NUMERICHOST)
                for ip in self._addresses]

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if self._closed:
            raise OSError("Telegram resolver is closed")
        if host != HOST:
            return await self._system.resolve(host, port, family)
        # Keep working requests independent of periodic DNS/probe timeouts.
        if self._addresses and not self._force_refresh:
            if time.monotonic() >= self._expires:
                if self._refresh_task is None or self._refresh_task.done():
                    self._refresh_task = asyncio.create_task(self._background_refresh())
            return self._records(host, port)
        async with self._lock:
            if self._closed:
                raise OSError("Telegram resolver is closed")
            if self._force_refresh or not self._addresses:
                await self._refresh()
            return self._records(host, port)

    async def close(self):
        self._closed = True
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._refresh_task
        await self._system.close()


class ResilientTelegramSession(AiohttpSession):
    def __init__(self, fallback_ips: tuple[str, ...] = (), **kwargs):
        super().__init__(**kwargs)
        self._telegram_resolver = TelegramResolver(fallback_ips)
        self._connector_init.update(resolver=self._telegram_resolver, use_dns_cache=False)

    async def create_session(self):
        if self._should_reset_connector:
            await super().close()
            self._should_reset_connector = False
        return await super().create_session()

    async def make_request(self, bot, method, timeout=None):
        try:
            return await super().make_request(bot, method, timeout)
        except TelegramNetworkError:
            self._telegram_resolver.invalidate()
            # Reset connections for the next request; never replay an uncertain send.
            await super().close()
            self._should_reset_connector = True
            raise

    async def close(self):
        await super().close()
        await self._telegram_resolver.close()


def build_telegram_session():
    if os.environ.get("TELEGRAM_RESILIENT_DNS", "0") != "1":
        return AiohttpSession()
    fallback = tuple(ip.strip() for ip in os.environ.get("TELEGRAM_FALLBACK_IPS", "").split(",") if ip.strip())
    return ResilientTelegramSession(fallback)
