"""
Google Sheets integration module.
"""
import os
import logging
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import get_effective_format

logger = logging.getLogger(__name__)


class GoogleSheetsClient:
    """Client for interacting with Google Sheets."""

    def __init__(self, credentials_file: str, spreadsheet_id: str, timezone):
        self.credentials_file = credentials_file
        self.spreadsheet_id = spreadsheet_id
        self.timezone = timezone
        self.client = None

        # Russian month names
        self.months_ru = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }

    def connect(self):
        """Establish connection to Google Sheets."""
        logger.info(f"Attempting to connect with credentials: {self.credentials_file}")
        logger.info(f"File exists: {os.path.exists(self.credentials_file)}")

        if not os.path.exists(self.credentials_file):
            logger.error(f"Credentials file not found: {self.credentials_file}")
            return False

        try:
            if os.path.getsize(self.credentials_file) == 0:
                logger.error("Credentials file is empty")
                return False

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ]

            creds = Credentials.from_service_account_file(self.credentials_file, scopes=scopes)
            self.client = gspread.authorize(creds)
            logger.info("✅ Connected to Google Sheets successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Google Sheets: {e}")
            return False

    def get_sheet_name_for_current_month(self) -> str:
        """Get sheet name for current month."""
        now = datetime.now(self.timezone)
        return f"{self.months_ru[now.month]} {now.year}"

    def find_date_column_index(self, headers: list, today: datetime) -> int:
        """Find column index for today's date."""
        today_str = today.strftime("%d.%m")
        logger.info(f"Looking for date column: {today_str}")

        for i, header in enumerate(headers):
            header_str = str(header).strip()
            if header_str == today_str:
                logger.info(f"Found date column at index {i}: {header_str}")
                return i

        logger.warning(f"Date column for {today_str} not found")
        return -1

    def get_cell_color(self, worksheet, row: int, col: int):
        """Get cell background color."""
        try:
            # Convert column number to letter (A, B, C, ...)
            if col <= 26:
                col_letter = chr(64 + col)
            else:
                first = chr(64 + (col - 1) // 26)
                second = chr(65 + (col - 1) % 26)
                col_letter = f"{first}{second}"

            cell_label = f"{col_letter}{row}"
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

    @staticmethod
    def is_colored(color_dict) -> bool:
        """Check if cell has color (not white/transparent)."""
        if not color_dict:
            return False

        red = color_dict.get('red', 0.0)
        green = color_dict.get('green', 0.0)
        blue = color_dict.get('blue', 0.0)

        red = float(red) if red is not None else 0.0
        green = float(green) if green is not None else 0.0
        blue = float(blue) if blue is not None else 0.0

        # Not white
        is_white = red > 0.9 and green > 0.9 and blue > 0.9

        return (red > 0.1 or green > 0.1 or blue > 0.1) and not is_white

    @staticmethod
    def is_green_color(color_dict) -> bool:
        """Check if color is green."""
        if not color_dict:
            return False

        red = color_dict.get('red', 0.0)
        green = color_dict.get('green', 0.0)
        blue = color_dict.get('blue', 0.0)

        red = float(red) if red is not None else 0.0
        green = float(green) if green is not None else 0.0
        blue = float(blue) if blue is not None else 0.0

        try:
            # Зеленый цвет: зеленый компонент значительно выше красного и синего
            return (green > 0.3 and
                    green > red * 1.5 and
                    green > blue * 1.5)
        except (TypeError, ZeroDivisionError):
            return False

    @staticmethod
    def is_yellow_color(color_dict) -> bool:
        """Check if color is yellow (vacation)."""
        if not color_dict:
            return False

        red = color_dict.get('red', 0.0)
        green = color_dict.get('green', 0.0)
        blue = color_dict.get('blue', 0.0)

        red = float(red) if red is not None else 0.0
        green = float(green) if green is not None else 0.0
        blue = float(blue) if blue is not None else 0.0

        try:
            # Желтый цвет: красный и зеленый высокие, синий низкий
            is_yellow = (red > 0.6 and
                         green > 0.6 and
                         blue < 0.3 and
                         abs(red - green) < 0.3)

            if is_yellow:
                logger.debug(f"Yellow color detected (vacation): R={red:.2f}, G={green:.2f}, B={blue:.2f}")

            return is_yellow
        except (TypeError, ZeroDivisionError):
            return False

    def get_today_duty(self) -> str:
        """Get today's duty information from spreadsheet."""
        today = datetime.now(self.timezone)
        sheet_name = self.get_sheet_name_for_current_month()

        logger.info(f"Looking for sheet: '{sheet_name}'")

        if not self.client:
            if not self.connect():
                return "❌ Не удалось подключиться к Google Sheets"

        try:
            spreadsheet = self.client.open_by_key(self.spreadsheet_id)

            # Find worksheet for current month
            try:
                worksheet = spreadsheet.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                all_worksheets = spreadsheet.worksheets()
                worksheet_names = [w.title for w in all_worksheets]
                return f"❌ Не найден лист '{sheet_name}'.\nДоступные листы: {', '.join(worksheet_names)}"

            # Get all values
            all_values = worksheet.get_all_values()

            if not all_values or len(all_values) < 2:
                return "❌ Лист пустой или содержит только заголовки"

            # Headers are first row
            headers = all_values[0]

            # Find today's date column
            date_col = self.find_date_column_index(headers, today)

            if date_col == -1:
                sample_headers = headers[:10]
                return (f"❌ Не найден столбец с датой {today.strftime('%d.%m')}.\n"
                        f"Заголовки: {sample_headers}...")

            # Employee column is first (index 0)
            employee_col = 0

            # Collect leaders and followers
            leaders = []
            followers = []
            vacation = []

            # Process each employee row
            for row_idx, row in enumerate(all_values[1:], start=2):
                if len(row) <= max(employee_col, date_col):
                    continue

                employee_name = row[employee_col].strip() if len(row) > employee_col else ""

                if not employee_name:
                    continue

                # Get cell color
                cell_color = self.get_cell_color(worksheet, row_idx, date_col + 1)

                if cell_color and self.is_colored(cell_color):
                    # Check for yellow (vacation) - ignore
                    if self.is_yellow_color(cell_color):
                        vacation.append(employee_name)
                        logger.info(f"🏖️ VACATION: {employee_name} (ignored)")
                    # Check for green (leader)
                    elif self.is_green_color(cell_color):
                        leaders.append(employee_name)
                        logger.info(f"✅ LEADER: {employee_name}")
                    # Other colors - followers
                    else:
                        followers.append(employee_name)
                        logger.info(f"📌 FOLLOWER: {employee_name}")
                else:
                    # Fallback to text content
                    cell_value = row[date_col].strip() if len(row) > date_col else ""
                    if cell_value:
                        followers.append(employee_name)
                        logger.info(f"📝 TEXT ONLY: {employee_name}")

            date_str = today.strftime("%d.%m.%Y")
            logger.info(f"Found {len(leaders)} leaders, {len(followers)} followers, {len(vacation)} on vacation")

            if not leaders and not followers:
                return f"ℹ️ На {date_str} дежурные не назначены."

            # Format message
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
            logger.error(f"Error reading spreadsheet: {e}", exc_info=True)
            return f"❌ Ошибка при чтении таблицы: {str(e)}"