@echo off
rem Starts the bundled mock Qwen (port 9001) and mock ServiceNow (port 9002) services
rem for an offline proof-of-concept on this computer. Close the windows to stop them.
rem Then set in config\ppt2kb.env (or in the UI Settings page):
rem   PPT2KB_QWEN_BASE_URL=http://127.0.0.1:9001/v1   PPT2KB_QWEN_MODEL=mock
rem   PPT2KB_SERVICENOW_URL=http://127.0.0.1:9002     user admin / password admin
setlocal
set "HERE=%~dp0.."
start "PPT2KB mock Qwen (9001)" "%HERE%\python\python.exe" -B -s -m mocks.mock_qwen --port 9001
start "PPT2KB mock ServiceNow (9002)" "%HERE%\python\python.exe" -B -s -m mocks.mock_servicenow --port 9002
echo Mock services started in two windows (Qwen: http://127.0.0.1:9001  ServiceNow: http://127.0.0.1:9002).
endlocal
