
@echo off
setlocal

REM ===== EDIT THESE TWO PATHS =====
set "PYTHON_SCRIPT=C:\path\to\tellius_pak.py"
set "ZU_FOLDER=C:\path\to\zu"
REM =================================

for /d %%M in ("%ZU_FOLDER%\*") do (
    for /d %%F in ("%%~M\*") do (
        if exist "%%~fF" (
            echo.
            echo Processing: %%~fF
            python "%PYTHON_SCRIPT%" write_info "%%~fF"

            if errorlevel 1 (
                echo.
                echo ERROR: Failed to unpack %%~fF
                pause
                exit /b 1
            )
        )
    )
)

echo.
echo Finished processing all matching files.
pause
