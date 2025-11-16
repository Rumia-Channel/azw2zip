@echo off

cd /d %~dp0

echo Syncing dependencies...
uv sync

echo Cleaning build directory...
if exist build rmdir /s /q build
mkdir build

echo Copying source files...
xcopy "DeDRM_Plugin\*" "build\DeDRM_Plugin\" /s /e /i /y
xcopy "KindleUnpack\lib\*" "build\KindleUnpack\lib\" /s /e /i /y
xcopy "kfxlib\*" "build\kfxlib\" /s /e /i /y
xcopy "DeDRM_tools\*" "build\DeDRM_tools\" /s /e /i /y

copy /Y "*.py" "build\"

echo Building standalone executable with Nuitka...
cd build
uv run python -m nuitka ^
    --standalone ^
    --output-filename="azw2zip.exe" ^
    --include-package=kfxlib ^
    --include-package=pypdf ^
    --include-package=lxml ^
    --include-package=PIL ^
    --include-package=Crypto ^
    --enable-plugin=pylint-warnings ^
    --assume-yes-for-downloads ^
    --windows-console-mode=attach ^
    --follow-imports ^
    --nofollow-import-to=tkinter ^
    azw2zip.py

cd ..

if errorlevel 1 (
    echo.
    echo Build failed! Check errors above.
    pause
    exit /b 1
)

echo.
echo Build complete!
echo Output: build\azw2zip.dist\azw2zip.exe
echo.
echo Verifying DeDRM_tools...
if exist "build\azw2zip.dist\DeDRM_tools\KFXKeyExtractor28.exe" (
    echo   [OK] KFXKeyExtractor28.exe found
) else (
    echo   [WARN] KFXKeyExtractor28.exe missing!
)
if exist "build\azw2zip.dist\DeDRM_tools\KRFKeyExtractor.exe" (
    echo   [OK] KRFKeyExtractor.exe found
) else (
    echo   [WARN] KRFKeyExtractor.exe missing!
)

pause