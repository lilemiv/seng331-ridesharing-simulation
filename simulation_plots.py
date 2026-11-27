
import matplotlib.pyplot as plt

from config import SimulationConfig
from simulation import RideSharingSimulation


def plot_q_b(event_history):
    times = [event.time for event in event_history]
    queue = [event.waiting for event in event_history]
    busy = [event.busy_drivers for event in event_history]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    # Q(t) - Queue Length
    axes[0].step(times, queue, where="post",
                 color="orange", linewidth=2)
    axes[0].set_title("Q(t) - Queue Length")
    axes[0].set_xlabel("Time (minutes)")
    axes[0].set_ylabel("Waiting Customers")
    axes[0].grid(True, alpha=0.3)

    # B(t) - Busy Drivers
    axes[1].step(times, busy, where="post",
                 color="royalblue", linewidth=2)
    axes[1].set_title("B(t) - Busy Drivers")
    axes[1].set_xlabel("Time (minutes)")
    axes[1].set_ylabel("Busy Drivers")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


if __name__ == "__main__":
    simulation = RideSharingSimulation(SimulationConfig())
    simulation.run()

    plot_q_b(simulation.event_history)
    plt.show()
