from decimal import Decimal

from cur_converter_bot.catalog import CODES, DEFAULT_CURRENCIES, toggle
from cur_converter_bot.convert import conversion_text, format_amount, parse_amount


def test_catalog_has_thirty_one_codes_and_default_order():
    assert len(CODES) == 31
    assert CODES[14:17] == ("JPY", "KRW", "KZT")
    assert DEFAULT_CURRENCIES == ("USD", "LKR", "RUB", "EUR", "THB")


def test_parse_dot_comma_and_case():
    dotted = parse_amount("7.21 usd")
    comma = parse_amount("7,21 USD")
    compact = parse_amount("1000lkr")
    assert dotted.amount == Decimal("7.21") and dotted.code == "USD"
    assert comma.amount == Decimal("7.21") and comma.code == "USD"
    assert compact.amount == Decimal(1000) and compact.code == "LKR"


def test_parse_rejects_format_amount_and_unknown_code():
    assert parse_amount("привет").kind == "format"
    assert parse_amount("0 usd").kind == "amount"
    assert parse_amount("-5 usd").kind == "format"
    assert parse_amount("10 xxx").kind == "currency"
    assert parse_amount(f"{'9' * 19} usd").kind == "format"


def test_amount_format_uses_grouping_comma():
    assert format_amount(Decimal("2228.61")) == "2,228.61"
    assert format_amount(Decimal("7.214")) == "7.21"


def test_conversion_keeps_source_amount_and_order():
    per_usd = {code: Decimal(1) for code in CODES}
    per_usd["USD"] = Decimal(1)
    per_usd["LKR"] = Decimal("309.1")
    per_usd["RUB"] = Decimal("77.01")
    per_usd["EUR"] = Decimal("0.847433")
    per_usd["THB"] = Decimal("31.0693")
    text = conversion_text(
        Decimal("7.21"),
        "USD",
        ("USD", "LKR", "RUB", "EUR", "THB"),
        per_usd,
    )
    assert "7.21 🇺🇸 USD (без конвертации)" in text
    assert text.index("USD (без конвертации)") < text.index("LKR")
    assert "Курсы из сохранённой копии" not in text


def test_conversion_skips_source_when_it_is_not_selected():
    per_usd = {code: Decimal(1) for code in ("USD", "EUR", "LKR")}
    text = conversion_text(Decimal(1000), "LKR", ("USD", "EUR"), per_usd)
    bullet_lines = [line for line in text.splitlines() if line.startswith("•")]
    assert all("LKR" not in line for line in bullet_lines)
    assert "(без конвертации)" not in text
    assert "USD" in text and "EUR" in text


def test_toggle_limit_and_last_currency():
    added = toggle(("USD",), "EUR")
    assert added.status == "added"
    assert added.currencies == ("USD", "EUR")
    full = ("USD", "LKR", "RUB", "EUR", "THB")
    blocked = toggle(full, "AED")
    assert blocked.status == "too_many"
    assert blocked.currencies == full
    last = toggle(("USD",), "USD")
    assert last.status == "last_one"
    assert last.currencies == ("USD",)
    removed = toggle(full, "THB")
    assert removed.status == "removed"
    assert removed.currencies[-1] == "EUR"


def test_vnd_input_selection_keyboard_and_conversion():
    from cur_converter_bot.telegram_io import inline_keyboard
    from cur_converter_bot.rates import frankfurter_request_url
    query = parse_amount("100000vnd")
    assert query.amount == Decimal(100000) and query.code == "VND"
    assert toggle(("USD",), "VND").currencies == ("USD", "VND")
    keyboard = inline_keyboard(("USD", "VND"))
    button = next(b for row in keyboard.inline_keyboard for b in row if b.callback_data == "t:VND")
    assert button.text == "✅ 🇻🇳 VND"
    assert "vnd" in frankfurter_request_url()
    rates = {"USD": Decimal(1), "VND": Decimal(25000)}
    assert "100,000.00 🇻🇳 VND" in conversion_text(Decimal(4), "USD", ("VND",), rates)
    assert "4.00 🇺🇸 USD" in conversion_text(query.amount, query.code, ("USD",), rates)
