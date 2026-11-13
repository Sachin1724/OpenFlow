@echo off
title MIRA STUDIO: Voice Enrollment and Cloned Speech Console
cd /d "%~dp0"
chcp 65001 >nul
python enroll_voice.py
pause

