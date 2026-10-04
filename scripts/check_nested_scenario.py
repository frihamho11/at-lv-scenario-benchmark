#!/usr/bin/env python
"""Check nested status-quo inheritance and EV/HP annual energy scaling."""

from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "outputs" / "Grossschoenau_Neu"
BASELINE = "status_quo"
SCENARIO = "2x_penetration_nested"
DT_H = 0.25

TEMPLATE_COLUMNS = [
    "profile_id",
    "simbench_peak_p_mw",
    "simbench_peak_q_mvar",
    "simbench_source_grid_code",
    "simbench_source_load_index",
]


def _paths(scenario: str, tech: str) -> tuple[Path, Path]:
    folder = PROJECT_DIR / scenario / "integration" / tech
    return (
        folder / f"{tech}_pandapower_profile_mapping.csv",
        folder / f"{tech}_simbench_relative_profile_pool.csv.gz",
    )


def _energy(scenario: str, tech: str) -> tuple[float, int]:
    mapping_path, profile_path = _paths(scenario, tech)
    mapping = pd.read_csv(mapping_path)
    profiles = pd.read_csv(profile_path)
    total = 0.0
    for row in mapping.itertuples(index=False):
        col = f"{row.profile_id}_pload"
        relative = pd.to_numeric(profiles[col], errors="raise")
        if tech == "ev":
            relative = relative.clip(lower=0.0)
        total += float(relative.sum()) * float(row.simbench_peak_p_mw) * DT_H
    return total, len(mapping)


def _compare_ev() -> None:
    base = pd.read_csv(_paths(BASELINE, "ev")[0])
    nested = pd.read_csv(_paths(SCENARIO, "ev")[0])
    key = ["building_id", "unit_at_building"]
    merged = base.merge(nested, on=key, suffixes=("_base", "_nested"), how="left", indicator=True)
    if not (merged["_merge"] == "both").all():
        raise RuntimeError("At least one baseline EV is missing from nested scenario.")
    mismatches = 0
    for col in TEMPLATE_COLUMNS:
        a, b = merged[f"{col}_base"], merged[f"{col}_nested"]
        if pd.api.types.is_numeric_dtype(a):
            mismatches += int((pd.to_numeric(a) != pd.to_numeric(b)).sum())
        else:
            mismatches += int((a.astype(str) != b.astype(str)).sum())
    print(f"EV inherited units: {len(base)} / {len(base)}")
    print(f"EV inherited-template mismatches: {mismatches}")


def _compare_hp() -> None:
    base = pd.read_csv(_paths(BASELINE, "hp")[0])
    nested = pd.read_csv(_paths(SCENARIO, "hp")[0])
    merged = base.merge(nested, on=["building_id"], suffixes=("_base", "_nested"), how="left", indicator=True)
    if not (merged["_merge"] == "both").all():
        raise RuntimeError("At least one baseline HP is missing from nested scenario.")
    mismatches = 0
    for col in TEMPLATE_COLUMNS:
        a, b = merged[f"{col}_base"], merged[f"{col}_nested"]
        if pd.api.types.is_numeric_dtype(a):
            mismatches += int((pd.to_numeric(a) != pd.to_numeric(b)).sum())
        else:
            mismatches += int((a.astype(str) != b.astype(str)).sum())
    print(f"HP inherited units: {len(base)} / {len(base)}")
    print(f"HP inherited-template mismatches: {mismatches}")


def _compare_bess() -> None:
    base_path = PROJECT_DIR / BASELINE / "allocation" / "bess_allocation.csv"
    nested_path = PROJECT_DIR / SCENARIO / "allocation" / "bess_allocation.csv"
    if not base_path.exists() or not nested_path.exists():
        print("BESS check skipped: one allocation CSV is missing.")
        return
    base = pd.read_csv(base_path)
    nested = pd.read_csv(nested_path)
    missing = sorted(set(base["building_id"].astype(str)) - set(nested["building_id"].astype(str)))
    print(f"BESS inherited baseline locations: {len(base) - len(missing)} / {len(base)}")
    if missing:
        raise RuntimeError(f"Missing baseline BESS buildings: {missing[:10]}")


def main() -> int:
    print(f"Project: {PROJECT_DIR}")
    print(f"Baseline: {BASELINE}")
    print(f"Nested scenario: {SCENARIO}\n")
    _compare_ev()
    _compare_hp()
    _compare_bess()

    print("\nAnnual energy:")
    for tech in ("ev", "hp"):
        e0, n0 = _energy(BASELINE, tech)
        e1, n1 = _energy(SCENARIO, tech)
        print(
            f"{tech.upper()}: {n0} -> {n1} units | "
            f"{e0:.4f} -> {e1:.4f} MWh | "
            f"count ratio={n1/n0:.4f} | energy ratio={e1/e0:.4f} | "
            f"energy/unit ratio={(e1/n1)/(e0/n0):.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
