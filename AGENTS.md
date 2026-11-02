# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains planning documents, not an application. `docs/verix_prob.pdf` describes the problem and validation strategy; `docs/verix_prd.pdf` contains the product requirements and proposed build plan. Read both before proposing implementation changes, and keep new documentation in `docs/` with descriptive, lowercase filenames.

The PRD proposes a local-first Python engine and CLI, with deterministic rules deciding outcomes and an LLM restricted to extraction and explanation. Treat the proposed stack and targets as plans to validate, not as existing functionality. Preserve the distinction between verified evidence, inference, and hypotheses when updating product documentation.

## Build, Test, and Development Commands

No build system, dependency manifest, or application commands are present yet. To inspect the current documents locally, use:

```sh
pdftotext -layout docs/verix_prd.pdf - | less
pdftotext -layout docs/verix_prob.pdf - | less
```

When adding runnable code, document its setup, development, build, and test commands alongside the implementation. Avoid introducing hosted services as a prerequisite for local development without an explicit product decision.

## Coding Style & Naming Conventions

No code formatter, linter, or language-specific conventions are configured. Follow the conventions of any existing module you extend; introduce formatting and linting configuration with the first implementation rather than assuming a style. Name files and tests for the behavior they contain, and keep changes focused on the stated requirements.

## Testing Guidelines

There is no test framework or coverage requirement yet. New behavior should include automated tests, particularly for deterministic decisions and stale-assumption scenarios. The PRD calls for a benchmark before the local engine; document how to run it and report results once it exists. Do not present the PRD's recall or false-block targets as measured results.

## Commit & Pull Request Guidelines

No Git history is available here to establish a commit convention. Use concise, imperative commit subjects that describe the change. Pull requests should explain the problem and solution, link relevant issues or requirements, and list checks performed; include screenshots when a change affects a user interface.
