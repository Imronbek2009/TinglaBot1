@echo off
title Tingla - Zero-Config Multi-Engine Bot v8
echo ============================================================
echo   YT-DLP VA KUTUBXONALAR ENG SO'NGGI VERSIYAGA YANGILANMOQDA...
echo ============================================================
pip install -U yt-dlp aiogram imageio-ffmpeg telethon shazamio
pip install -r requirements.txt
echo.
python -u main.py
pause
