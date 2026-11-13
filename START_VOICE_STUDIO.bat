@echo off
chcp 65001 >nul
title MIRA VOICE STUDIO: Zero-Shot Voice Cloning and Neural Speech Generation
cd /d "%~dp0.."

echo ================================================================================
echo       🎙️  MIRA VOICE STUDIO: ZERO-SHOT CLONING AND NEURAL SPEECH GENERATOR      
echo ================================================================================
echo   Engine   : 24,000 Hz MultiCondMatcha + Vocos Vocoder on NVIDIA RTX 4050
echo   Web App  : http://127.0.0.1:8000/studio
echo   API Docs : http://127.0.0.1:8000/docs
echo ================================================================================
echo.

echo Launching browser to MIRA Studio...
start http://127.0.0.1:8000/studio

echo Starting local FastAPI backend server...
python -m uvicorn openflow.api.speech_server:app --host 127.0.0.1 --port 8000 --log-level info
pause

