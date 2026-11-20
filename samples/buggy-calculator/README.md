# Buggy Calculator Sample

This is a sample Python repository used for end-to-end (E2E) verification of the Cloud-Native AI Coding Harness.

## Overview
- **Runtime**: Python 3.12 (standard library only) + `pytest`
- **Isolation**: Tested in an isolated Docker container with `network=none` (no pip installs permitted).

## Intentional Bug
In `calculator.py`, the `divide(a, b)` function erroneously uses integer floor division:
```python
return a // b
```
instead of true floating-point division:
```python
return a / b
```

This bug causes fractional divisions (e.g. `divide(7, 2)` or `divide(1, 4)`) to truncate to integer values (`3` and `0` respectively), which is exposed by `test_calculator.py`.

## Running Tests
To observe the bug failure:
```bash
pytest test_calculator.py
```
Expected output: 1 failure (`test_divide`: `assert 3 == 3.5`), 7 passing tests.

After fixing `calculator.py` by replacing `//` with `/`, all 8 tests pass with exit code 0.
