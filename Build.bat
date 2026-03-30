@echo off
set "directory=%~dp0"

:: 编译资源文件
for /r "%directory%" %%f in (*.qrc) do (
    echo Compiled %%f into %%~dpnf.py
    pyside6-rcc -o "%%~dpnf.py" "%%f"
)

:: 打包可执行文件
pyinstaller --onefile --noconsole -i "p4.ico" P4InterchangesTool.py

:: 复制生成的 exe 文件到当前目录并重命名
copy dist\P4InterchangesTool.exe streamMerge.exe

:: 运行生成的可执行文件
streamMerge.exe
