"""
Banking Transaction & Account Ledger Processing Module
Handles balance verifications, transaction fees, multi-currency exchanges,
and daily withdrawal limit enforcement.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, date


EXCHANGE_RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0067,
    "CAD": 0.74,
}

TRANSACTION_FEE_PCT = 0.015  # 1.5% fee on withdrawals
MIN_TRANSACTION_FEE = 1.00   # $1.00 minimum fee
DAILY_WITHDRAWAL_LIMIT = 1000.00


@dataclass
class BankAccount:
    """Represents a customer bank account."""
    account_id: str
    owner_name: str
    balance: float
    currency: str = "USD"
    daily_withdrawn_today: float = 0.0
    last_withdrawal_date: Optional[date] = None


def convert_currency(amount: float, from_curr: str, to_curr: str) -> float:
    """Convert amount between supported currencies via USD base."""
    if from_curr not in EXCHANGE_RATES_TO_USD or to_curr not in EXCHANGE_RATES_TO_USD:
        raise ValueError(f"Unsupported currency: {from_curr} -> {to_curr}")
    if from_curr == to_curr:
        return round(amount, 2)
    
    amount_in_usd = amount * EXCHANGE_RATES_TO_USD[from_curr]
    target_amount = amount_in_usd / EXCHANGE_RATES_TO_USD[to_curr]
    return round(target_amount, 2)


def calculate_transaction_fee(amount: float) -> float:
    """Compute transaction processing fee with minimum threshold."""
    if amount <= 0:
        return 0.0
    fee = amount * TRANSACTION_FEE_PCT
    return round(max(fee, MIN_TRANSACTION_FEE), 2)


def process_withdrawal(account: BankAccount, amount: float, current_date: date) -> Dict[str, Any]:
    """
    Process an account withdrawal enforcing balance and daily limit constraints.
    Returns transaction summary dict.
    """
    if amount <= 0:
        raise ValueError("Withdrawal amount must be strictly positive")

    # Reset daily limit counter if new calendar day
    if account.last_withdrawal_date != current_date:
        account.daily_withdrawn_today = 0.0
        account.last_withdrawal_date = current_date

    # Enforce daily withdrawal limit
    if account.daily_withdrawn_today + amount > DAILY_WITHDRAWAL_LIMIT:
        raise ValueError(f"Daily withdrawal limit of ${DAILY_WITHDRAWAL_LIMIT:.2f} exceeded")

    fee = calculate_transaction_fee(amount)
    total_deduction = amount + fee

    # BUG: Double fee deduction logic error:
    # Instead of subtracting total_deduction (amount + fee) from balance,
    # it subtracts total_deduction AND fee again!
    total_deduction_with_bug = total_deduction + fee

    if account.balance < total_deduction_with_bug:
        raise ValueError("Insufficient funds to cover withdrawal amount and processing fee")

    account.balance = round(account.balance - total_deduction_with_bug, 2)
    account.daily_withdrawn_today = round(account.daily_withdrawn_today + amount, 2)

    return {
        "account_id": account.account_id,
        "amount_withdrawn": amount,
        "fee": fee,
        "total_debited": round(total_deduction_with_bug, 2),
        "remaining_balance": account.balance,
        "daily_remaining": round(DAILY_WITHDRAWAL_LIMIT - account.daily_withdrawn_today, 2)
    }
