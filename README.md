# Memoirs: Evidence-Linked Information Extraction Demo

This repository is a small technical demo for turning long-form life-story interviews into structured, reviewable knowledge.

It is intentionally scoped as a portfolio project. The goal is not to build a complete memoir product or to hide complexity behind a chatbot. The goal is to demonstrate a reliable extraction workflow that preserves source evidence and makes uncertainty visible.

## Problem

A life story is not a clean database record. An interview can contain:

- several references to the same person, including aliases and nicknames;
- repeated or partially conflicting accounts of the same event;
- exact dates, approximate dates, ages and relative time expressions;
- facts spread across multiple transcript sections;
- statements that are explicit, inferred or uncertain.

The demo will use two or three fictional interview transcripts and extract:

- people and aliases;
- life events;
- dates and uncertain time ranges;
- places;
- relationships;
- claims and themes;
- evidence links to the original transcript.

## What This Demonstrates

- Python API design with FastAPI and Pydantic.
- PostgreSQL modelling for extracted knowledge and provenance.
- Context-preserving transcript chunking.
- Structured LLM output behind a small provider interface.
- Deterministic validation of extracted records.
- Confidence and uncertainty handling.
- Entity resolution for repeated people and aliases.
- Human review and approval workflows.
- Evidence-linked retrieval.
- Regression tests based on reviewed examples.
- Asynchronous processing with a small job abstraction.

## Deliberate Scope

The implementation will be small enough to understand in one sitting, but realistic enough to show production judgement.

The demo will include:

1. A small FastAPI service.
2. A PostgreSQL database managed with SQLAlchemy and Alembic.
3. A transcript ingestion endpoint or command.
4. A background extraction job.
5. A structured extraction schema.
6. Evidence spans identified by character offsets.
7. A review endpoint for approving or correcting extracted records.
8. A retrieval endpoint that returns records together with supporting evidence.
9. A compact evaluation dataset and regression tests.

Extraction runs will execute through a Celery worker. Redis will be used as the broker, while PostgreSQL remains the source of truth for job state, extraction runs and extracted data. This keeps the API responsive and makes retries and failure handling explicit without introducing multiple domain services.

## Example Flow

```text
fictional transcript
        |
        v
document and speaker segments
        |
        v
context-preserving chunks
        |
        v
structured extraction
        |
        v
schema validation and normalization
        |
        v
candidate records with evidence and confidence
        |
        v
human review: approve, correct, reject
        |
        v
evidence-linked knowledge available to editors
```

## Evidence and Uncertainty

Every extracted record should be traceable to one or more transcript spans. An evidence record will contain at least:

- source document identifier;
- segment identifier;
- character start and end offsets;
- quoted text;
- extraction run identifier.

Dates will not be reduced to a single guessed value. The model will preserve the original expression and represent the interpreted range, precision and whether the interpretation was inferred. For example, `in the early 1980s` can be stored as an approximate range rather than silently becoming `1982-01-01`.

The demo will distinguish:

- explicit statements, such as `I moved to Perth in 1984`;
- inferred values, such as an estimated year based on age;
- unresolved or contradictory values requiring review.

## Review Model

Extraction output is treated as a candidate, not as truth.

Reviewers can approve, correct or reject a candidate. Corrections are stored as review decisions instead of overwriting the original extraction. This makes it possible to:

- inspect what the model originally produced;
- preserve editorial decisions across reprocessing;
- compare extraction runs;
- identify recurring failure modes.

## Quality Evaluation

The demo will contain a small reviewed reference set created from the fictional transcripts. Tests and evaluation code will measure at least:

- entity extraction precision and recall;
- event extraction precision and recall;
- evidence span validity;
- relation or alias linking accuracy;
- date interpretation errors;
- unsupported claim rate;
- schema validation failures.

The numbers will be treated as a baseline, not as a claim that a small demo represents production quality. The important part is making quality measurable and failures inspectable.

## Planned API Surface

The initial API will stay intentionally small:

```text
POST /documents
POST /documents/{document_id}/extract
GET  /jobs/{job_id}
GET  /documents/{document_id}/records
GET  /records/{record_id}
POST /review/items/{item_id}
GET  /documents/{document_id}/search
```

The response for a record will include its current review state, confidence and evidence references. A frontend is not required for the first demo. Review can be exercised through the API and a small command-line script.

## Technology Choices

- Python 3.12
- FastAPI
- Pydantic
- SQLAlchemy and Alembic
- PostgreSQL
- Celery
- Redis
- pytest
- Docker Compose for the complete local stack
- One LLM provider adapter with a deterministic fake adapter for tests

The demo will avoid introducing a framework-heavy agent stack. Extraction logic should remain visible, testable and replaceable. Kubernetes, a separate frontend service and other deployment infrastructure are outside the scope of this demo.

## Local Development

Create a local environment file and start the complete stack:

```bash
cp .env.example .env
docker compose up --build
```

In a second terminal, apply migrations:

```bash
docker compose exec api alembic upgrade head
```

The API is available at `http://localhost:8000`, and interactive documentation is available at `http://localhost:8000/docs`.

The first provider is deterministic and does not require an API key. It exists to exercise the pipeline, evidence validation and review workflow. A real structured-output provider can be added behind the same `ExtractionProvider` interface later.

## Non-Goals

- speech recognition;
- a polished frontend;
- a general-purpose knowledge graph;
- multi-tenant production infrastructure;
- perfect chronological reconstruction;
- automatic publication without editorial review;
- benchmark claims based on a tiny synthetic dataset.

## Implementation Plan

The implementation plan and technical decisions are documented in [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

## Data and Privacy

All initial transcripts will be fictional and created specifically for this demo. No real family histories, personal data or private interviews should be committed to the repository.

## Included Fictional Corpus

The initial corpus contains three related interviews:

- `01_nora_bennett.txt` follows Nora Bennett, a former library assistant and cafe owner.
- `02_priya_bennett.txt` follows Priya Bennett, Nora's daughter, and provides a second account of shared family events.
- `03_mei_tan.txt` follows Mei Tan, Nora's friend and former business partner.

JSON request fixtures with the same interviews are stored next to the text files. Each JSON file contains `title`, `subject`, `interviewer`, `interview_date` and the complete transcript in `text`. The current `POST /documents` endpoint can accept the fixture directly and ignores the additional metadata fields.

The interviews intentionally contain useful extraction edge cases:

- Nora, Norrie, Nor and Nana Norrie are references to the same person.
- Mei Tan and Mei Chen are names used by the same person at different points in her life.
- The birth year for Priya is remembered differently by Nora and Priya.
- The opening year of The Lantern is described as 1991 or 1992 depending on whether the lease or the opening is meant.
- The meeting date for Nora and Mei is uncertain and described differently by the speakers.
- The red suitcase event is described by two witnesses with different months.
- Relative dates, approximate dates, explicit facts, inferred values and personal interpretations appear throughout the transcripts.

These conflicts are intentional. A correct system should preserve the competing evidence and make the conflict reviewable instead of silently selecting one version.
