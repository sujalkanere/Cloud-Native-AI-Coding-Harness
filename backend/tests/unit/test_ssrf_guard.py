"""
Unit tests for SSRF Guard and URL validation.

Adheres strictly to Spec §4:
- Rejects non-https URLs (http, ssh, file, etc.).
- Rejects loopback addresses (127.0.0.1, localhost, ::1).
- Rejects RFC 1918 private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16).
- Rejects link-local metadata addresses (169.254.169.254, fe80::/10).
- Rejects multicast, reserved, and IPv4-mapped IPv6 private addresses.
- Handles DNS resolution failures gracefully.
- Accepts valid public https repository URLs.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from backend.app.application.ssrf import validate_repo_url
from backend.app.domain.errors import SSRFSecurityError


@pytest.mark.parametrize(
    "invalid_scheme_url",
    [
        "http://github.com/repo/sample.git",
        "file:///etc/passwd",
        "ssh://git@github.com/repo/sample.git",
        "ftp://example.com/repo.git",
        "git://github.com/repo/sample.git",
        "javascript:alert(1)",
        "",
    ],
)
def test_rejects_non_https_schemes(invalid_scheme_url: str) -> None:
    with pytest.raises(SSRFSecurityError):
        validate_repo_url(invalid_scheme_url)


def test_rejects_missing_hostname() -> None:
    with pytest.raises(SSRFSecurityError, match="must contain a valid hostname"):
        validate_repo_url("https://")


@pytest.mark.parametrize(
    "direct_private_url",
    [
        "https://127.0.0.1/repo.git",
        "https://127.0.0.254/repo.git",
        "https://10.0.0.1/repo.git",
        "https://10.255.255.255/repo.git",
        "https://172.16.0.1/repo.git",
        "https://172.31.255.255/repo.git",
        "https://192.168.0.1/repo.git",
        "https://192.168.255.255/repo.git",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/repo.git",
        "https://[fe80::1]/repo.git",
        "https://[::ffff:127.0.0.1]/repo.git",
        "https://[::ffff:169.254.169.254]/repo.git",
        "https://[::ffff:10.0.0.1]/repo.git",
    ],
)
def test_rejects_direct_private_and_loopback_ips(direct_private_url: str) -> None:
    with pytest.raises(SSRFSecurityError, match="disallowed"):
        validate_repo_url(direct_private_url)


def test_rejects_dns_resolving_to_private_ip() -> None:
    # Simulate a domain that resolves to an internal RFC 1918 IP
    fake_dns_result = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.50.1.10", 0))
    ]
    with (
        patch("socket.getaddrinfo", return_value=fake_dns_result),
        pytest.raises(SSRFSecurityError, match="disallowed IP address"),
    ):
        validate_repo_url("https://internal-git.company.corp/repo.git")


def test_rejects_dns_resolving_to_cloud_metadata_ip() -> None:
    fake_dns_result = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))
    ]
    with (
        patch("socket.getaddrinfo", return_value=fake_dns_result),
        pytest.raises(SSRFSecurityError, match="disallowed IP address"),
    ):
        validate_repo_url("https://cloud-metadata.attacker.com/repo.git")


def test_rejects_dns_resolving_to_ipv6_loopback() -> None:
    fake_dns_result = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))
    ]
    with (
        patch("socket.getaddrinfo", return_value=fake_dns_result),
        pytest.raises(SSRFSecurityError, match="disallowed IP address"),
    ):
        validate_repo_url("https://ipv6-loopback.example.com/repo.git")


def test_rejects_dns_with_dual_stack_containing_one_private_ip() -> None:
    # If one IP in multi-A/AAAA records is private, fail fast
    fake_dns_result = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.5", 0)),
    ]
    with (
        patch("socket.getaddrinfo", return_value=fake_dns_result),
        pytest.raises(SSRFSecurityError, match="disallowed IP address"),
    ):
        validate_repo_url("https://mixed-resolution.example.com/repo.git")


def test_rejects_dns_resolution_failure() -> None:
    with (
        patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
        ),
        pytest.raises(SSRFSecurityError, match="DNS resolution failed"),
    ):
        validate_repo_url("https://non-existent-domain-12345.org/repo.git")


def test_accepts_valid_public_https_url() -> None:
    fake_dns_result = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.121.4", 0))
    ]
    with patch("socket.getaddrinfo", return_value=fake_dns_result):
        # Should not raise
        validate_repo_url("https://github.com/my-org/my-repo.git")
