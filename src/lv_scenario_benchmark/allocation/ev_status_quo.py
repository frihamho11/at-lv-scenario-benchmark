"""Polygon-based allocation of harmonised municipal BEV unit counts."""

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

# Reuse the already tested generic spatial helpers of the PV allocation.
from .pv_status_quo import (
    _assign_grid_buildings_to_municipalities,
    _derive_seed,
    _load_municipality_cache,
    _prepare_buildings,
    _resolve_path,
    _round_half_up_nonnegative,
)


class EVAllocationError(RuntimeError):
    """Raised when an EV allocation cannot be created consistently."""


EligibilityMode = Literal["all", "residential_only"]
SamplingWeight = Literal["uniform", "base_load"]


@dataclass(frozen=True)
class EVStatusQuoConfig:
    """Configuration of the municipality-to-polygon EV allocation."""

    project_name: str
    aoi_id: str
    scenario_id: str

    seiler_parameters_path: Path
    aoi_path: Path
    municipality_boundaries_path: Path
    harmonised_ev_path: Path
    grid_buildings_path: Path
    pandapower_net_path: Path
    municipality_building_cache_dir: Path
    output_dir: Path
    map_output_dir: Path

    municipality_id_column: str = "g_id"
    municipality_name_column: str | None = "g_name"
    municipality_encoding: str | None = "utf-8"

    ev_municipality_id_column: str = "municipality_id"
    ev_unit_count_column: str = "unit_count"
    ev_passenger_car_count_column: str = "passenger_car_count"
    ev_sheet: str | None = "ev_by_municipality"

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
    sampling_weight: SamplingWeight = "base_load"
    penetration_factor: float = 1.0
    base_seed: int = 42
    realisations: int = 1

    plot_enabled: bool = True
    plot_basemap: bool = True
    plot_dpi: int = 600
    plot_figsize: tuple[float, float] = (12.0, 12.0)

    def validate(self) -> None:
        if not self.project_name.strip():
            raise EVAllocationError("project_name must not be empty.")
        if self.aoi_id != self.project_name:
            raise EVAllocationError(
                "aoi_id must equal the active PROJECT from parameters.py."
            )
        if not self.scenario_id.strip():
            raise EVAllocationError("scenario_id must not be empty.")
        if self.minimum_footprint_area_m2 < 0:
            raise EVAllocationError(
                "minimum_footprint_area_m2 must be non-negative."
            )
        if self.penetration_factor <= 0:
            raise EVAllocationError(
                "penetration_factor must be greater than zero."
            )
        if self.realisations < 1:
            raise EVAllocationError("realisations must be at least 1.")
        if self.eligibility_mode not in {"all", "residential_only"}:
            raise EVAllocationError(
                "eligibility_mode must be 'all' or 'residential_only'."
            )
        if self.sampling_weight not in {"uniform", "base_load"}:
            raise EVAllocationError(
                "sampling_weight must be 'uniform' or 'base_load'."
            )
        if self.plot_dpi < 72:
            raise EVAllocationError("plot_dpi must be at least 72.")


@dataclass(frozen=True)
class EVAllocationResult:
    """Container for generated EV allocation products."""

    allocation: gpd.GeoDataFrame
    summary: pd.DataFrame
    candidates: gpd.GeoDataFrame
    validation: dict[str, Any]
    output_files: dict[str, Path]


def load_ev_config(path: str | Path) -> EVStatusQuoConfig:
    """Read the EV YAML configuration and resolve the active Seiler project."""

    try:
        import yaml
    except ImportError as exc:
        raise EVAllocationError(
            "PyYAML is required to read the configuration."
        ) from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EVAllocationError("The YAML root must be a mapping.")

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
        raise EVAllocationError("project.parameters is required.")

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get("pandapower_net_filename"),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise EVAllocationError(str(exc)) from exc

    required_paths = [
        "municipality_boundaries",
        "harmonised_ev",
        "municipality_building_cache",
        "allocation_output_root",
    ]
    missing = [key for key in required_paths if not paths.get(key)]
    if missing:
        raise EVAllocationError(f"Configuration is missing paths: {missing}")

    figsize = plotting.get("figsize", [12, 12])
    if not isinstance(figsize, (list, tuple)) or len(figsize) != 2:
        raise EVAllocationError("plotting.figsize must contain two numbers.")

    output_root = _resolve_path(base, paths["allocation_output_root"])
    if output_root is None:
        raise EVAllocationError("paths.allocation_output_root is required.")

    map_subdir = str(plotting.get("output_subdir", "ev_status_quo")).strip()
    if not map_subdir:
        raise EVAllocationError("plotting.output_subdir must not be empty.")

    scenario_output_dir = (
        output_root
        / project_context.project_name
        / map_subdir
    ).resolve()

    working_crs = spatial.get("working_crs") or project_context.working_crs
    minimum_area = allocation.get("minimum_footprint_area_m2")
    if minimum_area is None:
        minimum_area = project_context.minimum_footprint_area_m2

    config = EVStatusQuoConfig(
        project_name=project_context.project_name,
        aoi_id=project_context.project_name,
        scenario_id=str(case.get("scenario_id", "ev_status_quo")),
        seiler_parameters_path=project_context.parameters_path,
        aoi_path=project_context.aoi_path,
        municipality_boundaries_path=_resolve_path(
            base, paths["municipality_boundaries"]
        ),
        harmonised_ev_path=_resolve_path(base, paths["harmonised_ev"]),
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
        ev_municipality_id_column=str(
            columns.get("ev_municipality_id", "municipality_id")
        ),
        ev_unit_count_column=str(columns.get("ev_unit_count", "unit_count")),
        ev_passenger_car_count_column=str(columns.get("ev_passenger_car_count", "passenger_car_count")),
        ev_sheet=paths.get("harmonised_ev_sheet", "ev_by_municipality"),
        grid_building_id_column=str(columns.get("grid_building_id", "id")),
        grid_area_column=str(columns.get("grid_area", "area")),
        grid_residential_column=str(
            columns.get("grid_residential", "residential")
        ),
        bus_node_id_column=str(columns.get("bus_node_id", "node_id")),
        working_crs=str(working_crs),
        aoi_crs_if_missing=spatial.get("aoi_crs_if_missing", "EPSG:4326"),
        municipality_crs_if_missing=spatial.get(
            "municipality_crs_if_missing"
        ),
        building_crs_if_missing=spatial.get("building_crs_if_missing"),
        eligibility_mode=str(
            allocation.get("eligibility_mode", "residential_only")
        ),
        minimum_footprint_area_m2=float(minimum_area),
        sampling_weight=str(allocation.get("sampling_weight", "base_load")),
        penetration_factor=float(case.get("penetration_factor", 1.0)),
        base_seed=int(allocation.get("base_seed", 42)),
        realisations=int(allocation.get("realisations", 1)),
        plot_enabled=bool(plotting.get("enabled", True)),
        plot_basemap=bool(plotting.get("basemap", True)),
        plot_dpi=int(plotting.get("dpi", 600)),
        plot_figsize=(float(figsize[0]), float(figsize[1])),
    )
    config.validate()
    return config


def _load_harmonised_ev(config: EVStatusQuoConfig) -> pd.DataFrame:
    """Load the canonical municipality-level BEV stock table."""

    path = config.harmonised_ev_path
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        raise EVAllocationError(
            "harmonised_ev must point to the canonical output file, not a directory."
        )

    suffix = path.suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            frame = pd.read_excel(path, sheet_name=config.ev_sheet)
        elif suffix in {".parquet", ".geoparquet"}:
            frame = pd.read_parquet(path)
        elif suffix == ".csv":
            frame = pd.read_csv(path)
        else:
            raise EVAllocationError(
                f"Unsupported harmonised EV file type: {path.suffix}"
            )
    except EVAllocationError:
        raise
    except Exception as exc:
        raise EVAllocationError(f"Could not read {path}: {exc}") from exc

    frame.columns = [str(column).strip() for column in frame.columns]
    required = {
        config.ev_municipality_id_column,
        config.ev_unit_count_column,
        config.ev_passenger_car_count_column,
    }
    missing = required.difference(frame.columns)
    if missing:
        raise EVAllocationError(
            f"Harmonised EV table is missing columns: {sorted(missing)}"
        )

    frame = frame.rename(
        columns={
            config.ev_municipality_id_column: "municipality_id",
            config.ev_unit_count_column: "unit_count",
            config.ev_passenger_car_count_column: "passenger_car_count",
        }
    ).copy()
    frame["municipality_id"] = frame["municipality_id"].map(normalise_gkz)
    frame["unit_count"] = pd.to_numeric(frame["unit_count"], errors="raise")
    frame["passenger_car_count"] = pd.to_numeric(frame["passenger_car_count"], errors="raise")

    if not np.allclose(frame["unit_count"], np.round(frame["unit_count"])):
        raise EVAllocationError("Harmonised EV unit_count contains non-integers.")
    frame["unit_count"] = frame["unit_count"].astype(int)
    if (frame["unit_count"] < 0).any():
        raise EVAllocationError("Harmonised EV unit_count contains negative values.")
    if frame["municipality_id"].duplicated().any():
        duplicated = (
            frame.loc[frame["municipality_id"].duplicated(False), "municipality_id"]
            .drop_duplicates()
            .tolist()
        )
        raise EVAllocationError(
            f"Harmonised EV table contains duplicate GKZ rows: {duplicated}"
        )
    if not np.allclose(
        frame["passenger_car_count"],
        np.round(frame["passenger_car_count"]),
    ):
        raise EVAllocationError(
            "Harmonised EV passenger_car_count "
            "contains non-integers."
        )

    frame["passenger_car_count"] = (
        frame["passenger_car_count"].astype(int)
    )

    if (frame["passenger_car_count"] < 0).any():
        raise EVAllocationError(
            "Harmonised EV passenger_car_count "
            "contains negative values."
        )

    if (
        frame["unit_count"]
        > frame["passenger_car_count"]
    ).any():
        raise EVAllocationError(
            "Harmonised BEV stock exceeds total "
            "passenger-car stock."
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
            "passenger_car_count",
            "derivation_method",
            "data_quality",
        ]
    ]


def _load_building_bus_load_map(config: EVStatusQuoConfig) -> pd.DataFrame:
    """Return one pandapower bus and its base load for every grid building."""

    try:
        import pandapower as pp
    except ImportError as exc:
        raise EVAllocationError("pandapower is required for bus mapping.") from exc

    if not config.pandapower_net_path.exists():
        raise FileNotFoundError(config.pandapower_net_path)

    net = pp.from_pickle(str(config.pandapower_net_path))
    if config.bus_node_id_column not in net.bus.columns:
        raise EVAllocationError(
            f"net.bus has no column {config.bus_node_id_column!r}."
        )

    node_ids = net.bus[config.bus_node_id_column]
    if "node_type" in net.bus.columns:
        building_mask = (
            net.bus["node_type"]
            .astype(str)
            .str.strip()
            .str.upper()
            .eq("BUILDING")
        )
    else:
        building_mask = (
            node_ids.astype(str)
            .str.strip()
            .str.upper()
            .str.startswith("BD")
        )

    bus_map = net.bus.loc[
        node_ids.notna() & building_mask,
        [config.bus_node_id_column],
    ].copy()
    if bus_map.empty:
        raise EVAllocationError("No building buses were found in the network.")

    bus_map["building_id"] = (
        bus_map[config.bus_node_id_column].astype(str).str.strip()
    )
    try:
        bus_map["bus_id"] = bus_map.index.astype(int)
    except (TypeError, ValueError) as exc:
        raise EVAllocationError(
            "pandapower bus indices must be integer-like."
        ) from exc

    bus_map = bus_map.loc[
        bus_map["building_id"].ne("")
        & ~bus_map["building_id"].str.lower().isin({"nan", "none", "<na>"})
    ].copy()

    duplicate_mask = bus_map["building_id"].duplicated(keep=False)
    if duplicate_mask.any():
        duplicates = (
            bus_map.loc[duplicate_mask, "building_id"]
            .drop_duplicates()
            .tolist()
        )
        raise EVAllocationError(
            f"Multiple buses found for buildings: {duplicates[:10]}"
        )

    if not hasattr(net, "load") or net.load.empty:
        load_by_bus = pd.Series(dtype=float)
    else:
        if not {"bus", "p_mw"}.issubset(net.load.columns):
            raise EVAllocationError("net.load must contain 'bus' and 'p_mw'.")
        load_values = pd.to_numeric(net.load["p_mw"], errors="coerce")
        if load_values.isna().any() or (load_values < 0).any():
            raise EVAllocationError("net.load.p_mw contains invalid values.")
        load_by_bus = (
            net.load.assign(_p_mw=load_values)
            .groupby("bus")['_p_mw']
            .sum()
            .mul(1000.0)
        )

    bus_map["base_load_kw"] = bus_map["bus_id"].map(load_by_bus).fillna(0.0)
    return bus_map[["building_id", "bus_id", "base_load_kw"]].reset_index(
        drop=True
    )


def _attach_candidate_bus_data(
    candidates: gpd.GeoDataFrame,
    bus_map: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Attach bus/load data and return all and bus-connected candidates."""

    result = candidates.merge(
        bus_map,
        on="building_id",
        how="left",
        validate="one_to_one",
    )
    result["has_pandapower_bus"] = result["bus_id"].notna()
    result = gpd.GeoDataFrame(result, geometry="geometry", crs=candidates.crs)

    connected = result.loc[result["has_pandapower_bus"]].copy()
    connected["bus_id"] = connected["bus_id"].astype(int)
    return result, connected


def _sample_ev_units(
    candidates: gpd.GeoDataFrame,
    *,
    target: int,
    seed: int,
    sampling_weight: SamplingWeight,
) -> gpd.GeoDataFrame:
    """Sample EV home locations with replacement, allowing multiple EVs per building."""

    if target < 0:
        raise EVAllocationError(f"EV target must be non-negative, received {target}.")
    if target == 0:
        empty = candidates.iloc[0:0].copy()
        empty["selection_weight"] = pd.Series(dtype=float)
        empty["unit_at_building"] = pd.Series(dtype=int)
        return empty
    if candidates.empty:
        raise EVAllocationError("Cannot allocate EVs without bus-connected buildings.")

    ordered = candidates.sort_values("building_id").reset_index(drop=True)

    if sampling_weight == "uniform":
        probability = None
        ordered["selection_weight"] = 1.0
    else:
        weights = ordered["base_load_kw"].to_numpy(dtype=float)
        if not np.isfinite(weights).all() or (weights < 0).any():
            raise EVAllocationError("Base-load weights must be finite and non-negative.")
        if weights.sum() <= 0:
            raise EVAllocationError(
                "Base-load weighting requested, but candidate base loads sum to zero."
            )
        probability = weights / weights.sum()
        ordered["selection_weight"] = weights

    rng = np.random.default_rng(seed)
    positions = rng.choice(
        len(ordered),
        size=target,
        replace=True,
        p=probability,
    )
    selected = ordered.iloc[positions].copy()
    selected = selected.sort_values("building_id").reset_index(drop=True)
    selected["unit_at_building"] = (
        selected.groupby("building_id").cumcount() + 1
    )
    return gpd.GeoDataFrame(selected, geometry="geometry", crs=candidates.crs)


def run_ev_status_quo_allocation(
    config: EVStatusQuoConfig,
) -> EVAllocationResult:
    """Disaggregate municipal BEV stock to the AOI and allocate EVs to building buses."""

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
        raise EVAllocationError("The study polygon does not touch any municipality.")

    aoi_geometry = aoi.geometry.iloc[0]
    ev = _load_harmonised_ev(config)
    missing_ev = sorted(
        set(touched["municipality_id"]) - set(ev["municipality_id"])
    )
    if missing_ev:
        raise EVAllocationError(
            f"No harmonised EV row for touched municipalities: {missing_ev}"
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
        raise EVAllocationError("No eligible grid buildings lie inside the study polygon.")

    grid_candidates = _assign_grid_buildings_to_municipalities(
        grid_candidates,
        touched,
    )
    bus_map = _load_building_bus_load_map(config)
    all_grid_candidates, grid_candidates = _attach_candidate_bus_data(
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
        ev_row = ev.loc[ev["municipality_id"] == municipality_id].iloc[0]

        municipality_buildings = _load_municipality_cache(config, municipality_id)
        municipality_building_count = len(municipality_buildings)
        if municipality_building_count == 0:
            raise EVAllocationError(
                f"GKZ {municipality_id}: municipality building cache is empty."
            )

        aoi_building_count = int(
            municipality_buildings["allocation_point"].within(aoi_geometry).sum()
        )
        building_share = (
            aoi_building_count
            / municipality_building_count
        )

        municipality_unit_count = int(
            ev_row["unit_count"]
        )

        municipality_passenger_car_count = int(
            ev_row["passenger_car_count"]
        )

        target_raw = (
            municipality_unit_count
            * config.penetration_factor
            * building_share
        )

        target = _round_half_up_nonnegative(
            target_raw
        )

        aoi_passenger_car_count_raw = (
            municipality_passenger_car_count
            * building_share
        )

        aoi_passenger_car_count = (
            _round_half_up_nonnegative(
                aoi_passenger_car_count_raw
            )
        )

        if target > aoi_passenger_car_count:
            raise EVAllocationError(
                f"GKZ {municipality_id}: scenario "
                f"'{config.scenario_id}' requests "
                f"{target} EVs, but the estimated total "
                f"passenger-car stock in the AOI is only "
                f"{aoi_passenger_car_count}. "
                f"Penetration factor: "
                f"{config.penetration_factor}."
            )

        before_bus = all_grid_candidates.loc[
            all_grid_candidates["municipality_id"] == municipality_id
        ].copy()
        municipality_candidates = grid_candidates.loc[
            grid_candidates["municipality_id"] == municipality_id
        ].copy()

        if target > 0 and municipality_candidates.empty:
            raise EVAllocationError(
                f"GKZ {municipality_id}: target is {target}, but no eligible "
                "grid building has a pandapower bus."
            )

        for realisation in range(config.realisations):
            seed = _derive_seed(
                base_seed=config.base_seed,
                technology="EV",
                aoi_id=config.aoi_id,
                municipality_id=municipality_id,
                realisation=realisation,
            )
            selected = _sample_ev_units(
                municipality_candidates,
                target=target,
                seed=seed,
                sampling_weight=config.sampling_weight,
            )

            selected["allocation_id"] = [
                (
                    f"EV_{config.aoi_id}_{municipality_id}_"
                    f"R{realisation:03d}_{number:05d}"
                )
                for number in range(1, len(selected) + 1)
            ]
            selected["technology"] = "EV"
            selected["vehicle_category"] = "BEV_M1"
            selected["scenario_id"] = config.scenario_id
            selected["penetration_factor"] = config.penetration_factor
            selected["aoi_id"] = config.aoi_id
            selected["realisation"] = realisation
            selected["reference_date"] = ev_row["reference_date"]
            selected["municipality_unit_count"] = municipality_unit_count
            selected["municipality_building_count"] = municipality_building_count
            selected["aoi_building_count"] = aoi_building_count
            selected["municipality_passenger_car_count"] = municipality_passenger_car_count
            selected["aoi_passenger_car_count"] = aoi_passenger_car_count
            selected["target_ev_share"] = (
                target / aoi_passenger_car_count
                if aoi_passenger_car_count > 0
                else 0.0 
            )
            selected["building_share"] = building_share
            selected["target_unit_count_raw"] = target_raw
            selected["target_unit_count"] = target
            selected["allocation_method"] = (
                "municipal_residential_building_share_"
                + config.sampling_weight
                + "_sampling_with_replacement"
            )
            selected["random_seed"] = seed
            selected["charging_power_kw"] = pd.NA

            allocation_parts.append(selected)

            counts = selected.groupby("building_id").size()
            summary_rows.append(
                {
                    "technology": "EV",
                    "vehicle_category": "BEV_M1",
                    "scenario_id": config.scenario_id,
                    "penetration_factor": config.penetration_factor,
                    "aoi_id": config.aoi_id,
                    "realisation": realisation,
                    "municipality_id": municipality_id,
                    "municipality_name": ev_row["municipality_name"],
                    "reference_date": ev_row["reference_date"],
                    "municipality_unit_count": municipality_unit_count,
                    "municipality_passenger_car_count": (
                        municipality_passenger_car_count
                    ),
                    "municipality_building_count": (
                        municipality_building_count
                    ),
                    "aoi_building_count": aoi_building_count,
                    "aoi_passenger_car_count": (
                        aoi_passenger_car_count
                    ),
                    "building_share": building_share,
                    "target_ev_share": (
                        target / aoi_passenger_car_count
                        if aoi_passenger_car_count > 0
                        else 0.0
                    ),
                    "target_unit_count_raw": target_raw,
                    "target_unit_count": target,
                    "aoi_grid_building_count_before_bus_filter": len(before_bus),
                    "aoi_grid_candidate_count": len(municipality_candidates),
                    "aoi_grid_buildings_without_bus": (
                        len(before_bus) - len(municipality_candidates)
                    ),
                    "allocated_unit_count": len(selected),
                    "allocated_building_count": int(selected["building_id"].nunique()),
                    "max_units_per_building": int(counts.max()) if not counts.empty else 0,
                    "sampling_weight": config.sampling_weight,
                    "random_seed": seed,
                }
            )

    allocation = gpd.GeoDataFrame(
        pd.concat(allocation_parts, ignore_index=True),
        geometry="geometry",
        crs=config.working_crs,
    )
    summary = pd.DataFrame(summary_rows)

    if allocation["allocation_id"].duplicated().any():
        raise EVAllocationError("allocation_id is not unique.")
    if not (
        summary["allocated_unit_count"] == summary["target_unit_count"]
    ).all():
        raise EVAllocationError("At least one allocation misses its target count.")
    if not summary["building_share"].between(0, 1).all():
        raise EVAllocationError("A building share lies outside [0, 1].")
    if allocation["bus_id"].isna().any():
        raise EVAllocationError("At least one allocated EV has no bus ID.")

    selected_counts = allocation.groupby("building_id").size()
    candidates = all_grid_candidates.copy()
    candidates["allocated_ev_rows_across_realisations"] = (
        candidates["building_id"].map(selected_counts).fillna(0).astype(int)
    )

    validation = {
        "all_checks_passed": True,
        "aoi_id": config.aoi_id,
        "scenario_id": config.scenario_id,
        "penetration_factor": config.penetration_factor,
        "vehicle_category": "BEV_M1",
        "touched_municipalities": touched["municipality_id"].tolist(),
        "realisations": config.realisations,
        "eligibility_mode": config.eligibility_mode,
        "sampling_weight": config.sampling_weight,
        "multiple_evs_per_building_allowed": True,
        "charging_power_allocated": False,
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

    return EVAllocationResult(
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
    config: EVStatusQuoConfig,
) -> dict[str, Path]:
    """Write allocation, candidate, validation and metadata outputs."""

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    allocation_parquet = output_dir / "ev_status_quo_allocation.parquet"
    allocation_csv = output_dir / "ev_status_quo_allocation.csv"
    summary_csv = output_dir / "ev_status_quo_summary.csv"
    candidates_parquet = output_dir / "ev_status_quo_candidates.parquet"
    validation_json = output_dir / "ev_status_quo_validation.json"
    metadata_json = output_dir / "ev_status_quo_metadata.json"

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
        "The harmonised municipality BEV stock is scaled to the study polygon "
        "by the share of eligible residential municipality buildings inside the "
        "AOI. Integer EV units are then sampled with replacement from eligible "
        "bus-connected AOI buildings. By default, sampling probability is "
        "proportional to the existing building base load. Multiple EVs may be "
        "assigned to one building. Charging power and charging profiles are not "
        "assigned in this step."
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
