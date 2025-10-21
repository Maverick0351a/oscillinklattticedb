# Security Policy

## Supported versions
Main branch and latest release tags.

## Reporting a vulnerability
Please email security@yourdomain.com with steps to reproduce and affected versions. We aim to acknowledge within 72 hours.

## Scope
This repository and published container images.

## Filesystem safety and CodeQL

This project enables GitHub Advanced Security (CodeQL) and enforces safe filesystem access, especially around retrieval adapters.

### Safe base path for retrieval backends

Retrieval adapters (FAISS flat fallback, hnswlib, bm25 stub) restrict file IO to a safe base directory.

- Configure the base via the `LATTICEDB_DB_ROOT` environment variable.
- When set, all reads/writes must be within this directory; otherwise, adapters return deterministic stub receipts and avoid writing.
- Canonical validation: All adapter IO paths go through a helper that canonicalizes and validates paths against the trusted base (or a narrow dev/test exception below). We do not join user input directly into filesystem operations.
- In dev/test, if `LATTICEDB_DB_ROOT` is not set, we permit only absolute paths strictly under the system temporary directory (e.g., `pytest`'s `tmp_path`). All other locations are rejected. This supports local testing while preventing arbitrary filesystem access. Writes outside the base/temp are blocked.

The API router does not read per-DB configs from user-controlled paths and instead uses configured settings.

### CI guidance

Set `LATTICEDB_DB_ROOT` in CI jobs to the workspace database directory to allow retrieval backends to read/write indices safely.

- Windows PowerShell:
	- `$env:LATTICEDB_DB_ROOT = (Resolve-Path "latticedb").Path`
- Bash:
	- `export LATTICEDB_DB_ROOT="$(pwd)/latticedb"`

These measures address CodeQL `py/path-injection` by validating/constraining paths to a trusted base and avoiding IO otherwise.

## Best practices
Offline by default; metrics protection and JWT are available. See `docs/OPERATIONS.md`.
