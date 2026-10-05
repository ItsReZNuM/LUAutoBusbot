import os
import platform

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8959183882:AAEBWzQYJgDgsSK8pqdKNSedJt5x-Lo3Xh0")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6728527154"))

# By default, use local proxy on Windows if available; on Linux, read from env
default_tg_proxy = "http://127.0.0.1:10808" if platform.system() == "Windows" else ""
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", default_tg_proxy)

# Optional proxy to access Iranian sites if bot is running on a foreign VPS
IRAN_PROXY = os.getenv("IRAN_PROXY", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.sqlite")
