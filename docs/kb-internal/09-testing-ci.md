# Testing + CI

Local testing:
- Use Python 3.11 or 3.12.
- Run: `pytest -q`

CI:
- Workflow: `.github/workflows/tests.yml`
- Matrix: Python 3.11 and 3.12
- Installs: `requirements-pi.txt` (no TensorFlow required to run tests)

Known issue:
- Python 3.13 can hang async DB connects; blocked by `main.py` guard and `pyproject.toml` constraint.

