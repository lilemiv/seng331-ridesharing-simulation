import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import SimulationConfig
from simulation import RideSharingSimulation
from simulation_plots import plot_q_b
from test_metrics import snapshot


class PlotTests(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_unsorted_generator_and_same_time_sequence(self):
        rows = [snapshot(3, 10, 1, 2), snapshot(2, 2, 3, 1),
                snapshot(0, 0, 0), snapshot(1, 2, 5)]
        fig = plot_q_b(iter(rows))
        self.assertEqual(list(fig.axes[0].lines[0].get_xdata()), [0, 2, 2, 10])
        self.assertEqual(list(fig.axes[0].lines[0].get_ydata()), [0, 5, 3, 1])
        self.assertEqual(list(fig.axes[1].lines[0].get_ydata()), [0, 0, 1, 2])
        self.assertEqual(fig.axes[0].lines[0].get_drawstyle(), "steps-post")
        self.assertEqual(rows[0].sequence, 3)
        fig.canvas.draw()

    def test_real_engine_data_both_policies_and_modes(self):
        for mode in ("uniform", "distance_aware"):
            for policy in ("random", "nearest"):
                sim = RideSharingSimulation(SimulationConfig(pickup_mode=mode, dispatch_policy=policy))
                sim.run()
                fig = plot_q_b(sim.event_history)
                self.assertEqual(list(fig.axes[0].lines[0].get_ydata()), [e.waiting for e in sim.event_history])
                self.assertEqual(list(fig.axes[1].lines[0].get_ydata()), [e.busy_drivers for e in sim.event_history])
                self.assertEqual(fig.axes[0].lines[0].get_xdata()[-1], 60)
                fig.canvas.draw()

    def test_empty_history_renders(self):
        fig = plot_q_b([])
        self.assertEqual(len(fig.axes), 2)
        fig.canvas.draw()
