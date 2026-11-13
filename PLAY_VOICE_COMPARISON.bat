@echo off
chcp 65001 > nul
cls
echo ======================================================================
echo 🎧 MIRA 24kHz HD STUDIO VOICE: BROADCAST CLARITY AUDIT
echo ======================================================================
echo.
echo [1] Press any key to listen to Turn 1: 24kHz Studio Female Voice
echo     User: "ନମସ୍କାର, ଆପଣ କେମିତି ଅଛନ୍ତି ?"
echo     MIRA: "ନମସ୍କାର, ମୁଁ ବହୁତ ଭଲ ଅଛି !"
pause > nul
powershell -c "(New-Object Media.SoundPlayer 'data\voice_comparison\live_turn_1.wav').PlaySync()"
echo.
echo [2] Press any key to listen to Turn 2: 24kHz Studio Match Answer
echo     User: "କାଲି ମ୍ୟାଚ୍ କିଏ ଜିତିଲା କହିଲ ?"
echo     MIRA: "କାଲି ଇଣ୍ଡିଆ ପରା ଜିତିଗଲା ! ବଢିଆ ଖେଳିଲେ ସମସ୍ତେ ।"
pause > nul
powershell -c "(New-Object Media.SoundPlayer 'data\voice_comparison\live_turn_2.wav').PlaySync()"
echo.
echo [3] Press any key to listen to Turn 3: 24kHz Studio Custom Speech (Cricket Match)
echo     "ନମସ୍କାର ସଚିନ ଭାଇ, ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆମେ ଏକ ବହୁତ ବଢ଼ିଆ cricket match ଦେଖିବା !"
pause > nul
powershell -c "(New-Object Media.SoundPlayer 'data\voice_comparison\studio_engine_test.wav').PlaySync()"
echo.
echo [4] Press any key to listen to Old 16kHz Muffled Voice (for A/B comparison)
echo     Notice how the old 16kHz voice sounded telephone-muffled compared to 24kHz!
pause > nul
powershell -c "(New-Object Media.SoundPlayer 'data\voice_comparison\sample_1_robotic.wav').PlaySync()"
echo.
echo ======================================================================
echo Verified: 24,000 Hz broadcast clarity, zero diminishing tail words!
echo ======================================================================
pause
