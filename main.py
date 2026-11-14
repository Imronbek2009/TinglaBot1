import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db
from middlewares import AccessMiddleware, color_safe_request_middleware
from handlers_admin import admin_router
from handlers_user import user_router

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        stream=sys.stdout
    )

    if not BOT_TOKEN or BOT_TOKEN == "BU_YERGA_BOT_TOKEN_YOZING":
        print("=" * 60)
        print("❌ XATOLIK: BOT_TOKEN kiritilmagan!")
        print("👉 Iltimos, .env yoki config.py faylini ochib, o'z Bot Tokeningizni va Admin ID raqamingizni yozing.")
        print("=" * 60)
        return

    await init_db()

    bot = Bot(token=BOT_TOKEN)
    bot.session.middleware(color_safe_request_middleware)

    dp = Dispatcher(storage=MemoryStorage())

    access_mw = AccessMiddleware()
    dp.message.middleware(access_mw)
    dp.callback_query.middleware(access_mw)

    dp.include_router(admin_router)
    dp.include_router(user_router)

    print("=" * 60)
    print("🚀 TINGLA — ZERO-CONFIG MULTI-ENGINE BOT (v8) ISHGA TUSHDI!")
    print("✅ TikTok (TikWM) | ✅ Insta (GraphQL/Vx) | ✅ YouTube (Cloud/VR) | ✅ Stories")
    print("=" * 60)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot to'xtatildi.")
