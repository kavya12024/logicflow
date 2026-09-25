"""
Unit tests for banking_transaction_processor module.
Verifies currency conversion, fee schedules, balance deductions, and daily limits.
"""

import unittest
from datetime import date
from banking_transaction_processor import (
    BankAccount,
    convert_currency,
    calculate_transaction_fee,
    process_withdrawal,
    DAILY_WITHDRAWAL_LIMIT
)


class TestBankingTransactionProcessor(unittest.TestCase):
    """Test suite for banking transaction processor."""

    def setUp(self):
        self.today = date(2026, 9, 25)
        self.account = BankAccount(
            account_id="ACC-9921",
            owner_name="Jordan Reed",
            balance=5000.00,
            currency="USD"
        )

    def test_fee_minimum_threshold(self):
        """Fee for small withdrawal ($20) should hit the $1.00 minimum."""
        self.assertEqual(calculate_transaction_fee(20.0), 1.00)

    def test_fee_percentage_calculation(self):
        """Fee for $200 withdrawal @ 1.5% should equal $3.00."""
        self.assertEqual(calculate_transaction_fee(200.0), 3.00)

    def test_process_standard_withdrawal(self):
        """
        Withdraw $100 from $5000 balance:
        - Withdrawal: $100.00
        - Fee (1.5%): $1.50
        - Total debit: $101.50
        - Expected remaining balance: $4898.50
        """
        res = process_withdrawal(self.account, 100.0, self.today)
        self.assertEqual(res["amount_withdrawn"], 100.0)
        self.assertEqual(res["fee"], 1.50)
        self.assertEqual(res["total_debited"], 101.50)
        self.assertEqual(res["remaining_balance"], 4898.50)
        self.assertEqual(self.account.balance, 4898.50)

    def test_daily_withdrawal_limit_enforced(self):
        """Total daily withdrawals exceeding $1000 limit must raise ValueError."""
        process_withdrawal(self.account, 800.0, self.today)
        with self.assertRaises(ValueError):
            process_withdrawal(self.account, 300.0, self.today)

    def test_insufficient_funds_rejected(self):
        """Attempting to withdraw more than account balance raises ValueError."""
        poor_account = BankAccount("ACC-000", "Bob", balance=50.0)
        with self.assertRaises(ValueError):
            process_withdrawal(poor_account, 100.0, self.today)


if __name__ == "__main__":
    unittest.main()
