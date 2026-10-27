# Test quality

## FIRST

Fast · Independent · Repeatable · Self-validating (pass/fail, no manual inspection) · Timely.

## Structure

Arrange-Act-Assert (Given-When-Then). One behavior per test; name states behavior and condition: `test_rejects_expired_token`, `withdraw_fails_when_balance_insufficient`.

## Test doubles (Meszaros, *xUnit Test Patterns*)

| Double | Does | Use for |
|---|---|---|
| Dummy | Fills a parameter, unused | Required args |
| Stub | Returns canned answers | Indirect inputs |
| Spy | Records calls for later assertion | Indirect outputs, light |
| Mock | Pre-programmed expectations, verifies interaction | Protocol-critical interactions only |
| Fake | Working lightweight implementation (in-memory DB) | Most I/O boundaries |

Prefer fakes and real objects; mock only what you own at boundaries ("don't mock what you don't own"). Over-mocking tests implementation, not behavior.

## Test smells

| Smell | Symptom | Fix |
|---|---|---|
| Assertion-free / weak assert | Only "no exception"; `assert result` | Assert exact observable outcome |
| Eager test | One test checks many behaviors | Split |
| Mystery guest | Depends on hidden file/DB state | Inline or explicit fixture |
| Fragile test | Breaks on refactor without behavior change | Test via public interface |
| Over-specified mocks | Asserts call order/args irrelevant to behavior | Assert outcomes |
| Conditional logic in tests | `if`/loops in test body | Parametrize |
| Sleepy test | `sleep()` waits | Condition waits, injected clock |
| Test code duplication | Copy-paste setup | Fixtures/builders (Test Data Builder, Object Mother) |
| Snapshot abuse | Huge snapshots nobody reviews | Small, focused snapshots |
| Testing private internals | Reaching into `_private` | Test behavior; extract if needed |
| Coverage padding | Tests that execute without asserting | Delete or add assertions |

## Review checklist

- Would this test fail if the behavior broke? (mentally mutate the code)
- Does the name tell what broke when it fails?
- Is failure output diagnostic (expected vs. actual)?
- Deterministic under parallel and random order?
- Fast enough to run on every save (unit) / every PR (integration/E2E)?
