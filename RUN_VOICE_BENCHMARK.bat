@echo off
setlocal
cd /d "%~dp0\.."
title OpenFlow Voice Engine Benchmark (Studio Voice vs F5-TTS vs Chatterbox)

python -u openflow\alm\benchmark_voice_engines.py
pause

