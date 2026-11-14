import os
import html
import uuid
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile, URLInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_API_MAX_SIZE, DOWNLOAD_DIR
from database import (
    get_user, update_user_mode, get_setting, get_bot_text,
    get_cached_media, save_cached_media, log_download,
    get_user_today_downloads, get_user_history, get_history_item,
    add_favorite, get_favorites, delete_favorite, get_favorite_item,
    get_channels, get_menu_settings
)
from keyboards import (
    BTN_STORIES, BTN_MUSIC, BTN_PLATFORMS, BTN_HISTORY,
    BTN_FAVORITES, BTN_PROFILE, BTN_SETTINGS, BTN_HELP,
    main_menu_kb, format_choice_kb, under_video_kb,
    user_settings_kb, history_list_kb, favorites_list_kb,
    search_results_kb, sub_check_kb, story_platform_kb,
    quick_username_story_kb
)
from downloader import (
    extract_url, extract_clean_username, is_story_url, detect_platform,
    get_media_info, download_media_file, search_youtube, download_stories,
    recognize_song_shazam, send_large_video_mtproto, split_video_if_needed
)

user_router = Router()

URL_SESSIONS: dict[str, dict] = {}
SEARCH_SESSIONS: dict[str, list] = {}

class UserStates(StatesGroup):
    waiting_music_query = State()
    waiting_ig_story = State()
    waiting_tg_story = State()


@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, is_admin: bool = False, menu_cfg: dict | None = None):
    await state.clear()
    if menu_cfg is None:
        menu_cfg = await get_menu_settings()
    name = message.from_user.first_name or "Do'stim"
    text = await get_bot_text("txt_start", name=name)
    await message.answer(text, reply_markup=main_menu_kb(is_admin, menu_cfg), parse_mode="HTML")


@user_router.callback_query(F.data == "check_subscription")
async def cb_check_sub(call: CallbackQuery, bot: Bot, is_admin: bool = False):
    channels = await get_channels()
    unsubscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["channel_id"], user_id=call.from_user.id)
            if member.status in ("left", "kicked"):
                unsubscribed.append(ch)
        except Exception:
            pass

    if unsubscribed:
        await call.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=sub_check_kb(unsubscribed))
        except Exception:
            pass
    else:
        menu_cfg = await get_menu_settings()
        await call.answer("✅ Obuna tasdiqlandi! Rahmat!", show_alert=True)
        try:
            await call.message.delete()
        except Exception:
            pass
        text = await get_bot_text("txt_sub_confirmed")
        await call.message.answer(
            text,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )


@user_router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# =========================================================================
# 📸 STORY KO'RISH (TO'G'RIDAN-TO'G'RI @USERNAME ORQALI)
# =========================================================================

@user_router.message(F.text.in_({BTN_STORIES, "🟣 👁 Story Ko'rish (Insta & TG)", "👁 Story Ko'rish"}))
async def menu_stories_handler(message: Message, state: FSMContext, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_stories", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    await state.clear()
    text = await get_bot_text("txt_stories_menu")
    await message.answer(text, reply_markup=story_platform_kb(), parse_mode="HTML")


@user_router.callback_query(F.data.startswith("story_plat:"))
async def cb_story_platform(call: CallbackQuery, state: FSMContext):
    plat = call.data.split(":")[1]
    if plat == "ig":
        await state.set_state(UserStates.waiting_ig_story)
        txt = await get_bot_text("txt_ig_story_prompt")
        await call.message.edit_text(txt, parse_mode="HTML")
    else:
        await state.set_state(UserStates.waiting_tg_story)
        txt = await get_bot_text("txt_tg_story_prompt")
        await call.message.edit_text(txt, parse_mode="HTML")
    await call.answer()


@user_router.callback_query(F.data.startswith("ustory:"))
async def cb_quick_username_story(call: CallbackQuery, bot: Bot):
    _, plat_code, username = call.data.split(":", 2)
    await call.answer("📥 Story qidirilmoqda...")
    try:
        await call.message.delete()
    except Exception:
        pass
    await execute_story_download(call.message, bot, plat_code, username, user_id=call.from_user.id)


@user_router.callback_query(F.data.startswith("usearch:"))
async def cb_quick_username_search(call: CallbackQuery):
    query = call.data.split(":", 1)[1]
    await call.answer("🔎 Qidirilmoqda...")
    await run_youtube_music_search(call.message, query)


@user_router.message(UserStates.waiting_ig_story)
async def process_ig_story_request(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await execute_story_download(message, bot, "ig", message.text.strip(), user_id=message.from_user.id)


@user_router.message(UserStates.waiting_tg_story)
async def process_tg_story_request(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await execute_story_download(message, bot, "tg", message.text.strip(), user_id=message.from_user.id)


async def execute_story_download(
    message: Message,
    bot: Bot,
    plat_code: str,
    query_or_url: str,
    user_id: int | None = None
):
    uid = user_id or message.from_user.id
    plat_name = "Instagram Story" if plat_code == "ig" else "Telegram Story"
    icon = "📸" if plat_code == "ig" else "✈️"
    watermark = await get_bot_text("watermark")
    disp_user = query_or_url if query_or_url.startswith("@") or query_or_url.startswith("http") else f"@{query_or_url}"

    prog_msg = await message.answer(
        f"{icon} <b>{html.escape(disp_user)}</b> profilidan <b>{plat_name}</b> qidirilmoqda...\n"
        "<code>[█████░░░░░] 50%</code>",
        parse_mode="HTML"
    )
    items = []
    try:
        items = await download_stories(plat_code, query_or_url)
        await prog_msg.edit_text(
            f"{icon} <b>{len(items)} ta Story topildi!</b> Yuborilmoqda...\n"
            "<code>[██████████] 99%</code>",
            parse_mode="HTML"
        )
        for item in items:
            fpath = item["filepath"]
            if not os.path.exists(fpath):
                continue
            caption = f"{icon} <b>{html.escape(str(item['title']))}</b>\n\n{watermark}"
            inp = FSInputFile(fpath)
            if item.get("is_photo"):
                await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
                sent = await message.answer_photo(inp, caption=caption, parse_mode="HTML")
                fid = sent.photo[-1].file_id if sent.photo else ""
                m_type = "photo"
            else:
                await bot.send_chat_action(chat_id=message.chat.id, action="upload_video")
                sent = await message.answer_video(inp, caption=caption, supports_streaming=True, parse_mode="HTML")
                fid = sent.video.file_id if sent.video else ""
                m_type = "video"

            if fid:
                await log_download(uid, query_or_url, item["title"], plat_name, m_type, fid)
    except Exception as e:
        await message.answer(
            f"❌ <b>Story yuklashda xatolik:</b>\n\n<code>{html.escape(str(e)[:280])}</code>",
            parse_mode="HTML"
        )
    finally:
        try:
            await prog_msg.delete()
        except Exception:
            pass
        for item in items:
            fp = item.get("filepath")
            if fp and os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass


# =========================================================================
# 🎵 SHAZAM ORQALI ORIGINAL TO'LIQ QO'SHIQNI TOPISH VA YUKLASH
# =========================================================================

@user_router.callback_query(F.data.startswith("shazam:"))
async def cb_shazam_recognize(call: CallbackQuery, bot: Bot):
    session_key = call.data.split(":", 1)[1]
    sess = URL_SESSIONS.get(session_key)
    if not sess:
        return await call.answer("⏳ Sessiya eskirgan. Videoni yoki havolani qaytadan yuboring!", show_alert=True)

    url = sess.get("url")
    await call.answer("🎵 Shazam ishga tushdi! Qo'shiq aniqlanmoqda...")

    shz_search_txt = await get_bot_text("txt_shazam_searching")
    status_msg = await call.message.answer(shz_search_txt, parse_mode="HTML")

    try:
        song_info = await recognize_song_shazam(source_url=url)
        if not song_info:
            not_found_txt = await get_bot_text("txt_shazam_not_found")
            return await status_msg.edit_text(not_found_txt, parse_mode="HTML")

        full_song_name = song_info["full_name"]
        source_badge = song_info.get("source", "Shazam 🎵")

        await status_msg.edit_text(
            f"✅ <b>{html.escape(source_badge)} orqali qo'shiq topildi!</b>\n"
            f"🎶 <b>Qo'shiq:</b> <code>{html.escape(full_song_name)}</code>\n\n"
            f"📥 <i>Original to'liq MP3 qo'shiq yuklab olinmoqda...</i>\n"
            "<code>[████████░░] 85%</code>",
            parse_mode="HTML"
        )

        yt_results = await search_youtube(f"{full_song_name} official audio", max_results=5)
        if not yt_results:
            yt_results = await search_youtube(full_song_name, max_results=5)

        if not yt_results:
            return await status_msg.edit_text(
                f"🎶 <b>Topilgan qo'shiq:</b> <code>{html.escape(full_song_name)}</code>\n"
                "❌ Biroq uni yuklab olish uchun manba topilmadi.",
                parse_mode="HTML"
            )

        best_track = yt_results[0]
        track_res = await download_media_file(best_track["url"], media_type="audio", quality="best")
        filepath = track_res.get("filepath")

        watermark = await get_bot_text("watermark")
        if filepath and os.path.exists(filepath):
            await bot.send_chat_action(chat_id=call.message.chat.id, action="upload_voice")
            inp = FSInputFile(filepath)
            caption = (
                f"🎵 <b>{html.escape(str(song_info['artist']))} — {html.escape(str(song_info['title']))}</b>\n"
                f"✨ <i>{html.escape(source_badge)} orqali original to'liq qo'shiq topildi</i>\n\n"
                f"{watermark}"
            )
            sent = await call.message.answer_audio(
                inp,
                title=str(song_info["title"])[:60],
                performer=str(song_info["artist"])[:40],
                duration=track_res.get("duration") or None,
                caption=caption,
                parse_mode="HTML"
            )
            try:
                os.remove(filepath)
            except Exception:
                pass
            if sent.audio:
                await log_download(call.from_user.id, best_track["url"], full_song_name, "Shazam MP3", "audio", sent.audio.file_id)

        session_prefix = uuid.uuid4().hex[:8]
        SEARCH_SESSIONS[session_prefix] = yt_results
        await status_msg.edit_text(
            f"🎶 <b>«{html.escape(full_song_name)}»</b> qo'shig'ining boshqa versiyalari va klipi:",
            reply_markup=search_results_kb(yt_results, session_prefix),
            parse_mode="HTML"
        )

    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>Qo'shiqni aniqlashda xatolik:</b> <code>{html.escape(str(e)[:140])}</code>",
            parse_mode="HTML"
        )


@user_router.message(F.voice | F.audio | F.video | F.video_note)
async def handle_direct_media_shazam(message: Message, bot: Bot):
    shz_search_txt = await get_bot_text("txt_shazam_searching")
    status_msg = await message.answer(shz_search_txt, parse_mode="HTML")
    local_path = os.path.join(DOWNLOAD_DIR, f"user_media_{uuid.uuid4().hex[:8]}.ogg")
    try:
        media_obj = message.voice or message.audio or message.video or message.video_note
        if media_obj.file_size and media_obj.file_size > 20 * 1024 * 1024:
            return await status_msg.edit_text("⚠️ Shazam uchun yuboriladigan fayl 20 MB dan kichik bo'lishi kerak.")

        f_info = await bot.get_file(media_obj.file_id)
        await bot.download_file(f_info.file_path, destination=local_path)

        song_info = await recognize_song_shazam(media_path=local_path)
        if not song_info:
            not_found_txt = await get_bot_text("txt_shazam_not_found")
            return await status_msg.edit_text(not_found_txt, parse_mode="HTML")

        full_song_name = song_info["full_name"]
        await status_msg.edit_text(
            f"✅ <b>Qo'shiq topildi:</b> <code>{html.escape(full_song_name)}</code>\n"
            "📥 <i>Original to'liq MP3 yuklanmoqda...</i>",
            parse_mode="HTML"
        )

        yt_results = await search_youtube(f"{full_song_name} official audio", max_results=5)
        if yt_results:
            best = yt_results[0]
            track_res = await download_media_file(best["url"], media_type="audio", quality="best")
            fp = track_res.get("filepath")
            watermark = await get_bot_text("watermark")
            if fp and os.path.exists(fp):
                await message.answer_audio(
                    FSInputFile(fp),
                    title=str(song_info["title"])[:60],
                    performer=str(song_info["artist"])[:40],
                    duration=track_res.get("duration") or None,
                    caption=f"🎵 <b>{html.escape(full_song_name)}</b>\n\n{watermark}",
                    parse_mode="HTML"
                )
                try:
                    os.remove(fp)
                except Exception:
                    pass

            session_prefix = uuid.uuid4().hex[:8]
            SEARCH_SESSIONS[session_prefix] = yt_results
            await status_msg.edit_text(
                f"🎶 <b>«{html.escape(full_song_name)}»</b> bo'yicha barcha variantlar:",
                reply_markup=search_results_kb(yt_results, session_prefix),
                parse_mode="HTML"
            )
    except Exception as e:
        await status_msg.edit_text(f"❌ Xatolik: <code>{html.escape(str(e)[:120])}</code>", parse_mode="HTML")
    finally:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass


# =========================================================================
# FOYDALANUVCHI MENYUSI BO'LIMLARI
# =========================================================================

@user_router.message(F.text.in_({BTN_PLATFORMS, "🟠 🔥 Trend va Platformalar", "🔥 Trend va Platformalar"}))
async def menu_platforms(message: Message, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_platforms", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    text = await get_bot_text("txt_platforms")
    await message.answer(text, parse_mode="HTML")


@user_router.message(F.text.in_({BTN_PROFILE, "🟢 👤 Kabinet", "👤 Kabinet"}))
async def menu_profile(message: Message, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_profile", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    u = await get_user(message.from_user.id)
    today_cnt = await get_user_today_downloads(message.from_user.id)
    daily_limit = await get_setting("daily_limit", "0")
    limit_str = "Cheklovsiz ♾" if (daily_limit == "0" or u["is_vip"]) else f"{today_cnt} / {daily_limit} ta"
    mode_str = "⚡ Avtomatik" if u["download_mode"] == "auto" else "🎛 Tanlash orqali"
    status_str = "🌟 VIP Foydalanuvchi" if u["is_vip"] else "👤 Oddiy foydalanuvchi"

    text = await get_bot_text(
        "txt_profile",
        user_id=u["user_id"],
        full_name=u["full_name"],
        status=status_str,
        downloads_count=u["downloads_count"],
        limit_str=limit_str,
        mode_str=mode_str,
        joined_at=u["joined_at"]
    )
    await message.answer(text, parse_mode="HTML")


@user_router.message(F.text.in_({BTN_SETTINGS, "🟡 ⚙️ Sozlamalar"}))
async def menu_settings(message: Message, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_settings", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    u = await get_user(message.from_user.id)
    mode = u["download_mode"] if u else "auto"
    text = await get_bot_text("txt_settings")
    await message.answer(text, reply_markup=user_settings_kb(mode), parse_mode="HTML")


@user_router.callback_query(F.data.startswith("set_mode:"))
async def cb_set_mode(call: CallbackQuery, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_settings", True) and not is_admin:
        return await call.answer("⚠️ Sozlamalar bo'limi admin tomonidan o'chirilgan!", show_alert=True)
    mode = call.data.split(":")[1]
    await update_user_mode(call.from_user.id, mode)
    await call.answer("✅ Yuklash rejimi saqlandi!")
    await call.message.edit_reply_markup(reply_markup=user_settings_kb(mode))


@user_router.message(F.text.in_({BTN_HISTORY, "🔵 📂 Yuklamalar Tarixi"}))
async def menu_history(message: Message, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_history", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    items = await get_user_history(message.from_user.id, limit=10)
    if not items:
        empty_txt = await get_bot_text("txt_history_empty")
        return await message.answer(empty_txt, parse_mode="HTML")
    hist_txt = await get_bot_text("txt_history")
    await message.answer(
        hist_txt,
        reply_markup=history_list_kb(items),
        parse_mode="HTML"
    )


@user_router.callback_query(F.data.startswith("hist_send:"))
async def cb_hist_send(call: CallbackQuery):
    item_id = int(call.data.split(":")[1])
    item = await get_history_item(item_id)
    if not item or not item["file_id"]:
        return await call.answer("❌ Fayl keshdan topilmadi!", show_alert=True)
    await call.answer("🚀 Yuborilmoqda...")
    watermark = await get_bot_text("watermark")
    caption = f"🎬 <b>{html.escape(str(item['title']))}</b>\n\n{watermark}"
    if item["media_type"] == "audio":
        await call.message.answer_audio(item["file_id"], caption=caption, parse_mode="HTML")
    elif item["media_type"] == "photo":
        await call.message.answer_photo(item["file_id"], caption=caption, parse_mode="HTML")
    else:
        await call.message.answer_video(item["file_id"], caption=caption, parse_mode="HTML")


@user_router.message(F.text.in_({BTN_FAVORITES, "🩷 ❤️ Saqlanganlar"}))
async def menu_favorites(message: Message, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_favorites", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    items = await get_favorites(message.from_user.id, limit=15)
    if not items:
        empty_txt = await get_bot_text("txt_favorites_empty")
        return await message.answer(empty_txt, parse_mode="HTML")
    fav_txt = await get_bot_text("txt_favorites")
    await message.answer(
        fav_txt,
        reply_markup=favorites_list_kb(items),
        parse_mode="HTML"
    )


@user_router.callback_query(F.data.startswith("fav_add:"))
async def cb_fav_add(call: CallbackQuery, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_favorites", True) and not is_admin:
        return await call.answer("⚠️ Saqlanganlar bo'limi admin tomonidan o'chirilgan!", show_alert=True)
    hist_id = int(call.data.split(":")[1])
    item = await get_history_item(hist_id)
    if not item:
        return await call.answer("❌ Ma'lumot topilmadi!", show_alert=True)
    added = await add_favorite(call.from_user.id, item["title"], item["url"], item["file_id"], item["media_type"])
    if added:
        await call.answer("❤️ Saqlanganlarga qo'shildi!", show_alert=True)
    else:
        await call.answer("ℹ️ Bu media allaqachon saqlanganlarda bor!", show_alert=True)


@user_router.callback_query(F.data.startswith("fav_send:"))
async def cb_fav_send(call: CallbackQuery):
    fav_id = int(call.data.split(":")[1])
    item = await get_favorite_item(fav_id)
    if not item:
        return await call.answer("❌ Topilmadi!", show_alert=True)
    await call.answer("🚀 Yuborilmoqda...")
    watermark = await get_bot_text("watermark")
    caption = f"❤️ <b>{html.escape(str(item['title']))}</b>\n\n{watermark}"
    if item["media_type"] == "audio":
        await call.message.answer_audio(item["file_id"], caption=caption, parse_mode="HTML")
    elif item["media_type"] == "photo":
        await call.message.answer_photo(item["file_id"], caption=caption, parse_mode="HTML")
    else:
        await call.message.answer_video(item["file_id"], caption=caption, parse_mode="HTML")


@user_router.callback_query(F.data.startswith("fav_del:"))
async def cb_fav_del(call: CallbackQuery):
    fav_id = int(call.data.split(":")[1])
    await delete_favorite(fav_id, call.from_user.id)
    items = await get_favorites(call.from_user.id, limit=15)
    await call.answer("🗑 Ro'yxatdan o'chirildi!")
    if not items:
        empty_txt = await get_bot_text("txt_favorites_empty")
        await call.message.edit_text(empty_txt, parse_mode="HTML")
    else:
        await call.message.edit_reply_markup(reply_markup=favorites_list_kb(items))


@user_router.message(F.text.in_({BTN_HELP, "🩵 ℹ️ Yordam"}))
async def menu_help(message: Message, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_help", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    text = await get_bot_text("txt_help")
    await message.answer(text, parse_mode="HTML")


@user_router.message(F.text.in_({BTN_MUSIC, "🔴 🎵 Qo'shiq Qidirish (YouTube)", "🎵 Qo'shiq qidirish (YouTube)"}))
async def menu_music_search(message: Message, state: FSMContext, is_admin: bool = False):
    menu_cfg = await get_menu_settings()
    if not menu_cfg.get("menu_music", True) and not is_admin:
        disabled_txt = await get_bot_text("txt_section_disabled")
        return await message.answer(
            disabled_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )
    await state.set_state(UserStates.waiting_music_query)
    txt = await get_bot_text("txt_music_prompt")
    await message.answer(txt, parse_mode="HTML")


async def run_youtube_music_search(message: Message, query: str):
    wait_msg = await message.answer(f"🔎 <b>«{html.escape(query)}»</b> bo'yicha qidirilmoqda...", parse_mode="HTML")
    try:
        results = await search_youtube(query, max_results=5)
        if not results:
            return await wait_msg.edit_text("❌ Hech narsa topilmadi. Boshqa so'z bilan qidirib ko'ring.")
        session_prefix = uuid.uuid4().hex[:8]
        SEARCH_SESSIONS[session_prefix] = results
        await wait_msg.edit_text(
            f"🎶 <b>«{html.escape(query)}»</b> bo'yicha topilgan natijalar:\n"
            "<i>🎵 — MP3 audio yuklash | 🎬 Klip — Videoni yuklash</i>",
            reply_markup=search_results_kb(results, session_prefix),
            parse_mode="HTML"
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ Qidiruvda xatolik: <code>{html.escape(str(e)[:120])}</code>", parse_mode="HTML")


@user_router.message(UserStates.waiting_music_query)
async def process_music_search(message: Message, state: FSMContext, bot: Bot):
    if extract_url(message.text):
        await state.clear()
        return await handle_url_message(message, bot)

    query = message.text.strip()
    await state.clear()
    await run_youtube_music_search(message, query)


@user_router.callback_query(F.data.startswith("ytsearch:"))
async def cb_ytsearch_download(call: CallbackQuery, bot: Bot):
    _, prefix, idx_str, m_type = call.data.split(":")
    results = SEARCH_SESSIONS.get(prefix)
    if not results:
        return await call.answer("⏳ Qidiruv sessiyasi eskirgan, qaytadan qidiring.", show_alert=True)
    item = results[int(idx_str)]
    url = item["url"]
    session_key = uuid.uuid4().hex[:10]
    URL_SESSIONS[session_key] = {"url": url, "title": item["title"]}
    await call.answer("📥 Yuklash boshlandi...")
    await execute_download(call.message, bot, call.from_user.id, url, m_type, "best", session_key)


@user_router.callback_query(F.data == "delete_msg")
async def cb_delete_msg(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        await call.answer("O'chirildi")


# =========================================================================
# ASOSIY MATN, HAVOLA YOKI @USERNAME HANDLERI
# =========================================================================

@user_router.message(F.text)
async def handle_url_message(message: Message, bot: Bot, is_admin: bool = False):
    text_str = message.text.strip()
    url = extract_url(text_str)

    if not url:
        clean_u = extract_clean_username(text_str)
        if clean_u:
            return await message.answer(
                f"👤 <b>@{html.escape(clean_u)}</b> bo'yicha qaysi amalni bajaramiz?\n\n"
                "👇 <b>Kerakli tugmani bosing:</b>",
                reply_markup=quick_username_story_kb(clean_u),
                parse_mode="HTML"
            )

        menu_cfg = await get_menu_settings()
        inv_txt = await get_bot_text("txt_invalid_input")
        return await message.answer(
            inv_txt,
            reply_markup=main_menu_kb(is_admin, menu_cfg),
            parse_mode="HTML"
        )

    uid = message.from_user.id
    u = await get_user(uid)

    daily_limit = int(await get_setting("daily_limit", "0"))
    if daily_limit > 0 and not (u and u["is_vip"]):
        today_cnt = await get_user_today_downloads(uid)
        if today_cnt >= daily_limit:
            lim_txt = await get_bot_text("txt_daily_limit_reached", limit=daily_limit)
            return await message.answer(lim_txt, parse_mode="HTML")

    is_story, story_plat = is_story_url(url)
    if is_story:
        return await execute_story_download(message, bot, story_plat, url, user_id=uid)

    session_key = uuid.uuid4().hex[:10]
    URL_SESSIONS[session_key] = {"url": url, "title": "Media"}

    mode = u["download_mode"] if u else "auto"
    if mode == "ask":
        platform, icon = detect_platform(url)
        wait_msg = await message.answer(
            f"{icon} <b>{platform}</b> havolasi tahlil qilinmoqda...\n"
            "<code>[███░░░░░░░] 30%</code>",
            parse_mode="HTML"
        )
        try:
            info = await get_media_info(url)
            URL_SESSIONS[session_key]["title"] = info["title"]
            URL_SESSIONS[session_key]["thumbnail"] = info["thumbnail"]
            caption = (
                f"{icon} <b>Platforma:</b> {platform}\n"
                f"🎬 <b>Nomi:</b> {html.escape(str(info['title'])[:120])}\n"
                f"👤 <b>Muallif:</b> {html.escape(str(info['uploader']))}\n"
                f"⏱ <b>Davomiyligi:</b> {info['duration_str']}\n\n"
                "👇 <b>Kerakli formatni tanlang (yoki Shazam orqali qo'shiqni toping):</b>"
            )
            await wait_msg.edit_text(caption, reply_markup=format_choice_kb(session_key), parse_mode="HTML")
        except Exception:
            await wait_msg.edit_text(
                f"{icon} <b>{platform}</b> havolasi tayyor!\n👇 <b>Yuklash formatini tanlang:</b>",
                reply_markup=format_choice_kb(session_key),
                parse_mode="HTML"
            )
    else:
        await execute_download(message, bot, uid, url, "video", "best", session_key)


@user_router.callback_query(F.data.startswith("dl:"))
async def cb_download_choice(call: CallbackQuery, bot: Bot):
    _, media_type, quality, session_key = call.data.split(":")
    if media_type == "cancel":
        try:
            await call.message.delete()
        except Exception:
            pass
        return await call.answer("❌ Bekor qilindi")

    sess = URL_SESSIONS.get(session_key)
    if not sess:
        return await call.answer("⏳ Havola sessiyasi eskirgan. Havolani qaytadan yuboring!", show_alert=True)

    url = sess["url"]
    if media_type == "thumb":
        await call.answer("🖼 Muqova yuklanmoqda...")
        try:
            info = await get_media_info(url)
            if info.get("thumbnail"):
                await call.message.answer_photo(
                    URLInputFile(info["thumbnail"]),
                    caption=f"🖼 <b>{html.escape(str(info['title'])[:100])}</b>",
                    parse_mode="HTML"
                )
            else:
                await call.message.answer("❌ Ushbu mediada muqova topilmadi.")
        except Exception as e:
            await call.message.answer(f"❌ Xatolik: {html.escape(str(e)[:100])}")
        return

    await call.answer("📥 Yuklab olinmoqda...")
    await execute_download(call.message, bot, call.from_user.id, url, media_type, quality, session_key)


async def execute_download(
    target_msg: Message,
    bot: Bot,
    user_id: int,
    url: str,
    media_type: str,
    quality: str,
    session_key: str
):
    platform, icon = detect_platform(url)
    watermark = await get_bot_text("watermark")
    menu_cfg = await get_menu_settings()
    show_fav = menu_cfg.get("menu_favorites", True)

    cached = await get_cached_media(url, media_type, quality)
    if cached:
        await log_download(user_id, url, cached["title"], platform, media_type, cached["file_id"])
        hist_items = await get_user_history(user_id, limit=1)
        hist_id = hist_items[0]["id"] if hist_items else 0
        caption = f"{icon} <b>{html.escape(str(cached['title'])[:120])}</b>\n\n{watermark}"
        if media_type == "audio":
            await target_msg.answer_audio(cached["file_id"], caption=caption, parse_mode="HTML")
        elif media_type == "photo":
            await target_msg.answer_photo(cached["file_id"], caption=caption, parse_mode="HTML")
        else:
            await target_msg.answer_video(
                cached["file_id"],
                caption=caption,
                reply_markup=under_video_kb(session_key, hist_id, show_fav=show_fav),
                parse_mode="HTML"
            )
        return

    dl_prog_txt = await get_bot_text("txt_downloading", icon=icon, platform=platform)
    prog_msg = await target_msg.answer(dl_prog_txt, parse_mode="HTML")

    filepath = None
    extra_parts = []
    try:
        res = await download_media_file(url, media_type=media_type, quality=quality)
        filepath = res["filepath"]
        title = res["title"]
        is_photo = res.get("is_photo", False)

        if not filepath or not os.path.exists(filepath):
            raise RuntimeError("Faylni saqlashning imkoni bo'lmadi.")

        file_size = os.path.getsize(filepath)
        size_mb = file_size / (1024 * 1024)

        try:
            await prog_msg.edit_text(
                f"{icon} <b>{platform}</b> — Tayyor! ({size_mb:.1f} MB)\n"
                "📤 <i>Telegramga yuborilmoqda...</i>\n"
                "<code>[█████████░] 95%</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        caption = f"{icon} <b>{html.escape(str(title)[:120])}</b>\n\n{watermark}"

        if is_photo:
            await bot.send_chat_action(chat_id=target_msg.chat.id, action="upload_photo")
            sent_msg = await target_msg.answer_photo(
                FSInputFile(filepath),
                caption=caption,
                parse_mode="HTML"
            )
            file_id = sent_msg.photo[-1].file_id if sent_msg.photo else ""
            actual_type = "photo"
        elif media_type == "audio":
            await bot.send_chat_action(chat_id=target_msg.chat.id, action="upload_voice")
            sent_msg = await target_msg.answer_audio(
                FSInputFile(filepath),
                title=str(title)[:60],
                performer=str(res.get("uploader", "MediaBot"))[:40],
                duration=res.get("duration") or None,
                caption=caption,
                parse_mode="HTML"
            )
            file_id = sent_msg.audio.file_id if sent_msg.audio else ""
            actual_type = "audio"
        else:
            actual_type = "video"
            file_id = ""
            if file_size <= BOT_API_MAX_SIZE:
                await bot.send_chat_action(chat_id=target_msg.chat.id, action="upload_video")
                sent_msg = await target_msg.answer_video(
                    FSInputFile(filepath),
                    caption=caption,
                    width=res.get("width") or None,
                    height=res.get("height") or None,
                    duration=res.get("duration") or None,
                    supports_streaming=True,
                    reply_markup=under_video_kb(session_key, 0, show_fav=show_fav),
                    parse_mode="HTML"
                )
                file_id = sent_msg.video.file_id if sent_msg.video else ""
                if file_id:
                    await save_cached_media(url, actual_type, quality, file_id, title, platform)
                    await log_download(user_id, url, title, platform, actual_type, file_id)
                    hist_items = await get_user_history(user_id, limit=1)
                    hist_id = hist_items[0]["id"] if hist_items else 0
                    try:
                        await sent_msg.edit_reply_markup(reply_markup=under_video_kb(session_key, hist_id, show_fav=show_fav))
                    except Exception:
                        pass
            else:
                last_pct = {"v": 0}
                async def _mt_prog(current, total):
                    pct = int(current * 100 / total) if total else 0
                    if pct - last_pct["v"] >= 15:
                        last_pct["v"] = pct
                        try:
                            await prog_msg.edit_text(
                                f"📤 <b>Katta hajmli video ({size_mb:.1f} MB) yuklanmoqda...</b>\n"
                                f"<code>[{'█' * (pct // 10)}{'░' * (10 - pct // 10)}] {pct}%</code>",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass

                mt_ok = await send_large_video_mtproto(
                    chat_id=target_msg.chat.id,
                    filepath=filepath,
                    caption=caption,
                    width=res.get("width"),
                    height=res.get("height"),
                    duration=res.get("duration"),
                    progress_callback=_mt_prog
                )
                if mt_ok:
                    await log_download(user_id, url, title, platform, actual_type, "")
                    await target_msg.answer(
                        "👇 <b>Videodagi original qo'shiqni topish uchun bosing:</b>",
                        reply_markup=under_video_kb(session_key, 0, show_fav=False),
                        parse_mode="HTML"
                    )
                else:
                    await prog_msg.edit_text(
                        f"✂️ <b>Video ({size_mb:.1f} MB) sifatini buzmasdan qismlarga bo'lib yuborilmoqda...</b>",
                        parse_mode="HTML"
                    )
                    extra_parts = await split_video_if_needed(filepath)
                    for idx, part_path in enumerate(extra_parts, start=1):
                        if not os.path.exists(part_path):
                            continue
                        await bot.send_chat_action(chat_id=target_msg.chat.id, action="upload_video")
                        part_cap = f"{icon} <b>{html.escape(str(title)[:100])}</b> (Qism {idx}/{len(extra_parts)})\n\n{watermark}"
                        kb_part = under_video_kb(session_key, 0, show_fav=False) if idx == len(extra_parts) else None
                        await target_msg.answer_video(
                            FSInputFile(part_path),
                            caption=part_cap,
                            supports_streaming=True,
                            reply_markup=kb_part,
                            parse_mode="HTML"
                        )
                    await log_download(user_id, url, title, platform, actual_type, "")

        if file_id and actual_type in ("photo", "audio"):
            await save_cached_media(url, actual_type, quality, file_id, title, platform)
            await log_download(user_id, url, title, platform, actual_type, file_id)

    except Exception as e:
        err_str = str(e)[:160]
        err_msg = await get_bot_text("txt_error_download", error=err_str)
        await target_msg.answer(err_msg, parse_mode="HTML")
    finally:
        try:
            await prog_msg.delete()
        except Exception:
            pass
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        for p in extra_parts:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
