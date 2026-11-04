# Reproducing the release artifacts

Both packages are produced from this repository with scripts that pin every
external component. The build host needs internet access (or mirrors) once;
the resulting artifacts need none.

| Artifact | Script | Inputs (pinned) |
|---|---|---|
| `ppt2kb-web-offline.tar` | `deploy/docker/Dockerfile` via buildah or docker | base image `python:3.12-slim-bookworm`, Debian 12 packages (apt), `requirements.txt` (pip) |
| `PPT2KB-Setup.exe` | `deploy/windows/build-windows.sh` | Python 3.13.17 embeddable, LibreOffice 25.8.7 MSI, `requirements.txt` wheels (win_amd64), MinGW, NSIS 3.09 — checksums in `deploy/windows/components.sha256` |

Build host used for the released artifacts: Ubuntu 24.04 x86_64, Python
3.13.18, buildah 1.33.7, skopeo 1.13.3, nsis 3.09, msitools 0.103,
gcc-mingw-w64-x86-64 13.2, wine 9.0 (for testing only).

## 1. Docker image (`ppt2kb-web-offline.tar`)

Without a Docker daemon (rootful buildah, as used for the release):

```bash
sudo apt-get install -y buildah skopeo
cd ppt2kb
buildah --storage-driver vfs bud --isolation chroot --network host \
  --build-arg APT_MIRROR=https://deb.debian.org/debian \
  -f deploy/docker/Dockerfile -t ppt2kb:1.1.2 .
buildah --storage-driver vfs push ppt2kb:1.1.2 docker-archive:dist/ppt2kb-web-offline.tar:ppt2kb:1.1.2
skopeo inspect docker-archive:dist/ppt2kb-web-offline.tar | jq '.Labels, .Layers'
sha256sum dist/ppt2kb-web-offline.tar
```

Behind an egress proxy that re-terminates TLS, add
`-v /path/ca.pem:/build-ca.crt:ro --build-arg BUILD_PROXY=http://proxy:port --build-arg BUILD_CA_FILE=/build-ca.crt`
(used only during the build; nothing of it stays in the image). Internal
mirrors: `--build-arg APT_MIRROR=https://mirror.internal/debian --build-arg PIP_INDEX_URL=https://nexus.internal/repository/pypi/simple`.

With Docker: `docker build -f deploy/docker/Dockerfile -t ppt2kb:1.1.2 . && docker save ppt2kb:1.1.2 -o dist/ppt2kb-web-offline.tar`.

Determinism: the image is not bit-for-bit reproducible (apt package versions
move with Debian security updates, timestamps differ), but its *content* is
fully described: `sbom/docker-image-debian-packages.tsv` (256 Debian packages
as built), `sbom/ppt2kb-docker-image-sbom.cdx.json`, and `requirements.txt`.
A rebuild should be compared against those lists.

Functional check of a rebuilt image (no Docker daemon needed):

```bash
ctr=$(buildah --storage-driver vfs from ppt2kb:1.1.2)
buildah --storage-driver vfs run --isolation chroot --user 10001:10001 $ctr -- sh -c 'id; soffice --version; python -c "import ppt2kb;print(ppt2kb.__version__)"'
```

or with Docker: `docker run --rm ppt2kb:1.1.2 soffice --version`. The full
in-container acceptance run used for the release is described in
`docs/TEST_RESULTS.md`.

## 2. Windows installer (`PPT2KB-Setup.exe`)

```bash
sudo apt-get install -y nsis msitools gcc-mingw-w64-x86-64 p7zip-full python3-pip
cd ppt2kb
deploy/windows/build-windows.sh                 # ~8 minutes; downloads ~380 MB once
ls dist/PPT2KB-Setup.exe dist/PPT2KB-Setup.exe.sha256 dist/PPT2KB-Setup-payload.sha256
```

What the script does (all steps are in the script, nothing manual):

1. downloads the Python embeddable zip, the LibreOffice MSI and its `.asc`
   signature, then verifies them against `deploy/windows/components.sha256`;
   the MSI signature can additionally be checked with
   `gpg --verify LibreOffice_25.8.7_Win_x86-64.msi.asc` (TDF code-signing key
   `C283 9ECA D940 8FBE 9531 C3E9 F434 A1EF AFEE AEA3`) — this was done for the release;
2. unpacks Python, writes `python313._pth` (`python313.zip`, `.`, `..`, `Lib\site-packages`);
3. `pip install --target ... --platform win_amd64 --only-binary=:all:` of
   `requirements.txt` plus the `ppt2kb` wheel built from the repository — no
   compilation, exactly the pinned versions; fails if any Linux binary ends up in the payload;
4. `msiextract` of the LibreOffice MSI and pruning to what headless Impress
   conversion needs (en-US + Hebrew UI data, no Java, no bundled Python, no
   extensions/dictionaries/galleries/templates, one icon theme), VC++ runtime
   DLLs from the MSI placed next to `soffice.exe` and `python.exe`, Hebrew and
   metric-compatible Latin fonts into `share/fonts/truetype`;
5. cross-compiles `deploy/windows/launcher/ppt2kb_launcher.c` (55 kB, imports
   only kernel32/user32/shlwapi/msvcrt);
6. copies docs, licenses, SBOM, config template, mock services, tools;
   writes `PPT2KB-Setup-payload.sha256` (SHA-256 of every file that will be installed);
7. `makensis deploy/windows/ppt2kb.nsi` → `PPT2KB-Setup.exe` (LZMA solid).

To inspect an installer without running it: `7z l PPT2KB-Setup.exe` lists all
4,7xx files; `7z x PPT2KB-Setup.exe -oextracted` unpacks them so the payload
checksums can be compared with `PPT2KB-Setup-payload.sha256`.

Determinism: the payload content is deterministic for the pinned inputs
(except file timestamps); the installer stub adds the NSIS 3.09 runtime.
Code-sign the final installer with your organisation's certificate if
required: `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 /a PPT2KB-Setup.exe`.

## 3. Source archive

`ppt2kb-1.1.2-src.tar.gz` contains the complete repository (code, tests,
deployment files, docs, SBOM). `python -m pytest` runs the 57 automated tests
(needs LibreOffice on the host).
