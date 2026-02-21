# Testing + CI

Local testing:
- Use Python 3.11 or 3.12.
- Run: `pytest -q`

CI:
- Workflow: `.github/workflows/tests.yml`
- Matrix: Python 3.11 and 3.12
- Installs: `requirements-pi.txt` (no TensorFlow required to run tests)
- Release gate: `pytest` + walk-forward OOS gate must pass before shipping.

Type safety policy (current):
- `mypy src tests` is run as an informational quality signal.
- It is not yet a release-blocking gate due large legacy debt.
- For production release decisions, treat an increase in mypy error count as a regression to investigate.

Known issue:
- Python 3.13 can hang async DB connects; blocked by `main.py` guard and `pyproject.toml` constraint.
