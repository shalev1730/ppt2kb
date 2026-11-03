; PPT2KB - Windows installer (NSIS 3.x)
; Built by deploy/windows/build-windows.sh. Self-contained: embedded Python,
; the application, LibreOffice (headless) and fonts. No downloads, no
; registry changes beyond the standard uninstall entry.
;
;   PPT2KB-Setup.exe                 interactive
;   PPT2KB-Setup.exe /S              silent (per-user, or per-machine when elevated with /AllUsers)
;   PPT2KB-Setup.exe /S /AllUsers    silent per-machine (requires administrator)
;   PPT2KB-Setup.exe /S /D=C:\Dir    silent into a specific directory (must be the last argument)
;   uninstall.exe /S                 silent uninstall (keeps the data folder)

Unicode True
!define PRODUCT "PPT2KB"
!define VERSION "1.1.1"
!define PUBLISHER "ppt2kb project (MIT)"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PPT2KB"

!define MULTIUSER_EXECUTIONLEVEL Highest
!define MULTIUSER_USE_PROGRAMFILES64
!define MULTIUSER_MUI
!define MULTIUSER_INSTALLMODE_COMMANDLINE
!define MULTIUSER_INSTALLMODE_INSTDIR "PPT2KB"
!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_KEY "${REGKEY}"
!define MULTIUSER_INSTALLMODE_DEFAULT_REGISTRY_VALUENAME "InstallLocation"
!define MULTIUSER_INSTALLMODE_INSTDIR_REGISTRY_KEY "${REGKEY}"
!define MULTIUSER_INSTALLMODE_INSTDIR_REGISTRY_VALUENAME "InstallLocation"
!include "MultiUser.nsh"
!include "MUI2.nsh"
!include "FileFunc.nsh"

Name "${PRODUCT} ${VERSION}"
OutFile "${OUTFILE}"
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${PRODUCT} ${VERSION} - on-premise PowerPoint to ServiceNow Knowledge"
ShowInstDetails show
ShowUninstDetails show

!define MUI_ICON "${SRCDIR}\assets\ppt2kb.ico"
!define MUI_UNICON "${SRCDIR}\assets\ppt2kb.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\PPT2KB.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start PPT2KB now"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\docs\INSTALL_WINDOWS.md"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the installation guide"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PAYLOAD}\LICENSE.txt"
!insertmacro MULTIUSER_PAGE_INSTALLMODE
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Hebrew"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${PRODUCT}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "FileDescription" "${PRODUCT} installer"
VIAddVersionKey "LegalCopyright" "MIT License; includes ppt2desc (c) 2025 Adam Lucek, LibreOffice (MPL-2.0), Python (PSF)"

Var CmdInstDir

Function .onInit
  StrCpy $CmdInstDir $INSTDIR          ; non-empty only when /D=<dir> was given
  !insertmacro MULTIUSER_INIT
  StrCmp $CmdInstDir "" +2
    StrCpy $INSTDIR $CmdInstDir        ; /D wins over the MultiUser default
FunctionEnd

Function un.onInit
  !insertmacro MULTIUSER_UNINIT
FunctionEnd

Function StopRunningInstance
  IfFileExists "$INSTDIR\PPT2KB.exe" 0 done
    DetailPrint "Stopping a running PPT2KB instance (if any)..."
    ExecWait '"$INSTDIR\PPT2KB.exe" --stop' $0
    Sleep 1500
  done:
FunctionEnd

Section "PPT2KB (required)" SecMain
  SectionIn RO
  Call StopRunningInstance
  SetOutPath "$INSTDIR"
  ; remove files from a previous version (config and data are outside these folders)
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\libreoffice"
  RMDir /r "$INSTDIR\mocks"
  RMDir /r "$INSTDIR\docs"
  RMDir /r "$INSTDIR\sbom"
  RMDir /r "$INSTDIR\tools"
  File /r "${PAYLOAD}\*.*"
  ; first-run configuration (never overwrite an existing one)
  CreateDirectory "$INSTDIR\config"
  IfFileExists "$INSTDIR\config\ppt2kb.env" +2 0
    CopyFiles /SILENT "$INSTDIR\config\ppt2kb.env.example" "$INSTDIR\config\ppt2kb.env"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; shortcuts
  CreateDirectory "$SMPROGRAMS\${PRODUCT}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\PPT2KB.lnk" "$INSTDIR\PPT2KB.exe" "" "$INSTDIR\PPT2KB.exe" 0 SW_SHOWNORMAL "" "Open PPT2KB (PowerPoint to ServiceNow Knowledge)"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Stop PPT2KB.lnk" "$INSTDIR\PPT2KB.exe" "--stop" "$INSTDIR\PPT2KB.exe" 0 SW_SHOWMINIMIZED "" "Stop the PPT2KB background server"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\PPT2KB (console log).lnk" "$INSTDIR\PPT2KB.exe" "--console" "$INSTDIR\PPT2KB.exe" 0 SW_SHOWNORMAL "" "Start PPT2KB with a visible log window"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Edit configuration.lnk" "$SYSDIR\notepad.exe" '"$INSTDIR\config\ppt2kb.env"' "$SYSDIR\notepad.exe" 0
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Open data folder.lnk" "$SYSDIR\explorer.exe" '"$LOCALAPPDATA\PPT2KB"' "$SYSDIR\explorer.exe" 0
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Installation guide.lnk" "$INSTDIR\docs\INSTALL_WINDOWS.md"
  CreateShortCut "$SMPROGRAMS\${PRODUCT}\Uninstall PPT2KB.lnk" "$INSTDIR\uninstall.exe"
  CreateShortCut "$DESKTOP\PPT2KB.lnk" "$INSTDIR\PPT2KB.exe" "" "$INSTDIR\PPT2KB.exe" 0 SW_SHOWNORMAL "" "Open PPT2KB"

  ; Add/Remove Programs entry
  WriteRegStr SHCTX "${REGKEY}" "DisplayName" "${PRODUCT} ${VERSION}"
  WriteRegStr SHCTX "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr SHCTX "${REGKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr SHCTX "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr SHCTX "${REGKEY}" "DisplayIcon" "$INSTDIR\PPT2KB.exe"
  WriteRegStr SHCTX "${REGKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr SHCTX "${REGKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD SHCTX "${REGKEY}" "NoModify" 1
  WriteRegDWORD SHCTX "${REGKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD SHCTX "${REGKEY}" "EstimatedSize" "$0"
SectionEnd

Section "Uninstall"
  IfFileExists "$INSTDIR\PPT2KB.exe" 0 +3
    ExecWait '"$INSTDIR\PPT2KB.exe" --stop' $0
    Sleep 1500
  Delete "$DESKTOP\PPT2KB.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT}"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\libreoffice"
  RMDir /r "$INSTDIR\mocks"
  RMDir /r "$INSTDIR\docs"
  RMDir /r "$INSTDIR\sbom"
  RMDir /r "$INSTDIR\tools"
  Delete "$INSTDIR\PPT2KB.exe"
  Delete "$INSTDIR\uninstall.exe"
  Delete "$INSTDIR\*.md"
  Delete "$INSTDIR\LICENSE*"
  Delete "$INSTDIR\BUILD-INFO.txt"
  Delete "$INSTDIR\config\ppt2kb.env.example"
  DeleteRegKey SHCTX "${REGKEY}"
  IfSilent keepdata 0
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete the configuration ($INSTDIR\config) and the data folder ($LOCALAPPDATA\PPT2KB: uploaded presentations, slide images, database, logs)?" IDNO keepdata
    RMDir /r "$INSTDIR\config"
    RMDir /r "$LOCALAPPDATA\PPT2KB"
  keepdata:
  RMDir "$INSTDIR"
SectionEnd
