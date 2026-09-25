from calculator_api import calculate


def test_calculate_dispatches_to_calculator():
    assert calculate("multiply", 3, 4) == 12


def test_calculate_rejects_division_by_zero():
    try:
        calculate("divide", 10, 0)
    except ValueError as error:
        assert str(error) == "Cannot divide by zero"
    else:
        raise AssertionError("division by zero should be rejected")


def test_calculate_rejects_unknown_operation():
    try:
        calculate("power", 2, 3)
    except ValueError as error:
        assert "Unsupported operation" in str(error)
    else:
        raise AssertionError("unknown operations should be rejected")