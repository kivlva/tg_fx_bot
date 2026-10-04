"""Разбор суммы и текст конвертации."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from cur_converter_bot.catalog import (
    AMOUNT_HINT,
    CODE_SET,
    CURRENCY_HINT,
    FORMAT_HINT,
    RATES_CACHED,
    flag,
)

_INPUT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([A-Za-z]{3})$")
_CENT = Decimal("0.01")

ParseKind = Literal["format", "amount", "currency"]


@dataclass(frozen=True)
class AmountQuery:
    amount: Decimal
    code: str


@dataclass(frozen=True)
class ParseFailure:
    kind: ParseKind

    @property
    def text(self) -> str:
        if self.kind == "amount":
            return AMOUNT_HINT
        if self.kind == "currency":
            return CURRENCY_HINT
        return FORMAT_HINT


def parse_amount(text: str) -> AmountQuery | ParseFailure:
    match = _INPUT.fullmatch(text.strip())
    if match is None:
        return ParseFailure("format")
    numeric = match.group(1).replace(",", ".")
    if len(numeric.replace(".", "")) > 18:
        return ParseFailure("format")
    amount = Decimal(numeric)
    if amount <= 0:
        return ParseFailure("amount")
    code = match.group(2).upper()
    if code not in CODE_SET:
        return ParseFailure("currency")
    return AmountQuery(amount, code)


def format_amount(value: Decimal) -> str:
    quantized = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    return f"{quantized:,.2f}"


def cross_rate(amount: Decimal, source: str, target: str, per_usd: dict[str, Decimal]) -> Decimal:
    return amount * per_usd[target] / per_usd[source]


def conversion_text(
    amount: Decimal,
    source: str,
    selected: tuple[str, ...] | list[str],
    per_usd: dict[str, Decimal],
    *,
    cached: bool = False,
) -> str:
    lines = [f"💱 Конвертация {format_amount(amount)} {flag(source)} {source}:"]
    for code in selected:
        if code == source:
            shown = format_amount(amount)
            lines.append(f"• {shown} {flag(code)} {code} (без конвертации)")
            continue
        shown = format_amount(cross_rate(amount, source, code, per_usd))
        lines.append(f"• {shown} {flag(code)} {code}")
    if cached:
        lines.append(RATES_CACHED)
    return "\n".join(lines)
