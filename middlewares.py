import time
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
import keyboards
from database import (
    register_user, get_user, get_setting, get_channels, is_admin,
    get_menu_settings, get_bot_text
)
from keyboards import sub_check_kb
from texts import strip_html_tags


def _strip_or_remap_markup(markup):
    if not markup:
        return markup
    profile = keyboards.COLOR_PROFILES[keyboards.ACTIVE_COLOR_PROFILE_INDEX]
    rows = getattr(markup, "keyboard", None) or getattr(markup, "inline_keyboard", None)
    if not rows:
        return markup
    for row in rows:
        for btn in row:
            extra = getattr(btn, "__pydantic_extra__", None)
            if isinstance(extra, dict):
                old_vals = set(extra.values())
                color_type = None
                if old_vals & {"success", "green", "positive"}:
                    color_type = "green"
                elif old_vals & {"primary", "blue"}:
                    color_type = "blue"
                elif old_vals & {"danger", "red", "negative"}:
                    color_type = "red"
                extra.clear()
                if color_type and color_type in profile:
                    extra.update(profile[color_type])
    return markup


async def color_safe_request_middleware(make_request, bot: Bot, method):
    html_fallback_tried = False
    while True:
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as e:
            err_msg = str(e).lower()

            if "can't parse entities" in err_msg and not html_fallback_tried:
                html_fallback_tried = True
                if hasattr(method, "text") and method.text:
                    method.text = strip_html_tags(method.text)
                if hasattr(method, "caption") and method.caption:
                    method.caption = strip_html_tags(method.caption)
                if hasattr(method, "parse_mode"):
                    method.parse_mode = None
                continue

            has_markup = getattr(method, "reply_markup", None) is not None
            if (
                has_markup
                and keyboards.ACTIVE_COLOR_PROFILE_INDEX < len(keyboards.COLOR_PROFILES) - 1
                and ("button" in err_msg or "keyboard" in err_msg or "style" in err_msg or "color" in err_msg or "field" in err_msg)
            ):
                keyboards.ACTIVE_COLOR_PROFILE_INDEX += 1
                _strip_or_remap_markup(method.reply_markup)
                continue

            raise


class AccessMiddleware(BaseMiddleware):
    def __init__(self):
        self.last_request: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user = event.from_user
        if not user:
            return await handler(event, data)

        uid = user.id
        full_name = user.full_name or "Foydalanuvchi"
        username = user.username or ""

        await register_user(uid, full_name, username)
        db_user = await get_user(uid)
        admin_status = await is_admin(uid)
        menu_cfg = await get_menu_settings()

        data["is_admin"] = admin_status
        data["db_user"] = db_user
        data["menu_cfg"] = menu_cfg

        if db_user and db_user["is_banned"] == 1 and not admin_status:
            text = await get_bot_text("txt_banned")
            if isinstance(event, Message):
                await event.answer(text, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer(strip_html_tags(text)[:180], show_alert=True)
            return

        maintenance = await get_setting("maintenance", "0")
        if maintenance == "1" and not admin_status:
            text = await get_bot_text("txt_maintenance")
            if isinstance(event, Message):
                await event.answer(text, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer(strip_html_tags(text)[:180], show_alert=True)
            return

        if isinstance(event, Message) and not admin_status:
            now = time.time()
            last = self.last_request.get(uid, 0)
            if now - last < 0.6:
                return
            self.last_request[uid] = now

        force_sub = await get_setting("force_sub", "1")
        if force_sub == "1" and not admin_status:
            if isinstance(event, CallbackQuery) and event.data == "check_subscription":
                return await handler(event, data)

            channels = await get_channels()
            if channels:
                bot: Bot = data["bot"]
                unsubscribed = []
                for ch in channels:
                    try:
                        member = await bot.get_chat_member(chat_id=ch["channel_id"], user_id=uid)
                        if member.status in ("left", "kicked"):
                            unsubscribed.append(ch)
                    except Exception:
                        pass

                if unsubscribed:
                    msg_text = await get_bot_text("txt_force_sub")
                    kb = sub_check_kb(unsubscribed)
                    if isinstance(event, Message):
                        await event.answer(msg_text, reply_markup=kb, parse_mode="HTML")
                    elif isinstance(event, CallbackQuery):
                        await event.message.answer(msg_text, reply_markup=kb, parse_mode="HTML")
                        await event.answer("⚠️ Avval kanallarga obuna bo'ling!", show_alert=True)
                    return

        return await handler(event, data)
