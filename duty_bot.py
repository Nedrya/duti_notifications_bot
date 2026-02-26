import os
import sys
import logging
import fcntl
import atexit
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import get_effective_format

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8657007079:AAEFKtekvKXWEWrQX3Vo_44IvQ76PZv7MGg"
# GROUP_CHAT_ID = 1002668420862
GROUP_CHAT_ID = -5279863371

SPREADSHEET_ID = "1xAl6gC4PS__2dPnvLGJ4kPRIud--gucJiLX5Z3sXFkw"

# Service account credentials JSON file
CREDENTIALS_FILE = "service_account.json"

# Время для отправки (для продакшена - 9:00 MSK)
NOTIFY_HOUR = 12
NOTIFY_MINUTE = 40
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

ADMIN_USER_ID = 995425006

# Глобальная переменная для тестового режима
test_mode = False
# ──────────────────────────────────────────────────────────────────────────────

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def check_single_instance():
    """
    Проверяет, не запущен ли уже бот.
    Использует файловую блокировку для предотвращения множественных экземпляров.
    """
    lock_file = '/tmp/telegram_duty_bot.lock'

    try:
        # Открываем файл блокировки
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o666)

        # Пытаемся получить эксклюзивную блокировку
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Записываем PID текущего процесса
        os.write(fd, str(os.getpid()).encode())

        # Регистрируем функцию для снятия блокировки при выходе
        def unlock():
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                os.unlink(lock_file)
            except:
                pass

        atexit.register(unlock)

        logger.info("✓ Получена блокировка - бот может работать")
        return True

    except (IOError, OSError, BlockingIOError):
        # Не удалось получить блокировку - бот уже запущен
        logger.error("✗ Бот уже запущен! Завершаем работу.")

        # Пытаемся прочитать PID запущенного процесса
        try:
            with open(lock_file, 'r') as f:
                pid = f.read().strip()
                logger.error(f"Запущенный процесс имеет PID: {pid}")
                logger.error("Используйте 'kill -9 PID' для остановки")
        except:
            pass

        return False


def get_google_client():
    """Authenticate with Google Sheets API using service account."""
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error(f"Файл {CREDENTIALS_FILE} не найден!")
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Ошибка авторизации Google Sheets: {e}")
        return None


def get_sheet_name_for_current_month() -> str:
    """Return sheet name like 'Февраль 2026'."""
    months_ru = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
        5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    now = datetime.now(MOSCOW_TZ)
    return f"{months_ru[now.month]} {now.year}"


def find_date_column_index(headers: list, today: datetime) -> int:
    """
    Find column index for today's date.
    Headers are like: ['Сотрудники', '01.02', '02.02', '03.02', ...]
    """
    today_str = today.strftime("%d.%m")
    logger.info(f"Looking for date: {today_str}")

    for i, header in enumerate(headers):
        header_str = str(header).strip()
        if header_str == today_str:
            logger.info(f"Found date column at index {i}: {header_str}")
            return i

    logger.warning(f"Date column for {today_str} not found")
    return -1


def get_cell_color(worksheet, row: int, col: int):
    """
    Получает цвет ячейки с помощью gspread-formatting.
    row и col - индексы (1-based, как в Google Sheets)
    """
    try:
        # Конвертируем номер колонки в букву (A, B, C, ...)
        if col <= 26:
            col_letter = chr(64 + col)
        else:
            first = chr(64 + (col - 1) // 26)
            second = chr(65 + (col - 1) % 26)
            col_letter = f"{first}{second}"

        cell_label = f"{col_letter}{row}"

        # Получаем форматирование ячейки
        cell_format = get_effective_format(worksheet, cell_label)

        if cell_format and hasattr(cell_format, 'backgroundColor'):
            bg = cell_format.backgroundColor

            red = getattr(bg, 'red', 0.0)
            green = getattr(bg, 'green', 0.0)
            blue = getattr(bg, 'blue', 0.0)

            red = red if red is not None else 0.0
            green = green if green is not None else 0.0
            blue = blue if blue is not None else 0.0

            return {
                'red': float(red),
                'green': float(green),
                'blue': float(blue)
            }
    except Exception as e:
        logger.debug(f"Error getting color for {cell_label}: {e}")

    return None


def is_colored(color_dict) -> bool:
    """Проверяет, есть ли у ячейки цвет (не белый/прозрачный)"""
    if not color_dict:
        return False

    red = color_dict.get('red', 0.0)
    green = color_dict.get('green', 0.0)
    blue = color_dict.get('blue', 0.0)

    red = float(red) if red is not None else 0.0
    green = float(green) if green is not None else 0.0
    blue = float(blue) if blue is not None else 0.0

    # Считаем, что цвет есть, если хотя бы один компонент > 0.1
    # И это не близко к белому
    is_white = red > 0.9 and green > 0.9 and blue > 0.9

    return (red > 0.1 or green > 0.1 or blue > 0.1) and not is_white


def is_green_color(color_dict) -> bool:
    """Проверяет, является ли цвет зеленым"""
    if not color_dict:
        return False

    red = color_dict.get('red', 0.0)
    green = color_dict.get('green', 0.0)
    blue = color_dict.get('blue', 0.0)

    red = float(red) if red is not None else 0.0
    green = float(green) if green is not None else 0.0
    blue = float(blue) if blue is not None else 0.0

    # Зеленый цвет: зеленый компонент значительно выше красного и синего
    try:
        is_green = (green > 0.3 and
                    green > red * 1.5 and
                    green > blue * 1.5)

        if is_green:
            logger.debug(f"Green color detected: R={red:.2f}, G={green:.2f}, B={blue:.2f}")

        return is_green

    except (TypeError, ZeroDivisionError):
        return False


def get_today_duty() -> str:
    """Read the spreadsheet and return today's duty info as a string."""
    today = datetime.now(MOSCOW_TZ)
    sheet_name = get_sheet_name_for_current_month()

    logger.info(f"Looking for sheet: '{sheet_name}'")

    try:
        client = get_google_client()
        if client is None:
            return "❌ Не удалось подключиться к Google Sheets. Проверьте файл service_account.json"

        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        # Find the worksheet for current month
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            all_worksheets = spreadsheet.worksheets()
            worksheet_names = [w.title for w in all_worksheets]
            return f"❌ Не найден лист '{sheet_name}'.\nДоступные листы: {', '.join(worksheet_names)}"

        # Получаем все значения (только текст)
        all_values = worksheet.get_all_values()

        if not all_values or len(all_values) < 2:
            return "❌ Лист пустой или содержит только заголовки."

        # Заголовки - первая строка
        headers = all_values[0]

        # Находим колонку с сегодняшней датой
        date_col = find_date_column_index(headers, today)

        if date_col == -1:
            sample_headers = headers[:10]
            return (f"❌ Не найден столбец с датой {today.strftime('%d.%m')}.\n"
                    f"Заголовки: {sample_headers}...")

        # Колонка с сотрудниками - первая (индекс 0)
        employee_col = 0

        # Собираем ведущих и ведомых
        leaders = []
        followers = []

        # Проходим по всем строкам с сотрудниками
        for row_idx, row in enumerate(all_values[1:], start=2):
            if len(row) <= max(employee_col, date_col):
                continue

            employee_name = row[employee_col].strip() if len(row) > employee_col else ""

            if not employee_name:
                continue

            # Получаем цвет ячейки для сегодняшней даты
            cell_color = get_cell_color(worksheet, row_idx, date_col + 1)

            if cell_color and is_colored(cell_color):
                if is_green_color(cell_color):
                    leaders.append(employee_name)
                else:
                    followers.append(employee_name)
            else:
                # Если нет цвета, проверяем наличие текста
                cell_value = row[date_col].strip() if len(row) > date_col else ""
                if cell_value:
                    followers.append(employee_name)

        date_str = today.strftime("%d.%m.%Y")

        logger.info(f"Found {len(leaders)} leaders, {len(followers)} followers")

        if not leaders and not followers:
            return f"ℹ️ На {date_str} дежурные не назначены."

        # Формируем сообщение
        message_parts = [f"📋 <b>Дежурство на {date_str}</b>"]

        if leaders:
            leaders_list = "\n".join([f"• {name}" for name in leaders])
            leader_word = "Ведущий" if len(leaders) == 1 else "Ведущие"
            message_parts.append(f"👤 <b>{leader_word}:</b>\n{leaders_list}")

        if followers:
            followers_list = "\n".join([f"• {name}" for name in followers])
            follower_word = "Ведомый" if len(followers) == 1 else "Ведомые"
            message_parts.append(f"👥 <b>{follower_word}:</b>\n{followers_list}")

        return "\n\n".join(message_parts)

    except Exception as e:
        logger.error(f"Error getting duty: {e}", exc_info=True)
        return f"❌ Ошибка при чтении таблицы: {str(e)}"


# ─── TELEGRAM HANDLERS ────────────────────────────────────────────────────────

async def cmd_duty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /duty command — shows today's duty manually."""
    logger.info(f"Command /duty received from user {update.effective_user.id}")
    message = get_today_duty()
    await update.message.reply_html(message)


async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /time command — shows current Moscow time."""
    now = datetime.now(MOSCOW_TZ)
    mode_status = "ТЕСТОВЫЙ РЕЖИМ" if test_mode else "РАБОЧИЙ РЕЖИМ"
    await update.message.reply_text(
        f"🕐 Текущее время в Москве: {now.strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"Режим: {mode_status}"
    )


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /test command — immediately send test notification."""
    logger.info(f"Command /test received from user {update.effective_user.id}")
    message = get_today_duty()
    await update.message.reply_html(f"🧪 ТЕСТОВОЕ СООБЩЕНИЕ\n\n{message}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /status command — show current mode and job status."""
    mode_status = "🔴 ТЕСТОВЫЙ РЕЖИМ" if test_mode else "🟢 РАБОЧИЙ РЕЖИМ"

    # Получаем информацию о запланированных задачах
    jobs_info = []
    if context.job_queue:
        for job in context.job_queue.jobs():
            next_run = job.next_t if hasattr(job, 'next_t') else "неизвестно"
            jobs_info.append(f"• {job.name}: следующее в {next_run}")

    jobs_text = "\n".join(jobs_info) if jobs_info else "Нет активных задач"

    await update.message.reply_text(
        f"📊 <b>Статус бота</b>\n\n"
        f"Режим: {mode_status}\n"
        f"Группа для уведомлений: {GROUP_CHAT_ID}\n"
        f"Время уведомления: {NOTIFY_HOUR:02d}:{NOTIFY_MINUTE:02d} MSK\n\n"
        f"<b>Активные задачи:</b>\n{jobs_text}",
        parse_mode="HTML"
    )


# Команды для администратора
async def cmd_test_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включить тестовый режим (только для администратора)."""
    user_id = update.effective_user.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды.")
        return

    global test_mode
    if test_mode:
        await update.message.reply_text("⚠️ Тестовый режим уже включен.")
        return

    test_mode = True

    # Перезапускаем задачи с новым режимом
    if context.job_queue:
        # Удаляем старые задачи
        for job in context.job_queue.jobs():
            job.schedule_removal()

        # Добавляем тестовые задачи
        context.job_queue.run_once(
            send_daily_notification,
            when=10,
            name="test_notification"
        )

        context.job_queue.run_repeating(
            send_daily_notification,
            interval=60,
            first=70,
            name="test_notification"
        )

        await update.message.reply_text(
            "✅ Тестовый режим ВКЛЮЧЕН\n"
            "Уведомления будут отправляться каждую минуту.\n"
            "Используйте /test_off для выключения."
        )

        # Отправляем уведомление в группу
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text="🔴 <b>Включен тестовый режим</b>\nУведомления будут приходить каждую минуту.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ JobQueue не доступен")


async def cmd_test_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выключить тестовый режим (только для администратора)."""
    user_id = update.effective_user.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ У вас нет прав для выполнения этой команды.")
        return

    global test_mode
    if not test_mode:
        await update.message.reply_text("⚠️ Тестовый режим уже выключен.")
        return

    test_mode = False

    # Перезапускаем задачи с рабочим режимом
    if context.job_queue:
        # Удаляем старые задачи
        for job in context.job_queue.jobs():
            job.schedule_removal()

        # Добавляем ежедневную задачу
        notification_time = time(hour=NOTIFY_HOUR, minute=NOTIFY_MINUTE, second=0, tzinfo=MOSCOW_TZ)

        context.job_queue.run_daily(
            send_daily_notification,
            time=notification_time,
            days=tuple(range(7)),
            name="daily_notification"
        )

        await update.message.reply_text(
            f"✅ Тестовый режим ВЫКЛЮЧЕН\n"
            f"Уведомления будут отправляться ежедневно в {NOTIFY_HOUR:02d}:{NOTIFY_MINUTE:02d} MSK."
        )

        # Отправляем уведомление в группу
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=f"🟢 <b>Выключен тестовый режим</b>\nУведомления будут приходить ежедневно в {NOTIFY_HOUR:02d}:{NOTIFY_MINUTE:02d} MSK.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ JobQueue не доступен")


async def send_daily_notification(context: ContextTypes.DEFAULT_TYPE):
    """Job callback — sends duty notification to the group."""
    try:
        now = datetime.now(MOSCOW_TZ)
        message = get_today_duty()

        if test_mode:
            full_message = f"⏱️ <b>Тестовое уведомление</b> ({now.strftime('%H:%M:%S')})\n\n{message}"
        else:
            full_message = message

        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=full_message,
            parse_mode="HTML"
        )
        logger.info(f"Notification sent at {now.strftime('%H:%M:%S')} MSK")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


async def post_init(application: Application):
    """Run after application initialization."""
    now = datetime.now(MOSCOW_TZ)

    mode_text = "ТЕСТОВЫЙ РЕЖИМ" if test_mode else "РАБОЧИЙ РЕЖИМ"
    logger.info(f"Bot started in {mode_text} at {now.strftime('%d.%m.%Y %H:%M:%S')} MSK")

    try:
        bot_info = await application.bot.get_me()
        logger.info(f"Bot username: @{bot_info.username}")
    except Exception as e:
        logger.error(f"Failed to get bot info: {e}")

    if not os.path.exists(CREDENTIALS_FILE):
        logger.error(f"Файл {CREDENTIALS_FILE} не найден!")

    # УБРАНО: сообщение о запуске в группу


def main():
    """Start the bot."""
    # Проверяем, не запущен ли уже бот
    if not check_single_instance():
        sys.exit(1)

    try:
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0
        )

        app = Application.builder() \
            .token(TELEGRAM_TOKEN) \
            .request(request) \
            .post_init(post_init) \
            .build()

        if app.job_queue is None:
            logger.error("JobQueue is not available. Install with: pip install 'python-telegram-bot[job-queue]'")
            return

        # Добавляем обработчики команд
        app.add_handler(CommandHandler("duty", cmd_duty))
        app.add_handler(CommandHandler("time", cmd_time))
        app.add_handler(CommandHandler("test", cmd_test))
        app.add_handler(CommandHandler("status", cmd_status))

        # Админские команды
        app.add_handler(CommandHandler("test_on", cmd_test_on))
        app.add_handler(CommandHandler("test_off", cmd_test_off))

        # Настраиваем задачи в зависимости от режима
        if test_mode:
            # ТЕСТОВЫЙ РЕЖИМ: отправляем каждую минуту
            app.job_queue.run_once(
                send_daily_notification,
                when=10,
                name="test_notification"
            )

            app.job_queue.run_repeating(
                send_daily_notification,
                interval=60,
                first=70,
                name="test_notification"
            )

            logger.info("Тестовый режим: уведомления будут отправляться каждую минуту")
        else:
            # РАБОЧИЙ РЕЖИМ: отправляем ежедневно в 10:00 MSK
            notification_time = time(hour=NOTIFY_HOUR, minute=NOTIFY_MINUTE, second=0, tzinfo=MOSCOW_TZ)

            app.job_queue.run_daily(
                send_daily_notification,
                time=notification_time,
                days=tuple(range(7)),
                name="daily_notification"
            )

            logger.info(f"Рабочий режим: ежедневные уведомления в {NOTIFY_HOUR:02d}:{NOTIFY_MINUTE:02d} MSK")

        # Запускаем бота
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()