#!/usr/bin/env python
"""Run the existing PV/EV/HP scenario pipeline and append PV-coupled BESS.

Repository target:
    scripts/run_benchmark_scenario_with_bess.py

This wrapper deliberately leaves the existing PV/EV/HP scenario runner unchanged.
It first creates the scenario allocations and the combined PV/EV/HP network with the
existing runner. It then allocates BESS as a subset of the already allocated PV systems
and finally computes the chronological BESS dispatch on the combined network, so the
battery sees the local base, EV and HP loads as well as its coupled PV system.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lv_scenario_benchmark.allocation.bess_status_quo import (  # noqa: E402
    load_bess_allocation_config,
    run_bess_allocation,
)
from lv_scenario_benchmark.integration.bess_pandapower import (  # noqa: E402
    integrate_bess,
    load_bess_pandapower_config,
)


def _load_scenario_header(path: Path) -> tuple[str, int]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Scenario YAML root must be a mapping.")
    case = raw.get("case", {})
    scenario_id = str(case.get("scenario_id", "")).strip()
    if not scenario_id:
        raise ValueError("Scenario YAML requires case.scenario_id.")
    realisations = int(case.get("realisations", 1))
    if realisations <= 0:
        raise ValueError("case.realisations must be positive.")
    return scenario_id, realisations


def _combined_filename(scenario_id: str, realisation: int, realisations: int) -> str:
    if realisations == 1:
        return f"net_{scenario_id}_combined.p"
    return f"net_{scenario_id}_combined_r{realisation:03d}.p"


def _combined_bess_filename(
    scenario_id: str,
    realisation: int,
    realisations: int,
) -> str:
    if realisations == 1:
        return f"net_{scenario_id}_combined_bess.p"
    return f"net_{scenario_id}_combined_bess_r{realisation:03d}.p"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one existing PV/EV/HP benchmark scenario and then append "
            "PV-coupled BESS allocation and chronological self-consumption dispatch."
        )
    )
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument(
        "--bess-allocation-config",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--bess-integration-config",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--skip-base-scenario",
        action="store_true",
        help=(
            "Skip the existing PV/EV/HP scenario runner when its allocation and "
            "combined network outputs already exist."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario_path = args.scenario.resolve()
    scenario_id, realisations = _load_scenario_header(scenario_path)

    if not args.skip_base_scenario:
        existing_runner = PROJECT_ROOT / "scripts" / "run_benchmark_scenario.py"
        if not existing_runner.exists():
            raise FileNotFoundError(existing_runner)
        subprocess.run(
            [sys.executable, str(existing_runner), "--scenario", str(scenario_path)],
            cwd=PROJECT_ROOT,
            check=True,
        )

    allocation_base = load_bess_allocation_config(args.bess_allocation_config)
    output_root = allocation_base.output_dir.parents[2]
    scenario_root = (
        output_root / allocation_base.project_name / scenario_id
    ).resolve()

    allocation_config = replace(
        allocation_base,
        scenario_id=scenario_id,
        realisations=realisations,
        pv_allocation_path=(
            scenario_root
            / "allocation"
            / allocation_base.pv_allocation_path.name
        ).resolve(),
        output_dir=(scenario_root / "allocation").resolve(),
    )
    allocation_result = run_bess_allocation(allocation_config)

    integration_base = load_bess_pandapower_config(args.bess_integration_config)
    if integration_base.project_name != allocation_base.project_name:
        raise ValueError(
            "BESS allocation and integration configurations resolve different "
            f"projects: {allocation_base.project_name!r} and "
            f"{integration_base.project_name!r}."
        )
    for realisation in range(realisations):
        base_net_path = (
            scenario_root
            / "integration"
            / _combined_filename(scenario_id, realisation, realisations)
        ).resolve()
        output_net_path = (
            scenario_root
            / "integration"
            / _combined_bess_filename(scenario_id, realisation, realisations)
        ).resolve()

        integration_config = replace(
            integration_base,
            project_name=allocation_base.project_name,
            scenario_id=scenario_id,
            realisation=realisation,
            base_net_path=base_net_path,
            bess_allocation_path=(
                scenario_root / "allocation" / "bess_allocation.parquet"
            ).resolve(),
            output_net_path=output_net_path,
            output_dir=(
                scenario_root / "integration" / "bess" / f"r{realisation:03d}"
            ).resolve(),
        )
        result = integrate_bess(integration_config)
        print(
            f"BESS integrated for realisation {realisation}: "
            f"{result.bess_count} units -> {result.output_net_path}"
        )

    print()
    print(f"Scenario with BESS completed: {scenario_id}")
    print(f"BESS units across allocation table: {len(allocation_result.allocation)}")
    print(f"Realisations: {realisations}")
    print(f"Output: {scenario_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
