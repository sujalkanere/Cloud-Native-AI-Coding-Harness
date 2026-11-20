"""
Unit tests for SecretRedactor utility.

Adheres strictly to Spec §4:
- Sanitizes sensitive keys, tokens, and arbitrary strings from logs, events, dicts.
- Handles empty or short (< 3 chars) secrets safely so text isn't inadvertently stripped.
- Preserves structure of nested data without mutating inputs in place.
- Redacts sensitive key names (api_key, token, password, authorization, secret).
"""

from __future__ import annotations

from backend.app.application.redaction import SecretRedactor


def test_redact_tokens_in_string() -> None:
    redactor = SecretRedactor(["sk-ant-api-key-12345", "ghp_githubtoken98765"])
    raw_text = (
        "Using token sk-ant-api-key-12345 to authenticate and ghp_githubtoken98765 to clone."
    )
    redacted = redactor.redact(raw_text)

    assert "sk-ant-api-key-12345" not in redacted
    assert "ghp_githubtoken98765" not in redacted
    assert redacted == "Using token [REDACTED] to authenticate and [REDACTED] to clone."


def test_redact_short_and_empty_secrets_ignored() -> None:
    # Secrets shorter than 3 chars should be safely ignored so text isn't stripped
    redactor = SecretRedactor(["", " ", "a", "12", None])
    raw_text = "The quick brown fox jumps over the lazy dog 12."
    redacted = redactor.redact(raw_text)

    # Text must remain completely unchanged
    assert redacted == raw_text


def test_redact_overlapping_secrets_matches_longest_first() -> None:
    # "secret_token_123" vs "token_123"
    redactor = SecretRedactor(["token_123", "secret_token_123"])
    text = "Authorization: secret_token_123"
    redacted = redactor.redact(text)

    # Longest matched first, not leaving stray "secret_[REDACTED]"
    assert redacted == "Authorization: [REDACTED]"


def test_redact_special_regex_characters_in_secret() -> None:
    secret_with_symbols = "key+with*regex[chars]?"
    redactor = SecretRedactor([secret_with_symbols])
    text = f"My secret is {secret_with_symbols} here"
    redacted = redactor.redact(text)

    assert redacted == "My secret is [REDACTED] here"


def test_redact_dict_sensitive_keys() -> None:
    redactor = SecretRedactor()
    input_dict = {
        "api_key": "my-secret-key-value",
        "user_token": "bearer-token-123",
        "password": "supersecretpassword",
        "authorization": "Bearer xyz-999",
        "username": "alice",
        "status": "active",
    }
    output_dict = redactor.redact_dict(input_dict)

    assert output_dict["api_key"] == "[REDACTED]"
    assert output_dict["user_token"] == "[REDACTED]"
    assert output_dict["password"] == "[REDACTED]"
    assert output_dict["authorization"] == "[REDACTED]"
    assert output_dict["username"] == "alice"
    assert output_dict["status"] == "active"

    # Input dict must not be mutated in-place
    assert input_dict["api_key"] == "my-secret-key-value"


def test_redact_nested_structures() -> None:
    redactor = SecretRedactor(["super_secret_token_456"])
    payload = {
        "event": "llm_call",
        "details": {
            "prompt": "Calling with super_secret_token_456 inside prompt.",
            "auth": {
                "token": "inner-token",
            },
        },
        "messages": [
            {"role": "user", "content": "Here is super_secret_token_456"},
            {"role": "assistant", "content": "I received it."},
        ],
        "tuple_data": ("secret_in_tuple: super_secret_token_456", 123),
        "set_data": {"super_secret_token_456"},
        "count": 42,
    }

    redacted = redactor.redact_data(payload)

    # String occurrences inside nested dicts and lists must be redacted
    assert "super_secret_token_456" not in str(redacted)
    assert redacted["details"]["auth"]["token"] == "[REDACTED]"
    assert redacted["details"]["prompt"] == "Calling with [REDACTED] inside prompt."
    assert redacted["messages"][0]["content"] == "Here is [REDACTED]"
    assert redacted["tuple_data"][0] == "secret_in_tuple: [REDACTED]"
    assert "[REDACTED]" in redacted["set_data"]
    assert redacted["count"] == 42


def test_redact_none_and_non_string_primitives() -> None:
    redactor = SecretRedactor(["secret"])
    assert redactor.redact(None) is None  # type: ignore[arg-type]
    assert redactor.redact("") == ""
    assert redactor.redact_data(12345) == 12345
    assert redactor.redact_data(True) is True


def test_redact_circular_data_structures_does_not_crash() -> None:
    redactor = SecretRedactor(["my_secret"])

    # 1. Circular dict
    circular_dict: dict = {"key": "my_secret"}
    circular_dict["self"] = circular_dict
    res_dict = redactor.redact_data(circular_dict)
    assert res_dict["key"] == "[REDACTED]"
    assert res_dict["self"] == "<circular-ref>"

    # 2. Circular list
    circular_list: list = ["my_secret"]
    circular_list.append(circular_list)
    res_list = redactor.redact_data(circular_list)
    assert res_list[0] == "[REDACTED]"
    assert res_list[1] == "<circular-ref>"

    # 3. Mutual circular reference
    d1: dict = {"name": "d1"}
    d2: dict = {"name": "d2", "ref": d1}
    d1["ref"] = d2
    res_mutual = redactor.redact_data(d1)
    assert res_mutual["name"] == "d1"
    assert res_mutual["ref"]["name"] == "d2"
    assert res_mutual["ref"]["ref"] == "<circular-ref>"


def test_redact_sensitive_key_collections_without_preregistration() -> None:
    redactor = SecretRedactor()  # No pre-registered secret tokens

    data = {
        "api_keys": ["unregistered_key_1", "unregistered_key_2"],
        "tokens": ("unregistered_tok_1", "unregistered_tok_2"),
        "passwords": {"unregistered_pwd_1"},
        "nested_secrets": [["level2_secret_1", "level2_secret_2"]],
        "mixed_credentials": [123, "text_secret", True],
        "normal_field": ["public_1", "public_2"],
    }

    result = redactor.redact_dict(data)

    # Sensitive key lists, tuples, and sets must have their strings redacted
    assert result["api_keys"] == ["[REDACTED]", "[REDACTED]"]
    assert result["tokens"] == ("[REDACTED]", "[REDACTED]")
    assert result["passwords"] == {"[REDACTED]"}
    assert result["nested_secrets"] == [["[REDACTED]", "[REDACTED]"]]
    assert result["mixed_credentials"] == [123, "[REDACTED]", True]

    # Non-sensitive keys must NOT have their values altered
    assert result["normal_field"] == ["public_1", "public_2"]
