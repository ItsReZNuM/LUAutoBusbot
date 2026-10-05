import os
import platform

# Base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

# 1. Try loading via python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass

# 2. Fallback manual .env parser if python-dotenv is not installed
if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8959183882:AAEBWzQYJgDgsSK8pqdKNSedJt5x-Lo3Xh0")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6728527154"))

# By default, use local proxy on Windows if available; on Linux, read from env
default_tg_proxy = "http://127.0.0.1:10808" if platform.system() == "Windows" else ""
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", default_tg_proxy)

# Optional proxy to access Iranian sites if bot is running on a foreign VPS
IRAN_PROXY = os.getenv("IRAN_PROXY", "")

DB_PATH = os.path.join(BASE_DIR, "database.sqlite")
