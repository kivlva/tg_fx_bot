"""
Конфигурация валют и их флагов для бота конвертера валют.

Для добавления новой валюты:
1. Добавьте код валюты в список AVAILABLE_CURRENCIES
2. Добавьте соответствующий флаг в словарь CURRENCY_FLAGS
"""

# Доступные валюты для выбора
AVAILABLE_CURRENCIES = [
    # Основные мировые валюты
    "USD",  # США (US Dollar)
    "EUR",  # Европейский союз (Euro)
    "GBP",  # Великобритания (British Pound)
    "JPY",  # Япония (Japanese Yen)
    "CNY",  # Китай (Chinese Yuan)
    "RUB",  # Россия (Russian Ruble)
    "THB",  # Таиланд (Thai Baht)
    "TRY",  # Турция (Turkish Lira)
    "KRW",  # Южная Корея (South Korean Won)
    "INR",  # Индия (Indian Rupee)
    "IDR",  # Индонезия (Indonesian Rupiah)
    "CAD",  # Канада (Canadian Dollar)
    "CHF",  # Швейцария (Swiss Franc)
    "SGD",  # Сингапур (Singapore Dollar)
    "HKD",  # Гонконг (Hong Kong Dollar)
    "MXN",  # Мексика (Mexican Peso)
    "LKR",  # Шри-Ланка (Sri Lankan Rupee)
    "MVR",  # Мальдивы (Maldivian Rufiyaa)
    "MUR",  # Маврикий (Mauritian Rupee)
    "AED",  # Арабские Эмираты (UAE Dirham)
    "RSD",  # Сербия (Serbian Dinar)
    "BYN",  # Беларусь (Belarusian Ruble)
    "KZT",  # Казахстан (Kazakhstani Tenge)
    "UZS",  # Узбекистан (Uzbekistani Som)
    "PLN",  # Польша (Polish Zloty)
    "ILS",  # Израиль (Israeli Shekel)
    "AMD",  # Армения (Armenian Dram)
    "GEL",  # Грузия (Georgian Lari)
    "AZN",  # Азербайджан (Azerbaijani Manat)
    "UAH",  # Украина (Ukrainian Hryvnia)
]

# Соответствие валют и флагов стран
CURRENCY_FLAGS = {
    "USD": "🇺🇸",  # США
    "EUR": "🇪🇺",  # Европейский союз
    "GBP": "🇬🇧",  # Великобритания
    "JPY": "🇯🇵",  # Япония
    "CNY": "🇨🇳",  # Китай
    "RUB": "🇷🇺",  # Россия
    "THB": "🇹🇭",  # Таиланд
    "TRY": "🇹🇷",  # Турция
    "KRW": "🇰🇷",  # Южная Корея
    "INR": "🇮🇳",  # Индия
    "IDR": "🇮🇩",  # Индонезия
    "CAD": "🇨🇦",  # Канада
    "CHF": "🇨🇭",  # Швейцария
    "SGD": "🇸🇬",  # Сингапур
    "HKD": "🇭🇰",  # Гонконг
    "MXN": "🇲🇽",  # Мексика
    "LKR": "🇱🇰",  # Шри-Ланка
    "MVR": "🇲🇻",  # Мальдивы
    "MUR": "🇲🇺",  # Маврикий
    "AED": "🇦🇪",  # ОАЭ
    "RSD": "🇷🇸",  # Сербия
    "BYN": "🇧🇾",  # Беларусь
    "KZT": "🇰🇿",  # Казахстан
    "UZS": "🇺🇿",  # Узбекистан
    "PLN": "🇵🇱",  # Польша
    "ILS": "🇮🇱",  # Израиль
    "AMD": "🇦🇲",  # Армения
    "GEL": "🇬🇪",  # Грузия
    "AZN": "🇦🇿",  # Азербайджан
    "UAH": "🇺🇦",  # Украина
}

