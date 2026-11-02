# Dependency inventory (Python runtime)

Generated from `requirements.txt` on the verified build environment. See `sbom/ppt2kb-sbom.cdx.json` (CycloneDX 1.6) for the machine-readable SBOM and `sbom/pip-audit.txt` for the vulnerability scan result.

| Package | Version | License | Purpose | Source |
|---|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | FastAPI dependency | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | pydantic dependency | https://github.com/annotated-types/annotated-types |
| anyio | 4.15.1 | MIT | async compatibility layer | https://github.com/agronholm/anyio |
| certifi | 2026.10.18 | Mozilla Public License 2.0 (MPL 2.0) | Mozilla CA bundle (fallback only; internal CA configured via PPT2KB_CA_BUNDLE) | https://github.com/certifi/python-certifi |
| click | 8.5.0 | BSD-3-Clause | CLI helper (uvicorn dependency) | https://github.com/pallets/click/ |
| fastapi | 0.162.0 | MIT | Web framework (API + static UI) | https://github.com/fastapi/fastapi |
| h11 | 0.16.0 | MIT License | HTTP/1.1 parser | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | httpx transport | https://www.encode.io/httpcore/ |
| httpx | 0.28.1 | BSD License | HTTP client for Qwen / ServiceNow | https://github.com/encode/httpx |
| idna | 3.20 | BSD-3-Clause | IDNA hostnames (httpx) | https://github.com/kjd/idna |
| lxml | 6.1.3 | BSD-3-Clause | XML parser (python-pptx dependency) | https://github.com/lxml/lxml |
| opentelemetry-api | 1.45.2 | Apache-2.0 | FastAPI dependency (API only, no SDK/exporter installed; telemetry disabled) | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| pillow | 13.0.0 | MIT-CMU | image compositing / PNG encoding | https://python-pillow.org |
| pydantic-settings | 2.16.2 | MIT | environment configuration | https://github.com/pydantic/pydantic-settings |
| pydantic | 2.13.5 | MIT | settings/schema validation | https://github.com/pydantic/pydantic |
| pydantic_core | 2.46.5 | MIT | pydantic runtime | https://github.com/pydantic |
| pypdfium2 | 5.13.0 | BSD-3-Clause, Apache-2.0, dependency licenses | PDF page rendering (bundles pdfium) | https://github.com/pypdfium2-team/pypdfium2 |
| python-dotenv | 1.2.3 | BSD-3-Clause | env-file loading (pydantic-settings) | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.32 | Apache-2.0 | multipart upload parsing | https://github.com/Kludex/python-multipart |
| python-pptx | 1.0.2 | MIT License | original slide text extraction + test deck generation | https://github.com/scanny/python-pptx |
| starlette | 1.7.0 | BSD-3-Clause | ASGI toolkit (FastAPI dependency) | https://github.com/Kludex/starlette |
| typing-inspection | 0.4.4 | MIT | pydantic dependency | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | typing backports | https://github.com/python/typing_extensions |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server | https://uvicorn.dev/ |
| xlsxwriter | 3.2.9 | BSD License | python-pptx dependency (chart data), unused at runtime | https://github.com/jmcnamara/XlsxWriter |

## Package-specific SBOMs

* `ppt2kb-docker-image-sbom.cdx.json` — the Python packages above plus the 256 Debian packages of the image (`docker-image-debian-packages.tsv`).
* `ppt2kb-windows-sbom.cdx.json` — the Python packages plus the embedded CPython 3.13.17, LibreOffice 25.8.7 (Windows), the VC++ runtime DLLs, the launcher and NSIS; `PPT2KB-Setup-payload.sha256` lists every installed file with its SHA-256.

## System packages (container image / standalone host)

| Package | License | Purpose |
|---|---|---|
| LibreOffice (impress, draw, core, common) | MPL-2.0 (+ LGPL/Apache components) | PPT/PPTX -> PDF conversion, headless, isolated process |
| pdfium (bundled in pypdfium2 wheel) | BSD-3-Clause / Apache-2.0 | PDF -> raster rendering |
| fonts-dejavu-core | Bitstream Vera / public domain additions | Latin fallback fonts |
| fonts-liberation2 | SIL OFL 1.1 | Arial/Times/Courier metric-compatible fonts |
| fonts-crosextra-carlito / caladea | SIL OFL 1.1 | Calibri/Cambria metric-compatible fonts |
| fonts-noto-core, fonts-noto-color-emoji | SIL OFL 1.1 | Broad Unicode coverage incl. Hebrew (Noto Sans Hebrew) |
| culmus | GPL-2.0 with font exception | Hebrew fonts (David, Frank Ruehl, Miriam, ...) |
| tini | MIT | PID 1 / signal forwarding in the container |
| python 3.12 (Debian bookworm image) | PSF-2.0 | runtime |

## Removed compared to upstream ppt2desc

The upstream project pinned ~55 packages including `anthropic`, `openai`, `boto3`/`botocore`, the full `google-cloud-*` / `google-generativeai` / `grpcio` stack, `requests`, `numpy`, `shapely`, `tqdm` and `pymupdf` (AGPL-3.0). None of these are needed for an internal Qwen endpoint; all were removed, which eliminates every cloud SDK (and their credential discovery / telemetry code paths) and the AGPL obligation.
