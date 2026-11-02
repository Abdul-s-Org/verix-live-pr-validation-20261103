# Verix

Verix is a planned local-first tool for identifying coding-agent assumptions that may have become stale as a repository changes. See [the product plan](docs/verix_prd.pdf) and [problem research](docs/verix_prob.pdf).

This repository is an early scaffold: the guard, hooks, and benchmark are not implemented yet. Verix is not a security boundary or proof of code correctness.

## Development

Python 3.12 or newer is required.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
verix --help
python -m pytest
```

The CLI help can also be checked without installing dependencies: `PYTHONPATH=src python3 -m verix --help`.

## Layout

- `src/verix/`: Python package and CLI; `engine/` and `hooks/` are reserved for the local guard.
- `tests/fixtures/`: test fixtures.
- `benchmark/scenarios/`: benchmark scenarios and their ground-truth labels.
- `docs/`: product and research documents.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance and [SECURITY.md](SECURITY.md) for security reporting.
