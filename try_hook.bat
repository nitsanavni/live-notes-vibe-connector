@echo off
rem Step 2: run the hook by hand, without Vibe.
rem It waits for a line in the meeting, prints one line of JSON, and exits.
cd /d "%~dp0"
if not exist ".vibe\agent-link" (
  echo Missing .vibe\agent-link. Copy .vibe\agent-link.example to .vibe\agent-link
  echo and replace its one line with your agent link.
  exit /b 1
)
echo Waiting for a line in the meeting. Say or type something there. Ctrl+C stops.
echo {} | python wait_for_meeting.py
echo.
echo Exit code: %errorlevel%. JSON above = it works. Nothing above = see the message on the line before.
