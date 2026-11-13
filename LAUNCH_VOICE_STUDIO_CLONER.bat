@echo off
title VoiceStudio Odia Voice Cloner & Testing Studio
color 0D
chcp 65001 > nul
cls
echo ===============================================================================
echo        🎙️ VOICE STUDIO: ZERO-SHOT ODIA VOICE CLONING & TESTING
echo ===============================================================================
echo  Reference Audio Cloning : debpalash/VoiceStudio & IndicF5 Style
echo  Preloaded Voices        : Smita Mohanty (Female Odia Media Anchor)
echo  Custom Cloning          : Clone from Microphone (5s) or any WAV/MP3
echo  Expressive Synthesis   : Full English Loanwords + Natural Breathing Pauses
echo ===============================================================================
echo.
cd /d "%~dp0"
python voice_studio_cloner.py
pause

