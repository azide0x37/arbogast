"""Idempotent content-addressed campaign output sinks."""

from .base import (
    Sink,
    SinkError,
    SinkIntegrityError,
    SinkPredicate,
    SinkReceipt,
    SinkRecord,
)
from .custom import CustomContains, CustomReader, CustomSink, CustomWriter
from .database import DatabaseSink, SQLiteSink
from .filesystem import AtomicFilesystemSink, FilesystemSink

__all__ = [
    "AtomicFilesystemSink",
    "CustomContains",
    "CustomReader",
    "CustomSink",
    "CustomWriter",
    "DatabaseSink",
    "FilesystemSink",
    "SQLiteSink",
    "Sink",
    "SinkError",
    "SinkIntegrityError",
    "SinkPredicate",
    "SinkReceipt",
    "SinkRecord",
]
