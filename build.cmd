@echo off
setlocal EnableExtensions
cd /d %~dp0

echo Syncing dependencies...
uv sync
if errorlevel 1 (
    echo.
    echo [ERROR] uv sync failed!
    exit /b 1
)

echo Cleaning build directory...
if exist build rmdir /s /q build
mkdir build
if errorlevel 1 (
    echo.
    echo [ERROR] Could not create build directory!
    exit /b 1
)

echo Copying source files...
for %%D in (DeDRM_Plugin KindleUnpack kfxlib DeDRM_tools) do (
    xcopy "%%D\*" "build\%%D\" /s /e /i /y
    if errorlevel 1 exit /b 1
)
copy /Y "*.py" "build\"
if errorlevel 1 exit /b 1

echo Building standalone executable with Nuitka...
cd build
set PYTHONPATH=%CD%\KindleUnpack\lib;%CD%\DeDRM_Plugin
uv run python -m nuitka ^
    --standalone ^
    --output-filename="azw2zip.exe" ^
    --include-package=kfxlib ^
    --include-package=kfx_stages ^
    --include-package=pypdf ^
    --include-package=lxml ^
    --include-package=PIL ^
    --include-package=Crypto ^
    --include-module=compatibility_utils ^
    --include-module=unipath ^
    --include-module=kindleunpack ^
    --include-module=DumpAZW6_py3 ^
    --include-module=kindlekey ^
    --include-module=scriptinterface ^
    --include-module=alfcrypto ^
    --include-module=k4mobidedrm ^
    --include-module=mobidedrm ^
    --include-module=utilities ^
    --include-module=kfx_page_validation ^
    --include-module=msix_registration ^
    --enable-plugin=pylint-warnings ^
    --assume-yes-for-downloads ^
    --windows-console-mode=attach ^
    --include-data-dir="DeDRM_Plugin=DeDRM_Plugin" ^
    --follow-imports ^
    --nofollow-import-to=tkinter ^
    azw2zip.py
if errorlevel 1 (
    cd ..
    echo.
    echo [ERROR] Nuitka build failed! Check errors above.
    exit /b 1
)

cd ..
if not exist "build\azw2zip.dist\azw2zip.exe" (
    echo.
    echo [ERROR] build\azw2zip.dist\azw2zip.exe was not produced!
    exit /b 1
)

echo.
echo Build complete!
echo Output: build\azw2zip.dist\azw2zip.exe
echo.
echo Copying DeDRM_tools to build output...
robocopy "build\DeDRM_tools" "build\azw2zip.dist\DeDRM_tools" /e /njh /njs /nfl /ndl
if errorlevel 8 (
    echo.
    echo [ERROR] Failed to copy DeDRM_tools into the standalone output!
    exit /b 1
)

echo.
echo Verifying DeDRM_tools...
if exist "build\azw2zip.dist\DeDRM_tools\KFXKeyExtractor282.exe" (
    echo   [OK] KFXKeyExtractor282.exe found
) else if exist "build\azw2zip.dist\DeDRM_tools\KFXKeyExtractor28.exe" (
    echo   [OK] KFXKeyExtractor28.exe found
) else (
    echo   [WARN] KFXKeyExtractor28/282.exe missing!
)

REM Legacy / optional tools.
if exist "build\azw2zip.dist\DeDRM_tools\KRFKeyExtractor.exe" (
    echo   [OK] KRFKeyExtractor.exe found
) else (
    echo   [INFO] KRFKeyExtractor.exe not found (optional)
)
if exist "build\azw2zip.dist\DeDRM_tools\KFXArchiver291.exe" (
    echo   [OK] KFXArchiver291.exe found
) else (
    echo   [INFO] KFXArchiver291.exe not found (optional)
)

REM Verify the updated archivers are included in the standalone distribution.
if exist "build\azw2zip.dist\DeDRM_tools\MSIXKFXArchiver_x64_1_5634.exe" (
    echo   [OK] MSIXKFXArchiver_x64_1_5634.exe found
) else (
    echo   [ERROR] MSIXKFXArchiver_x64_1_5634.exe missing!
    exit /b 1
)
if exist "build\azw2zip.dist\DeDRM_tools\MSIXKFXArchiver1_23620_final.exe" (
    echo   [OK] MSIXKFXArchiver1_23620_final.exe found
) else (
    echo   [ERROR] MSIXKFXArchiver1_23620_final.exe missing!
    exit /b 1
)
for %%F in (MSIXKFXArchiverMobi1_22326.exe MSIXKFXArchiverMobi1_18632.exe MSIXKFXArchiverMobi1_16118.exe) do (
    if exist "build\azw2zip.dist\DeDRM_tools\%%F" echo   [OK] %%F found
)

echo.
echo Renaming output folder ...
if exist "build\azw2zip" rmdir /s /q "build\azw2zip"
robocopy "build\azw2zip.dist" "build\azw2zip" /e /move /njh /njs /nfl /ndl
if errorlevel 8 (
    echo.
    echo [ERROR] Failed to finalize build\azw2zip!
    exit /b 1
)
if exist "build\azw2zip.dist" rmdir /s /q "build\azw2zip.dist"

if not exist "build\azw2zip\azw2zip.exe" (
    echo.
    echo [ERROR] build\azw2zip\azw2zip.exe is missing after finalization!
    exit /b 1
)

echo.
echo Build process finished.
echo Output: build\azw2zip\azw2zip.exe
echo.

endlocal
exit /b 0
