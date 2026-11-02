# Contributing

Read the product plan in `docs/` before proposing changes. The project is at the scaffold stage; prioritize the benchmark and deterministic local engine described in the plan.

## Development

Use Python 3.12 or newer. Set up a virtual environment and install the development dependencies as described in [README.md](README.md). Run `python -m pytest` before submitting a change. Add tests for new behavior, including edge cases and regressions where applicable.

Keep changes focused and explain the problem, approach, and checks performed in the pull request. Link a relevant issue or product requirement when available. Never commit credentials, private source code, or real session data as fixtures.
