import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.extraction.chunking import TranscriptSegment
from app.extraction.pipeline import extract_records
from app.services.ingestion import parse_transcript

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "fictional_interviews"
DEFAULT_GOLD = PROJECT_ROOT / "data" / "gold_reference.json"
SCORED_TYPES = ("person", "place", "claim", "event")


@dataclass(frozen=True)
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def _score(predicted: set[Any], expected: set[Any]) -> Counts:
    return Counts(
        tp=len(predicted & expected),
        fp=len(predicted - expected),
        fn=len(expected - predicted),
    )


def _event_identity(event: dict[str, Any]) -> tuple[str, str | None]:
    return (str(event["event_key"]), event.get("date_start"))


def evaluate(corpus_dir: Path | None = None, gold_path: Path | None = None) -> dict[str, Any]:
    corpus = corpus_dir or DEFAULT_CORPUS
    gold = json.loads((gold_path or DEFAULT_GOLD).read_text(encoding="utf-8"))

    totals = {record_type: Counts() for record_type in SCORED_TYPES}
    alias_totals = {"matched": 0, "total": 0}
    date_totals = {"matched": 0, "total": 0}
    evidence_totals = {"valid": 0, "total": 0}
    documents: dict[str, Any] = {}

    for filename, expected in gold["documents"].items():
        segments = [
            TranscriptSegment(
                id=index + 1,
                speaker=segment.speaker,
                text=segment.text,
                char_start=segment.char_start,
            )
            for index, segment in enumerate(parse_transcript((corpus / filename).read_text()))
        ]
        records = extract_records(segments)

        predicted: dict[str, set[Any]] = {record_type: set() for record_type in SCORED_TYPES}
        predicted_aliases: dict[str, set[str]] = {}
        predicted_precision: dict[tuple[str, str | None], str] = {}
        for (record_type, record_key), record in records.items():
            if record_type == "event":
                predicted["event"].add(_event_identity(record.payload))
                predicted_precision[_event_identity(record.payload)] = str(
                    record.payload.get("date_precision", "unknown")
                )
            elif record_type in predicted:
                predicted[record_type].add(record_key)
            if record_type == "person":
                predicted_aliases[record_key] = set(record.payload.get("aliases", []))

        expected_sets: dict[str, set[Any]] = {
            "person": set(expected["people"]),
            "place": set(expected["places"]),
            "claim": set(expected["claims"]),
            "event": {_event_identity(event) for event in expected["events"]},
        }

        document: dict[str, Any] = {}
        for record_type in SCORED_TYPES:
            counts = _score(predicted[record_type], expected_sets[record_type])
            document[record_type] = counts.as_dict()
            current = totals[record_type]
            totals[record_type] = Counts(
                tp=current.tp + counts.tp,
                fp=current.fp + counts.fp,
                fn=current.fn + counts.fn,
            )

        alias_result = {"matched": 0, "total": 0}
        for record_key, surfaces in expected.get("aliases", {}).items():
            for surface in surfaces:
                alias_result["total"] += 1
                if surface in predicted_aliases.get(record_key, set()):
                    alias_result["matched"] += 1
        alias_totals["matched"] += alias_result["matched"]
        alias_totals["total"] += alias_result["total"]
        document["alias"] = alias_result

        date_result = {"matched": 0, "total": 0}
        for event in expected["events"]:
            expected_precision = event.get("date_precision")
            if not expected_precision or expected_precision == "unknown":
                continue
            identity = _event_identity(event)
            if identity not in predicted["event"]:
                continue
            date_result["total"] += 1
            if predicted_precision.get(identity) == expected_precision:
                date_result["matched"] += 1
        date_totals["matched"] += date_result["matched"]
        date_totals["total"] += date_result["total"]
        document["date_precision"] = date_result

        segment_by_id = {segment.id: segment for segment in segments}
        evidence_result = {"valid": 0, "total": 0}
        for record in records.values():
            for evidence in record.evidence:
                evidence_result["total"] += 1
                segment = segment_by_id.get(evidence.segment_id)
                if (
                    segment is not None
                    and segment.text[evidence.char_start : evidence.char_end] == evidence.quote
                ):
                    evidence_result["valid"] += 1
        evidence_totals["valid"] += evidence_result["valid"]
        evidence_totals["total"] += evidence_result["total"]
        document["evidence"] = evidence_result

        documents[filename] = document

    overall: dict[str, Any] = {
        record_type: counts.as_dict() for record_type, counts in totals.items()
    }
    overall["alias"] = alias_totals
    overall["date_precision"] = date_totals
    overall["evidence"] = evidence_totals
    return {"documents": documents, "overall": overall}


def _ratio(result: dict[str, int]) -> float:
    total = result["total"]
    matched = result.get("matched", result.get("valid", 0))
    return matched / total if total else 0.0


def format_report(result: dict[str, Any]) -> str:
    overall = result["overall"]
    lines = ["type       precision  recall     f1     tp  fp  fn"]
    for record_type in SCORED_TYPES:
        scores = overall[record_type]
        lines.append(
            f"{record_type:10} {scores['precision']:.2f}       {scores['recall']:.2f}      "
            f"{scores['f1']:.2f}   {scores['tp']:3} {scores['fp']:3} {scores['fn']:3}"
        )
    alias = overall["alias"]
    date = overall["date_precision"]
    evidence = overall["evidence"]
    lines.append(f"alias      {_ratio(alias):.2f} ({alias['matched']}/{alias['total']})")
    lines.append(f"date       {_ratio(date):.2f} ({date['matched']}/{date['total']})")
    lines.append(f"evidence   {_ratio(evidence):.2f} ({evidence['valid']}/{evidence['total']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the deterministic extractor.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args(argv)

    result = evaluate(args.corpus, args.gold)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))

    overall = result["overall"]
    ratios = [
        _ratio(overall["alias"]),
        _ratio(overall["date_precision"]),
        _ratio(overall["evidence"]),
    ]
    ratios.extend(overall[record_type]["f1"] for record_type in SCORED_TYPES)
    return 0 if min(ratios) >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
