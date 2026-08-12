@echo off
rem Launches Garage from the repository root, regardless of the caller's
rem current working directory.
cd /d "%~dp0"
python -m tools.garage %*
