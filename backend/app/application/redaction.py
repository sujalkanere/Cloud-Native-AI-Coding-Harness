"""
Secret Redaction Utility for Cloud-Native AI Coding Harness.

Adheres strictly to Spec §4 and PROJECT.md:
- Sanitizes sensitive keys, tokens, and arbitrary strings from logs, events,
  dicts, and strings, replacing with [REDACTED].
- Handles empty or short (< 3 chars) secrets safely so text isn't inadvertently stripped.
- Provides deep, recursive sanitization of arbitrary nested dicts and data structures.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

REDACTED_SUBSTITUTION = "[REDACTED]"
CIRCULAR_REF_PLACEHOLDER = "<circular-ref>"
MIN_SECRET_LENGTH = 3

_SENSITIVE_KEY_MARKERS = (
    "secret",
    "token",
    "password",
    "credential",
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "access_key",
    "secret_key",
    "private_key",
)


class SecretRedactor:
    """Sanitizes configured secrets and sensitive fields from text, events, and data structures."""

    def __init__(self, secrets: Iterable[str] | None = None) -> None:
        self._secrets: set[str] = set()
        if secrets:
            for s in secrets:
                self.add_secret(s)

    def add_secret(self, secret: str | None) -> None:
        """Adds a secret token to the redactor if it meets the minimum length."""
        if not secret or not isinstance(secret, str):
            return
        cleaned = secret.strip()
        if len(cleaned) < MIN_SECRET_LENGTH:
            return
        self._secrets.add(cleaned)

    def redact(self, text: str) -> str:
        """Replaces all occurrences of configured secrets in text with [REDACTED]."""
        if not text or not isinstance(text, str):
            return text

        result = text
        # Sort secrets by length descending to replace longer tokens first
        for secret in sorted(self._secrets, key=len, reverse=True):
            result = result.replace(secret, REDACTED_SUBSTITUTION)
        return result

    def _redact_sensitive_collection(
        self,
        collection: Any,
        seen: set[int],
    ) -> Any:
        """Recursively sanitizes collections nested directly under a sensitive key."""
        obj_id = id(collection)
        if obj_id in seen:
            return CIRCULAR_REF_PLACEHOLDER

        seen.add(obj_id)
        try:
            if isinstance(collection, list):
                return [self._redact_sensitive_item(item, seen) for item in collection]
            if isinstance(collection, tuple):
                return tuple(self._redact_sensitive_item(item, seen) for item in collection)
            if isinstance(collection, set):
                return {self._redact_sensitive_item(item, seen) for item in collection}
            return self._redact_sensitive_item(collection, seen)
        finally:
            seen.remove(obj_id)

    def _redact_sensitive_item(self, item: Any, seen: set[int]) -> Any:
        """Sanitizes an item inside a sensitive key's collection."""
        if isinstance(item, str):
            return REDACTED_SUBSTITUTION
        if isinstance(item, (list, tuple, set)):
            return self._redact_sensitive_collection(item, seen)
        if isinstance(item, dict):
            return self.redact_dict(item, seen=seen)
        return item

    def redact_data(self, data: Any, seen: set[int] | None = None) -> Any:
        """Recursively redacts secrets and sensitive fields from arbitrary nested structures."""
        if seen is None:
            seen = set()

        if isinstance(data, (dict, list, tuple, set)):
            obj_id = id(data)
            if obj_id in seen:
                return CIRCULAR_REF_PLACEHOLDER

        if isinstance(data, dict):
            return self.redact_dict(data, seen=seen)
        if isinstance(data, list):
            obj_id = id(data)
            seen.add(obj_id)
            try:
                return [self.redact_data(item, seen=seen) for item in data]
            finally:
                seen.remove(obj_id)
        if isinstance(data, tuple):
            obj_id = id(data)
            seen.add(obj_id)
            try:
                return tuple(self.redact_data(item, seen=seen) for item in data)
            finally:
                seen.remove(obj_id)
        if isinstance(data, set):
            obj_id = id(data)
            seen.add(obj_id)
            try:
                return {self.redact_data(item, seen=seen) for item in data}
            finally:
                seen.remove(obj_id)
        if isinstance(data, str):
            return self.redact(data)
        return data

    def redact_dict(
        self,
        data: dict[str, Any],
        seen: set[int] | None = None,
    ) -> dict[str, Any]:
        """
        Recursively sanitizes a dictionary, redacting sensitive key values
        and occurrences of configured secrets in strings.
        """
        if not isinstance(data, dict):
            return data

        if seen is None:
            seen = set()

        obj_id = id(data)
        if obj_id in seen:
            return CIRCULAR_REF_PLACEHOLDER  # type: ignore[return-value]

        seen.add(obj_id)
        try:
            sanitized: dict[str, Any] = {}
            for key, val in data.items():
                str_key = str(key)
                lower_key = str_key.lower()

                # Check if this key name indicates a sensitive credential
                is_sensitive_key = any(marker in lower_key for marker in _SENSITIVE_KEY_MARKERS)

                if is_sensitive_key:
                    if isinstance(val, (list, tuple, set)):
                        sanitized[str_key] = self._redact_sensitive_collection(val, seen)
                    elif isinstance(val, dict):
                        sanitized[str_key] = self.redact_dict(val, seen=seen)
                    else:
                        sanitized[str_key] = REDACTED_SUBSTITUTION
                else:
                    sanitized[str_key] = self.redact_data(val, seen=seen)

            return sanitized
        finally:
            seen.remove(obj_id)
