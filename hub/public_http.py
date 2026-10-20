"""Async HTTP for seller-supplied URLs, pinned to validated public IPs.

Port of agent-tools.cloud ``directory/public_http.py``. Differences: async, and
public IP literals are allowed because Hub sellers legitimately use them.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket

import httpx
import idna

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home", ".lan")


class UnsafeURL(ValueError):
    """A URL can reach something other than a public Internet service."""


def _public(raw: str) -> str:
    try:
        address = ipaddress.ip_address(str(raw).split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeURL("URL host resolved to an invalid address") from exc
    if not address.is_global:
        raise UnsafeURL("URL host resolves to a non-public address")
    return str(address)


def normalize_host(value: str) -> tuple[str, bool]:
    """Return (host, is_ip_literal)."""
    raw = (value or "").strip().strip("[]").rstrip(".").lower()
    try:
        return _public(raw), True
    except UnsafeURL:
        try:
            ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            pass
        else:
            raise
    try:
        host = idna.encode(raw, uts46=True).decode("ascii")
    except (idna.IDNAError, UnicodeError) as exc:
        raise UnsafeURL("URL host is not a valid DNS name") from exc
    if not host or len(host) > 253 or "." not in host:
        raise UnsafeURL("URL host must be a fully-qualified DNS name")
    if any(not _HOST_LABEL.fullmatch(label) for label in host.split(".")):
        raise UnsafeURL("URL host is not a valid DNS name")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURL("local hostnames are not accepted")
    return host, False


def parse_url(url: str) -> tuple[httpx.URL, str, int, bool]:
    try:
        parsed = httpx.URL(str(url))
    except Exception as exc:
        raise UnsafeURL("invalid URL") from exc
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("URL scheme must be http or https")
    if parsed.userinfo:
        raise UnsafeURL("URL credentials are not accepted")
    host, literal = normalize_host(parsed.host)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise UnsafeURL("URL port is invalid")
    return parsed, host, port, literal


def resolve_public(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                                   proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UnsafeURL("URL host does not resolve") from exc
    out: list[str] = []
    for info in infos:
        text = _public(info[4][0])
        if text not in out:
            out.append(text)
    if not out:
        raise UnsafeURL("URL host has no usable public address")
    return out


class PublicAsyncTransport(httpx.AsyncBaseTransport):
    """Resolve once, require every address to be public, connect to that IP."""

    def __init__(self, resolver=None, inner: httpx.AsyncBaseTransport | None = None):
        self._resolver = resolver or resolve_public
        self._inner = inner or httpx.AsyncHTTPTransport(
            trust_env=False, retries=0,
            limits=httpx.Limits(max_keepalive_connections=0))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        parsed, host, port, literal = parse_url(str(request.url))
        if literal:
            address = host
        else:
            addresses = await asyncio.to_thread(self._resolver, host, port)
            address = [_public(a) for a in addresses][0]
        headers = request.headers.copy()
        default_port = 443 if parsed.scheme == "https" else 80
        shown = "[%s]" % host if ":" in host else host
        headers["Host"] = shown if port == default_port else "%s:%d" % (shown, port)
        extensions = dict(request.extensions)
        if parsed.scheme == "https" and not literal:
            extensions["sni_hostname"] = host
        pinned = httpx.Request(request.method, request.url.copy_with(host=address),
                               headers=headers, stream=request.stream,
                               extensions=extensions)
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


def async_client(**kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("transport", PublicAsyncTransport())
    kwargs["follow_redirects"] = False
    return httpx.AsyncClient(**kwargs)
