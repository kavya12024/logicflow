"""
Payroll and Benefits Computation Module
Handles hourly wages, overtime calculations, progressive tax brackets,
health insurance deductions, and employee paystub generation.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass


# Standard payroll configuration constants
STANDARD_WORK_WEEK_HOURS = 40.0
OVERTIME_MULTIPLIER = 1.5
MAX_RETIREMENT_MATCH_PCT = 0.06

HEALTH_PLANS = {
    "none": 0.0,
    "individual": 75.0,
    "plus_one": 140.0,
    "family": 220.0,
}


@dataclass
class EmployeeRecord:
    """Represents an employee profile for payroll computation."""
    employee_id: str
    name: str
    hourly_rate: float
    health_tier: str = "individual"
    retirement_pct: float = 0.05


def validate_employee_record(employee: EmployeeRecord) -> bool:
    """Validate that employee parameters meet compliance standards."""
    if not employee.employee_id or not employee.name:
        raise ValueError("Employee ID and name are required")
    if employee.hourly_rate < 15.0:
        raise ValueError("Hourly rate must satisfy minimum wage of $15.00")
    if employee.health_tier not in HEALTH_PLANS:
        raise ValueError(f"Unknown health plan: {employee.health_tier}")
    if not (0.0 <= employee.retirement_pct <= 0.20):
        raise ValueError("Retirement contribution must be between 0% and 20%")
    return True


def calculate_gross_pay(hours_worked: float, hourly_rate: float) -> float:
    if hours_worked < 0 or hourly_rate < 0:
        raise ValueError("Hours and rate must be non-negative")

    if hours_worked <= STANDARD_WORK_WEEK_HOURS:
        return round(hours_worked * hourly_rate, 2)

    regular_pay = STANDARD_WORK_WEEK_HOURS * hourly_rate
    overtime_hours = hours_worked - STANDARD_WORK_WEEK_HOURS

    # Fix: Apply 1.5x overtime multiplier on hours over 40
    overtime_pay = overtime_hours * hourly_rate * OVERTIME_MULTIPLIER

    return round(regular_pay + overtime_pay, 2)


def calculate_tax_deduction(gross_pay: float) -> float:
    if gross_pay <= 0:
        return 0.0
    if gross_pay <= 1000.0:
        return round(gross_pay * 0.10, 2)
    elif gross_pay <= 3000.0:
        return round(100.0 + (gross_pay - 1000.0) * 0.15, 2)
    else:
        return round(400.0 + (gross_pay - 3000.0) * 0.25, 2)


def calculate_health_insurance(tier: str) -> float:
    """Retrieve pre-tax health insurance deduction based on selected tier."""
    if tier not in HEALTH_PLANS:
        raise ValueError(f"Invalid health insurance plan tier: {tier}")
    return HEALTH_PLANS[tier]


def calculate_retirement_contribution(gross_pay: float, percentage: float) -> float:
    """Calculate employee pre-tax retirement deduction."""
    if percentage < 0:
        raise ValueError("Contribution percentage cannot be negative")
    clamped_pct = min(percentage, 0.20)
    return round(gross_pay * clamped_pct, 2)


def generate_paystub(
    employee: EmployeeRecord,
    hours_worked: float
) -> Dict[str, Any]:
    """
    Calculate full payroll breakdown and net pay for an employee.
    """
    validate_employee_record(employee)
    
    gross = calculate_gross_pay(hours_worked, employee.hourly_rate)
    health = calculate_health_insurance(employee.health_tier)
    retirement = calculate_retirement_contribution(gross, employee.retirement_pct)
    
    taxable_income = max(0.0, gross - health - retirement)
    tax = calculate_tax_deduction(taxable_income)
    
    net_pay = round(gross - health - retirement - tax, 2)
    
    return {
        "employee_id": employee.employee_id,
        "name": employee.name,
        "hours_worked": hours_worked,
        "hourly_rate": employee.hourly_rate,
        "gross_pay": gross,
        "tax_deduction": tax,
        "health_deduction": health,
        "retirement_deduction": retirement,
        "total_deductions": round(tax + health + retirement, 2),
        "net_pay": net_pay,
    }


def format_paystub_summary(paystub: Dict[str, Any]) -> str:
    """Format paystub dictionary into a readable text summary."""
    return (
        f"Paystub for {paystub['name']} (ID: {paystub['employee_id']})\n"
        f"Hours: {paystub['hours_worked']} hrs @ ${paystub['hourly_rate']:.2f}/hr\n"
        f"Gross Pay:   ${paystub['gross_pay']:.2f}\n"
        f"Taxes:       ${paystub['tax_deduction']:.2f}\n"
        f"Health:      ${paystub['health_deduction']:.2f}\n"
        f"Retirement:  ${paystub['retirement_deduction']:.2f}\n"
        f"----------------------------------------\n"
        f"Net Pay:     ${paystub['net_pay']:.2f}"
    )