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
    """Write UTF-8 CSV with a header, preserving input order and raw precision.

    None values become empty cells. An empty iterable produces a header only.
    The caller chooses the path; its parent directory must already exist.
    Existing files are overwritten and ordinary I/O errors propagate.
    No events or engine records are modified, and no simulation is run here.
    """
    with open(output_path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(asdict(event) for event in events)
