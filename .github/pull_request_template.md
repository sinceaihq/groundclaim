## What and why

## Checks

- [ ] `pytest`, `ruff check .`, `ruff format --check .` and `mypy` pass
- [ ] New verdict rules come with a test in `tests/test_verify.py` and are described in `docs/RULES.md`
- [ ] If benchmark numbers change, `docs/BENCHMARK.md` is updated (the frozen test results are never re-tuned)
- [ ] No secrets, private code or personal data in tests, fixtures or traces
