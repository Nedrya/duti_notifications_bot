"""
Production calendar API client for Russia.
Uses free API from production-calendar.ru
"""
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta
import logging
from typing import Optional, Dict, Any, Union
import pytz

logger = logging.getLogger(__name__)

# Московский часовой пояс
MSK_TZ = pytz.timezone('Europe/Moscow')

# Бесплатный гостевой токен (имеет ограничения, но для личного использования подойдет)
GUEST_TOKEN = "6914a408120146bcb82ab95c003bc6ad"

# Базовый URL API
API_BASE_URL = "https://www.production-calendar.ru/get-period"


class ProductionCalendarAPI:
    """Клиент для API производственного календаря РФ"""

    def __init__(self, token: str = GUEST_TOKEN, country: str = "ru"):
        self.token = token
        self.country = country
        self.cache = {}  # Простое кэширование
        self.cache_ttl = 3600  # 1 час

    async def get_day_info(self, date: datetime) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о конкретном дне через API

        Args:
            date: Дата для проверки

        Returns:
            Dict с информацией о дне или None при ошибке
        """
        date_str = date.strftime("%d.%m.%Y")
        cache_key = date_str

        # Проверяем кэш
        if cache_key in self.cache:
            cache_time, cache_data = self.cache[cache_key]
            if (datetime.now() - cache_time).seconds < self.cache_ttl:
                logger.debug(f"Cache hit for {date_str}")
                return cache_data

        # Формируем URL запроса
        period = date.strftime("%d.%m.%Y")
        url = f"{API_BASE_URL}/{self.token}/{self.country}/{period}/json"

        logger.info(f"Fetching day info from API: {url}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        # API может вернуть JSON или строку
                        try:
                            data = await response.json()
                        except:
                            # Если не JSON, пробуем прочитать как текст
                            text = await response.text()
                            logger.warning(f"API returned non-JSON response: {text[:100]}")
                            return None

                        # Проверяем структуру ответа
                        if isinstance(data, dict):
                            if data.get("status") == "ok" and "days" in data and len(data["days"]) > 0:
                                day_data = data["days"][0]
                                self.cache[cache_key] = (datetime.now(), day_data)
                                return day_data
                            elif "type_id" in data:
                                # Прямой ответ для одного дня
                                self.cache[cache_key] = (datetime.now(), data)
                                return data
                            else:
                                logger.error(f"API returned unexpected structure: {data}")
                                return None
                        else:
                            logger.error(f"API returned non-dict: {type(data)}")
                            return None
                    else:
                        logger.error(f"API request failed with status {response.status}")
                        return None

        except asyncio.TimeoutError:
            logger.error("API request timeout")
            return None
        except Exception as e:
            logger.error(f"API request error: {e}")
            return None

    async def is_working_day(self, date: datetime) -> bool:
        """
        Проверяет, является ли день рабочим

        Типы дней из API:
        1 - Рабочий день
        2 - Выходной день
        3 - Государственный праздник
        4 - Региональный праздник
        5 - Предпраздничный сокращенный рабочий день
        6 - Дополнительный / перенесенный выходной день
        """
        day_info = await self.get_day_info(date)

        if day_info and isinstance(day_info, dict):
            type_id = day_info.get("type_id")

            # Рабочие дни: 1 (рабочий) и 5 (сокращенный)
            is_working = type_id in [1, 5]

            logger.debug(f"Day {date.strftime('%d.%m.%Y')}: type_id={type_id}, working={is_working}")
            return is_working
        else:
            # Если API недоступен или вернул неверные данные, используем запасную логику
            logger.warning(f"API unavailable or invalid data for {date.strftime('%d.%m.%Y')}, falling back to weekend check")
            return self._fallback_is_working_day(date)

    async def get_day_type(self, date: datetime) -> str:
        """Возвращает тип дня на русском"""
        day_info = await self.get_day_info(date)

        if day_info and isinstance(day_info, dict):
            type_text = day_info.get("type_text", "Неизвестно")
            note = day_info.get("note", "")

            if note:
                return f"{type_text} ({note})"
            return type_text
        else:
            # Запасной вариант
            if date.weekday() >= 5:
                return "Выходной день"
            else:
                return "Рабочий день"

    def _fallback_is_working_day(self, date: datetime) -> bool:
        """Запасная логика на случай недоступности API"""
        # Считаем субботу и воскресенье выходными
        return date.weekday() < 5

    async def prefetch_month(self, year: int, month: int):
        """
        Предзагружает данные за целый месяц для кэширования
        """
        period = f"{month:02d}.{year}"
        url = f"{API_BASE_URL}/{self.token}/{self.country}/{period}/json?compact=true"

        logger.info(f"Prefetching month {month}.{year}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        try:
                            data = await response.json()
                        except:
                            logger.warning(f"Prefetch returned non-JSON response")
                            return

                        if isinstance(data, dict) and data.get("status") == "ok" and "days" in data:
                            # Кэшируем каждый день
                            for day_data in data["days"]:
                                date_str = day_data.get("date")
                                if date_str:
                                    self.cache[date_str] = (datetime.now(), day_data)

                            logger.info(f"Prefetched {len(data['days'])} days for {month}.{year}")
        except Exception as e:
            logger.error(f"Failed to prefetch month: {e}")