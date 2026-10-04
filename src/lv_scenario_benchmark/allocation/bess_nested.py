"""Nested PV-coupled BESS allocation for controlled penetration scenarios.

The status-quo BESS locations are inherited exactly by building. A higher
penetration scenario keeps those batteries and adds only the additional number
required by the configured attachment rate. Additional BESS locations are chosen
by a stable building-specific ordering. The status-quo BESS set is therefore
preserved exactly in the controlled higher-penetration case.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)


class NestedBESSAllocationError(RuntimeError):
    """Raised when nested BESS allocation cannot be completed consistently."""


@dataclass(frozen=True)
class NestedBESSAllocationConfig:
    project_name: str
    aoi_id: str
    scenario_id: str
    realisations: int
    pv_allocation_path: Path
    baseline_scenario_id: str
    baseline_bess_allocation_path: Path
    output_dir: Path
    attachment_rate: float = 0.40
    base_seed: int = 42

    def validate(self) -> None:
        if not self.project_name.strip():
            raise NestedBESSAllocationError("project_name must not be empty.")
        if not self.scenario_id.strip():
            raise NestedBESSAllocationError("scenario_id must not be empty.")
        if not self.baseline_scenario_id.strip():
            raise NestedBESSAllocationError("baseline_scenario_id must not be empty.")
        if self.realisations <= 0:
            raise NestedBESSAllocationError("realisations must be positive.")
        if not 0.0 <= self.attachment_rate <= 1.0:
            raise NestedBESSAllocationError("attachment_rate must lie within [0, 1].")
        if not self.pv_allocation_path.exists():
            raise FileNotFoundError(self.pv_allocation_path)
        if not self.baseline_bess_allocation_path.exists():
            csv_fallback = self.baseline_bess_allocation_path.with_suffix(".csv")
            if not csv_fallback.exists():
                raise FileNotFoundError(self.baseline_bess_allocation_path)


@dataclass(frozen=True)
class NestedBESSAllocationResult:
    allocation: pd.DataFrame
    summary: pd.DataFrame
    validation: dict[str, Any]
    output_files: dict[str, Path]


def _resolve_path(base: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _round_half_up(value: float) -> int:
    if value < 0:
        raise NestedBESSAllocationError("Counts must not be negative.")
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        fallback = path.with_suffix(".csv")
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        try:
            import geopandas as gpd
            return pd.DataFrame(gpd.read_parquet(path))
        except Exception:
            return pd.read_parquet(path)
    raise NestedBESSAllocationError(f"Unsupported table format: {path.suffix}")


def _normalise_common(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ("allocation_id", "building_id", "municipality_id", "scenario_id"):
        if column in result.columns:
            result[column] = result[column].astype(str).str.strip()
    if "realisation" in result.columns:
        result["realisation"] = pd.to_numeric(result["realisation"], errors="raise").astype(int)
    if "bus_id" in result.columns:
        result["bus_id"] = pd.to_numeric(result["bus_id"], errors="raise").astype(int)
    return result


def _stable_score(config: NestedBESSAllocationConfig, municipality_id: str, realisation: int, building_id: str) -> int:
    payload = (
        f"{config.base_seed}|BESS_NESTED|{config.aoi_id}|"
        f"{municipality_id}|{realisation}|{building_id}"
    )
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def load_nested_bess_allocation_config(path: str | Path) -> NestedBESSAllocationConfig:
    try:
        import yaml
    except ImportError as exc:
        raise NestedBESSAllocationError("PyYAML is required to read the configuration.") from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise NestedBESSAllocationError("The YAML root must be a mapping.")

    project = raw.get("project", {})
    case = raw.get("case", {})
    baseline = raw.get("baseline", {})
    paths = raw.get("paths", {})
    allocation = raw.get("allocation", {})
    base = config_path.parent

    parameters_path = _resolve_path(
        base, project.get("parameters", "../../external/seiler/scripts/parameters.py")
    )
    if parameters_path is None:
        raise NestedBESSAllocationError("project.parameters is required.")
    try:
        ctx = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get("pandapower_net_filename", "net.p"),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise NestedBESSAllocationError(str(exc)) from exc

    scenario_id = str(case.get("scenario_id", "2x_penetration_nested")).strip()
    realisations = int(case.get("realisations", 1))
    baseline_scenario_id = str(baseline.get("scenario_id", "status_quo")).strip()
    output_root = _resolve_path(base, paths.get("output_root", "../../outputs"))
    if output_root is None:
        raise NestedBESSAllocationError("paths.output_root is required.")

    pv_filename = str(paths.get("pv_allocation_filename", "pv_status_quo_allocation.parquet")).strip()
    baseline_bess_filename = str(paths.get("baseline_bess_allocation_filename", "bess_allocation.parquet")).strip()
    scenario_dir = output_root / ctx.project_name / scenario_id
    baseline_dir = output_root / ctx.project_name / baseline_scenario_id

    config = NestedBESSAllocationConfig(
        project_name=ctx.project_name,
        aoi_id=ctx.project_name,
        scenario_id=scenario_id,
        realisations=realisations,
        pv_allocation_path=(scenario_dir / "allocation" / pv_filename).resolve(),
        baseline_scenario_id=baseline_scenario_id,
        baseline_bess_allocation_path=(baseline_dir / "allocation" / baseline_bess_filename).resolve(),
        output_dir=(scenario_dir / "allocation").resolve(),
        attachment_rate=float(allocation.get("attachment_rate", 0.40)),
        base_seed=int(allocation.get("base_seed", 42)),
    )
    config.validate()
    return config


def run_nested_bess_allocation(config: NestedBESSAllocationConfig) -> NestedBESSAllocationResult:
    config.validate()
    pv = _normalise_common(_read_table(config.pv_allocation_path))
    baseline_bess = _normalise_common(_read_table(config.baseline_bess_allocation_path))

    required_pv = {"allocation_id", "building_id", "bus_id", "scenario_id", "realisation", "municipality_id"}
    missing = sorted(required_pv - set(pv.columns))
    if missing:
        raise NestedBESSAllocationError(f"Current PV allocation misses columns: {missing}")
    required_bess = {"building_id", "scenario_id", "realisation", "municipality_id"}
    missing = sorted(required_bess - set(baseline_bess.columns))
    if missing:
        raise NestedBESSAllocationError(f"Baseline BESS allocation misses columns: {missing}")

    allocation_parts: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []

    for realisation in range(config.realisations):
        current = pv.loc[
            (pv["scenario_id"] == config.scenario_id) & (pv["realisation"] == realisation)
        ].copy()
        baseline = baseline_bess.loc[
            (baseline_bess["scenario_id"] == config.baseline_scenario_id)
            & (baseline_bess["realisation"] == realisation)
        ].copy()
        if current.empty:
            raise NestedBESSAllocationError(
                f"No current PV rows for scenario={config.scenario_id!r}, realisation={realisation}."
            )
        if baseline.empty:
            raise NestedBESSAllocationError(
                f"No baseline BESS rows for scenario={config.baseline_scenario_id!r}, realisation={realisation}."
            )

        for municipality_id, candidates in current.groupby("municipality_id", sort=True):
            candidates = candidates.sort_values("building_id").reset_index(drop=True)
            baseline_m = baseline.loc[baseline["municipality_id"] == municipality_id].copy()
            baseline_buildings = set(baseline_m["building_id"].astype(str))
            current_buildings = set(candidates["building_id"].astype(str))
            missing_buildings = sorted(baseline_buildings - current_buildings)
            if missing_buildings:
                raise NestedBESSAllocationError(
                    "Current PV scenario is not nested with the baseline BESS locations. "
                    f"Missing buildings: {missing_buildings[:10]}"
                )

            target_raw = config.attachment_rate * len(candidates)
            target = _round_half_up(target_raw)
            inherited_count = len(baseline_buildings)
            if target < inherited_count:
                raise NestedBESSAllocationError(
                    f"Nested BESS target {target} is smaller than inherited baseline count "
                    f"{inherited_count} in municipality {municipality_id}."
                )

            inherited = candidates.loc[candidates["building_id"].isin(baseline_buildings)].copy()
            remaining = candidates.loc[~candidates["building_id"].isin(baseline_buildings)].copy()
            additional_needed = target - inherited_count
            if additional_needed > len(remaining):
                raise NestedBESSAllocationError(
                    f"Need {additional_needed} additional BESS but only {len(remaining)} eligible PVs remain."
                )
            if additional_needed:
                remaining["_stable_score"] = remaining["building_id"].astype(str).map(
                    lambda b: _stable_score(config, str(municipality_id), realisation, b)
                )
                additional = remaining.sort_values(["_stable_score", "building_id"]).head(additional_needed).drop(columns="_stable_score")
            else:
                additional = remaining.iloc[0:0].copy()

            inherited["nested_origin"] = "baseline_inherited"
            additional["nested_origin"] = "stable_additional"
            chosen = pd.concat([inherited, additional], ignore_index=True)
            chosen = chosen.sort_values("building_id").reset_index(drop=True)
            chosen["pv_allocation_id"] = chosen["allocation_id"].astype(str)
            chosen["allocation_id"] = [
                f"BESS_{config.aoi_id}_{municipality_id}_R{realisation:03d}_{i:05d}"
                for i in range(1, len(chosen) + 1)
            ]
            chosen["technology"] = "BESS"
            chosen["scenario_id"] = config.scenario_id
            chosen["attachment_rate"] = config.attachment_rate
            chosen["allocation_method"] = "pv_coupled_nested_from_status_quo"
            chosen["random_seed"] = config.base_seed
            chosen["baseline_scenario_id"] = config.baseline_scenario_id
            allocation_parts.append(chosen)

            summary_rows.append(
                {
                    "technology": "BESS",
                    "scenario_id": config.scenario_id,
                    "baseline_scenario_id": config.baseline_scenario_id,
                    "aoi_id": config.aoi_id,
                    "realisation": realisation,
                    "municipality_id": municipality_id,
                    "pv_candidate_count": int(len(candidates)),
                    "attachment_rate": config.attachment_rate,
                    "target_unit_count_raw": target_raw,
                    "target_unit_count": target,
                    "inherited_baseline_count": inherited_count,
                    "additional_count": additional_needed,
                    "allocated_unit_count": int(len(chosen)),
                }
            )

    allocation = pd.concat(allocation_parts, ignore_index=True) if allocation_parts else pd.DataFrame()
    summary = pd.DataFrame(summary_rows)
    if not allocation.empty and allocation["allocation_id"].duplicated().any():
        raise NestedBESSAllocationError("Nested BESS allocation_id is not unique.")

    validation = {
        "all_checks_passed": True,
        "project_name": config.project_name,
        "scenario_id": config.scenario_id,
        "baseline_scenario_id": config.baseline_scenario_id,
        "realisations": config.realisations,
        "attachment_rate": config.attachment_rate,
        "allocation_rows": int(len(allocation)),
        "baseline_locations_inherited": int((allocation.get("nested_origin", pd.Series(dtype=str)) == "baseline_inherited").sum()),
        "additional_locations_added": int((allocation.get("nested_origin", pd.Series(dtype=str)) == "stable_additional").sum()),
        "nested_location_check": True,
    }

    config.output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = config.output_dir / "bess_allocation.parquet"
    csv_path = config.output_dir / "bess_allocation.csv"
    summary_path = config.output_dir / "bess_allocation_summary.csv"
    validation_path = config.output_dir / "bess_allocation_validation.json"
    metadata_path = config.output_dir / "bess_allocation_metadata.json"

    geometry_columns = [
        c for c in allocation.columns if str(allocation[c].dtype).lower() == "geometry"
    ] if not allocation.empty else []
    export = allocation.drop(
        columns=["geometry", "centroid", "allocation_point", "geometry_wkt", *geometry_columns],
        errors="ignore",
    ).copy()
    export.to_parquet(parquet_path, index=False)
    export.to_csv(csv_path, index=False)
    summary.to_csv(summary_path, index=False)
    validation_path.write_text(json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")
    metadata = asdict(config)
    metadata = {k: str(v) if isinstance(v, Path) else v for k, v in metadata.items()}
    metadata["method_note"] = (
        "Status-quo BESS locations are inherited by building. Only the additional "
        "BESS units required by the higher PV stock are selected, using a stable "
        "building-specific ordering."
    )
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    return NestedBESSAllocationResult(
        allocation=export,
        summary=summary,
        validation=validation,
        output_files={
            "allocation_parquet": parquet_path,
            "allocation_csv": csv_path,
            "summary_csv": summary_path,
            "validation_json": validation_path,
            "metadata_json": metadata_path,
        },
    )
