#!/usr/bin/env bash
# Reproducible build of PPT2KB-Setup.exe (Windows 10/11 x64) on a Linux host.
#
#   deploy/windows/build-windows.sh [--work /path] [--out dist] [--skip-download]
#
# Host requirements (Debian/Ubuntu): python3 + pip, nsis, msitools, gcc-mingw-w64-x86-64,
# p7zip-full (verification only), curl.  Everything is pinned below; the
# downloaded files are checked against the SHA256 values in
# deploy/windows/components.sha256 (update them when bumping versions).
#
# Steps: download components -> extract embedded Python -> install pinned Windows
# wheels (no compilation, win_amd64 wheels only) -> extract and trim LibreOffice
# -> cross-compile the launcher -> makensis -> SHA256.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$PWD"
WORK="${WORK:-$REPO/build-windows}"
OUT="$REPO/dist"
SKIP_DL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --work) WORK="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --skip-download) SKIP_DL=1; shift;;
    *) echo "unknown option $1"; exit 2;;
  esac
done

# ---------------------------------------------------------------- pinned components
PY_VER=3.13.17
PY_URL="https://www.python.org/ftp/python/${PY_VER}/python-${PY_VER}-embed-amd64.zip"
LO_VER=25.8.7
LO_URL="https://download.documentfoundation.org/libreoffice/stable/${LO_VER}/win/x86_64/LibreOffice_${LO_VER}_Win_x86-64.msi"
VERSION="$(python3 -c 'import re;print(re.search(r"version\s*=\s*\"([^\"]+)\"", open("pyproject.toml").read()).group(1))')"

DL="$WORK/downloads"; PAYLOAD="$WORK/payload"; LOX="$WORK/lo-extract"
mkdir -p "$DL" "$OUT"
echo "==> Components: Python $PY_VER (embeddable), LibreOffice $LO_VER, ppt2kb $VERSION"

if [ "$SKIP_DL" = 0 ]; then
  echo "==> Downloading"
  [ -f "$DL/python-${PY_VER}-embed-amd64.zip" ] || curl -sS -L --retry 3 -o "$DL/python-${PY_VER}-embed-amd64.zip" "$PY_URL"
  [ -f "$DL/LibreOffice_${LO_VER}_Win_x86-64.msi" ] || curl -sS -L --retry 3 -o "$DL/LibreOffice_${LO_VER}_Win_x86-64.msi" "$LO_URL"
  [ -f "$DL/LibreOffice_${LO_VER}_Win_x86-64.msi.asc" ] || curl -sS -L --retry 3 -o "$DL/LibreOffice_${LO_VER}_Win_x86-64.msi.asc" "$LO_URL.asc"
fi
echo "==> Verifying component checksums"
( cd "$DL" && sha256sum -c "$REPO/deploy/windows/components.sha256" )

echo "==> Embedded Python"
rm -rf "$PAYLOAD"; mkdir -p "$PAYLOAD/python" "$PAYLOAD/config" "$PAYLOAD/docs" "$PAYLOAD/tools"
( cd "$PAYLOAD/python" && unzip -q "$DL/python-${PY_VER}-embed-amd64.zip" )
PYTAG="$(ls "$PAYLOAD/python"/python3*.zip | sed -E 's#.*/python([0-9]+)\.zip#\1#')"   # e.g. 313
printf 'python%s.zip\n.\n..\nLib\\site-packages\n' "$PYTAG" > "$PAYLOAD/python/python${PYTAG}._pth"
mkdir -p "$PAYLOAD/python/Lib/site-packages"

echo "==> Application wheel + pinned Windows dependencies (win_amd64, cp${PYTAG})"
rm -rf "$WORK/wheel"; python3 -m pip wheel -q --no-deps -w "$WORK/wheel" "$REPO"
python3 -m pip install -q --target "$PAYLOAD/python/Lib/site-packages" \
  --platform win_amd64 --python-version "${PY_VER%.*}" --implementation cp --abi "cp${PYTAG}" --abi abi3 --abi none \
  --only-binary=:all: --no-compile -r "$REPO/requirements.txt" "$WORK"/wheel/ppt2kb-*.whl
rm -rf "$PAYLOAD/python/Lib/site-packages/bin"
if find "$PAYLOAD/python" -name '*.so' | grep -q .; then echo "ERROR: Linux binaries in the Windows payload"; exit 1; fi

echo "==> LibreOffice (extract MSI, keep what headless Impress conversion needs: en-US + he)"
rm -rf "$LOX"; mkdir -p "$LOX"; ( cd "$LOX" && msiextract "$DL/LibreOffice_${LO_VER}_Win_x86-64.msi" >/dev/null )
SRC="$LOX/LibreOffice:."; DST="$PAYLOAD/libreoffice"; mkdir -p "$DST"
cp -r "$SRC/program" "$SRC/share" "$SRC/presets" "$SRC/LICENSE.html" "$SRC/NOTICE" "$SRC/license.txt" "$DST/"
( cd "$DST"
  find program/resource -mindepth 1 -maxdepth 1 -type d ! -name en-US ! -name he ! -name common -exec rm -rf {} +
  rm -rf program/python-core-* program/python.exe program/python3.dll program/python3*.dll program/pythonloader.py \
         program/pythonloader.uno.ini program/pythonloaderlo.dll program/pythonscript.py program/classes \
         program/java_uno.dll program/javaloaderlo.dll program/javavmlo.dll program/juh.dll program/jpipe.dll program/jpipx.dll program/javavendors.xml
  find share/registry/res -name 'Langpack-*.xcd' ! -name 'Langpack-en-US.xcd' ! -name 'Langpack-he.xcd' -delete
  find share/registry/res -name 'fcfg_langpack_*.xcd' ! -name 'fcfg_langpack_en-US.xcd' ! -name 'fcfg_langpack_he.xcd' -delete
  find share/registry/res -name 'registry_*.xcd' ! -name 'registry_he.xcd' -delete
  rm -f share/registry/cjk_*.xcd share/registry/ctlseqcheck_*.xcd share/registry/onlineupdate.xcd share/registry/reportbuilder.xcd \
        share/registry/postgresql.xcd share/registry/librelogo.xcd share/registry/*.sample
  find share/registry -name 'ctl_*.xcd' ! -name 'ctl_he.xcd' -delete
  rm -rf share/extensions share/gallery share/template share/autotext share/wizards share/Scripts share/tipoftheday
  find share/config -name 'images_*.zip' ! -name 'images_colibre.zip' -delete
  # VC++ runtime DLLs shipped inside the MSI, kept private next to soffice.exe (no system-wide install)
  cp "$LOX/System64/"*.dll program/
  mkdir -p share/fonts/truetype
  for f in DavidCLM DavidLibre FrankRuehlCLM MiriamCLM MiriamMonoCLM NachlieliCLM NotoSansHebrew NotoSerifHebrew Alef Rubik \
           LiberationSans LiberationSerif LiberationMono LiberationSansNarrow Carlito Caladea DejaVuSans DejaVuSerif DejaVuSansMono NotoSans NotoSerif; do
    cp "$LOX/Fonts/${f}"-* share/fonts/truetype/ 2>/dev/null || true
  done
)
# the same runtime DLLs next to python.exe (pydantic_core / lxml / Pillow need vcruntime140*, msvcp140*)
cp "$LOX/System64/"*.dll "$PAYLOAD/python/"
rm -rf "$LOX"

echo "==> Launcher (MinGW cross-compile)"
( cd "$REPO/deploy/windows/launcher"
  x86_64-w64-mingw32-windres ppt2kb_launcher.rc -O coff -o "$WORK/launcher.res"
  x86_64-w64-mingw32-gcc -O2 -municode -mwindows -s -o "$PAYLOAD/PPT2KB.exe" ppt2kb_launcher.c "$WORK/launcher.res" -lshlwapi )

echo "==> Documentation, licenses, config template, mocks, tools"
cp "$REPO/deploy/windows/ppt2kb.env.example" "$PAYLOAD/config/ppt2kb.env.example"
cp "$REPO/README.md" "$REPO/THIRD_PARTY_NOTICES.md" "$REPO/LICENSE.ppt2desc" "$PAYLOAD/"
cp "$REPO/LICENSE" "$PAYLOAD/LICENSE.txt"
cp "$REPO"/docs/*.md "$PAYLOAD/docs/"
cp -r "$REPO/sbom" "$PAYLOAD/sbom"
cp -r "$REPO/mocks" "$PAYLOAD/mocks"; rm -rf "$PAYLOAD/mocks/__pycache__"
cp "$REPO/deploy/windows/tools/"* "$PAYLOAD/tools/"
{ echo "PPT2KB $VERSION"; echo "python-embed $PY_VER"; echo "libreoffice $LO_VER (trimmed: en-US+he, no Java/Python/extensions)"; echo "built $(date -u +%Y-%m-%dT%H:%M:%SZ)"; } > "$PAYLOAD/BUILD-INFO.txt"
find "$PAYLOAD" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "==> Payload inventory (for the SBOM / security review)"
( cd "$PAYLOAD" && find . -type f -print0 | sort -z | xargs -0 sha256sum > "$OUT/PPT2KB-Setup-payload.sha256" )
du -sh "$PAYLOAD"

echo "==> makensis"
makensis -V2 -DSRCDIR="$REPO/deploy/windows" -DPAYLOAD="$PAYLOAD" -DOUTFILE="$OUT/PPT2KB-Setup.exe" "$REPO/deploy/windows/ppt2kb.nsi"
( cd "$OUT" && sha256sum PPT2KB-Setup.exe | tee PPT2KB-Setup.exe.sha256 )
echo "==> Done: $OUT/PPT2KB-Setup.exe"
