from app.evaluation import Counts, evaluate


def test_counts_derive_precision_recall_and_f1() -> None:
    counts = Counts(tp=3, fp=1, fn=1)

    assert counts.precision == 0.75
    assert counts.recall == 0.75
    assert counts.f1 == 0.75


def test_reference_corpus_meets_quality_gate() -> None:
    result = evaluate()
    overall = result["overall"]

    for record_type in ("person", "place", "claim", "event"):
        assert overall[record_type]["f1"] >= 0.95, record_type
    assert overall["alias"]["matched"] == overall["alias"]["total"]
    assert overall["date_precision"]["matched"] == overall["date_precision"]["total"]
    assert overall["evidence"]["valid"] == overall["evidence"]["total"]
