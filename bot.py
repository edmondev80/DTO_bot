import os
import json
import logging
import re
import hashlib
import random
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
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
)
logger = logging.getLogger(__name__)

# Загружаем переменные из .env
load_dotenv()

# Получаем токен
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Токен не найден. Убедитесь, что переменная окружения TELEGRAM_BOT_TOKEN установлена.")

# Загружаем разрешенных пользователей из .env
ALLOWED_USERS = {}
allowed_users_str = os.getenv("ALLOWED_USERS", "")
if allowed_users_str:
    for user in allowed_users_str.split(","):
        employee_number = user.strip()  # Убираем лишние пробелы
        ALLOWED_USERS[employee_number] = True
else:
    raise ValueError("Список пользователей не найден. Убедитесь, что переменная ALLOWED_USERS установлена в .env.")

# Загружаем соль для хэширования
SALT = os.getenv("HASH_SALT", "default_salt")  # Соль для хэширования

# Загружаем данные из JSON-файла
def load_data():
    """Загружает данные из файла data.json."""
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Файл data.json не найден.")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON в файле data.json: {e}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при загрузке данных: {e}")
        return None

sections = load_data()
if not sections:
    logger.error("Не удалось загрузить данные. Бот завершает работу.")
    exit(1)

# Состояния для ConversationHandler
AUTH, TWO_FACTOR, MAIN_MENU = range(3)

# Глобальный словарь для хранения авторизованных пользователей
active_users = {}  # Ключ: user.id, значение: время последней активности
authorized_numbers = {}  # Ключ: хэш табельного номера, значение: user.id

# Время неактивности для автоматического выхода (в секундах)
INACTIVITY_TIMEOUT = 300  # 5 минут

# Функция для хэширования табельных номеров
def hash_employee_number(employee_number):
    """Хэширует табельный номер с использованием SHA-256 и соли."""
    return hashlib.sha256((employee_number + SALT).encode()).hexdigest()

# Функция для генерации случайного кода двухфакторной аутентификации
def generate_two_factor_code():
    """Генерирует случайный 6-значный код."""
    return str(random.randint(100000, 999999))

# Функция для форматирования описания
def format_description(description):
    """Форматирует описание для удобного отображения."""
    if isinstance(description, dict):
        # Если описание — это словарь, преобразуем его в читаемый текст
        formatted_text = ""
        for key, value in description.items():
            formatted_text += f"• *{key}*: _{value}_\n"
        return formatted_text.strip()
    elif isinstance(description, str):
        # Если описание — это строка, возвращаем как есть
        return description
    else:
        # Если описание — другой тип, преобразуем в строку
        return str(description)

# Функция для экранирования специальных символов
def escape_markdown(text):
    """Экранирует специальные символы для MarkdownV2."""
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.message.from_user
    logger.info(f"Пользователь {user.username} запустил команду /start")

    # Сбрасываем состояние пользователя
    context.user_data.clear()

    # Удаляем пользователя из списка активных
    if user.id in active_users:
        del active_users[user.id]

    # Приветствуем пользователя по имени
    await update.message.reply_text(f"Привет, {user.first_name}! Добро пожаловать.")

    # Запрашиваем табельный номер
    await update.message.reply_text("Введите ваш табельный номер для авторизации:")
    return AUTH

# Обработка ввода табельного номера
async def authenticate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик авторизации по табельному номеру."""
    employee_number = update.message.text
    user = update.message.from_user
    logger.info(f"Пользователь {user.username} ввел табельный номер: {employee_number}")

    try:
        # Хэшируем табельный номер
        hashed_number = hash_employee_number(employee_number)
        logger.info(f"Хэшированный номер для {employee_number}: {hashed_number}")

        # Проверяем, есть ли номер в списке разрешенных
        if employee_number in ALLOWED_USERS:
            # Сохраняем данные пользователя
            context.user_data['employee_number'] = employee_number
            context.user_data['hashed_number'] = hashed_number

            # Генерируем двухфакторный код
            two_factor_code = generate_two_factor_code()
            context.user_data['two_factor_code'] = two_factor_code

            await update.message.reply_text(f"Табельный номер подтвержден. Введите код двухфакторной аутентификации: {two_factor_code}")
            return TWO_FACTOR
        else:
            await update.message.reply_text("Табельный номер не найден. Попробуйте еще раз.")
            return AUTH
    except Exception as e:
        logger.error(f"Ошибка при авторизации: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при авторизации. Попробуйте еще раз.")
        return AUTH

# Обработка двухфакторной аутентификации
async def two_factor_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик двухфакторной аутентификации."""
    user = update.message.from_user
    code = update.message.text
    logger.info(f"Пользователь {user.username} ввел код двухфакторной аутентификации: {code}")

    try:
        # Проверяем код
        if code == context.user_data.get('two_factor_code'):
            # Авторизуем пользователя
            context.user_data['authenticated'] = True

            # Добавляем пользователя в список активных
            active_users[user.id] = datetime.now()

            # Связываем хэш табельного номера с user.id
            authorized_numbers[context.user_data['hashed_number']] = user.id

            await update.message.reply_text(f"Двухфакторная аутентификация успешна. Привет, {user.first_name}!")
            return await main_menu(update, context)
        else:
            await update.message.reply_text("Неверный код. Попробуйте еще раз.")
            return TWO_FACTOR
    except Exception as e:
        logger.error(f"Ошибка при двухфакторной аутентификации: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")
        return TWO_FACTOR

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
    try:
        # Проверяем, авторизован ли пользователь
        if not context.user_data.get('authenticated', False):
            await update.message.reply_text("Пожалуйста, авторизуйтесь с помощью команды /start.")
            return

        text = update.message.text
        user = update.message.from_user
        logger.info(f"Пользователь {user.username} отправил сообщение: {text}")

        # Обновляем время последней активности пользователя
        active_users[user.id] = datetime.now()

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
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")

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
        logger.info(f"Пользователь {user.username} вышел из бота.")

        if not context.user_data.get('authenticated', False):
            await update.message.reply_text("Вы не авторизованы.")
            return

        # Очищаем данные пользователя
        hashed_number = context.user_data.get('hashed_number')
        if hashed_number:
            # Удаляем связь хэша табельного номера с user.id
            if hashed_number in authorized_numbers:
                del authorized_numbers[hashed_number]

        context.user_data.clear()

        # Удаляем пользователя из списка активных
        if user.id in active_users:
            del active_users[user.id]

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
        for user_id, last_active in list(active_users.items()):
            if (current_time - last_active).total_seconds() > INACTIVITY_TIMEOUT:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="Вы сейчас автоматически вышли из бота из-за неактивности. Для повторной авторизации используйте команду /start."
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                finally:
                    del active_users[user_id]

                    # Удаляем связь хэша табельного номера с user.id
                    for hashed_num, u_id in list(authorized_numbers.items()):
                        if u_id == user_id:
                            del authorized_numbers[hashed_num]
                            break
    except Exception as e:
        logger.error(f"Ошибка при проверке неактивности: {e}", exc_info=True)

# Обработка ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок."""
    logger.error(f"Ошибка: {context.error}", exc_info=True)

# Основная функция
def main():
    """Запуск бота."""
    try:
        # Создаем приложение
        application = Application.builder().token(TOKEN).build()

        # Создаем ConversationHandler для авторизации
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                AUTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, authenticate)],
                TWO_FACTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, two_factor_auth)],
                MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
            },
            fallbacks=[CommandHandler("start", start), CommandHandler("exit", exit_bot)]  # Добавляем /start в fallbacks
        )

        # Регистрируем обработчики
        application.add_handler(conv_handler)

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

if __name__ == '__main__':
    main()