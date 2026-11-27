"""Schematic 2D event-history replay for the ride-sharing simulation.

No geographic coordinates exist in the simulation. Positions in this viewer
are illustrative display positions, *not* actual driver or customer locations.

Run from the repository root:
    python city_visualization.py
    python city_visualization.py --csv events.csv

The first form runs the existing engine once, the second replays a CSV exported
with event_export.export_event_history(). The UI uses only tkinter (stdlib).
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Iterable


EVENT_TYPES = {
    "simulation_start", "arrival", "driver_assignment", "abandonment",
    "pickup_completion", "trip_completion", "simulation_end",
}
STATUS_COLORS = {
    "waiting": "#F5B942",
    "pickup": "#449DFA",
    "trip": "#8B73F8",
    "completed": "#44BF83",
    "abandoned": "#EB6D73",
}


@dataclass(frozen=True)
class ReplayEvent:
    sequence: int
    time: float
    event_type: str
    request_id: int | None
    waiting: int
    in_system: int
    busy_drivers: int
    completed: int
    abandoned: int
    arrivals: int


def normalize_events(events: Iterable[object]) -> list[ReplayEvent]:
    """Convert engine events/CSV dictionaries to ordered, validated replay rows."""
    result: list[ReplayEvent] = []
    previous_time = 0.0
    for i, event in enumerate(events):
        get = event.get if isinstance(event, dict) else lambda k: getattr(event, k)
        name = str(get("event_type"))
        if name not in EVENT_TYPES:
            raise ValueError(f"Unknown event_type in row {i}: {name!r}")
        raw_id = get("request_id")
        rid = None if raw_id is None or raw_id == "" else int(raw_id)
        t = float(get("time"))
        if not 0 <= t < float("inf") or t < previous_time:
            raise ValueError(f"Invalid or out-of-order event time in row {i}")
        seq = int(get("sequence"))
        if seq != i:
            raise ValueError(f"Event sequence mismatch in row {i}: {seq}")
        if (name in {"simulation_start", "simulation_end"}) != (rid is None):
            raise ValueError(f"Invalid request_id in row {i}")
        counts = {field: int(get(field)) for field in
                  ("waiting", "in_system", "busy_drivers", "completed", "abandoned", "arrivals")}
        if any(value < 0 for value in counts.values()):
            raise ValueError(f"Negative count in row {i}")
        if counts["in_system"] != counts["waiting"] + counts["busy_drivers"]:
            raise ValueError(f"Inconsistent in_system count in row {i}")
        if counts["arrivals"] != counts["in_system"] + counts["completed"] + counts["abandoned"]:
            raise ValueError(f"Inconsistent arrivals count in row {i}")
        result.append(ReplayEvent(seq, t, name, rid, **counts))
        previous_time = t
    if not result:
        raise ValueError("No events to replay")
    if result[0].event_type != "simulation_start" or result[-1].event_type != "simulation_end":
        raise ValueError("Replay must include simulation_start and simulation_end")
    return result


def load_csv(path: str | Path) -> list[ReplayEvent]:
    with open(path, newline="", encoding="utf-8-sig") as stream:
        return normalize_events(csv.DictReader(stream))


class ReplayState:
    """View-only projection of events; never alters simulation engine records."""

    def __init__(self) -> None:
        self.customers: dict[int, str] = {}
        self.event: ReplayEvent | None = None

    def apply(self, event: ReplayEvent) -> None:
        if event.request_id is not None:
            rid = event.request_id
            if event.event_type == "arrival":
                if rid in self.customers:
                    raise ValueError(f"Duplicate arrival: {rid}")
                self.customers[rid] = "waiting"
            else:
                prior = self.customers.get(rid)
                transitions = {
                    "driver_assignment": ("waiting", "pickup"),
                    "pickup_completion": ("pickup", "trip"),
                    "trip_completion": ("trip", "completed"),
                    "abandonment": ("waiting", "abandoned"),
                }
                if event.event_type in transitions:
                    expected, new = transitions[event.event_type]
                    if prior != expected:
                        raise ValueError(f"Invalid lifecycle for request {rid}: {prior} -> {new}")
                    self.customers[rid] = new
        expected_counts = {
            "waiting": event.waiting,
            "pickup_or_trip": event.busy_drivers,
            "completed": event.completed,
            "abandoned": event.abandoned,
        }
        observed = {
            "waiting": sum(s == "waiting" for s in self.customers.values()),
            "pickup_or_trip": sum(s in {"pickup", "trip"} for s in self.customers.values()),
            "completed": sum(s == "completed" for s in self.customers.values()),
            "abandoned": sum(s == "abandoned" for s in self.customers.values()),
        }
        if observed != expected_counts:
            raise ValueError(f"Event {event.sequence}: replay counts differ from engine history")
        self.event = event


class CityViewer:
    WIDTH, HEIGHT = 940, 590
    # Named schematic areas, not geographic sites.
    ZONES = {
        "waiting": (80, 86, 280, 224, "WAITING"),
        "pickup": (335, 86, 535, 224, "ASSIGNED: PICKUP"),
        "trip": (590, 86, 850, 224, "ASSIGNED: ON TRIP"),
        "completed": (94, 338, 395, 487, "COMPLETED"),
        "abandoned": (525, 338, 838, 487, "ABANDONED"),
    }


    def __init__(self, root: tk.Tk, events: list[ReplayEvent]) -> None:
        self.root = root
        self.events = events
        self.state = ReplayState()
        self.position = 0
        self.playing = False
        self.after_id: str | None = None
        self.speed = tk.DoubleVar(value=5.0)  # simulated minutes per real second
        self.time_var = tk.StringVar(value="Simulation: 0.00 min")
        self.summary_var = tk.StringVar(value="No events processed")
        self.detail_var = tk.StringVar(value="Press Play to replay recorded events")

        root.title("Ride-Sharing | 2D Event History Viewer")
        root.geometry("980x765")
        root.minsize(820, 680)
        base = ttk.Frame(root, padding=12)
        base.pack(fill="both", expand=True)
        ttk.Label(base, text="Ride-Sharing Dispatch · Schematic City Replay",
                  font=("Arial", 17, "bold")).pack(anchor="w")
        ttk.Label(base, text="Positions are illustrative. Data comes from the actual simulation event history.",
                  foreground="#68737d").pack(anchor="w", pady=(2, 8))
        self.canvas = tk.Canvas(base, width=self.WIDTH, height=self.HEIGHT,
                                background="#E8F0F0", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        controls = ttk.Frame(base)
        controls.pack(fill="x", pady=(12, 3))
        self.play_button = ttk.Button(controls, text="Play", command=self.toggle)
        self.play_button.pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Restart", command=self.restart).pack(side="left", padx=(0, 12))
        ttk.Label(controls, text="Speed (sim min / sec):").pack(side="left")
        
        self.speed_label = ttk.Label(controls, text=f"{self.speed.get():.1f}")

        ttk.Scale(
            controls,
            from_=0.5,
            to=20,
            variable=self.speed,
            orient="horizontal",
            length=170,
            command=lambda value: self.speed_label.configure(
                text=f"{float(value):.1f}"
            )
        ).pack(side="left", padx=8)

        self.speed_label.pack(side="left", padx=5)

        ttk.Label(controls, textvariable=self.time_var).pack(side="right")
        ttk.Label(base, textvariable=self.summary_var, font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(base, textvariable=self.detail_var).pack(anchor="w", pady=(2, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.draw()

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        c.create_rectangle(0, 0, self.WIDTH, self.HEIGHT, fill="#E8F0F0", outline="")
        # Fixed stylized road network and buildings, *not* measured geography.
        for y in (60, 285, 525):
            c.create_rectangle(0, y, self.WIDTH, y + 25, fill="#BAC8CE", outline="")
            for x in range(10, self.WIDTH, 56):
                c.create_line(x, y + 12, x + 26, y + 12, fill="#F9FAFA", width=2)
        for x in (35, 305, 560, 880):
            c.create_rectangle(x, 0, x + 25, self.HEIGHT, fill="#BAC8CE", outline="")
            for y in range(12, self.HEIGHT, 54):
                c.create_line(x + 12, y, x + 12, y + 24, fill="#F9FAFA", width=2)
        for idx, (key, (x1, y1, x2, y2, label)) in enumerate(self.ZONES.items()):
            c.create_rectangle(x1, y1, x2, y2, fill="#F7FAF9", outline="#BCCBC9", width=2)
            c.create_rectangle(x1, y1, x2, y1 + 30, fill=STATUS_COLORS[key], outline="")
            c.create_text((x1 + x2) / 2, y1 + 15, text=label,
                          font=("Arial", 11, "bold"), fill="white" if key != "waiting" else "#35424B")
            if key in {"pickup", "trip"}:
                self.draw_building(c, x1 + 18, y2 - 52)
                self.draw_building(c, x2 - 56, y2 - 52)
        # Fixed stable row-major positions; wrapped customers show via counter.
        groups: dict[str, list[int]] = {s: [] for s in STATUS_COLORS}
        for rid, status in self.state.customers.items():
            groups[status].append(rid)
        for status, ids in groups.items():
            x1, y1, x2, y2, _ = self.ZONES[status]
            cell_w, cell_h = 28, 26
            cols = max(1, (x2 - x1 - 26) // cell_w)
            rows = max(1, (y2 - y1 - 48) // cell_h)
            limit = cols * rows
            for j, rid in enumerate(ids[:limit]):
                px = x1 + 19 + (j % cols) * cell_w
                py = y1 + 47 + (j // cols) * cell_h
                c.create_oval(px - 9, py - 9, px + 9, py + 9, fill=STATUS_COLORS[status],
                              outline="#253944", width=1)
                c.create_text(px, py, text=str(rid) if rid < 100 else "•",
                              font=("Arial", 7, "bold"), fill="white" if status != "waiting" else "black")
            if len(ids) > limit:
                c.create_text(x2 - 30, y2 - 14, text=f"+{len(ids) - limit}",
                              font=("Arial", 10, "bold"), fill="#3B4B57")
            c.create_text(x2 - 15, y1 + 15, text=str(len(ids)), anchor="e",
                          font=("Arial", 11, "bold"), fill="#182B33")
        
        legend = "Yellow: Waiting | Blue: Assigned (Pickup) | Purple: Assigned (Trip) | Green: Completed | Red: Abandoned"
        c.create_text(self.WIDTH / 2, 565, text=legend, fill="#354B54", font=("Arial", 10))
        ev = self.state.event
        if ev is not None:
            self.time_var.set(f"Simulation: {ev.time:.2f} / {self.events[-1].time:.2f} min")
            self.summary_var.set(
                f"Arrivals: {ev.arrivals}   Waiting: {ev.waiting}   Assigned: {ev.busy_drivers}   "
                f"Completed: {ev.completed}   Abandoned: {ev.abandoned}"
            )
            req = "" if ev.request_id is None else f" · customer #{ev.request_id}"
            self.detail_var.set(f"Event {ev.sequence + 1}/{len(self.events)}: {ev.event_type}{req}")

            transitions = {
                "driver_assignment": ("waiting", "pickup"),
                "pickup_completion": ("pickup", "trip"),
                "trip_completion": ("trip", "completed"),
                "abandonment": ("waiting", "abandoned"),
            }

            if ev.event_type in transitions and self.playing:
                source, target = transitions[ev.event_type]
                a = self.ZONES[source]
                b = self.ZONES[target]

                sx, sy = (a[0] + a[2]) / 2, a[3]
                tx, ty = (b[0] + b[2]) / 2, b[3]

                marker = c.create_oval(
                    sx - 6, sy - 6, sx + 6, sy + 6,
                    fill=STATUS_COLORS[target],
                    outline="white", width=2
                )

                def move_marker(frame=0):
                    if not c.type(marker):
                        return
                    if not self.playing or frame >= 12:
                        c.delete(marker)
                        return
                    c.move(marker, (tx - sx) / 12,
                           (ty - sy) / 12)
                    c.after(25, move_marker, frame + 1)

                move_marker()

    @staticmethod
    def draw_building(c: tk.Canvas, x: int, y: int) -> None:
        c.create_rectangle(x, y, x + 38, y + 40, fill="#8BA9AC", outline="#6C8C91")
        for dx in (7, 24):
            for dy in (8, 23):
                c.create_rectangle(x + dx, y + dy, x + dx + 8, y + dy + 8,
                                   fill="#D8F4FF", outline="")

    def step(self) -> None:
        self.after_id = None
        if not self.playing:
            return
        # Consume equal-time events in event sequence order without a time gap.
        target_time = self.events[self.position].time
        while self.position < len(self.events) and self.events[self.position].time == target_time:
            self.state.apply(self.events[self.position])
            self.position += 1
        self.draw()
        if self.position == len(self.events):
            self.playing = False
            self.play_button.configure(text="Play")
            return
        gap_minutes = self.events[self.position].time - target_time
        delay_ms = max(25, int(gap_minutes / max(0.5, self.speed.get()) * 1000))
        self.after_id = self.root.after(delay_ms, self.step)

    def toggle(self) -> None:
        if self.playing:
            self.playing = False
            self.play_button.configure(text="Play")
            if self.after_id is not None:
                self.root.after_cancel(self.after_id)
                self.after_id = None
            return
        if self.position >= len(self.events):
            self.restart()
        self.playing = True
        self.play_button.configure(text="Pause")
        self.step()

    def restart(self) -> None:
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.playing = False
        self.position = 0
        self.state = ReplayState()
        self.time_var.set("Simulation: 0.00 min")
        self.summary_var.set("No events processed")
        self.detail_var.set("Press Play to replay recorded events")
        self.play_button.configure(text="Play")
        self.draw()

    def close(self) -> None:
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay ride-sharing events in a schematic 2D city viewer")
    parser.add_argument("--csv", type=Path, help="CSV previously created with export_event_history")
    args = parser.parse_args()
    if args.csv:
        events = load_csv(args.csv)
    else:
        from config import SimulationConfig
        from simulation import RideSharingSimulation
        simulation = RideSharingSimulation(SimulationConfig())
        simulation.run()
        events = normalize_events(simulation.event_history)
    root = tk.Tk()
    CityViewer(root, events)
    root.mainloop()


if __name__ == "__main__":
    main()
