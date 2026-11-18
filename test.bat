@echo off
rem Runs the tests. Exit code 0 means all passed.
cd /d "%~dp0"
python -m unittest -v
exit /b %errorlevel%
