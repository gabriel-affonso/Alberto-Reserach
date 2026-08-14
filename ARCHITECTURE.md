# Architecture

Alberto is organized as a small deterministic core plus agent-facing contracts.

## Modules

- `main`: existing user-facing OpenClaw orchestrator. It routes research work to `alberto-research` and avoids direct handling of untrusted documents. Production deployment preserves its existing workspace, credentials, sessions and model.
- `alberto-research`: owns project configuration, discovery, screening, readings, synthesis, citation chasing, digest generation, feedback and Zotero sync.
- `research-reader`: isolated reader contract for hostile external text. It receives only the document payload and project question required for a reading task.

Future modules, including Alberto Finance, should be isolated in separate OpenClaw workspaces and SQLite namespaces or databases. Research Reader must not be granted access to finance data or credentials.

## Deterministic Core

Python handles deterministic responsibilities:

- API access and retries.
- Metadata normalization.
- DOI and external ID deduplication.
- SQLite migrations and repositories.
- Project YAML validation.
- Run state and structured logs.
- Digest persistence and local delivery.
- Zotero API adapter.

LLM/Codex agents handle semantic work behind validated schemas:

- Relevance and priority judgments.
- Structured paper analysis.
- Argument and methodology extraction.
- Contradiction and relationship detection.
- Citation-following decisions.
- Digest editorial ranking.

## Storage

SQLite is Alberto's operational state. Zotero is treated as a human research library, not the source of operational truth.

The database tracks papers, authors, searches, discoveries, screenings, documents, readings, citations, relationships, digests, feedback and runs. Paper access is explicit: `FULL_TEXT`, `PARTIAL_TEXT`, `ABSTRACT_ONLY` or `METADATA_ONLY`.

## OpenClaw

OpenClaw templates live in `openclaw/`. The installer verifies the installed OpenClaw CLI before attempting to copy or register production configuration. When OpenClaw is absent, the installer leaves the templates in place and reports the skipped steps.
