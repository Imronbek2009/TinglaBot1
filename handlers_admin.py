import os
import html
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import DB_PATH, IG_COOKIES_FILE, YT_COOKIES_FILE
from texts import TEXT_DEFINITIONS
from database import (
    is_admin, get_stats, get_setting, set_setting,
    get_channels, add_channel, remove_channel,
    get_user, set_user_ban, set_user_vip,
    get_all_user_ids, get_all_admins, add_admin_db, remove_admin_db,
    get_menu_settings, MENU_KEYS, reset_bot_text, reset_all_bot_texts
)
from keyboards import (
    BTN_ADMIN, admin_panel_kb, admin_channels_kb, admin_user_manage_kb,
    admin_ui_menus_kb, admin_ig_settings_kb, main_menu_kb,
    admin_texts_list_kb, admin_text_detail_kb
)

admin_router = Router()

class AdminStates(StatesGroup):
    waiting_channel_id = State()
    waiting_channel_title = State()
    waiting_channel_link = State()
    waiting_broadcast = State()
    waiting_user_search = State()
    waiting_daily_limit = State()
    waiting_new_admin = State()
    waiting_ig_session = State()
    waiting_ig_cookies_file = State()
    waiting_yt_cookies_file = State()
    waiting_tg_session = State()
    waiting_custom_text = State()


async def render_admin_panel(target: Message | CallbackQuery):
    force_sub = await get_setting("force_sub", "1")
    maintenance = await get_setting("maintenance", "0")
    watermark = await get_setting("watermark", "")
    daily_limit = await get_setting("daily_limit", "0")
    limit_str = "Cheklovsiz ♾" if daily_limit == "0" else f"{daily_limit} ta / kun"

    text = (
        "👑 <b>ADMIN BOSHQARUV PANELI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔐 <b>Majburiy obuna:</b> {'Yoqilgan' if force_sub == '1' else 'O`chirilgan'}\n"
        f"🛠 <b>Texnik ishlar rejimi:</b> {'Yoqilgan' if maintenance == '1' else 'O`chirilgan'}\n"
        "⚡ <b>Yuklash dvijogi:</b> Multi-Engine Auto (TikWM + GraphQL + Cloud)\n"
        "📦 <b>Maksimal video hajmi:</b> 2 GB (2000 MB)\n"
        f"⏳ <b>Kunlik bepul limit:</b> {limit_str}\n"
        f"📝 <b>Ostki matn (Watermark):</b> <code>{html.escape(watermark[:60])}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Kerakli bo'limni tanlang:"
    )
    kb = admin_panel_kb(force_sub, maintenance)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@admin_router.message(F.text.in_({BTN_ADMIN, "👑 Admin Panel 🟢"}))
async def open_admin_panel_msg(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await state.clear()
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:home")
async def cb_admin_home(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.clear()
    await render_admin_panel(call)


@admin_router.callback_query(F.data.startswith("adm:texts_page:"))
async def cb_admin_texts_page(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.clear()
    page = int(call.data.split(":")[2])
    text = (
        "📝 <b>BOT MATNLARINI BOSHQARISH (BARCHA TEXTLAR)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Bu yerdan bot foydalanuvchilarga yuboradigan <b>har bir xabar matnini</b> "
        "o'zingiz xohlagandek o'zgartirishingiz yoki standart holatiga qaytarishingiz mumkin!\n\n"
        "👇 O'zgartirmoqchi bo'lgan matningizni tanlang:"
    )
    await call.message.edit_text(text, reply_markup=admin_texts_list_kb(page), parse_mode="HTML")
    await call.answer()


@admin_router.callback_query(F.data.startswith("adm:txt_view:"))
async def cb_admin_txt_view(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.clear()
    _, _, t_key, page_str = call.data.split(":")
    page = int(page_str)
    if t_key not in TEXT_DEFINITIONS:
        return await call.answer("❌ Matn topilmadi!", show_alert=True)

    title, placeholders, _ = TEXT_DEFINITIONS[t_key]
    current_val = await get_setting(t_key)

    text = (
        f"📝 <b>MATN: {html.escape(title)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧩 <b>Mavjud o'zgaruvchilar:</b> <code>{html.escape(placeholders)}</code>\n\n"
        "📌 <b>Hozirgi matn ko'rinishi:</b>\n"
        f"<blockquote>{current_val}</blockquote>\n\n"
        "👇 Matnni yangilash uchun <b>«✏️ Matnni o'zgartirish»</b> tugmasini bosing:"
    )
    await call.message.edit_text(text, reply_markup=admin_text_detail_kb(t_key, page), parse_mode="HTML")
    await call.answer()


@admin_router.callback_query(F.data.startswith("adm:txt_edit:"))
async def cb_admin_txt_edit(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    _, _, t_key, page_str = call.data.split(":")
    page = int(page_str)
    if t_key not in TEXT_DEFINITIONS:
        return await call.answer("❌ Matn topilmadi!", show_alert=True)

    title, placeholders, _ = TEXT_DEFINITIONS[t_key]
    current_val = await get_setting(t_key)

    await state.set_state(AdminStates.waiting_custom_text)
    await state.update_data(edit_text_key=t_key, edit_text_page=page)

    await call.message.edit_text(
        f"✏️ <b>«{html.escape(title)}» MATNINI O'ZGARTIRISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧩 <b>Ishlatish mumkin bo'lgan o'zgaruvchilar:</b>\n<code>{html.escape(placeholders)}</code>\n\n"
        "📄 <b>Hozirgi matn (nusxalab olish uchun):</b>\n"
        f"<code>{html.escape(current_val)}</code>\n\n"
        "✍️ <b>Yangi matnni yozib yuboring:</b>\n"
        "<i>(Matnni Telegramning o'zida qalin/kursiv qilib yuborishingiz yoki <code>&lt;b&gt;...&lt;/b&gt;</code> teglaridan foydalanishingiz mumkin. Bekor qilish uchun /cancel yozing)</i>",
        parse_mode="HTML"
    )
    await call.answer()


@admin_router.message(AdminStates.waiting_custom_text)
async def process_custom_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    t_key = data.get("edit_text_key")
    page = data.get("edit_text_page", 0)

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        return await render_admin_panel(message)

    raw_text = message.text or message.caption or ""
    if not raw_text.strip():
        return await message.answer("❌ Iltimos, matn yuboring yoki /cancel bosing!")

    if any(tag in raw_text for tag in ("<b>", "</b>", "<i>", "</i>", "<code>", "</code>", "<blockquote>", "<a ")):
        new_value = raw_text
    else:
        new_value = getattr(message, "html_text", None) or raw_text

    await set_setting(t_key, new_value)
    await state.clear()

    title, _, _ = TEXT_DEFINITIONS.get(t_key, ("Matn", "", ""))
    await message.answer(
        f"✅ <b>«{html.escape(title)}» muvaffaqiyatli yangilandi!</b>\n\n"
        f"📌 <b>Yangi ko'rinishi:</b>\n<blockquote>{new_value}</blockquote>",
        reply_markup=admin_text_detail_kb(t_key, page),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data.startswith("adm:txt_reset:"))
async def cb_admin_txt_reset_single(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    _, _, t_key, page_str = call.data.split(":")
    page = int(page_str)
    await reset_bot_text(t_key)
    await call.answer("🔄 Matn asl (standart) holatiga qaytarildi!", show_alert=True)

    title, placeholders, _ = TEXT_DEFINITIONS[t_key]
    current_val = await get_setting(t_key)
    text = (
        f"📝 <b>MATN: {html.escape(title)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧩 <b>Mavjud o'zgaruvchilar:</b> <code>{html.escape(placeholders)}</code>\n\n"
        "📌 <b>Hozirgi matn ko'rinishi:</b>\n"
        f"<blockquote>{current_val}</blockquote>\n\n"
        "👇 Matnni yangilash uchun <b>«✏️ Matnni o'zgartirish»</b> tugmasini bosing:"
    )
    await call.message.edit_text(text, reply_markup=admin_text_detail_kb(t_key, page), parse_mode="HTML")


@admin_router.callback_query(F.data == "adm:txt_reset_all")
async def cb_admin_txt_reset_all(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    await reset_all_bot_texts()
    await call.answer("✅ Barcha matnlar standart holatga qaytarildi!", show_alert=True)


@admin_router.callback_query(F.data == "adm:ui_menus")
async def cb_admin_ui_menus(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    menu_cfg = await get_menu_settings()
    text = (
        "🎛 <b>FOYDALANUVCHI BO'LIMLARINI BOSHQARISH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Bu yerdan foydalanuvchilarga ko'rinadigan har bir bo'limni (masalan: <b>❤️ Saqlanganlar</b>, <b>⚙️ Sozlamalar</b>, <b>📸 Story ko'rish</b> va h.k.) "
        "1 ta tugma bilan o'chirib yoki yoqib qo'yishingiz mumkin.\n\n"
        "O'chirilgan bo'limlar oddiy foydalanuvchilarning menyusidan (klaviaturasidan) butunlay yo'qoladi:"
    )
    await call.message.edit_text(text, reply_markup=admin_ui_menus_kb(menu_cfg), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm:toggle_menu:"))
async def cb_toggle_single_menu(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    key = call.data.split(":")[2]
    curr = await get_setting(key, "1")
    new_val = "0" if curr == "1" else "1"
    await set_setting(key, new_val)
    menu_cfg = await get_menu_settings()
    status_str = "✅ Yoqildi (Foydalanuvchilarga ko'rinadi)" if new_val == "1" else "❌ O'chirildi (Yashirildi)"
    await call.answer(status_str)
    await call.message.edit_reply_markup(reply_markup=admin_ui_menus_kb(menu_cfg))


@admin_router.callback_query(F.data.startswith("adm:all_menus:"))
async def cb_toggle_all_menus(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    val = call.data.split(":")[2]
    for k in MENU_KEYS:
        await set_setting(k, val)
    menu_cfg = await get_menu_settings()
    await call.answer("✅ Barcha bo'limlar yoqildi!" if val == "1" else "❌ Barcha bo'limlar o'chirildi!")
    await call.message.edit_reply_markup(reply_markup=admin_ui_menus_kb(menu_cfg))


@admin_router.callback_query(F.data == "adm:refresh_reply_kb")
async def cb_refresh_reply_kb(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    menu_cfg = await get_menu_settings()
    await call.answer("🔄 Pastdagi klaviatura menyusi yangilandi!")
    await call.message.answer(
        "✅ <b>Klaviatura menyusi joriy sozlamalarga mos ravishda yangilandi!</b>",
        reply_markup=main_menu_kb(True, menu_cfg),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "adm:ig_settings")
async def cb_admin_ig_settings(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.clear()
    ig_sess = await get_setting("ig_sessionid", "")
    tg_sess = await get_setting("tg_user_session_string", "")
    has_sess = bool(ig_sess)
    has_file = os.path.exists(IG_COOKIES_FILE)
    has_yt = os.path.exists(YT_COOKIES_FILE)
    has_tg = bool(tg_sess)

    text = (
        "👁 <b>QO'SHIMCHA COOKIE VA STORY SOZLAMALARI (IXTIYORIY)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ <i>Botda barcha ochiq YouTube, TikTok, Instagram va Storylar hech qanday cookiesiz <b>Avto-Rejimda</b> ishlaydi! Quyidagilar faqat yopiq (Private) profillar uchun ixtiyoriy:</i>\n\n"
        f"▶️ <b>YouTube:</b> {'cookies.txt ulangan ✅' if has_yt else 'Avto-Cloud + VR Bypass ⚡'}\n"
        f"📸 <b>Instagram:</b> {'sessionid ulangan ✅' if has_sess else 'Avto-GraphQL + AnonStory ⚡'}\n"
        f"✈️ <b>Telegram Story:</b> {'StringSession ulangan ✅' if has_tg else 'Avto-Scanner + Forward ⚡'}"
    )
    await call.message.edit_text(
        text,
        reply_markup=admin_ig_settings_kb(has_sess, has_file, has_tg, has_yt),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "adm:upload_yt_cookies")
async def cb_upload_yt_cookies(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_yt_cookies_file)
    await call.message.edit_text(
        "▶️ <b>YOUTUBE COOKIES.TXT FAYLINI YUKLASH</b>\n\n"
        "Netscape formatidagi <code>cookies.txt</code> faylni Document sifatida yuboring yoki /cancel bosing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_yt_cookies_file)
async def process_yt_cookies_file(message: Message, state: FSMContext, bot: Bot):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)
    if not message.document:
        return await message.answer("❌ Iltimos, fayl sifatida yuboring yoki /cancel bosing!")
    file_info = await bot.get_file(message.document.file_id)
    await bot.download_file(file_info.file_path, destination=YT_COOKIES_FILE)
    await state.clear()
    await message.answer("✅ <b>YouTube cookies.txt saqlandi!</b>", parse_mode="HTML")
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:set_ig_session")
async def cb_set_ig_session(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_ig_session)
    await call.message.edit_text(
        "🔑 <b>INSTAGRAM SESSIONID KIRITISH</b>\n\n"
        "Yopiq profillar uchun <code>sessionid</code> qiymatini yuboring yoki /cancel bosing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_ig_session)
async def process_ig_session(message: Message, state: FSMContext):
    if message.text != "/cancel":
        await set_setting("ig_sessionid", message.text.strip())
        await message.answer("✅ <b>Instagram sessionid saqlandi!</b>", parse_mode="HTML")
    await state.clear()
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:set_tg_session")
async def cb_set_tg_session(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_tg_session)
    await call.message.edit_text(
        "✈️ <b>TELEGRAM STRINGSESSION KIRITISH</b>\n\n"
        "Telethon <code>StringSession</code> satrini yuboring yoki /cancel bosing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_tg_session)
async def process_tg_session(message: Message, state: FSMContext):
    if message.text != "/cancel":
        await set_setting("tg_user_session_string", message.text.strip())
        await message.answer("✅ <b>Telegram StringSession saqlandi!</b>", parse_mode="HTML")
    await state.clear()
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:upload_ig_cookies")
async def cb_upload_ig_cookies(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_ig_cookies_file)
    await call.message.edit_text(
        "📂 <b>INSTAGRAM COOKIES.TXT YUKLASH</b>\n\n"
        "Faylni Document sifatida yuboring yoki /cancel bosing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_ig_cookies_file)
async def process_ig_cookies_file(message: Message, state: FSMContext, bot: Bot):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)
    if not message.document:
        return await message.answer("❌ Fayl sifatida yuboring yoki /cancel bosing!")
    file_info = await bot.get_file(message.document.file_id)
    await bot.download_file(file_info.file_path, destination=IG_COOKIES_FILE)
    await state.clear()
    await message.answer("✅ <b>Instagram cookies.txt saqlandi!</b>", parse_mode="HTML")
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:clear_ig_session")
async def cb_clear_ig_session(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    await set_setting("ig_sessionid", "")
    await set_setting("tg_user_session_string", "")
    for fpath in (IG_COOKIES_FILE, YT_COOKIES_FILE):
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    await call.answer("🗑 Barcha Cookie va sessiyalar tozalandi!", show_alert=True)
    await render_admin_panel(call)


@admin_router.callback_query(F.data == "adm:stats")
async def cb_admin_stats(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    st = await get_stats()
    plat_lines = []
    for p_name, cnt in st["platforms"]:
        plat_lines.append(f"  ▫️ <b>{html.escape(str(p_name))}:</b> {cnt} ta")
    plat_text = "\n".join(plat_lines) if plat_lines else "  ▫️ Hozircha yuklamalar yo'q"

    text = (
        "📊 <b>BOTNING BATAFSIL STATISTIKASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {st['total_users']} ta\n"
        f"🆕 <b>Bugun qo'shilganlar:</b> +{st['today_users']} ta\n"
        f"🌟 <b>VIP foydalanuvchilar:</b> {st['vip_users']} ta\n"
        f"🚫 <b>Bloklanganlar:</b> {st['banned_users']} ta\n\n"
        f"📥 <b>Jami yuklangan medialar:</b> {st['total_downloads']} ta\n"
        f"⚡ <b>Bugungi yuklamalar:</b> {st['today_downloads']} ta\n"
        f"🚀 <b>Tezkor keshdagi (file_id) fayllar:</b> {st['cached_files']} ta\n\n"
        "🌐 <b>Platformalar kesimida:</b>\n"
        f"{plat_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    force_sub = await get_setting("force_sub", "1")
    maintenance = await get_setting("maintenance", "0")
    await call.message.edit_text(text, reply_markup=admin_panel_kb(force_sub, maintenance), parse_mode="HTML")
    await call.answer("📊 Statistika yangilandi!")


@admin_router.callback_query(F.data == "adm:toggle_fs")
async def cb_toggle_fs(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    curr = await get_setting("force_sub", "1")
    new_val = "0" if curr == "1" else "1"
    await set_setting("force_sub", new_val)
    await call.answer(f"Majburiy obuna: {'Yoqildi' if new_val == '1' else 'O`chirildi'}")
    await render_admin_panel(call)


@admin_router.callback_query(F.data == "adm:toggle_mt")
async def cb_toggle_mt(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    curr = await get_setting("maintenance", "0")
    new_val = "0" if curr == "1" else "1"
    await set_setting("maintenance", new_val)
    await call.answer(f"Texnik ishlar rejimi: {'Yoqildi' if new_val == '1' else 'O`chirildi'}")
    await render_admin_panel(call)


@admin_router.callback_query(F.data == "adm:channels")
async def cb_admin_channels(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.clear()
    channels = await get_channels()
    text = (
        "📢 <b>MAJBURIY OBUNA KANALLARI BOSHQARUVI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ <i>Eslatma: Bot kanalda a'zolarni tekshira olishi uchun uni o'sha kanalga <b>Admin</b> qilishingiz shart!</i>\n\n"
        f"📋 Ulangan kanallar soni: <b>{len(channels)} ta</b>"
    )
    await call.message.edit_text(text, reply_markup=admin_channels_kb(channels), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm:del_ch:"))
async def cb_del_channel(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    ch_db_id = int(call.data.split(":")[2])
    await remove_channel(ch_db_id)
    await call.answer("🗑 Kanal o'chirildi!", show_alert=True)
    channels = await get_channels()
    await call.message.edit_reply_markup(reply_markup=admin_channels_kb(channels))


@admin_router.callback_query(F.data == "adm:add_ch")
async def cb_add_channel_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_channel_id)
    await call.message.edit_text(
        "➕ <b>YANGI KANAL QO'SHISH (1/3)</b>\n\n"
        "Kanalning <b>username</b> (@kanal_nomi) yoki <b>ID</b> raqamini (-100123456789) yuboring:\n\n"
        "<i>⚠️ Avval botni kanalga Admin qilganingizga ishonch hosil qiling!</i>\n"
        "Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_channel_id)
async def process_channel_id(message: Message, state: FSMContext, bot: Bot):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)

    ch_id = message.text.strip()
    try:
        chat = await bot.get_chat(ch_id)
        default_title = chat.title or "Kanal"
        default_link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "")
    except Exception:
        default_title = ""
        default_link = ""

    await state.update_data(channel_id=ch_id, default_title=default_title, default_link=default_link)
    await state.set_state(AdminStates.waiting_channel_title)

    hint = f"\n(Avto aniqlangan nom: <code>{html.escape(default_title)}</code> — shu nom qolishi uchun <b>.</b> nuqta yuboring)" if default_title else ""
    await message.answer(
        f"➕ <b>YANGI KANAL QO'SHISH (2/3)</b>\n\n"
        f"Tugmada ko'rinadigan <b>Kanal nomini</b> kiriting:{hint}",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_channel_title)
async def process_channel_title(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)

    data = await state.get_data()
    title = message.text.strip()
    if title == "." and data.get("default_title"):
        title = data["default_title"]

    await state.update_data(title=title)
    await state.set_state(AdminStates.waiting_channel_link)

    default_link = data.get("default_link", "")
    hint = f"\n(Avto havola: <code>{html.escape(default_link)}</code> — shu qolishi uchun <b>.</b> nuqta yuboring)" if default_link else ""
    await message.answer(
        f"➕ <b>YANGI KANAL QO'SHISH (3/3)</b>\n\n"
        f"Kanalga kirish <b>havolasini (linkini)</b> yuboring (https://t.me/...):{hint}",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_channel_link)
async def process_channel_link(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)

    data = await state.get_data()
    link = message.text.strip()
    if link == "." and data.get("default_link"):
        link = data["default_link"]
    if link.startswith("@"):
        link = f"https://t.me/{link[1:]}"

    await add_channel(data["channel_id"], data["title"], link)
    await state.clear()
    await message.answer("✅ <b>Kanal muvaffaqiyatli majburiy obuna ro'yxatiga qo'shildi!</b>", parse_mode="HTML")
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await call.message.edit_text(
        "✉️ <b>OMMAVIY XABAR YUBORISH (BROADCAST)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring.\n"
        "Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)

    await state.clear()
    user_ids = await get_all_user_ids()
    total = len(user_ids)
    status_msg = await message.answer(f"🚀 Xabar yuborish boshlandi... (0 / {total})")

    sent = 0
    failed = 0
    for idx, uid in enumerate(user_ids, start=1):
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1
        if idx % 25 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ <b>Yuborilmoqda...</b> ({idx} / {total})\n"
                    f"✅ Yetib bordi: {sent} ta | ❌ Xato: {failed} ta",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        await asyncio.sleep(0.04)

    await status_msg.edit_text(
        f"✅ <b>Ommaviy xabar yuborish yakunlandi!</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total} ta</b>\n"
        f"✅ Muvaffaqiyatli: <b>{sent} ta</b>\n"
        f"❌ Bloklagan / xato: <b>{failed} ta</b>",
        parse_mode="HTML"
    )
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:user_search")
async def cb_user_search(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_user_search)
    await call.message.edit_text(
        "👤 <b>FOYDALANUVCHINI TOPISH VA BOSHQARISH</b>\n\n"
        "Foydalanuvchining <b>Telegram ID</b> raqamini yuboring:\n"
        "Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_user_search)
async def process_user_search(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await render_admin_panel(message)

    if not message.text.strip().isdigit():
        return await message.answer("❌ Iltimos, faqat raqamdan iborat Telegram ID kiriting!")

    uid = int(message.text.strip())
    u = await get_user(uid)
    await state.clear()
    if not u:
        await message.answer("❌ Bunday ID ga ega foydalanuvchi bazadan topilmadi.")
        return await render_admin_panel(message)

    text = (
        "👤 <b>FOYDALANUVCHI MA'LUMOTLARI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{u['user_id']}</code>\n"
        f"👤 <b>Ism:</b> {html.escape(str(u['full_name']))}\n"
        f"🌐 <b>Username:</b> @{html.escape(str(u['username'] if u['username'] else 'mavjud_emas'))}\n"
        f"📥 <b>Jami yuklamalari:</b> {u['downloads_count']} ta\n"
        f"🌟 <b>Status:</b> {'VIP 🌟' if u['is_vip'] else 'Oddiy'}\n"
        f"🚫 <b>Holati:</b> {'Bloklangan' if u['is_banned'] else 'Faol'}\n"
        f"📅 <b>Qo'shilgan vaqti:</b> {u['joined_at']}"
    )
    await message.answer(text, reply_markup=admin_user_manage_kb(u), parse_mode="HTML")


@admin_router.callback_query(F.data.startswith("adm:ban:"))
async def cb_user_ban(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    _, _, uid_str, val_str = call.data.split(":")
    uid, val = int(uid_str), int(val_str)
    await set_user_ban(uid, val)
    u = await get_user(uid)
    await call.answer("Holat o'zgartirildi!")
    await call.message.edit_reply_markup(reply_markup=admin_user_manage_kb(u))


@admin_router.callback_query(F.data.startswith("adm:vip:"))
async def cb_user_vip(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    _, _, uid_str, val_str = call.data.split(":")
    uid, val = int(uid_str), int(val_str)
    await set_user_vip(uid, val)
    u = await get_user(uid)
    await call.answer("VIP status o'zgartirildi!")
    await call.message.edit_reply_markup(reply_markup=admin_user_manage_kb(u))


@admin_router.callback_query(F.data == "adm:daily_limit")
async def cb_daily_limit(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    curr = await get_setting("daily_limit", "0")
    await state.set_state(AdminStates.waiting_daily_limit)
    await call.message.edit_text(
        f"⏳ <b>KUNLIK YUKLASH LIMITINI SOZLASH</b>\n\n"
        f"Hozirgi limit: <b>{curr}</b> (0 = cheklovsiz)\n\n"
        "Oddiy foydalanuvchilar kuniga nechta media yuklay olsin? Raqam yuboring (cheklovsiz qilish uchun 0 yuboring):\n"
        "Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_daily_limit)
async def process_daily_limit(message: Message, state: FSMContext):
    if message.text != "/cancel" and message.text.strip().isdigit():
        await set_setting("daily_limit", message.text.strip())
        await message.answer("✅ Kunlik limit saqlandi!")
    await state.clear()
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:admins")
async def cb_admins_manage(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        return
    admins = await get_all_admins()
    adm_list = "\n".join([f"👮‍♂️ <code>{a}</code>" for a in admins])
    await state.set_state(AdminStates.waiting_new_admin)
    await call.message.edit_text(
        f"👮‍♂️ <b>ADMINLAR RO'YXATI:</b>\n{adm_list}\n\n"
        "➕ Yangi admin qo'shish uchun uning Telegram ID raqamini yuboring.\n"
        "➖ Adminni o'chirish uchun ID oldiga minus qo'yib yuboring (masalan: <code>-1234567</code>).\n"
        "Bekor qilish uchun /cancel yozing.",
        parse_mode="HTML"
    )


@admin_router.message(AdminStates.waiting_new_admin)
async def process_new_admin(message: Message, state: FSMContext):
    txt = message.text.strip()
    if txt != "/cancel":
        if txt.startswith("-") and txt[1:].isdigit():
            await remove_admin_db(int(txt[1:]))
            await message.answer("🗑 Admin ro'yxatdan o'chirildi!")
        elif txt.isdigit():
            await add_admin_db(int(txt))
            await message.answer("✅ Yangi admin muvaffaqiyatli qo'shildi!")
    await state.clear()
    await render_admin_panel(message)


@admin_router.callback_query(F.data == "adm:backup")
async def cb_backup_db(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        return
    await call.answer("📦 Baza nusxasi tayyorlanmoqda...")
    if os.path.exists(DB_PATH):
        doc = FSInputFile(DB_PATH, filename="database_backup.db")
        await call.message.answer_document(
            doc,
            caption="💾 <b>SQLite ma'lumotlar bazasining to'liq zaxira nusxasi (Backup)</b>",
            parse_mode="HTML"
        )
