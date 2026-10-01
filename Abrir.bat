@echo off
cd /d "%~dp0"
uv run --python 3.14 --with customtkinter --with pymysql python main.py
if errorlevel 1 pause
