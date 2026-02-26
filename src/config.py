import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)


class Config:
    """Application configuration from environment variables."""

    # Telegram
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')
    ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '0'))

    # Google Sheets
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
    GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'service_account.json')

    # Notification time (MSK)
    NOTIFY_HOUR = int(os.getenv('NOTIFY_HOUR', '10'))
    NOTIFY_MINUTE = int(os.getenv('NOTIFY_MINUTE', '0'))

    # Test mode
    TEST_MODE = os.getenv('TEST_MODE', 'false').lower() == 'true'

    @classmethod
    def validate(cls):
        """Validate required configuration."""
        required_vars = [
            ('TELEGRAM_TOKEN', cls.TELEGRAM_TOKEN),
            ('GROUP_CHAT_ID', cls.GROUP_CHAT_ID),
            ('SPREADSHEET_ID', cls.SPREADSHEET_ID),
            ('ADMIN_USER_ID', cls.ADMIN_USER_ID),
        ]

        missing = [name for name, value in required_vars if not value]

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        # Convert GROUP_CHAT_ID to int if it's a string
        try:
            cls.GROUP_CHAT_ID = int(cls.GROUP_CHAT_ID)
        except (ValueError, TypeError):
            raise ValueError(f"GROUP_CHAT_ID must be an integer, got {cls.GROUP_CHAT_ID}")

        # Check if credentials file exists
        if not os.path.exists(cls.GOOGLE_CREDENTIALS_FILE):
            logger.warning(f"Google credentials file not found: {cls.GOOGLE_CREDENTIALS_FILE}")

        return True