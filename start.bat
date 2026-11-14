@echo off
title Universal Media, Story, Shazam & 2GB Bot Pro v6
echo ============================================================
echo   KUTUBXONALAR (SHAZAMIO, TELETHON, YT-DLP) TEKSHIRILMOQDA...
echo ============================================================
pip install -U aiogram yt-dlp imageio-ffmpeg telethon shazamio
pip install -r requirements.txt
echo.
python -u main.py
pause
