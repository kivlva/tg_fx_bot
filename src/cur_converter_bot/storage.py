"""Настройки пользователя, снимок курсов и обработанные update_id."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from cur_converter_bot.catalog import DEFAULT_CURRENCIES, toggle
from cur_converter_bot.rates import FxSnapshot


@dataclass(frozen=True)
class UserSettings:
    user_id: int
    currencies: tuple[str, ...]
    updated_at: str


class Store(Protocol):
    async def get_user(self, user_id: int) -> UserSettings | None: ...

    async def create_user(self, user_id: int, updated_at: str) -> UserSettings: ...

    async def save_currencies(
        self,
        user_id: int,
        currencies: tuple[str, ...],
        expected_updated_at: str,
        updated_at: str,
    ) -> UserSettings | None: ...

    async def toggle_currency(
        self, user_id: int, code: str, update_id: int, updated_at: str
    ) -> tuple[UserSettings | None, str]: ...

    async def get_snapshot(self) -> FxSnapshot | None: ...

    async def save_snapshot(self, snapshot: FxSnapshot) -> None: ...

    async def claim_update(self, update_id: int) -> bool: ...

    async def release_update(self, update_id: int) -> None: ...


def _encode_currencies(currencies: tuple[str, ...]) -> str:
    return ",".join(currencies)


def _decode_currencies(raw: str) -> tuple[str, ...]:
    return tuple(part for part in raw.split(",") if part)


class MemoryStore:
    def __init__(self) -> None:
        self._users: dict[int, UserSettings] = {}
        self._snapshot: FxSnapshot | None = None
        self._updates: set[int] = set()
        self._lock = asyncio.Lock()

    async def get_user(self, user_id: int) -> UserSettings | None:
        async with self._lock:
            return self._users.get(user_id)

    async def create_user(self, user_id: int, updated_at: str) -> UserSettings:
        async with self._lock:
            existing = self._users.get(user_id)
            if existing is not None:
                return existing
            created = UserSettings(user_id, DEFAULT_CURRENCIES, updated_at)
            self._users[user_id] = created
            return created

    async def save_currencies(
        self,
        user_id: int,
        currencies: tuple[str, ...],
        expected_updated_at: str,
        updated_at: str,
    ) -> UserSettings | None:
        async with self._lock:
            current = self._users.get(user_id)
            if current is None or current.updated_at != expected_updated_at:
                return None
            saved = UserSettings(user_id, currencies, updated_at)
            self._users[user_id] = saved
            return saved

    async def toggle_currency(self, user_id, code, update_id, updated_at):
        async with self._lock:
            current = self._users.get(user_id)
            if update_id in self._updates:
                return current, "duplicate"
            if current is None:
                return None, "missing"
            result = toggle(current.currencies, code)
            saved = UserSettings(user_id, result.currencies, updated_at)
            self._users[user_id] = saved
            self._updates.add(update_id)
            return saved, result.status

    async def get_snapshot(self) -> FxSnapshot | None:
        async with self._lock:
            return self._snapshot

    async def save_snapshot(self, snapshot: FxSnapshot) -> None:
        async with self._lock:
            self._snapshot = snapshot

    async def claim_update(self, update_id: int) -> bool:
        async with self._lock:
            if update_id in self._updates:
                return False
            self._updates.add(update_id)
            return True

    async def release_update(self, update_id: int) -> None:
        async with self._lock:
            self._updates.discard(update_id)


def _snapshot_to_row(snapshot: FxSnapshot) -> str:
    pairs = ",".join(f"{code}:{snapshot.per_usd[code]}" for code in sorted(snapshot.per_usd))
    fetched = snapshot.fetched_at.isoformat()
    return f"{snapshot.source}|{snapshot.rate_date}|{fetched}|{pairs}"


def _snapshot_from_row(raw: str) -> FxSnapshot:
    source, rate_date, fetched, pairs = raw.split("|", 3)
    per_usd = {}
    for item in pairs.split(","):
        code, value = item.split(":", 1)
        per_usd[code] = Decimal(value)
    return FxSnapshot(
        per_usd,
        rate_date,
        datetime.fromisoformat(fetched),
        source,  # type: ignore[arg-type]
    )


class YdbStore:
    """То же хранилище в YDB Serverless. SDK импортируется только при создании."""

    def __init__(self, endpoint: str, database: str) -> None:
        import ydb

        # В Serverless Containers ключ сервисного аккаунта приходит из metadata.
        credentials = ydb.iam.MetadataUrlCredentials()
        driver = ydb.Driver(endpoint=endpoint, database=database, credentials=credentials)
        driver.wait(fail_fast=True, timeout=10)
        self._ydb = ydb
        self._database = database
        self._pool = ydb.SessionPool(driver)

    def ensure_schema(self) -> None:
        descriptions = (
            ("user_settings", ("user_id",), (
                ("user_id", self._ydb.PrimitiveType.Int64),
                ("currencies", self._ydb.PrimitiveType.Utf8),
                ("updated_at", self._ydb.PrimitiveType.Utf8),
            )),
            ("fx_snapshot", ("id",), (
                ("id", self._ydb.PrimitiveType.Utf8),
                ("payload", self._ydb.PrimitiveType.Utf8),
            )),
            ("processed_updates", ("update_id",), (
                ("update_id", self._ydb.PrimitiveType.Int64),
            )),
        )

        def callee(session) -> None:
            for name, keys, columns in descriptions:
                description = self._ydb.TableDescription().with_primary_keys(*keys)
                for column_name, column_type in columns:
                    description = description.with_column(
                        self._ydb.Column(column_name, column_type)
                    )
                try:
                    session.create_table(f"{self._database.rstrip('/')}/{name}", description)
                except (self._ydb.SchemeError, self._ydb.AlreadyExists):
                    session.describe_table(f"{self._database.rstrip('/')}/{name}")

        self._pool.retry_operation_sync(callee)

    def _execute(self, query: str, params: dict):
        def callee(session):
            return session.transaction().execute(session.prepare(query), params, commit_tx=True)

        return self._pool.retry_operation_sync(callee)

    async def get_user(self, user_id: int) -> UserSettings | None:
        return await asyncio.to_thread(self._get_user, user_id)

    def _get_user(self, user_id: int) -> UserSettings | None:
        result = self._execute(
            """
            DECLARE $user_id AS Int64;
            SELECT currencies, updated_at FROM user_settings WHERE user_id = $user_id;
            """,
            {"$user_id": user_id},
        )
        rows = result[0].rows
        if not rows:
            return None
        return UserSettings(user_id, _decode_currencies(rows[0].currencies), rows[0].updated_at)

    async def create_user(self, user_id: int, updated_at: str) -> UserSettings:
        return await asyncio.to_thread(self._create_user, user_id, updated_at)

    def _create_user(self, user_id: int, updated_at: str) -> UserSettings:
        existing = self._get_user(user_id)
        if existing is not None:
            return existing
        currencies = _encode_currencies(DEFAULT_CURRENCIES)
        try:
            self._execute(
                """
                DECLARE $user_id AS Int64;
                DECLARE $currencies AS Utf8;
                DECLARE $updated_at AS Utf8;
                INSERT INTO user_settings (user_id, currencies, updated_at)
                VALUES ($user_id, $currencies, $updated_at);
                """,
                {
                    "$user_id": user_id,
                    "$currencies": currencies,
                    "$updated_at": updated_at,
                },
            )
        except self._ydb.Error:
            existing = self._get_user(user_id)
            if existing is not None:
                return existing
            raise
        return UserSettings(user_id, DEFAULT_CURRENCIES, updated_at)

    async def save_currencies(
        self,
        user_id: int,
        currencies: tuple[str, ...],
        expected_updated_at: str,
        updated_at: str,
    ) -> UserSettings | None:
        return await asyncio.to_thread(
            self._save_currencies,
            user_id,
            currencies,
            expected_updated_at,
            updated_at,
        )

    def _save_currencies(
        self,
        user_id: int,
        currencies: tuple[str, ...],
        expected_updated_at: str,
        updated_at: str,
    ) -> UserSettings | None:
        def callee(session):
            tx = session.transaction(self._ydb.SerializableReadWrite())
            selected = tx.execute(session.prepare(
                """
                DECLARE $user_id AS Int64;
                SELECT updated_at FROM user_settings WHERE user_id = $user_id;
                """),
                {"$user_id": user_id},
            )
            rows = selected[0].rows
            if not rows or rows[0].updated_at != expected_updated_at:
                tx.rollback()
                return None
            tx.execute(session.prepare(
                """
                DECLARE $user_id AS Int64;
                DECLARE $currencies AS Utf8;
                DECLARE $updated_at AS Utf8;
                UPDATE user_settings
                SET currencies = $currencies, updated_at = $updated_at
                WHERE user_id = $user_id;
                """),
                {
                    "$user_id": user_id,
                    "$currencies": _encode_currencies(currencies),
                    "$updated_at": updated_at,
                },
            )
            tx.commit()
            return UserSettings(user_id, currencies, updated_at)

        return self._pool.retry_operation_sync(callee)

    async def toggle_currency(self, user_id, code, update_id, updated_at):
        return await asyncio.to_thread(
            self._toggle_currency, user_id, code, update_id, updated_at
        )

    def _toggle_currency(self, user_id, code, update_id, updated_at):
        def callee(session):
            tx = session.transaction(self._ydb.SerializableReadWrite())
            result = tx.execute(session.prepare(
                """
                DECLARE $user_id AS Int64;
                DECLARE $update_id AS Int64;
                SELECT currencies, updated_at FROM user_settings WHERE user_id = $user_id;
                SELECT update_id FROM processed_updates WHERE update_id = $update_id;
                """),
                {"$user_id": user_id, "$update_id": update_id},
            )
            rows = result[0].rows
            current = (UserSettings(user_id, _decode_currencies(rows[0].currencies),
                                    rows[0].updated_at) if rows else None)
            if result[1].rows or current is None:
                tx.rollback()
                return current, "duplicate" if result[1].rows else "missing"
            changed = toggle(current.currencies, code)
            tx.execute(session.prepare(
                """
                DECLARE $user_id AS Int64;
                DECLARE $update_id AS Int64;
                DECLARE $currencies AS Utf8;
                DECLARE $updated_at AS Utf8;
                UPDATE user_settings SET currencies = $currencies, updated_at = $updated_at
                WHERE user_id = $user_id;
                INSERT INTO processed_updates (update_id) VALUES ($update_id);
                """),
                {"$user_id": user_id, "$update_id": update_id,
                 "$currencies": _encode_currencies(changed.currencies),
                 "$updated_at": updated_at},
            )
            tx.commit()
            return UserSettings(user_id, changed.currencies, updated_at), changed.status
        return self._pool.retry_operation_sync(callee)

    async def get_snapshot(self) -> FxSnapshot | None:
        return await asyncio.to_thread(self._get_snapshot)

    def _get_snapshot(self) -> FxSnapshot | None:
        result = self._execute(
            """
            DECLARE $id AS Utf8;
            SELECT payload FROM fx_snapshot WHERE id = $id;
            """,
            {"$id": "current"},
        )
        rows = result[0].rows
        if not rows:
            return None
        return _snapshot_from_row(rows[0].payload)

    async def save_snapshot(self, snapshot: FxSnapshot) -> None:
        await asyncio.to_thread(self._save_snapshot, snapshot)

    def _save_snapshot(self, snapshot: FxSnapshot) -> None:
        self._execute(
            """
            DECLARE $id AS Utf8;
            DECLARE $payload AS Utf8;
            UPSERT INTO fx_snapshot (id, payload) VALUES ($id, $payload);
            """,
            {"$id": "current", "$payload": _snapshot_to_row(snapshot)},
        )

    async def claim_update(self, update_id: int) -> bool:
        return await asyncio.to_thread(self._claim_update, update_id)

    def _claim_update(self, update_id: int) -> bool:
        def callee(session):
            tx = session.transaction(self._ydb.SerializableReadWrite())
            found = tx.execute(session.prepare(
                """
                DECLARE $update_id AS Int64;
                SELECT update_id FROM processed_updates WHERE update_id = $update_id;
                """),
                {"$update_id": update_id},
            )
            if found[0].rows:
                tx.rollback()
                return False
            tx.execute(session.prepare(
                """
                DECLARE $update_id AS Int64;
                INSERT INTO processed_updates (update_id) VALUES ($update_id);
                """),
                {"$update_id": update_id},
            )
            tx.commit()
            return True

        return self._pool.retry_operation_sync(callee)

    async def release_update(self, update_id: int) -> None:
        await asyncio.to_thread(self._release_update, update_id)

    def _release_update(self, update_id: int) -> None:
        self._execute(
            """
            DECLARE $update_id AS Int64;
            DELETE FROM processed_updates WHERE update_id = $update_id;
            """,
            {"$update_id": update_id},
        )
