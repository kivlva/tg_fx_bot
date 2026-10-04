"""Каталог валют, флаги и правило выбора."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MAX_SELECTED = 5

# Порядок рядов как на клавиатуре исходного бота.
CODES: tuple[str, ...] = (
    "AED",
    "AMD",
    "AZN",
    "BYN",
    "CAD",
    "CHF",
    "CNY",
    "EUR",
    "GBP",
    "GEL",
    "HKD",
    "IDR",
    "ILS",
    "INR",
    "JPY",
    "KRW",
    "KZT",
    "LKR",
    "MUR",
    "MVR",
    "MXN",
    "PLN",
    "RSD",
    "RUB",
    "SGD",
    "THB",
    "TRY",
    "UAH",
    "USD",
    "UZS",
    "VND",
)

DEFAULT_CURRENCIES: tuple[str, ...] = ("USD", "LKR", "RUB", "EUR", "THB")

FLAGS: dict[str, str] = {
    "AED": "🇦🇪",
    "AMD": "🇦🇲",
    "AZN": "🇦🇿",
    "BYN": "🇧🇾",
    "CAD": "🇨🇦",
    "CHF": "🇨🇭",
    "CNY": "🇨🇳",
    "EUR": "🇪🇺",
    "GBP": "🇬🇧",
    "GEL": "🇬🇪",
    "HKD": "🇭🇰",
    "IDR": "🇮🇩",
    "ILS": "🇮🇱",
    "INR": "🇮🇳",
    "JPY": "🇯🇵",
    "KRW": "🇰🇷",
    "KZT": "🇰🇿",
    "LKR": "🇱🇰",
    "MUR": "🇲🇺",
    "MVR": "🇲🇻",
    "MXN": "🇲🇽",
    "PLN": "🇵🇱",
    "RSD": "🇷🇸",
    "RUB": "🇷🇺",
    "SGD": "🇸🇬",
    "THB": "🇹🇭",
    "TRY": "🇹🇷",
    "UAH": "🇺🇦",
    "USD": "🇺🇸",
    "UZS": "🇺🇿",
    "VND": "🇻🇳",
}

CODE_SET = frozenset(CODES)

REGIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "europe": ("Европа и СНГ", ("AMD", "AZN", "BYN", "CHF", "EUR", "GBP", "GEL", "PLN", "RSD", "RUB", "UAH")),
    "asia": ("Азия", ("CNY", "HKD", "IDR", "INR", "JPY", "KRW", "KZT", "LKR", "MVR", "SGD", "THB", "UZS", "VND")),
    "middle_east": ("Ближний Восток", ("AED", "ILS", "TRY")),
    "other": ("Другие", ("CAD", "MUR", "MXN", "USD")),
}

NAMES: dict[str, str] = {
    "AED": "Дирхам ОАЭ", "AMD": "Армянский драм", "AZN": "Азербайджанский манат",
    "BYN": "Белорусский рубль", "CAD": "Канадский доллар", "CHF": "Швейцарский франк",
    "CNY": "Китайский юань", "EUR": "Евро", "GBP": "Британский фунт",
    "GEL": "Грузинский лари", "HKD": "Гонконгский доллар", "IDR": "Индонезийская рупия",
    "ILS": "Израильский шекель", "INR": "Индийская рупия", "JPY": "Японская иена",
    "KRW": "Южнокорейская вона", "KZT": "Казахстанский тенге", "LKR": "Шри-ланкийская рупия",
    "MUR": "Маврикийская рупия", "MVR": "Мальдивская руфия", "MXN": "Мексиканское песо",
    "PLN": "Польский злотый", "RSD": "Сербский динар", "RUB": "Российский рубль",
    "SGD": "Сингапурский доллар", "THB": "Тайский бат", "TRY": "Турецкая лира",
    "UAH": "Украинская гривна", "USD": "Доллар США", "UZS": "Узбекский сум",
    "VND": "Вьетнамский донг",
}


EXTRA_BUTTON = "💡 Дополнительные функции:"
PICK_BUTTON = "💰 Выбрать валюты"
HELP_BUTTON = "ℹ️ Помощь"

BEFORE_START = (
    "👋 Привет! Для начала работы с ботом нажми команду /start\n"
    "\n"
    "Это поможет мне настроить всё необходимое для тебя!"
)

EXTRA_HINT = "💡 Используй кнопки ниже для управления ботом:"

FORMAT_HINT = "Напиши сумму и валюту, например: 100 usd"
AMOUNT_HINT = "Сумма должна быть больше нуля."
CURRENCY_HINT = "Такой валюты нет в списке. Напиши код из доступных, например: 100 usd"
TOO_MANY = "Выбрано 5 из 5. Чтобы добавить валюту, сначала убери одну из выбранных."
LAST_ONE = "Нужна хотя бы одна валюта."
RATES_UNAVAILABLE = "Курсы сейчас недоступны. Попробуй ещё раз чуть позже."
RATES_CACHED = "Курсы из сохранённой копии."
SAVE_CONFLICT = "Не удалось сохранить выбор. Нажми ещё раз."

ToggleStatus = Literal["added", "removed", "too_many", "last_one", "invalid"]


@dataclass(frozen=True)
class ToggleResult:
    currencies: tuple[str, ...]
    status: ToggleStatus


def flag(code: str) -> str:
    return FLAGS[code]


def format_currency_list(codes: tuple[str, ...] | list[str]) -> str:
    return ", ".join(f"{flag(code)} {code}" for code in codes)


def welcome_text(codes: tuple[str, ...] | list[str]) -> str:
    return (
        "💱 Привет! Я конвертер валют.\n"
        "\n"
        f"Валюты, в которые конвертируем: {format_currency_list(codes)}\n"
        "\n"
        "Используй кнопки ниже для управления ботом:\n"
        "\n"
        "Напиши сумму и валюту (любую из доступных), например:\n"
        "• 100 usd\n"
        "• 250 rub\n"
        "• 1000 lkr\n"
        "\n"
        "Я конвертирую её в выбранные валюты.\n"
        "Если введенная валюта совпадает с выбранной - верну ту же сумму."
    )


def picker_text(codes: tuple[str, ...] | list[str], region: str = "home") -> str:
    selected = "\n".join(f"• {flag(code)} {code} — {NAMES[code]}" for code in codes)
    title = "Добавить валюту: выбери регион." if region == "home" else f"Добавить валюту · {REGIONS[region][0]}"
    limit = "\nЧтобы добавить валюту, сначала убери одну из выбранных." if len(codes) == MAX_SELECTED else ""
    return (
        f"💰 Выбрано {len(codes)} из {MAX_SELECTED}\n\n"
        f"{selected}\n\n"
        "Нажми ✅ сверху, чтобы убрать валюту.\n"
        "Изменения сохраняются сразу."
        f"{limit}\n\n{title}\n"
        "На входе можно указать любую валюту каталога."
    )


def saved_text(codes: tuple[str, ...] | list[str]) -> str:
    return f"Сохранено. Валюты, в которые конвертируем: {format_currency_list(codes)}"


def toggle(currencies: tuple[str, ...] | list[str], code: str) -> ToggleResult:
    current = tuple(currencies)
    if code not in CODE_SET:
        return ToggleResult(current, "invalid")
    if code in current:
        if len(current) == 1:
            return ToggleResult(current, "last_one")
        return ToggleResult(tuple(item for item in current if item != code), "removed")
    if len(current) >= MAX_SELECTED:
        return ToggleResult(current, "too_many")
    return ToggleResult((*current, code), "added")
