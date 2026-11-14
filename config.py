import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "BU_YERGA_BOT_TOKEN_YOZING").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "tingla_officialbot").strip().lstrip("@")
DEFAULT_IG_SESSIONID = os.getenv("IG_SESSIONID", "").strip()

# 2 GB MTProto yuklash uchun API_ID va API_HASH
TG_API_ID = int(os.getenv("TG_API_ID", "2040").strip() or "2040")
TG_API_HASH = os.getenv("TG_API_HASH", "b18441a1ff607e10a989891a5462e627").strip()

raw_admins = os.getenv("ADMIN_IDS", "123456789")
ADMIN_IDS = []
for x in raw_admins.replace(";", ",").split(","):
    x = x.strip()
    if x.isdigit():
        ADMIN_IDS.append(int(x))

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "database.db")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
IG_COOKIES_FILE = os.path.join(BASE_DIR, "ig_cookies.txt")
TELETHON_BOT_SESSION = os.path.join(BASE_DIR, "mtproto_bot_session")
TELETHON_USER_SESSION = os.path.join(BASE_DIR, "mtproto_user_session")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Bot API standart limiti (50 MB) va MTProto maksimal limiti (2 GB = 2000 MB)
BOT_API_MAX_SIZE = 49 * 1024 * 1024
MAX_FILESIZE = 2000 * 1024 * 1024
