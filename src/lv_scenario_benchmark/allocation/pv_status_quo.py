"""Polygon-based allocation of harmonised municipal PV unit counts.

The active study area is taken from ``PROJECT`` in
``external/seiler/scripts/parameters.py``. The PV configuration therefore
contains no Grossschoenau-specific project paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
import json
import math

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


class AllocationError(RuntimeError):
    """Raised when a PV allocation cannot be created consistently."""


EligibilityMode = Literal["all", "residential_only"]
SamplingWeight = Literal["uniform", "footprint_area"]


@dataclass(frozen=True)
class PVStatusQuoConfig:
    """Configuration of the municipality-to-polygon PV allocation."""

    project_name: str
    aoi_id: str
    scenario_id: str

    seiler_parameters_path: Path
    project_data_dir: Path
    project_lvgrid_dir: Path
    project_plots_dir: Path

    aoi_path: Path
    municipality_boundaries_path: Path
    harmonised_pv_path: Path
    grid_buildings_path: Path
    pandapower_net_path: Path
    municipality_building_cache_dir: Path
    osmnx_cache_dir: Path
    output_dir: Path
    map_output_dir: Path

    municipality_id_column: str = "g_id"
    municipality_name_column: str | None = "g_name"
    municipality_encoding: str | None = "utf-8"

    pv_municipality_id_column: str = "municipality_id"
    pv_unit_count_column: str = "unit_count"
    pv_sheet: str | None = None

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
    plot_basemap: bool = True
    plot_municipality_boundaries: bool = True
    plot_dpi: int = 600
    plot_figsize: tuple[float, float] = (12.0, 12.0)

    def validate(self) -> None:
        """Validate all configuration invariants.

        Raises:
            AllocationError: If an identifier, option or numeric setting is
                invalid.
        """

        if not self.project_name.strip():
            raise AllocationError("project_name must not be empty.")
        if self.aoi_id != self.project_name:
            raise AllocationError(
                "aoi_id must equal the active PROJECT from parameters.py."
            )
        if not self.scenario_id.strip():
            raise AllocationError("scenario_id must not be empty.")
        if self.minimum_footprint_area_m2 < 0:
            raise AllocationError(
                "minimum_footprint_area_m2 must be non-negative."
            )
        if self.penetration_factor <= 0:
            raise AllocationError(
                "penetration_factor must be greater than zero."
            )
        if self.realisations < 1:
            raise AllocationError("realisations must be at least 1.")
        if self.eligibility_mode not in {"all", "residential_only"}:
            raise AllocationError(
                "eligibility_mode must be 'all' or 'residential_only'."
            )
        if self.sampling_weight not in {"uniform", "footprint_area"}:
            raise AllocationError(
                "sampling_weight must be 'uniform' or 'footprint_area'."
            )
        if self.plot_dpi < 72:
            raise AllocationError("plot_dpi must be at least 72.")


@dataclass(frozen=True)
class AllocationResult:
    """Container for the generated allocation products.

    Attributes:
        allocation: Building-level PV allocations, including pandapower bus IDs.
        summary: Municipality-level derivation and validation summary.
        candidates: All eligible AOI grid buildings, including buildings that
            were excluded because no pandapower bus exists.
        validation: Machine-readable validation results.
        output_files: Paths of all generated output files.
    """

    allocation: gpd.GeoDataFrame
    summary: pd.DataFrame
    candidates: gpd.GeoDataFrame
    validation: dict[str, Any]
    output_files: dict[str, Path]


def _resolve_path(
    base_dir: Path,
    value: str | Path | None,
) -> Path | None:
    """Resolve a path relative to the YAML configuration directory.

    Args:
        base_dir: Directory containing the YAML configuration.
        value: Absolute path, relative path or ``None``.

    Returns:
        The resolved absolute path, or ``None`` when no value was supplied.
    """

    if value is None:
        return None

    path = Path(value)
    return path if path.is_absolute() else (base_dir / path).resolve()


def load_config(path: str | Path) -> PVStatusQuoConfig:
    """Read YAML configuration and resolve the active Seiler project.

    Args:
        path: Path to ``pv_status_quo.yaml``.

    Returns:
        A validated project-specific configuration.

    Raises:
        AllocationError: If the YAML structure or project configuration is
            invalid.
    """

    try:
        import yaml
    except ImportError as exc:
        raise AllocationError(
            "PyYAML is required to read the configuration."
        ) from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AllocationError("The YAML root must be a mapping.")

    project = raw.get("project", {})
    case = raw.get("case", {})
    paths = raw.get("paths", {})
    columns = raw.get("columns", {})
    spatial = raw.get("spatial", {})
    allocation = raw.get("allocation", {})
    plotting = raw.get("plotting", {})
    base = config_path.parent

    parameters_value = project.get(
        "parameters",
        "../../external/seiler/scripts/parameters.py",
    )
    parameters_path = _resolve_path(base, parameters_value)
    if parameters_path is None:
        raise AllocationError("project.parameters is required.")

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get(
                "pandapower_net_filename"
            ),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise AllocationError(str(exc)) from exc

    required_path_keys = [
        "municipality_boundaries",
        "harmonised_pv",
        "municipality_building_cache",
        "osmnx_cache",
        "allocation_output_root",
    ]
    missing_paths = [key for key in required_path_keys if not paths.get(key)]
    if missing_paths:
        raise AllocationError(
            f"Configuration is missing paths: {missing_paths}"
        )

    figsize = plotting.get("figsize", [12, 12])
    if not isinstance(figsize, (list, tuple)) or len(figsize) != 2:
        raise AllocationError("plotting.figsize must contain two numbers.")

    allocation_output_root = _resolve_path(
        base,
        paths["allocation_output_root"],
    )
    if allocation_output_root is None:
        raise AllocationError("paths.allocation_output_root is required.")

    map_subdir = str(plotting.get("output_subdir", "pv_status_quo")).strip()
    if not map_subdir:
        raise AllocationError("plotting.output_subdir must not be empty.")

    scenario_output_dir = (
        allocation_output_root
        / project_context.project_name
        / map_subdir
    ).resolve()

    working_crs_value = spatial.get("working_crs")
    if working_crs_value is None:
        working_crs_value = project_context.working_crs

    minimum_area_value = allocation.get("minimum_footprint_area_m2")
    if minimum_area_value is None:
        minimum_area_value = project_context.minimum_footprint_area_m2

    config = PVStatusQuoConfig(
        project_name=project_context.project_name,
        aoi_id=project_context.project_name,
        scenario_id=str(case.get("scenario_id", "pv_status_quo")),
        seiler_parameters_path=project_context.parameters_path,
        project_data_dir=project_context.data_dir,
        project_lvgrid_dir=project_context.lvgrid_dir,
        project_plots_dir=project_context.plots_dir,
        aoi_path=project_context.aoi_path,
        municipality_boundaries_path=_resolve_path(
            base,
            paths["municipality_boundaries"],
        ),
        harmonised_pv_path=_resolve_path(base, paths["harmonised_pv"]),
        grid_buildings_path=project_context.grid_buildings_path,
        pandapower_net_path=project_context.pandapower_net_path,
        municipality_building_cache_dir=_resolve_path(
            base,
            paths["municipality_building_cache"],
        ),
        osmnx_cache_dir=_resolve_path(base, paths["osmnx_cache"]),
        output_dir=(scenario_output_dir / "allocation").resolve(),
        map_output_dir=(scenario_output_dir / "figures").resolve(),
        municipality_id_column=str(columns.get("municipality_id", "g_id")),
        municipality_name_column=columns.get("municipality_name", "g_name"),
        municipality_encoding=columns.get(
            "municipality_encoding",
            "utf-8",
        ),
        pv_municipality_id_column=str(
            columns.get("pv_municipality_id", "municipality_id")
        ),
        pv_unit_count_column=str(
            columns.get("pv_unit_count", "unit_count")
        ),
        pv_sheet=paths.get("harmonised_pv_sheet"),
        grid_building_id_column=str(columns.get("grid_building_id", "id")),
        grid_area_column=str(columns.get("grid_area", "area")),
        grid_residential_column=str(
            columns.get("grid_residential", "residential")
        ),
        bus_node_id_column=str(columns.get("bus_node_id", "node_id")),
        working_crs=str(working_crs_value),
        aoi_crs_if_missing=spatial.get("aoi_crs_if_missing", "EPSG:4326"),
        municipality_crs_if_missing=spatial.get(
            "municipality_crs_if_missing"
        ),
        building_crs_if_missing=spatial.get("building_crs_if_missing"),
        eligibility_mode=str(
            allocation.get("eligibility_mode", "residential_only")
        ),
        minimum_footprint_area_m2=float(minimum_area_value),
        sampling_weight=str(allocation.get("sampling_weight", "uniform")),
        penetration_factor=float(case.get("penetration_factor", 1.0)),
        base_seed=int(allocation.get("base_seed", 42)),
        realisations=int(allocation.get("realisations", 1)),
        plot_enabled=bool(plotting.get("enabled", True)),
        plot_basemap=bool(plotting.get("basemap", True)),
        plot_municipality_boundaries=bool(
            plotting.get("municipality_boundaries", True)
        ),
        plot_dpi=int(plotting.get("dpi", 600)),
        plot_figsize=(float(figsize[0]), float(figsize[1])),
    )
    config.validate()
    return config


def _read_pv_candidate_file(
    path: Path,
    *,
    required_source: set[str],
    sheet: str | None,
) -> pd.DataFrame | None:
    """Read a supported file if it contains the required PV columns.

    Args:
        path: Candidate CSV, Excel or Parquet file.
        required_source: Column names that must be present.
        sheet: Optional Excel worksheet name.

    Returns:
        The matching table, or ``None`` when the file is unsupported or does
        not contain the required columns.

    Raises:
        AllocationError: If a supported file cannot be read.
    """

    suffix = path.suffix.lower()

    try:
        if suffix in {".xlsx", ".xls"}:
            workbook = pd.ExcelFile(path)
            sheets = [sheet] if sheet else workbook.sheet_names

            for sheet_name in sheets:
                candidate = pd.read_excel(
                    workbook,
                    sheet_name=sheet_name,
                )
                candidate.columns = [
                    str(column).strip()
                    for column in candidate.columns
                ]
                if required_source.issubset(candidate.columns):
                    return candidate

            return None

        if suffix in {".parquet", ".geoparquet"}:
            candidate = pd.read_parquet(path)
        elif suffix == ".csv":
            candidate = pd.read_csv(path)
        else:
            return None

    except Exception as exc:
        raise AllocationError(
            f"Could not read candidate PV file {path}: {exc}"
        ) from exc

    candidate.columns = [
        str(column).strip()
        for column in candidate.columns
    ]

    if required_source.issubset(candidate.columns):
        return candidate

    return None


def _load_harmonised_pv(
    config: PVStatusQuoConfig,
) -> pd.DataFrame:
    """Load and validate the harmonised municipality-level PV table.

    Args:
        config: Resolved workflow configuration.

    Returns:
        A normalized table with one row per municipality.

    Raises:
        AllocationError: If no unique matching source exists or the values are
            inconsistent.
        FileNotFoundError: If the configured source path does not exist.
    """

    path = config.harmonised_pv_path
    if not path.exists():
        raise FileNotFoundError(path)

    required_source = {
        config.pv_municipality_id_column,
        config.pv_unit_count_column,
    }

    if path.is_dir():
        matches: list[tuple[Path, pd.DataFrame]] = []

        for candidate_path in sorted(path.iterdir()):
            candidate = _read_pv_candidate_file(
                candidate_path,
                required_source=required_source,
                sheet=config.pv_sheet,
            )
            if candidate is not None:
                matches.append(
                    (
                        candidate_path,
                        candidate,
                    )
                )

        if len(matches) != 1:
            matched_paths = [
                str(match[0])
                for match in matches
            ]
            raise AllocationError(
                "Expected exactly one harmonised municipality PV output in "
                f"{path}, found {len(matches)}: {matched_paths}"
            )

        _, frame = matches[0]

    else:
        frame = _read_pv_candidate_file(
            path,
            required_source=required_source,
            sheet=config.pv_sheet,
        )
        if frame is None:
            raise AllocationError(
                f"No table in {path} contains "
                f"{sorted(required_source)}."
            )

    frame.columns = [
        str(column).strip()
        for column in frame.columns
    ]

    missing = required_source.difference(frame.columns)
    if missing:
        raise AllocationError(
            "Harmonised PV table is missing columns: "
            f"{sorted(missing)}"
        )

    frame = frame.rename(
        columns={
            config.pv_municipality_id_column: "municipality_id",
            config.pv_unit_count_column: "unit_count",
        }
    ).copy()

    frame["municipality_id"] = frame[
        "municipality_id"
    ].map(normalise_gkz)
    frame["unit_count"] = pd.to_numeric(
        frame["unit_count"],
        errors="raise",
    )

    if not np.allclose(
        frame["unit_count"],
        np.round(frame["unit_count"]),
    ):
        raise AllocationError(
            "Harmonised PV unit_count contains non-integers."
        )

    frame["unit_count"] = frame["unit_count"].astype(int)

    if (frame["unit_count"] < 0).any():
        raise AllocationError(
            "Harmonised PV unit_count contains negative values."
        )

    duplicate_mask = frame["municipality_id"].duplicated(
        keep=False
    )
    if duplicate_mask.any():
        duplicated = (
            frame.loc[
                duplicate_mask,
                "municipality_id",
            ]
            .drop_duplicates()
            .tolist()
        )
        raise AllocationError(
            "Harmonised PV table contains duplicate GKZ rows: "
            f"{duplicated}"
        )

    optional_columns = [
        "municipality_name",
        "federal_state_code",
        "reference_date",
        "installed_capacity_kw",
        "derivation_method",
        "data_quality",
    ]

    for column in optional_columns:
        if column not in frame.columns:
            frame[column] = pd.NA

    return frame[
        [
            "municipality_id",
            "municipality_name",
            "federal_state_code",
            "reference_date",
            "unit_count",
            "installed_capacity_kw",
            "derivation_method",
            "data_quality",
        ]
    ]


def _as_boolean(
    series: pd.Series,
    *,
    column_name: str,
) -> pd.Series:
    """Convert Boolean-like source values to a strict Boolean series.

    Args:
        series: Source values.
        column_name: Column name used in error messages.

    Returns:
        A Boolean series without missing values.

    Raises:
        AllocationError: If at least one value cannot be interpreted.
    """

    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    mapping = {
        "true": True,
        "1": True,
        "yes": True,
        "ja": True,
        "false": False,
        "0": False,
        "no": False,
        "nein": False,
    }

    converted = (
        series.astype(str)
        .str.strip()
        .str.lower()
        .map(mapping)
    )

    if converted.isna().any():
        invalid = (
            series.loc[converted.isna()]
            .drop_duplicates()
            .tolist()[:10]
        )
        raise AllocationError(
            f"Could not interpret values in "
            f"{column_name!r}: {invalid}"
        )

    return converted.astype(bool)


def _prepare_buildings(
    raw: gpd.GeoDataFrame,
    *,
    id_column: str,
    area_column: str,
    residential_column: str,
    config: PVStatusQuoConfig,
    require_unique_id: bool,
    source_name: str,
) -> gpd.GeoDataFrame:
    """Normalize and filter a building GeoDataFrame.

    The function retains valid polygon geometries, applies the configured
    footprint and residential filters, normalizes building IDs and creates one
    representative point per building for deterministic spatial membership.

    Args:
        raw: Source building geometries.
        id_column: Column containing the building identifier.
        area_column: Optional footprint-area column.
        residential_column: Residential classification column.
        config: Resolved workflow configuration.
        require_unique_id: Whether duplicate building IDs are forbidden.
        source_name: Human-readable source name for diagnostics.

    Returns:
        Eligible building polygons with ``building_id``,
        ``footprint_area_m2`` and ``allocation_point`` columns.

    Raises:
        AllocationError: If the CRS, required columns, valid geometries or
            building IDs are missing.
    """

    if raw.crs is None:
        raise AllocationError(
            f"{source_name} has no coordinate reference system."
        )

    buildings = raw.to_crs(config.working_crs).copy()
    buildings = buildings.loc[
        buildings.geometry.notna()
        & ~buildings.geometry.is_empty
        & buildings.geometry.geom_type.isin(
            [
                "Polygon",
                "MultiPolygon",
            ]
        )
    ].copy()

    if buildings.empty:
        raise AllocationError(
            f"No building polygons remain in {source_name}."
        )

    geometry_area = buildings.geometry.area

    if area_column in buildings.columns:
        source_area = pd.to_numeric(
            buildings[area_column],
            errors="coerce",
        )
        area = source_area.fillna(geometry_area)
    else:
        area = geometry_area

    buildings["footprint_area_m2"] = area
    buildings = buildings.loc[
        buildings["footprint_area_m2"].notna()
        & (
            buildings["footprint_area_m2"]
            >= config.minimum_footprint_area_m2
        )
    ].copy()

    if config.eligibility_mode == "residential_only":
        if residential_column not in buildings.columns:
            raise AllocationError(
                f"{source_name} has no column "
                f"{residential_column!r}."
            )

        residential = _as_boolean(
            buildings[residential_column],
            column_name=residential_column,
        )
        buildings = buildings.loc[residential].copy()

    if buildings.empty:
        raise AllocationError(
            f"No eligible buildings remain in {source_name}."
        )

    if id_column not in buildings.columns:
        raise AllocationError(
            f"{source_name} has no ID column {id_column!r}."
        )

    buildings["building_id"] = (
        buildings[id_column]
        .astype(str)
        .str.strip()
    )

    invalid_id = (
        buildings["building_id"].eq("")
        | buildings["building_id"].str.lower().isin(
            {
                "nan",
                "none",
                "<na>",
            }
        )
    )
    if invalid_id.any():
        raise AllocationError(
            f"{source_name} contains empty building IDs."
        )

    duplicate_mask = buildings["building_id"].duplicated(
        keep=False
    )
    if require_unique_id and duplicate_mask.any():
        duplicates = (
            buildings.loc[
                duplicate_mask,
                "building_id",
            ]
            .drop_duplicates()
            .tolist()
        )
        raise AllocationError(
            f"{source_name} contains duplicate IDs: "
            f"{duplicates[:10]}"
        )

    buildings["allocation_point"] = (
        buildings.geometry.representative_point()
    )

    return buildings


def _load_municipality_cache(
    config: PVStatusQuoConfig,
    municipality_id: str,
) -> gpd.GeoDataFrame:
    """Load the cached eligible building inventory of one municipality.

    Args:
        config: Resolved workflow configuration.
        municipality_id: Normalized municipality identifier.

    Returns:
        Prepared municipality buildings.

    Raises:
        FileNotFoundError: If the municipality cache does not exist.
        AllocationError: If the cached building data are inconsistent.
    """

    path = (
        config.municipality_building_cache_dir
        / f"municipality_{municipality_id}.parquet"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Municipality building cache is missing: {path}. "
            "Run scripts/build_municipality_buildings.py first."
        )

    raw = read_vector(
        path,
        crs_if_missing=config.building_crs_if_missing,
    )
    id_column = (
        "building_uid"
        if "building_uid" in raw.columns
        else "id"
    )

    return _prepare_buildings(
        raw,
        id_column=id_column,
        area_column="area",
        residential_column="residential",
        config=config,
        require_unique_id=True,
        source_name=f"municipality_{municipality_id}",
    )


def _assign_grid_buildings_to_municipalities(
    buildings: gpd.GeoDataFrame,
    municipalities: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Assign each AOI grid building to exactly one touched municipality.

    Representative points are used instead of polygon intersections so that
    every building receives one deterministic municipality assignment.

    Args:
        buildings: Prepared AOI grid buildings.
        municipalities: Municipality polygons touched by the AOI.

    Returns:
        Grid buildings with a normalized ``municipality_id`` column.

    Raises:
        AllocationError: If a building is assigned to zero or multiple
            municipalities.
    """

    points = gpd.GeoDataFrame(
        buildings[["building_id"]].copy(),
        geometry=buildings["allocation_point"],
        crs=buildings.crs,
    )

    joined = gpd.sjoin(
        points,
        municipalities[
            [
                "municipality_id",
                "geometry",
            ]
        ],
        how="left",
        predicate="within",
    )

    duplicate_index = joined.index.duplicated(
        keep=False
    )
    if duplicate_index.any():
        duplicated = (
            joined.loc[
                duplicate_index,
                "building_id",
            ]
            .drop_duplicates()
            .tolist()
        )
        raise AllocationError(
            "Grid buildings were assigned to multiple "
            "municipalities: "
            f"{duplicated[:10]}"
        )

    joined = joined.reindex(buildings.index)

    if joined["municipality_id"].isna().any():
        missing = (
            joined.loc[
                joined["municipality_id"].isna(),
                "building_id",
            ]
            .drop_duplicates()
            .tolist()
        )
        raise AllocationError(
            "Eligible grid buildings could not be assigned "
            "to a touched GKZ. "
            f"Examples: {missing[:10]}"
        )

    result = buildings.copy()
    result["municipality_id"] = (
        joined["municipality_id"].to_numpy()
    )

    return result


def _round_half_up_nonnegative(
    value: float,
) -> int:
    """Round a finite non-negative value using half-up semantics.

    Args:
        value: Value to round.

    Returns:
        The rounded non-negative integer.

    Raises:
        AllocationError: If the value is negative or non-finite.
    """

    if value < 0 or not math.isfinite(value):
        raise AllocationError(
            f"Cannot round invalid target value: {value}"
        )

    return int(math.floor(value + 0.5))


def _derive_seed(
    *,
    base_seed: int,
    technology: str,
    aoi_id: str,
    municipality_id: str,
    realisation: int,
) -> int:
    """Derive a deterministic 64-bit seed for one technology realisation.

    The scenario identifier is intentionally excluded. Therefore the same
    realisation number produces the same spatial random order across different
    penetration scenarios.
    """

    text = (
        f"{base_seed}|{technology}|{aoi_id}|"
        f"{municipality_id}|{realisation}"
    )
    digest = sha256(text.encode("utf-8")).digest()

    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    )


def _sample_buildings(
    candidates: gpd.GeoDataFrame,
    *,
    target: int,
    seed: int,
    sampling_weight: SamplingWeight,
) -> gpd.GeoDataFrame:
    """Sample a fixed number of buildings without replacement.

    Args:
        candidates: Bus-connected grid-building candidates.
        target: Number of buildings to select.
        seed: Deterministic random seed.
        sampling_weight: Uniform or footprint-area-weighted sampling.

    Returns:
        Selected candidate rows with a ``selection_weight`` column.

    Raises:
        AllocationError: If the target is invalid or the sampling weights are
            not finite and positive.
    """

    if target < 0:
        raise AllocationError(
            f"PV target must be non-negative, received {target}."
        )

    if target > len(candidates):
        raise AllocationError(
            f"PV target {target} exceeds candidate count "
            f"{len(candidates)}."
        )

    ordered = (
        candidates.sort_values("building_id")
        .reset_index(drop=True)
    )

    if sampling_weight == "uniform":
        ordered["selection_weight"] = 1.0
        probability = None

    else:
        weights = ordered[
            "footprint_area_m2"
        ].to_numpy(dtype=float)

        if (
            not np.isfinite(weights).all()
            or (weights <= 0).any()
        ):
            raise AllocationError(
                "Footprint-area weights must be finite "
                "and positive."
            )

        probability = weights / weights.sum()
        ordered["selection_weight"] = weights

    if target == 0:
        return ordered.iloc[0:0].copy()

    rng = np.random.default_rng(seed)
    positions = rng.choice(
        len(ordered),
        size=len(ordered),
        replace=False,
        p=probability,
    )[:target]

    return ordered.iloc[
        np.sort(positions)
    ].copy()

def _load_unique_building_bus_map(
    config: PVStatusQuoConfig,
) -> pd.DataFrame:
    """Load a one-to-one building-to-bus mapping from pandapower.

    The explicit ``node_type == "BUILDING"`` classification is preferred.
    When the column is unavailable, node IDs beginning with ``BD`` are used as
    a fallback.

    Args:
        config: Resolved workflow configuration.

    Returns:
        A table containing ``building_id`` and integer ``bus_id`` columns.

    Raises:
        AllocationError: If pandapower is unavailable, required bus columns are
            missing, no building buses are found, or a building maps to
            multiple buses.
        FileNotFoundError: If the pandapower network does not exist.
    """

    try:
        import pandapower as pp
    except ImportError as exc:
        raise AllocationError(
            "pandapower is required for bus mapping."
        ) from exc

    if not config.pandapower_net_path.exists():
        raise FileNotFoundError(
            config.pandapower_net_path
        )

    net = pp.from_pickle(
        str(config.pandapower_net_path)
    )

    if config.bus_node_id_column not in net.bus.columns:
        raise AllocationError(
            "net.bus has no column "
            f"{config.bus_node_id_column!r}."
        )

    node_ids = net.bus[config.bus_node_id_column]
    valid_node_id = node_ids.notna()

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
        valid_node_id & building_mask,
        [config.bus_node_id_column],
    ].copy()

    if bus_map.empty:
        raise AllocationError(
            "No building buses were found in the "
            "pandapower network."
        )

    bus_map["building_id"] = (
        bus_map[config.bus_node_id_column]
        .astype(str)
        .str.strip()
    )

    try:
        bus_map["bus_id"] = (
            bus_map.index.astype(int)
        )
    except (TypeError, ValueError) as exc:
        raise AllocationError(
            "pandapower bus indices must be integer-like."
        ) from exc

    invalid_id = (
        bus_map["building_id"].eq("")
        | bus_map["building_id"].str.lower().isin(
            {
                "nan",
                "none",
                "<na>",
            }
        )
    )
    bus_map = bus_map.loc[~invalid_id].copy()

    duplicate_mask = bus_map[
        "building_id"
    ].duplicated(keep=False)

    if duplicate_mask.any():
        duplicates = (
            bus_map.loc[
                duplicate_mask,
                "building_id",
            ]
            .drop_duplicates()
            .tolist()
        )
        raise AllocationError(
            "Multiple buses found for buildings: "
            f"{duplicates[:10]}"
        )

    return (
        bus_map[
            [
                "building_id",
                "bus_id",
            ]
        ]
        .sort_values("building_id")
        .reset_index(drop=True)
    )


def _mark_bus_availability(
    candidates: gpd.GeoDataFrame,
    bus_map: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Mark candidates according to pandapower bus availability.

    Args:
        candidates: Eligible AOI grid buildings.
        bus_map: One-to-one building-to-bus mapping.

    Returns:
        A tuple containing all candidates with a Boolean
        ``has_pandapower_bus`` column and the subset that has a valid bus.

    Raises:
        AllocationError: If the candidate table has no ``building_id`` column.
    """

    if "building_id" not in candidates.columns:
        raise AllocationError(
            "Grid candidates have no 'building_id' column."
        )

    bus_building_ids = set(
        bus_map["building_id"]
    )

    all_candidates = candidates.copy()
    all_candidates["has_pandapower_bus"] = (
        all_candidates["building_id"].isin(
            bus_building_ids
        )
    )

    candidates_with_bus = all_candidates.loc[
        all_candidates["has_pandapower_bus"]
    ].copy()

    return (
        all_candidates,
        candidates_with_bus,
    )

def _attach_bus_indices(
    allocation: gpd.GeoDataFrame,
    bus_map: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Attach the unique pandapower bus to every allocated building.

    Args:
        allocation: Selected PV allocation rows.
        bus_map: One-to-one building-to-bus mapping.

    Returns:
        Allocation rows with an integer ``bus_id`` column.

    Raises:
        AllocationError: If building IDs are missing or at least one selected
            building has no pandapower bus.
    """

    if "building_id" not in allocation.columns:
        raise AllocationError(
            "Allocation has no 'building_id' column."
        )

    result = allocation.drop(
        columns=["bus_id"],
        errors="ignore",
    ).merge(
        bus_map,
        on="building_id",
        how="left",
        validate="many_to_one",
    )

    if result["bus_id"].isna().any():
        missing = (
            result.loc[
                result["bus_id"].isna(),
                "building_id",
            ]
            .drop_duplicates()
            .tolist()
        )
        raise AllocationError(
            "No pandapower bus found for buildings: "
            f"{missing[:10]}"
        )

    result["bus_id"] = result["bus_id"].astype(int)

    return gpd.GeoDataFrame(
        result,
        geometry="geometry",
        crs=allocation.crs,
    )


def run_pv_status_quo_allocation(
    config: PVStatusQuoConfig,
) -> AllocationResult:
    """Run the complete municipality-to-AOI PV allocation workflow.

    For every municipality touched by the study polygon, the municipal PV unit
    count is multiplied by the share of eligible municipality buildings whose
    representative points lie inside the AOI. The rounded target is sampled
    without replacement from eligible AOI grid buildings that have a unique
    pandapower connection bus.

    Args:
        config: Fully resolved workflow configuration.

    Returns:
        Generated allocation, summary, candidate and validation products.

    Raises:
        AllocationError: If input data are inconsistent, the target exceeds the
            available bus-connected grid buildings, or a validation check
            fails.
        FileNotFoundError: If a required input or municipality cache is missing.
    """

    config.validate()
    config.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    aoi = load_aoi(
        config.aoi_path,
        aoi_id=config.aoi_id,
        working_crs=config.working_crs,
        crs_if_missing=config.aoi_crs_if_missing,
    )
    municipalities = load_municipalities(
        config.municipality_boundaries_path,
        municipality_id_column=(
            config.municipality_id_column
        ),
        municipality_name_column=(
            config.municipality_name_column
        ),
        working_crs=config.working_crs,
        crs_if_missing=(
            config.municipality_crs_if_missing
        ),
        encoding=config.municipality_encoding,
    )
    touched = touched_municipalities(
        aoi,
        municipalities,
    )

    if touched.empty:
        raise AllocationError(
            "The study polygon does not touch any municipality."
        )

    aoi_geometry = aoi.geometry.iloc[0]

    pv = _load_harmonised_pv(config)
    missing_pv = sorted(
        set(touched["municipality_id"])
        - set(pv["municipality_id"])
    )
    if missing_pv:
        raise AllocationError(
            "No harmonised PV row for touched municipalities: "
            f"{missing_pv}"
        )

    grid_raw = read_vector(
        config.grid_buildings_path,
        crs_if_missing=config.building_crs_if_missing,
    )
    grid_candidates = _prepare_buildings(
        grid_raw,
        id_column=config.grid_building_id_column,
        area_column=config.grid_area_column,
        residential_column=(
            config.grid_residential_column
        ),
        config=config,
        require_unique_id=True,
        source_name="grid_buildings",
    )
    grid_candidates = grid_candidates.loc[
        grid_candidates["allocation_point"].within(
            aoi_geometry
        )
    ].copy()

    if grid_candidates.empty:
        raise AllocationError(
            "No eligible grid buildings lie inside "
            "the study polygon."
        )

    grid_candidates = (
        _assign_grid_buildings_to_municipalities(
            grid_candidates,
            touched,
        )
    )

    building_bus_map = _load_unique_building_bus_map(
        config
    )
    (
        all_grid_candidates,
        grid_candidates,
    ) = _mark_bus_availability(
        grid_candidates,
        building_bus_map,
    )

    grid_candidates_without_bus = (
        all_grid_candidates.loc[
            ~all_grid_candidates[
                "has_pandapower_bus"
            ]
        ].copy()
    )

    print(
        "Eligible AOI grid buildings:",
        len(all_grid_candidates),
    )
    print(
        "Buildings with pandapower bus:",
        len(grid_candidates),
    )
    print(
        "Buildings excluded because no bus exists:",
        len(grid_candidates_without_bus),
    )

    if grid_candidates.empty:
        raise AllocationError(
            "No eligible AOI grid building has a "
            "pandapower connection bus."
        )

    allocation_parts: list[gpd.GeoDataFrame] = []
    summary_rows: list[dict[str, Any]] = []

    for boundary_row in touched.itertuples(
        index=False
    ):
        municipality_id = str(
            boundary_row.municipality_id
        )
        pv_row = pv.loc[
            pv["municipality_id"] == municipality_id
        ].iloc[0]

        municipality_buildings = (
            _load_municipality_cache(
                config,
                municipality_id,
            )
        )
        municipality_building_count = len(
            municipality_buildings
        )

        if municipality_building_count == 0:
            raise AllocationError(
                f"GKZ {municipality_id}: municipality "
                "building cache contains no eligible buildings."
            )

        municipality_aoi_buildings = (
            municipality_buildings.loc[
                municipality_buildings[
                    "allocation_point"
                ].within(aoi_geometry)
            ].copy()
        )
        aoi_building_count = len(
            municipality_aoi_buildings
        )

        building_share = (
            aoi_building_count
            / municipality_building_count
        )
        municipality_unit_count = int(
            pv_row["unit_count"]
        )
        target_raw = (
            municipality_unit_count
            * config.penetration_factor
            * building_share
        )
        target = _round_half_up_nonnegative(
            target_raw
        )

        municipality_candidates_before_bus_filter = (
            all_grid_candidates.loc[
                all_grid_candidates[
                    "municipality_id"
                ] == municipality_id
            ].copy()
        )
        municipality_candidates = (
            grid_candidates.loc[
                grid_candidates[
                    "municipality_id"
                ] == municipality_id
            ].copy()
        )
        municipality_candidates_without_bus = (
            len(
                municipality_candidates_before_bus_filter
            )
            - len(municipality_candidates)
        )

        if target > len(municipality_candidates):
            raise AllocationError(
                f"GKZ {municipality_id}: scenario "
                f"{config.scenario_id!r} requests {target} PV units, "
                f"but only {len(municipality_candidates)} eligible "
                "bus-connected buildings are available. "
                "PV allocation allows at most one unit per building. "
                f"Penetration factor: {config.penetration_factor}."
            )

        for realisation in range(
            config.realisations
        ):
            seed = _derive_seed(
                base_seed=config.base_seed,
                technology="PV",
                aoi_id=config.aoi_id,
                municipality_id=municipality_id,
                realisation=realisation,
            )
            selected = _sample_buildings(
                municipality_candidates,
                target=target,
                seed=seed,
                sampling_weight=(
                    config.sampling_weight
                ),
            )

            selected["allocation_id"] = [
                (
                    f"PV_{config.aoi_id}_"
                    f"{municipality_id}_"
                    f"R{realisation:03d}_"
                    f"{number:05d}"
                )
                for number in range(
                    1,
                    len(selected) + 1,
                )
            ]
            selected["technology"] = "PV"
            selected["scenario_id"] = (
                config.scenario_id
            )
            selected["penetration_factor"] = (
                config.penetration_factor
            )
            selected["aoi_id"] = config.aoi_id
            selected["realisation"] = realisation
            selected["reference_date"] = (
                pv_row["reference_date"]
            )
            selected["municipality_unit_count"] = (
                municipality_unit_count
            )
            selected[
                "municipality_building_count"
            ] = municipality_building_count
            selected["aoi_building_count"] = (
                aoi_building_count
            )
            selected["building_share"] = (
                building_share
            )
            selected["target_unit_count_raw"] = (
                target_raw
            )
            selected["target_unit_count"] = target
            selected["allocation_method"] = (
                "municipal_building_share_"
                + config.sampling_weight
                + "_sampling_without_replacement"
            )
            selected["random_seed"] = seed
            selected["installed_capacity_kw"] = (
                pd.NA
            )

            allocation_parts.append(selected)

            summary_rows.append(
                {
                    "technology": "PV",
                    "scenario_id": (
                        config.scenario_id
                    ),
                    "penetration_factor": (
                        config.penetration_factor
                    ),
                    "aoi_id": config.aoi_id,
                    "realisation": realisation,
                    "municipality_id": (
                        municipality_id
                    ),
                    "municipality_name": (
                        pv_row["municipality_name"]
                    ),
                    "reference_date": (
                        pv_row["reference_date"]
                    ),
                    "municipality_unit_count": (
                        municipality_unit_count
                    ),
                    "municipality_building_count": (
                        municipality_building_count
                    ),
                    "aoi_building_count": (
                        aoi_building_count
                    ),
                    "aoi_grid_building_count_before_bus_filter": len(
                        municipality_candidates_before_bus_filter
                    ),
                    "aoi_grid_candidate_count": len(
                        municipality_candidates
                    ),
                    "aoi_grid_buildings_without_bus": (
                        municipality_candidates_without_bus
                    ),
                    "building_share": building_share,
                    "target_unit_count_raw": (
                        target_raw
                    ),
                    "target_unit_count": target,
                    "allocated_unit_count": len(
                        selected
                    ),
                    "sampling_weight": (
                        config.sampling_weight
                    ),
                    "random_seed": seed,
                }
            )

    if not allocation_parts:
        raise AllocationError(
            "No allocation result was produced."
        )

    allocation = gpd.GeoDataFrame(
        pd.concat(
            allocation_parts,
            ignore_index=True,
        ),
        geometry="geometry",
        crs=config.working_crs,
    )
    allocation = _attach_bus_indices(
        allocation,
        building_bus_map,
    )
    summary = pd.DataFrame(summary_rows)

    if allocation["allocation_id"].duplicated().any():
        raise AllocationError(
            "allocation_id is not unique."
        )

    duplicate_assignment = allocation.duplicated(
        [
            "realisation",
            "municipality_id",
            "building_id",
        ]
    )
    if duplicate_assignment.any():
        raise AllocationError(
            "A building received more than one PV unit "
            "in one realisation."
        )

    if not (
        summary["allocated_unit_count"]
        == summary["target_unit_count"]
    ).all():
        raise AllocationError(
            "At least one allocation misses its "
            "target count."
        )

    if not summary["building_share"].between(
        0,
        1,
    ).all():
        raise AllocationError(
            "A building share lies outside [0, 1]."
        )

    if allocation["bus_id"].isna().any():
        raise AllocationError(
            "At least one allocated building has no bus ID."
        )

    selected_counts = allocation.groupby(
        "building_id"
    ).size()

    candidates = all_grid_candidates.copy()
    candidates[
        "selected_across_realisations"
    ] = (
        candidates["building_id"]
        .map(selected_counts)
        .fillna(0)
        .astype(int)
    )

    validation = {
        "all_checks_passed": True,
        "aoi_id": config.aoi_id,
        "scenario_id": config.scenario_id,
        "penetration_factor": config.penetration_factor,
        "touched_municipalities": (
            touched["municipality_id"].tolist()
        ),
        "realisations": config.realisations,
        "eligibility_mode": (
            config.eligibility_mode
        ),
        "sampling_weight": (
            config.sampling_weight
        ),
        "one_unit_per_building_per_realisation": True,
        "capacity_allocated": False,
        "profile_allocated": False,
        "bus_mapping_checked": True,
        "eligible_aoi_grid_buildings": int(
            len(all_grid_candidates)
        ),
        "bus_connected_aoi_grid_buildings": int(
            len(grid_candidates)
        ),
        "aoi_grid_buildings_without_bus": int(
            len(grid_candidates_without_bus)
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

    return AllocationResult(
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
    config: PVStatusQuoConfig,
) -> dict[str, Path]:
    """Write allocation, candidate, validation and metadata outputs.

    Args:
        allocation: Selected PV allocation rows with bus IDs.
        summary: Municipality-level allocation summary.
        candidates: All eligible AOI grid buildings, including buildings
            excluded because no pandapower bus exists.
        validation: Machine-readable validation results.
        config: Resolved workflow configuration.

    Returns:
        A mapping from logical output names to written file paths.
    """

    output_dir = config.output_dir
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    allocation_parquet = (
        output_dir
        / "pv_status_quo_allocation.parquet"
    )
    allocation_csv = (
        output_dir
        / "pv_status_quo_allocation.csv"
    )
    summary_csv = (
        output_dir
        / "pv_status_quo_summary.csv"
    )
    candidates_parquet = (
        output_dir
        / "pv_status_quo_candidates.parquet"
    )
    validation_json = (
        output_dir
        / "pv_status_quo_validation.json"
    )
    metadata_json = (
        output_dir
        / "pv_status_quo_metadata.json"
    )

    allocation.to_parquet(
        allocation_parquet,
        index=False,
    )

    allocation_csv_frame = allocation.drop(
        columns=[
            "geometry",
            "allocation_point",
        ],
        errors="ignore",
    ).copy()
    allocation_csv_frame["geometry_wkt"] = (
        allocation.geometry.to_wkt()
    )
    allocation_csv_frame.to_csv(
        allocation_csv,
        index=False,
    )

    summary.to_csv(
        summary_csv,
        index=False,
    )

    candidates.drop(
        columns="allocation_point",
        errors="ignore",
    ).to_parquet(
        candidates_parquet,
        index=False,
    )

    validation_json.write_text(
        json.dumps(
            validation,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    metadata = asdict(config)
    for key, value in list(metadata.items()):
        if isinstance(value, Path):
            metadata[key] = str(value)

    metadata["method_note"] = (
        "The municipal PV unit count is multiplied by the "
        "share of eligible municipality buildings whose "
        "representative points lie inside the study polygon. "
        "The rounded target is sampled without replacement "
        "from eligible AOI grid buildings that have a unique "
        "pandapower connection bus. Buildings without a bus "
        "remain in the candidate output for documentation but "
        "cannot receive a PV unit. Capacity and time profiles "
        "are not assigned."
    )

    metadata_json.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
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