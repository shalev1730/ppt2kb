"""
Outbound network policy.

The application may contact only explicitly configured internal services.
Every HTTP client the application creates goes through :func:`make_client`,
which:

  * refuses any request whose host is not in the allow-list
    (``PPT2KB_ALLOWED_OUTBOUND_HOSTS`` plus the hosts of the configured
    Qwen/ServiceNow URLs);
  * ignores proxy environment variables (``trust_env=False``), so a stray
    ``HTTPS_PROXY`` can never route internal traffic elsewhere;
  * applies the configured CA bundle / client certificate;
  * keeps TLS verification on unless explicitly disabled by configuration
    (which is logged loudly and documented as unsupported for production).
"""
from __future__ import annotations

import logging
import ssl
from typing import Iterable, Optional

import httpx

from ..config import host_of

logger = logging.getLogger(__name__)


class OutboundBlocked(httpx.TransportError):
    pass


class AllowListTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport, allowed: Iterable[str]):
        self._inner = inner
        self._allowed = {h.lower() for h in allowed}

    def _check(self, request: httpx.Request) -> None:
        url = request.url
        host = url.host.lower() if url.host else ""
        port = url.port
        candidates = {host}
        if port:
            candidates.add(f"{host}:{port}")
        else:
            default = 443 if url.scheme == "https" else 80
            candidates.add(f"{host}:{default}")
        if not (candidates & self._allowed):
            logger.warning("Blocked outbound request to non-allow-listed host %s", host)
            raise OutboundBlocked(f"Outbound host '{host}' is not allow-listed")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._check(request)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def build_ssl_context(ca_bundle: Optional[str], verify: bool, client_cert: Optional[str], client_key: Optional[str]) -> ssl.SSLContext | bool:
    if not verify:
        logger.critical("TLS certificate verification is DISABLED (PPT2KB_TLS_VERIFY=false). Not acceptable for production.")
        return False
    ctx = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if client_cert:
        ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)
    return ctx


def make_client(
    *,
    allowed_hosts: Iterable[str],
    timeout_s: float,
    ca_bundle: Optional[str] = None,
    verify: bool = True,
    client_cert: Optional[str] = None,
    client_key: Optional[str] = None,
    base_url: str = "",
    headers: Optional[dict] = None,
    extra_allowed: Iterable[str] = (),
) -> httpx.Client:
    allowed = set(allowed_hosts) | set(extra_allowed)
    if base_url:
        h = host_of(base_url)
        if h:
            allowed.add(h)
    ssl_ctx = build_ssl_context(ca_bundle, verify, client_cert, client_key)
    inner = httpx.HTTPTransport(verify=ssl_ctx, retries=0)
    transport = AllowListTransport(inner, allowed)
    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout_s, connect=min(30.0, timeout_s)),
        trust_env=False,
        follow_redirects=False,
        base_url=base_url or "",
        headers=headers or {},
    )
