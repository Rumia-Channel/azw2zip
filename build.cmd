@echo off

cd /d %~dp0

rye sync

mkdir build

xcopy "DeDRM_Plugin\*" "build\" /s /e /y
xcopy "KindleUnpack\lib\*" "build\" /s /e /y

copy /Y "*.py" "build\"

rye run python -m nuitka --onefile --output-"dir=build\out" "build\azw2zip.py"