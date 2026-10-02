"""PV-coupled BESS allocation for the Austrian LV scenario benchmark.

Repository target:
    src/lv_scenario_benchmark/allocation/bess_status_quo.py

The allocation does not harmonise an independent municipal battery stock. Instead,
it selects a deterministic target share from PV systems that are already allocated in
one scenario/realisation. The target count is fixed per municipality and the selected
PV locations are sampled uniformly without replacement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)


class BESSAllocationError(RuntimeError):
    """Raised when PV-coupled BESS allocation cannot be completed."""


@dataclass(frozen=True)
class BESSAllocationConfig:
    """Resolved configuration for one PV-coupled BESS allocation."""

    project_name: str
    aoi_id: str
    scenario_id: str
    realisations: int
    pv_allocation_path: Path
    output_dir: Path
    attachment_rate: float = 0.40
    base_seed: int = 42

    def validate(self) -> None:
        if not self.project_name.strip():
            raise BESSAllocationError("project_name must not be empty.")
        if not self.aoi_id.strip():
            raise BESSAllocationError("aoi_id must not be empty.")
        if not self.scenario_id.strip():
            raise BESSAllocationError("scenario_id must not be empty.")
        if self.realisations <= 0:
            raise BESSAllocationError("realisations must be positive.")
        if not 0.0 <= self.attachment_rate <= 1.0:
            raise BESSAllocationError("attachment_rate must lie within [0, 1].")


@dataclass(frozen=True)
class BESSAllocationResult:
    """Tabular outputs of one BESS allocation run."""

    allocation: pd.DataFrame
    summary: pd.DataFrame
    validation: dict[str, Any]
    output_files: dict[str, Path]


def _resolve_path(base: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def round_half_up(value: float) -> int:
    """Round a non-negative count using deterministic half-up rounding."""

    if value < 0:
        raise BESSAllocationError("Counts must not be negative.")
    return int(
        Decimal(str(value)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _stable_seed(base_seed: int, *tokens: object) -> int:
    """Construct a process-independent 32-bit RNG seed."""

    payload = "|".join([str(base_seed), *(str(token) for token in tokens)])
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % (2**32)


def load_bess_allocation_config(path: str | Path) -> BESSAllocationConfig:
    """Load the BESS allocation YAML and resolve project/scenario paths."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise BESSAllocationError("PyYAML is required to read the configuration.") from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BESSAllocationError("The YAML root must be a mapping.")

    project = raw.get("project", {})
    case = raw.get("case", {})
    paths = raw.get("paths", {})
    allocation = raw.get("allocation", {})
    base = config_path.parent

    parameters_path = _resolve_path(
        base,
        project.get("parameters", "../../external/seiler/scripts/parameters.py"),
    )
    if parameters_path is None:
        raise BESSAllocationError("project.parameters is required.")

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get("pandapower_net_filename", "net.p"),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise BESSAllocationError(str(exc)) from exc

    scenario_id = str(case.get("scenario_id", "status_quo")).strip()
    realisations = int(case.get("realisations", 1))

    output_root = _resolve_path(base, paths.get("output_root", "../../outputs"))
    if output_root is None:
        raise BESSAllocationError("paths.output_root is required.")

    pv_allocation_filename = str(
        paths.get("pv_allocation_filename", "pv_status_quo_allocation.parquet")
    ).strip()
    if not pv_allocation_filename:
        raise BESSAllocationError("paths.pv_allocation_filename must not be empty.")

    scenario_allocation_dir = (
        output_root / project_context.project_name / scenario_id / "allocation"
    ).resolve()

    config = BESSAllocationConfig(
        project_name=project_context.project_name,
        aoi_id=project_context.project_name,
        scenario_id=scenario_id,
        realisations=realisations,
        pv_allocation_path=(scenario_allocation_dir / pv_allocation_filename).resolve(),
        output_dir=scenario_allocation_dir,
        attachment_rate=float(allocation.get("attachment_rate", 0.40)),
        base_seed=int(allocation.get("base_seed", 42)),
    )
    config.validate()
    return config


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        csv_fallback = path.with_suffix(".csv")
        if csv_fallback.exists():
            path = csv_fallback
        else:
            raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".parquet":
        try:
            import geopandas as gpd
        except ImportError:
            return pd.read_parquet(path)
        try:
            return pd.DataFrame(gpd.read_parquet(path))
        except Exception:
            return pd.read_parquet(path)
    raise BESSAllocationError(f"Unsupported PV allocation format: {suffix}")


def _load_pv_allocation(config: BESSAllocationConfig) -> pd.DataFrame:
    frame = _read_table(config.pv_allocation_path)

    required = {
        "allocation_id",
        "building_id",
        "bus_id",
        "scenario_id",
        "realisation",
        "municipality_id",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise BESSAllocationError(
            f"PV allocation is missing required columns: {missing}"
        )

    frame = frame.copy()
    frame["allocation_id"] = frame["allocation_id"].astype(str).str.strip()
    frame["building_id"] = frame["building_id"].astype(str).str.strip()
    frame["municipality_id"] = frame["municipality_id"].astype(str).str.strip()
    frame["scenario_id"] = frame["scenario_id"].astype(str).str.strip()
    frame["realisation"] = pd.to_numeric(
        frame["realisation"], errors="raise"
    ).astype(int)
    frame["bus_id"] = pd.to_numeric(frame["bus_id"], errors="raise").astype(int)

    invalid_text = {"", "nan", "none", "<na>"}
    for column in (
        "allocation_id",
        "building_id",
        "municipality_id",
        "scenario_id",
    ):
        if frame[column].str.lower().isin(invalid_text).any():
            raise BESSAllocationError(f"PV allocation column {column!r} is empty.")
    if (frame["realisation"] < 0).any():
        raise BESSAllocationError("PV realisation values must be non-negative.")
    if frame["allocation_id"].duplicated().any():
        raise BESSAllocationError("PV allocation_id is not globally unique.")
    if frame.duplicated(
        ["scenario_id", "realisation", "building_id"]
    ).any():
        raise BESSAllocationError(
            "PV allocation contains more than one PV unit per building and "
            "realisation."
        )

    return frame


def run_bess_allocation(config: BESSAllocationConfig) -> BESSAllocationResult:
    """Allocate BESS as a municipality-wise subset of allocated PV systems."""

    config.validate()
    pv = _load_pv_allocation(config)

    allocation_parts: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []

    for realisation in range(config.realisations):
        selected_realisation = pv.loc[
            (pv["scenario_id"] == config.scenario_id)
            & (pv["realisation"] == realisation)
        ].copy()

        if selected_realisation.empty:
            available = sorted(
                pv.loc[pv["scenario_id"] == config.scenario_id, "realisation"]
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )
            raise BESSAllocationError(
                "No PV allocation rows for "
                f"scenario={config.scenario_id!r}, realisation={realisation}. "
                f"Available realisations: {available}"
            )

        for municipality_id, candidates in selected_realisation.groupby(
            "municipality_id", sort=True
        ):
            candidates = candidates.sort_values("allocation_id").reset_index(drop=True)
            pv_count = int(len(candidates))
            target_raw = config.attachment_rate * pv_count
            target = round_half_up(target_raw)

            seed = _stable_seed(
                config.base_seed,
                "BESS",
                config.scenario_id,
                config.aoi_id,
                municipality_id,
                realisation,
            )

            if target == 0:
                chosen = candidates.iloc[0:0].copy()
            else:
                rng = np.random.default_rng(seed)
                positions = np.sort(rng.choice(pv_count, size=target, replace=False))
                chosen = candidates.iloc[positions].copy()

            if not chosen.empty:
                chosen = chosen.reset_index(drop=True)
                chosen["pv_allocation_id"] = chosen["allocation_id"].astype(str)
                chosen["allocation_id"] = [
                    (
                        f"BESS_{config.aoi_id}_{municipality_id}_"
                        f"R{realisation:03d}_{number:05d}"
                    )
                    for number in range(1, len(chosen) + 1)
                ]
                chosen["technology"] = "BESS"
                chosen["attachment_rate"] = config.attachment_rate
                chosen["allocation_method"] = (
                    "pv_coupled_uniform_sampling_without_replacement"
                )
                chosen["random_seed"] = seed
                allocation_parts.append(chosen)

            summary_rows.append(
                {
                    "technology": "BESS",
                    "scenario_id": config.scenario_id,
                    "aoi_id": config.aoi_id,
                    "realisation": realisation,
                    "municipality_id": municipality_id,
                    "pv_candidate_count": pv_count,
                    "attachment_rate": config.attachment_rate,
                    "target_unit_count_raw": target_raw,
                    "target_unit_count": target,
                    "allocated_unit_count": int(len(chosen)),
                    "sampling_weight": "uniform",
                    "random_seed": seed,
                }
            )

    summary = pd.DataFrame(summary_rows)

    if allocation_parts:
        allocation = pd.concat(allocation_parts, ignore_index=True)
    else:
        base_columns = list(pv.columns)
        allocation = pd.DataFrame(
            columns=base_columns
            + [
                "pv_allocation_id",
                "technology",
                "attachment_rate",
                "allocation_method",
                "random_seed",
            ]
        )

    if allocation["allocation_id"].duplicated().any():
        raise BESSAllocationError("BESS allocation_id is not unique.")
    if (
        "pv_allocation_id" in allocation
        and allocation["pv_allocation_id"].duplicated().any()
    ):
        raise BESSAllocationError("A PV unit received more than one BESS.")
    if "building_id" in allocation and allocation.duplicated(
        ["scenario_id", "realisation", "building_id"]
    ).any():
        raise BESSAllocationError(
            "A building received more than one BESS in one realisation."
        )
    if not summary.empty and not (
        summary["allocated_unit_count"] == summary["target_unit_count"]
    ).all():
        raise BESSAllocationError(
            "At least one BESS allocation misses its target count."
        )

    candidate_count = int(summary["pv_candidate_count"].sum())
    target_count = int(summary["target_unit_count"].sum())
    allocated_count = int(summary["allocated_unit_count"].sum())

    validation = {
        "all_checks_passed": True,
        "project_name": config.project_name,
        "scenario_id": config.scenario_id,
        "realisations": config.realisations,
        "attachment_rate": config.attachment_rate,
        "candidate_population": "already_allocated_PV_systems",
        "sampling_weight": "uniform",
        "sampling_without_replacement": True,
        "one_bess_per_pv_per_realisation": True,
        "municipality_specific_target": True,
        "rounding": "half_up",
        "pv_candidate_rows": candidate_count,
        "target_rows": target_count,
        "allocation_rows": allocated_count,
        "target_count_matches_allocation": target_count == allocated_count,
        "realised_attachment_rate": (
            allocated_count / candidate_count if candidate_count else 0.0
        ),
        "empty_allocation_is_valid": allocated_count == 0,
    }

    config.output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = config.output_dir / "bess_allocation.parquet"
    csv_path = config.output_dir / "bess_allocation.csv"
    summary_path = config.output_dir / "bess_allocation_summary.csv"
    validation_path = config.output_dir / "bess_allocation_validation.json"
    metadata_path = config.output_dir / "bess_allocation_metadata.json"

    # BESS reuses only the existing building/bus relation. Remove every spatial
    # column before writing the allocation as an ordinary tabular Parquet file.
    geometry_columns = [
        column
        for column in allocation.columns
        if str(allocation[column].dtype).lower() == "geometry"
    ]

    export = allocation.drop(
        columns=[
            "geometry",
            "centroid",
            "allocation_point",
            "geometry_wkt",
            *geometry_columns,
        ],
        errors="ignore",
    ).copy()
    export.to_parquet(parquet_path, index=False)
    export.to_csv(csv_path, index=False)
    summary.to_csv(summary_path, index=False)
    validation_path.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    metadata = asdict(config)
    metadata = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in metadata.items()
    }
    metadata["method_note"] = (
        "BESS is not independently downscaled from a municipal stock. For each "
        "municipality and PV realisation, attachment_rate times the allocated PV "
        "count is half-up rounded and sampled uniformly without replacement from "
        "those PV systems."
    )
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    output_files = {
        "allocation_parquet": parquet_path,
        "allocation_csv": csv_path,
        "summary_csv": summary_path,
        "validation_json": validation_path,
        "metadata_json": metadata_path,
    }

    return BESSAllocationResult(
        allocation=export,
        summary=summary,
        validation=validation,
        output_files=output_files,
    )
