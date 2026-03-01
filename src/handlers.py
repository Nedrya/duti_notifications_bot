"""
Telegram command handlers.
"""
import logging
from datetime import datetime, time
import pytz
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

import asyncio
from datetime import datetime, timedelta
import time as time_module
from holiday_api import ProductionCalendarAPI, MSK_TZ


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, max_calls_per_minute=1):
        self.max_calls_per_minute = max_calls_per_minute
        self.calls = []

    async def wait_if_needed(self):
        """Wait if we've exceeded rate limit."""
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)

        # Очищаем старые вызовы
        self.calls = [call for call in self.calls if call > minute_ago]

        if len(self.calls) >= self.max_calls_per_minute:
            # Ждем до следующей минуты
            oldest_call = min(self.calls)
            wait_time = 60 - (now - oldest_call).total_seconds()
            if wait_time > 0:
                logger.info(f"⏳ Rate limit: waiting {wait_time:.1f} seconds")
                await asyncio.sleep(wait_time)

        # Добавляем текущий вызов
        self.calls.append(now)


class DutyBotHandlers:
    """Handlers for Telegram bot commands."""

    def __init__(self, config, google_client, test_mode):
        self.config = config
        self.google_client = google_client
        self.test_mode = test_mode
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        self.rate_limiter = RateLimiter(max_calls_per_minute=1)
        self.calendar_api = ProductionCalendarAPI()

    async def cmd_duty(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /duty command - max 1 per minute with hard protection."""
        user_id = update.effective_user.id
        logger.info(f"Command /duty from user {user_id}")

        # Админу можно всё - проверка в САМОМ НАЧАЛЕ
        if user_id == self.config.ADMIN_USER_ID:
            logger.info(f"Admin user {user_id} - bypassing rate limit")
            message = self.google_client.get_today_duty()
            link_text = f'<a href="{self.config.SPREADSHEET_URL}">📅 Открыть график дежурств</a>'
            full_message = f"{link_text}\n\n{message}"
            await update.message.reply_html(full_message, disable_web_page_preview=True)
            return

        # Для обычных пользователей - жесткая проверка
        last_call_key = f'last_duty_call_{user_id}'
        current_time = time_module.time()
        last_call = context.bot_data.get(last_call_key, 0)

        logger.info(f"User {user_id} - last call: {last_call:.0f}, current: {current_time:.0f}, diff: {current_time - last_call:.0f}s")

        # Если прошло меньше 60 секунд с последнего вызова
        if current_time - last_call < 60:
            wait_time = 60 - (current_time - last_call)
            await update.message.reply_text(
                f"⏳ <b>Слишком много запросов</b>\n\n"
                f"Команда /duty доступна не чаще 1 раза в минуту.\n"
                f"Пожалуйста, подождите {wait_time:.0f} секунд.",
                parse_mode="HTML"
            )
            logger.warning(f"Rate limit triggered for user {user_id}, wait {wait_time:.0f}s")
            return

        # Обновляем время последнего вызова ДО выполнения команды
        context.bot_data[last_call_key] = current_time
        logger.info(f"User {user_id} - updated last call time to {current_time:.0f}")

        # Выполняем команду
        message = self.google_client.get_today_duty()
        link_text = f'<a href="{self.config.SPREADSHEET_URL}">📅 Открыть график дежурств</a>'
        full_message = f"{link_text}\n\n{message}"

        await update.message.reply_html(
            full_message,
            disable_web_page_preview=True,
        )

    async def cmd_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /time command."""
        user_id = update.effective_user.id
        now = datetime.now(self.moscow_tz)
        mode_status = "🔴 ТЕСТОВЫЙ" if self.test_mode else "🟢 РАБОЧИЙ"

        # Для админа показываем дополнительную информацию
        if user_id == self.config.ADMIN_USER_ID:
            await update.message.reply_text(
                f"🕐 Текущее время: {now.strftime('%d.%m.%Y %H:%M:%S')} MSK\n"
                f"Режим: {mode_status}\n"
                f"Ваш ID: {user_id} (админ)"
            )
        else:
            await update.message.reply_text(
                f"🕐 Текущее время: {now.strftime('%d.%m.%Y %H:%M:%S')} MSK\n"
                f"Режим: {mode_status}"
            )

    async def cmd_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /test command - max 1 per minute."""
        user_id = update.effective_user.id
        logger.info(f"Command /test from user {user_id}")

        # Админу можно всё
        if user_id == self.config.ADMIN_USER_ID:
            message = self.google_client.get_today_duty()
            await update.message.reply_html(f"🧪 ТЕСТОВОЕ\n\n{message}")
            return

        # Для обычных пользователей - проверка
        last_call_key = f'last_test_call_{user_id}'
        current_time = time_module.time()
        last_call = context.bot_data.get(last_call_key, 0)

        if current_time - last_call < 60:
            wait_time = 60 - (current_time - last_call)
            await update.message.reply_text(
                f"⏳ <b>Слишком много запросов</b>\n\n"
                f"Команда /test доступна не чаще 1 раза в минуту.\n"
                f"Пожалуйста, подождите {wait_time:.0f} секунд.",
                parse_mode="HTML"
            )
            return

        context.bot_data[last_call_key] = current_time
        message = self.google_client.get_today_duty()
        await update.message.reply_html(f"🧪 ТЕСТОВОЕ\n\n{message}")

    async def cmd_chatid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show current chat ID (для диагностики)."""
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        chat_title = update.effective_chat.title

        message = f"📌 <b>Информация о чате</b>\n\n"
        message += f"ID: <code>{chat_id}</code>\n"
        message += f"Тип: {chat_type}\n"

        if chat_title:
            message += f"Название: {chat_title}\n"

        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            message += f"Статус бота: {bot_member.status}\n"
        except:
            message += f"Статус бота: не в чате\n"

        await update.message.reply_html(message)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for /status command."""
        user_id = update.effective_user.id
        mode_status = "🔴 ТЕСТОВЫЙ" if self.test_mode else "🟢 РАБОЧИЙ"

        jobs_info = []
        if context.job_queue:
            for job in context.job_queue.jobs():
                next_run = job.next_t if hasattr(job, 'next_t') else "неизвестно"
                jobs_info.append(f"• {job.name}: {next_run}")

        jobs_text = "\n".join(jobs_info) if jobs_info else "Нет активных задач"

        # Информация о rate limits
        if user_id == self.config.ADMIN_USER_ID:
            # Для админа показываем все вызовы
            duty_calls = []
            for key in context.bot_data:
                if key.startswith('last_duty_call_'):
                    uid = key.replace('last_duty_call_', '')
                    last_time = context.bot_data[key]
                    time_ago = time_module.time() - last_time
                    duty_calls.append(f"• User {uid}: {time_ago:.0f}s ago")

            duty_text = "\n".join(duty_calls) if duty_calls else "Нет вызовов /duty"
        else:
            # Для обычных пользователей только их данные
            last_call = context.bot_data.get(f'last_duty_call_{user_id}', 0)
            if last_call:
                time_ago = time_module.time() - last_call
                duty_text = f"• Ваш последний вызов: {time_ago:.0f}s назад"
            else:
                duty_text = "• Вы еще не вызывали /duty"

        await update.message.reply_text(
            f"📊 <b>Статус бота</b>\n\n"
            f"Режим: {mode_status}\n"
            f"Группа: {self.config.GROUP_CHAT_ID}\n"
            f"Время: {self.config.NOTIFY_HOUR:02d}:{self.config.NOTIFY_MINUTE:02d} MSK\n\n"
            f"<b>Rate limits:</b>\n{duty_text}\n\n"
            f"<b>Задачи:</b>\n{jobs_text}",
            parse_mode="HTML"
        )

    async def cmd_reset_rate_limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reset rate limit counters (admin only)."""
        if update.effective_user.id != self.config.ADMIN_USER_ID:
            await update.message.reply_text("⛔ Нет прав")
            return

        # Удаляем все ключи с ограничениями
        keys_to_delete = []
        for key in context.bot_data:
            if key.startswith('last_duty_call_') or key.startswith('last_test_call_'):
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del context.bot_data[key]

        await update.message.reply_text(f"✅ Rate limit counters reset (удалено {len(keys_to_delete)} записей)")

    async def cmd_test_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Turn on test mode (admin only)."""
        if update.effective_user.id != self.config.ADMIN_USER_ID:
            await update.message.reply_text("⛔ Нет прав")
            return

        if self.test_mode:
            await update.message.reply_text("⚠️ Тестовый режим уже включен")
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
                name="test_once"
            )
            context.job_queue.run_repeating(
                self.send_notification,
                interval=60,
                first=70,
                name="test_repeating"
            )

            await update.message.reply_text(
                "✅ Тестовый режим ВКЛЮЧЕН\n"
                "Уведомления каждую минуту"
            )

            try:
                await context.bot.send_message(
                    chat_id=self.config.GROUP_CHAT_ID,
                    text="🔴 <b>Тестовый режим включен</b>\nУведомления каждую минуту",
                    parse_mode="HTML"
                )
            except:
                pass

    async def cmd_test_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Turn off test mode (admin only)."""
        if update.effective_user.id != self.config.ADMIN_USER_ID:
            await update.message.reply_text("⛔ Нет прав")
            return

        if not self.test_mode:
            await update.message.reply_text("⚠️ Тестовый режим уже выключен")
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
                name="daily"
            )

            await update.message.reply_text(
                f"✅ Тестовый режим ВЫКЛЮЧЕН\n"
                f"Уведомления в {self.config.NOTIFY_HOUR:02d}:{self.config.NOTIFY_MINUTE:02d} MSK"
            )

            try:
                await context.bot.send_message(
                    chat_id=self.config.GROUP_CHAT_ID,
                    text=f"🟢 <b>Рабочий режим</b>\nУведомления в {self.config.NOTIFY_HOUR:02d}:{self.config.NOTIFY_MINUTE:02d} MSK",
                    parse_mode="HTML"
                )
            except:
                pass

    async def send_notification(self, context: ContextTypes.DEFAULT_TYPE):
        """Send duty notification to group with built-in retry logic."""
        try:
            now = datetime.now(self.moscow_tz)

            # Проверяем через API, рабочий ли сегодня день
            is_working = await self.calendar_api.is_working_day(now)

            if not is_working:
                day_type = await self.calendar_api.get_day_type(now)
                logger.info(f"📅 Сегодня {day_type} ({now.strftime('%d.%m.%Y')}) - пропускаем уведомление")

                # В тестовом режиме отправляем уведомление о пропуске
                if self.test_mode:
                    link_text = f'<a href="{self.config.SPREADSHEET_URL}">📅 График дежурств</a>'
                    await context.bot.send_message(
                        chat_id=self.config.GROUP_CHAT_ID,
                        text=f"📅 <b>Сегодня {day_type}</b>\n\n"
                             f"Уведомление о дежурстве не отправляется.\n"
                             f"{link_text}",
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                return

            logger.info(
                f"🔔 Notification triggered at {now.strftime('%H:%M:%S')} MSK for working day {now.strftime('%d.%m.%Y')}")

            message = self.google_client.get_today_duty()
            link_text = f'<a href="{self.config.SPREADSHEET_URL}">📅 Открыть график дежурств</a>'

            if self.test_mode:
                full_message = f"⏱️ <b>Тест</b> ({now.strftime('%H:%M:%S')})\n\n{link_text}\n\n{message}"
            else:
                full_message = f"{link_text}\n\n{message}"

            # Проверяем rate limit перед отправкой
            last_sent = context.bot_data.get('last_api_call', 0)
            current_time = time_module.time()

            if current_time - last_sent < 1:
                await asyncio.sleep(1)

            await self.rate_limiter.wait_if_needed()

            await context.bot.send_message(
                chat_id=self.config.GROUP_CHAT_ID,
                text=full_message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )

            context.bot_data['last_api_call'] = time_module.time()
            logger.info(f"✅ Notification sent successfully at {now.strftime('%H:%M:%S')} MSK")

            context.bot_data['notification_attempts'] = 0
            context.bot_data['last_notification_time'] = time_module.time()

        except Exception as e:
            logger.error(f"❌ Failed to send notification: {e}")

            # Rate limiting для повторных попыток
            attempts = context.bot_data.get('notification_attempts', 0)
            attempts += 1

            MAX_ATTEMPTS = 5

            if attempts <= MAX_ATTEMPTS:
                delay = 60 * (2 ** (attempts - 1))
                delay = max(delay, 60)

                logger.warning(f"🔄 Scheduling retry #{attempts} in {delay} seconds")

                context.bot_data['notification_attempts'] = attempts

                context.job_queue.run_once(
                    self.send_notification_with_rate_limit,
                    when=delay,
                    name=f"retry_{attempts}",
                    data={'attempt': attempts}
                )
            else:
                logger.error(f"❌ All {MAX_ATTEMPTS} retry attempts failed. Giving up.")
                context.bot_data['notification_attempts'] = 0

    async def cmd_check_calendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверяет сегодняшний день через API календаря"""
        now = datetime.now(self.moscow_tz)

        # Получаем информацию через API
        day_info = await self.calendar_api.get_day_info(now)
        is_working = await self.calendar_api.is_working_day(now)
        day_type = await self.calendar_api.get_day_type(now)

        if day_info:
            message = (
                f"📅 <b>Информация о дне</b>\n\n"
                f"Дата: {now.strftime('%d.%m.%Y')}\n"
                f"Тип: {day_type}\n"
                f"Рабочий: {'✅' if is_working else '❌'}\n"
                f"ID типа: {day_info.get('type_id')}\n"
                f"Примечание: {day_info.get('note', '—')}"
            )
        else:
            # Запасной вариант
            is_working = now.weekday() < 5
            message = (
                f"📅 <b>Информация о дне (запасной режим)</b>\n\n"
                f"Дата: {now.strftime('%d.%m.%Y')}\n"
                f"Рабочий: {'✅' if is_working else '❌'}\n"
                f"(API временно недоступен)"
            )

        await update.message.reply_html(message)

    async def send_notification_with_rate_limit(self, context: ContextTypes.DEFAULT_TYPE):
        """Send notification with rate limiting - max 1 per minute."""

        # Ключ для хранения времени последней отправки
        last_sent_key = 'last_notification_time'
        current_time = time_module.time()

        # Проверяем, когда было последнее отправление
        last_sent = context.bot_data.get(last_sent_key, 0)
        time_since_last = current_time - last_sent

        # Если прошло меньше 60 секунд с последней отправки
        if time_since_last < 60:
            wait_time = 60 - time_since_last
            logger.warning(f"⏳ Rate limit: {wait_time:.1f} seconds until next allowed notification")

            # Планируем повторную попытку через оставшееся время
            context.job_queue.run_once(
                self.send_notification,
                when=wait_time,
                name="rate_limited_retry",
                data=context.job.data if context.job else None
            )
            return

        # Обновляем время последней отправки
        context.bot_data[last_sent_key] = current_time

        # Вызываем основную функцию отправки
        await self.send_notification(context)

    async def cmd_test_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестирует API календаря"""
        now = datetime.now(self.moscow_tz)

        await update.message.reply_text("🔄 Тестируем API календаря...")

        # Проверяем сегодня
        day_info = await self.calendar_api.get_day_info(now)
        is_working = await self.calendar_api.is_working_day(now)
        day_type = await self.calendar_api.get_day_type(now)

        message = f"📅 <b>Тест API календаря</b>\n\n"
        message += f"Дата: {now.strftime('%d.%m.%Y')}\n"
        message += f"Тип дня: {day_type}\n"
        message += f"Рабочий: {'✅' if is_working else '❌'}\n\n"

        if day_info and isinstance(day_info, dict):
            message += f"Данные API:\n"
            message += f"  type_id: {day_info.get('type_id')}\n"
            message += f"  type_text: {day_info.get('type_text')}\n"
            message += f"  note: {day_info.get('note', '—')}\n"
        else:
            message += f"⚠️ API вернул некорректные данные: {type(day_info)}"

        await update.message.reply_html(message)