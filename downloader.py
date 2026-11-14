import os
import re
import json
import html
import uuid
import math
import shutil
import asyncio
import subprocess
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import yt_dlp

from config import (
    DOWNLOAD_DIR, MAX_FILESIZE, BOT_API_MAX_SIZE,
    IG_COOKIES_FILE, YT_COOKIES_FILE,
    BOT_TOKEN, TG_API_ID, TG_API_HASH, TELETHON_BOT_SESSION
)
from database import get_setting

URL_REGEX = re.compile(r"(https?://[^\s]+)")
USERNAME_REGEX = re.compile(r"^@?([A-Za-z0-9._]{3,32})$")
YT_ID_REGEX = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})")

_mtproto_bot_client = None
_mtproto_lock = asyncio.Lock()

# YouTube "Sign in to confirm you're not a bot" ni chetlab o'tuvchi maxsus client sozlamasi
YT_BYPASS_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["android_vr", "tv_embedded", "mweb", "ios", "web_embedded"],
        "player_skip": ["webpage", "configs"],
    }
}


def extract_url(text: str) -> str | None:
    if not text:
        return None
    match = URL_REGEX.search(text)
    return match.group(1) if match else None


def extract_clean_username(text: str) -> str | None:
    if not text:
        return None
    t = text.strip()
    if " " in t or "/" in t:
        return None
    m = USERNAME_REGEX.match(t)
    return m.group(1) if m else None


def extract_yt_video_id(url: str) -> str | None:
    m = YT_ID_REGEX.search(url)
    return m.group(1) if m else None


def is_story_url(url: str) -> tuple[bool, str]:
    u = url.lower()
    if "instagram.com/stories/" in u:
        return True, "ig"
    if ("t.me/" in u or "telegram.me/" in u) and "/s/" in u:
        return True, "tg"
    return False, ""


def detect_platform(url: str) -> tuple[str, str]:
    u = url.lower()
    if "instagram.com/stories/" in u:
        return "Instagram Story", "📸"
    elif "instagram.com" in u:
        return "Instagram", "📸"
    elif ("t.me/" in u or "telegram.me/" in u) and "/s/" in u:
        return "Telegram Story", "✈️"
    elif "tiktok.com" in u:
        return "TikTok", "🎵"
    elif "youtube.com" in u or "youtu.be" in u:
        return "YouTube", "▶️"
    elif "pinterest." in u or "pin.it" in u:
        return "Pinterest", "📌"
    elif "facebook.com" in u or "fb.watch" in u:
        return "Facebook", "📘"
    elif "twitter.com" in u or "x.com" in u:
        return "X (Twitter)", "🐦"
    elif "likee." in u:
        return "Likee", "❤️"
    elif "threads.net" in u:
        return "Threads", "🧵"
    elif "vk.com" in u:
        return "VK", "🌐"
    return "Media", "🌐"


def get_ffmpeg_path() -> str | None:
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def format_duration(seconds) -> str:
    if not seconds:
        return "00:00"
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except Exception:
        return "00:00"


# =========================================================================
# 2 GB GACHA YUKLASH UCHUN MTPROTO BRIDGE + FFMPEG SPLITTER ZAXIRA TIZIMI
# =========================================================================

async def get_mtproto_bot():
    global _mtproto_bot_client
    async with _mtproto_lock:
        if _mtproto_bot_client is not None and _mtproto_bot_client.is_connected():
            return _mtproto_bot_client
        try:
            from telethon import TelegramClient
            client = TelegramClient(TELETHON_BOT_SESSION, TG_API_ID, TG_API_HASH)
            await client.start(bot_token=BOT_TOKEN)
            _mtproto_bot_client = client
            return _mtproto_bot_client
        except Exception:
            return None


async def send_large_video_mtproto(
    chat_id: int,
    filepath: str,
    caption: str,
    width: int | None = None,
    height: int | None = None,
    duration: int | None = None,
    progress_callback=None
) -> bool:
    client = await get_mtproto_bot()
    if not client:
        return False
    try:
        from telethon.tl.types import DocumentAttributeVideo
        attrs = [
            DocumentAttributeVideo(
                duration=int(duration or 0),
                w=int(width or 1280),
                h=int(height or 720),
                supports_streaming=True
            )
        ]
        await client.send_file(
            entity=chat_id,
            file=filepath,
            caption=caption,
            parse_mode="html",
            attributes=attrs,
            supports_streaming=True,
            progress_callback=progress_callback
        )
        return True
    except Exception:
        return False


def _sync_split_video_ffmpeg(filepath: str, segment_max_mb: int = 46) -> list[str]:
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(filepath):
        return []

    fsize = os.path.getsize(filepath)
    num_parts = math.ceil(fsize / (segment_max_mb * 1024 * 1024))
    if num_parts <= 1:
        return [filepath]

    base, ext = os.path.splitext(filepath)
    out_pattern = f"{base}_part%02d{ext}"
    cmd = [
        ffmpeg_exe, "-y", "-i", filepath,
        "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", "300",
        "-reset_timestamps", "1",
        out_pattern
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        parts = sorted([
            os.path.join(os.path.dirname(filepath), f)
            for f in os.listdir(os.path.dirname(filepath))
            if f.startswith(os.path.basename(base) + "_part")
        ])
        return parts
    except Exception:
        return []


async def split_video_if_needed(filepath: str) -> list[str]:
    return await asyncio.to_thread(_sync_split_video_ffmpeg, filepath)


# =========================================================================
# SHAZAM ORQALI ORIGINAL QO'SHIQNI ANIQLASH VA TO'LIQ MP3 YUKLASH TIZIMI
# =========================================================================

def _extract_audio_sample_ffmpeg(input_media_path: str, duration_sec: int = 15) -> str | None:
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(input_media_path):
        return None
    sample_path = os.path.join(DOWNLOAD_DIR, f"shazam_sample_{uuid.uuid4().hex[:8]}.mp3")
    cmd = [
        ffmpeg_exe, "-y",
        "-i", input_media_path,
        "-vn", "-acodec", "libmp3lame",
        "-ar", "44100", "-ac", "2",
        "-b:a", "128k",
        "-t", str(duration_sec),
        sample_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if os.path.exists(sample_path) and os.path.getsize(sample_path) > 1024:
            return sample_path
    except Exception:
        pass
    return None


async def recognize_song_shazam(media_path: str | None = None, source_url: str | None = None) -> dict | None:
    temp_downloaded = None
    sample_path = None
    metadata_guess = None

    try:
        if (not media_path or not os.path.exists(media_path)) and source_url:
            def _fetch_small_audio():
                uid = uuid.uuid4().hex[:8]
                out = os.path.join(DOWNLOAD_DIR, f"shz_dl_{uid}.%(ext)s")
                opts = {
                    "format": "worstaudio/bestaudio/best",
                    "outtmpl": out,
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "max_filesize": 25 * 1024 * 1024,
                    "extractor_args": YT_BYPASS_EXTRACTOR_ARGS,
                }
                if os.path.exists(YT_COOKIES_FILE) and ("youtube.com" in source_url.lower() or "youtu.be" in source_url.lower()):
                    opts["cookiefile"] = YT_COOKIES_FILE
                ff = get_ffmpeg_path()
                if ff:
                    opts["ffmpeg_location"] = ff
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(source_url, download=True)
                    if "entries" in info and info["entries"]:
                        info = info["entries"][0]
                    fn = ydl.prepare_filename(info)
                    if not os.path.exists(fn):
                        base, _ = os.path.splitext(fn)
                        for ext in [".m4a", ".mp3", ".webm", ".mp4", ".opus"]:
                            if os.path.exists(base + ext):
                                fn = base + ext
                                break
                    track = info.get("track") or info.get("alt_title")
                    artist = info.get("artist") or info.get("creator") or info.get("uploader")
                    title = info.get("title") or ""
                    meta = {
                        "track": track,
                        "artist": artist,
                        "title": title,
                    }
                    return fn, meta

            try:
                temp_downloaded, metadata_guess = await asyncio.to_thread(_fetch_small_audio)
                media_path = temp_downloaded
            except Exception:
                pass

        if media_path and os.path.exists(media_path):
            sample_path = await asyncio.to_thread(_extract_audio_sample_ffmpeg, media_path, 15)
            target_for_shazam = sample_path if (sample_path and os.path.exists(sample_path)) else media_path

            try:
                from shazamio import Shazam
                shazam = Shazam()
                out = await shazam.recognize(target_for_shazam)
                track_info = out.get("track")
                if track_info:
                    title = track_info.get("title", "")
                    subtitle = track_info.get("subtitle", "")
                    full_query = f"{subtitle} - {title}".strip(" -")
                    images = track_info.get("images", {})
                    cover = images.get("coverarthq") or images.get("coverart")
                    return {
                        "artist": subtitle or "Original Artist",
                        "title": title or "Qo'shiq",
                        "full_name": full_query,
                        "cover": cover,
                        "source": "Shazam 🎵"
                    }
            except Exception:
                pass

        if not metadata_guess and source_url:
            try:
                info = await get_media_info(source_url)
                metadata_guess = info
            except Exception:
                pass

        if metadata_guess:
            track = metadata_guess.get("track")
            artist = metadata_guess.get("artist") or metadata_guess.get("uploader", "")
            raw_title = metadata_guess.get("title", "")
            if track:
                full_q = f"{artist} - {track}" if artist else track
                return {
                    "artist": artist or "Original",
                    "title": track,
                    "full_name": full_q,
                    "cover": None,
                    "source": "Media Audio 🎶"
                }
            clean_t = re.sub(r"#\S+", "", raw_title).strip()
            clean_t = re.sub(r"(?i)(official\s*video|shorts|reels|tiktok|video|status)", "", clean_t).strip(" -|:")
            if len(clean_t) >= 3 and clean_t.lower() not in ("media", "video", "instagram", "tiktok"):
                return {
                    "artist": artist or "YouTube Music",
                    "title": clean_t[:60],
                    "full_name": f"{clean_t[:60]}",
                    "cover": None,
                    "source": "Smart Search 🔎"
                }

        return None
    finally:
        for p in (sample_path, temp_downloaded):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


# =========================================================================
# MA'LUMOT OLISH VA YOUTUBE QIDIRUV
# =========================================================================

def _sync_get_info(url: str, ig_sessionid: str = "") -> dict:
    u_low = url.lower()
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        "extractor_args": YT_BYPASS_EXTRACTOR_ARGS,
    }
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path
    if "instagram.com" in u_low:
        if os.path.exists(IG_COOKIES_FILE):
            ydl_opts["cookiefile"] = IG_COOKIES_FILE
        elif ig_sessionid:
            ydl_opts["http_headers"] = {"Cookie": f"sessionid={ig_sessionid}"}
    elif ("youtube.com" in u_low or "youtu.be" in u_low) and os.path.exists(YT_COOKIES_FILE):
        ydl_opts["cookiefile"] = YT_COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info and info["entries"]:
            info = info["entries"][0]
        return {
            "title": info.get("title") or "Media fayl",
            "uploader": info.get("uploader") or info.get("channel") or "Noma'lum",
            "track": info.get("track"),
            "artist": info.get("artist"),
            "duration": info.get("duration") or 0,
            "duration_str": format_duration(info.get("duration")),
            "thumbnail": info.get("thumbnail"),
            "view_count": info.get("view_count") or 0,
            "like_count": info.get("like_count") or 0,
            "webpage_url": info.get("webpage_url") or url,
        }


async def get_media_info(url: str) -> dict:
    ig_sessionid = await get_setting("ig_sessionid", "")
    return await asyncio.to_thread(_sync_get_info, url, ig_sessionid)


def _sync_search_youtube(query: str, max_results: int = 5) -> list:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": True,
        "extractor_args": YT_BYPASS_EXTRACTOR_ARGS,
    }
    if os.path.exists(YT_COOKIES_FILE):
        ydl_opts["cookiefile"] = YT_COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        entries = info.get("entries", [])
        results = []
        for e in entries:
            if not e:
                continue
            vid_url = e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}"
            results.append({
                "title": e.get("title") or "Qo'shiq",
                "url": vid_url,
                "duration": e.get("duration") or 0,
                "duration_str": format_duration(e.get("duration")),
                "uploader": e.get("uploader") or "YouTube"
            })
        return results


async def search_youtube(query: str, max_results: int = 5) -> list:
    return await asyncio.to_thread(_sync_search_youtube, query, max_results)


# =========================================================================
# TO'G'RIDAN-TO'G'RI @USERNAME ORQALI TELEGRAM VA INSTAGRAM STORY YUKLASH
# =========================================================================

async def _async_download_tg_stories_mtproto(username: str, tg_session_str: str) -> list[dict]:
    if not tg_session_str:
        return []
    client = None
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.functions.stories import GetPeerStoriesRequest

        client = TelegramClient(StringSession(tg_session_str.strip()), TG_API_ID, TG_API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            return []

        peer = await client.get_entity(username)
        res = await client(GetPeerStoriesRequest(peer=peer))
        peer_stories = getattr(res, "stories", None)
        story_items = getattr(peer_stories, "stories", []) if peer_stories else []
        if not story_items:
            return []

        unique_id = uuid.uuid4().hex[:8]
        downloaded = []
        for idx, st in enumerate(story_items[:10], start=1):
            media = getattr(st, "media", None)
            if not media:
                continue
            fpath = await client.download_media(
                media,
                file=os.path.join(DOWNLOAD_DIR, f"tgstory_{unique_id}_{idx}")
            )
            if fpath and os.path.exists(fpath):
                ext = os.path.splitext(fpath)[1].lower()
                downloaded.append({
                    "filepath": fpath,
                    "title": f"@{username} — Telegram Story #{idx}",
                    "uploader": f"@{username}",
                    "is_photo": ext in (".jpg", ".jpeg", ".png", ".webp"),
                })
        return downloaded
    except Exception:
        return []
    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


def _probe_single_tg_story_embed(username: str, story_id: int, headers: dict) -> dict | None:
    url = f"https://t.me/{username}/s/{story_id}?embed=1"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        v_m = re.findall(r'<video[^>]+src=["\'](https?://[^"\']+)["\']', raw, re.I)
        if not v_m:
            v_m = re.findall(r'src=["\'](https://cdn\d*\.telesco\.pe/file/[^"\']+\.mp4[^"\']*)["\']', raw, re.I)
        if v_m:
            return {"id": story_id, "url": html.unescape(v_m[0]), "is_photo": False}
        if "tgme_widget_story" in raw or "story" in raw.lower():
            i_m = re.findall(r'background-image:url\(\'(https://cdn\d*\.telesco\.pe/file/[^\']+)\'\)', raw, re.I)
            if i_m:
                return {"id": story_id, "url": html.unescape(i_m[0]), "is_photo": True}
    except Exception:
        pass
    return None


def _sync_download_telegram_story(query_or_url: str) -> list[dict]:
    unique_id = uuid.uuid4().hex[:10]
    q = query_or_url.strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
    }

    if q.startswith("http"):
        m = re.search(r"t(?:elegram)?\.me/([^/?#]+)/s/(\d+)", q, re.I)
        if m:
            username = m.group(1)
            specific_ids = [int(m.group(2))]
        else:
            m2 = re.search(r"t(?:elegram)?\.me/(?:s/)?([^/?#]+)", q, re.I)
            username = m2.group(1) if m2 else q
            specific_ids = []
    else:
        username = q.lstrip("@").split("/")[0].strip()
        specific_ids = []

    ffmpeg_path = get_ffmpeg_path()
    outtmpl = os.path.join(DOWNLOAD_DIR, f"tgstory_{unique_id}_%(id)s.%(ext)s")

    if specific_ids:
        direct_url = f"https://t.me/{username}/s/{specific_ids[0]}"
        try:
            ydl_opts = {
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
            }
            if ffmpeg_path:
                ydl_opts["ffmpeg_location"] = ffmpeg_path
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(direct_url, download=True)
                entries = info.get("entries") if "entries" in info else [info]
                results = []
                for entry in entries:
                    if not entry:
                        continue
                    fname = _locate_downloaded_file(ydl, entry, "video", ffmpeg_path)
                    if os.path.exists(fname):
                        ext = os.path.splitext(fname)[1].lower()
                        results.append({
                            "filepath": fname,
                            "title": f"@{username} — Telegram Story",
                            "uploader": f"@{username}",
                            "is_photo": ext in (".jpg", ".jpeg", ".png", ".webp"),
                        })
                if results:
                    return results
        except Exception:
            pass

    candidate_ids = list(specific_ids)
    if not candidate_ids:
        for page_url in (f"https://t.me/{username}", f"https://t.me/s/{username}"):
            try:
                req = urllib.request.Request(page_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    page_html = resp.read().decode("utf-8", errors="ignore")
                found_ids = re.findall(rf"{re.escape(username)}/s/(\d+)", page_html, re.I)
                for fid in found_ids:
                    if int(fid) not in candidate_ids:
                        candidate_ids.append(int(fid))
            except Exception:
                pass

    probe_range = candidate_ids if candidate_ids else list(range(1, 31))
    found_media = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_probe_single_tg_story_embed, username, sid, headers) for sid in probe_range]
        for fut in futures:
            res = fut.result()
            if res:
                found_media.append(res)

    if found_media:
        downloaded = []
        for idx, item in enumerate(found_media[:10], start=1):
            ext = ".jpg" if item["is_photo"] else ".mp4"
            fpath = os.path.join(DOWNLOAD_DIR, f"tgstory_{unique_id}_{idx}{ext}")
            try:
                m_req = urllib.request.Request(item["url"], headers=headers)
                with urllib.request.urlopen(m_req, timeout=30) as m_resp, open(fpath, "wb") as out_f:
                    shutil.copyfileobj(m_resp, out_f)
                downloaded.append({
                    "filepath": fpath,
                    "title": f"@{username} — Telegram Story #{item['id']}",
                    "uploader": f"@{username}",
                    "is_photo": item["is_photo"],
                })
            except Exception:
                pass
        if downloaded:
            return downloaded

    raise RuntimeError(
        f"@{username} profilida ochiq Telegram Story topilmadi.\n"
        "💡 Barcha shaxsiy profillarning Telegram storylarini faqat @username bilan yuklash uchun "
        "Admin Panel -> «👁 Story va Cookie sozlamalari» bo'limidan Telegram StringSession ulashingiz mumkin!"
    )


def _sync_download_instagram_stories(username_or_url: str, ig_sessionid: str = "") -> list[dict]:
    unique_id = uuid.uuid4().hex[:10]
    raw = username_or_url.strip()

    story_pk = None
    if "instagram.com" in raw.lower():
        m = re.search(r"instagram\.com/stories/([^/?#]+)(?:/(\d+))?", raw, re.I)
        if m:
            username = m.group(1)
            story_pk = m.group(2)
        else:
            m2 = re.search(r"instagram\.com/([^/?#]+)", raw, re.I)
            username = m2.group(1) if m2 else raw
        target_url = raw
    else:
        username = raw.lstrip("@").strip().split("/")[0]
        target_url = f"https://www.instagram.com/stories/{username}/"

    decoded_session = urllib.parse.unquote(ig_sessionid.strip()) if ig_sessionid else ""

    if decoded_session:
        try:
            ig_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.instagram.com/{username}/",
                "Cookie": f"sessionid={decoded_session};",
            }
            prof_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            req = urllib.request.Request(prof_url, headers=ig_headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                prof_data = json.loads(resp.read().decode("utf-8", errors="ignore"))

            user_obj = prof_data.get("data", {}).get("user", {})
            target_user_id = user_obj.get("id")
            if target_user_id:
                reels_url = f"https://www.instagram.com/api/v1/feed/reels_media/?reel_ids={target_user_id}"
                r_req = urllib.request.Request(reels_url, headers=ig_headers)
                with urllib.request.urlopen(r_req, timeout=20) as r_resp:
                    reels_data = json.loads(r_resp.read().decode("utf-8", errors="ignore"))

                reels = reels_data.get("reels", {})
                user_reel = reels.get(str(target_user_id)) or (list(reels.values())[0] if reels else {})
                items = user_reel.get("items", [])

                if story_pk:
                    filtered = [it for it in items if str(it.get("pk")) == str(story_pk) or str(it.get("id", "")).startswith(str(story_pk))]
                    if filtered:
                        items = filtered

                downloaded_stories = []
                for idx, item in enumerate(items[:15], start=1):
                    media_type_code = item.get("media_type")
                    if media_type_code == 2 and item.get("video_versions"):
                        v_url = item["video_versions"][0]["url"]
                        fpath = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_{idx}.mp4")
                        v_req = urllib.request.Request(v_url, headers={"User-Agent": ig_headers["User-Agent"]})
                        with urllib.request.urlopen(v_req, timeout=30) as v_r, open(fpath, "wb") as out_f:
                            shutil.copyfileobj(v_r, out_f)
                        downloaded_stories.append({
                            "filepath": fpath,
                            "title": f"@{username} — Story #{idx}",
                            "uploader": f"@{username}",
                            "is_photo": False,
                        })
                    elif item.get("image_versions2", {}).get("candidates"):
                        i_url = item["image_versions2"]["candidates"][0]["url"]
                        fpath = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_{idx}.jpg")
                        i_req = urllib.request.Request(i_url, headers={"User-Agent": ig_headers["User-Agent"]})
                        with urllib.request.urlopen(i_req, timeout=25) as i_r, open(fpath, "wb") as out_f:
                            shutil.copyfileobj(i_r, out_f)
                        downloaded_stories.append({
                            "filepath": fpath,
                            "title": f"@{username} — Story #{idx}",
                            "uploader": f"@{username}",
                            "is_photo": True,
                        })

                if downloaded_stories:
                    return downloaded_stories
        except Exception:
            pass

    ffmpeg_path = get_ffmpeg_path()
    outtmpl = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "playlistend": 15,
        "nocheckcertificate": True,
    }
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path
    if os.path.exists(IG_COOKIES_FILE):
        ydl_opts["cookiefile"] = IG_COOKIES_FILE
    elif decoded_session:
        ydl_opts["http_headers"] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Cookie": f"sessionid={decoded_session};",
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            entries = info.get("entries") if "entries" in info else [info]
            results = []
            for idx, entry in enumerate(entries, start=1):
                if not entry:
                    continue
                fname = _locate_downloaded_file(ydl, entry, "video", ffmpeg_path)
                if os.path.exists(fname):
                    ext = os.path.splitext(fname)[1].lower()
                    results.append({
                        "filepath": fname,
                        "title": f"@{username} — Story #{idx}",
                        "uploader": f"@{username}",
                        "is_photo": ext in (".jpg", ".jpeg", ".png", ".webp"),
                    })
            if results:
                return results
    except Exception as e:
        err_msg = str(e)
        if not decoded_session and not os.path.exists(IG_COOKIES_FILE):
            raise RuntimeError(
                f"@{username} ning Instagram Story'larini yuklash uchun Admin Panel -> "
                "«👁 Story va Cookie sozlamalari» bo'limidan Instagram sessionid (yoki cookies.txt) kiriting!"
            )
        raise RuntimeError(
            f"@{username} profilida faol story topilmadi yoki akkaunt yopiq.\n"
            f"Texnik ma'lumot: {err_msg[:100]}"
        )

    raise RuntimeError(f"@{username} profilida hozircha faol Story mavjud emas.")


async def download_stories(platform_code: str, query_or_url: str) -> list[dict]:
    if platform_code == "tg":
        clean_u = query_or_url.strip().lstrip("@").split("/")[0]
        tg_sess = await get_setting("tg_user_session_string", "")
        if tg_sess and not query_or_url.strip().startswith("http"):
            mt_res = await _async_download_tg_stories_mtproto(clean_u, tg_sess)
            if mt_res:
                return mt_res
        return await asyncio.to_thread(_sync_download_telegram_story, query_or_url)
    else:
        ig_sessionid = await get_setting("ig_sessionid", "")
        return await asyncio.to_thread(_sync_download_instagram_stories, query_or_url, ig_sessionid)


# =========================================================================
# ASOSIY VIDEO (2 GB GACHA), RASM VA AUDIO YUKLASH TIZIMI + YOUTUBE BYPASS
# =========================================================================

def _fallback_youtube_piped_api(url: str, unique_id: str, media_type: str = "video") -> dict:
    '''
    Agar server IP manzili YouTube tomonidan qattiq bloklangan bo'lsa va cookie bo'lmasa,
    zaxira sifatida Piped / Invidious public API tugunlaridan to'g'ridan-to'g'ri stream oladi.
    '''
    vid_id = extract_yt_video_id(url)
    if not vid_id:
        raise RuntimeError("YouTube video ID topilmadi.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.moomoo.me",
        "https://api.piped.private.coffee",
    ]

    for base_api in piped_instances:
        try:
            req = urllib.request.Request(f"{base_api}/streams/{vid_id}", headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))

            title = data.get("title") or "YouTube Media"
            uploader = data.get("uploader") or "YouTube"
            duration = int(data.get("duration") or 0)

            if media_type == "audio":
                streams = data.get("audioStreams", [])
                if not streams:
                    continue
                chosen = streams[0]
                stream_url = chosen.get("url")
                ext = ".m4a"
            else:
                # 720p yoki 360p combined video+audio stream qidiramiz
                v_streams = [s for s in data.get("videoStreams", []) if not s.get("videoOnly", True)]
                if not v_streams:
                    continue
                chosen = v_streams[0]
                stream_url = chosen.get("url")
                ext = ".mp4"

            if not stream_url:
                continue

            filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_{vid_id}{ext}")
            dl_req = urllib.request.Request(stream_url, headers=headers)
            with urllib.request.urlopen(dl_req, timeout=45) as dl_resp, open(filepath, "wb") as out_f:
                shutil.copyfileobj(dl_resp, out_f)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                return {
                    "filepath": filepath,
                    "title": title,
                    "uploader": uploader,
                    "track": None,
                    "artist": uploader,
                    "duration": duration,
                    "thumbnail": data.get("thumbnailUrl"),
                    "width": None,
                    "height": None,
                    "is_photo": False,
                }
        except Exception:
            continue

    raise RuntimeError("Zaxira serverlardan ham yuklab bo'lmadi.")


def _fallback_direct_scrape(url: str, unique_id: str) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw_html = resp.read().decode("utf-8", errors="ignore")

    title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', raw_html, re.I)
    if not title_match:
        title_match = re.search(r"<title>([^<]+)</title>", raw_html, re.I)
    title = html.unescape(title_match.group(1)).strip() if title_match else "Media"

    video_urls = re.findall(r'https://v1\.pinimg\.com/videos/[^"\'\s\\]+\.mp4', raw_html)
    if not video_urls:
        og_vid = re.search(r'<meta[^>]+property=["\']og:video(?::url|:secure_url)?["\'][^>]+content=["\']([^"\']+\.mp4[^"\']*)["\']', raw_html, re.I)
        if og_vid:
            video_urls = [html.unescape(og_vid.group(1))]

    if video_urls:
        chosen_vid = video_urls[0]
        for vu in video_urls:
            if "720p" in vu or "mp4" in vu:
                chosen_vid = vu
                break
        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_pin.mp4")
        v_req = urllib.request.Request(chosen_vid, headers=headers)
        with urllib.request.urlopen(v_req, timeout=30) as v_resp, open(filepath, "wb") as out_f:
            shutil.copyfileobj(v_resp, out_f)
        return {
            "filepath": filepath,
            "title": title,
            "uploader": "Pinterest",
            "duration": 0,
            "thumbnail": None,
            "width": None,
            "height": None,
            "is_photo": False,
        }

    img_urls = re.findall(r'https://i\.pinimg\.com/originals/[^"\'\s\\]+\.(?:jpg|jpeg|png|webp)', raw_html)
    if not img_urls:
        img_urls = re.findall(r'https://i\.pinimg\.com/736x/[^"\'\s\\]+\.(?:jpg|jpeg|png|webp)', raw_html)
    if not img_urls:
        og_img = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', raw_html, re.I)
        if og_img:
            img_urls = [html.unescape(og_img.group(1))]

    if img_urls:
        chosen_img = img_urls[0]
        ext = os.path.splitext(chosen_img.split("?")[0])[1] or ".jpg"
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_photo{ext}")
        i_req = urllib.request.Request(chosen_img, headers=headers)
        with urllib.request.urlopen(i_req, timeout=25) as i_resp, open(filepath, "wb") as out_f:
            shutil.copyfileobj(i_resp, out_f)
        return {
            "filepath": filepath,
            "title": title,
            "uploader": "Pinterest",
            "duration": 0,
            "thumbnail": chosen_img,
            "width": None,
            "height": None,
            "is_photo": True,
        }

    raise RuntimeError("Ushbu havoladan video yoki rasm topilmadi.")


def _build_ydl_opts(url: str, outtmpl: str, media_type: str, quality: str, ffmpeg_path: str | None, ig_sessionid: str = "") -> dict:
    u_low = url.lower()
    is_yt = ("youtube.com" in u_low) or ("youtu.be" in u_low)
    is_ig = "instagram.com" in u_low

    ydl_opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_FILESIZE,
        "geo_bypass": True,
        "nocheckcertificate": True,
    }

    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = ffmpeg_path

    if is_yt:
        # YouTube anti-bot tekshiruvini ("Sign in to confirm you're not a bot") chetlab o'tish!
        ydl_opts["extractor_args"] = YT_BYPASS_EXTRACTOR_ARGS
        if os.path.exists(YT_COOKIES_FILE):
            ydl_opts["cookiefile"] = YT_COOKIES_FILE
    elif is_ig:
        if os.path.exists(IG_COOKIES_FILE):
            ydl_opts["cookiefile"] = IG_COOKIES_FILE
        elif ig_sessionid:
            decoded_s = urllib.parse.unquote(ig_sessionid.strip())
            ydl_opts["http_headers"] = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Cookie": f"sessionid={decoded_s};",
            }
    else:
        ydl_opts["http_headers"] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        }

    if media_type == "audio":
        ydl_opts["format"] = "ba/b"
        if ffmpeg_path:
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
    else:
        if quality == "480p":
            if ffmpeg_path:
                ydl_opts["format"] = (
                    "bv*[height<=480][ext=mp4]+ba[ext=m4a]/"
                    "b[height<=480][ext=mp4]/bv*[height<=480]+ba/b[height<=480]/b"
                )
                ydl_opts["merge_output_format"] = "mp4"
            else:
                ydl_opts["format"] = "b[height<=480][ext=mp4]/b[height<=480]/b[ext=mp4]/b"
        else:
            if ffmpeg_path:
                ydl_opts["format"] = (
                    "bv*[height<=1080][filesize<48M][ext=mp4]+ba[ext=m4a]/"
                    "bv*[height<=720][filesize_approx<48M][ext=mp4]+ba[ext=m4a]/"
                    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
                    "bv*[height<=720][ext=mp4]+ba[ext=m4a]/"
                    "b[ext=mp4]/bv*+ba/b"
                )
                ydl_opts["merge_output_format"] = "mp4"
            else:
                ydl_opts["format"] = "b[ext=mp4]/b"

    return ydl_opts


def _locate_downloaded_file(ydl, info: dict, media_type: str, ffmpeg_path: str | None) -> str:
    filename = ydl.prepare_filename(info)
    if media_type == "audio" and ffmpeg_path:
        base, _ = os.path.splitext(filename)
        mp3_file = base + ".mp3"
        if os.path.exists(mp3_file):
            return mp3_file

    if os.path.exists(filename):
        return filename

    base, _ = os.path.splitext(filename)
    for ext in [".mp4", ".mp3", ".m4a", ".webm", ".mkv", ".jpg", ".png", ".webp"]:
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate
    return filename


def _extract_result_dict(ydl, info: dict, media_type: str, ffmpeg_path: str | None) -> dict:
    if "entries" in info and info["entries"]:
        info = info["entries"][0]
    filename = _locate_downloaded_file(ydl, info, media_type, ffmpeg_path)
    ext = os.path.splitext(filename)[1].lower()
    is_photo = ext in (".jpg", ".jpeg", ".png", ".webp")
    return {
        "filepath": filename,
        "title": info.get("title") or "Media",
        "uploader": info.get("uploader") or info.get("channel") or "MediaBot",
        "track": info.get("track"),
        "artist": info.get("artist"),
        "duration": int(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail"),
        "width": info.get("width"),
        "height": info.get("height"),
        "is_photo": is_photo,
    }


def _sync_download(url: str, media_type: str = "video", quality: str = "best", ig_sessionid: str = "") -> dict:
    unique_id = uuid.uuid4().hex[:10]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{unique_id}_%(id)s.%(ext)s")
    ffmpeg_path = get_ffmpeg_path()
    is_yt = ("youtube.com" in url.lower()) or ("youtu.be" in url.lower())

    ydl_opts = _build_ydl_opts(url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return _extract_result_dict(ydl, info, media_type, ffmpeg_path)

    except Exception as first_err:
        err_text = str(first_err)

        # 1-ZAXIRA: YouTube "Sign in to confirm you're not a bot" yoki format xatosida
        if is_yt:
            # 1A: TV / Android VR embedded clientlar bilan qayta urinib ko'ramiz
            for client_list in (["tv_embedded", "android_vr"], ["mweb", "ios", "tv"]):
                try:
                    retry_opts = _build_ydl_opts(url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)
                    retry_opts["extractor_args"] = {
                        "youtube": {
                            "player_client": client_list,
                            "player_skip": ["webpage", "configs"],
                        }
                    }
                    retry_opts["format"] = "ba/b" if media_type == "audio" else ("bv*+ba/b" if ffmpeg_path else "b")
                    with yt_dlp.YoutubeDL(retry_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        return _extract_result_dict(ydl, info, media_type, ffmpeg_path)
                except Exception:
                    pass

            # 1B: Kompyuterdagi lokal brauzer cookie'laridan avtomatik foydalanish (Edge, Firefox, Brave, Chrome)
            if not os.path.exists(YT_COOKIES_FILE):
                for browser_name in ("edge", "firefox", "brave", "opera", "chrome"):
                    try:
                        b_opts = _build_ydl_opts(url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)
                        b_opts["cookiesfrombrowser"] = (browser_name,)
                        b_opts["format"] = "ba/b" if media_type == "audio" else ("bv*+ba/b" if ffmpeg_path else "b")
                        with yt_dlp.YoutubeDL(b_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            return _extract_result_dict(ydl, info, media_type, ffmpeg_path)
                    except Exception:
                        continue

            # 1C: Piped Public API orqali to'g'ridan-to'g'ri tortish
            try:
                return _fallback_youtube_piped_api(url, unique_id, media_type)
            except Exception:
                pass

        # 2-ZAXIRA: Format mos kelmagan boshqa saytlar uchun
        if "Requested format is not available" in err_text or "format" in err_text.lower():
            try:
                fallback_opts = _build_ydl_opts(url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)
                fallback_opts["format"] = "bestaudio/best" if media_type == "audio" else ("bestvideo+bestaudio/best" if ffmpeg_path else "best")
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return _extract_result_dict(ydl, info, media_type, ffmpeg_path)
            except Exception:
                pass

        # 3-ZAXIRA: Pinterest rasm pinlari yoki "No video formats found"
        if (
            "No video formats found" in err_text
            or "pinterest." in url.lower()
            or "pin.it" in url.lower()
        ):
            try:
                return _fallback_direct_scrape(url, unique_id)
            except Exception:
                pass

        raise first_err


async def download_media_file(url: str, media_type: str = "video", quality: str = "best") -> dict:
    ig_sessionid = await get_setting("ig_sessionid", "")
    return await asyncio.to_thread(_sync_download, url, media_type, quality, ig_sessionid)
