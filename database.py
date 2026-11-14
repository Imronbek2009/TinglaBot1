import aiosqlite
import datetime
from config import DB_PATH, ADMIN_IDS, DEFAULT_IG_SESSIONID
from texts import TEXT_DEFINITIONS, safe_format_html

MENU_KEYS = [
    "menu_stories",
    "menu_music",
    "menu_platforms",
    "menu_history",
    "menu_favorites",
    "menu_profile",
    "menu_settings",
    "menu_help",
]

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                language TEXT DEFAULT 'uz',
                download_mode TEXT DEFAULT 'auto',
                downloads_count INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,
                joined_at TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                title TEXT,
                invite_link TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS media_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                media_type TEXT,
                quality TEXT,
                file_id TEXT,
                title TEXT,
                platform TEXT,
                created_at TEXT,
                UNIQUE(url, media_type, quality)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                url TEXT,
                title TEXT,
                platform TEXT,
                media_type TEXT,
                file_id TEXT,
                created_at TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                url TEXT,
                file_id TEXT,
                media_type TEXT,
                created_at TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT
            )
        ''')

        default_settings = {
            "force_sub": "1",
            "maintenance": "0",
            "daily_limit": "0",
            "ig_sessionid": DEFAULT_IG_SESSIONID,
            "tg_user_session_string": "",
            # Foydalanuvchi menyusi bo'limlarini yoqish/o'chirish (1 = yoqilgan, 0 = o'chirilgan)
            "menu_stories": "1",
            "menu_music": "1",
            "menu_platforms": "1",
            "menu_history": "1",
            "menu_favorites": "1",
            "menu_profile": "1",
            "menu_settings": "1",
            "menu_help": "1",
        }
        # Barcha standart matnlarni settings jadvaliga qo'shamiz
        for t_key, (_, _, def_val) in TEXT_DEFINITIONS.items():
            default_settings[t_key] = def_val

        for k, v in default_settings.items():
            await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for admin_id in ADMIN_IDS:
            await db.execute("INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)", (admin_id, now))

        await db.commit()


async def get_menu_settings() -> dict[str, bool]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT key, value FROM settings WHERE key LIKE 'menu_%'")
        rows = await cursor.fetchall()
        res = {k: True for k in MENU_KEYS}
        for k, v in rows:
            res[k] = (str(v) == "1")
        return res


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row and row[0] is not None:
            return row[0]
        if key in TEXT_DEFINITIONS:
            return TEXT_DEFINITIONS[key][2]
        return default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()


async def get_bot_text(key: str, **kwargs) -> str:
    '''
    Bazadan (yoki standart ro'yxatdan) matnni olib, ichidagi {o'zgaruvchilarni}
    HTML-xavfsiz qilib formatlab qaytaradi.
    '''
    default_tpl = TEXT_DEFINITIONS[key][2] if key in TEXT_DEFINITIONS else ""
    raw_tpl = await get_setting(key, default_tpl)
    if not kwargs:
        return raw_tpl
    return safe_format_html(raw_tpl, **kwargs)


async def reset_bot_text(key: str):
    if key in TEXT_DEFINITIONS:
        await set_setting(key, TEXT_DEFINITIONS[key][2])


async def reset_all_bot_texts():
    async with aiosqlite.connect(DB_PATH) as db:
        for k, (_, _, def_val) in TEXT_DEFINITIONS.items():
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, def_val))
        await db.commit()


async def register_user(user_id: int, full_name: str, username: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO users (user_id, full_name, username, joined_at) VALUES (?, ?, ?, ?)",
                (user_id, full_name, username or "", now)
            )
        else:
            await db.execute(
                "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
                (full_name, username or "", user_id)
            )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()


async def update_user_mode(user_id: int, mode: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET download_mode = ? WHERE user_id = ?", (mode, user_id))
        await db.commit()


async def set_user_ban(user_id: int, is_banned: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (is_banned, user_id))
        await db.commit()


async def set_user_vip(user_id: int, is_vip: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_vip = ? WHERE user_id = ?", (is_vip, user_id))
        await db.commit()


async def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        return (await cursor.fetchone()) is not None


async def add_admin_db(user_id: int):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)", (user_id, now))
        await db.commit()


async def remove_admin_db(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_all_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM admins")
        rows = await cursor.fetchall()
        ids = set(ADMIN_IDS)
        for r in rows:
            ids.add(r[0])
        return list(ids)


async def add_channel(channel_id: str, title: str, invite_link: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO channels (channel_id, title, invite_link) VALUES (?, ?, ?)",
            (str(channel_id), title, invite_link)
        )
        await db.commit()


async def remove_channel(db_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE id = ?", (db_id,))
        await db.commit()


async def get_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM channels ORDER BY id ASC")
        return await cursor.fetchall()


async def get_cached_media(url: str, media_type: str, quality: str = "best"):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM media_cache WHERE url = ? AND media_type = ? AND quality = ?",
            (url, media_type, quality)
        )
        return await cursor.fetchone()


async def save_cached_media(url: str, media_type: str, quality: str, file_id: str, title: str, platform: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT OR REPLACE INTO media_cache
               (url, media_type, quality, file_id, title, platform, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (url, media_type, quality, file_id, title, platform, now)
        )
        await db.commit()


async def log_download(user_id: int, url: str, title: str, platform: str, media_type: str, file_id: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET downloads_count = downloads_count + 1 WHERE user_id = ?", (user_id,))
        await db.execute(
            '''INSERT INTO download_history (user_id, url, title, platform, media_type, file_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (user_id, url, title[:100], platform, media_type, file_id, now)
        )
        await db.commit()


async def get_user_today_downloads(user_id: int) -> int:
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM download_history WHERE user_id = ? AND created_at LIKE ?",
            (user_id, f"{today}%")
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_user_history(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM download_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return await cursor.fetchall()


async def get_history_item(item_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM download_history WHERE id = ?", (item_id,))
        return await cursor.fetchone()


async def add_favorite(user_id: int, title: str, url: str, file_id: str, media_type: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM favorites WHERE user_id = ? AND file_id = ?",
            (user_id, file_id)
        )
        if await cursor.fetchone():
            return False
        await db.execute(
            "INSERT INTO favorites (user_id, title, url, file_id, media_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, title[:100], url, file_id, media_type, now)
        )
        await db.commit()
        return True


async def get_favorites(user_id: int, limit: int = 15):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM favorites WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return await cursor.fetchall()


async def delete_favorite(fav_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM favorites WHERE id = ? AND user_id = ?", (fav_id, user_id))
        await db.commit()


async def get_favorite_item(fav_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM favorites WHERE id = ?", (fav_id,))
        return await cursor.fetchone()


async def get_all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def get_stats():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        total_users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        today_users = (await (await db.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",))).fetchone())[0]
        banned_users = (await (await db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")).fetchone())[0]
        vip_users = (await (await db.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")).fetchone())[0]
        total_downloads = (await (await db.execute("SELECT COUNT(*) FROM download_history")).fetchone())[0]
        today_downloads = (await (await db.execute("SELECT COUNT(*) FROM download_history WHERE created_at LIKE ?", (f"{today}%",))).fetchone())[0]
        cached_files = (await (await db.execute("SELECT COUNT(*) FROM media_cache")).fetchone())[0]

        cursor = await db.execute(
            "SELECT platform, COUNT(*) as cnt FROM download_history GROUP BY platform ORDER BY cnt DESC"
        )
        platform_rows = await cursor.fetchall()

        return {
            "total_users": total_users,
            "today_users": today_users,
            "banned_users": banned_users,
            "vip_users": vip_users,
            "total_downloads": total_downloads,
            "today_downloads": today_downloads,
            "cached_files": cached_files,
            "platforms": platform_rows
        }
