"""Nested EV integration with status-quo template inheritance.

The spatial EV allocation determines where each electric vehicle is connected. This
module adds one dedicated pandapower ``load`` per allocated EV and assigns a
reproducible SimBench household-charging template consisting of

* a normalized active-power profile,
* a normalized reactive-power profile,
* the SimBench reference load's maximum active power, and
* the SimBench reference load's maximum reactive power.

The default reference pool is built from the three SimBench rural LV grid
classes of scenario 2. Sampling a complete reference record preserves the
joint SimBench relationship between profile type and maximum power instead of
inventing a separate fixed charging-station rating.

Two ``ConstControl`` objects are attached to the enriched net (p_mw and,
optionally, q_mvar). The base ``net.p`` is loaded as immutable input and is
never overwritten.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)
from lv_scenario_benchmark.time_axis import (
    TimeAxisError,
    align_nearest_same_weekday_to_reference_year,
)


class EVPandapowerIntegrationError(RuntimeError):
    """Raised when EV/pandapower/SimBench integration is inconsistent."""


DEFAULT_SIMBENCH_RURAL_LV_CODES = (
    "1-LV-rural1--2-sw",
    "1-LV-rural2--2-sw",
    "1-LV-rural3--2-sw",
)

DEFAULT_EV_PROFILE_PREFIXES = ("HLS_",)


@dataclass(frozen=True)
class EVPandapowerConfig:
    """Resolved configuration for EV-to-pandapower time-series integration."""

    project_name: str
    scenario_id: str
    realisation: int

    seiler_parameters_path: Path
    base_net_path: Path
    ev_allocation_path: Path
    output_net_path: Path
    output_dir: Path

    baseline_scenario_id: str
    baseline_mapping_path: Path

    in_service: bool = True
    check_building_bus_match: bool = True

    simbench_scenario: int = 2
    simbench_source_grid_codes: tuple[str, ...] = DEFAULT_SIMBENCH_RURAL_LV_CODES
    simbench_ev_profile_prefixes: tuple[str, ...] = DEFAULT_EV_PROFILE_PREFIXES
    simbench_expected_ev_profile_count: int = 6
    profile_assignment_seed: int = 20260813
    profile_weighting: str = "uniform"
    use_reactive_power: bool = True
    reference_year: int = 2025
    time_alignment_method: str = "nearest_same_weekday"
    time_step_minutes: int = 15

    def validate(self) -> None:
        if not self.project_name.strip():
            raise EVPandapowerIntegrationError("project_name must not be empty.")
        if not self.scenario_id.strip():
            raise EVPandapowerIntegrationError("scenario_id must not be empty.")
        if self.realisation < 0:
            raise EVPandapowerIntegrationError("realisation must be non-negative.")
        if not self.baseline_scenario_id.strip():
            raise EVPandapowerIntegrationError("baseline_scenario_id must not be empty.")
        if (
            self.scenario_id != self.baseline_scenario_id
            and not self.baseline_mapping_path.exists()
        ):
            raise FileNotFoundError(self.baseline_mapping_path)
        if self.output_net_path.resolve() == self.base_net_path.resolve():
            raise EVPandapowerIntegrationError(
                "The enriched EV network must not overwrite the base net.p."
            )
        if self.simbench_scenario not in {0, 1, 2}:
            raise EVPandapowerIntegrationError(
                "simbench_scenario must be one of 0, 1 or 2."
            )
        if not self.simbench_source_grid_codes:
            raise EVPandapowerIntegrationError(
                "At least one SimBench source grid code is required."
            )
        for code in self.simbench_source_grid_codes:
            parts = str(code).split("-")
            try:
                code_scenario = int(parts[-2])
            except (ValueError, IndexError) as exc:
                raise EVPandapowerIntegrationError(
                    f"Cannot read scenario from SimBench code {code!r}."
                ) from exc
            if code_scenario != self.simbench_scenario:
                raise EVPandapowerIntegrationError(
                    f"SimBench code {code!r} belongs to scenario {code_scenario}, "
                    f"but simbench_scenario={self.simbench_scenario}."
                )
        if not self.simbench_ev_profile_prefixes:
            raise EVPandapowerIntegrationError(
                "At least one SimBench home-charging EV profile prefix is required."
            )
        if self.simbench_expected_ev_profile_count <= 0:
            raise EVPandapowerIntegrationError(
                "simbench_expected_ev_profile_count must be positive."
            )
        if self.profile_assignment_seed < 0:
            raise EVPandapowerIntegrationError(
                "profile_assignment_seed must be non-negative."
            )
        if self.profile_weighting not in {"uniform", "reference_rows"}:
            raise EVPandapowerIntegrationError(
                "profile_weighting must be 'uniform' or 'reference_rows'."
            )
        if self.reference_year < 1900:
            raise EVPandapowerIntegrationError("reference_year must be >= 1900.")
        if self.time_alignment_method not in {"none", "nearest_same_weekday"}:
            raise EVPandapowerIntegrationError(
                "time_alignment_method must be 'none' or 'nearest_same_weekday'."
            )
        if self.time_step_minutes <= 0:
            raise EVPandapowerIntegrationError("time_step_minutes must be positive.")


@dataclass(frozen=True)
class EVPandapowerIntegrationResult:
    """Products created by EV + SimBench pandapower integration."""

    ev_count: int
    base_load_count: int
    enriched_load_count: int
    n_time_steps: int
    n_profiles_used: int
    output_net_path: Path
    output_files: dict[str, Path]
    validation: dict[str, Any]


def _resolve_path(base: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _as_tuple_of_strings(value: Any, default: Iterable[str]) -> tuple[str, ...]:
    if value is None:
        return tuple(str(v) for v in default)
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise EVPandapowerIntegrationError("Expected a string or list of strings.")
    result = tuple(str(v).strip() for v in value if str(v).strip())
    if not result:
        raise EVPandapowerIntegrationError("Configured string list must not be empty.")
    return result


def load_ev_pandapower_config(path: str | Path) -> EVPandapowerConfig:
    """Load YAML configuration and derive project-specific paths."""

    try:
        import yaml
    except ImportError as exc:
        raise EVPandapowerIntegrationError(
            "PyYAML is required to read the configuration."
        ) from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EVPandapowerIntegrationError("The YAML root must be a mapping.")

    project = raw.get("project", {})
    case = raw.get("case", {})
    paths = raw.get("paths", {})
    integration = raw.get("integration", {})
    simbench_cfg = raw.get("simbench", {})
    baseline_cfg = raw.get("baseline", {})
    time_alignment = raw.get("time_alignment", {})
    base = config_path.parent

    parameters_path = _resolve_path(
        base,
        project.get("parameters", "../../external/seiler/scripts/parameters.py"),
    )
    if parameters_path is None:
        raise EVPandapowerIntegrationError("project.parameters is required.")

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get("pandapower_net_filename", "net.p"),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise EVPandapowerIntegrationError(str(exc)) from exc

    scenario_id = str(case.get("scenario_id", "ev_status_quo")).strip()
    realisation = int(case.get("realisation", 0))

    allocation_output_root = _resolve_path(
        base,
        paths.get("allocation_output_root", "../../outputs"),
    )
    integration_output_root = _resolve_path(
        base,
        paths.get("integration_output_root", "../../outputs"),
    )
    if allocation_output_root is None or integration_output_root is None:
        raise EVPandapowerIntegrationError(
            "paths.allocation_output_root and paths.integration_output_root are required."
        )

    allocation_filename = str(
        paths.get("allocation_filename", "ev_status_quo_allocation.parquet")
    ).strip()
    if not allocation_filename:
        raise EVPandapowerIntegrationError("paths.allocation_filename must not be empty.")

    output_net_filename = str(
        integration.get("output_net_filename", "net_status_quo_ev.p")
    ).strip()
    if not output_net_filename:
        raise EVPandapowerIntegrationError(
            "integration.output_net_filename must not be empty."
        )
    if Path(output_net_filename).name != output_net_filename:
        raise EVPandapowerIntegrationError(
            "integration.output_net_filename must be a filename, not a path."
        )

    simbench_scenario = int(simbench_cfg.get("scenario", 2))
    source_grid_codes = _as_tuple_of_strings(
        simbench_cfg.get("source_grid_codes"), DEFAULT_SIMBENCH_RURAL_LV_CODES
    )
    ev_profile_prefixes = _as_tuple_of_strings(
        simbench_cfg.get("ev_profile_prefixes"), DEFAULT_EV_PROFILE_PREFIXES
    )

    allocation_dir = (
        allocation_output_root
        / project_context.project_name
        / scenario_id
        / "allocation"
    ).resolve()

    integration_dir = (
        integration_output_root
        / project_context.project_name
        / scenario_id
        / "integration"
    ).resolve()

    baseline_scenario_id = str(
        baseline_cfg.get("scenario_id", "status_quo")
    ).strip()
    baseline_mapping_value = baseline_cfg.get("mapping")
    if baseline_mapping_value is None:
        baseline_mapping_path = (
            integration_output_root
            / project_context.project_name
            / baseline_scenario_id
            / "integration"
            / "ev"
            / "ev_pandapower_profile_mapping.csv"
        ).resolve()
    else:
        baseline_mapping_path = _resolve_path(
            base, baseline_mapping_value
        )
        if baseline_mapping_path is None:
            raise EVPandapowerIntegrationError(
                "baseline.mapping could not be resolved."
            )

    config = EVPandapowerConfig(
        project_name=project_context.project_name,
        scenario_id=scenario_id,
        realisation=realisation,
        seiler_parameters_path=parameters_path,
        base_net_path=project_context.pandapower_net_path,
        ev_allocation_path=(allocation_dir / allocation_filename).resolve(),
        output_net_path=(integration_dir / output_net_filename).resolve(),
        output_dir=integration_dir,
        baseline_scenario_id=baseline_scenario_id,
        baseline_mapping_path=baseline_mapping_path,
        in_service=bool(integration.get("in_service", True)),
        check_building_bus_match=bool(
            integration.get("check_building_bus_match", True)
        ),
        simbench_scenario=simbench_scenario,
        simbench_source_grid_codes=source_grid_codes,
        simbench_ev_profile_prefixes=ev_profile_prefixes,
        simbench_expected_ev_profile_count=int(
            simbench_cfg.get("expected_ev_profile_count", 6)
        ),
        profile_assignment_seed=int(simbench_cfg.get("random_seed", 20260813)),
        profile_weighting=str(
            simbench_cfg.get("profile_weighting", "uniform")
        ).strip(),
        use_reactive_power=bool(simbench_cfg.get("use_reactive_power", True)),
        reference_year=int(time_alignment.get("reference_year", 2025)),
        time_alignment_method=str(
                    time_alignment.get("method", "nearest_same_weekday")
        ).strip(),
        time_step_minutes=int(time_alignment.get("time_step_minutes", 15)),
    )
    config.validate()
    return config


def _load_allocation(config: EVPandapowerConfig) -> pd.DataFrame:
    """Load and validate the selected EV allocation realisation."""

    path = config.ev_allocation_path
    if not path.exists():
        csv_fallback = path.with_suffix(".csv")
        if csv_fallback.exists():
            path = csv_fallback
        else:
            raise FileNotFoundError(config.ev_allocation_path)

    if path.suffix.lower() == ".parquet":
        allocation = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        allocation = pd.read_csv(path)
    else:
        raise EVPandapowerIntegrationError(
            f"Unsupported EV allocation format: {path.suffix}"
        )

    required = {
        "allocation_id",
        "building_id",
        "bus_id",
        "scenario_id",
        "realisation",
    }
    missing = sorted(required - set(allocation.columns))
    if missing:
        raise EVPandapowerIntegrationError(
            f"EV allocation is missing required columns: {missing}"
        )

    selected = allocation.loc[
        (allocation["scenario_id"].astype(str) == config.scenario_id)
        & (
            pd.to_numeric(allocation["realisation"], errors="coerce")
            == config.realisation
        )
    ].copy()

    if selected.empty:
        available = sorted(
            {
                int(value)
                for value in pd.to_numeric(
                    allocation.loc[
                        allocation["scenario_id"].astype(str) == config.scenario_id,
                        "realisation",
                    ],
                    errors="coerce",
                ).dropna()
            }
        )
        raise EVPandapowerIntegrationError(
            f"No EV allocation rows for scenario={config.scenario_id!r}, "
            f"realisation={config.realisation}. Available realisations: {available}"
        )

    if selected["allocation_id"].duplicated().any():
        raise EVPandapowerIntegrationError(
            "allocation_id is not unique in the selected EV realisation."
        )
    bus_numeric = pd.to_numeric(selected["bus_id"], errors="coerce")
    if bus_numeric.isna().any():
        bad = selected.loc[bus_numeric.isna(), "allocation_id"].tolist()
        raise EVPandapowerIntegrationError(
            f"Non-numeric bus_id in EV allocation: {bad[:10]}"
        )
    selected["bus_id"] = bus_numeric.astype(int)

    # EV allocation intentionally samples with replacement: multiple EVs may be
    # assigned to one residential building. Repeated rows must nevertheless
    # point to one and the same pandapower bus for that building.
    building_bus_counts = selected.groupby("building_id")["bus_id"].nunique()
    inconsistent_buildings = building_bus_counts.loc[building_bus_counts > 1]
    if not inconsistent_buildings.empty:
        raise EVPandapowerIntegrationError(
            "At least one building is mapped to multiple bus_id values in the "
            f"selected EV realisation: {inconsistent_buildings.index.tolist()[:10]}"
        )

    selected["allocation_id"] = selected["allocation_id"].astype(str).str.strip()
    selected["building_id"] = selected["building_id"].astype(str).str.strip()
    if selected["allocation_id"].eq("").any() or selected["building_id"].eq("").any():
        raise EVPandapowerIntegrationError(
            "allocation_id and building_id must not be empty."
        )

    return selected.sort_values("allocation_id").reset_index(drop=True)


def _validate_bus_mapping(
    net: Any, allocation: pd.DataFrame, config: EVPandapowerConfig
) -> None:
    """Ensure every allocation bus exists and still belongs to the same building."""

    missing_buses = sorted(set(allocation["bus_id"]) - set(net.bus.index))
    if missing_buses:
        raise EVPandapowerIntegrationError(
            f"EV allocation references buses absent from base net: {missing_buses[:10]}"
        )

    if not config.check_building_bus_match:
        return

    if "node_id" not in net.bus.columns:
        raise EVPandapowerIntegrationError(
            "net.bus has no 'node_id' column required for building/bus validation."
        )

    mismatches: list[tuple[str, int, str]] = []
    for row in allocation.itertuples(index=False):
        actual = str(net.bus.at[int(row.bus_id), "node_id"]).strip()
        if actual != str(row.building_id).strip():
            mismatches.append((str(row.building_id), int(row.bus_id), actual))

    if mismatches:
        raise EVPandapowerIntegrationError(
            "At least one EV building no longer matches its stored pandapower bus. "
            f"Examples: {mismatches[:10]}"
        )


def _ensure_not_already_integrated(net: Any, allocation: pd.DataFrame) -> None:
    """Fail instead of silently duplicating EV loads."""

    if net.load.empty:
        return

    allocation_ids = set(allocation["allocation_id"].astype(str))

    if "allocation_id" in net.load.columns:
        existing = set(net.load["allocation_id"].dropna().astype(str)) & allocation_ids
        if existing:
            raise EVPandapowerIntegrationError(
                "The selected EV allocation is already present in the input net. "
                f"Examples: {sorted(existing)[:10]}"
            )

    if "name" in net.load.columns:
        existing_names = set(net.load["name"].dropna().astype(str)) & allocation_ids
        if existing_names:
            raise EVPandapowerIntegrationError(
                "EV load names already exist in the input net. "
                f"Examples: {sorted(existing_names)[:10]}"
            )


def _profile_name_matches(name: Any, prefixes: tuple[str, ...]) -> bool:
    if pd.isna(name):
        return False
    text = str(name)
    return any(text.startswith(prefix) for prefix in prefixes)


def _merge_profile_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge SimBench load-profile frames while checking duplicate columns."""

    if not frames:
        raise EVPandapowerIntegrationError("No SimBench profile frames were loaded.")

    first = frames[0].reset_index(drop=True).copy()
    n_rows = len(first)
    result = pd.DataFrame(index=pd.RangeIndex(n_rows))

    if "time" in first.columns:
        result["time"] = first["time"].reset_index(drop=True)

    for frame in frames:
        current = frame.reset_index(drop=True)
        if len(current) != n_rows:
            raise EVPandapowerIntegrationError(
                "Configured SimBench source grids have different profile lengths."
            )
        if "time" in result.columns and "time" in current.columns:
            if not result["time"].astype(str).equals(current["time"].astype(str)):
                raise EVPandapowerIntegrationError(
                    "Configured SimBench source grids have inconsistent time columns."
                )

        for column in current.columns:
            if column == "time":
                continue
            series = pd.to_numeric(current[column], errors="coerce")
            if series.isna().any():
                raise EVPandapowerIntegrationError(
                    f"SimBench profile column {column!r} contains non-numeric/NaN values."
                )
            if column in result.columns:
                if not np.allclose(
                    result[column].to_numpy(dtype=float),
                    series.to_numpy(dtype=float),
                    rtol=0.0,
                    atol=1e-12,
                ):
                    raise EVPandapowerIntegrationError(
                        f"Duplicate SimBench profile column {column!r} differs across grids."
                    )
            else:
                result[column] = series.to_numpy(dtype=float)

    return result


def _load_simbench_reference_data(
    config: EVPandapowerConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, str, pd.DataFrame | None]:
    """Build the rural-LV home-charging EV reference pool and merge its relative profiles."""

    try:
        import simbench as sb
    except ImportError as exc:
        raise EVPandapowerIntegrationError(
            "The simbench package is required. Install the pinned dependency from "
            "requirements-ev-pandapower.txt."
        ) from exc

    pool_frames: list[pd.DataFrame] = []
    profile_frames: list[pd.DataFrame] = []

    for code in config.simbench_source_grid_codes:
        try:
            reference_net = sb.get_simbench_net(code)
        except Exception as exc:  # external package error -> add context
            raise EVPandapowerIntegrationError(
                f"Could not load SimBench source grid {code!r}: {exc}"
            ) from exc

        if not hasattr(reference_net, "load"):
            raise EVPandapowerIntegrationError(
                f"SimBench grid {code!r} has no load table."
            )
        required = {"profile", "p_mw", "q_mvar"}
        missing = required - set(reference_net.load.columns)
        if missing:
            raise EVPandapowerIntegrationError(
                f"SimBench grid {code!r} load table misses {sorted(missing)}."
            )

        mask = reference_net.load["profile"].map(
            lambda value: _profile_name_matches(
                value, config.simbench_ev_profile_prefixes
            )
        )
        ev_rows = reference_net.load.loc[
            mask, ["profile", "p_mw", "q_mvar"]
        ].copy()
        if ev_rows.empty:
            raise EVPandapowerIntegrationError(
                f"No EV reference loads found in SimBench grid {code!r}."
            )

        ev_rows["source_grid_code"] = code
        ev_rows["source_load_index"] = ev_rows.index.astype(int)
        if "name" in reference_net.load.columns:
            ev_rows["source_load_name"] = reference_net.load.loc[
                ev_rows.index, "name"
            ].astype(str).to_numpy()
        else:
            ev_rows["source_load_name"] = ""

        ev_rows["p_mw"] = pd.to_numeric(ev_rows["p_mw"], errors="coerce")
        ev_rows["q_mvar"] = pd.to_numeric(ev_rows["q_mvar"], errors="coerce")
        if ev_rows[["p_mw", "q_mvar"]].isna().any().any():
            raise EVPandapowerIntegrationError(
                f"SimBench EV reference powers contain NaN values in {code!r}."
            )
        if (ev_rows["p_mw"] <= 0).any():
            raise EVPandapowerIntegrationError(
                f"SimBench EV reference p_mw must be positive in {code!r}."
            )
        pool_frames.append(ev_rows.reset_index(drop=True))

        profiles = getattr(reference_net, "profiles", None)
        if not isinstance(profiles, dict) or "load" not in profiles:
            raise EVPandapowerIntegrationError(
                f"SimBench grid {code!r} has no net.profiles['load'] data."
            )
        profile_frames.append(profiles["load"].copy())

    pool = pd.concat(pool_frames, ignore_index=True)
    pool = pool.sort_values(
        ["source_grid_code", "source_load_index", "profile", "p_mw", "q_mvar"],
        kind="stable",
    ).reset_index(drop=True)
    relative_profiles = _merge_profile_frames(profile_frames)

    profile_names = sorted(pool["profile"].astype(str).unique())
    if len(profile_names) != config.simbench_expected_ev_profile_count:
        raise EVPandapowerIntegrationError(
            "Unexpected number of SimBench home-charging EV profiles in configured source grids: "
            f"expected {config.simbench_expected_ev_profile_count}, got "
            f"{len(profile_names)} ({profile_names})."
        )

    required_profile_columns: list[str] = []
    for profile_name in profile_names:
        required_profile_columns.append(f"{profile_name}_pload")
        if config.use_reactive_power:
            required_profile_columns.append(f"{profile_name}_qload")
    missing_profile_columns = sorted(
        set(required_profile_columns) - set(relative_profiles.columns)
    )
    if missing_profile_columns:
        raise EVPandapowerIntegrationError(
            "SimBench relative load-profile columns are missing: "
            f"{missing_profile_columns}"
        )

    alignment_mapping: pd.DataFrame | None = None
    if config.time_alignment_method == "nearest_same_weekday":
        try:
            alignment = align_nearest_same_weekday_to_reference_year(
                relative_profiles,
                config.reference_year,
                time_column="time",
                time_step_minutes=config.time_step_minutes,
            )
        except TimeAxisError as exc:
            raise EVPandapowerIntegrationError(
                f"Could not align SimBench EV profiles: {exc}"
            ) from exc
        relative_profiles = alignment.frame
        alignment_mapping = alignment.mapping

    simbench_version = str(getattr(sb, "__version__", "unknown"))
    return pool, relative_profiles, simbench_version, alignment_mapping


def _charging_power_kw_from_profile(profile_name: str) -> float:
    """Extract the nominal charging-station power encoded in an HLS profile ID.

    SimBench household-charging profile IDs follow names such as
    ``HLS_A_3.7``, ``HLS_B_11.0`` or ``HLS_A_22.0``. The suffix is the
    nominal charging-station power in kW. The actual active-power scaling used
    for the time series still comes from the SimBench reference load's ``p_mw``.
    """

    try:
        value = float(str(profile_name).rsplit("_", 1)[1])
    except (IndexError, ValueError) as exc:
        raise EVPandapowerIntegrationError(
            f"Cannot derive charging power from SimBench EV profile {profile_name!r}."
        ) from exc
    if value <= 0:
        raise EVPandapowerIntegrationError(
            f"Charging power encoded in profile {profile_name!r} must be positive."
        )
    return value


def _stable_unit_seed(
    config: EVPandapowerConfig,
    building_id: str,
    unit_at_building: int,
) -> int:
    """Derive a scenario-size-independent seed for one EV unit."""

    payload = (
        f"{config.profile_assignment_seed}|EV|{config.project_name}|"
        f"{config.realisation}|{building_id}|{unit_at_building}"
    )
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % (2**32)


def _sample_one_template(
    reference_pool: pd.DataFrame,
    config: EVPandapowerConfig,
    *,
    building_id: str,
    unit_at_building: int,
) -> pd.Series:
    """Sample one complete SimBench reference row deterministically."""

    rng = np.random.default_rng(
        _stable_unit_seed(config, building_id, unit_at_building)
    )
    if config.profile_weighting == "reference_rows":
        return reference_pool.iloc[int(rng.integers(0, len(reference_pool)))]

    profile_names = np.array(
        sorted(reference_pool["profile"].astype(str).unique()), dtype=object
    )
    profile_name = str(profile_names[int(rng.integers(0, len(profile_names)))])
    candidates = reference_pool.loc[
        reference_pool["profile"].astype(str).eq(profile_name)
    ]
    return candidates.iloc[int(rng.integers(0, len(candidates)))]


def _load_baseline_mapping(config: EVPandapowerConfig) -> pd.DataFrame:
    """Load the status-quo EV mapping used as the controlled baseline."""

    baseline = pd.read_csv(config.baseline_mapping_path)
    required = {
        "building_id",
        "unit_at_building",
        "profile_id",
        "simbench_peak_p_mw",
        "simbench_peak_q_mvar",
        "simbench_source_grid_code",
        "simbench_source_load_index",
        "simbench_source_load_name",
    }
    missing = sorted(required - set(baseline.columns))
    if missing:
        raise EVPandapowerIntegrationError(
            "Baseline EV mapping is missing required columns: " f"{missing}"
        )

    if "realisation" in baseline.columns:
        baseline = baseline.loc[
            pd.to_numeric(baseline["realisation"], errors="coerce")
            == config.realisation
        ].copy()
    if baseline.empty:
        raise EVPandapowerIntegrationError(
            f"Baseline EV mapping has no rows for realisation {config.realisation}."
        )

    baseline["building_id"] = baseline["building_id"].astype(str).str.strip()
    baseline["unit_at_building"] = pd.to_numeric(
        baseline["unit_at_building"], errors="raise"
    ).astype(int)
    if baseline.duplicated(["building_id", "unit_at_building"]).any():
        raise EVPandapowerIntegrationError(
            "Baseline EV mapping contains duplicate "
            "(building_id, unit_at_building) keys."
        )
    return baseline.reset_index(drop=True)


def _baseline_row_to_reference(row: pd.Series) -> pd.Series:
    return pd.Series(
        {
            "profile": str(row["profile_id"]),
            "p_mw": float(row["simbench_peak_p_mw"]),
            "q_mvar": float(row["simbench_peak_q_mvar"]),
            "source_grid_code": str(row["simbench_source_grid_code"]),
            "source_load_index": int(row["simbench_source_load_index"]),
            "source_load_name": str(row["simbench_source_load_name"]),
        }
    )


def _sample_simbench_templates(
    allocation: pd.DataFrame,
    reference_pool: pd.DataFrame,
    config: EVPandapowerConfig,
) -> pd.DataFrame:
    """Inherit baseline EV templates and sample only templates of new units."""

    work = allocation.reset_index(drop=True).copy()
    if "unit_at_building" not in work.columns:
        raise EVPandapowerIntegrationError(
            "Nested EV integration requires allocation column 'unit_at_building'."
        )
    work["building_id"] = work["building_id"].astype(str).str.strip()
    work["unit_at_building"] = pd.to_numeric(
        work["unit_at_building"], errors="raise"
    ).astype(int)

    # Allow this dedicated module to reproduce the baseline if explicitly used
    # for it. Higher scenarios always inherit the already stored baseline mapping.
    if config.scenario_id == config.baseline_scenario_id:
        rng = np.random.default_rng(config.profile_assignment_seed)
        if config.profile_weighting == "reference_rows":
            choice = rng.integers(0, len(reference_pool), size=len(work))
            sampled = reference_pool.iloc[choice].reset_index(drop=True).copy()
        else:
            profile_names = np.array(
                sorted(reference_pool["profile"].astype(str).unique()), dtype=object
            )
            profile_choice = rng.integers(0, len(profile_names), size=len(work))
            rows: list[pd.Series] = []
            for profile_index in profile_choice:
                profile_name = str(profile_names[int(profile_index)])
                candidates = reference_pool.loc[
                    reference_pool["profile"].astype(str).eq(profile_name)
                ]
                rows.append(candidates.iloc[int(rng.integers(0, len(candidates)))])
            sampled = pd.DataFrame(rows).reset_index(drop=True)
        assignment_mode = ["independent_baseline"] * len(work)
    else:
        baseline = _load_baseline_mapping(config)
        baseline_indexed = baseline.set_index(["building_id", "unit_at_building"])
        baseline_keys = set(baseline_indexed.index.tolist())
        current_keys = set(
            zip(work["building_id"].tolist(), work["unit_at_building"].tolist())
        )
        missing_baseline = sorted(baseline_keys - current_keys)
        if missing_baseline:
            raise EVPandapowerIntegrationError(
                "Nested EV allocation does not contain all baseline EV units. "
                f"Missing examples: {missing_baseline[:10]}"
            )

        rows = []
        assignment_mode = []
        for row in work.itertuples(index=False):
            key = (str(row.building_id).strip(), int(row.unit_at_building))
            if key in baseline_indexed.index:
                rows.append(_baseline_row_to_reference(baseline_indexed.loc[key]))
                assignment_mode.append("baseline_inherited")
            else:
                rows.append(
                    _sample_one_template(
                        reference_pool,
                        config,
                        building_id=key[0],
                        unit_at_building=key[1],
                    )
                )
                assignment_mode.append("stable_new_unit")
        sampled = pd.DataFrame(rows).reset_index(drop=True)

    result = work.copy()
    result["profile_id"] = sampled["profile"].astype(str).to_numpy()
    result["charging_power_kw"] = result["profile_id"].map(
        _charging_power_kw_from_profile
    )
    result["electrical_peak_power_kw"] = sampled["p_mw"].to_numpy(float) * 1000.0
    result["simbench_peak_p_mw"] = sampled["p_mw"].to_numpy(float)
    result["simbench_peak_q_mvar"] = sampled["q_mvar"].to_numpy(float)
    result["simbench_source_grid_code"] = sampled["source_grid_code"].astype(str).to_numpy()
    result["simbench_source_load_index"] = sampled["source_load_index"].astype(int).to_numpy()
    result["simbench_source_load_name"] = sampled["source_load_name"].astype(str).to_numpy()
    result["profile_assignment_seed"] = config.profile_assignment_seed
    result["profile_weighting"] = config.profile_weighting
    result["template_assignment_mode"] = assignment_mode
    result["baseline_scenario_id"] = config.baseline_scenario_id
    return result

def _copy_optional_value(row: Any, name: str, default: Any = None) -> Any:
    value = getattr(row, name, default)
    if pd.isna(value):
        return default
    return value


def _add_ev_loads(
    pp: Any,
    net: Any,
    assignments: pd.DataFrame,
    config: EVPandapowerConfig,
) -> pd.DataFrame:
    """Create one pandapower load per EV and store SimBench template metadata."""

    mapping_rows: list[dict[str, Any]] = []

    for row in assignments.itertuples(index=False):
        # p/q are set to their SimBench maxima first, mirroring the SimBench convention.
        # After the absolute time series is built below, the saved net is moved to t=0.
        load_index = pp.create_load(
            net,
            bus=int(row.bus_id),
            p_mw=float(row.simbench_peak_p_mw),
            q_mvar=(
                float(row.simbench_peak_q_mvar)
                if config.use_reactive_power
                else 0.0
            ),
            name=str(row.allocation_id),
            in_service=config.in_service,
        )

        metadata = {
            "technology": "EV",
            "vehicle_category": _copy_optional_value(
                row, "vehicle_category", "BEV_M1"
            ),
            "allocation_id": str(row.allocation_id),
            "building_id": str(row.building_id),
            "scenario_id": str(row.scenario_id),
            "realisation": int(row.realisation),
            "municipality_id": str(_copy_optional_value(row, "municipality_id", "")),
            "reference_date": str(_copy_optional_value(row, "reference_date", "")),
            "unit_at_building": int(_copy_optional_value(row, "unit_at_building", 1)),
            "allocation_method": str(_copy_optional_value(row, "allocation_method", "")),
            "allocation_random_seed": int(_copy_optional_value(row, "random_seed", -1)),
            "profile": str(row.profile_id),
            "profile_id": str(row.profile_id),
            "profile_source": "SimBench",
            "profile_assignment_seed": int(config.profile_assignment_seed),
            "profile_weighting": str(config.profile_weighting),
            "template_assignment_mode": str(
                _copy_optional_value(row, "template_assignment_mode", "unknown")
            ),
            "baseline_scenario_id": str(
                _copy_optional_value(row, "baseline_scenario_id", config.baseline_scenario_id)
            ),
            "charging_power_kw": float(row.charging_power_kw),
            "electrical_power_kw": float(row.electrical_peak_power_kw),
            "electrical_peak_power_kw": float(row.electrical_peak_power_kw),
            "simbench_peak_p_mw": float(row.simbench_peak_p_mw),
            "simbench_peak_q_mvar": float(row.simbench_peak_q_mvar),
            "simbench_source_grid_code": str(row.simbench_source_grid_code),
            "simbench_source_load_index": int(row.simbench_source_load_index),
            "model_layer": "technology_load",
            "source": "status_quo_allocation+simbench",
        }
        for column, value in metadata.items():
            if column not in net.load.columns:
                net.load[column] = np.nan if isinstance(value, (float, int)) else None
            net.load.at[load_index, column] = value

        mapping_rows.append(
            {
                "load_index": int(load_index),
                "allocation_id": str(row.allocation_id),
                "building_id": str(row.building_id),
                "bus_id": int(row.bus_id),
                "scenario_id": str(row.scenario_id),
                "realisation": int(row.realisation),
                "unit_at_building": int(_copy_optional_value(row, "unit_at_building", 1)),
                "profile_id": str(row.profile_id),
                "charging_power_kw": float(row.charging_power_kw),
                "electrical_peak_power_kw": float(row.electrical_peak_power_kw),
                "simbench_peak_p_mw": float(row.simbench_peak_p_mw),
                "simbench_peak_q_mvar": float(row.simbench_peak_q_mvar),
                "simbench_source_grid_code": str(row.simbench_source_grid_code),
                "simbench_source_load_index": int(row.simbench_source_load_index),
                "simbench_source_load_name": str(row.simbench_source_load_name),
                "profile_assignment_seed": int(config.profile_assignment_seed),
                "profile_weighting": str(config.profile_weighting),
                "template_assignment_mode": str(
                    _copy_optional_value(row, "template_assignment_mode", "unknown")
                ),
                "baseline_scenario_id": str(
                    _copy_optional_value(row, "baseline_scenario_id", config.baseline_scenario_id)
                ),
            }
        )

    return pd.DataFrame(mapping_rows)


def build_ev_absolute_timeseries(
    mapping: pd.DataFrame,
    relative_profiles: pd.DataFrame,
    use_reactive_power: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Build absolute EV p/q time series from normalized SimBench profiles.

    Returned p/q DataFrames use ``allocation_id`` as columns and a simple integer
    time-step index. The separate returned Series preserves the original SimBench
    time labels (if available).
    """

    if mapping.empty:
        raise EVPandapowerIntegrationError("Cannot build time series for empty mapping.")

    n_steps = len(relative_profiles)
    if n_steps <= 0:
        raise EVPandapowerIntegrationError("SimBench relative profiles are empty.")

    allocation_ids = mapping["allocation_id"].astype(str).tolist()
    p_columns = [f"{name}_pload" for name in mapping["profile_id"].astype(str)]
    missing_p = sorted(set(p_columns) - set(relative_profiles.columns))
    if missing_p:
        raise EVPandapowerIntegrationError(
            f"Missing active-power SimBench profile columns: {missing_p}"
        )

    p_relative = relative_profiles[p_columns].to_numpy(dtype=float)

    # SimBench HLS_C_3.7 contains a few tiny negative active-power samples
    # (down to about -1.2e-05 p.u.). The EV profiles represent charging, not
    # vehicle-to-grid feed-in, so these values are treated as numerical/data
    # noise. Keep a strict guard against materially negative values instead of
    # silently accepting arbitrary feed-in.
    negative_noise_tolerance = 1e-4
    min_relative_p = float(np.min(p_relative))
    if min_relative_p < -negative_noise_tolerance:
        raise EVPandapowerIntegrationError(
            "SimBench EV active-power profile contains materially negative "
            f"values (minimum {min_relative_p:.6g} p.u.)."
        )
    p_relative = np.clip(p_relative, 0.0, None)

    p_factor = mapping["simbench_peak_p_mw"].to_numpy(dtype=float).reshape(1, -1)
    p_absolute = pd.DataFrame(
        p_relative * p_factor,
        index=pd.RangeIndex(n_steps, name="time_step"),
        columns=allocation_ids,
    )

    if use_reactive_power:
        q_columns = [f"{name}_qload" for name in mapping["profile_id"].astype(str)]
        missing_q = sorted(set(q_columns) - set(relative_profiles.columns))
        if missing_q:
            raise EVPandapowerIntegrationError(
                f"Missing reactive-power SimBench profile columns: {missing_q}"
            )
        q_relative = relative_profiles[q_columns].to_numpy(dtype=float)
        q_factor = mapping["simbench_peak_q_mvar"].to_numpy(dtype=float).reshape(1, -1)
        q_absolute = pd.DataFrame(
            q_relative * q_factor,
            index=pd.RangeIndex(n_steps, name="time_step"),
            columns=allocation_ids,
        )
    else:
        q_absolute = pd.DataFrame(
            np.zeros((n_steps, len(mapping)), dtype=float),
            index=pd.RangeIndex(n_steps, name="time_step"),
            columns=allocation_ids,
        )

    if not np.isfinite(p_absolute.to_numpy()).all():
        raise EVPandapowerIntegrationError("Absolute EV p_mw contains non-finite values.")
    if not np.isfinite(q_absolute.to_numpy()).all():
        raise EVPandapowerIntegrationError("Absolute EV q_mvar contains non-finite values.")
    if (p_absolute.to_numpy() < -1e-12).any():
        raise EVPandapowerIntegrationError("EV active-power time series contains negative load.")

    if "time" in relative_profiles.columns:
        time_labels = relative_profiles["time"].reset_index(drop=True).copy()
    else:
        time_labels = pd.Series(np.arange(n_steps), name="simbench_time")
    time_labels.name = "simbench_time"
    return p_absolute, q_absolute, time_labels


def _attach_ev_const_controls(
    net: Any,
    mapping: pd.DataFrame,
    p_absolute: pd.DataFrame,
    q_absolute: pd.DataFrame,
    config: EVPandapowerConfig,
) -> int:
    """Attach pandapower ConstControl objects for the EV loads only."""

    try:
        from pandapower.control import ConstControl
        from pandapower.timeseries import DFData
    except ImportError as exc:
        raise EVPandapowerIntegrationError(
            "pandapower ConstControl/DFData are required for EV time series."
        ) from exc

    load_indices = mapping["load_index"].astype(int).tolist()
    allocation_ids = mapping["allocation_id"].astype(str).tolist()

    ConstControl(
        net,
        element="load",
        variable="p_mw",
        element_index=load_indices,
        profile_name=allocation_ids,
        data_source=DFData(p_absolute),
    )
    count = 1

    if config.use_reactive_power:
        ConstControl(
            net,
            element="load",
            variable="q_mvar",
            element_index=load_indices,
            profile_name=allocation_ids,
            data_source=DFData(q_absolute),
        )
        count += 1
    else:
        net.load.loc[load_indices, "q_mvar"] = 0.0

    # Store the net at time step 0 instead of leaving every EV at simultaneous peak.
    first_p = p_absolute.iloc[0]
    first_q = q_absolute.iloc[0]
    for load_index, allocation_id in zip(load_indices, allocation_ids):
        net.load.at[load_index, "p_mw"] = float(first_p[allocation_id])
        net.load.at[load_index, "q_mvar"] = float(first_q[allocation_id])

    return count


def _table_counts(net: Any) -> dict[str, int]:
    """Return counts for network tables used in structural validation."""

    result: dict[str, int] = {}
    for name in ["bus", "line", "trafo", "sgen", "ext_grid", "load"]:
        table = getattr(net, name, None)
        if table is not None:
            result[name] = int(len(table))
    return result


def _write_compact_profile_pool(
    path: Path,
    relative_profiles: pd.DataFrame,
    used_profiles: list[str],
    use_reactive_power: bool,
) -> None:
    columns: list[str] = []
    if "time" in relative_profiles.columns:
        columns.append("time")
    for profile in sorted(set(used_profiles)):
        columns.append(f"{profile}_pload")
        if use_reactive_power:
            columns.append(f"{profile}_qload")
    relative_profiles[columns].to_csv(path, index=False, compression="gzip")


def integrate_ev_status_quo(
    config: EVPandapowerConfig,
) -> EVPandapowerIntegrationResult:
    """Create a simulation-ready EV-enriched pandapower network."""

    config.validate()

    try:
        import pandapower as pp
    except ImportError as exc:
        raise EVPandapowerIntegrationError(
            "pandapower is required for EV network integration."
        ) from exc

    if not config.base_net_path.exists():
        raise FileNotFoundError(config.base_net_path)

    allocation = _load_allocation(config)
    base_net = pp.from_pickle(str(config.base_net_path))

    _validate_bus_mapping(base_net, allocation, config)
    _ensure_not_already_integrated(base_net, allocation)

    reference_pool, relative_profiles, simbench_version, alignment_mapping = (
        _load_simbench_reference_data(config)
    )
    assignments = _sample_simbench_templates(allocation, reference_pool, config)

    base_counts = _table_counts(base_net)
    base_load_count = int(len(base_net.load))

    enriched_net = deepcopy(base_net)
    mapping = _add_ev_loads(pp, enriched_net, assignments, config)
    p_absolute, q_absolute, time_labels = build_ev_absolute_timeseries(
        mapping,
        relative_profiles,
        use_reactive_power=config.use_reactive_power,
    )
    controller_count_added = _attach_ev_const_controls(
        enriched_net, mapping, p_absolute, q_absolute, config
    )

    enriched_counts = _table_counts(enriched_net)
    enriched_load_count = int(len(enriched_net.load))
    expected_load_count = base_load_count + len(allocation)
    if enriched_load_count != expected_load_count:
        raise EVPandapowerIntegrationError(
            "Unexpected load count after EV integration: "
            f"expected {expected_load_count}, got {enriched_load_count}."
        )

    for table in ["bus", "line", "trafo", "sgen", "ext_grid"]:
        if table in base_counts and table in enriched_counts:
            if base_counts[table] != enriched_counts[table]:
                raise EVPandapowerIntegrationError(
                    f"Table {table!r} changed during EV-only integration."
                )

    if "technology" not in enriched_net.load.columns:
        raise EVPandapowerIntegrationError("EV technology metadata was not created.")
    ev_rows = enriched_net.load.loc[
        enriched_net.load["technology"].astype(str).eq("EV")
    ]
    if len(ev_rows) != len(allocation):
        raise EVPandapowerIntegrationError(
            "Integrated EV load count does not match the selected allocation."
        )
    if ev_rows["profile_id"].isna().any():
        raise EVPandapowerIntegrationError("At least one EV has no profile_id.")
    if not ev_rows["profile_id"].astype(str).str.startswith("HLS_").all():
        raise EVPandapowerIntegrationError(
            "At least one EV received a non-household SimBench charging profile."
        )
    if (pd.to_numeric(ev_rows["charging_power_kw"], errors="coerce") <= 0).any():
        raise EVPandapowerIntegrationError(
            "At least one EV has no positive nominal charging power."
        )
    if (pd.to_numeric(ev_rows["electrical_peak_power_kw"]) <= 0).any():
        raise EVPandapowerIntegrationError(
            "At least one EV has no positive electrical peak power."
        )

    enriched_net["ev_timeseries_metadata"] = {
        "source": "SimBench",
        "simbench_version": simbench_version,
        "simbench_scenario": config.simbench_scenario,
        "source_grid_codes": list(config.simbench_source_grid_codes),
        "profile_assignment_seed": config.profile_assignment_seed,
        "profile_weighting": config.profile_weighting,
        "home_charging_only": True,
        "multiple_evs_per_building_allowed": True,
        "use_reactive_power": config.use_reactive_power,
        "n_time_steps": int(len(p_absolute)),
        "time_step_minutes": config.time_step_minutes,
        "reference_year": config.reference_year,
        "time_alignment_method": config.time_alignment_method,
        "ev_load_indices": mapping["load_index"].astype(int).tolist(),
        "profile_ids": sorted(mapping["profile_id"].astype(str).unique().tolist()),
    }

    config.output_net_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pp.to_pickle(enriched_net, str(config.output_net_path))

    mapping_csv = config.output_dir / "ev_pandapower_profile_mapping.csv"
    reference_pool_csv = config.output_dir / "ev_simbench_reference_pool.csv"
    relative_profiles_csv_gz = (
        config.output_dir / "ev_simbench_relative_profile_pool.csv.gz"
    )
    time_index_csv = config.output_dir / "ev_simbench_time_index.csv"
    alignment_mapping_csv = config.output_dir / "ev_time_alignment_mapping.csv"
    validation_json = config.output_dir / "ev_pandapower_validation.json"
    metadata_json = config.output_dir / "ev_pandapower_metadata.json"

    mapping.to_csv(mapping_csv, index=False)
    reference_pool.to_csv(reference_pool_csv, index=False)
    _write_compact_profile_pool(
        relative_profiles_csv_gz,
        relative_profiles,
        mapping["profile_id"].astype(str).tolist(),
        config.use_reactive_power,
    )
    pd.DataFrame(
        {
            "time_step": np.arange(len(time_labels), dtype=int),
            "simbench_time": time_labels.astype(str).to_numpy(),
        }
    ).to_csv(time_index_csv, index=False)
    if alignment_mapping is not None:
        alignment_mapping.to_csv(alignment_mapping_csv, index=False)

    profile_distribution = {
        str(key): int(value)
        for key, value in mapping["profile_id"].value_counts().sort_index().items()
    }
    peak_kw = mapping["electrical_peak_power_kw"].astype(float)

    validation: dict[str, Any] = {
        "all_checks_passed": True,
        "project_name": config.project_name,
        "scenario_id": config.scenario_id,
        "realisation": config.realisation,
        "base_net_path": str(config.base_net_path),
        "output_net_path": str(config.output_net_path),
        "base_net_preserved": config.output_net_path.resolve()
        != config.base_net_path.resolve(),
        "building_bus_match_checked": config.check_building_bus_match,
        "ev_allocation_rows": int(len(allocation)),
        "ev_loads_added": int(len(mapping)),
        "allocated_building_count": int(allocation["building_id"].nunique()),
        "max_evs_per_building": int(allocation.groupby("building_id").size().max()),
        "base_load_count": base_load_count,
        "enriched_load_count": enriched_load_count,
        "simbench_version": simbench_version,
        "simbench_scenario": config.simbench_scenario,
        "simbench_source_grid_codes": list(config.simbench_source_grid_codes),
        "simbench_reference_pool_rows": int(len(reference_pool)),
        "available_ev_profiles": sorted(reference_pool["profile"].astype(str).unique()),
        "assigned_profile_distribution": profile_distribution,
        "profile_assignment_seed": config.profile_assignment_seed,
        "profile_weighting": config.profile_weighting,
        "home_charging_only": True,
        "multiple_evs_per_building_allowed": True,
        "charging_power_assigned": True,
        "charging_power_kw_values": sorted(
            {float(v) for v in mapping["charging_power_kw"].astype(float)}
        ),
        "electrical_peak_power_assigned": True,
        "electrical_peak_power_kw_min": float(peak_kw.min()),
        "electrical_peak_power_kw_median": float(peak_kw.median()),
        "electrical_peak_power_kw_max": float(peak_kw.max()),
        "profile_assigned": True,
        "time_series_controller_created": True,
        "controllers_added": controller_count_added,
        "use_reactive_power": config.use_reactive_power,
        "n_time_steps": int(len(p_absolute)),
        "time_step_minutes": config.time_step_minutes,
        "reference_year": config.reference_year,
        "time_alignment_method": config.time_alignment_method,
        "initial_saved_state": "SimBench time step 0",
        "base_table_counts": base_counts,
        "enriched_table_counts": enriched_counts,
    }
    validation_json.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    metadata = asdict(config)
    for key, value in list(metadata.items()):
        if isinstance(value, Path):
            metadata[key] = str(value)
        elif isinstance(value, tuple):
            metadata[key] = list(value)
    metadata["simbench_version"] = simbench_version
    metadata["time_alignment_note"] = (
        "EV profiles are mapped to the benchmark reference year using the nearest "
        "source day with the same weekday, while preserving time of day."
        if config.time_alignment_method == "nearest_same_weekday"
        else "No EV time alignment was applied."
    )
    metadata["method_note"] = (
        "Each allocated EV becomes one separate pandapower load, including when "
        "multiple EVs are allocated to the same residential building and bus. "
        "Each EV receives one complete reference record sampled with replacement "
        "from SimBench household-charging (HLS) loads in the configured rural LV "
        "grids. Workplace-charging APLS profiles are excluded. The HLS profile ID "
        "provides the nominal charging-station power, while the SimBench reference "
        "load p_mw/q_mvar values are used to scale the normalized active/reactive "
        "profiles to absolute time series. With profile_weighting='uniform', the six "
        "HLS profile IDs are selected with equal probability. Sampling is "
        "reproducible through profile_assignment_seed. ConstControl is attached only "
        "to the newly created EV loads. The immutable base net.p is never overwritten."
    )
    metadata_json.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return EVPandapowerIntegrationResult(
        ev_count=int(len(mapping)),
        base_load_count=base_load_count,
        enriched_load_count=enriched_load_count,
        n_time_steps=int(len(p_absolute)),
        n_profiles_used=int(mapping["profile_id"].nunique()),
        output_net_path=config.output_net_path,
        output_files={
            "mapping_csv": mapping_csv,
            "reference_pool_csv": reference_pool_csv,
            "relative_profiles_csv_gz": relative_profiles_csv_gz,
            "time_index_csv": time_index_csv,
            **(
                {"alignment_mapping_csv": alignment_mapping_csv}
                if alignment_mapping is not None
                else {}
            ),
            "validation_json": validation_json,
            "metadata_json": metadata_json,
        },
        validation=validation,
    )
