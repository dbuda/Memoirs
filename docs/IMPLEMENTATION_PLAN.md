# Implementation Plan

## 1. Objective

Build a small but credible demonstration of an evidence-backed information extraction pipeline for memoir interviews.

The demo should answer the following engineering questions:

1. Can the system extract structured people, events, claims and relationships from messy narrative text?
2. Can every extracted record be traced back to supporting transcript evidence?
3. Can it represent uncertainty, approximate dates and contradictions without inventing certainty?
4. Can an editor review and correct results?
5. Do approved corrections survive a later extraction run?
6. Can extraction quality and failure modes be measured with repeatable tests?

## 2. Design Principles

### Keep the domain model explicit

Use ordinary Python models and PostgreSQL tables for the core concepts. Do not hide the main workflow inside a prompt chain or an agent framework.

### Treat model output as a proposal

LLM output is an extraction candidate. It must pass schema validation, evidence validation and domain checks before it becomes reviewable.

### Preserve source evidence

The system stores transcript offsets and quoted text for every candidate record. Unsupported claims should be visible as failures, not silently accepted.

### Make uncertainty first-class

Store original date expressions, interpreted ranges, precision, confidence and inference flags. Do not force uncertain information into exact values.

### Keep human decisions separate from model output

Review decisions should be append-only or versioned. Reprocessing a document must not erase an approved correction.

The API should expose the latest extraction run as the effective result while retaining older runs for audit and comparison. Review decisions are carried forward to matching records by stable record type and key.

### Prefer a replaceable pipeline over a large platform

Use a small FastAPI application, PostgreSQL, Redis and a Celery worker. The demo should show a real asynchronous boundary because extraction is long-running and failure-prone. The architecture should still remain small: one API container, one worker container, one PostgreSQL container and one Redis container. Kubernetes, Celery Beat and multiple domain services are out of scope.

## 3. Initial Repository Structure

```text
app/
  api/
  domain/
  extraction/
  db/
  jobs/
tests/
  fixtures/
  unit/
  integration/
data/
  fictional_interviews/
  reviewed_examples/
docs/
  IMPLEMENTATION_PLAN.md
```

The exact module names can change during implementation. The important boundary is between API code, domain models, extraction logic and infrastructure adapters.

## 4. Minimal Data Model

### `documents`

- `id`
- `title`
- `language`
- `created_at`
- `source_version`

### `segments`

- `id`
- `document_id`
- `speaker`
- `sequence_number`
- `text`
- `char_start`
- `char_end`

Segments preserve speaker information and offsets in the original document.

### `extraction_runs`

- `id`
- `document_id`
- `provider`
- `model`
- `prompt_version`
- `status`
- `created_at`

This allows results from different runs to be compared without losing history.

### `persons`

- `id`
- `canonical_name`
- `description`

### `person_aliases`

- `id`
- `person_id`
- `alias`
- `confidence`
- `review_status`

### `events`

- `id`
- `event_type`
- `summary`
- `date_text`
- `date_start`
- `date_end`
- `date_precision`
- `is_inferred`
- `confidence`
- `review_status`

### `claims`

- `id`
- `subject_type`
- `subject_id`
- `predicate`
- `object_type`
- `object_id` or `object_text`
- `is_explicit`
- `confidence`
- `review_status`

### `evidence`

- `id`
- `extraction_run_id`
- `segment_id`
- `char_start`
- `char_end`
- `quote`

### `record_evidence`

Join records to one or more evidence spans. This supports facts that are assembled from multiple parts of an interview.

### `review_decisions`

- `id`
- `record_type`
- `record_id`
- `decision`: `approved`, `corrected`, `rejected`
- `original_value`
- `reviewed_value`
- `reviewer_note`
- `created_at`

The original extraction remains available. The effective value is resolved from the latest applicable review decision.

## 5. Extraction Pipeline

### Step 1: Ingest

Load two or three fictional interviews with speaker labels. Normalize line endings while preserving the original text and character offsets.

### Step 2: Chunk with context

Create chunks by transcript size, but keep speaker, document and segment metadata. Add a small overlap so that relationships and dates are not split at chunk boundaries.

The chunker must return an offset map from model input back to the original transcript.

### Step 3: Extract structured candidates

Use a provider interface such as:

```python
class ExtractionProvider(Protocol):
    async def extract(self, chunk: ExtractionChunk) -> ExtractionResult:
        ...
```

The initial provider can use an OpenAI-compatible structured-output API. Tests will use a deterministic fake provider with fixture responses.

The extraction schema should include:

- people and aliases;
- events and participants;
- places;
- claims and relationships;
- date expressions and interpreted ranges;
- themes;
- evidence references;
- confidence and inference flags.

### Step 4: Validate

Validate both the data shape and the meaning of references:

- Pydantic schema validation;
- evidence offsets must exist inside the source segment;
- evidence quote must match the referenced text after normalization;
- confidence must be between 0 and 1;
- inferred dates must not be represented as exact facts without a precision flag;
- references to people and events must resolve or remain explicitly unresolved.

### Step 5: Normalize and link

Use deterministic rules first:

- normalized lower-case aliases;
- punctuation and whitespace normalization;
- same-document candidate matching;
- exact and fuzzy name comparison only as a candidate-generation step.

Use model reasoning only where the rule-based result is ambiguous. Ambiguous links should remain reviewable rather than being forced into a match.

### Step 6: Persist candidates

Persist candidates with their extraction run and evidence links. Do not overwrite records from previous runs.

### Step 7: Review

Expose operations to approve, correct or reject a candidate. A correction should store the original and reviewed value, reviewer note and timestamp.

### Step 8: Retrieve

Return effective approved values together with the evidence used to support them. Retrieval should make it easy for a downstream editor or chapter-generation system to inspect why a fact exists.

## 6. Async Processing

The first implementation should use Celery for execution and Redis as the broker. PostgreSQL remains the source of truth for job state and must not be replaced by Redis state:

```text
POST /documents/{id}/extract
        |
        v
create extraction run and job record in PostgreSQL
        |
        v
enqueue Celery task through Redis
        |
        v
Celery worker processes chunks and persists status and errors
```

The job model should include status, attempts, error message, timestamps and a stable task identifier. Processing must be idempotent for a document and extraction run. A retry must not create duplicate records or remove review decisions.

Celery tasks should define bounded retries and distinguish retryable failures, such as a temporary provider error, from permanent failures, such as invalid input. The API should return the persisted job status rather than exposing broker internals.

The local stack should be started through Docker Compose:

```text
api       FastAPI application
worker    Celery worker
db        PostgreSQL
broker    Redis
```

The LLM provider remains behind an adapter. Tests use a deterministic fake provider and do not require network access or API credentials.

## 7. Evaluation and Regression Tests

Create a reviewed reference file from the fictional interviews. It should include expected people, aliases, events, dates, claims and evidence spans.

Tests should cover:

- successful extraction of explicit facts;
- alias resolution for the same person;
- two people with similar names;
- a repeated event described in different words;
- an approximate date such as `in the early 1980s`;
- a relative date such as `two years later`;
- contradictory accounts of an event;
- an unsupported model claim with no valid evidence;
- invalid evidence offsets;
- approval and correction of a candidate;
- reprocessing that preserves an approved correction;
- retry and failure states for an async job.

At minimum, report:

- entity precision and recall;
- event precision and recall;
- alias-linking accuracy;
- evidence validity rate;
- unsupported-claim rate;
- date interpretation errors;
- schema validation failures.

The evaluation code should be simple and inspectable. A small reviewed dataset is more useful here than an impressive but opaque benchmark.

## 8. Security and Privacy Boundaries

- Use only fictional transcripts in the repository.
- Keep API keys in environment variables.
- Do not log full transcript content in application logs.
- Make the LLM provider an explicit adapter so data handling can be changed later.
- Document that a production system would need access control, retention rules, encryption and provider-specific data-processing review.

## 9. Definition of Done

The demo is complete when a reviewer can:

1. Start the API, worker, PostgreSQL and Redis with Docker Compose.
2. Load the fictional interviews.
3. Run an extraction job.
4. Inspect structured records and supporting evidence.
5. Approve, correct and reject records.
6. Re-run extraction without losing an approved correction.
7. Search records and receive evidence-linked results.
8. Run the test suite and see extraction evaluation output.

The Compose setup should include healthchecks and environment configuration through an `.env` file or `.env.example`. The application should not start processing jobs until PostgreSQL and Redis are reachable.

## 10. Explicit Non-Goals

- No speech-to-text implementation.
- No polished frontend in the first version.
- No multi-agent orchestration.
- No general-purpose graph database.
- No Kubernetes, Celery Beat or separate deployment platform.
- No automatic publication of unreviewed facts.
- No claim that the demo is production-ready.

These exclusions keep the project focused on the core question for this role: can structured knowledge be extracted from messy narratives while remaining accurate, reviewable and traceable?
