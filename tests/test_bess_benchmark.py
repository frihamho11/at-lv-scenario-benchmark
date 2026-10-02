"""Regression tests for BESS benchmark network-path resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

from lv_scenario_benchmark.simulation.benchmark import (
    BenchmarkSimulationError,
    load_benchmark_simulation_config,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))



def test_scenario_filename_uses_active_project(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs" / "benchmark"
    config_dir.mkdir(parents=True)
    parameters_path = tmp_path / "external" / "seiler" / "scripts" / "parameters.py"
    parameters_path.parent.mkdir(parents=True)
    parameters_path.touch()

    config_path = config_dir / "status_quo_winter_week_bess.yaml"
    config_path.write_text(
        """
project:
  parameters: ../../external/seiler/scripts/parameters.py
  pandapower_net_filename: net.p
network:
  scenario_filename: net_status_quo_combined_bess.p
benchmark:
  id: winter_week_bess
  reference_year: 2025
  time_step_minutes: 15
case:
  scenario_id: status_quo
  realisation: 0
analysis:
  start: "2025-01-15T00:00:00"
  end: "2025-01-21T23:45:00"
outputs:
  root: ../../outputs
  file_type: .csv
""".strip(),
        encoding="utf-8",
    )

    project_context = SimpleNamespace(
        project_name="Dynamic_Project",
        pandapower_net_path=tmp_path / "base" / "net.p",
    )
    with patch(
        "lv_scenario_benchmark.simulation.benchmark.load_seiler_project_context",
        return_value=project_context,
    ):
        config = load_benchmark_simulation_config(config_path)

    assert config.net_path == (
        tmp_path
        / "outputs"
        / "Dynamic_Project"
        / "status_quo"
        / "integration"
        / "net_status_quo_combined_bess.p"
    ).resolve()


def test_explicit_path_and_scenario_filename_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs" / "benchmark"
    config_dir.mkdir(parents=True)
    parameters_path = tmp_path / "external" / "seiler" / "scripts" / "parameters.py"
    parameters_path.parent.mkdir(parents=True)
    parameters_path.touch()

    config_path = config_dir / "invalid.yaml"
    config_path.write_text(
        """
project:
  parameters: ../../external/seiler/scripts/parameters.py
network:
  path: ../../outputs/explicit.p
  scenario_filename: net_status_quo_combined_bess.p
analysis:
  start: "2025-01-15T00:00:00"
  end: "2025-01-15T00:15:00"
""".strip(),
        encoding="utf-8",
    )

    project_context = SimpleNamespace(
        project_name="Dynamic_Project",
        pandapower_net_path=tmp_path / "base" / "net.p",
    )
    with patch(
        "lv_scenario_benchmark.simulation.benchmark.load_seiler_project_context",
        return_value=project_context,
    ):
        try:
            load_benchmark_simulation_config(config_path)
        except BenchmarkSimulationError as exc:
            assert "mutually exclusive" in str(exc)
        else:
            raise AssertionError("Expected mutually exclusive network settings to fail.")
