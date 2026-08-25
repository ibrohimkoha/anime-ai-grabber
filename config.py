import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Telegram MTProto Credentials
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE_NUMBER = os.getenv("TELEGRAM_PHONE", "")
SESSION_NAME = str(BASE_DIR / os.getenv("SESSION_NAME", "anime_userbot_session"))
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING", "")

# DeepSeek AI Configuration
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Default Monitored Channels
DEFAULT_TARGET_CHANNELS = os.getenv("TARGET_CHANNELS", "@amediatarjima,@anidubuz")

# Default Destination Bot
DEFAULT_DESTINATION_BOT = os.getenv("DESTINATION_BOT", "@Tarjima_Animelarrbot")

# Automation flags
AUTO_JOIN_CHANNELS = os.getenv("AUTO_JOIN_CHANNELS", "True").lower() in ("true", "1", "yes")

# Database path
DB_PATH = str(BASE_DIR / "anime_grabber.db")
