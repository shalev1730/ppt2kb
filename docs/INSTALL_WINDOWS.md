# PPT2KB for Windows — installation guide (PPT2KB-Setup.exe)

Self-contained desktop edition for Windows 10/11 x64. The installer contains
everything the application needs: an embedded Python 3.13 runtime, the PPT2KB
application and its libraries, LibreOffice (headless, for PowerPoint
conversion) with Hebrew and Latin fonts, and the Visual C++ runtime DLLs.
Nothing is downloaded during installation or at runtime; no other software
has to be installed.

| | |
|---|---|
| Installer | `PPT2KB-Setup.exe` (verify with `PPT2KB-Setup.exe.sha256`) |
| Install location | per user: `%LOCALAPPDATA%\Programs\PPT2KB` (no administrator rights needed) — or per machine: `C:\Program Files\PPT2KB` when run as administrator and "All users" is chosen |
| Data | `%LOCALAPPDATA%\PPT2KB\data` (uploads, slide images, SQLite database) and `%LOCALAPPDATA%\PPT2KB\logs` |
| Configuration | `<install dir>\config\ppt2kb.env` (Start menu → PPT2KB → *Edit configuration*) |
| Network | listens on `127.0.0.1:8080` only; outbound only to the Qwen and ServiceNow URLs you configure |
| Uninstall | Settings → Apps → PPT2KB, or Start menu → PPT2KB → *Uninstall PPT2KB*, or `uninstall.exe /S` |

## 1. Verify and install

```powershell
Get-FileHash .\PPT2KB-Setup.exe -Algorithm SHA256      # compare with PPT2KB-Setup.exe.sha256
.\PPT2KB-Setup.exe                                     # interactive: Next, Next, Install
```

Silent / scripted deployment:

```
PPT2KB-Setup.exe /S                      per-user, default folder
PPT2KB-Setup.exe /S /AllUsers            per-machine (run elevated)
PPT2KB-Setup.exe /S /D=D:\Apps\PPT2KB    custom folder (/D must be last)
```

The installer creates a desktop shortcut **PPT2KB** and a Start-menu folder
with: *PPT2KB*, *Stop PPT2KB*, *PPT2KB (console log)*, *Edit configuration*,
*Open data folder*, *Installation guide*, *Uninstall PPT2KB*.

The installer is not code-signed with an organisational certificate; Windows
SmartScreen may show "unknown publisher" — verify the SHA-256 instead, or sign
the installer with your internal code-signing certificate
(`signtool sign /fd SHA256 /a PPT2KB-Setup.exe`) before distribution.

## 2. Configure the internal endpoints

Either in the UI (**Settings** page — credentials entered there are stored
encrypted with Windows DPAPI for the current user) or in
`config\ppt2kb.env` (Start menu → *Edit configuration*), then *Stop PPT2KB* and
start it again:

```
PPT2KB_QWEN_BASE_URL=https://qwen.internal.example/v1
PPT2KB_QWEN_MODEL=Qwen2.5-VL-72B-Instruct
PPT2KB_QWEN_API_KEY=...
PPT2KB_SERVICENOW_URL=https://servicenow.internal.example
PPT2KB_SERVICENOW_USERNAME=svc_ppt2kb
PPT2KB_SERVICENOW_PASSWORD=...
PPT2KB_CA_BUNDLE=C:\Users\<you>\AppData\Local\Programs\PPT2KB\config\ca.pem
PPT2KB_ALLOWED_OUTBOUND_HOSTS=qwen.internal.example,servicenow.internal.example
```

`PPT2KB_CA_BUNDLE` is the PEM file with your internal CA chain (copy it into
the `config` folder). `PPT2KB_ALLOWED_OUTBOUND_HOSTS` locks outbound traffic to
exactly those hosts; the UI then refuses any other URL. All settings are
documented in `docs\CONFIGURATION.md`.

## 3. Use

Double-click **PPT2KB**. The server starts in the background and the UI opens
in your default browser at `http://127.0.0.1:8080/`. Closing the browser does
not stop the server; use *Stop PPT2KB* (or it ends when you sign out).
Workflow: **Upload** a PowerPoint → watch the slide progress → review/edit the
generated text, check the embedded images that will be attached (tick/untick
*Include*), resolve any slide marked *needs review* → *Create draft article*
(choose the knowledge base and the image attachment mode) → the article
number and links are shown. Full description: `docs\USER_GUIDE.md`.
Switch the UI to Hebrew with the **עברית** button.

If port 8080 is taken by another program, set `PPT2KB_PORT` in the
configuration file. The desktop edition always binds to 127.0.0.1 (this
computer only); it is not intended to be exposed to other users — use the
Docker/server edition for that.

## 4. Offline proof-of-concept without real endpoints

The installation includes mock services for a self-contained test:

1. Start menu → *PPT2KB* folder is not needed; run `<install dir>\tools\start-mock-services.cmd`
   (two console windows: mock Qwen on port 9001, mock ServiceNow on port 9002).
2. In **Settings** set Qwen URL `http://127.0.0.1:9001/v1`, model `mock`;
   ServiceNow URL `http://127.0.0.1:9002`, Basic auth `admin` / `admin`.
3. Upload any `.pptx`, process, create the draft. `http://127.0.0.1:9002/_mock/articles`
   shows the created article and attachments.

Automated acceptance test (recommended on the clean, network-disabled VM):

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\PPT2KB\tools\validate-offline.ps1"
```

It starts the mocks and PPT2KB with a temporary data folder, generates a
60-slide presentation, converts and describes it, creates the draft with 60
attachments, stops everything and prints PASS/FAIL per check.

## 5. Update

Run the new `PPT2KB-Setup.exe` over the existing installation: it stops a
running instance, replaces the program files and keeps `config\ppt2kb.env`
and the data folder. Downgrade the same way with the older installer.
Upgrading from 1.0.x or 1.1.0 to 1.1.1: the local database is migrated automatically on
first start; presentations processed by 1.0 keep their text and get their
embedded images extracted automatically when you publish them (or earlier,
by re-selecting *Image attachment mode* on the presentation page).

## 6. Troubleshooting

| Symptom | What to do |
|---|---|
| Nothing happens when starting | Start menu → *PPT2KB (console log)* shows the server output; log file in `%LOCALAPPDATA%\PPT2KB\logs\ppt2kb.log` |
| "Port 8080 is in use" | change `PPT2KB_PORT` in `config\ppt2kb.env` |
| Slides fail with *conversion failed* | run `<install dir>\libreoffice\program\soffice.exe --version` from a console; antivirus may block `soffice.bin` — allow the install folder |
| *connection error* on slides / test connection | URL, CA bundle (`PPT2KB_CA_BUNDLE`), proxy: the application ignores system proxy settings by design; the endpoints must be reachable directly |
| Hebrew shown as boxes in slide images | the bundled fonts cover Hebrew; for presentations using other fonts, install them in Windows (LibreOffice also uses system fonts) |
| Antivirus flags the installer | it is an NSIS installer containing LibreOffice and Python; verify the SHA-256 and the payload inventory (`PPT2KB-Setup-payload.sha256`) and whitelist, or rebuild it yourself with `deploy/windows/build-windows.sh` |

## 7. What the installer writes

Files only under the install folder; one registry key
(`HKCU` or `HKLM` `\Software\Microsoft\Windows\CurrentVersion\Uninstall\PPT2KB`)
for Add/Remove Programs; shortcuts on the desktop and Start menu. No
services, no scheduled tasks, no file associations, no PATH changes, no
system-wide runtime installation (the VC++ DLLs stay inside the folder).
