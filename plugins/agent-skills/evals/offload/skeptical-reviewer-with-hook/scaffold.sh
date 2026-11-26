#!/bin/bash
# Tiny Python project with a spec for a ~60-line module spread over two files.
set -e
mkdir -p docs tests
cat > docs/spec.md <<'MD'
# Spec: inventory

- `inventory.py` (new): class `Inventory` with `add(sku, qty)`, `remove(sku, qty)` (raises `ValueError("insufficient stock")` when short), `quantity(sku)` and `low_stock(threshold)` returning the skus under the threshold, sorted.
- `report.py` (new): `render(inventory, threshold=5) -> str`, one line per sku as `<sku>: <qty>` sorted by sku, then a `Low stock:` line listing the skus under the threshold, or `Low stock: none`.
- Both files need docstrings on public functions and input validation (quantities must be positive integers).
MD
cat > tests/test_smoke.py <<'PY'
import unittest

class Smoke(unittest.TestCase):
    def test_nothing(self):
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
PY
