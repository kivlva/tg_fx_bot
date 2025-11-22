import os
import logging
import time
import sys
import json
from typing import Dict, Tuple, Optional
from pathlib import Path

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.error import Conflict, BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Импортируем конфигурацию валют
from currencies import AVAILABLE_CURRENCIES, CURRENCY_FLAGS

# --------------------
# НАСТРОЙКИ
# --------------------

# Загружаем переменные из .env файла, если он существует
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                # Убираем кавычки и пробелы
                value = value.strip().strip('"').strip("'")
                os.environ[key.strip()] = value

# Токен бота (из переменной окружения TELEGRAM_BOT_TOKEN или из .env файла)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")

def get_currency_flag(currency: str) -> str:
    """Получить флаг страны для валюты."""
    return CURRENCY_FLAGS.get(currency.upper(), "")

# Валюты по умолчанию (если пользователь не выбрал свои)
DEFAULT_CURRENCIES = ["RUB", "LKR", "USD"]

# Файл для хранения настроек пользователей
USER_SETTINGS_FILE = Path(__file__).parent / "user_settings.json"

# Базовый URL внешнего API курсов
# Используем exchangerate-api.com - бесплатный API без ключа
FX_API_URL = "https://api.exchangerate-api.com/v4/latest"

# Максимальное количество валют, которые можно выбрать
MAX_SELECTED_CURRENCIES = 5

# Настройки для retry логики API
API_MAX_RETRIES = 3
API_RETRY_DELAY = 1  # секунды между попытками

# Включаем логирование (полезно для отладки)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# --------------------

def get_rates(base: str, symbols: list[str]) -> Dict[str, float]:
    """
    Получить курсы для списка валют `symbols`, где `base` — базовая валюта.
    Использует API exchangerate-api.com с retry логикой (бесплатный, без ключа).
    Возвращает словарь вида {"EUR": 0.92, "THB": 36.5}
    
    Raises:
        RuntimeError: Если не удалось получить курсы после всех попыток
        ValueError: Если базовая валюта или символы невалидны
    """
    # Валидация входных данных
    if not base or not isinstance(base, str):
        raise ValueError("Базовая валюта должна быть непустой строкой")
    
    if not symbols or not isinstance(symbols, list) or len(symbols) == 0:
        raise ValueError("Список валют не может быть пустым")
    
    base = base.upper().strip()
    symbols = [s.upper().strip() for s in symbols if s and isinstance(s, str)]
    
    if not symbols:
        raise ValueError("Нет валидных валют для конвертации")
    
    # Формируем URL для exchangerate-api.com
    # Формат: https://api.exchangerate-api.com/v4/latest/{base}
    url = f"{FX_API_URL}/{base}"

    last_error = None
    for attempt in range(API_MAX_RETRIES):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Проверка структуры ответа
            if "rates" not in data:
                raise RuntimeError("API вернул неожиданную структуру данных")

            rates = data.get("rates", {})
            
            # Проверка, что получили хотя бы один курс
            if not rates:
                raise RuntimeError("API вернул пустой список курсов")
            
            # Фильтруем только запрошенные валюты
            filtered_rates = {}
            missing = []
            for symbol in symbols:
                if symbol in rates:
                    # Конвертируем курс относительно базовой валюты
                    # API возвращает курсы относительно базовой валюты, так что используем напрямую
                    filtered_rates[symbol] = rates[symbol]
                else:
                    missing.append(symbol)
            
            if missing:
                logger.warning(f"Не найдены курсы для валют: {missing}")
            
            if not filtered_rates:
                raise RuntimeError("Не удалось получить ни одного запрошенного курса")
            
            return filtered_rates
            
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < API_MAX_RETRIES - 1:
                wait_time = API_RETRY_DELAY * (attempt + 1)  # Экспоненциальная задержка
                logger.warning(f"Попытка {attempt + 1}/{API_MAX_RETRIES} не удалась. Повтор через {wait_time}с...")
                time.sleep(wait_time)
            else:
                logger.error(f"Все {API_MAX_RETRIES} попытки получения курсов не удались")
        except (ValueError, KeyError, TypeError) as e:
            # Ошибки парсинга не требуют retry
            raise RuntimeError(f"Ошибка обработки ответа API: {e}") from e
    
    # Если все попытки не удались
    raise RuntimeError(f"Не удалось получить курсы валют после {API_MAX_RETRIES} попыток: {last_error}")


def load_user_settings() -> Dict[str, Dict]:
    """Загрузить настройки всех пользователей из файла."""
    if not USER_SETTINGS_FILE.exists():
        return {}
    
    try:
        with open(USER_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Ошибка при загрузке настроек пользователей: {e}")
        return {}


def save_user_settings(settings: Dict[str, Dict]) -> None:
    """Сохранить настройки всех пользователей в файл."""
    try:
        with open(USER_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"Ошибка при сохранении настроек пользователей: {e}")


def get_user_currencies(context: ContextTypes.DEFAULT_TYPE, user_id: Optional[str] = None) -> list[str]:
    """
    Получить список валют пользователя.
    Сначала проверяет context.user_data (в памяти), затем загружает из файла.
    
    Args:
        context: Контекст бота
        user_id: ID пользователя (если не указан, берется из context.user_data)
    """
    if user_id is None:
        user_id = str(context.user_data.get("user_id", ""))
    
    # Сначала проверяем в памяти (быстрее)
    if "currencies" in context.user_data:
        return context.user_data["currencies"]
    
    # Если нет в памяти, загружаем из файла
    if user_id:
        settings = load_user_settings()
        if user_id in settings and "currencies" in settings[user_id]:
            currencies = settings[user_id]["currencies"]
            # Сохраняем в память для быстрого доступа
            context.user_data["currencies"] = currencies
            return currencies
    
    # Если ничего не найдено, возвращаем валюты по умолчанию
    default = DEFAULT_CURRENCIES.copy()
    context.user_data["currencies"] = default
    return default


def is_user_started(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Проверить, был ли вызван /start пользователем.
    
    Args:
        context: Контекст бота
    
    Returns:
        bool: True если пользователь запустил бота, False иначе
    """
    return context.user_data.get("started", False)


def save_user_currencies(context: ContextTypes.DEFAULT_TYPE, currencies: list[str]) -> None:
    """Сохранить список валют пользователя в файл и в память."""
    user_id = str(context.user_data.get("user_id", ""))
    
    if not user_id:
        logger.warning("Не удалось сохранить настройки: user_id не найден")
        return
    
    # Сохраняем в память
    context.user_data["currencies"] = currencies.copy()
    
    # Загружаем все настройки
    settings = load_user_settings()
    
    # Обновляем настройки пользователя
    if user_id not in settings:
        settings[user_id] = {}
    settings[user_id]["currencies"] = currencies.copy()
    
    # Сохраняем в файл
    save_user_settings(settings)


def parse_amount_and_currency(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Парсим строку вида:
      '100 usd'
      '250.5 EUR'
      '1000 thb'
    
    Валидация:
    - Проверка формата (сумма и валюта)
    - Проверка на отрицательные и нулевые суммы
    - Проверка на слишком большие суммы
    - Проверка валюты в списке доступных валют (AVAILABLE_CURRENCIES)
    
    Returns:
        Tuple[Optional[float], Optional[str]]: (amount, currency) или (None, None) при ошибке
    """
    if not text or not isinstance(text, str):
        return None, None
    
    # Очистка и нормализация текста
    text = text.strip()
    if not text:
        return None, None
    
    # Замена запятой на точку для десятичных чисел
    text = text.replace(",", ".")
    
    # Разделение на части
    parts = text.split()
    
    # Проверка формата: должно быть ровно 2 части
    if len(parts) != 2:
        return None, None

    amount_str, currency_str = parts
    
    # Валидация и парсинг суммы
    try:
        amount = float(amount_str)
    except (ValueError, OverflowError):
        return None, None
    
    # Проверка на отрицательные суммы
    if amount < 0:
        return None, None
    
    # Проверка на нулевую сумму
    if amount == 0:
        return None, None
    
    # Проверка на слишком большие суммы (защита от переполнения)
    MAX_AMOUNT = 1e15  # 1 квадриллион
    if amount > MAX_AMOUNT:
        return None, None
    
    # Проверка на слишком маленькие суммы (меньше копейки/цента)
    MIN_AMOUNT = 1e-10
    if 0 < amount < MIN_AMOUNT:
        return None, None

    # Валидация валюты
    currency = currency_str.upper().strip()
    if not currency:
        return None, None
    
    # Проверка, что валюта в списке доступных валют
    if currency not in AVAILABLE_CURRENCIES:
        return None, None

    return amount, currency


# --------------------
# ХЕНДЛЕРЫ
# --------------------

def get_main_menu_keyboard():
    """Создает inline-клавиатуру с основными командами меню."""
    keyboard = [
        [InlineKeyboardButton("💰 Выбрать валюты", callback_data="menu_set_currencies")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_reply_keyboard():
    """Создает постоянную клавиатуру с кнопками команд."""
    keyboard = [
        [KeyboardButton("/start"), KeyboardButton("/set_currencies")],
        [KeyboardButton("/help")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сохраняем user_id для последующего использования
    user_id = str(update.effective_user.id)
    context.user_data["user_id"] = user_id
    # Отмечаем, что пользователь запустил бота
    context.user_data["started"] = True
    
    user_currencies = get_user_currencies(context, user_id)
    # Формируем список валют с флагами
    supported_with_flags = [
        f"{get_currency_flag(c)} {c}" for c in user_currencies
    ]
    supported = ", ".join(supported_with_flags)
    msg = (
        "💱 Привет! Я конвертер валют.\n\n"
        f"Валюты, в которые конвертируем: {supported}\n\n"
        "Используй кнопки ниже для управления ботом:\n\n"
        "Напиши сумму и валюту (любую из доступных), например:\n"
        "• 100 usd\n"
        "• 250 rub\n"
        "• 1000 lkr\n\n"
        "Я конвертирую её в выбранные валюты.\n"
        "Если введенная валюта совпадает с выбранной - верну ту же сумму."
    )
    await update.message.reply_text(
        msg, 
        reply_markup=get_reply_keyboard()
    )
    # Также отправляем inline-кнопки для дополнительных функций
    await update.message.reply_text(
        "💡 Дополнительные функции:",
        reply_markup=get_main_menu_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сохраняем user_id для последующего использования
    user_id = str(update.effective_user.id)
    context.user_data["user_id"] = user_id
    # Отмечаем, что пользователь запустил бота (если еще не отмечено)
    if not context.user_data.get("started", False):
        context.user_data["started"] = True
    
    user_currencies = get_user_currencies(context, user_id)
    supported_with_flags = [
        f"{get_currency_flag(c)} {c}" for c in user_currencies
    ]
    supported = ", ".join(supported_with_flags)
    msg = (
        "ℹ️ Помощь по использованию бота\n\n"
        f"Валюты для конвертации: {supported}\n\n"
        "📝 Как использовать:\n"
        "1. Напиши сумму в исходной валюте в формате: <сумма> <валюта>\n"
        "   Можно указать любую доступную валюту на входе\n"
        "2. Примеры: 100 usd, 250 rub, 1000 lkr, 50 eur\n"
        "3. Бот конвертирует в выбранные тобой валюты\n"
        "   Если введенная валюта совпадает с выбранной - вернется та же сумма\n\n"
        "⚙️ Команды:\n"
        "• /start - начать работу\n"
        "• /set_currencies - выбрать целевые валюты\n"
        "• /help - показать эту справку\n\n"
        "💡 Совет: Используй кнопки ниже для быстрого доступа к функциям!"
    )
    if update.message:
        await update.message.reply_text(msg, reply_markup=get_reply_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())


async def convert_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений с конвертацией валют."""
    # Сохраняем user_id для последующего использования
    user_id = str(update.effective_user.id)
    context.user_data["user_id"] = user_id
    
    # Проверяем, был ли вызван /start
    if not context.user_data.get("started", False):
        await update.message.reply_text(
            "👋 Привет! Для начала работы с ботом нажми команду /start\n\n"
            "Это поможет мне настроить всё необходимое для тебя!",
            reply_markup=get_reply_keyboard()
        )
        return
    
    text = (update.message.text or "").strip()
    user_currencies = get_user_currencies(context, user_id)

    # Валидация списка валют пользователя
    if not user_currencies or len(user_currencies) == 0:
        await update.message.reply_text(
            "❌ У тебя не выбраны валюты для конвертации.\n"
            "Используй /set_currencies чтобы выбрать валюты.",
            reply_markup=get_reply_keyboard()
        )
        return

    amount, currency = parse_amount_and_currency(text)
    if amount is None or currency is None:
        # Формируем список доступных валют с флагами
        available_with_flags = [
            f"{get_currency_flag(c)} {c}" for c in sorted(AVAILABLE_CURRENCIES)
        ]
        available = ", ".join(available_with_flags)
        
        # Формируем список выбранных валют для конвертации
        selected_with_flags = [
            f"{get_currency_flag(c)} {c}" for c in user_currencies
        ]
        selected = ", ".join(selected_with_flags)
        
        await update.message.reply_text(
            "❌ Не смог разобрать сообщение 😔\n\n"
            "📝 Формат: `<сумма> <валюта>`\n\n"
            "✅ Примеры:\n"
            "• 100 usd\n"
            "• 250.5 eur\n"
            "• 1000 rub\n\n"
            f"💱 Доступные валюты для ввода: {available}\n\n"
            f"💰 Валюты для конвертации (выбраны в настройках): {selected}\n\n"
            "⚠️ Сумма должна быть положительным числом.\n"
            "Используй /set_currencies чтобы выбрать валюты для конвертации."
        )
        return

    # Определяем валюты для конвертации (все выбранные пользователем)
    target_currencies = user_currencies.copy()
    
    if not target_currencies:
        await update.message.reply_text(
            "❌ Нужно выбрать хотя бы одну валюту для конвертации.\n"
            "Используй /set_currencies чтобы выбрать валюты.",
            reply_markup=get_reply_keyboard()
        )
        return

    # Получаем курсы только для валют, которые отличаются от введенной
    currencies_to_convert = [c for c in target_currencies if c != currency]
    
    try:
        rates = {}
        if currencies_to_convert:
            rates = get_rates(currency, currencies_to_convert)
    except ValueError as e:
        logger.error(f"Ошибка валидации: {e}")
        await update.message.reply_text(
            "❌ Ошибка валидации валют. Проверь выбранные валюты."
        )
        return
    except RuntimeError as e:
        logger.exception("Ошибка при получении курсов")
        await update.message.reply_text(
            "❌ Не удалось получить актуальный курс валют.\n"
            "Возможные причины:\n"
            "• Проблемы с интернет-соединением\n"
            "• Временная недоступность API\n\n"
            "Попробуй позже 🙏"
        )
        return
    except Exception as e:
        logger.exception("Неожиданная ошибка при получении курсов")
        await update.message.reply_text(
            "❌ Произошла неожиданная ошибка. Попробуй позже 🙏"
        )
        return

    # Получаем флаг базовой валюты
    base_flag = get_currency_flag(currency)
    
    # Формирование результата
    lines = [f"💱 Конвертация {amount:.2f} {base_flag} {currency.upper()}:"]
    successful_conversions = 0
    
    # Обрабатываем все выбранные валюты
    for tgt in target_currencies:
        tgt_flag = get_currency_flag(tgt)
        
        # Если валюта совпадает с введенной - просто возвращаем ту же сумму
        if tgt == currency:
            if amount >= 1:
                lines.append(f"• {amount:,.2f} {tgt_flag} {tgt} (без конвертации)")
            else:
                lines.append(f"• {amount:.6f} {tgt_flag} {tgt} (без конвертации)")
            successful_conversions += 1
            continue
        
        # Для остальных валют конвертируем
        rate = rates.get(tgt)
        
        if rate is None:
            lines.append(f"❌ Нет курса для {tgt_flag} {tgt}")
            continue
        
        # Валидация курса
        if rate <= 0:
            logger.warning(f"Некорректный курс для {tgt}: {rate}")
            lines.append(f"❌ Некорректный курс для {tgt_flag} {tgt}")
            continue
        
        converted = amount * rate
        
        # Проверка на переполнение
        if converted > 1e15:
            lines.append(f"⚠️ {tgt_flag} {tgt}: сумма слишком большая")
            continue
        
        # Форматирование с правильным количеством знаков после запятой
        if converted >= 1:
            lines.append(f"• {converted:,.2f} {tgt_flag} {tgt}")
        else:
            # Для очень маленьких сумм показываем больше знаков
            lines.append(f"• {converted:.6f} {tgt_flag} {tgt}")
        
        successful_conversions += 1
    
    if successful_conversions == 0:
        await update.message.reply_text(
            "❌ Не удалось конвертировать ни в одну валюту.\n"
            "Попробуй позже или выбери другие валюты."
        )
        return

    await update.message.reply_text("\n".join(lines))


async def set_currencies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать inline-кнопки для выбора валют."""
    # Сохраняем user_id для последующего использования
    user_id = str(update.effective_user.id)
    context.user_data["user_id"] = user_id
    # Отмечаем, что пользователь запустил бота (если еще не отмечено)
    if not context.user_data.get("started", False):
        context.user_data["started"] = True
    
    user_currencies = get_user_currencies(context, user_id)
    
    # Сортируем валюты в алфавитном порядке для отображения на кнопках
    sorted_currencies = sorted(AVAILABLE_CURRENCIES)
    
    # Создаем кнопки для каждой валюты
    keyboard = []
    row = []
    
    for currency in sorted_currencies:
        # Получаем флаг страны
        flag = get_currency_flag(currency)
        
        # Отмечаем выбранные валюты
        prefix = "✅ " if currency in user_currencies else ""
        button_text = f"{prefix}{flag} {currency}"
        
        row.append(InlineKeyboardButton(button_text, callback_data=f"currency_{currency}"))
        
        # Размещаем по 3 кнопки в ряд
        if len(row) == 3:
            keyboard.append(row)
            row = []
    
    # Добавляем оставшиеся кнопки
    if row:
        keyboard.append(row)
    
    # Кнопка "Готово"
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="currency_done")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Формируем список выбранных валют с флагами
    selected_with_flags = [
        f"{get_currency_flag(c)}{c}" for c in user_currencies
    ]
    selected_text = ", ".join(selected_with_flags) if selected_with_flags else "не выбрано"
    
    msg = (
        f"💰 Выбери валюты, В которые конвертировать (максимум {MAX_SELECTED_CURRENCIES}):\n\n"
        f"Текущий выбор: {selected_text}\n\n"
        "На входе можно указать любую доступную валюту.\n"
        "Здесь выбираешь валюты, в которые будет конвертироваться ввод.\n\n"
        "Нажми на валюту, чтобы добавить/убрать её из списка."
    )
    
    await update.message.reply_text(msg, reply_markup=reply_markup)
    # Также показываем постоянную клавиатуру с командами
    await update.message.reply_text(
        "💡 Используй кнопки ниже для управления ботом:",
        reply_markup=get_reply_keyboard()
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки меню."""
    # Сохраняем user_id для последующего использования
    user_id = str(update.effective_user.id)
    context.user_data["user_id"] = user_id
    
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "menu_set_currencies":
        # Показываем кнопки выбора валют
        user_currencies = get_user_currencies(context, user_id)
        
        # Сортируем валюты в алфавитном порядке для отображения на кнопках
        sorted_currencies = sorted(AVAILABLE_CURRENCIES)
        
        # Создаем кнопки для каждой валюты
        keyboard = []
        row = []
        
        for currency in sorted_currencies:
            # Получаем флаг страны
            flag = get_currency_flag(currency)
            
            # Отмечаем выбранные валюты
            prefix = "✅ " if currency in user_currencies else ""
            button_text = f"{prefix}{flag} {currency}"
            
            row.append(InlineKeyboardButton(button_text, callback_data=f"currency_{currency}"))
            
            # Размещаем по 3 кнопки в ряд
            if len(row) == 3:
                keyboard.append(row)
                row = []
        
        # Добавляем оставшиеся кнопки
        if row:
            keyboard.append(row)
        
        # Кнопка "Готово"
        keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="currency_done")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Формируем список выбранных валют с флагами
        selected_with_flags = [
            f"{get_currency_flag(c)} {c}" for c in user_currencies
        ]
        selected_text = ", ".join(selected_with_flags) if selected_with_flags else "не выбрано"
        
        msg = (
            f"💰 Выбери валюты, В которые конвертировать (максимум {MAX_SELECTED_CURRENCIES}):\n\n"
            f"Текущий выбор: {selected_text}\n\n"
            "На входе можно указать любую доступную валюту.\n"
            "Здесь выбираешь валюты, в которые будет конвертироваться ввод.\n\n"
            "Нажми на валюту, чтобы добавить/убрать её из списка."
        )
        
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup)
        except BadRequest as e:
            # Игнорируем ошибку, если сообщение не изменилось
            if "Message is not modified" in str(e):
                await query.answer()
            else:
                raise
    elif data == "menu_help":
        user_currencies = get_user_currencies(context, user_id)
        supported_with_flags = [
            f"{get_currency_flag(c)} {c}" for c in user_currencies
        ]
        supported = ", ".join(supported_with_flags)
        msg = (
            "ℹ️ Помощь по использованию бота\n\n"
            f"Валюты для конвертации: {supported}\n\n"
            "📝 Как использовать:\n"
            "1. Напиши сумму и валюту в формате: <сумма> <валюта>\n"
            "   Можно указать любую доступную валюту на входе\n"
            "2. Примеры: 100 usd, 250 rub, 1000 lkr, 50 eur\n"
            "3. Бот конвертирует в выбранные валюты\n"
            "   Если введенная валюта совпадает с выбранной - вернется та же сумма\n\n"
            "⚙️ Команды:\n"
            "• /start - начать работу\n"
            "• /set_currencies - выбрать валюты для конвертации\n"
            "• /help - показать эту справку\n\n"
            "💡 Совет: Используй кнопки меню для быстрого доступа к функциям!"
        )
        try:
            await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
        except BadRequest as e:
            # Игнорируем ошибку, если сообщение не изменилось
            if "Message is not modified" in str(e):
                await query.answer()
            else:
                raise


async def currency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки выбора валют."""
    # Сохраняем user_id для последующего использования
    user_id = str(update.effective_user.id)
    context.user_data["user_id"] = user_id
    
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "currency_done":
        user_currencies = get_user_currencies(context, user_id)
        if not user_currencies:
            try:
                await query.edit_message_text(
                    "❌ Нужно выбрать хотя бы одну валюту!\n"
                    "Используй /set_currencies чтобы выбрать валюты."
                )
            except BadRequest as e:
                # Игнорируем ошибку, если сообщение не изменилось
                if "Message is not modified" in str(e):
                    await query.answer("❌ Нужно выбрать хотя бы одну валюту!", show_alert=True)
                else:
                    raise
            return
        
        # Формируем список выбранных валют с флагами
        selected_with_flags = [
            f"{get_currency_flag(c)}{c}" for c in user_currencies
        ]
        selected_text = ", ".join(selected_with_flags)
        
        try:
            await query.edit_message_text(
                f"✅ Валюты сохранены!\n\n"
                f"Выбранные валюты: {selected_text}\n\n"
                "Теперь можешь конвертировать между этими валютами."
            )
        except BadRequest as e:
            # Игнорируем ошибку, если сообщение не изменилось
            if "Message is not modified" in str(e):
                await query.answer("✅ Валюты уже сохранены!")
            else:
                raise
        return
    
    # Обработка выбора валюты
    currency = data.replace("currency_", "")
    
    if currency not in AVAILABLE_CURRENCIES:
        return
    
    user_currencies = get_user_currencies(context, user_id)
    
    # Переключаем валюту (добавляем/убираем)
    if currency in user_currencies:
        # Удаляем валюту, но проверяем, что останется хотя бы одна
        if len(user_currencies) <= 1:
            await query.answer(
                "❌ Нужно оставить хотя бы одну валюту!",
                show_alert=True
            )
            return
        user_currencies.remove(currency)
    else:
        # Добавляем валюту, проверяя лимит
        if len(user_currencies) >= MAX_SELECTED_CURRENCIES:
            await query.answer(
                f"❌ Максимум {MAX_SELECTED_CURRENCIES} валют! Сначала убери одну из выбранных.",
                show_alert=True
            )
            return
        user_currencies.append(currency)
    
    # Валидация перед сохранением
    if not user_currencies or len(user_currencies) == 0:
        await query.answer(
            "❌ Ошибка: список валют не может быть пустым!",
            show_alert=True
        )
        return
    
    # Сохраняем обновленный список в файл и в память
    save_user_currencies(context, user_currencies)
    
    # Обновляем сообщение с кнопками
    # Сортируем валюты в алфавитном порядке для отображения на кнопках
    sorted_currencies = sorted(AVAILABLE_CURRENCIES)
    
    keyboard = []
    row = []
    
    for curr in sorted_currencies:
        # Получаем флаг страны
        flag = get_currency_flag(curr)
        
        prefix = "✅ " if curr in user_currencies else ""
        button_text = f"{prefix}{flag} {curr}"
        row.append(InlineKeyboardButton(button_text, callback_data=f"currency_{curr}"))
        
        if len(row) == 3:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="currency_done")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Формируем список выбранных валют с флагами
    selected_with_flags = [
        f"{get_currency_flag(c)}{c}" for c in user_currencies
    ]
    selected_text = ", ".join(selected_with_flags) if selected_with_flags else "не выбрано"
    
    msg = (
        f"💰 Выбери валюты, В которые конвертировать (максимум {MAX_SELECTED_CURRENCIES}):\n\n"
        f"Текущий выбор: {selected_text}\n\n"
        "На входе можно указать любую доступную валюту.\n"
        "Здесь выбираешь валюты, в которые будет конвертироваться ввод.\n\n"
        "Нажми на валюту, чтобы добавить/убрать её из списка."
    )
    
    try:
        await query.edit_message_text(msg, reply_markup=reply_markup)
    except BadRequest as e:
        # Игнорируем ошибку, если сообщение не изменилось
        if "Message is not modified" in str(e):
            # Просто подтверждаем нажатие, но не обновляем сообщение
            await query.answer()
        else:
            raise


# --------------------
# MAIN
# --------------------

def main():
    if TELEGRAM_TOKEN == "PASTE_YOUR_TOKEN_HERE" or not TELEGRAM_TOKEN:
        env_file_path = Path(__file__).parent / ".env"
        error_msg = (
            "❌ Ошибка: Токен бота не установлен!\n\n"
            "Способы установки токена:\n\n"
            "1. Создайте файл .env в папке проекта со строкой:\n"
            "   TELEGRAM_BOT_TOKEN=ваш_токен_здесь\n\n"
            "2. Или установите переменную окружения:\n"
            "   export TELEGRAM_BOT_TOKEN='ваш_токен_здесь'\n\n"
            f"Файл .env {'существует' if env_file_path.exists() else 'НЕ найден'} в: {env_file_path}\n\n"
            "Получить токен можно у @BotFather в Telegram"
        )
        raise RuntimeError(error_msg)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("set_currencies", set_currencies))
    
    # Обработчик нажатий на кнопки меню
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    
    # Обработчик нажатий на inline-кнопки выбора валют
    app.add_handler(CallbackQueryHandler(currency_callback, pattern="^currency_"))

    # Обработчик текстовых сообщений (конвертация)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, convert_message)
    )

    # Обработка ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка ошибок бота."""
        error = context.error
        
        if isinstance(error, Conflict):
            logger.error(
                "❌ Конфликт: уже запущен другой экземпляр бота!\n"
                "Остановите другие процессы бота и попробуйте снова."
            )
            print("\n" + "="*60)
            print("❌ ОШИБКА: Конфликт с другим экземпляром бота")
            print("="*60)
            print("\nУже запущен другой экземпляр бота с тем же токеном.")
            print("Остановите другие процессы и попробуйте снова.\n")
            print("Для остановки всех процессов бота выполните:")
            print("  pkill -f 'python.*bot.py'")
            print("\nИли найдите процессы вручную:")
            print("  ps aux | grep 'python.*bot.py'")
            print("="*60 + "\n")
            sys.exit(1)
        else:
            logger.exception(f"Неожиданная ошибка: {error}")

    app.add_error_handler(error_handler)

    logger.info("Бот запущен...")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict as e:
        logger.error(f"Конфликт при запуске: {e}")
        print("\n❌ Ошибка: уже запущен другой экземпляр бота!")
        print("Остановите другие процессы: pkill -f 'python.*bot.py'")
        sys.exit(1)


if __name__ == "__main__":
    main()

