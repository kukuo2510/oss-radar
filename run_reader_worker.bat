@echo off
:: 深讀翻譯站：雙擊執行一次，或交給 Windows 工作排程器定時執行。
:: 會把深讀清單裡排隊的文章抓下來、用本機 Ollama 翻譯，再順便補寫推薦理由，處理完就結束。
:: 執行紀錄附加在 data\reader\worker.log。
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0src"
if not exist "..\data\reader" mkdir "..\data\reader"
echo ===== %date% %time% ===== >> "..\data\reader\worker.log"
"..\venv\Scripts\python.exe" reader_worker.py >> "..\data\reader\worker.log" 2>&1
echo Reader worker finished. Log: data\reader\worker.log
