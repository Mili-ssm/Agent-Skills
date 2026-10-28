#!/bin/bash
# Tiny Python project with one failing test, so the run has real output to offload.
set -e
mkdir -p tests
cat > cart.py <<'PY'
def total(prices, discount=0.0):
    subtotal = sum(prices)
    return round(subtotal * (1 - discount), 1)
PY
cat > tests/test_cart.py <<'PY'
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from cart import total

class CartTest(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(total([10, 5]), 15)
    def test_discount_keeps_cents(self):
        self.assertEqual(total([9.99], 0.1), 8.99)

if __name__ == "__main__":
    unittest.main()
PY
