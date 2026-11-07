@echo off
chcp 65001 >nul
title MIRA Next-Gen Voice Benchmark Audition Console
cd /d "%~dp0\.."
python openflow\alm\play_voice_benchmark.py
pause

