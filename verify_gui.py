"""Real-window smoke test of viewer rendering and controls; requires working Tk."""

import tempfile
from pathlib import Path
import tkinter as tk

from city_visualization import CityViewer, load_csv, normalize_events
from config import SimulationConfig
from event_export import export_event_history
from simulation import RideSharingSimulation


def verify_gui():
    for mode in ("uniform", "distance_aware"):
        for policy in ("random", "nearest"):
            sim = RideSharingSimulation(SimulationConfig(pickup_mode=mode, dispatch_policy=policy))
            sim.run()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.csv"
                export_event_history(sim.event_history, path)
                for events in (normalize_events(sim.event_history), load_csv(path)):
                    root = tk.Tk()
                    viewer = CityViewer(root, events)
                    try:
                        root.update()
                        assert root.winfo_ismapped() and viewer.canvas.find_all()
                        viewer.play_button.invoke()
                        assert viewer.playing and viewer.position > 0
                        viewer.play_button.invoke()
                        assert not viewer.playing and viewer.after_id is None
                        assert viewer.animation_after_id is None
                        viewer.speed.set(20)
                        viewer.restart()
                        assert viewer.position == 0 and not viewer.state.customers
                        assert viewer.animation_after_id is None
                        viewer.playing = True
                        # Advance through real Canvas draws while avoiding timed waits.
                        while viewer.position < len(events):
                            if viewer.after_id is not None:
                                root.after_cancel(viewer.after_id)
                            viewer.step()
                        root.update()
                        assert viewer.state.event.event_type == "simulation_end"
                        assert not viewer.playing
                        assert len(viewer.state.customers) == len(sim.requests)
                    finally:
                        viewer.close()
            print(f"GUI render, controls and complete direct/CSV replay passed: {mode}/{policy}")


if __name__ == "__main__":
    verify_gui()
