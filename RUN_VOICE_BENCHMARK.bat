@echo off
setlocal
cd /d "%~dp0"
title OpenFlow Voice Engine Benchmark (Studio Voice vs Chatterbox)

echo =====================================================================
echo  OpenFlow Odia Voice AI Architecture Benchmark
echo =====================================================================
echo  1. MIRA Studio Voice (Female/Smita) : Matcha-Vocos Odia Narrator (Ultra Low Latency)
echo  2. MIRA Studio Voice (Male/Kishore) : Matcha-Vocos Odia Grounded Presence
echo  3. Chatterbox 0.5B                 : Conversational Dialogue ALM with Guided Emotion
echo =====================================================================
echo.

python -u alm\benchmark_voice_engines.py

echo.
echo =====================================================================
echo  Benchmark complete. Generated WAV files are saved in:
echo  scratch\benchmark_results\
echo =====================================================================
pause
