"""
Unit tests for tmpfs memory headroom validation.

Adheres strictly to Spec §3.6:
- tmpfs mounts count against container memory cgroups.
- Total tmpfs memory (SANDBOX_WORKSPACE_SIZE + SANDBOX_TMP_SIZE) must not exceed 60%
  of SANDBOX_MEM_LIMIT to avoid cgroup OOM kills.
- Shipped defaults (384m + 128m = 512m, exactly 50% of 1g) pass this rule.
- Fails fast naming the variables if headroom is violated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.app.application.headroom import (
    parse_size_bytes,
    validate_tmpfs_headroom,
)
from backend.app.domain.errors import HeadroomValidationError


def test_shipped_defaults_pass_headroom_validation() -> None:
    # 384m + 128m = 512m (50% of 1g, which is <= 60%)
    validate_tmpfs_headroom(
        workspace_size="384m",
        tmp_size="128m",
        mem_limit="1g",
        max_ratio=0.60,
    )


def test_env_example_file_values_pass_headroom_validation() -> None:
    # Find .env.example relative to root
    root_dir = Path(__file__).resolve().parents[3]
    env_file = root_dir / ".env.example"
    assert env_file.exists(), f".env.example not found at {env_file}"

    env_vars: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

    ws_size = env_vars.get("SANDBOX_WORKSPACE_SIZE")
    tmp_size = env_vars.get("SANDBOX_TMP_SIZE")
    mem_limit = env_vars.get("SANDBOX_MEM_LIMIT")

    assert ws_size == "384m"
    assert tmp_size == "128m"
    assert mem_limit == "1g"

    validate_tmpfs_headroom(ws_size, tmp_size, mem_limit)


@pytest.mark.parametrize(
    ("size_input", "expected_bytes"),
    [
        (1024, 1024),
        ("1024", 1024),
        ("512b", 512),
        ("512 bytes", 512),
        ("1k", 1024),
        ("1024K", 1024 * 1024),
        ("384m", 384 * 1024 * 1024),
        ("128M", 128 * 1024 * 1024),
        ("512mb", 512 * 1024 * 1024),
        ("256MiB", 256 * 1024 * 1024),
        ("1g", 1024 * 1024 * 1024),
        ("2GB", 2 * 1024 * 1024 * 1024),
        ("1.5g", int(1.5 * 1024 * 1024 * 1024)),
    ],
)
def test_parse_size_bytes_valid(size_input: str | int, expected_bytes: int) -> None:
    assert parse_size_bytes(size_input) == expected_bytes


@pytest.mark.parametrize(
    "invalid_size",
    [
        "",
        "   ",
        "-100m",
        "invalid",
        "100xyz",
        "12.34.56m",
    ],
)
def test_parse_size_bytes_invalid(invalid_size: str) -> None:
    with pytest.raises(HeadroomValidationError):
        parse_size_bytes(invalid_size)


def test_headroom_boundary_exact_60_percent_passes() -> None:
    # 400m + 200m = 600m of 1000m -> exactly 60.0%
    validate_tmpfs_headroom(
        workspace_size=400 * 1024 * 1024,
        tmp_size=200 * 1024 * 1024,
        mem_limit=1000 * 1024 * 1024,
        max_ratio=0.60,
    )


def test_headroom_exceeding_fails_fast_naming_variables() -> None:
    # 512m + 256m = 768m of 1g -> 75% > 60%
    with pytest.raises(HeadroomValidationError) as exc_info:
        validate_tmpfs_headroom(
            workspace_size="512m",
            tmp_size="256m",
            mem_limit="1g",
            max_ratio=0.60,
        )

    msg = str(exc_info.value)
    # Must name the three key configuration variables and their values
    assert "SANDBOX_WORKSPACE_SIZE (512m)" in msg
    assert "SANDBOX_TMP_SIZE (256m)" in msg
    assert "SANDBOX_MEM_LIMIT (1g)" in msg
    assert "exceeds 60%" in msg


def test_headroom_zero_or_negative_memory_limit_raises() -> None:
    with pytest.raises(HeadroomValidationError, match="greater than zero"):
        validate_tmpfs_headroom("384m", "128m", "0m")


@pytest.mark.parametrize(
    ("ws", "tmp", "mem", "expected_var"),
    [
        ("invalid", "128m", "1g", "SANDBOX_WORKSPACE_SIZE"),
        ("-100m", "128m", "1g", "SANDBOX_WORKSPACE_SIZE"),
        ("12.34.56m", "128m", "1g", "SANDBOX_WORKSPACE_SIZE"),
        ("384m", "bad_unit_999xyz", "1g", "SANDBOX_TMP_SIZE"),
        ("384m", "-50m", "1g", "SANDBOX_TMP_SIZE"),
        ("384m", "128m", "not_a_size", "SANDBOX_MEM_LIMIT"),
        ("384m", "128m", "-1g", "SANDBOX_MEM_LIMIT"),
    ],
)
def test_headroom_invalid_size_format_names_variable(
    ws: str, tmp: str, mem: str, expected_var: str
) -> None:
    with pytest.raises(HeadroomValidationError) as exc_info:
        validate_tmpfs_headroom(workspace_size=ws, tmp_size=tmp, mem_limit=mem)

    assert expected_var in str(exc_info.value)
