@echo off
title MIRA Live Voice-to-Voice Conversation (Odia AI)
color 0B
chcp 65001 > nul
cls
echo ===============================================================================
echo              🎙️ MIRA: Real-Time Odia Voice-to-Voice Assistant
echo ===============================================================================
echo  Hardware Acceleration : NVIDIA GeForce RTX 4050 Laptop GPU
echo  Speech Recognition   : IndicConformer CTC ASR (16kHz)
echo  Conversational SLM   : SmolLM2-135M + LoRA (Trained on authentic Odia dialogues)
echo  Voice Synthesis      : Meta MMS Odia Neural TTS (16kHz)
echo  Adaptive Learning    : On-Device Dialect & Tempo Reinforcement Learning
echo ===============================================================================
echo.
echo Starting MIRA Voice Engine...
cd /d "%~dp0"
python live_voice_conversation.py
pause
