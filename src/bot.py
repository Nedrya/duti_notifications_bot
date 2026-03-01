#!/usr/bin/env python3
"""
Telegram bot for duty schedule notifications.
"""
import os
import sys
import logging
import fcntl
import atexit
import socket
import time
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler
from telegram.request import HTTPXRequest

from config import Config
from google_sheets import GoogleSheetsClient
from handlers import DutyBotHandlers

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def check_single_instance():
    """Prevent multiple bot instances with aggressive cleanup."""
    hostname = socket.gethostname()
    token_hash = abs(hash(Config.TELEGRAM_TOKEN)) % 10000
    lock_file = f'/tmp/telegram_duty_bot_{token_hash}_{hostname}.lock'

    logger.info(f"Attempting to acquire lock: {lock_file}")

    # Clean up old lock files
    try:
        for f in os.listdir('/tmp'):
            if f.startswith('telegram_duty_bot_'):
                old_lock = os.path.join('/tmp', f)
                try:
                    # Remove locks older than 1 hour
                    if time.time() - os.path.getmtime(old_lock) > 3600:
                        os.unlink(old_lock)
                        logger.info(f"Removed old lock: {old_lock}")
                except:
                    pass
    except:
        pass

    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o666)

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("✓ Lock acquired")
        except (IOError, OSError, BlockingIOError):
            # Lock exists - check if process is alive
            try:
                with open(lock_file, 'r') as f:
                    old_pid = int(f.read().strip())

                try:
                    os.kill(old_pid, 0)
                    logger.error(f"✗ Bot already running with PID: {old_pid}")
                    os.close(fd)
                    return False
                except OSError:
                    # Process is dead - remove lock
                    logger.warning(f"Removing stale lock from PID {old_pid}")
                    os.close(fd)
                    os.unlink(lock_file)
                    # Try again
                    return check_single_instance()
            except:
                os.close(fd)
                return False

        # Write current PID
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)

        def unlock():
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                try:
                    os.unlink(lock_file)
                    logger.info("Lock file removed")
                except:
                    pass
            except:
                pass

        atexit.register(unlock)
        logger.info(f"✓ Single instance lock acquired (PID: {os.getpid()})")
        return True

    except Exception as e:
        logger.error(f"Failed to acquire lock: {e}")
        return False


async def post_init(application: Application):
    """Log bot startup."""
    now = datetime.now(pytz.timezone('Europe/Moscow'))
    mode = "TEST" if application.bot_data.get('test_mode', False) else "PRODUCTION"
    logger.info(f"🚀 Bot started in {mode} mode at {now.strftime('%d.%m.%Y %H:%M:%S')} MSK")

    try:
        bot_info = await application.bot.get_me()
        logger.info(f"🤖 Bot username: @{bot_info.username}")
    except Exception as e:
        logger.error(f"Failed to get bot info: {e}")


def main():
    """Start the bot."""
    # Load configuration
    try:
        Config.validate()
        logger.info("✅ Configuration loaded successfully")
    except ValueError as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)

    # Check single instance
    if not check_single_instance():
        logger.error("❌ Another instance is running. Exiting.")
        sys.exit(1)

    try:
        # Setup timezone
        moscow_tz = pytz.timezone('Europe/Moscow')

        # Initialize Google Sheets client
        google_client = GoogleSheetsClient(
            credentials_file=Config.GOOGLE_CREDENTIALS_FILE,
            spreadsheet_id=Config.SPREADSHEET_ID,
            timezone=moscow_tz
        )

        # Initialize handlers
        handlers = DutyBotHandlers(Config, google_client, Config.TEST_MODE)

        # Create HTTP request with timeouts
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0
        )

        # Build application
        app = Application.builder() \
            .token(Config.TELEGRAM_TOKEN) \
            .request(request) \
            .post_init(post_init) \
            .build()

        # Store test mode in bot_data
        app.bot_data['test_mode'] = Config.TEST_MODE
        app.bot_data['notification_sent_today'] = False

        # Check job queue
        if app.job_queue is None:
            logger.error("❌ JobQueue not available")
            return

        # Add command handlers
        app.add_handler(CommandHandler("duty", handlers.cmd_duty))
        app.add_handler(CommandHandler("time", handlers.cmd_time))
        app.add_handler(CommandHandler("test", handlers.cmd_test))
        app.add_handler(CommandHandler("chatid", handlers.cmd_chatid))
        app.add_handler(CommandHandler("status", handlers.cmd_status))
        app.add_handler(CommandHandler("test_on", handlers.cmd_test_on))
        app.add_handler(CommandHandler("test_off", handlers.cmd_test_off))
        app.add_handler(CommandHandler("reset_rate", handlers.cmd_reset_rate_limit))
        app.add_handler(CommandHandler("calendar", handlers.cmd_check_calendar))
        app.add_handler(CommandHandler("test_api", handlers.cmd_test_api))

        # Setup jobs based on mode
        if Config.TEST_MODE:
            # Test mode: every minute
            app.job_queue.run_once(
                handlers.send_notification,
                when=10,
                name="test_once"
            )
            app.job_queue.run_repeating(
                handlers.send_notification,
                interval=60,
                first=70,
                name="test_repeating"
            )
            logger.info("🔴 Test mode: notifications every minute")
        else:
            # Production mode: daily at specified time
            notification_time = time(
                hour=Config.NOTIFY_HOUR,
                minute=Config.NOTIFY_MINUTE,
                second=0,
                tzinfo=moscow_tz
            )

            app.job_queue.run_daily(
                handlers.send_notification,
                time=notification_time,
                days=tuple(range(7)),
                name="daily"
            )

            logger.info(f"🟢 Production mode: daily at {Config.NOTIFY_HOUR:02d}:{Config.NOTIFY_MINUTE:02d} MSK")

        # Start bot
        logger.info("🔄 Starting bot polling...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()