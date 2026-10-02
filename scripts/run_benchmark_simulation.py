"""Run one configured benchmark time-series simulation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


# ---------------------------------------------------------------------------
# Make the src-layout package importable when this file is executed directly:
#
# python scripts/run_benchmark_simulation.py --config ...
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if not SRC_ROOT.exists():
    raise RuntimeError(
        f"Could not find repository src directory: {SRC_ROOT}"
    )

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SRC_ROOT),
    )


# Project imports must come AFTER the src bootstrap above.
from lv_scenario_benchmark.simulation import (  # noqa: E402
    load_benchmark_simulation_config,
    run_benchmark_simulation,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Run a pandapower benchmark simulation "
            "for a selected analysis time window."
        )
    )

    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help=(
            "Path to the benchmark YAML configuration."
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Run the configured benchmark simulation."""

    args = parse_args()

    config = load_benchmark_simulation_config(
        args.config
    )

    print(
        f"Active PROJECT: {config.project_name}"
    )
    print(
        f"Benchmark: {config.benchmark_id}"
    )
    print(
        f"Scenario: {config.scenario_id}"
    )
    print(
        f"Realisation: {config.realisation}"
    )
    print(
        f"Pandapower net: {config.net_path}"
    )
    print(
        f"Reference year: {config.reference_year}"
    )
    print(
        f"Analysis start: {config.analysis_start}"
    )
    print(
        f"Analysis end: {config.analysis_end}"
    )
    print(
        f"Time-step resolution: "
        f"{config.time_step_minutes} min"
    )
    print(
        f"Output directory: {config.output_dir}"
    )

    result = run_benchmark_simulation(
        config
    )

    print()
    print(
        "Benchmark simulation completed."
    )
    print(
        f"Time steps: {result.n_time_steps}"
    )
    print(
        f"Integer range: "
        f"{result.first_time_step} "
        f"... {result.last_time_step}"
    )
    print(
        f"Analysis start: "
        f"{result.analysis_start}"
    )
    print(
        f"Analysis end: "
        f"{result.analysis_end}"
    )
    print(
        f"Outputs: {result.output_dir}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )