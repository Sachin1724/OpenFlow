@echo off
chcp 65001 >nul
title MIRA LIVE VOICE ORDERING CRM
cls
echo ==============================================================================
echo   MIRA LIVE VOICE ORDERING CRM · 24kHz STUDIO NEURAL VOICE
echo ==============================================================================
echo   Starting FastAPI + WebSockets Merchant Terminal on http://127.0.0.1:8000
echo   Features:
echo   - Odia & English colloquial food ordering and slot extraction
echo   - Non-linear state rollbacks and mid-sentence modifications
echo   - Real-time Kitchen Order Ticket (KOT) updating
echo   - 24,000 Hz studio voice responses
echo ==============================================================================
echo.

cd /d "%~dp0.."
start http://127.0.0.1:8000
python openflow\gateway\live_voice_crm_server.py

pause

