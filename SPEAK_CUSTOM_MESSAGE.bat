@echo off
title Odia Custom Message Voice Speaker
color 0A
chcp 65001 > nul
cls
echo ===============================================================================
echo             🔊 ODIA CUSTOM MESSAGE VOICE SPEAKER (MIRA VOICE)
echo ===============================================================================
echo  Type ANY message in Odia or mixed Odia/English loanwords.
echo  Automatic phonetic transliteration, breathing pauses, and instant speech!
echo ===============================================================================
echo.
cd /d "%~dp0"
python speak_custom_message.py
pause

