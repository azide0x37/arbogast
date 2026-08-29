from __future__ import annotations

from pathlib import Path

import pytest

from arbogast.sinks import (
    CustomSink,
    DatabaseSink,
    FilesystemSink,
    SinkIntegrityError,
    SinkRecord,
)


def test_filesystem_sink_is_atomic_idempotent_and_readable(tmp_path: Path) -> None:
    sink = FilesystemSink(tmp_path / "records")
    record = SinkRecord.create({"target": "24T1", "outcome": "FOUND"}, kind="result")

    first = sink.write(record)
    second = sink.write(record)

    assert first.accepted and first.stored
    assert second.accepted and not second.stored
    assert sink.contains(record.content_id)
    assert sink.read(record.content_id) == record
    assert sink.records() == (record,)


def test_filesystem_sink_filter_is_explicit(tmp_path: Path) -> None:
    accepted = FilesystemSink(
        tmp_path / "filtered",
        predicate=lambda record: record.kind == "accepted",
    )
    receipt = accepted.write({"value": 1}, kind="rejected")
    assert not receipt.accepted
    assert not receipt.stored


def test_database_sink_deduplicates_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "records.sqlite3"
    record = SinkRecord.create({"n": 5}, kind="candidate")
    with DatabaseSink(path) as first:
        assert first.write(record).stored
        assert not first.write(record).stored
    with DatabaseSink(path) as second:
        assert not second.write(record).stored
        assert second.read(record.content_id) == record
        assert second.records() == (record,)


def test_custom_sink_calls_writer_once_per_content_id() -> None:
    written: list[SinkRecord] = []
    sink = CustomSink(lambda record: written.append(record), name="collector")

    first = sink.emit({"value": 3}, kind="observation")
    second = sink.emit({"value": 3}, kind="observation")

    assert first.stored
    assert not second.stored
    assert len(written) == 1
    assert sink.read(first.content_id) == written[0]


def test_sink_record_rejects_tampered_content_id_and_unknown_fields() -> None:
    document = SinkRecord.create({"value": 3}).to_dict()
    document["content_id"] = "sha256:" + "0" * 64
    with pytest.raises(SinkIntegrityError, match="mismatch"):
        SinkRecord.from_dict(document)

    document = SinkRecord.create({"value": 3}).to_dict()
    document["callable"] = "os.system"
    with pytest.raises(SinkIntegrityError, match="unknown"):
        SinkRecord.from_dict(document)
