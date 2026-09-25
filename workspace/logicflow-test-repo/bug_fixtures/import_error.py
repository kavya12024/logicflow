"""Intentional import-error fixture for the LogicFlow repair workflow."""

from missing_calculator_dependency import format_currency


def display_total(value):
    return format_currency(value)