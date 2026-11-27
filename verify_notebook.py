"""Execute the analysis notebook in a fresh kernel using this Python environment."""

import argparse
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


def execute_notebook(source: Path, output: Path):
    with TemporaryDirectory(prefix="ridesharing-notebook-") as directory:
        keys = ("IPYTHONDIR", "JUPYTER_DATA_DIR", "JUPYTER_RUNTIME_DIR", "MPLCONFIGDIR")
        previous = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ[key] = str(Path(directory) / key.lower())
            return _execute_notebook(source, output)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _execute_notebook(source: Path, output: Path):
    import nbformat
    from jupyter_client import KernelManager
    from nbclient import NotebookClient

    notebook = nbformat.read(source, as_version=4)
    manager = KernelManager(kernel_name="python3")
    # Do not register a global kernel or accidentally execute in another venv.
    manager.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    client = NotebookClient(notebook, km=manager, timeout=180,
                            resources={"metadata": {"path": str(source.resolve().parent)}})
    try:
        client.execute()
    finally:
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
    nbformat.write(notebook, output)
    count = sum(c.cell_type == "code" and bool(c.source.strip()) for c in notebook.cells)
    print(f"Executed {count} code cells without errors: {output}")
    return notebook


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("ridesharing_analysis.ipynb"))
    parser.add_argument("--output", type=Path, default=Path("tmp/executed_analysis.ipynb"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    execute_notebook(args.source, args.output)
