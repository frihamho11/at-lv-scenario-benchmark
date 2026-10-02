"""Polygon-based allocation of harmonised municipal heating heat-pump counts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
import json

import geopandas as gpd
import numpy as np
import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)
from lv_scenario_benchmark.spatial import (
    load_aoi,
    load_municipalities,
    normalise_gkz,
    read_vector,
    touched_municipalities,
)

# Reuse the generic spatial and pandapower helpers of the PV allocation.
from .pv_status_quo import (
    _assign_grid_buildings_to_municipalities,
    _derive_seed,
    _load_municipality_cache,
    _load_unique_building_bus_map,
    _mark_bus_availability,
    _prepare_buildings,
    _resolve_path,
    _round_half_up_nonnegative,
    _sample_buildings,
)


class HPAllocationError(RuntimeError):
    """Raised when an HP allocation cannot be created consistently."""


EligibilityMode = Literal["all", "residential_only"]
SamplingWeight = Literal["uniform", "footprint_area"]


@dataclass(frozen=True)
class HPStatusQuoConfig:
    """Configuration of the municipality-to-polygon HP allocation."""

    project_name: str
    aoi_id: str
    scenario_id: str

    seiler_parameters_path: Path
    aoi_path: Path
    municipality_boundaries_path: Path
    harmonised_hp_path: Path
    grid_buildings_path: Path
    pandapower_net_path: Path
    municipality_building_cache_dir: Path
    output_dir: Path
    map_output_dir: Path

    municipality_id_column: str = "g_id"
    municipality_name_column: str | None = "g_name"
    municipality_encoding: str | None = "utf-8"

    hp_municipality_id_column: str = "municipality_id"
    hp_unit_count_column: str = "unit_count"
    hp_sheet: str | None = "hp_by_municipality"

    grid_building_id_column: str = "id"
    grid_area_column: str = "area"
    grid_residential_column: str = "residential"
    bus_node_id_column: str = "node_id"

    working_crs: str = "EPSG:9273"
    aoi_crs_if_missing: str | None = "EPSG:4326"
    municipality_crs_if_missing: str | None = None
    building_crs_if_missing: str | None = None

    eligibility_mode: EligibilityMode = "residential_only"
    minimum_footprint_area_m2: float = 60.0
    sampling_weight: SamplingWeight = "uniform"
    penetration_factor: float = 1.0
    base_seed: int = 42
    realisations: int = 1

    plot_enabled: bool = True
    plot_basemap: bool = False
    plot_dpi: int = 600
    plot_figsize: tuple[float, float] = (12.0, 12.0)

    def validate(self) -> None:
        if not self.project_name.strip():
            raise HPAllocationError("project_name must not be empty.")
        if self.aoi_id != self.project_name:
            raise HPAllocationError(
                "aoi_id must equal the active PROJECT from parameters.py."
            )
        if not self.scenario_id.strip():
            raise HPAllocationError("scenario_id must not be empty.")
        if self.minimum_footprint_area_m2 < 0:
            raise HPAllocationError(
                "minimum_footprint_area_m2 must be non-negative."
            )
        if self.penetration_factor <= 0:
            raise HPAllocationError(
                "penetration_factor must be greater than zero."
            )
        if self.realisations < 1:
            raise HPAllocationError("realisations must be at least 1.")
        if self.eligibility_mode not in {"all", "residential_only"}:
            raise HPAllocationError(
                "eligibility_mode must be 'all' or 'residential_only'."
            )
        if self.sampling_weight not in {"uniform", "footprint_area"}:
            raise HPAllocationError(
                "sampling_weight must be 'uniform' or 'footprint_area'."
            )
        if self.plot_dpi < 72:
            raise HPAllocationError("plot_dpi must be at least 72.")


@dataclass(frozen=True)
class HPAllocationResult:
    """Container for generated HP allocation products."""

    allocation: gpd.GeoDataFrame
    summary: pd.DataFrame
    candidates: gpd.GeoDataFrame
    validation: dict[str, Any]
    output_files: dict[str, Path]


def load_hp_config(path: str | Path) -> HPStatusQuoConfig:
    """Read the HP YAML configuration and resolve the active Seiler project."""

    try:
        import yaml
    except ImportError as exc:
        raise HPAllocationError(
            "PyYAML is required to read the configuration."
        ) from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise HPAllocationError("The YAML root must be a mapping.")

    project = raw.get("project", {})
    case = raw.get("case", {})
    paths = raw.get("paths", {})
    columns = raw.get("columns", {})
    spatial = raw.get("spatial", {})
    allocation = raw.get("allocation", {})
    plotting = raw.get("plotting", {})
    base = config_path.parent

    parameters_path = _resolve_path(
        base,
        project.get(
            "parameters",
            "../../external/seiler/scripts/parameters.py",
        ),
    )
    if parameters_path is None:
        raise HPAllocationError("project.parameters is required.")

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get("pandapower_net_filename"),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise HPAllocationError(str(exc)) from exc

    required_paths = [
        "municipality_boundaries",
        "harmonised_hp",
        "municipality_building_cache",
        "allocation_output_root",
    ]
    missing = [key for key in required_paths if not paths.get(key)]
    if missing:
        raise HPAllocationError(f"Configuration is missing paths: {missing}")

    figsize = plotting.get("figsize", [12, 12])
    if not isinstance(figsize, (list, tuple)) or len(figsize) != 2:
        raise HPAllocationError("plotting.figsize must contain two numbers.")

    output_root = _resolve_path(base, paths["allocation_output_root"])
    if output_root is None:
        raise HPAllocationError("paths.allocation_output_root is required.")

    map_subdir = str(plotting.get("output_subdir", "hp_status_quo")).strip()
    if not map_subdir:
        raise HPAllocationError("plotting.output_subdir must not be empty.")

    scenario_output_dir = (
    output_root
        / project_context.project_name
        / map_subdir
    ).resolve()

    working_crs = spatial.get("working_crs") or project_context.working_crs
    minimum_area = allocation.get("minimum_footprint_area_m2")
    if minimum_area is None:
        minimum_area = project_context.minimum_footprint_area_m2

    config = HPStatusQuoConfig(
        project_name=project_context.project_name,
        aoi_id=project_context.project_name,
        scenario_id=str(case.get("scenario_id", "hp_status_quo")),
        seiler_parameters_path=project_context.parameters_path,
        aoi_path=project_context.aoi_path,
        municipality_boundaries_path=_resolve_path(
            base, paths["municipality_boundaries"]
        ),
        harmonised_hp_path=_resolve_path(base, paths["harmonised_hp"]),
        grid_buildings_path=project_context.grid_buildings_path,
        pandapower_net_path=project_context.pandapower_net_path,
        municipality_building_cache_dir=_resolve_path(
            base, paths["municipality_building_cache"]
        ),
        output_dir=(scenario_output_dir / "allocation").resolve(),
        map_output_dir=(scenario_output_dir / "figures").resolve(),
        municipality_id_column=str(columns.get("municipality_id", "g_id")),
        municipality_name_column=columns.get("municipality_name", "g_name"),
        municipality_encoding=columns.get("municipality_encoding", "utf-8"),
        hp_municipality_id_column=str(
            columns.get("hp_municipality_id", "municipality_id")
        ),
        hp_unit_count_column=str(columns.get("hp_unit_count", "unit_count")),
        hp_sheet=paths.get("harmonised_hp_sheet", "hp_by_municipality"),
        grid_building_id_column=str(columns.get("grid_building_id", "id")),
        grid_area_column=str(columns.get("grid_area", "area")),
        grid_residential_column=str(
            columns.get("grid_residential", "residential")
        ),
        bus_node_id_column=str(columns.get("bus_node_id", "node_id")),
        working_crs=str(working_crs),
        aoi_crs_if_missing=spatial.get("aoi_crs_if_missing", "EPSG:4326"),
        municipality_crs_if_missing=spatial.get("municipality_crs_if_missing"),
        building_crs_if_missing=spatial.get("building_crs_if_missing"),
        eligibility_mode=str(
            allocation.get("eligibility_mode", "residential_only")
        ),
        minimum_footprint_area_m2=float(minimum_area),
        sampling_weight=str(allocation.get("sampling_weight", "uniform")),
        penetration_factor=float(case.get("penetration_factor", 1.0)),
        base_seed=int(allocation.get("base_seed", 42)),
        realisations=int(allocation.get("realisations", 1)),
        plot_enabled=bool(plotting.get("enabled", True)),
        plot_basemap=bool(plotting.get("basemap", False)),
        plot_dpi=int(plotting.get("dpi", 600)),
        plot_figsize=(float(figsize[0]), float(figsize[1])),
    )
    config.validate()
    return config


def _load_harmonised_hp(config: HPStatusQuoConfig) -> pd.DataFrame:
    """Load the canonical municipality-level heating heat-pump stock table."""

    path = config.harmonised_hp_path
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        raise HPAllocationError(
            "harmonised_hp must point to the canonical output file, not a directory."
        )

    suffix = path.suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            frame = pd.read_excel(path, sheet_name=config.hp_sheet)
        elif suffix in {".parquet", ".geoparquet"}:
            frame = pd.read_parquet(path)
        elif suffix == ".csv":
            frame = pd.read_csv(path)
        else:
            raise HPAllocationError(
                f"Unsupported harmonised HP file type: {path.suffix}"
            )
    except HPAllocationError:
        raise
    except Exception as exc:
        raise HPAllocationError(f"Could not read {path}: {exc}") from exc

    frame.columns = [str(column).strip() for column in frame.columns]
    required = {
        config.hp_municipality_id_column,
        config.hp_unit_count_column,
    }
    missing = required.difference(frame.columns)
    if missing:
        raise HPAllocationError(
            f"Harmonised HP table is missing columns: {sorted(missing)}"
        )

    frame = frame.rename(
        columns={
            config.hp_municipality_id_column: "municipality_id",
            config.hp_unit_count_column: "unit_count",
        }
    ).copy()
    frame["municipality_id"] = frame["municipality_id"].map(normalise_gkz)
    frame["unit_count"] = pd.to_numeric(frame["unit_count"], errors="raise")

    if not np.allclose(frame["unit_count"], np.round(frame["unit_count"])):
        raise HPAllocationError("Harmonised HP unit_count contains non-integers.")
    frame["unit_count"] = frame["unit_count"].astype(int)
    if (frame["unit_count"] < 0).any():
        raise HPAllocationError("Harmonised HP unit_count contains negative values.")
    if frame["municipality_id"].duplicated().any():
        duplicated = (
            frame.loc[frame["municipality_id"].duplicated(False), "municipality_id"]
            .drop_duplicates()
            .tolist()
        )
        raise HPAllocationError(
            f"Harmonised HP table contains duplicate GKZ rows: {duplicated}"
        )

    for column in [
        "municipality_name",
        "federal_state_code",
        "reference_date",
        "derivation_method",
        "data_quality",
    ]:
        if column not in frame.columns:
            frame[column] = pd.NA

    return frame[
        [
            "municipality_id",
            "municipality_name",
            "federal_state_code",
            "reference_date",
            "unit_count",
            "derivation_method",
            "data_quality",
        ]
    ]


def run_hp_status_quo_allocation(
    config: HPStatusQuoConfig,
) -> HPAllocationResult:
    """Disaggregate municipal heating-HP stock and allocate units to buildings."""

    config.validate()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    aoi = load_aoi(
        config.aoi_path,
        aoi_id=config.aoi_id,
        working_crs=config.working_crs,
        crs_if_missing=config.aoi_crs_if_missing,
    )
    municipalities = load_municipalities(
        config.municipality_boundaries_path,
        municipality_id_column=config.municipality_id_column,
        municipality_name_column=config.municipality_name_column,
        working_crs=config.working_crs,
        crs_if_missing=config.municipality_crs_if_missing,
        encoding=config.municipality_encoding,
    )
    touched = touched_municipalities(aoi, municipalities)
    if touched.empty:
        raise HPAllocationError("The study polygon does not touch any municipality.")

    aoi_geometry = aoi.geometry.iloc[0]
    hp = _load_harmonised_hp(config)
    missing_hp = sorted(
        set(touched["municipality_id"]) - set(hp["municipality_id"])
    )
    if missing_hp:
        raise HPAllocationError(
            f"No harmonised HP row for touched municipalities: {missing_hp}"
        )

    grid_raw = read_vector(
        config.grid_buildings_path,
        crs_if_missing=config.building_crs_if_missing,
    )
    grid_candidates = _prepare_buildings(
        grid_raw,
        id_column=config.grid_building_id_column,
        area_column=config.grid_area_column,
        residential_column=config.grid_residential_column,
        config=config,
        require_unique_id=True,
        source_name="grid_buildings",
    )
    grid_candidates = grid_candidates.loc[
        grid_candidates["allocation_point"].within(aoi_geometry)
    ].copy()
    if grid_candidates.empty:
        raise HPAllocationError("No eligible grid buildings lie inside the study polygon.")

    grid_candidates = _assign_grid_buildings_to_municipalities(
        grid_candidates,
        touched,
    )
    bus_map = _load_unique_building_bus_map(config)
    all_grid_candidates, grid_candidates = _mark_bus_availability(
        grid_candidates,
        bus_map,
    )

    print("Eligible AOI grid buildings:", len(all_grid_candidates))
    print("Buildings with pandapower bus:", len(grid_candidates))
    print(
        "Buildings excluded because no bus exists:",
        int((~all_grid_candidates["has_pandapower_bus"]).sum()),
    )

    allocation_parts: list[gpd.GeoDataFrame] = []
    summary_rows: list[dict[str, Any]] = []

    for boundary_row in touched.itertuples(index=False):
        municipality_id = str(boundary_row.municipality_id)
        hp_row = hp.loc[hp["municipality_id"] == municipality_id].iloc[0]

        municipality_buildings = _load_municipality_cache(config, municipality_id)
        municipality_building_count = len(municipality_buildings)
        if municipality_building_count == 0:
            raise HPAllocationError(
                f"GKZ {municipality_id}: municipality building cache is empty."
            )

        aoi_building_count = int(
            municipality_buildings["allocation_point"].within(aoi_geometry).sum()
        )
        building_share = aoi_building_count / municipality_building_count
        municipality_unit_count = int(hp_row["unit_count"])
        target_raw = (
            municipality_unit_count
            * config.penetration_factor
            * building_share
        )
        target = _round_half_up_nonnegative(target_raw)

        before_bus = all_grid_candidates.loc[
            all_grid_candidates["municipality_id"] == municipality_id
        ].copy()
        municipality_candidates = grid_candidates.loc[
            grid_candidates["municipality_id"] == municipality_id
        ].copy()

        if target > len(municipality_candidates):
            raise HPAllocationError(
                f"GKZ {municipality_id}: scenario "
                f"{config.scenario_id!r} requests {target} HP units, "
                f"but only {len(municipality_candidates)} eligible "
                "bus-connected residential buildings are available. "
                "HP allocation allows at most one unit per building. "
                f"Penetration factor: {config.penetration_factor}."
            )

        for realisation in range(config.realisations):
            seed = _derive_seed(
                base_seed=config.base_seed,
                technology="HP",
                aoi_id=config.aoi_id,
                municipality_id=municipality_id,
                realisation=realisation,
            )
            selected = _sample_buildings(
                municipality_candidates,
                target=target,
                seed=seed,
                sampling_weight=config.sampling_weight,
            )
            selected = selected.merge(
                bus_map,
                on="building_id",
                how="left",
                validate="one_to_one",
            )
            selected["bus_id"] = selected["bus_id"].astype(int)
            selected = gpd.GeoDataFrame(
                selected,
                geometry="geometry",
                crs=config.working_crs,
            )

            selected["allocation_id"] = [
                (
                    f"HP_{config.aoi_id}_{municipality_id}_"
                    f"R{realisation:03d}_{number:05d}"
                )
                for number in range(1, len(selected) + 1)
            ]
            selected["technology"] = "HP"
            selected["hp_category"] = "heating_heat_pump"
            selected["scenario_id"] = config.scenario_id
            selected["penetration_factor"] = config.penetration_factor
            selected["aoi_id"] = config.aoi_id
            selected["realisation"] = realisation
            selected["reference_date"] = hp_row["reference_date"]
            selected["municipality_unit_count"] = municipality_unit_count
            selected["municipality_building_count"] = municipality_building_count
            selected["aoi_building_count"] = aoi_building_count
            selected["building_share"] = building_share
            selected["target_unit_count_raw"] = target_raw
            selected["target_unit_count"] = target
            selected["allocation_method"] = (
                "municipal_residential_building_share_"
                + config.sampling_weight
                + "_sampling_without_replacement"
            )
            selected["random_seed"] = seed
            selected["electrical_power_kw"] = pd.NA
            selected["thermal_power_kw"] = pd.NA
            selected["cop"] = pd.NA

            allocation_parts.append(selected)

            summary_rows.append(
                {
                    "technology": "HP",
                    "hp_category": "heating_heat_pump",
                    "scenario_id": config.scenario_id,
                    "penetration_factor": config.penetration_factor,
                    "aoi_id": config.aoi_id,
                    "realisation": realisation,
                    "municipality_id": municipality_id,
                    "municipality_name": hp_row["municipality_name"],
                    "reference_date": hp_row["reference_date"],
                    "municipality_unit_count": municipality_unit_count,
                    "municipality_building_count": municipality_building_count,
                    "aoi_building_count": aoi_building_count,
                    "building_share": building_share,
                    "target_unit_count_raw": target_raw,
                    "target_unit_count": target,
                    "aoi_grid_building_count_before_bus_filter": len(before_bus),
                    "aoi_grid_candidate_count": len(municipality_candidates),
                    "aoi_grid_buildings_without_bus": (
                        len(before_bus) - len(municipality_candidates)
                    ),
                    "allocated_unit_count": len(selected),
                    "sampling_weight": config.sampling_weight,
                    "random_seed": seed,
                }
            )

    if not allocation_parts:
        raise HPAllocationError("No allocation result was produced.")

    allocation = gpd.GeoDataFrame(
        pd.concat(allocation_parts, ignore_index=True),
        geometry="geometry",
        crs=config.working_crs,
    )
    summary = pd.DataFrame(summary_rows)

    if allocation["allocation_id"].duplicated().any():
        raise HPAllocationError("allocation_id is not unique.")
    if allocation.duplicated(
        ["realisation", "municipality_id", "building_id"]
    ).any():
        raise HPAllocationError(
            "A building received more than one HP in one realisation."
        )
    if not (
        summary["allocated_unit_count"] == summary["target_unit_count"]
    ).all():
        raise HPAllocationError("At least one allocation misses its target count.")
    if not summary["building_share"].between(0, 1).all():
        raise HPAllocationError("A building share lies outside [0, 1].")
    if allocation["bus_id"].isna().any():
        raise HPAllocationError("At least one allocated HP has no bus ID.")

    selected_counts = allocation.groupby("building_id").size()
    candidates = all_grid_candidates.copy()
    candidates["selected_across_realisations"] = (
        candidates["building_id"].map(selected_counts).fillna(0).astype(int)
    )

    validation = {
        "all_checks_passed": True,
        "aoi_id": config.aoi_id,
        "scenario_id": config.scenario_id,
        "penetration_factor": config.penetration_factor,
        "hp_category": "heating_heat_pump",
        "touched_municipalities": touched["municipality_id"].tolist(),
        "realisations": config.realisations,
        "eligibility_mode": config.eligibility_mode,
        "sampling_weight": config.sampling_weight,
        "one_hp_per_building_per_realisation": True,
        "electrical_power_allocated": False,
        "thermal_power_allocated": False,
        "cop_allocated": False,
        "profile_allocated": False,
        "bus_mapping_checked": True,
        "eligible_aoi_grid_buildings": int(len(all_grid_candidates)),
        "bus_connected_aoi_grid_buildings": int(len(grid_candidates)),
        "aoi_grid_buildings_without_bus": int(
            (~all_grid_candidates["has_pandapower_bus"]).sum()
        ),
        "allocation_rows": int(len(allocation)),
    }

    output_files = _write_outputs(
        allocation=allocation,
        summary=summary,
        candidates=candidates,
        validation=validation,
        config=config,
    )

    return HPAllocationResult(
        allocation=allocation,
        summary=summary,
        candidates=candidates,
        validation=validation,
        output_files=output_files,
    )


def _write_outputs(
    *,
    allocation: gpd.GeoDataFrame,
    summary: pd.DataFrame,
    candidates: gpd.GeoDataFrame,
    validation: dict[str, Any],
    config: HPStatusQuoConfig,
) -> dict[str, Path]:
    """Write allocation, candidate, validation and metadata outputs."""

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    allocation_parquet = output_dir / "hp_status_quo_allocation.parquet"
    allocation_csv = output_dir / "hp_status_quo_allocation.csv"
    summary_csv = output_dir / "hp_status_quo_summary.csv"
    candidates_parquet = output_dir / "hp_status_quo_candidates.parquet"
    validation_json = output_dir / "hp_status_quo_validation.json"
    metadata_json = output_dir / "hp_status_quo_metadata.json"

    allocation.to_parquet(allocation_parquet, index=False)

    csv_frame = allocation.drop(
        columns=["geometry", "allocation_point"], errors="ignore"
    ).copy()
    csv_frame["geometry_wkt"] = allocation.geometry.to_wkt()
    csv_frame.to_csv(allocation_csv, index=False)

    summary.to_csv(summary_csv, index=False)
    candidates.drop(columns="allocation_point", errors="ignore").to_parquet(
        candidates_parquet,
        index=False,
    )
    validation_json.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    metadata = asdict(config)
    for key, value in list(metadata.items()):
        if isinstance(value, Path):
            metadata[key] = str(value)
    metadata["method_note"] = (
        "The harmonised municipality stock of heating heat pumps is scaled to "
        "the study polygon by the share of eligible residential municipality "
        "buildings inside the AOI. The rounded target is sampled without "
        "replacement from eligible bus-connected residential grid buildings. "
        "The baseline uses uniform sampling because no building-level heat-pump "
        "evidence is available. At most one heating heat pump is assigned to a "
        "building in one realisation. Electrical and thermal ratings, COP and "
        "time profiles are not assigned in this step."
    )
    metadata_json.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return {
        "allocation_parquet": allocation_parquet,
        "allocation_csv": allocation_csv,
        "summary_csv": summary_csv,
        "candidates_parquet": candidates_parquet,
        "validation_json": validation_json,
        "metadata_json": metadata_json,
    }
