"""Create one factor-based benchmark scenario and combined pandapower net."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from lv_scenario_benchmark.allocation import (  # noqa: E402
    load_config,
    load_ev_config,
    load_hp_config,
    run_ev_status_quo_allocation,
    run_hp_status_quo_allocation,
    run_pv_status_quo_allocation,
)
from lv_scenario_benchmark.integration.combined_status_quo import (  # noqa: E402
    integrate_combined_status_quo,
    load_combined_status_quo_config,
)


PV_CONFIG = PROJECT_ROOT / "configs" / "allocation" / "pv_status_quo.yaml"
EV_CONFIG = PROJECT_ROOT / "configs" / "allocation" / "ev_status_quo.yaml"
HP_CONFIG = PROJECT_ROOT / "configs" / "allocation" / "hp_status_quo.yaml"
COMBINED_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "integration"
    / "status_quo_combined.yaml"
)


def load_scenario(path: Path) -> tuple[str, int, dict[str, float]]:
    """Load the scenario identifier, realisation count and technology factors."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Scenario YAML root must be a mapping.")

    case = raw.get("case", {})
    factors = raw.get("penetration_factors", {})
    if not isinstance(case, dict) or not isinstance(factors, dict):
        raise ValueError(
            "case and penetration_factors must be YAML mappings."
        )

    scenario_id = str(case.get("scenario_id", "")).strip()
    realisations = int(case.get("realisations", 1))

    if not scenario_id:
        raise ValueError("case.scenario_id is required.")
    if realisations < 1:
        raise ValueError("case.realisations must be at least 1.")

    result: dict[str, float] = {}
    for technology in ("pv", "ev", "hp"):
        factor = float(factors.get(technology, 1.0))
        if factor <= 0:
            raise ValueError(
                f"penetration_factors.{technology} must be greater than zero."
            )
        result[technology] = factor

    return scenario_id, realisations, result


def apply_scenario(
    config,
    *,
    scenario_id: str,
    penetration_factor: float,
    realisations: int,
):
    """Apply one scenario to an existing technology-allocation config."""

    project_output_dir = config.output_dir.parents[1]
    scenario_root = project_output_dir / scenario_id

    return replace(
        config,
        scenario_id=scenario_id,
        penetration_factor=penetration_factor,
        realisations=realisations,
        output_dir=(scenario_root / "allocation").resolve(),
        map_output_dir=(scenario_root / "figures").resolve(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Allocate PV, EV and HP for one factor-based scenario and "
            "build combined pandapower networks."
        )
    )
    parser.add_argument(
        "--scenario",
        required=True,
        type=Path,
        help="Path to a scenario YAML file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario_path = args.scenario.resolve()

    scenario_id, realisations, factors = load_scenario(scenario_path)

    pv_config = apply_scenario(
        load_config(PV_CONFIG),
        scenario_id=scenario_id,
        penetration_factor=factors["pv"],
        realisations=realisations,
    )
    run_pv_status_quo_allocation(pv_config)

    ev_config = apply_scenario(
        load_ev_config(EV_CONFIG),
        scenario_id=scenario_id,
        penetration_factor=factors["ev"],
        realisations=realisations,
    )
    run_ev_status_quo_allocation(ev_config)

    hp_config = apply_scenario(
        load_hp_config(HP_CONFIG),
        scenario_id=scenario_id,
        penetration_factor=factors["hp"],
        realisations=realisations,
    )
    run_hp_status_quo_allocation(hp_config)

    combined_base = load_combined_status_quo_config(COMBINED_CONFIG)
    project_output_dir = combined_base.output_dir.parents[1]
    scenario_root = project_output_dir / scenario_id

    for realisation in range(realisations):
        if realisations == 1:
            output_filename = f"net_{scenario_id}_combined.p"
        else:
            output_filename = (
                f"net_{scenario_id}_combined_r{realisation:03d}.p"
            )

        combined_config = replace(
            combined_base,
            scenario_id=scenario_id,
            realisation=realisation,
            output_dir=(scenario_root / "integration").resolve(),
            figure_dir=(scenario_root / "figures").resolve(),
            output_net_path=(
                scenario_root
                / "integration"
                / output_filename
            ).resolve(),
        )
        integrate_combined_status_quo(combined_config)

    print()
    print(f"Scenario completed: {scenario_id}")
    print(f"PV factor: {factors['pv']}")
    print(f"EV factor: {factors['ev']}")
    print(f"HP factor: {factors['hp']}")
    print(f"Realisations: {realisations}")
    print(f"Output: {scenario_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
