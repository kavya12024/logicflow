"""
E-Commerce Shopping Cart Discount & Promotion Engine
Handles item pricing, volume-based discounts, coupon promotions,
shipping thresholds, and final tax computation.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


TAX_RATE = 0.08  # 8% standard sales tax
FREE_SHIPPING_MINIMUM = 50.00
STANDARD_SHIPPING_FEE = 7.99

VALID_COUPONS = {
    "WELCOME10": {"type": "percent", "value": 0.10},
    "SAVE20": {"type": "percent", "value": 0.20},
    "FLAT15": {"type": "fixed", "value": 15.00},
}


@dataclass
class CartItem:
    """Represents a product item in the shopping cart."""
    item_id: str
    name: str
    price: float
    quantity: int
    category: str = "general"


def calculate_item_subtotal(items: List[CartItem]) -> float:
    """Calculate raw subtotal across all cart items."""
    total = 0.0
    for item in items:
        if item.price < 0 or item.quantity < 0:
            raise ValueError("Price and quantity must be non-negative")
        total += item.price * item.quantity
    return round(total, 2)


def calculate_volume_discount(subtotal: float, total_item_count: int) -> float:
    """
    Calculate volume-based rebate based on total item quantity.
    - 5 to 9 items: 5% discount
    - 10+ items: 10% discount
    """
    if total_item_count >= 10:
        return round(subtotal * 0.10, 2)
    elif total_item_count >= 5:
        return round(subtotal * 0.05, 2)
    return 0.0


def calculate_coupon_discount(subtotal: float, coupon_code: Optional[str]) -> float:
    """Compute discount amount from promotional coupon code."""
    if not coupon_code:
        return 0.0
    code = coupon_code.upper().strip()
    if code not in VALID_COUPONS:
        raise ValueError(f"Invalid or expired coupon code: {coupon_code}")
    
    coupon = VALID_COUPONS[code]
    if coupon["type"] == "percent":
        return round(subtotal * coupon["value"], 2)
    elif coupon["type"] == "fixed":
        return round(min(subtotal, coupon["value"]), 2)
    return 0.0


def calculate_cart_total(
    items: List[CartItem],
    coupon_code: Optional[str] = None
) -> Dict[str, float]:
    """
    Calculate full cart pricing breakdown including discounts, taxes, and shipping.
    """
    if not items:
        return {
            "subtotal": 0.0,
            "volume_discount": 0.0,
            "coupon_discount": 0.0,
            "taxable_amount": 0.0,
            "tax": 0.0,
            "shipping": 0.0,
            "final_total": 0.0
        }

    subtotal = calculate_item_subtotal(items)
    total_qty = sum(item.quantity for item in items)

    volume_discount = calculate_volume_discount(subtotal, total_qty)
    coupon_discount = calculate_coupon_discount(subtotal, coupon_code)

    # Pre-tax discounted subtotal
    discounted_subtotal = max(0.0, subtotal - volume_discount - coupon_discount)

    # BUG: Sales tax is mistakenly calculated on the original pre-discount subtotal
    # rather than the post-discount taxable amount!
    # Correct formula: tax = round(discounted_subtotal * TAX_RATE, 2)
    tax = round(subtotal * TAX_RATE, 2)

    shipping = 0.0 if discounted_subtotal >= FREE_SHIPPING_MINIMUM else STANDARD_SHIPPING_FEE
    final_total = round(discounted_subtotal + tax + shipping, 2)

    return {
        "subtotal": subtotal,
        "volume_discount": volume_discount,
        "coupon_discount": coupon_discount,
        "taxable_amount": round(discounted_subtotal, 2),
        "tax": tax,
        "shipping": shipping,
        "final_total": final_total
    }
