@echo off
chcp 65001 >nul
title MIRA Odia Voice Benchmark Audition Console
cd /d "%~dp0"
python alm\play_voice_benchmark.py
pause
