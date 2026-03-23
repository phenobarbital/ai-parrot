# calculator/operations/statistics.py
"""Statistical operations."""
import math
from typing import List
from . import operation


@operation(name="mean", description="Calculate arithmetic mean")
def calculate_mean(values: List[float], **kwargs) -> float:
    """Calculate the arithmetic mean of a list of values."""
    if not values:
        raise ValueError("Cannot calculate mean of empty list")
    return sum(values) / len(values)


@operation(name="std", description="Calculate standard deviation")
def calculate_std(values: List[float], sample: bool = True, **kwargs) -> float:
    """
    Calculate standard deviation.

    Args:
        values: List of numerical values
        sample: If True, use sample std (n-1), else population std (n)
    """
    if not values:
        raise ValueError("Cannot calculate std of empty list")

    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values)

    divisor = len(values) - 1 if sample else len(values)
    if divisor == 0:
        raise ValueError("Need at least 2 values for sample standard deviation")

    return math.sqrt(variance / divisor)


@operation(name="median")
def calculate_median(values: List[float], **kwargs) -> float:
    """Calculate median value."""
    if not values:
        raise ValueError("Cannot calculate median of empty list")

    sorted_values = sorted(values)
    n = len(sorted_values)

    if n % 2 == 0:
        return (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
    else:
        return sorted_values[n//2]


@operation(name="correlation")
def calculate_correlation(values: List[float], **kwargs) -> float:
    """
    Calculate Pearson correlation coefficient.
    Expects values to be alternating [x1, y1, x2, y2, ...]
    """
    if len(values) < 4 or len(values) % 2 != 0:
        raise ValueError("Need at least 2 pairs of values for correlation")

    x_values = values[::2]
    y_values = values[1::2]

    n = len(x_values)
    mean_x = sum(x_values) / n
    mean_y = sum(y_values) / n

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denominator_x = math.sqrt(sum((x - mean_x) ** 2 for x in x_values))
    denominator_y = math.sqrt(sum((y - mean_y) ** 2 for y in y_values))

    if denominator_x == 0 or denominator_y == 0:
        raise ValueError("Standard deviation is zero, cannot calculate correlation")

    return numerator / (denominator_x * denominator_y)
