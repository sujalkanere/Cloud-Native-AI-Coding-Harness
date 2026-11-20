"""Calculator module providing basic arithmetic operations.

Contains an intentional bug in divide() for AI coding harness E2E testing.
"""


def add(a: float | int, b: float | int) -> float | int:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: float | int, b: float | int) -> float | int:
    """Return the difference of two numbers."""
    return a - b


def multiply(a: float | int, b: float | int) -> float | int:
    """Return the product of two numbers."""
    return a * b


def divide(a: float | int, b: float | int) -> float:
    """Return the quotient of two numbers.

    Raises:
        ValueError: If division by zero is attempted.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a // b  # BUG: integer floor division used instead of float division


def power(base: float | int, exponent: float | int) -> float | int:
    """Return base raised to the given exponent."""
    return base ** exponent


def factorial(n: int) -> int:
    """Return the factorial of a non-negative integer.

    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    if n in (0, 1):
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
