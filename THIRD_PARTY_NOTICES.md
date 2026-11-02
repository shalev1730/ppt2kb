# Third-party notices

ppt2kb is derived from **ppt2desc** by Adam Łucek (https://github.com/ALucek/ppt2desc),
licensed under the MIT License. The original license text is preserved in
`LICENSE.ppt2desc`. The following parts of ppt2kb are adapted from ppt2desc and
carry a header saying so:

| ppt2kb file | ppt2desc origin | Change |
|---|---|---|
| `src/ppt2kb/converters/ppt_converter.py` | `src/converters/ppt_converter.py` | process isolation, timeouts, resource limits, throw-away profile |
| `src/ppt2kb/converters/pdf_converter.py` | `src/converters/pdf_converter.py` | PyMuPDF (AGPL) replaced by pypdfium2; page limit; placeholder on page error |
| `src/ppt2kb/converters/exceptions.py` | `src/converters/exceptions.py` | unchanged |
| `src/ppt2kb/llm/base.py` | `src/llm/base.py` | unchanged |
| `src/ppt2kb/llm/rate_limiter.py` | `ThreadSafeRateLimiter` in `src/processor.py` | unchanged |
| `src/ppt2kb/llm/qwen.py` | `src/llm/openai.py` | OpenAI SDK replaced by httpx; configurable endpoint/auth/TLS; retries; JSON parsing |
| `src/ppt2kb/pipeline/processor.py` | `src/processor.py` | partial-JSON resume replaced by SQLite per-slide state; per-slide retry |
| `src/ppt2kb/prompt.py` | `src/prompt.py` | original `BASE_PROMPT` kept; structured, anti-hallucination, bilingual prompt added |
| `src/ppt2kb/schemas/deck.py` | `src/schemas/deck.py` | `DeckData`/`SlideData` kept and extended |

Removed from ppt2desc: `src/llm/{anthropic,aws,azure,google_unified}.py`,
`src/converters/docker_converter.py`, `src/libreoffice_docker/*`, `src/main.py`
(CLI replaced by `ppt2kb-cli`) and all cloud SDK dependencies.

## Python packages

See `sbom/DEPENDENCY_INVENTORY.md` for the full list with versions and licenses
and `sbom/ppt2kb-sbom.cdx.json` for the CycloneDX SBOM. All runtime packages are
distributed under permissive licenses (MIT, BSD-3-Clause, Apache-2.0, MPL-2.0 for
certifi, PSF). License texts are included in each wheel's `*.dist-info/licenses`
directory inside the virtual environment / container image.

Notable:

* **pypdfium2** (BSD-3-Clause / Apache-2.0) bundles Google **pdfium** (BSD-3-Clause),
  which itself includes third-party code (FreeType - FTL/GPLv2 dual, libjpeg-turbo,
  OpenJPEG, Skia, etc.); see https://pdfium.googlesource.com/pdfium/+/main/LICENSE
  and the `LICENSE` files shipped inside the wheel.
* **python-pptx** depends on **lxml** (BSD-3-Clause; libxml2/libxslt MIT).

## System packages

* **LibreOffice** - Mozilla Public License 2.0 (https://www.libreoffice.org/about-us/licenses/).
  Used unmodified as an external, isolated process; not linked into the application.
* **Culmus Hebrew fonts** - GPL-2.0 with font-embedding exception.
* **DejaVu fonts** - Bitstream Vera license / public domain. **Liberation 2**, **Carlito**,
  **Caladea**, **Noto** - SIL Open Font License 1.1.
* **tini** - MIT. **Debian** base image packages - see https://www.debian.org/legal/licenses/.

## Trademarks

ServiceNow is a trademark of ServiceNow, Inc. Qwen is a trademark of Alibaba Cloud.
PowerPoint is a trademark of Microsoft Corporation. ppt2kb is not affiliated with any of them.
