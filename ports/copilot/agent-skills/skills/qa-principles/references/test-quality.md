# Test quality

FIRST: Fast · Independent · Repeatable · Self-validating · Timely. Structure: Arrange-Act-Assert; one behavior per test; the name states behavior and condition (`test_rejects_expired_token`).

DAMP over DRY in tests: descriptive and readable beats deduplicated, because a failing test must be understood on its own. Share setup through builders/fixtures, not through logic.

## Test doubles (Meszaros, *xUnit Test Patterns*)

| Double | Does | Use for |
|---|---|---|
| Dummy | Fills a parameter | Required args |
| Stub | Returns canned answers | Indirect inputs |
| Spy | Records calls | Indirect outputs, light |
| Mock | Verifies expected interactions | Protocol-critical interactions only |
| Fake | Lightweight working implementation (in-memory DB) | Most I/O boundaries |

Prefer fakes and real objects; mock only what you own, at boundaries. Over-mocking tests the implementation, so refactors break tests without breaking behavior.

## Test smells

| Smell | Symptom | Fix |
|---|---|---|
| Weak assertion | Only "no exception"; `assert result` | Assert the exact observable outcome |
| Eager test | Many behaviors in one test | Split |
| Mystery guest | Hidden file/DB state | Explicit fixture |
| Fragile test | Breaks on refactor without behavior change | Test via the public interface |
| Over-specified mocks | Asserts irrelevant call order/args | Assert outcomes |
| Logic in tests | `if`/loops in the body | Parametrize |
| Sleepy test | `sleep()` waits | Condition waits, injected clock |
| Snapshot abuse | Huge snapshots nobody reviews | Small, focused snapshots |
| Testing internals | Reaching into `_private` | Test behavior; extract if needed |
| Coverage padding | Executes without asserting | Add assertions or delete |

## Review checklist

- Would this test fail if the behavior broke? (mentally mutate the code)
- Does its name say what broke?
- Does failure output show expected vs. actual?
- Deterministic under parallel and random order?
- Fast enough for its size (small: every save; medium/large: every PR)?
