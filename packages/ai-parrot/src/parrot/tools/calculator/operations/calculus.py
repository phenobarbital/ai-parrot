# calculator/operations/calculus.py
"""Calculus operations."""
from typing import Callable, List
from . import operation


@operation(name="derivative")
def numerical_derivative(
    expression: str = None,
    x: float = None,
    h: float = 1e-5,
    **kwargs
) -> float:
    """
    Calculate numerical derivative using central difference.

    Args:
        expression: Python expression as string (e.g., "x**2 + 3*x")
        x: Point at which to evaluate derivative
        h: Step size for numerical differentiation
    """
    if expression is None or x is None:
        raise ValueError("Need both expression and x value")

    # Compile expression for evaluation
    # This uses Python's eval - in production, consider safer alternatives
    import numpy as np

    def f(val):
        # Make common functions available
        from math import sin, cos, tan, exp, log, sqrt, pi, e
        return eval(expression, {"x": val, "np": np, "__builtins__": {}},
                   {"sin": sin, "cos": cos, "tan": tan, "exp": exp,
                    "log": log, "sqrt": sqrt, "pi": pi, "e": e})

    # Central difference: f'(x) ≈ (f(x+h) - f(x-h)) / (2h)
    return (f(x + h) - f(x - h)) / (2 * h)


@operation(name="integrate")
def numerical_integral(
    expression: str = None,
    a: float = None,
    b: float = None,
    n: int = 1000,
    **kwargs
) -> float:
    """
    Calculate numerical integral using Simpson's rule.

    Args:
        expression: Python expression as string
        a: Lower bound
        b: Upper bound
        n: Number of intervals (must be even)
    """
    if any(v is None for v in [expression, a, b]):
        raise ValueError("Need expression, a, and b")

    if n % 2 != 0:
        n += 1

    from math import sin, cos, tan, exp, log, sqrt, pi, e

    def f(val):
        return eval(expression, {"x": val, "__builtins__": {}},
                   {"sin": sin, "cos": cos, "tan": tan, "exp": exp,
                    "log": log, "sqrt": sqrt, "pi": pi, "e": e})

    h = (b - a) / n
    result = f(a) + f(b)

    for i in range(1, n):
        x = a + i * h
        if i % 2 == 0:
            result += 2 * f(x)
        else:
            result += 4 * f(x)

    return result * h / 3
