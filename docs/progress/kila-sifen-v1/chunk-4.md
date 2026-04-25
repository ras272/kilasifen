# Chunk 4

## Purpose

Start the core document lifecycle:

- documents
- jobs
- idempotent creation

## Why it exists

This is the first chunk that models the real async fiscal workflow. Before talking to SIFEN, the platform needs a durable way to:

- accept a business document
- create one logical record for it
- attach a processing job
- return the same result on idempotent retries

## Closed tasks

- `Task 8` commit `5accd84`
- `Task 9` commit `7232dee`
- `Task 10` commit `0914799`

## Main files

- `kilasifen/domain/documents/models.py`
- `kilasifen/domain/jobs/models.py`
- `kilasifen/repositories/documents.py`
- `kilasifen/repositories/jobs.py`
- `kilasifen/infrastructure/db/repositories/documents.py`
- `kilasifen/infrastructure/db/repositories/jobs.py`
- `kilasifen/application/documents/service.py`
- `kilasifen/application/jobs/service.py`
- `kilasifen/api/routers/documents.py`
- `kilasifen/api/routers/jobs.py`
- `kilasifen/infrastructure/jobs/queue.py`
- `kilasifen/infrastructure/jobs/workers.py`
- `kilasifen/infrastructure/sifen/engine.py`
- `kilasifen/infrastructure/sifen/mapper.py`
