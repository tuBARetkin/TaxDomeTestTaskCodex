# TaxDome Test Task

Minimal Python project with a `src` layout and no runtime dependencies.
Setuptools is the only build dependency; tests use Python's built-in `unittest`.

## Setup

Requires Python 3.13 or newer.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Structure

```text
src/taxdome_test_task/  Application package
tests/                 Unit tests
pyproject.toml         Package metadata and build configuration
```

## Tests

```sh
python -m unittest discover -s tests -v
```

The test directory is initially empty. Add tests as functionality is implemented.
