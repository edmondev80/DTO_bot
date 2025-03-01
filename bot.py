import os
import json
import logging
import re
import sqlite3
import time
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Функция для форматирования описания
def format_description(description):
    """Форматирует описание для удобного отображения."""
    if isinstance(description, dict):
        formatted_text = ""
        for key, value in description.items():
            formatted_text += f"• *{key}*: _{value}_\n"
        return formatted_text.strip()
    elif isinstance(description, str):
        return description
    else:
        return str(description)

# Функция для экранирования специальных символов
def escape_markdown(text):
    """Экранирует специальные символы для MarkdownV2."""
    escape_chars = r"\_*\[\]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# Загружаем переменные из .env
if not load_dotenv():
    logger.error("Файл .env не найден.")
    exit(1)

# Получаем токен
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("Токен не найден. Убедитесь, что переменная окружения TELEGRAM_BOT_TOKEN установлена.")
    exit(1)

# ID владельца бота (ваш Telegram ID)
OWNER_ID = os.getenv("OWNER_ID")
if not OWNER_ID:
    logger.error("ID владельца не найден. Убедитесь, что переменная OWNER_ID установлена в .env.")
    exit(1)

try:
    OWNER_ID = int(OWNER_ID)  # Преобразуем в число
except ValueError:
    logger.error("OWNER_ID должен быть числом. Убедитесь, что в .env указан ваш Telegram ID (число).")
    exit(1)

# Загружаем данные из JSON-файла
def load_data():
    """Загружает данные из файла data.json."""
    retries = 3
    for attempt in range(retries):
        try:
            with open('data.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("Файл data.json не найден. Убедитесь, что файл существует и находится в корневой директории.")
            if attempt == retries - 1:
                exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON в файле data.json: {e}")
            if attempt == retries - 1:
                exit(1)
        except Exception as e:
            logger.error(f"Неизвестная ошибка при загрузке данных: {e}")
            if attempt == retries - 1:
                exit(1)
        time.sleep(5)  # Ждем 5 секунд перед повторной попыткой

sections = load_data()
if not sections:
    logger.error("Не удалось загрузить данные. Бот завершает работу.")
    exit(1)

logger.debug(f"Загруженные данные: {sections}")

# Состояния для ConversationHandler
AUTH, MAIN_MENU = range(2)

# Время неактивности для автоматического выхода (в секундах)
INACTIVITY_TIMEOUT = 43200  # 12 часов

# Инициализация базы данных
def init_db():
    """Создает базу данных и таблицу, если они не существуют."""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            employee_number TEXT UNIQUE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_requests (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            employee_number TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Функции для работы с базой данных
def add_user_to_db(user_id, username, full_name, employee_number):
    """Добавляет пользователя в базу данных."""
    retries = 3
    for attempt in range(retries):
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO users (user_id, username, full_name, employee_number)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, full_name, employee_number))
            conn.commit()
            logger.info(f"Пользователь {user_id} добавлен в базу данных.")
            return
        except sqlite3.IntegrityError as e:
            logger.error(f"Ошибка при добавлении пользователя: {e}")
            if attempt == retries - 1:
                logger.error("Не удалось добавить пользователя после нескольких попыток.")
                return
        finally:
            conn.close()
        time.sleep(5)  # Ждем 5 секунд перед повторной попыткой

def is_user_in_db(user_id):
    """Проверяет, есть ли пользователь в базе данных."""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    logger.debug(f"Проверка пользователя {user_id} в базе данных: {'найден' if result else 'не найден'}")
    return result is not None

def add_access_request(user_id, username, full_name, employee_number):
    """Добавляет запрос на доступ в базу данных."""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO access_requests (user_id, username, full_name, employee_number)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, full_name, employee_number))
        conn.commit()
        logger.info(f"Запрос на доступ от пользователя {user_id} добавлен.")
    except sqlite3.IntegrityError as e:
        logger.error(f"Ошибка при добавлении запроса: {e}")
    finally:
        conn.close()

def get_access_requests():
    """Возвращает список запросов на доступ."""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM access_requests')
    result = cursor.fetchall()
    conn.close()
    return result

def delete_access_request(user_id):
    """Удаляет запрос на доступ."""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM access_requests WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.message.from_user
    logger.info(f"Пользователь {user.username} (ID: {user.id}) запустил команду /start")

    # Проверяем, авторизован ли пользователь
    if is_user_in_db(user.id):
        context.user_data['authenticated'] = True
        # Приветствие и список команд
        help_text = (
            f"Привет, {user.first_name}! Я механик Никитич.\n\n"
            "Доступные команды:\n\n"
            "/start - Начать работу с ботом\n"
            "/exit - Выйти из бота\n"
            "/help - Показать это сообщение\n"
            "/add_user - Добавить пользователя (только для владельца)\n"
            "/search - Поиск по базе данных\n\n"
            "Для навигации используйте кнопки или введите название раздела."
        )
        await update.message.reply_text(help_text)
        return await main_menu(update, context)
    else:
        # Создаем клавиатуру с кнопками
        keyboard = [
            [KeyboardButton("Отправить запрос")],
            [KeyboardButton("Помощь")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

        # Сообщение для неавторизованных пользователей
        await update.message.reply_text(
            "Доступ запрещен. Чтобы получить доступ, нажмите кнопку 'Отправить запрос'.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

# Обработка кнопки "Отправить запрос"
async def handle_request_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Отправить запрос'."""
    user = update.message.from_user
    logger.info(f"Пользователь {user.username} (ID: {user.id}) нажал кнопку 'Отправить запрос'.")

    # Проверяем, есть ли уже запрос от этого пользователя
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM access_requests WHERE user_id = ?', (user.id,))
    existing_request = cursor.fetchone()
    conn.close()

    if existing_request:
        await update.message.reply_text("Вы уже отправили запрос на доступ. Ожидайте одобрения.")
        return ConversationHandler.END

    # Запрашиваем табельный номер
    await update.message.reply_text("Введите ваш табельный номер для запроса доступа:")
    return AUTH

# Обработка ввода табельного номера
async def handle_employee_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода табельного номера."""
    user = update.message.from_user
    employee_number = update.message.text
    logger.info(f"Пользователь {user.username} (ID: {user.id}) ввел табельный номер: {employee_number}")

    # Добавляем запрос на доступ
    add_access_request(user.id, user.username, user.full_name, employee_number)

    # Уведомляем владельца
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"Новый запрос на доступ:\n\n"
             f"ID: {user.id}\n"
             f"Username: @{user.username}\n"
             f"Имя: {user.full_name}\n"
             f"Табельный номер: {employee_number}"
    )

    await update.message.reply_text("Ваш запрос на доступ отправлен владельцу бота.")
    return ConversationHandler.END

# Обработка кнопки "Помощь"
async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Помощь'."""
    help_text = (
        "Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/exit - Выйти из бота\n"
        "/help - Показать это сообщение\n"
        "/add_user - Добавить пользователя (только для владельца)\n"
        "/search - Поиск по базе данных\n\n"
        "Для навигации используйте кнопки или введите название раздела."
    )
    await update.message.reply_text(help_text)

# Команда /add_user (только для владельца)
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /add_user."""
    user = update.message.from_user
    if user.id != OWNER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Получаем список запросов на доступ
    requests = get_access_requests()
    if not requests:
        await update.message.reply_text("Нет запросов на доступ.")
        return

    # Формируем список запросов
    request_list = "\n".join(
        [f"ID: {req[0]}, Username: @{req[1]}, Имя: {req[2]}, Табельный номер: {req[3]}" for req in requests]
    )
    await update.message.reply_text(
        f"Запросы на доступ:\n\n{request_list}\n\n"
        "Чтобы добавить пользователя, введите его ID и табельный номер через пробел."
    )

    return AUTH

# Обработка добавления пользователя
async def handle_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик добавления пользователя."""
    user = update.message.from_user
    if user.id != OWNER_ID:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END

    try:
        user_id, employee_number = update.message.text.split()
        user_id = int(user_id)
    except ValueError:
        await update.message.reply_text("Неверный формат. Введите ID и табельный номер через пробел.")
        return AUTH

    # Добавляем пользователя в базу данных
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username, full_name FROM access_requests WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if not result:
        await update.message.reply_text("Запрос с таким ID не найден.")
        return AUTH

    username, full_name = result
    add_user_to_db(user_id, username, full_name, employee_number)
    delete_access_request(user_id)

    await update.message.reply_text(f"Пользователь {username} добавлен.")
    return ConversationHandler.END

# Функция для поиска по данным
def search_data(query, data, path=None):
    """Рекурсивно ищет совпадения в данных."""
    if path is None:
        path = []
    results = []

    logger.debug(f"Поиск в данных: {data}, путь: {path}")

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = path + [key]
            # Поиск в ключах (названиях разделов/подразделов)
            if query.lower() in key.lower():
                logger.debug(f"Найдено совпадение в ключе: {key}")
                results.append((new_path, value))
            # Рекурсивный поиск в значениях
            if isinstance(value, (dict, list, str)):
                results.extend(search_data(query, value, new_path))
    elif isinstance(data, list):
        for item in data:
            results.extend(search_data(query, item, path))
    elif isinstance(data, str):
        # Поиск в тексте описания
        if query.lower() in data.lower():
            logger.debug(f"Найдено совпадение в тексте: {data}")
            results.append((path, data))

    return results

# Обработчик команды /search
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /search."""
    user = update.message.from_user
    logger.info(f"Пользователь {user.username} (ID: {user.id}) запустил команду /search")

    # Проверяем, авторизован ли пользователь
    if not context.user_data.get('authenticated', False):
        await update.message.reply_text("Пожалуйста, авторизуйтесь с помощью команды /start.")
        return

    # Получаем текст после команды /search
    query = update.message.text.replace("/search", "").strip()

    # Если запрос пустой
    if not query:
        await update.message.reply_text("Введите ключевое слово для поиска после команды /search.")
        return

    logger.info(f"Пользователь {user.username} (ID: {user.id}) ищет: {query}")

    # Выполняем поиск
    results = search_data(query, sections)

    if not results:
        await update.message.reply_text("Ничего не найдено.")
        return

    # Формируем сообщение с результатами
    response = "Результаты поиска:\n\n"
    for path, value in results:
        # Форматируем путь (например, "Раздел > Подраздел > Под-подраздел")
        path_str = " > ".join(path)
        # Форматируем значение (если это описание)
        if isinstance(value, str):
            response += f"*{path_str}*:\n{value}\n\n"
        else:
            response += f"*{path_str}*\n\n"

    await update.message.reply_text(response, parse_mode="Markdown")

# Главное меню
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает главное меню."""
    try:
        # Сбрасываем путь пользователя
        context.user_data['path'] = []

        # Создаем клавиатуру с разделами
        keyboard = [[section] for section in sections.keys()]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите главу...")

        await update.message.reply_text(
            "Выберите главу:",
            reply_markup=reply_markup
        )
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Ошибка при отображении главного меню: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")
        return MAIN_MENU

# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    retries = 3
    for attempt in range(retries):
        try:
            # Проверяем, авторизован ли пользователь
            if not context.user_data.get('authenticated', False):
                await update.message.reply_text("Пожалуйста, авторизуйтесь с помощью команды /start.")
                return

            text = update.message.text
            user = update.message.from_user
            logger.info(f"Пользователь {user.username} (ID: {user.id}) отправил сообщение: {text}")

            # Обновляем время последней активности пользователя
            context.bot_data['active_users'][user.id] = datetime.now()

            # Если нажата кнопка "Назад"
            if text == "Назад":
                if context.user_data['path']:
                    context.user_data['path'].pop()  # Возвращаемся на уровень выше
                await show_current_level(update, context)
                return

            # Если нажата кнопка "Главное меню"
            if text == "Главное меню":
                return await main_menu(update, context)

            # Если введена команда /start
            if text == "/start":
                return await start(update, context)

            # Текущий путь пользователя
            current_path = context.user_data['path']

            # Если выбран раздел
            if not current_path and text in sections:
                context.user_data['path'] = [text]  # Начинаем новый путь
                await show_current_level(update, context)

            # Если выбран подраздел
            elif len(current_path) == 1:
                current_section = current_path[0]
                if text in sections[current_section]:
                    context.user_data['path'].append(text)  # Добавляем подраздел в путь
                    await show_current_level(update, context)

            # Если выбран под-подраздел
            elif len(current_path) == 2:
                current_section, current_subsection = current_path
                if text in sections[current_section][current_subsection]:
                    context.user_data['path'].append(text)  # Добавляем под-подраздел в путь
                    description = sections[current_section][current_subsection][text]

                    # Форматируем описание
                    formatted_description = format_description(description)

                    # Экранируем специальные символы
                    escaped_text = escape_markdown(text)
                    escaped_description = escape_markdown(formatted_description)

                    # Форматируем текст
                    formatted_text = (
                        f"*{escaped_text}*\n"  # Название под-подраздела жирным шрифтом
                        "────────────\n"       # Разделитель
                        f"_{escaped_description}_"  # Описание курсивом
                    )
                    await update.message.reply_text(formatted_text, parse_mode="MarkdownV2")

                    # После выбора под-подраздела показываем кнопки "Назад" и "Главное меню"
                    keyboard = [["Назад", "Главное меню"]]
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    await update.message.reply_text(
                        "Используйте кнопки для навигации.",
                        reply_markup=reply_markup
                    )

            # Если сообщение не распознано
            else:
                await update.message.reply_text("Неизвестная команда. Пожалуйста, выберите раздел, подраздел или под-подраздел.")
            return
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
            if attempt == retries - 1:
                await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")
            await asyncio.sleep(5)  # Ждем 5 секунд перед повторной попыткой

# Функция для отображения текущего уровня меню
async def show_current_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает текущий уровень меню на основе пути пользователя."""
    try:
        current_path = context.user_data['path']

        # Если путь пуст, показываем разделы
        if not current_path:
            keyboard = [[section] for section in sections.keys()]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите главу...")
            await update.message.reply_text(
                "Выберите главу:",
                reply_markup=reply_markup
            )
            return

        # Если выбран раздел, показываем подразделы
        if len(current_path) == 1:
            current_section = current_path[0]
            keyboard = [[subsection] for subsection in sections[current_section].keys()]
            keyboard.append(["Назад", "Главное меню"])  # Добавляем кнопки "Назад" и "Главное меню"
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите подраздел...")
            await update.message.reply_text(
                f"Вы выбрали раздел '{current_section}'. Выберите подраздел:",
                reply_markup=reply_markup
            )
            return

        # Если выбран подраздел, показываем под-подразделы (если они есть) и кнопки "Назад" и "Главное меню"
        if len(current_path) == 2:
            current_section, current_subsection = current_path
            subsubsections = sections[current_section][current_subsection]

            # Если есть под-подразделы, показываем их
            if isinstance(subsubsections, dict):
                keyboard = [[subsubsection] for subsubsection in subsubsections.keys()]
            else:
                keyboard = []

            # Добавляем кнопки "Назад" и "Главное меню"
            keyboard.append(["Назад", "Главное меню"])

            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите под-подраздел...")
            await update.message.reply_text(
                f"Вы выбрали подраздел '{current_subsection}'. Выберите под-подраздел:",
                reply_markup=reply_markup
            )
            return
    except Exception as e:
        logger.error(f"Ошибка при отображении текущего уровня меню: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")

# Команда /exit
async def exit_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /exit."""
    try:
        user = update.message.from_user
        logger.info(f"Пользователь {user.username} (ID: {user.id}) вышел из бота.")

        if not context.user_data.get('authenticated', False):
            await update.message.reply_text("Вы не авторизованы.")
            return

        # Очищаем данные пользователя
        context.user_data.clear()

        await update.message.reply_text("Вы вышли из бота. Для повторной авторизации используйте команду /start.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка при выходе из бота: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")

# Функция для проверки неактивности пользователей
async def check_inactivity(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет неактивность пользователей и выполняет автоматический выход."""
    try:
        current_time = datetime.now()
        for user_id, last_active in list(context.bot_data['active_users'].items()):
            if (current_time - last_active).total_seconds() > INACTIVITY_TIMEOUT:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="Вы были автоматически вышли из бота из-за неактивности. Для повторной авторизации используйте команду /start."
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                finally:
                    # Удаляем пользователя из списка активных
                    if user_id in context.bot_data['active_users']:
                        del context.bot_data['active_users'][user_id]
    except Exception as e:
        logger.error(f"Ошибка при проверке неактивности: {e}", exc_info=True)

# Обработка ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок."""
    logger.error(f"Ошибка: {context.error}", exc_info=True)

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    help_text = (
        "Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/exit - Выйти из бота\n"
        "/help - Показать это сообщение\n"
        "/add_user - Добавить пользователя (только для владельца)\n"
        "/search - Поиск по базе данных\n\n"
        "Для навигации используйте кнопки или введите название раздела."
    )
    await update.message.reply_text(help_text)

# Основная функция
def main():
    """Запуск бота."""
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            # Создаем приложение
            application = Application.builder().token(TOKEN).build()

            # Инициализируем bot_data
            application.bot_data['active_users'] = {}

            # Создаем ConversationHandler для авторизации
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler("start", start)],
                states={
                    AUTH: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_employee_number),
                    ],
                    MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
                },
                fallbacks=[
                    CommandHandler("start", start),
                    CommandHandler("exit", exit_bot),
                ]
            )

            # Регистрируем обработчики
            application.add_handler(conv_handler)
            application.add_handler(MessageHandler(filters.Text("Отправить запрос"), handle_request_access))
            application.add_handler(MessageHandler(filters.Text("Помощь"), handle_help))
            application.add_handler(CommandHandler("add_user", add_user))
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("search", search_command))  # Регистрируем команду /search

            # Регистрируем обработчик ошибок
            application.add_error_handler(error_handler)

            # Запускаем JobQueue для проверки неактивности
            if application.job_queue:
                application.job_queue.run_repeating(
                    check_inactivity,
                    interval=60.0,  # Проверка каждую минуту
                    first=0.0,
                )
            else:
                logger.warning("JobQueue не доступен. Проверка неактивности отключена.")

            # Запускаем бота
            logger.info("Бот запущен...")
            application.run_polling()
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)
            retry_count += 1
            logger.info(f"Попытка перезапуска бота через 10 секунд... (Попытка {retry_count}/{max_retries})")
            time.sleep(10)
    logger.error("Бот не может быть запущен после нескольких попыток.")

if __name__ == '__main__':
    main()