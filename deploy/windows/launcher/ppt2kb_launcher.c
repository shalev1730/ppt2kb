/*
 * PPT2KB.exe - Windows launcher for the desktop edition.
 *
 * Runs the embedded interpreter with the ppt2kb.desktop module:
 *     <install>\python\pythonw.exe -m ppt2kb.desktop [args]
 * (no console window). With "--console" it uses python.exe instead so the
 * log is visible; with "--stop" it waits for the stop command to finish.
 *
 * No network code, no registry access, no elevation. Source is part of the
 * repository; build with: x86_64-w64-mingw32-gcc (see build-windows.sh).
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlwapi.h>
#include <string.h>
#include <wchar.h>

static void fail(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"PPT2KB", MB_OK | MB_ICONERROR);
    ExitProcess(1);
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmdline, int nShow) {
    (void)hInst; (void)hPrev; (void)nShow;
    wchar_t exe[MAX_PATH], dir[MAX_PATH], py[MAX_PATH], envfile[MAX_PATH];
    if (!GetModuleFileNameW(NULL, exe, MAX_PATH)) fail(L"Cannot determine the installation directory.");
    wcscpy_s(dir, MAX_PATH, exe);
    PathRemoveFileSpecW(dir);

    BOOL console = (wcsstr(cmdline, L"--console") != NULL);
    BOOL wait    = (wcsstr(cmdline, L"--stop") != NULL) || console;

    swprintf(py, MAX_PATH, L"%ls\\python\\%ls", dir, console ? L"python.exe" : L"pythonw.exe");
    if (!PathFileExistsW(py)) fail(L"The embedded Python runtime is missing. Please reinstall PPT2KB.");

    swprintf(envfile, MAX_PATH, L"%ls\\config\\ppt2kb.env", dir);
    if (PathFileExistsW(envfile)) SetEnvironmentVariableW(L"PPT2KB_ENV_FILE", envfile);
    SetEnvironmentVariableW(L"OTEL_SDK_DISABLED", L"true");
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1");
    SetEnvironmentVariableW(L"PYTHONIOENCODING", L"utf-8");

    wchar_t cmd[4096];
    swprintf(cmd, 4096, L"\"%ls\" -B -s -m ppt2kb.desktop %ls", py, cmdline);

    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    DWORD flags = console ? CREATE_NEW_CONSOLE : CREATE_NO_WINDOW;
    HANDLE hnul = INVALID_HANDLE_VALUE;
    if (!console) {
        /* Give the hidden child well-defined standard handles (NUL) instead of
           whatever this GUI process inherited; the server logs to its log file. */
        SECURITY_ATTRIBUTES sa; sa.nLength = sizeof(sa); sa.lpSecurityDescriptor = NULL; sa.bInheritHandle = TRUE;
        hnul = CreateFileW(L"NUL", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
        if (hnul != INVALID_HANDLE_VALUE) {
            si.dwFlags = STARTF_USESTDHANDLES;
            si.hStdInput = hnul; si.hStdOutput = hnul; si.hStdError = hnul;
        }
    }
    if (!CreateProcessW(NULL, cmd, NULL, NULL, hnul != INVALID_HANDLE_VALUE, flags, NULL, dir, &si, &pi))
        fail(L"Could not start the PPT2KB server process.");
    if (hnul != INVALID_HANDLE_VALUE) CloseHandle(hnul);
    DWORD code = 0;
    if (wait) {
        WaitForSingleObject(pi.hProcess, INFINITE);
        GetExitCodeProcess(pi.hProcess, &code);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
