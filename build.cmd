@echo off

cd /d %~dp0

uv sync

mkdir build

xcopy "DeDRM_Plugin\*" "build\" /s /e /y
xcopy "KindleUnpack\lib\*" "build\" /s /e /y

copy /Y "*.py" "build\"

uv run python -m nuitka --onefile --output-dir="build\out" "build\azw2zip.py"