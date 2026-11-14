@echo off
title Tingla - Universal Media, Story, Shazam & 2GB Bot Pro v7
echo ============================================================
echo   YT-DLP VA KUTUBXONALAR ENG SO'NGGI VERSIYAGA YANGILANMOQDA...
echo ============================================================
pip install -U yt-dlp aiogram imageio-ffmpeg telethon shazamio
pip install -r requirements.txt
echo.
python -u main.py
pause
