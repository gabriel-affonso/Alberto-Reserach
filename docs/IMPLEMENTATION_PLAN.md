# Implementation Plan

Status legend: `complete`, `in-progress`, `pending`, `blocked`.

## M0 - Repository Foundation

Status: complete

Acceptance criteria:

- Required directories exist.
- Repository-level instructions, README, architecture, deployment and security docs exist.
- Example project config exists.
- Python package metadata exists.

Completion note: repository scaffold, docs and package metadata were created.

## M1 - SQLite Storage

Status: complete

Acceptance criteria:

- Migrations create projects, papers, authors, paper_authors, searches, discoveries, screenings, documents, readings, citations, relationships, digests, digest_items, feedback and runs.
- Migration application is idempotent.
- Repository methods cover core create/read/update paths.

Completion note: `migrations/001_initial.sql` and repository tests cover the V1 storage surface.

## M2 - Project Configuration

Status: complete

Acceptance criteria:

- Version-controlled YAML project configs validate required fields.
- Example project loads successfully.
- Thresholds, limits, citation chasing, digest and timezone settings are represented.

Completion note: `projects/example-research.yaml` validates in smoke tests.

## M3 - Discovery Providers

Status: complete

Acceptance criteria:

- Provider abstraction supports Crossref and Semantic Scholar.
- Providers implement retries, timeouts, rate-limit handling, provenance and dry-run behavior.
- Normalization and deduplication are tested with fixtures.

Completion note: provider adapters, dry-run behavior and retry failure tests are implemented without network dependency.

## M4 - Research Reader Contract

Status: complete

Acceptance criteria:

- Structured reader output schema covers access level, bibliography, question, argument, methodology, sources, findings, concepts, relevance, connections, disagreements, references, human-reading recommendation and confidence.
- Invalid or over-privileged outputs are rejected.
- Prompt-injection shaped fixtures remain inert data.

Completion note: reader schema validation rejects forbidden tool/action fields and abstract-only page claims.

## M5 - Research Workflow

Status: complete

Acceptance criteria:

- Research runs have run IDs and structured logs.
- Discovery, screening, reading placeholder handling and run statistics persist.
- Lifecycle states are enforced.

Completion note: dry-run and fixture-provider workflows persist run records, searches, screenings and paper states.

## M6 - Synthesis And Relationships

Status: complete

Acceptance criteria:

- Important findings can be compared with existing literature records.
- Relationship types include convergence, contradiction, extension, methodological difference, historiographic shift and research gap.
- Relationship provenance is persisted.

Completion note: relationship persistence and allowed relationship types are implemented; semantic comparison remains an agent workflow responsibility behind this storage contract.

## M7 - Digest And Feedback

Status: complete

Acceptance criteria:

- Daily digest contains statistics, findings, changed understanding, connections, contradictions, gaps, rabbit holes, reading recommendations, references and user-judgment questions.
- Digest items have stable identifiers.
- Feedback is stored for future prioritization.

Completion note: digest generation persists stable item identifiers and feedback records.

## M8 - Zotero And Delivery Interfaces

Status: complete

Acceptance criteria:

- Zotero adapter supports search, DOI lookup, create/update metadata, tags, notes, attachment metadata and deduplication where available.
- Digest is always saved locally.
- Email delivery is behind an interface and only active when configured.

Completion note: Zotero Web API and delivery adapters are implemented; live Zotero/email verification is optional and credential-gated.

## M8.1 - Notion Digest Archive

- Optional Notion setup command creates an article archive database under a user-shared parent page.
- Each validated reading included in a digest is mirrored as one idempotently updated Notion page, with bibliographic data and structured synthesis.
- SQLite records Notion page mappings; missing credentials or a sync failure never prevents the local digest from being saved or delivered.

## M9 - OpenClaw Packaging

Status: complete-with-local-openclaw-verification-pending

Acceptance criteria:

- Agent workspaces include `AGENTS.md`, `SOUL.md`, `USER.md`, skills, config fragments, policies, routing and automation templates.
- Installer verifies local OpenClaw CLI syntax before production commands.
- Existing OpenClaw config is backed up before modification.

Completion note: templates and installer probes are implemented. Local OpenClaw CLI is not installed in this environment, so agent recognition must be verified on a target machine with OpenClaw.

## M10 - Installer, Tests And Smoke

Status: complete

Acceptance criteria:

- `scripts/install.sh`, `scripts/update.sh`, `scripts/backup.sh` and `scripts/smoke-test.sh` exist and are executable.
- Automated tests cover migrations, deduplication, provider normalization, project validation, states, reader outputs, digests, feedback, security boundaries, installer dry-run and retry behavior.
- Normal tests do not require network.
- Smoke test reports success.

Completion note: full pytest suite passed locally (`15 passed`) and `scripts/smoke-test.sh` reports success.

## M11 - Production Portability Audit

Status: complete

Acceptance criteria:

- Repository hardcoded path scan is clean for user-specific and platform-specific package-manager paths.
- Scripts use repository-relative, `$HOME`, XDG or environment-discovered paths.
- `scripts/preflight.sh` is read-only and checks production host prerequisites.
- `scripts/install.sh --dry-run` reports planned phases without making changes.
- Existing unrelated OpenClaw configuration, agents, plugins and cron jobs are preserved.
- Mac-to-Linux NUC deployment and rollback documentation exists.

Completion note: production portability hardening was added after the V1 foundation.

## M12 - Supported OpenClaw Agent Deployment

Status: complete

Acceptance criteria:

- Installer does not create `alberto-main`.
- Existing OpenClaw `main` remains the Alberto orchestrator and is not modified.
- Alberto creates only `alberto-research` and `research-reader`.
- Agent creation uses `openclaw agents add <agent-id> --workspace <workspace> --model <model> --non-interactive`.
- Existing Alberto-owned agents are detected with `openclaw agents list`.
- Dry-run prints intended operations without creating venvs, installing packages, migrating databases, modifying files, creating agents or creating cron jobs.

Completion note: deployment now uses the supported OpenClaw agent management CLI instead of internal config paths.

## M13 - Academic Research Pipeline End-To-End

Status: complete

Acceptance criteria:

- Crossref date normalization handles missing, partial and `None` date parts.
- Discovery generates at most four deterministic composed queries per project.
- Provider retry uses exponential backoff and honors `Retry-After` for retryable responses such as HTTP 429.
- Workflow persists cheap pre-screen and semantic screening decisions.
- Workflow uses `deep_reading_threshold` and `maximum_daily_deep_reads`.
- `research-reader` contract output from title, abstract and bibliographic metadata is persisted in `readings`.
- Runs record `read_count`.
- Digests prefer persisted readings over raw paper metadata.
- Provider/query errors are retained in run diagnostics without stopping valid results from other providers.
- Projects can opt into article-only discovery filters, excluded DOI prefixes for book-heavy publishers, and skipping papers already read in earlier runs.

Completion note: implemented with offline fixtures, article-only controls and regression tests; full-PDF reading remains a later milestone.

## M14 - Full-Text Acquisition

Status: complete

Acceptance criteria:

- FullTextResolver runs between DEEP_READ ranking and research-reader invocation.
- Resolution order is configurable and defaults to Zotero, Unpaywall, OpenAlex, CORE, DOAJ, Europe PMC, provider PDF URL, abstract fallback, metadata fallback.
- Zotero remains optional and supports DOI lookup, PDF attachment enumeration, indexed full text and permitted file download.
- Unpaywall uses configured email and only legal OA locations.
- OpenAlex, CORE, DOAJ and Europe PMC use documented APIs and only accept validated PDF responses.
- Sci-Hub and Anna's Archive remain unsupported by the default acquisition path.
- DOI full-text resolution caches downloaded PDF paths to avoid repeated API lookups.
- Downloaded PDF responses are content-type/size/signature validated.
- Documents are stored outside the git repository and persisted through the existing `documents` table.
- Duplicate document checksums are not persisted repeatedly.
- PDF text extraction preserves page markers.
- FULL_TEXT, ABSTRACT_ONLY and METADATA_ONLY access levels are accurately passed to research-reader.
- Full-text acquisition failures fall back without aborting the research run.

Completion note: implemented with offline resolver tests, legal OA resolvers and DOI cache; OCR remains intentionally out of scope until normal PDF extraction proves insufficient.
