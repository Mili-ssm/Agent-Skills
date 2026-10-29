#!/bin/bash
# Tiny Python project with an agreed plan whose next task has owned files and acceptance criteria.
set -e
mkdir -p tests docs
cat > cart.py <<'PY'
def total(prices, coupon=None):
    return round(sum(prices), 2)
PY
cat > invoice.py <<'PY'
def line_total(price, quantity):
    return round(price * quantity, 2)
PY
cat > tests/test_cart.py <<'PY'
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from cart import total

class CartTest(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(total([10, 5]), 15)

if __name__ == "__main__":
    unittest.main()
PY
cat > docs/plan.md <<'MD'
# Plan: cart coupons

## Task 1: Sum prices (done)

## Task 2: Coupon rules
- Files: `coupons.py` (new), `cart.py`, `tests/test_coupons.py` (new), `tests/test_cart.py`
- Acceptance:
  - `coupons.py` defines `apply(coupon, prices) -> float` returning the discounted subtotal for three coupons: `SAVE10` (10 % off the subtotal), `FLAT5` (5 off, never below 0), `BOGO` (the cheapest item is free when there are 2 or more items).
  - Unknown coupons raise `ValueError("unknown coupon")`.
  - `total(prices, coupon=None)` applies the coupon through `coupons.apply` and rounds to cents.
  - Unit tests cover each coupon, the floor at 0, BOGO with a single item and the unknown coupon; `python3 -m unittest discover -s tests` passes.
- Constraint: keep the `total(prices, coupon=None)` signature.
MD
