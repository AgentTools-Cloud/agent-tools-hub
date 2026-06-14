"""Transit-link safety for the hub gateway.

Our rule: a seller's own origin security is the seller's problem, but anything
that flows *through* our gateway is ours to keep tight. The biggest risk of a
"give us any URL, we'll proxy it" service is SSRF — someone registering an
internal / cloud-metadata URL and using the hub as a jump host. So we resolve
the upstream host and refuse private, loopback, link-local and reserved
addresses, at registration time and again on every proxied request (DNS can
change between the two).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

# Cloud metadata + obvious internal hostnames we never proxy to.
_BLOCK_HOSTNAMES = {
    "metadata.google.internal", "metadata", "localhost",
    "instance-data", "metadata.azure.com",
}


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> refuse
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
        # cloud metadata service (AWS/GCP/Azure/OpenStack/Alibaba all 169.254.169.254)
        or str(addr) == "169.254.169.254"
    )


def upstream_host_reason(url: str) -> str | None:
    """Return a human reason string if this upstream URL is unsafe to proxy to,
    else None. Resolves the hostname and rejects internal/metadata targets."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "upstream must be http(s)"
    host = (parts.hostname or "").strip().lower()
    if not host:
        return "upstream URL has no host"
    if host in _BLOCK_HOSTNAMES:
        return f"upstream host '{host}' is not allowed"
    # If the host is a literal IP, check it directly.
    try:
        ipaddress.ip_address(host)
        if _ip_is_blocked(host):
            return f"upstream IP '{host}' is private/reserved/metadata — refused"
        return None
    except ValueError:
        pass
    # Hostname: resolve all A/AAAA records, refuse if ANY is internal (defends
    # against a name that resolves to both a public and an internal address).
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"upstream host '{host}' does not resolve"
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            return f"upstream host '{host}' resolves to a private/metadata address — refused"
    return None


def assert_upstream_safe(url: str) -> None:
    """Raise ValueError if the upstream URL is unsafe to proxy to."""
    reason = upstream_host_reason(url)
    if reason:
        raise ValueError(reason)
