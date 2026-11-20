"""
Tmpfs Memory Headroom Validation for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §3.6 and PROJECT.md:
- tmpfs mounts count against container memory cgroups.
- Total tmpfs memory (SANDBOX_WORKSPACE_SIZE + SANDBOX_TMP_SIZE) must not exceed 60%
  of SANDBOX_MEM_LIMIT to avoid cgroup OOM kills.
- Shipped defaults (384m + 128m = 512m, exactly 50% of 1g) pass this rule.
- Fails fast naming the variables if headroom is violated.
"""

from __future__ import annotations

import re

from backend.app.domain.errors import HeadroomValidationError

_SIZE_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)$")

_UNIT_MULTIPLIERS: dict[str, int] = {
    "": 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024 * 1024,
    "mb": 1024 * 1024,
    "mib": 1024 * 1024,
    "g": 1024 * 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
    "gib": 1024 * 1024 * 1024,
    "t": 1024 * 1024 * 1024 * 1024,
    "tb": 1024 * 1024 * 1024 * 1024,
    "tib": 1024 * 1024 * 1024 * 1024,
}


def parse_size_bytes(size: str | float) -> int:
    """Parses a human-readable size string or number into bytes."""
    if isinstance(size, (int, float)):
        if size < 0:
            raise HeadroomValidationError(f"Size cannot be negative: {size}")
        return int(size)

    if not isinstance(size, str) or not size.strip():
        raise HeadroomValidationError(f"Invalid size value: '{size}'")

    s = size.strip()
    match = _SIZE_PATTERN.match(s)
    if not match:
        raise HeadroomValidationError(f"Unable to parse size format: '{size}'")

    num_str, unit_str = match.groups()
    try:
        val = float(num_str)
    except ValueError as err:
        raise HeadroomValidationError(f"Invalid numeric value in size: '{size}'") from err

    unit = unit_str.lower()
    if unit not in _UNIT_MULTIPLIERS:
        raise HeadroomValidationError(
            f"Unknown size unit '{unit_str}' in '{size}'. Supported: B, K, M, G, T."
        )

    bytes_val = int(val * _UNIT_MULTIPLIERS[unit])
    if bytes_val < 0:
        raise HeadroomValidationError(f"Size cannot be negative: {size}")

    return bytes_val


def validate_tmpfs_headroom(
    workspace_size: str | int,
    tmp_size: str | int,
    mem_limit: str | int,
    max_ratio: float = 0.60,
) -> None:
    """
    Validates that total tmpfs memory (SANDBOX_WORKSPACE_SIZE + SANDBOX_TMP_SIZE)
    does not exceed max_ratio (default 60%) of SANDBOX_MEM_LIMIT.

    Fails fast naming variables with HeadroomValidationError on violation.
    """
    def _parse_named_size(var_name: str, value: str | float) -> int:
        try:
            return parse_size_bytes(value)
        except HeadroomValidationError as err:
            raise HeadroomValidationError(
                f"Invalid {var_name} size format: '{value}'. {err}"
            ) from err

    ws_bytes = _parse_named_size("SANDBOX_WORKSPACE_SIZE", workspace_size)
    tmp_bytes = _parse_named_size("SANDBOX_TMP_SIZE", tmp_size)
    mem_bytes = _parse_named_size("SANDBOX_MEM_LIMIT", mem_limit)

    if mem_bytes <= 0:
        raise HeadroomValidationError(
            f"SANDBOX_MEM_LIMIT must be greater than zero: '{mem_limit}'"
        )

    total_tmpfs = ws_bytes + tmp_bytes
    max_allowed = max_ratio * mem_bytes

    if total_tmpfs > max_allowed:
        raise HeadroomValidationError(
            f"Tmpfs memory headroom exceeded: SANDBOX_WORKSPACE_SIZE ({workspace_size}) + "
            f"SANDBOX_TMP_SIZE ({tmp_size}) exceeds {max_ratio*100:.0f}% of "
            f"SANDBOX_MEM_LIMIT ({mem_limit})"
        )
