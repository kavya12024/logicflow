"""
Unit tests for ecommerce_discount_engine module.
Verifies subtotals, volume tiers, coupon deductions, sales taxes, and free shipping.
"""

import unittest
from ecommerce_discount_engine import (
    CartItem,
    calculate_item_subtotal,
    calculate_volume_discount,
    calculate_coupon_discount,
    calculate_cart_total,
    TAX_RATE
)


class TestEcommerceDiscountEngine(unittest.TestCase):
    """Test suite for validating shopping cart discount calculations."""

    def test_basic_subtotal(self):
        """Test calculation of raw cart subtotal."""
        items = [
            CartItem("ITM-1", "Coffee Beans", 15.00, 2),
            CartItem("ITM-2", "Mug", 10.00, 1),
        ]
        self.assertEqual(calculate_item_subtotal(items), 40.00)

    def test_volume_discount_tiers(self):
        """Test 5% and 10% volume discount brackets."""
        self.assertEqual(calculate_volume_discount(100.0, 3), 0.0)
        self.assertEqual(calculate_volume_discount(100.0, 6), 5.00)
        self.assertEqual(calculate_volume_discount(100.0, 12), 10.00)

    def test_coupon_discount_calculation(self):
        """Test percentage and fixed coupon redemptions."""
        self.assertEqual(calculate_coupon_discount(100.0, "WELCOME10"), 10.00)
        self.assertEqual(calculate_coupon_discount(100.0, "SAVE20"), 20.00)
        self.assertEqual(calculate_coupon_discount(100.0, "FLAT15"), 15.00)

    def test_cart_total_tax_on_discounted_amount(self):
        """
        Cart total with SAVE20 (20% off):
        - Subtotal: $100.00 (2 items @ $50.00)
        - Coupon discount: $20.00
        - Discounted taxable amount: $80.00
        - Tax (8% of $80.00): $6.40  <-- (Bug calculates 8% on $100 = $8.00)
        - Shipping: Free ($80.00 >= $50.00) = $0.00
        - Expected final total: $86.40
        """
        items = [CartItem("ITM-01", "Keyboard", 50.00, 2)]
        breakdown = calculate_cart_total(items, coupon_code="SAVE20")

        self.assertEqual(breakdown["subtotal"], 100.00)
        self.assertEqual(breakdown["coupon_discount"], 20.00)
        self.assertEqual(breakdown["taxable_amount"], 80.00)
        self.assertEqual(breakdown["tax"], 6.40)
        self.assertEqual(breakdown["shipping"], 0.0)
        self.assertEqual(breakdown["final_total"], 86.40)


if __name__ == "__main__":
    unittest.main()
