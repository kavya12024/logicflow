"""
Unit tests for payroll_calculator module.
Verifies wage calculations, overtime rules, progressive taxes, and paystub assembly.
"""

import unittest
from payroll_calculator import (
    EmployeeRecord,
    calculate_gross_pay,
    calculate_tax_deduction,
    calculate_health_insurance,
    calculate_retirement_contribution,
    generate_paystub,
    validate_employee_record
)


class TestPayrollCalculator(unittest.TestCase):
    """Test suite for validating payroll and deduction logic."""

    def test_regular_gross_pay(self):
        """Test pay calculation for standard 40 or fewer hours."""
        self.assertEqual(calculate_gross_pay(40.0, 25.0), 1000.0)
        self.assertEqual(calculate_gross_pay(20.0, 30.0), 600.0)

    def test_overtime_gross_pay(self):
        """
        Test that hours over 40 receive 1.5x overtime rate.
        45 hours at $20/hr:
        - 40 hours @ $20 = $800
        - 5 hours @ $20 * 1.5 ($30) = $150
        - Total expected: $950.00
        """
        self.assertEqual(calculate_gross_pay(45.0, 20.0), 950.0)

    def test_tax_bracket_tier1(self):
        """Test income under $1,000 taxed at 10%."""
        self.assertEqual(calculate_tax_deduction(800.0), 80.0)

    def test_tax_bracket_tier2(self):
        """Test income between $1,000 and $3,000."""
        # 100 + (2000 - 1000) * 0.15 = 100 + 150 = 250
        self.assertEqual(calculate_tax_deduction(2000.0), 250.0)

    def test_health_insurance_tiers(self):
        """Test health insurance deduction amounts."""
        self.assertEqual(calculate_health_insurance("individual"), 75.0)
        self.assertEqual(calculate_health_insurance("family"), 220.0)

    def test_complete_paystub_generation(self):
        """Test end-to-end paystub net pay calculation."""
        emp = EmployeeRecord(
            employee_id="EMP-101",
            name="Alice Smith",
            hourly_rate=25.0,
            health_tier="individual",
            retirement_pct=0.05
        )
        paystub = generate_paystub(emp, hours_worked=40.0)
        self.assertEqual(paystub["gross_pay"], 1000.0)
        self.assertEqual(paystub["health_deduction"], 75.0)
        self.assertEqual(paystub["retirement_deduction"], 50.0)
        # Taxable: 1000 - 75 - 50 = 875 -> 10% = 87.50
        self.assertEqual(paystub["tax_deduction"], 87.50)
        # Net: 1000 - 75 - 50 - 87.50 = 787.50
        self.assertEqual(paystub["net_pay"], 787.50)


if __name__ == "__main__":
    unittest.main()
