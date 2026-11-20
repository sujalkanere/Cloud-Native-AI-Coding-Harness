"""Unit tests for the calculator module."""

import pytest
from calculator import add, divide, factorial, multiply, power, subtract


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(-5, -7) == -12
    assert add(1.5, 2.5) == 4.0


def test_subtract():
    assert subtract(10, 4) == 6
    assert subtract(4, 10) == -6
    assert subtract(0, 0) == 0
    assert subtract(2.5, 1.0) == 1.5


def test_multiply():
    assert multiply(3, 4) == 12
    assert multiply(-2, 5) == -10
    assert multiply(0, 100) == 0
    assert multiply(2.5, 2) == 5.0


def test_divide():
    assert divide(10, 2) == 5.0
    assert divide(7, 2) == 3.5
    assert divide(1, 4) == 0.25
    assert divide(-9, 3) == -3.0


def test_divide_by_zero():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(10, 0)


def test_power():
    assert power(2, 3) == 8
    assert power(5, 0) == 1
    assert power(2, -1) == 0.5


def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120
    assert factorial(6) == 720


def test_factorial_negative():
    with pytest.raises(ValueError, match="Factorial is not defined for negative numbers"):
        factorial(-1)
