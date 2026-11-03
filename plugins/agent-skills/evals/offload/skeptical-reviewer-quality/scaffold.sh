#!/bin/bash
# A working module with one clear improvable point (dedupe.py scans a list inside a loop where a set fits)
# and a clean file (labels.py) that has nothing worth reworking.
set -e
mkdir -p tests
cat > dedupe.py <<'PY'
def unique_ids(events):
    """Return the event ids in first-seen order, without repeats."""
    seen = []
    result = []
    for event in events:
        event_id = event["id"]
        if event_id not in seen:
            seen.append(event_id)
            result.append(event_id)
    return result
PY
cat > labels.py <<'PY'
def label(name, count):
    """Return "<name>: <count>"."""
    return f"{name}: {count}"
PY
cat > tests/test_dedupe.py <<'PY'
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from dedupe import unique_ids

class DedupeTest(unittest.TestCase):
    def test_order_and_repeats(self):
        events = [{"id": 3}, {"id": 1}, {"id": 3}, {"id": 2}, {"id": 1}]
        self.assertEqual(unique_ids(events), [3, 1, 2])

if __name__ == "__main__":
    unittest.main()
PY
cat > tests/test_labels.py <<'PY'
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from labels import label

class LabelTest(unittest.TestCase):
    def test_label(self):
        self.assertEqual(label("open issues", 4), "open issues: 4")

if __name__ == "__main__":
    unittest.main()
PY
