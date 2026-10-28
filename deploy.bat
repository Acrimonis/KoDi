@echo off
setlocal

set "SRC=%~dp0nico.video.contextactions"
set "DST=D:\.kodi\portable_data\addons\nico.video.contextactions"

if not exist "%SRC%\addon.xml" (
    echo Source not found: %SRC%
    exit /b 1
)
if not exist "D:\.kodi\portable_data\addons" (
    echo Kodi addons folder not found: D:\.kodi\portable_data\addons
    exit /b 1
)

robocopy "%SRC%" "%DST%" /MIR /NJH /NJS /NP ^
    /XD .git .github __pycache__ ^
    /XF AGENTS.md Tracking.md *.zip *.bat

rem robocopy exit codes 0-7 are success, 8+ are failures
if errorlevel 8 (
    echo Deploy FAILED
    exit /b 1
)

echo Deployed to %DST%
exit /b 0
