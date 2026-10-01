# Contributing to kilasifen

Thanks for contributing.

## Scope

`kilasifen` is a headless fiscal API for SIFEN Paraguay plus the Python
engine it is built on (`kilasifen.engine`: XSD bindings, XMLDSig signing and
SOAP transport). Contributions should improve:

- correctness against official SIFEN XSD and docs
- API stability for integrators
- test coverage and maintainability

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[sign,transmision,test]"
```

## Required checks before PR

```bash
python -m pytest -q
python -m ruff check kilasifen tests
python -m build
python -m twine check --strict dist/*
```

If a check is not available in your environment, explain it in the PR.

## Project rules

- Do not edit files under `kilasifen/engine/de/bindings/` manually.
- Keep public API changes backward compatible whenever possible.
- Add or update tests for behavioral changes.
- Keep changes focused: one logical change per commit.

## Pull request checklist

- clear problem statement and scope
- tests included or updated
- docs updated if user-facing behavior changed
- no unrelated refactors in the same PR

## Commit style

Use concise, imperative messages, for example:

- `feat: add high-level sifen sdk client`
- `fix: preserve optional soap import and retry config`
- `docs: add executable sdk integration examples`
