"""
SSRF Protection and Repository URL Validation for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §4 and PROJECT.md:
- Rejects non-https repository URLs.
- Resolves hostnames via DNS across all addresses (IPv4 & IPv6).
- Rejects private (RFC 1918), loopback, link-local, multicast, reserved,
  or non-global IP addresses.
- Raises typed SSRFSecurityError from backend.app.domain.errors.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from backend.app.domain.errors import SSRFSecurityError


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks if an IP address falls into any restricted/private range."""
    # Handle IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def validate_repo_url(url: str) -> None:
    """
    Validates a git repository clone URL against SSRF attacks.

    Ensures the scheme is https and that all resolved DNS addresses
    are public, globally routable IPs.
    """
    if not url or not isinstance(url, str):
        raise SSRFSecurityError("Repository URL must be a non-empty string.")

    try:
        parsed = urlparse(url.strip())
    except Exception as err:
        raise SSRFSecurityError(f"Failed to parse repository URL: {err}") from err

    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise SSRFSecurityError(
            f"Invalid URL scheme '{scheme}'. Only 'https' repository URLs are allowed."
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFSecurityError("Repository URL must contain a valid hostname.")

    # Resolve hostname via DNS
    try:
        addr_info = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except (socket.gaierror, socket.herror, OSError) as err:
        raise SSRFSecurityError(
            f"DNS resolution failed for hostname '{hostname}': {err}"
        ) from err

    if not addr_info:
        raise SSRFSecurityError(f"No IP addresses resolved for hostname '{hostname}'.")

    # Validate every resolved IP
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as err:
            raise SSRFSecurityError(
                f"Resolved hostname contains invalid IP '{ip_str}': {err}"
            ) from err

        if _is_disallowed_ip(ip):
            raise SSRFSecurityError(
                f"Repository URL host '{hostname}' resolves to disallowed IP address: {ip_str}"
            )
