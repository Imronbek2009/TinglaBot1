import os
import re
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from texts import TEXT_DEFINITIONS

BTN_STORIES = "📸 Story ko'rish"
BTN_MUSIC = "🎵 Qo'shiq qidirish"
BTN_PLATFORMS = "🔥 Platformalar"
BTN_HISTORY = "📂 Yuklamalar tarixi"
BTN_FAVORITES = "❤️ Saqlanganlar"
BTN_PROFILE = "💼 Mening hisobim"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_HELP = "ℹ️ Yordam"
BTN_ADMIN = "👑 Admin Panel"

MENU_LABELS = {
    "menu_stories": ("📸 Story ko'rish", BTN_STORIES),
    "menu_music": ("🎵 Qo'shiq qidirish", BTN_MUSIC),
    "menu_platforms": ("🔥 Platformalar", BTN_PLATFORMS),
    "menu_history": ("📂 Yuklamalar tarixi", BTN_HISTORY),
    "menu_favorites": ("❤️ Saqlanganlar", BTN_FAVORITES),
    "menu_profile": ("💼 Mening hisobim", BTN_PROFILE),
    "menu_settings": ("⚙️ Sozlamalar", BTN_SETTINGS),
    "menu_help": ("ℹ️ Yordam", BTN_HELP),
}

COLOR_PROFILES = [
    {
        "green": {"style": "success"},
        "blue": {"style": "primary"},
        "red": {"style": "danger"},
    },
    {
        "green": {"color": "green"},
        "blue": {"color": "blue"},
        "red": {"color": "red"},
    },
    {
        "green": {"color": "success"},
        "blue": {"color": "primary"},
        "red": {"color": "danger"},
    },
    {
        "green": {"color": "positive"},
        "blue": {"color": "primary"},
        "red": {"color": "negative"},
    },
    {
        "green": {"style": "success", "color": "green"},
        "blue": {"style": "primary", "color": "blue"},
        "red": {"style": "danger", "color": "red"},
    },
    {
        "green": {},
        "blue": {},
        "red": {},
    },
]

ACTIVE_COLOR_PROFILE_INDEX = 0


def _auto_detect_local_color_syntax():
    global COLOR_PROFILES
    try:
        fields = set(KeyboardButton.model_fields.keys())
        if "style" in fields and "color" not in fields:
            return
        if "color" in fields and "style" not in fields:
            COLOR_PROFILES.insert(0, {
                "green": {"color": "green"},
                "blue": {"color": "blue"},
                "red": {"color": "red"},
            })
            return
    except Exception:
        pass

    search_dirs = [r"D:\Aql Zor", r"D:\telegram_earn_system_ready"]
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for root, _, files in os.walk(sdir):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fpath = os.path.join(root, fn)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if "Savollarni boshlash" in content or "Mening hisobim" in content:
                        m_green = re.search(
                            r'Savollarni boshlash["\']\s*,\s*([a-zA-Z_]+)\s*=\s*["\']([^"\']+)["\']',
                            content
                        )
                        m_blue = re.search(
                            r'(?:To\'lovlar|Mening hisobim)["\']\s*,\s*([a-zA-Z_]+)\s*=\s*["\']([^"\']+)["\']',
                            content
                        )
                        if m_green:
                            k_g, v_g = m_green.group(1), m_green.group(2)
                            k_b, v_b = (m_blue.group(1), m_blue.group(2)) if m_blue else (k_g, "primary")
                            v_r = "danger" if v_g == "success" else ("negative" if v_g == "positive" else "red")
                            COLOR_PROFILES.insert(0, {
                                "green": {k_g: v_g},
                                "blue": {k_b: v_b},
                                "red": {k_g: v_r},
                            })
                            return
                except Exception:
                    pass


_auto_detect_local_color_syntax()


def _btn_kwargs(color: str | None) -> dict:
    if not color or ACTIVE_COLOR_PROFILE_INDEX >= len(COLOR_PROFILES):
        return {}
    profile = COLOR_PROFILES[ACTIVE_COLOR_PROFILE_INDEX]
    return dict(profile.get(color, {}))


def kbtn(text: str, color: str | None = None) -> KeyboardButton:
    return KeyboardButton(text=text, **_btn_kwargs(color))


def ibtn(text: str, callback_data: str | None = None, url: str | None = None, color: str | None = None) -> InlineKeyboardButton:
    kwargs = _btn_kwargs(color)
    if url:
        return InlineKeyboardButton(text=text, url=url, **kwargs)
    return InlineKeyboardButton(text=text, callback_data=callback_data or "noop", **kwargs)


def main_menu_kb(is_admin_user: bool = False, menu_cfg: dict | None = None) -> ReplyKeyboardMarkup:
    if menu_cfg is None:
        menu_cfg = {k: True for k in MENU_LABELS}

    kb = []

    if menu_cfg.get("menu_stories", True):
        kb.append([kbtn(BTN_STORIES, color="green")])

    middle_keys = [
        "menu_music",
        "menu_platforms",
        "menu_history",
        "menu_favorites",
        "menu_profile",
        "menu_settings",
    ]
    middle_buttons = []
    for key in middle_keys:
        if menu_cfg.get(key, True):
            middle_buttons.append(kbtn(MENU_LABELS[key][1], color="blue"))

    for i in range(0, len(middle_buttons), 2):
        kb.append(middle_buttons[i:i+2])

    if menu_cfg.get("menu_help", True):
        kb.append([kbtn(BTN_HELP, color="green")])

    if is_admin_user:
        kb.append([kbtn(BTN_ADMIN, color="green")])

    if not kb:
        kb.append([kbtn("🔗 Video havolasini yuboring", color="green")])

    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Havola yoki @username yuboring..."
    )


def story_platform_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(text="📸 Instagram Story (@username)", callback_data="story_plat:ig", color="green"),
    )
    builder.row(
        ibtn(text="✈️ Telegram Story (@username)", callback_data="story_plat:tg", color="blue"),
    )
    builder.row(
        ibtn(text="❌ Bekor qilish", callback_data="delete_msg", color="red")
    )
    return builder.as_markup()


def quick_username_story_kb(username: str) -> InlineKeyboardMarkup:
    clean_u = username.lstrip("@").strip()[:28]
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(text=f"📸 Instagram Story (@{clean_u})", callback_data=f"ustory:ig:{clean_u}", color="green")
    )
    builder.row(
        ibtn(text=f"✈️ Telegram Story (@{clean_u})", callback_data=f"ustory:tg:{clean_u}", color="blue")
    )
    builder.row(
        ibtn(text=f"🎵 Qo'shiq qidirish ({clean_u})", callback_data=f"usearch:{clean_u}", color="blue")
    )
    builder.row(
        ibtn(text="❌ Yopish", callback_data="delete_msg", color="red")
    )
    return builder.as_markup()


def sub_check_kb(unsubscribed_channels: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, ch in enumerate(unsubscribed_channels, start=1):
        builder.row(
            ibtn(
                text=f"📢 {idx}. {ch['title']}",
                url=ch['invite_link'],
                color="blue"
            )
        )
    builder.row(
        ibtn(
            text="✅ Obuna bo'ldim",
            callback_data="check_subscription",
            color="green"
        )
    )
    return builder.as_markup()


def format_choice_kb(session_key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(text="🎬 Yuqori sifat (HD / 2GB)", callback_data=f"dl:video:best:{session_key}", color="green"),
        ibtn(text="📱 O'rtacha sifat (480p)", callback_data=f"dl:video:480p:{session_key}", color="blue")
    )
    builder.row(
        ibtn(text="🎵 Original qo'shiqni topish (Shazam)", callback_data=f"shazam:{session_key}", color="green")
    )
    builder.row(
        ibtn(text="🔊 Videoning o'z ovozi", callback_data=f"dl:audio:best:{session_key}", color="blue"),
        ibtn(text="🖼 Muqova", callback_data=f"dl:thumb:best:{session_key}", color="blue")
    )
    builder.row(
        ibtn(text="❌ Bekor qilish", callback_data=f"dl:cancel:none:{session_key}", color="red")
    )
    return builder.as_markup()


def under_video_kb(session_key: str, history_id: int = 0, show_fav: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(text="🎵 Original qo'shiqni topish (Shazam)", callback_data=f"shazam:{session_key}", color="green")
    )
    if history_id and show_fav:
        builder.row(
            ibtn(text="🔊 Video ovozi (MP3)", callback_data=f"dl:audio:best:{session_key}", color="blue"),
            ibtn(text="❤️ Saqlash", callback_data=f"fav_add:{history_id}", color="blue")
        )
    else:
        builder.row(
            ibtn(text="🔊 Videoning o'z ovozi (MP3)", callback_data=f"dl:audio:best:{session_key}", color="blue")
        )
    builder.row(
        ibtn(text="🗑 Xabarni o'chirish", callback_data="delete_msg", color="red")
    )
    return builder.as_markup()


def search_results_kb(results: list, session_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, item in enumerate(results, start=1):
        title = item.get("title", "Audio")[:35]
        duration = item.get("duration_str", "")
        builder.row(
            ibtn(
                text=f"🎵 {idx}. {title} ({duration})",
                callback_data=f"ytsearch:{session_prefix}:{idx-1}:audio",
                color="blue"
            ),
            ibtn(
                text="🎬 Klip",
                callback_data=f"ytsearch:{session_prefix}:{idx-1}:video",
                color="green"
            )
        )
    builder.row(ibtn(text="❌ Yopish", callback_data="delete_msg", color="red"))
    return builder.as_markup()


def user_settings_kb(current_mode: str) -> InlineKeyboardMarkup:
    auto_mark = "✅ " if current_mode == "auto" else ""
    ask_mark = "✅ " if current_mode == "ask" else ""
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(
            text=f"{auto_mark}⚡ Avtomatik (Darhol video yuklash)",
            callback_data="set_mode:auto",
            color="green" if current_mode == "auto" else "blue"
        )
    )
    builder.row(
        ibtn(
            text=f"{ask_mark}🎛 Tanlash orqali (Sifat va format so'rash)",
            callback_data="set_mode:ask",
            color="green" if current_mode == "ask" else "blue"
        )
    )
    return builder.as_markup()


def history_list_kb(items: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, item in enumerate(items, start=1):
        icon = "🎬" if item["media_type"] == "video" else ("🖼" if item["media_type"] == "photo" else "🎵")
        title = (item["title"] or "Media")[:32]
        builder.row(
            ibtn(
                text=f"{idx}. {icon} {title}",
                callback_data=f"hist_send:{item['id']}",
                color="blue"
            )
        )
    builder.row(ibtn(text="❌ Yopish", callback_data="delete_msg", color="red"))
    return builder.as_markup()


def favorites_list_kb(items: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, item in enumerate(items, start=1):
        icon = "🎬" if item["media_type"] == "video" else ("🖼" if item["media_type"] == "photo" else "🎵")
        title = (item["title"] or "Media")[:28]
        builder.row(
            ibtn(
                text=f"{idx}. {icon} {title}",
                callback_data=f"fav_send:{item['id']}",
                color="blue"
            ),
            ibtn(
                text="🗑",
                callback_data=f"fav_del:{item['id']}",
                color="red"
            )
        )
    builder.row(ibtn(text="❌ Yopish", callback_data="delete_msg", color="red"))
    return builder.as_markup()


def admin_panel_kb(force_sub: str, maintenance: str) -> InlineKeyboardMarkup:
    fs_on = (force_sub == "1")
    mt_on = (maintenance == "1")
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(text="📝 Bot matnlarini tahrirlash (Barcha textlar)", callback_data="adm:texts_page:0", color="green")
    )
    builder.row(
        ibtn(text="🎛 Bo'limlarni boshqarish (Menyu UI)", callback_data="adm:ui_menus", color="green")
    )
    builder.row(
        ibtn(text="👁 Story va Cookie sozlamalari (Insta / YouTube / TG)", callback_data="adm:ig_settings", color="blue")
    )
    builder.row(
        ibtn(text="📊 Statistika", callback_data="adm:stats", color="blue"),
        ibtn(text="📢 Majburiy obuna", callback_data="adm:channels", color="blue")
    )
    builder.row(
        ibtn(text="✉️ Xabar yuborish", callback_data="adm:broadcast", color="blue"),
        ibtn(text="👤 Foydalanuvchi izlash", callback_data="adm:user_search", color="blue")
    )
    builder.row(
        ibtn(
            text=f"🔐 Majburiy obuna: {'Yoqilgan' if fs_on else 'O`chirilgan'}",
            callback_data="adm:toggle_fs",
            color="green" if fs_on else "red"
        ),
        ibtn(
            text=f"🛠 Texnik rejim: {'Yoqilgan' if mt_on else 'O`chirilgan'}",
            callback_data="adm:toggle_mt",
            color="red" if mt_on else "green"
        )
    )
    builder.row(
        ibtn(text="⏳ Kunlik limit", callback_data="adm:daily_limit", color="blue"),
        ibtn(text="👮‍♂️ Adminlar", callback_data="adm:admins", color="blue")
    )
    builder.row(
        ibtn(text="💾 Baza nusxasi (Backup)", callback_data="adm:backup", color="blue"),
        ibtn(text="❌ Yopish", callback_data="delete_msg", color="red")
    )
    return builder.as_markup()


def admin_texts_list_kb(page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    keys = list(TEXT_DEFINITIONS.keys())
    total_pages = max(1, (len(keys) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = start + per_page
    for k in keys[start:end]:
        label = TEXT_DEFINITIONS[k][0]
        builder.row(
            ibtn(text=label, callback_data=f"adm:txt_view:{k}:{page}", color="blue")
        )

    nav_btns = []
    if page > 0:
        nav_btns.append(ibtn(text="⬅️ Oldingi", callback_data=f"adm:texts_page:{page-1}", color="green"))
    nav_btns.append(ibtn(text=f"📄 {page+1}/{total_pages}", callback_data="noop", color="blue"))
    if page < total_pages - 1:
        nav_btns.append(ibtn(text="Keyingi ➡️", callback_data=f"adm:texts_page:{page+1}", color="green"))
    builder.row(*nav_btns)

    builder.row(
        ibtn(text="🔄 Barcha matnlarni standartga qaytarish", callback_data="adm:txt_reset_all", color="red")
    )
    builder.row(
        ibtn(text="⬅️ Admin panelga qaytish", callback_data="adm:home", color="blue")
    )
    return builder.as_markup()


def admin_text_detail_kb(t_key: str, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        ibtn(text="✏️ Matnni o'zgartirish", callback_data=f"adm:txt_edit:{t_key}:{page}", color="green")
    )
    builder.row(
        ibtn(text="🔄 Asl (standart) holatiga qaytarish", callback_data=f"adm:txt_reset:{t_key}:{page}", color="red")
    )
    builder.row(
        ibtn(text="⬅️ Matnlar ro'yxatiga qaytish", callback_data=f"adm:texts_page:{page}", color="blue")
    )
    return builder.as_markup()


def admin_ui_menus_kb(menu_cfg: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, (short_label, _) in MENU_LABELS.items():
        is_on = menu_cfg.get(key, True)
        status_text = "✅ Yoqilgan" if is_on else "❌ O'chirilgan"
        builder.row(
            ibtn(
                text=f"{short_label} — {status_text}",
                callback_data=f"adm:toggle_menu:{key}",
                color="green" if is_on else "red"
            )
        )
    builder.row(
        ibtn(text="✅ Barchasini yoqish", callback_data="adm:all_menus:1", color="green"),
        ibtn(text="❌ Barchasini o'chirish", callback_data="adm:all_menus:0", color="red")
    )
    builder.row(
        ibtn(text="🔄 Asosiy klaviaturani yangilash", callback_data="adm:refresh_reply_kb", color="blue")
    )
    builder.row(
        ibtn(text="⬅️ Orqaga", callback_data="adm:home", color="blue")
    )
    return builder.as_markup()


def admin_ig_settings_kb(
    has_session: bool,
    has_cookies_file: bool,
    has_tg_user: bool = False,
    has_yt_cookies: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    s_status = "Ulangan" if has_session else "Kiritilmagan"
    c_status = "Yuklangan" if has_cookies_file else "Yuklanmagan"
    yt_status = "Yuklangan" if has_yt_cookies else "Avto-Bypass"
    tg_status = "Ulangan" if has_tg_user else "Ixtiyoriy"

    builder.row(
        ibtn(
            text=f"▶️ YouTube cookies.txt yuklash ({yt_status})",
            callback_data="adm:upload_yt_cookies",
            color="green" if has_yt_cookies else "blue"
        )
    )
    builder.row(
        ibtn(
            text=f"📸 Instagram sessionid kiritish ({s_status})",
            callback_data="adm:set_ig_session",
            color="green" if has_session else "blue"
        )
    )
    builder.row(
        ibtn(
            text=f"📂 Instagram cookies.txt yuklash ({c_status})",
            callback_data="adm:upload_ig_cookies",
            color="green" if has_cookies_file else "blue"
        )
    )
    builder.row(
        ibtn(
            text=f"✈️ Telegram StringSession kiritish ({tg_status})",
            callback_data="adm:set_tg_session",
            color="green" if has_tg_user else "blue"
        )
    )
    if has_session or has_cookies_file or has_tg_user or has_yt_cookies:
        builder.row(
            ibtn(text="🗑 Barcha Cookie va sessiyalarni tozalash", callback_data="adm:clear_ig_session", color="red")
        )
    builder.row(
        ibtn(text="⬅️ Orqaga", callback_data="adm:home", color="blue")
    )
    return builder.as_markup()


def admin_channels_kb(channels: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.row(
            ibtn(text=f"📢 {ch['title']} ({ch['channel_id']})", url=ch['invite_link'], color="blue"),
            ibtn(text="🗑 O'chirish", callback_data=f"adm:del_ch:{ch['id']}", color="red")
        )
    builder.row(
        ibtn(text="➕ Yangi kanal qo'shish", callback_data="adm:add_ch", color="green")
    )
    builder.row(
        ibtn(text="⬅️ Orqaga", callback_data="adm:home", color="blue")
    )
    return builder.as_markup()


def admin_user_manage_kb(user_row) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    uid = user_row["user_id"]
    ban_text = "🔓 Blokdan chiqarish" if user_row["is_banned"] else "🚫 Bloklash"
    ban_val = 0 if user_row["is_banned"] else 1
    vip_text = "⭐ VIP ni olib tashlash" if user_row["is_vip"] else "🌟 VIP status berish"
    vip_val = 0 if user_row["is_vip"] else 1

    builder.row(
        ibtn(text=ban_text, callback_data=f"adm:ban:{uid}:{ban_val}", color="green" if user_row["is_banned"] else "red"),
        ibtn(text=vip_text, callback_data=f"adm:vip:{uid}:{vip_val}", color="blue" if user_row["is_vip"] else "green")
    )
    builder.row(
        ibtn(text="⬅️ Orqaga", callback_data="adm:home", color="blue")
    )
    return builder.as_markup()
