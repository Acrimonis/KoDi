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

rem ---- Build the addon archive (<id>-<version>.zip) and copy it to QPC ----
set "ZIPDST=P:\.kodi_d\X__WorkinG__X"
set "ADDON_ID=nico.video.contextactions"
set "VERSION="
for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "([xml](Get-Content -Raw '%SRC%\addon.xml')).addon.version"`) do set "VERSION=%%V"
if not defined VERSION (
    echo Could not read version from addon.xml
    exit /b 1
)
if not exist "%ZIPDST%" (
    echo Archive folder not found: %ZIPDST%
    exit /b 1
)

set "ZIP=%~dp0%ADDON_ID%-%VERSION%.zip"
if exist "%ZIP%" del "%ZIP%"
rem System32 tar = bsdtar (a Git/MSYS tar earlier in PATH would misread D: as a host); it writes forward-slash paths, which Kodi requires; top-level folder = addon id
"%SystemRoot%\System32\tar.exe" -a -c -f "%ZIP%" -C "%~dp0." ^
    --exclude=.git --exclude=.github --exclude=__pycache__ ^
    --exclude=AGENTS.md --exclude=Tracking.md ^
    --exclude=*.zip --exclude=*.bat --exclude=*.code-workspace ^
    %ADDON_ID%
if errorlevel 1 (
    echo Archive build FAILED
    exit /b 1
)

copy /y "%ZIP%" "%ZIPDST%\" >nul
if errorlevel 1 (
    echo Archive copy FAILED
    exit /b 1
)

echo Archive %ADDON_ID%-%VERSION%.zip built and copied to %ZIPDST%
exit /b 0
