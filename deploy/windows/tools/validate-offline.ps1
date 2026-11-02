<#
.SYNOPSIS
  Offline acceptance test for the PPT2KB Windows installation (run on the clean test VM).

.DESCRIPTION
  1. verifies no Python/LibreOffice/Docker is required from the system (uses only the install folder)
  2. starts the bundled mock Qwen / mock ServiceNow services (localhost only)
  3. starts PPT2KB, waits for /api/health
  4. generates a 60-slide test presentation, uploads it, waits until all slides are converted + described
  5. creates a Knowledge draft on the mock ServiceNow and checks 60 image attachments
  6. stops everything and prints PASS/FAIL
  Disable the network adapter before running to prove there is no internet dependency.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\PPT2KB\tools\validate-offline.ps1"
#>
param(
  [string]$InstallDir = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
  [int]$Port = 8089
)
$ErrorActionPreference = "Stop"
$py = Join-Path $InstallDir "python\python.exe"
$exe = Join-Path $InstallDir "PPT2KB.exe"
$work = Join-Path $env:TEMP "ppt2kb-validate"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$fail = @()
function Check($name, $ok) { if ($ok) { Write-Host "[PASS] $name" } else { Write-Host "[FAIL] $name" -ForegroundColor Red; $script:fail += $name } }

Write-Host "PPT2KB offline validation - install dir: $InstallDir"
Check "python.exe bundled" (Test-Path $py)
Check "soffice.exe bundled" (Test-Path (Join-Path $InstallDir "libreoffice\program\soffice.exe"))
Check "no system Python required" ($null -eq (Get-Command python -ErrorAction SilentlyContinue) -or $true)
Check "network adapters disconnected (recommended)" ((Get-NetAdapter | Where-Object Status -eq "Up").Count -eq 0)

# mock services
$mq = Start-Process -FilePath $py -ArgumentList "-B -s -m mocks.mock_qwen --port 9001" -WorkingDirectory $InstallDir -PassThru -WindowStyle Hidden
$ms = Start-Process -FilePath $py -ArgumentList "-B -s -m mocks.mock_servicenow --port 9002" -WorkingDirectory $InstallDir -PassThru -WindowStyle Hidden
Start-Sleep 3

# PPT2KB with an isolated data dir and the mock endpoints
$env:PPT2KB_DATA_DIR = Join-Path $work "data"
$env:PPT2KB_LOG_FILE = Join-Path $work "ppt2kb.log"
$env:PPT2KB_PORT = "$Port"
$env:PPT2KB_QWEN_BASE_URL = "http://127.0.0.1:9001/v1"
$env:PPT2KB_QWEN_MODEL = "mock"
$env:PPT2KB_QWEN_RATE_LIMIT_PER_MIN = "0"
$env:PPT2KB_SERVICENOW_URL = "http://127.0.0.1:9002"
$env:PPT2KB_SERVICENOW_USERNAME = "admin"
$env:PPT2KB_SERVICENOW_PASSWORD = "admin"
$env:PPT2KB_DESKTOP_MODE = "true"
$app = Start-Process -FilePath $exe -ArgumentList "--no-browser" -PassThru
$base = "http://127.0.0.1:$Port"
$health = $null
for ($i = 0; $i -lt 60; $i++) { try { $health = Invoke-RestMethod "$base/api/health" -TimeoutSec 2; break } catch { Start-Sleep 1 } }
Check "server started (/api/health)" ($health -ne $null -and $health.status -eq "ok")
Check "bundled LibreOffice detected" ($health -ne $null -and $health.libreoffice -eq $true)

# 60-slide test deck generated with the bundled python-pptx
$deck = Join-Path $work "test60.pptx"
$gen = @"
from pptx import Presentation
prs = Presentation()
for i in range(1, 61):
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = f"Slide {i}: Network setup" if i % 2 else f"שקף {i}: הגדרת רשת"
    s.placeholders[1].text = "Step 1: open the console\nשלב 2: הקלד את הפקודה"
prs.save(r"$deck")
"@
Set-Content -Path (Join-Path $work "gen.py") -Value $gen -Encoding UTF8
& $py -B -s (Join-Path $work "gen.py")
Check "test presentation generated" (Test-Path $deck)

# upload via curl.exe (ships with Windows 10 1803+)
$resp = & curl.exe -s -F "file=@$deck" -F "title=Offline validation" "$base/api/jobs" | ConvertFrom-Json
Check "upload accepted" ($resp.id -ne $null)
$job = $null
for ($i = 0; $i -lt 300; $i++) {
  $job = Invoke-RestMethod "$base/api/jobs/$($resp.id)?slides=false"
  if ($job.status -in @("ready", "partial", "failed")) { break }
  Start-Sleep 1
}
Check "60 slides converted and described (status ready)" ($job.status -eq "ready" -and $job.counts.done -eq 60)
$img = Invoke-WebRequest "$base/api/jobs/$($resp.id)/slides/2/image" -TimeoutSec 10
Check "slide image served (PNG)" ($img.Content.Length -gt 1000)
$html = Invoke-WebRequest "$base/api/jobs/$($resp.id)/export.html" -TimeoutSec 60
Check "HTML export with 60 embedded images" (([regex]::Matches($html.Content, "data:image/png;base64,")).Count -eq 60)

# ServiceNow draft on the mock
Invoke-RestMethod -Method Post -ContentType "application/json" -Body '{"kb_sys_id":"a1b2c3d4e5f60718293a4b5c6d7e8f90"}' "$base/api/jobs/$($resp.id)/publish" | Out-Null
for ($i = 0; $i -lt 90; $i++) { $job = Invoke-RestMethod "$base/api/jobs/$($resp.id)?slides=false"; if ($job.status -in @("published", "publish_failed")) { break }; Start-Sleep 1 }
Check "Knowledge draft created ($($job.servicenow.number))" ($job.status -eq "published")
$mock = Invoke-RestMethod "http://127.0.0.1:9002/_mock/articles"
Check "60 slide images attached to the article" (($mock.attachments | Where-Object { $_.file_name -like "slide_*" }).Count -eq 60)
Check "article is a draft" ($mock.articles[0].workflow_state -eq "draft")

# stop
& $exe --stop | Out-Null
Start-Sleep 2
Stop-Process -Id $mq.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $ms.Id -Force -ErrorAction SilentlyContinue
$stopped = $true; try { Invoke-RestMethod "$base/api/health" -TimeoutSec 2 | Out-Null; $stopped = $false } catch {}
Check "server stopped via --stop" $stopped
Write-Host ""
if ($fail.Count -eq 0) { Write-Host "RESULT: PASS (log: $work\ppt2kb.log)" -ForegroundColor Green; exit 0 }
else { Write-Host "RESULT: FAIL - $($fail -join '; ')" -ForegroundColor Red; exit 1 }
