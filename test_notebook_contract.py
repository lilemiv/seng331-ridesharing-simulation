"""Notebook structural contract; full kernel execution runs separately in CI."""

import json
from pathlib import Path
import unittest


class NotebookContractTests(unittest.TestCase):
    def test_embedded_graph_matches_current_architecture(self):
        notebook = json.loads(Path("ridesharing_analysis.ipynb").read_text(encoding="utf8"))
        source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
        graph = Path("EVENT_GRAPH.md").read_text(encoding="utf8").split("```mermaid", 1)[1].split("```", 1)[0]
        self.assertIn(graph, source)

    def test_notebook_uses_actual_replication_and_experiment_apis(self):
        notebook = json.loads(Path("ridesharing_analysis.ipynb").read_text(encoding="utf8"))
        code = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
        for call in ("run_replications(", "confidence_interval(", "estimate_replications(",
                     "run_experiment(", "plot_q_b("):
            self.assertIn(call, code)
        self.assertIn("assert_report_matches(experiment, recorded)", code)
