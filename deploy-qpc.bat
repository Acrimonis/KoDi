@echo off
setlocal

set "SRC=%~dp0nico.video.contextactions"
set "DST=P:\.kodi_d\addons\nico.video.contextactions"

if not exist "%SRC%\addon.xml" (
    echo Source not found: %SRC%
    exit /b 1
)
if not exist "P:\.kodi_d\addons" (
    echo Kodi addons folder not found: P:\.kodi_d\addons
    exit /b 1
)

robocopy "%SRC%" "%DST%" /MIR /NJH /NJS /NP ^
    /XD .git .github __pycache__ ^
    /XF AGENTS.md Tracking.md *.zip *.bat *.code-workspace

rem robocopy exit codes 0-7 are success, 8+ are failures
if errorlevel 8 (
    echo Deploy FAILED
    exit /b 1
)

echo Deployed to %DST%
exit /b 0
