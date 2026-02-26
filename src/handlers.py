import logging
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class DutyBotHandlers:
    """Handlers for Telegram bot commands."""

    def __init__(self, config, google_client, test_mode):
        self.config = config
        self.google_client = google_client
        self.test_mode = test_mode
        self.moscow_tz = pytz.timezone('Europe/Moscow')

    async def cmd_duty(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /duty command."""
        logger.info(f"Command /duty from user {update.effective_user.id}")
        message = self.google_client.get_today_duty()
        await update.message.reply_html(message)

    async def cmd_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /time command."""
        now = datetime.now(self.moscow_tz)
        mode_status = "ТЕСТОВЫЙ РЕЖИМ" if self.test_mode else "РАБОЧИЙ РЕЖИМ"
        await update.message.reply_text(
            f"🕐 Текущее время в Москве: {now.strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"Режим: {mode_status}"
        )

    async def cmd_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /test command."""
        logger.info(f"Command /test from user {update.effective_user.id}")
        message = self.google_client.get_today_duty()
        await update.message.reply_html(f"🧪 ТЕСТОВОЕ СООБЩЕНИЕ\n\n{message}")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /status command."""
        mode_status = "🔴 ТЕСТОВЫЙ РЕЖИМ" if self.test_mode else "🟢 РАБОЧИЙ РЕЖИМ"

        jobs_info = []
        if context.job_queue:
            for job in context.job_queue.jobs():
                next_run = job.next_t if hasattr(job, 'next_t') else "неизвестно"
                jobs_info.append(f"• {job.name}: следующее в {next_run}")

        jobs_text = "\n".join(jobs_info) if jobs_info else "Нет активных задач"

        await update.message.reply_text(
            f"📊 <b>Статус бота</b>\n\n"
            f"Режим: {mode_status}\n"
            f"Группа: {self.config.GROUP_CHAT_ID}\n"
            f"Время: {self.config.NOTIFY_HOUR:02d}:{self.config.NOTIFY_MINUTE:02d} MSK\n\n"
            f"<b>Активные задачи:</b>\n{jobs_text}",
            parse_mode="HTML"
        )

    async def cmd_test_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Turn on test mode (admin only)."""
        if update.effective_user.id != self.config.ADMIN_USER_ID:
            await update.message.reply_text("⛔ У вас нет прав для этой команды.")
            return

        if self.test_mode:
            await update.message.reply_text("⚠️ Тестовый режим уже включен.")
            return

        self.test_mode = True

        if context.job_queue:
            # Remove old jobs
            for job in context.job_queue.jobs():
                job.schedule_removal()

            # Add test jobs
            context.job_queue.run_once(
                self.send_notification,
                when=10,
                name="test_notification"
            )
            context.job_queue.run_repeating(
                self.send_notification,
                interval=60,
                first=70,
                name="test_notification"
            )

            await update.message.reply_text(
                "✅ Тестовый режим ВКЛЮЧЕН\n"
                "Уведомления каждую минуту.\n"
                "/test_off для выключения."
            )

            await context.bot.send_message(
                chat_id=self.config.GROUP_CHAT_ID,
                text="🔴 <b>Включен тестовый режим</b>\nУведомления каждую минуту.",
                parse_mode="HTML"
            )

    async def cmd_test_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Turn off test mode (admin only)."""
        if update.effective_user.id != self.config.ADMIN_USER_ID:
            await update.message.reply_text("⛔ У вас нет прав для этой команды.")
            return

        if not self.test_mode:
            await update.message.reply_text("⚠️ Тестовый режим уже выключен.")
            return

        self.test_mode = False

        if context.job_queue:
            # Remove old jobs
            for job in context.job_queue.jobs():
                job.schedule_removal()

            # Add daily job
            notification_time = time(
                hour=self.config.NOTIFY_HOUR,
                minute=self.config.NOTIFY_MINUTE,
                second=0,
                tzinfo=self.moscow_tz
            )

            context.job_queue.run_daily(
                self.send_notification,
                time=notification_time,
                days=tuple(range(7)),
                name="daily_notification"
            )

            await update.message.reply_text(
                f"✅ Тестовый режим ВЫКЛЮЧЕН\n"
                f"Уведомления ежедневно в {self.config.NOTIFY_HOUR:02d}:{self.config.NOTIFY_MINUTE:02d} MSK."
            )

            await context.bot.send_message(
                chat_id=self.config.GROUP_CHAT_ID,
                text=f"🟢 <b>Выключен тестовый режим</b>\n"
                     f"Уведомления ежедневно в {self.config.NOTIFY_HOUR:02d}:{self.config.NOTIFY_MINUTE:02d} MSK.",
                parse_mode="HTML"
            )

    async def send_notification(self, context: ContextTypes.DEFAULT_TYPE):
        """Send duty notification to group."""
        try:
            now = datetime.now(self.moscow_tz)
            message = self.google_client.get_today_duty()

            if self.test_mode:
                full_message = f"⏱️ <b>Тестовое уведомление</b> ({now.strftime('%H:%M:%S')})\n\n{message}"
            else:
                full_message = message

            await context.bot.send_message(
                chat_id=self.config.GROUP_CHAT_ID,
                text=full_message,
                parse_mode="HTML"
            )
            logger.info(f"Notification sent at {now.strftime('%H:%M:%S')} MSK")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")