# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses semantic versioning principles.

## [Unreleased]

### Added

- `SifenClient` high-level SDK facade for send/query/event flows.
- deterministic schema registry validation helpers.
- polling helpers for lote and async DTE status workflows.
- executable examples under `docs/examples/`.

### Changed

- transport lifecycle now supports `close()` and context manager.
- timeout/retry/session reuse behavior hardened in SOAP transport.
- PKCS12 signer state is reused across repeated signatures.
- CI now validates wheel/sdist artifacts and public API smoke checks.

### Documentation

- regulatory traceability matrix in `docs/normativa/matriz.md`.
- contribution and security process documents.

## [0.1.1] - 2026-04-22

### Added

- stable top-level public API facade.

### Changed

- README normalization and public API documentation updates.
