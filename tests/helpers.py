from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cur_converter_bot.catalog import CODES
from cur_converter_bot.rates import FxSnapshot

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)


def sample_rates() -> dict[str, Decimal]:
    per_usd = {code: Decimal(1) for code in CODES}
    per_usd["LKR"] = Decimal(300)
    per_usd["RUB"] = Decimal(90)
    per_usd["EUR"] = Decimal("0.9")
    per_usd["THB"] = Decimal(35)
    return per_usd


def snapshot(fetched_at: datetime | None = None, source: str = "frankfurter") -> FxSnapshot:
    return FxSnapshot(sample_rates(), "2026-10-03", fetched_at or NOW, source)  # type: ignore[arg-type]


class CountingBook:
    def __init__(self, primary_result=None, fallback_result=None, primary_error=None, fallback_error=None):
        self.primary_calls = 0
        self.fallback_calls = 0
        self._primary_result = primary_result
        self._fallback_result = fallback_result
        self._primary_error = primary_error
        self._fallback_error = fallback_error

    async def primary(self, now: datetime) -> FxSnapshot:
        self.primary_calls += 1
        if self._primary_error is not None:
            raise self._primary_error
        result = self._primary_result
        if result is None:
            result = snapshot(now)
        return result

    async def fallback(self, now: datetime) -> FxSnapshot:
        self.fallback_calls += 1
        if self._fallback_error is not None:
            raise self._fallback_error
        result = self._fallback_result
        if result is None:
            result = snapshot(now, "fallback")
        return result


STALE = NOW - timedelta(hours=7)
