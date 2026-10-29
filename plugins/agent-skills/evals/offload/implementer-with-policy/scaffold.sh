#!/bin/bash
# Tiny Python project with an agreed plan whose next task has owned files and acceptance criteria.
set -e
mkdir -p tests docs
cat > cart.py <<'PY'
def total(prices, coupon=None):
    return round(sum(prices), 2)
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

## Task 2: Percentage coupons
- Files: `cart.py`, `tests/test_cart.py`
- Acceptance: `total([10, 10], coupon="SAVE10")` returns `18.0`; `total([10], coupon="BOGUS")` raises `ValueError("unknown coupon")`; `python3 -m unittest discover -s tests` passes.
- Constraint: keep the `total(prices, coupon=None)` signature.
MD
