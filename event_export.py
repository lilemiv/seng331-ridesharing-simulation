"""Opt-in CSV serialization of raw simulation events, without derived metrics."""

from collections.abc import Iterable
import csv
from dataclasses import asdict, fields
from os import PathLike

from simulation import SimulationEvent


CSV_COLUMNS = tuple(field.name for field in fields(SimulationEvent))


def export_event_history(
    events: Iterable[SimulationEvent], output_path: str | PathLike[str]
) -> None:
    """Write UTF-8 CSV in input order, preserving numeric precision.

    None becomes an empty cell; empty input writes only the header.
    The parent directory must exist. Existing files are overwritten; I/O errors
    propagate. Input records are unchanged.
    """
    with open(output_path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(asdict(event) for event in events)
