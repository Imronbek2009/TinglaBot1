import os
import re
import json
import html
import time
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
IG_SHORTCODE_REGEX = re.compile(r"instagram\.com/(?:[^/?#]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)

_mtproto_bot_client = None
_mtproto_lock = asyncio.Lock()

# MUHIM: player_skip BERILMAYDI! Aks holda visitorData olinmaydi va "Sign in to confirm you're not a bot" chiqadi!
YT_BYPASS_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["android_vr", "tv", "ios", "mweb"],
    }
}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


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


def resolve_redirect_url(url: str) -> str:
    '''Instagram /share/... yoki TikTok vm.tiktok.com qisqa linklarini asl manzilga ochadi.'''
    if any(k in url.lower() for k in ("/share/", "vm.tiktok.com", "vt.tiktok.com", "pin.it")):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.geturl() or url
        except Exception:
            return url
    return url


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


def _convert_video_to_mp3_ffmpeg(video_path: str) -> str:
    ffmpeg_exe = get_ffmpeg_path()
    if not ffmpeg_exe or not os.path.exists(video_path):
        return video_path
    base, _ = os.path.splitext(video_path)
    mp3_path = base + ".mp3"
    cmd = [
        ffmpeg_exe, "-y", "-i", video_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", "192k", mp3_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1024:
            try:
                os.remove(video_path)
            except Exception:
                pass
            return mp3_path
    except Exception:
        pass
    return video_path


def _download_binary_url(file_url: str, dest_path: str, referer: str = "") -> bool:
    headers = {"User-Agent": BROWSER_UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(file_url, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp, open(dest_path, "wb") as out_f:
        shutil.copyfileobj(resp, out_f)
    return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024


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
# ENGINE 1: TIKTOK AVTO-YUKLAGICH (TIKWM + TIKLYDOWN — COOKIE TALAB QILMAYDI!)
# =========================================================================

def _download_tiktok_direct(url: str, unique_id: str, media_type: str = "video") -> dict:
    # 1A: TikWM Public API (No-Watermark HD MP4 + Original MP3)
    try:
        api_url = "https://www.tikwm.com/api/"
        post_data = urllib.parse.urlencode({"url": url, "hd": "1"}).encode("utf-8")
        req = urllib.request.Request(api_url, data=post_data, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            res = json.loads(resp.read().decode("utf-8", errors="ignore"))

        if res.get("code") == 0 and res.get("data"):
            d = res["data"]
            title = d.get("title") or "TikTok Video"
            author = d.get("author", {}).get("nickname") or d.get("author", {}).get("unique_id") or "TikTok"
            duration = int(d.get("duration") or 0)
            music_info = d.get("music_info") or {}
            track = music_info.get("title")
            artist = music_info.get("author")

            if media_type == "audio":
                audio_url = d.get("music") or music_info.get("play")
                if audio_url:
                    filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_tiktok.mp3")
                    if _download_binary_url(audio_url, filepath):
                        return {
                            "filepath": filepath,
                            "title": track or title,
                            "uploader": artist or author,
                            "track": track,
                            "artist": artist,
                            "duration": duration,
                            "thumbnail": d.get("cover"),
                            "width": None,
                            "height": None,
                            "is_photo": False,
                        }

            # Agar rasm slayd-shou bo'lsa va video so'ralgan bo'lsa
            images = d.get("images")
            if images and isinstance(images, list) and media_type != "audio":
                img_url = images[0]
                filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_tiktok.jpg")
                if _download_binary_url(img_url, filepath):
                    return {
                        "filepath": filepath,
                        "title": title,
                        "uploader": author,
                        "track": track,
                        "artist": artist,
                        "duration": 0,
                        "thumbnail": img_url,
                        "width": None,
                        "height": None,
                        "is_photo": True,
                    }

            video_url = d.get("hdplay") or d.get("play") or d.get("wmplay")
            if video_url:
                if video_url.startswith("/"):
                    video_url = "https://www.tikwm.com" + video_url
                filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_tiktok.mp4")
                if _download_binary_url(video_url, filepath):
                    if media_type == "audio":
                        filepath = _convert_video_to_mp3_ffmpeg(filepath)
                    return {
                        "filepath": filepath,
                        "title": title,
                        "uploader": author,
                        "track": track,
                        "artist": artist,
                        "duration": duration,
                        "thumbnail": d.get("cover"),
                        "width": None,
                        "height": None,
                        "is_photo": False,
                    }
    except Exception:
        pass

    # 1B: TiklyDown API fallback
    try:
        q_url = f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(q_url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=18) as resp:
            d = json.loads(resp.read().decode("utf-8", errors="ignore"))
        vid_obj = d.get("video") or {}
        mus_obj = d.get("music") or {}
        dl_url = mus_obj.get("play_url") if media_type == "audio" else (vid_obj.get("noWatermark") or vid_obj.get("watermark"))
        if dl_url:
            ext = ".mp3" if media_type == "audio" else ".mp4"
            filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_tt{ext}")
            if _download_binary_url(dl_url, filepath):
                return {
                    "filepath": filepath,
                    "title": d.get("title") or "TikTok Media",
                    "uploader": d.get("author", {}).get("name") or "TikTok",
                    "track": mus_obj.get("title"),
                    "artist": mus_obj.get("author"),
                    "duration": int(vid_obj.get("duration") or 0),
                    "thumbnail": vid_obj.get("cover"),
                    "width": None,
                    "height": None,
                    "is_photo": False,
                }
    except Exception:
        pass

    raise RuntimeError("TikTok direct API fallback")


# =========================================================================
# ENGINE 2: INSTAGRAM AVTO-YUKLAGICH (GRAPHQL + VXINSTAGRAM + EMBED — COOKIESIZ!)
# =========================================================================

def _download_instagram_direct(url: str, unique_id: str, media_type: str = "video") -> dict:
    real_url = resolve_redirect_url(url)
    m = IG_SHORTCODE_REGEX.search(real_url)
    shortcode = m.group(1) if m else None

    if shortcode:
        # 2A: Instagram Anonymous GraphQL API (Hech qanday login va cookiesiz HD video + musiqa nomini oladi!)
        for doc_id in ("8845758582119845", "10015901848480474"):
            try:
                vars_json = json.dumps({"shortcode": shortcode, "fetch_tagged_user_count": None, "hoisted_comment_id": None, "hoisted_reply_id": None})
                gql_url = f"https://www.instagram.com/graphql/query?doc_id={doc_id}&variables={urllib.parse.quote(vars_json)}"
                gql_headers = {
                    "User-Agent": BROWSER_UA,
                    "X-IG-App-ID": "936619743392459",
                    "X-ASBD-ID": "129477",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"https://www.instagram.com/p/{shortcode}/",
                }
                req = urllib.request.Request(gql_url, headers=gql_headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    gql_data = json.loads(resp.read().decode("utf-8", errors="ignore"))

                media = (
                    gql_data.get("data", {}).get("xdt_shortcode_media")
                    or gql_data.get("data", {}).get("shortcode_media")
                )
                if media:
                    owner = media.get("owner", {}).get("username") or "Instagram"
                    edges = media.get("edge_media_to_caption", {}).get("edges", [])
                    caption_txt = edges[0]["node"]["text"] if edges else f"Instagram @{owner}"
                    music_attr = media.get("clips_music_attribution_info") or {}
                    track = music_attr.get("song_name")
                    artist = music_attr.get("artist_name")

                    video_url = media.get("video_url")
                    # Agar karusel (sidecar) bo'lsa, birinchi elementni tekshiramiz
                    if not video_url and media.get("edge_sidecar_to_children", {}).get("edges"):
                        first_node = media["edge_sidecar_to_children"]["edges"][0].get("node", {})
                        video_url = first_node.get("video_url")

                    if video_url:
                        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_ig.mp4")
                        if _download_binary_url(video_url, filepath, referer="https://www.instagram.com/"):
                            if media_type == "audio":
                                filepath = _convert_video_to_mp3_ffmpeg(filepath)
                            return {
                                "filepath": filepath,
                                "title": caption_txt[:100] or "Instagram Video",
                                "uploader": f"@{owner}",
                                "track": track,
                                "artist": artist,
                                "duration": int(media.get("video_duration") or 0),
                                "thumbnail": media.get("display_url"),
                                "width": media.get("dimensions", {}).get("width"),
                                "height": media.get("dimensions", {}).get("height"),
                                "is_photo": False,
                            }

                    display_url = media.get("display_url")
                    if display_url and media_type != "audio":
                        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_ig.jpg")
                        if _download_binary_url(display_url, filepath, referer="https://www.instagram.com/"):
                            return {
                                "filepath": filepath,
                                "title": caption_txt[:100] or "Instagram Photo",
                                "uploader": f"@{owner}",
                                "track": track,
                                "artist": artist,
                                "duration": 0,
                                "thumbnail": display_url,
                                "width": None,
                                "height": None,
                                "is_photo": True,
                            }
            except Exception:
                pass

        # 2B: VxInstagram JSON API & DDInstagram / KKInstagram Meta Proxies (Telegram preview provayderlari)
        try:
            vx_url = f"https://api.vxinstagram.com/p/{shortcode}"
            req = urllib.request.Request(vx_url, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                vx_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            media_list = vx_data.get("media_extended") or []
            if media_list:
                m_item = media_list[0]
                m_url = m_item.get("url")
                m_type = m_item.get("type", "video")
                if m_url:
                    is_img = m_type in ("image", "photo")
                    ext = ".jpg" if is_img else ".mp4"
                    filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_vxig{ext}")
                    if _download_binary_url(m_url, filepath):
                        if media_type == "audio" and not is_img:
                            filepath = _convert_video_to_mp3_ffmpeg(filepath)
                        return {
                            "filepath": filepath,
                            "title": (vx_data.get("text") or "Instagram Media")[:100],
                            "uploader": f"@{vx_data.get('user_name', 'Instagram')}",
                            "track": None,
                            "artist": None,
                            "duration": int(m_item.get("duration_millis", 0) // 1000),
                            "thumbnail": m_item.get("thumbnail_url"),
                            "width": None,
                            "height": None,
                            "is_photo": is_img and media_type != "audio",
                        }
        except Exception:
            pass

        for proxy_domain in ("www.ddinstagram.com", "www.kkinstagram.com", "www.vxinstagram.com"):
            try:
                p_url = f"https://{proxy_domain}/p/{shortcode}"
                req = urllib.request.Request(p_url, headers={"User-Agent": "TelegramBot (like TwitterBot)"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw_html = resp.read().decode("utf-8", errors="ignore")

                vid_m = re.search(r'<meta[^>]+property=["\']og:video(?::secure_url|:url)?["\'][^>]+content=["\']([^"\']+)["\']', raw_html, re.I)
                title_m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', raw_html, re.I)
                title = html.unescape(title_m.group(1))[:100] if title_m else "Instagram Media"

                if vid_m:
                    v_url = html.unescape(vid_m.group(1))
                    if v_url.startswith("/"):
                        v_url = f"https://{proxy_domain}{v_url}"
                    filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_ddig.mp4")
                    if _download_binary_url(v_url, filepath):
                        if media_type == "audio":
                            filepath = _convert_video_to_mp3_ffmpeg(filepath)
                        return {
                            "filepath": filepath,
                            "title": title,
                            "uploader": "Instagram",
                            "track": None,
                            "artist": None,
                            "duration": 0,
                            "thumbnail": None,
                            "width": None,
                            "height": None,
                            "is_photo": False,
                        }
            except Exception:
                pass

        # 2C: Instagram Public /embed/captioned/ sahifasi (Login talab qilmaydi!)
        try:
            emb_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
            req = urllib.request.Request(emb_url, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                emb_html = resp.read().decode("utf-8", errors="ignore")

            v_matches = re.findall(r'\\?"video_url\\?"\s*:\s*\\?"(https:[^"\\]+(?:\\.[^"\\]+)*)\\?"', emb_html)
            if v_matches:
                clean_v_url = v_matches[0].encode("utf-8").decode("unicode_escape").replace(r"\/", "/")
                filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_embig.mp4")
                if _download_binary_url(clean_v_url, filepath, referer="https://www.instagram.com/"):
                    if media_type == "audio":
                        filepath = _convert_video_to_mp3_ffmpeg(filepath)
                    return {
                        "filepath": filepath,
                        "title": "Instagram Video",
                        "uploader": "Instagram",
                        "track": None,
                        "artist": None,
                        "duration": 0,
                        "thumbnail": None,
                        "width": None,
                        "height": None,
                        "is_photo": False,
                    }
        except Exception:
            pass

    raise RuntimeError("Instagram direct API fallback")


# =========================================================================
# ENGINE 3: YOUTUBE CLOUD API (OCEANSAVER / LOADER.TO + PIPED — COOKIESIZ!)
# =========================================================================

def _fallback_youtube_cloud_api(url: str, unique_id: str, media_type: str = "video", quality: str = "best") -> dict:
    '''
    YouTube IP bloklaganda yoki cookie bo'lmaganda tashqi Cloud API (Oceansaver / Loader.to
    va Piped/Invidious) orqali videoni yoki MP3 ni hech qanday cookiesiz tortib beradi!
    '''
    vid_id = extract_yt_video_id(url)
    clean_yt_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url

    # 3A: Oceansaver / Loader.to Cloud Downloader API
    try:
        fmt = "mp3" if media_type == "audio" else ("480" if quality == "480p" else "720")
        init_url = (
            f"https://ab.cococococ.com/ajax/download.php?copyright=0&format={fmt}"
            f"&url={urllib.parse.quote(clean_yt_url)}&api=dfcb6d76f2f6a9894gjkege8a4ab232222"
        )
        req = urllib.request.Request(init_url, headers={"User-Agent": BROWSER_UA, "Referer": "https://loader.to/"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            init_data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        task_id = init_data.get("id")
        title = init_data.get("title") or (init_data.get("info", {}) or {}).get("title") or "YouTube Media"
        if task_id:
            prog_url = f"https://p.savenow.to/ajax/progress.php?id={task_id}"
            for _ in range(25):
                time.sleep(1.2)
                p_req = urllib.request.Request(prog_url, headers={"User-Agent": BROWSER_UA})
                with urllib.request.urlopen(p_req, timeout=10) as p_resp:
                    p_data = json.loads(p_resp.read().decode("utf-8", errors="ignore"))
                if p_data.get("success") == 1 and p_data.get("download_url"):
                    dl_url = p_data["download_url"]
                    ext = ".mp3" if media_type == "audio" else ".mp4"
                    filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_ytcloud{ext}")
                    if _download_binary_url(dl_url, filepath):
                        return {
                            "filepath": filepath,
                            "title": title,
                            "uploader": "YouTube",
                            "track": None,
                            "artist": None,
                            "duration": 0,
                            "thumbnail": (init_data.get("info", {}) or {}).get("image"),
                            "width": None,
                            "height": None,
                            "is_photo": False,
                        }
                if p_data.get("text", "").lower() in ("error", "failed"):
                    break
    except Exception:
        pass

    # 3B: Piped / Invidious Public API instances
    if vid_id:
        headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
        piped_instances = [
            "https://pipedapi.kavin.rocks",
            "https://pipedapi.tokhmi.xyz",
            "https://pipedapi.moomoo.me",
            "https://api.piped.private.coffee",
            "https://pipedapi.smnz.de",
            "https://pipedapi.adminforge.de",
            "https://pipedapi.drgns.space",
        ]
        for base_api in piped_instances:
            try:
                req = urllib.request.Request(f"{base_api}/streams/{vid_id}", headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))

                title = data.get("title") or "YouTube Media"
                uploader = data.get("uploader") or "YouTube"
                duration = int(data.get("duration") or 0)

                if media_type == "audio":
                    streams = data.get("audioStreams", [])
                    if not streams:
                        continue
                    stream_url = streams[0].get("url")
                    ext = ".m4a"
                else:
                    v_streams = [s for s in data.get("videoStreams", []) if not s.get("videoOnly", True)]
                    if not v_streams:
                        continue
                    stream_url = v_streams[0].get("url")
                    ext = ".mp4"

                if not stream_url:
                    continue

                filepath = os.path.join(DOWNLOAD_DIR, f"{unique_id}_{vid_id}{ext}")
                if _download_binary_url(stream_url, filepath):
                    if media_type == "audio":
                        filepath = _convert_video_to_mp3_ffmpeg(filepath)
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

    raise RuntimeError("YouTube Cloud API fallback failed")


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


async def recognize_song_shazam(
    media_path: str | None = None,
    source_url: str | None = None,
    hint_track: str | None = None,
    hint_artist: str | None = None
) -> dict | None:
    temp_downloaded = None
    sample_path = None
    metadata_guess = None

    try:
        # 1. Agar lokal fayl berilmagan bo'lsa, multi-engine yuklagich yordamida audioni tortib olamiz
        if (not media_path or not os.path.exists(media_path)) and source_url:
            try:
                dl_res = await download_media_file(source_url, media_type="audio", quality="best")
                temp_downloaded = dl_res.get("filepath")
                media_path = temp_downloaded
                metadata_guess = {
                    "track": dl_res.get("track") or hint_track,
                    "artist": dl_res.get("artist") or hint_artist or dl_res.get("uploader"),
                    "title": dl_res.get("title"),
                }
            except Exception:
                pass

        # 2. SHAZAMIO orqali audio faylni haqiqiy Shazam serverida tinglab aniqlash
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

        # 3. Agar Shazam topolmasa, TikTok/Instagram/YouTube metadatasidagi original musiqa nomidan foydalanamiz
        if hint_track:
            full_q = f"{hint_artist} - {hint_track}".strip(" -") if hint_artist else hint_track
            return {
                "artist": hint_artist or "Original Artist",
                "title": hint_track,
                "full_name": full_q,
                "cover": None,
                "source": "Original Audio Metadata 🎶"
            }

        if metadata_guess:
            track = metadata_guess.get("track")
            artist = metadata_guess.get("artist") or ""
            raw_title = metadata_guess.get("title", "")
            if track and track.lower() not in ("original sound", "оригинальный звук", "original audio"):
                full_q = f"{artist} - {track}".strip(" -") if artist else track
                return {
                    "artist": artist or "Original",
                    "title": track,
                    "full_name": full_q,
                    "cover": None,
                    "source": "Media Audio 🎶"
                }
            clean_t = re.sub(r"#\S+", "", raw_title).strip()
            clean_t = re.sub(r"(?i)(official\s*video|shorts|reels|tiktok|video|status|instagram)", "", clean_t).strip(" -|:")
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
# (AVTOMATIK ZERO-CONFIG ARXITEKTURASI!)
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        # Faqat haqiqiy story media mavjud bo'lsa olamiz
        if "tgme_widget_story" not in raw and "telesco.pe" not in raw:
            return None
        v_m = re.findall(r'<video[^>]+src=["\'](https?://[^"\']+)["\']', raw, re.I)
        if not v_m:
            v_m = re.findall(r'src=["\'](https://cdn\d*\.telesco\.pe/file/[^"\']+\.mp4[^"\']*)["\']', raw, re.I)
        if v_m:
            return {"id": story_id, "url": html.unescape(v_m[0]), "is_photo": False}
        i_m = re.findall(r'tgme_widget_story_photo[^>]+background-image:url\(\'(https://cdn\d*\.telesco\.pe/file/[^\']+)\'\)', raw, re.I)
        if not i_m and "tgme_widget_story" in raw:
            i_m = re.findall(r'background-image:url\(\'(https://cdn\d*\.telesco\.pe/file/[^\']+)\'\)', raw, re.I)
        if i_m:
            return {"id": story_id, "url": html.unescape(i_m[0]), "is_photo": True}
    except Exception:
        pass
    return None


def _sync_download_telegram_story(query_or_url: str) -> list[dict]:
    unique_id = uuid.uuid4().hex[:10]
    q = query_or_url.strip()
    headers = {"User-Agent": BROWSER_UA}

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

    # 1. Agar aniq story ID bor bo'lsa (link yoki forward orqali)
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
                            "title": f"@{username} — Telegram Story #{specific_ids[0]}",
                            "uploader": f"@{username}",
                            "is_photo": ext in (".jpg", ".jpeg", ".png", ".webp"),
                        })
                if results:
                    return results
        except Exception:
            pass

    # 2. @username orqali profil sahifasi va kengaytirilgan parallel skaner (1..100)
    candidate_ids = list(specific_ids)
    if not candidate_ids:
        for page_url in (f"https://t.me/{username}", f"https://t.me/s/{username}"):
            try:
                req = urllib.request.Request(page_url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    page_html = resp.read().decode("utf-8", errors="ignore")
                found_ids = re.findall(rf"{re.escape(username)}/s/(\d+)", page_html, re.I)
                for fid in found_ids:
                    if int(fid) not in candidate_ids:
                        candidate_ids.append(int(fid))
            except Exception:
                pass

    probe_range = candidate_ids if candidate_ids else list(range(1, 95))
    found_media = []
    with ThreadPoolExecutor(max_workers=25) as ex:
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
                if _download_binary_url(item["url"], fpath):
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
        f"@{username} profilida veb-ochiq Telegram Story topilmadi.\n"
        "💡 MASLAHAT: Telegramda o'sha storyni ochib, «Ulashish (Share)» tugmasi orqali to'g'ridan-to'g'ri shu botga yuboring (Forward qiling) yoki story linkini tashlang — bot darhol yuklab beradi!"
    )


def _sync_download_instagram_stories(username_or_url: str, ig_sessionid: str = "") -> list[dict]:
    '''
    Instagram Story'larni HECH QANDAY SOZLAMASIZ (Zero-Config) 5 ta tashqi Anonim Story Viewer
    API + VxInstagram + Lokal brauzer + Instagram API orqali yuklab oladi!
    '''
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

    # 1-USUL: VxInstagram / DDInstagram Story API (Cookiesiz ishlaydi!)
    for api_base in (
        f"https://api.vxinstagram.com/stories/{username}",
        f"https://api.vxinstagram.com/stories/{username}/{story_pk}" if story_pk else "",
    ):
        if not api_base:
            continue
        try:
            req = urllib.request.Request(api_base, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                vx_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            media_list = vx_data.get("media_extended") or []
            downloaded = []
            for idx, m_item in enumerate(media_list[:12], start=1):
                m_url = m_item.get("url")
                if not m_url:
                    continue
                is_img = m_item.get("type") in ("image", "photo")
                ext = ".jpg" if is_img else ".mp4"
                fpath = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_{idx}{ext}")
                if _download_binary_url(m_url, fpath):
                    downloaded.append({
                        "filepath": fpath,
                        "title": f"@{username} — Instagram Story #{idx}",
                        "uploader": f"@{username}",
                        "is_photo": is_img,
                    })
            if downloaded:
                return downloaded
        except Exception:
            pass

    # 2-USUL: Anonim Story Viewer API'lar (StoriesIG / AnonyIG / MollyGram — Cookiesiz!)
    anon_apis = [
        f"https://storiesig.info/api/ig/story?url=https://www.instagram.com/stories/{username}/",
        f"https://anonyig.com/api/ig/story?url=https://www.instagram.com/stories/{username}/",
        f"https://iganony.io/api/ig/story?url=https://www.instagram.com/stories/{username}/",
    ]
    for anon_url in anon_apis:
        try:
            req = urllib.request.Request(
                anon_url,
                headers={"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                a_data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            result_items = a_data.get("result") or a_data.get("data") or []
            if isinstance(result_items, list) and result_items:
                downloaded = []
                for idx, item in enumerate(result_items[:12], start=1):
                    v_vers = item.get("video_versions") or []
                    i_vers = (item.get("image_versions2") or {}).get("candidates") or []
                    if v_vers and isinstance(v_vers, list):
                        dl_u = v_vers[0].get("url")
                        is_img = False
                    elif item.get("url"):
                        dl_u = item.get("url")
                        is_img = ".jpg" in dl_u.lower() or ".webp" in dl_u.lower()
                    elif i_vers and isinstance(i_vers, list):
                        dl_u = i_vers[0].get("url")
                        is_img = True
                    else:
                        continue

                    ext = ".jpg" if is_img else ".mp4"
                    fpath = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_{idx}{ext}")
                    if _download_binary_url(dl_u, fpath):
                        downloaded.append({
                            "filepath": fpath,
                            "title": f"@{username} — Instagram Story #{idx}",
                            "uploader": f"@{username}",
                            "is_photo": is_img,
                        })
                if downloaded:
                    return downloaded
        except Exception:
            pass

    # 3-USUL: Instagram Private Web API (agar sessionid berilgan bo'lsa — yopiq profillarni ham ochadi)
    if decoded_session:
        try:
            ig_headers = {
                "User-Agent": BROWSER_UA,
                "X-IG-App-ID": "936619743392459",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.instagram.com/{username}/",
                "Cookie": f"sessionid={decoded_session};",
            }
            prof_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            req = urllib.request.Request(prof_url, headers=ig_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                prof_data = json.loads(resp.read().decode("utf-8", errors="ignore"))

            user_obj = prof_data.get("data", {}).get("user", {})
            target_user_id = user_obj.get("id")
            if target_user_id:
                reels_url = f"https://www.instagram.com/api/v1/feed/reels_media/?reel_ids={target_user_id}"
                r_req = urllib.request.Request(reels_url, headers=ig_headers)
                with urllib.request.urlopen(r_req, timeout=15) as r_resp:
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
                        if _download_binary_url(v_url, fpath):
                            downloaded_stories.append({
                                "filepath": fpath,
                                "title": f"@{username} — Story #{idx}",
                                "uploader": f"@{username}",
                                "is_photo": False,
                            })
                    elif item.get("image_versions2", {}).get("candidates"):
                        i_url = item["image_versions2"]["candidates"][0]["url"]
                        fpath = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_{idx}.jpg")
                        if _download_binary_url(i_url, fpath):
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

    # 4-USUL: yt-dlp + lokal brauzer cookie'lari (Firefox / Edge / Brave / Chrome)
    ffmpeg_path = get_ffmpeg_path()
    outtmpl = os.path.join(DOWNLOAD_DIR, f"igstory_{unique_id}_%(id)s.%(ext)s")
    cookie_sources = []
    if os.path.exists(IG_COOKIES_FILE):
        cookie_sources.append({"cookiefile": IG_COOKIES_FILE})
    if decoded_session:
        cookie_sources.append({"http_headers": {"Cookie": f"sessionid={decoded_session};"}})
    for b_name in ("firefox", "edge", "brave", "opera", "chrome"):
        cookie_sources.append({"cookiesfrombrowser": (b_name,)})

    for c_opt in cookie_sources:
        try:
            ydl_opts = {
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "playlistend": 12,
                "nocheckcertificate": True,
                **c_opt
            }
            if ffmpeg_path:
                ydl_opts["ffmpeg_location"] = ffmpeg_path
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
        except Exception:
            continue

    raise RuntimeError(
        f"@{username} profilida hozirda faol (24 soatlik) Story mavjud emas yoki profil yopiq (Private)."
    )


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
# ASOSIY MULTI-ENGINE VIDEO, RASM VA AUDIO YUKLASH TIZIMI
# =========================================================================

def _fallback_direct_scrape(url: str, unique_id: str) -> dict:
    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
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
        if _download_binary_url(chosen_vid, filepath):
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
        if _download_binary_url(chosen_img, filepath):
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

    # MUHIM: Global http_headers["User-Agent"] BERILMAYDI! yt-dlp o'zining mobil client User-Agent'larini ishlatishi shart!
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
        ydl_opts["extractor_args"] = YT_BYPASS_EXTRACTOR_ARGS
        if os.path.exists(YT_COOKIES_FILE):
            ydl_opts["cookiefile"] = YT_COOKIES_FILE
    elif is_ig:
        if os.path.exists(IG_COOKIES_FILE):
            ydl_opts["cookiefile"] = IG_COOKIES_FILE
        elif ig_sessionid:
            decoded_s = urllib.parse.unquote(ig_sessionid.strip())
            ydl_opts["http_headers"] = {"Cookie": f"sessionid={decoded_s};"}

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
    real_url = resolve_redirect_url(url)
    u_low = real_url.lower()
    ffmpeg_path = get_ffmpeg_path()

    is_tiktok = "tiktok.com" in u_low
    is_ig = "instagram.com" in u_low
    is_yt = ("youtube.com" in u_low) or ("youtu.be" in u_low)

    # 1. TIKTOK UCHUN BIRINCHI NAVBATDA TIKWM DIRECT ENGINE ISHLAYDI (100% AVTOMATIK VA COOKIESIZ!)
    if is_tiktok:
        try:
            return _download_tiktok_direct(real_url, unique_id, media_type)
        except Exception:
            pass

    # 2. INSTAGRAM UCHUN BIRINCHI NAVBATDA DIRECT GRAPHQL/VX ENGINE ISHLAYDI (100% AVTOMATIK VA COOKIESIZ!)
    if is_ig:
        try:
            return _download_instagram_direct(real_url, unique_id, media_type)
        except Exception:
            pass

    # 3. YT-DLP MULTI-CLIENT ENGINE
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{unique_id}_%(id)s.%(ext)s")
    ydl_opts = _build_ydl_opts(real_url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(real_url, download=True)
            return _extract_result_dict(ydl, info, media_type, ffmpeg_path)

    except Exception as first_err:
        err_text = str(first_err)

        # 4. YOUTUBE MAXSUS ZAXIRA ZANJIRI (CLOUD API + TV/VR CLIENT + BROWSER COOKIE)
        if is_yt:
            # 4A: Cloud YouTube API (Oceansaver / Loader.to / Piped — Cookie so'ramaydi!)
            try:
                return _fallback_youtube_cloud_api(real_url, unique_id, media_type, quality)
            except Exception:
                pass

            # 4B: Alohida android_vr va tv clientlari (player_skip'siz!)
            for client_list in (["android_vr"], ["tv"], ["ios", "mweb"]):
                try:
                    retry_opts = _build_ydl_opts(real_url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)
                    retry_opts["extractor_args"] = {"youtube": {"player_client": client_list}}
                    retry_opts["format"] = "ba/b" if media_type == "audio" else ("bv*+ba/b" if ffmpeg_path else "b")
                    with yt_dlp.YoutubeDL(retry_opts) as ydl:
                        info = ydl.extract_info(real_url, download=True)
                        return _extract_result_dict(ydl, info, media_type, ffmpeg_path)
                except Exception:
                    pass

            # 4C: Lokal brauzerlar cookie'si
            for browser_name in ("firefox", "edge", "brave", "opera", "chrome"):
                try:
                    b_opts = _build_ydl_opts(real_url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)
                    b_opts["cookiesfrombrowser"] = (browser_name,)
                    b_opts["format"] = "ba/b" if media_type == "audio" else ("bv*+ba/b" if ffmpeg_path else "b")
                    with yt_dlp.YoutubeDL(b_opts) as ydl:
                        info = ydl.extract_info(real_url, download=True)
                        return _extract_result_dict(ydl, info, media_type, ffmpeg_path)
                except Exception:
                    continue

        # 5. Boshqa saytlar uchun universal format zaxirasi
        if "Requested format is not available" in err_text or "format" in err_text.lower():
            try:
                fallback_opts = _build_ydl_opts(real_url, outtmpl, media_type, quality, ffmpeg_path, ig_sessionid)
                fallback_opts["format"] = "bestaudio/best" if media_type == "audio" else ("bestvideo+bestaudio/best" if ffmpeg_path else "best")
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    info = ydl.extract_info(real_url, download=True)
                    return _extract_result_dict(ydl, info, media_type, ffmpeg_path)
            except Exception:
                pass

        # 6. Pinterest va rasm postlar uchun Direct Scrape
        if (
            "No video formats found" in err_text
            or "pinterest." in u_low
            or "pin.it" in u_low
        ):
            try:
                return _fallback_direct_scrape(real_url, unique_id)
            except Exception:
                pass

        raise first_err


async def download_media_file(url: str, media_type: str = "video", quality: str = "best") -> dict:
    ig_sessionid = await get_setting("ig_sessionid", "")
    return await asyncio.to_thread(_sync_download, url, media_type, quality, ig_sessionid)
