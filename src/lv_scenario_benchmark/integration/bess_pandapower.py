"""Chronological self-consumption BESS integration for pandapower.

Repository target:
    src/lv_scenario_benchmark/integration/bess_pandapower.py

Design:
- one BESS is coupled to one already integrated PV system;
- usable energy capacity = 1.01 kWh/kWp by default;
- maximum charging/discharging power = 0.25 h^-1 times usable capacity;
- 96% charging and discharging efficiency;
- usable energy state maps to a reported SOC interval of 20...100%;
- charging only from local PV surplus; discharging only into local demand;
- the complete annual BESS series is computed before benchmark power flows.

Pandapower sign convention used here:
    storage p_mw > 0  -> charging / consumption
    storage p_mw < 0  -> discharging / generation
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)


class BESSPandapowerIntegrationError(RuntimeError):
    """Raised when BESS network integration cannot be completed."""


@dataclass(frozen=True)
class BESSPandapowerConfig:
    """Resolved BESS electrical/temporal integration configuration."""

    project_name: str
    scenario_id: str
    realisation: int
    base_net_path: Path
    bess_allocation_path: Path
    output_net_path: Path
    output_dir: Path

    usable_capacity_ratio_kwh_per_kwp: float = 1.01
    power_to_usable_energy_ratio_per_h: float = 0.25
    soc_min: float = 0.20
    soc_max: float = 1.00
    initial_soc: float = 0.20
    eta_charge: float = 0.96
    eta_discharge: float = 0.96
    q_mvar: float = 0.0
    in_service: bool = True
    reference_year: int = 2025
    time_step_minutes: int = 15
    default_pv_nominal_power_kwp: float = 12.0
    check_building_bus_match: bool = True

    def validate(self) -> None:
        if not self.project_name.strip():
            raise BESSPandapowerIntegrationError("project_name must not be empty.")
        if not self.scenario_id.strip():
            raise BESSPandapowerIntegrationError("scenario_id must not be empty.")
        if self.realisation < 0:
            raise BESSPandapowerIntegrationError("realisation must be non-negative.")
        if self.output_net_path.resolve() == self.base_net_path.resolve():
            raise BESSPandapowerIntegrationError("BESS integration must not overwrite its base network.")
        if self.usable_capacity_ratio_kwh_per_kwp <= 0:
            raise BESSPandapowerIntegrationError("usable capacity ratio must be positive.")
        if self.power_to_usable_energy_ratio_per_h <= 0:
            raise BESSPandapowerIntegrationError("power-to-energy ratio must be positive.")
        if not 0 <= self.soc_min < self.soc_max <= 1:
            raise BESSPandapowerIntegrationError("Require 0 <= soc_min < soc_max <= 1.")
        if not self.soc_min <= self.initial_soc <= self.soc_max:
            raise BESSPandapowerIntegrationError("initial_soc must lie within the SOC interval.")
        if not 0 < self.eta_charge <= 1 or not 0 < self.eta_discharge <= 1:
            raise BESSPandapowerIntegrationError("Efficiencies must lie within (0, 1].")
        if self.reference_year < 1900:
            raise BESSPandapowerIntegrationError("reference_year must be >= 1900.")
        if self.time_step_minutes <= 0:
            raise BESSPandapowerIntegrationError("time_step_minutes must be positive.")
        if self.default_pv_nominal_power_kwp <= 0:
            raise BESSPandapowerIntegrationError("default PV nominal power must be positive.")


@dataclass(frozen=True)
class BESSPandapowerIntegrationResult:
    """Outputs of one BESS integration run."""

    bess_count: int
    n_time_steps: int
    reference_year: int
    time_step_minutes: int
    output_net_path: Path
    output_files: dict[str, Path]


def _resolve_path(base: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_bess_pandapower_config(path: str | Path) -> BESSPandapowerConfig:
    """Load BESS integration YAML and resolve repository output paths."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise BESSPandapowerIntegrationError("PyYAML is required.") from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BESSPandapowerIntegrationError("The YAML root must be a mapping.")

    project = raw.get("project", {})
    case = raw.get("case", {})
    paths = raw.get("paths", {})
    network = raw.get("network", {})
    sizing = raw.get("sizing", {})
    battery = raw.get("battery", {})
    electrical = raw.get("electrical", {})
    time_cfg = raw.get("time", {})
    integration = raw.get("integration", {})
    base = config_path.parent

    parameters_path = _resolve_path(
        base,
        project.get("parameters", "../../external/seiler/scripts/parameters.py"),
    )
    if parameters_path is None:
        raise BESSPandapowerIntegrationError("project.parameters is required.")

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get("pandapower_net_filename", "net.p"),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise BESSPandapowerIntegrationError(str(exc)) from exc

    scenario_id = str(case.get("scenario_id", "status_quo")).strip()
    realisation = int(case.get("realisation", 0))
    output_root = _resolve_path(base, paths.get("output_root", "../../outputs"))
    if output_root is None:
        raise BESSPandapowerIntegrationError("paths.output_root is required.")

    scenario_root = (output_root / project_context.project_name / scenario_id).resolve()
    allocation_dir = scenario_root / "allocation"
    integration_dir = scenario_root / "integration"

    allocation_filename = str(paths.get("allocation_filename", "bess_allocation.parquet")).strip()
    base_net_filename = str(
        network.get("base_net_filename", f"net_{scenario_id}_combined.p")
    ).strip()
    output_net_filename = str(
        integration.get("output_net_filename", f"net_{scenario_id}_combined_bess.p")
    ).strip()

    config = BESSPandapowerConfig(
        project_name=project_context.project_name,
        scenario_id=scenario_id,
        realisation=realisation,
        base_net_path=(integration_dir / base_net_filename).resolve(),
        bess_allocation_path=(allocation_dir / allocation_filename).resolve(),
        output_net_path=(integration_dir / output_net_filename).resolve(),
        output_dir=(integration_dir / "bess").resolve(),
        usable_capacity_ratio_kwh_per_kwp=float(
            sizing.get("usable_capacity_ratio_kwh_per_kwp", 1.01)
        ),
        power_to_usable_energy_ratio_per_h=float(
            sizing.get("power_to_usable_energy_ratio_per_h", 0.25)
        ),
        soc_min=float(battery.get("soc_min", 0.20)),
        soc_max=float(battery.get("soc_max", 1.00)),
        initial_soc=float(battery.get("initial_soc", 0.20)),
        eta_charge=float(battery.get("eta_charge", 0.96)),
        eta_discharge=float(battery.get("eta_discharge", 0.96)),
        q_mvar=float(electrical.get("q_mvar", 0.0)),
        in_service=bool(integration.get("in_service", True)),
        reference_year=int(time_cfg.get("reference_year", 2025)),
        time_step_minutes=int(time_cfg.get("time_step_minutes", 15)),
        default_pv_nominal_power_kwp=float(
            sizing.get("default_pv_nominal_power_kwp", 12.0)
        ),
        check_building_bus_match=bool(
            integration.get("check_building_bus_match", True)
        ),
    )
    config.validate()
    return config


def _read_allocation(path: Path) -> pd.DataFrame:
    if not path.exists():
        csv_fallback = path.with_suffix(".csv")
        if csv_fallback.exists():
            path = csv_fallback
        else:
            raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise BESSPandapowerIntegrationError(
        f"Unsupported BESS allocation format: {path.suffix}"
    )


def _load_allocation(config: BESSPandapowerConfig) -> pd.DataFrame:
    allocation = _read_allocation(config.bess_allocation_path)
    required = {
        "allocation_id",
        "pv_allocation_id",
        "building_id",
        "bus_id",
        "scenario_id",
        "realisation",
    }
    missing = sorted(required - set(allocation.columns))
    if missing:
        raise BESSPandapowerIntegrationError(
            f"BESS allocation is missing required columns: {missing}"
        )

    selected = allocation.loc[
        (allocation["scenario_id"].astype(str) == config.scenario_id)
        & (pd.to_numeric(allocation["realisation"], errors="coerce") == config.realisation)
    ].copy()
    if selected.empty:
        # A valid attachment rate may produce zero BESS after municipality-wise
        # rounding. Preserve this as a valid no-op integration when the complete
        # allocation file is empty. A non-empty file without the requested case
        # still indicates a configuration mismatch and must fail.
        if not allocation.empty:
            raise BESSPandapowerIntegrationError(
                f"No BESS allocation rows for scenario={config.scenario_id!r}, "
                f"realisation={config.realisation}."
            )
        selected["bus_id"] = pd.Series(dtype="int64")
        return selected.reset_index(drop=True)

    for column in ("allocation_id", "pv_allocation_id", "building_id"):
        selected[column] = selected[column].astype(str).str.strip()
        if selected[column].eq("").any():
            raise BESSPandapowerIntegrationError(f"{column} must not be empty.")
    selected["bus_id"] = pd.to_numeric(selected["bus_id"], errors="raise").astype(int)

    if selected["allocation_id"].duplicated().any():
        raise BESSPandapowerIntegrationError("BESS allocation_id is not unique.")
    if selected["pv_allocation_id"].duplicated().any():
        raise BESSPandapowerIntegrationError("A PV unit is referenced by more than one BESS.")
    if selected["building_id"].duplicated().any():
        raise BESSPandapowerIntegrationError("A building contains more than one BESS.")

    return selected.sort_values("allocation_id").reset_index(drop=True)


def build_reference_index(year: int, time_step_minutes: int) -> pd.DatetimeIndex:
    """Build the canonical full-year time index used by the benchmark."""

    return pd.date_range(
        start=f"{year}-01-01 00:00:00",
        end=f"{year + 1}-01-01 00:00:00",
        inclusive="left",
        freq=f"{time_step_minutes}min",
    )


def dispatch_bess_self_consumption(
    residual_kw: Iterable[float],
    *,
    usable_capacity_kwh: float,
    p_max_kw: float,
    eta_charge: float,
    eta_discharge: float,
    dt_hours: float,
    soc_min: float = 0.20,
    soc_max: float = 1.00,
    initial_soc: float = 0.20,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create BESS power, SOC and post-BESS residual series.

    ``residual_kw`` is positive for local demand and negative for PV surplus.
    Output storage power follows pandapower's sign convention:
    positive = charging, negative = discharging.

    The energy state is expressed inside the *usable* energy window. Therefore
    the market-derived usable capacity is not reduced by the 20% SOC floor a
    second time. Reported SOC is only a linear mapping of this usable state to
    the configured SOC interval.
    """

    residual = np.asarray(list(residual_kw), dtype=float)
    if residual.ndim != 1 or residual.size == 0:
        raise BESSPandapowerIntegrationError("residual_kw must be a non-empty 1D series.")
    if not np.isfinite(residual).all():
        raise BESSPandapowerIntegrationError("residual_kw contains non-finite values.")
    if usable_capacity_kwh <= 0 or p_max_kw <= 0 or dt_hours <= 0:
        raise BESSPandapowerIntegrationError("Capacity, power and time step must be positive.")
    if not (0 < eta_charge <= 1 and 0 < eta_discharge <= 1):
        raise BESSPandapowerIntegrationError("Efficiencies must lie within (0, 1].")
    if not 0 <= soc_min < soc_max <= 1 or not soc_min <= initial_soc <= soc_max:
        raise BESSPandapowerIntegrationError("Invalid SOC bounds/initial value.")

    usable_energy = (
        (initial_soc - soc_min) / (soc_max - soc_min) * usable_capacity_kwh
    )
    usable_energy = float(np.clip(usable_energy, 0.0, usable_capacity_kwh))

    p_storage = np.zeros_like(residual)
    soc = np.zeros_like(residual)
    residual_after = np.zeros_like(residual)

    for t, value in enumerate(residual):
        if value < 0.0:  # local PV surplus -> charge
            surplus_kw = -value
            energy_limited_kw = (
                (usable_capacity_kwh - usable_energy)
                / (eta_charge * dt_hours)
            )
            p_charge_kw = max(
                0.0,
                min(surplus_kw, p_max_kw, energy_limited_kw),
            )
            usable_energy += eta_charge * p_charge_kw * dt_hours
            p_storage[t] = p_charge_kw

        elif value > 0.0:  # residual demand -> discharge
            energy_limited_kw = usable_energy * eta_discharge / dt_hours
            p_discharge_kw = max(
                0.0,
                min(value, p_max_kw, energy_limited_kw),
            )
            usable_energy -= p_discharge_kw / eta_discharge * dt_hours
            p_storage[t] = -p_discharge_kw

        usable_energy = float(np.clip(usable_energy, 0.0, usable_capacity_kwh))
        soc[t] = soc_min + (soc_max - soc_min) * (
            usable_energy / usable_capacity_kwh
        )
        residual_after[t] = value + p_storage[t]

    return p_storage, soc, residual_after


def _controller_objects(net: Any) -> list[Any]:
    table = getattr(net, "controller", None)
    if table is None or len(table) == 0 or "object" not in table.columns:
        return []
    return [obj for obj in table["object"].tolist() if obj is not None]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or np.isscalar(value):
        return [value]
    if isinstance(value, pd.Index):
        return value.tolist()
    try:
        return list(value)
    except TypeError:
        return [value]


def _profile_column(df: pd.DataFrame, profile_name: Any) -> pd.Series:
    if profile_name in df.columns:
        return df[profile_name]
    text = str(profile_name)
    for column in df.columns:
        if str(column) == text:
            return df[column]
    raise BESSPandapowerIntegrationError(
        f"Controller profile {profile_name!r} is absent from its DFData table."
    )


def _element_active_power_timeseries(
    net: Any,
    *,
    element: str,
    element_indices: list[int],
    n_steps: int,
) -> pd.DataFrame:
    """Reconstruct p_mw for selected elements from static values + ConstControls."""

    table = getattr(net, element, None)
    if table is None:
        raise BESSPandapowerIntegrationError(f"Network has no {element!r} table.")

    missing = sorted(set(element_indices) - set(table.index.astype(int)))
    if missing:
        raise BESSPandapowerIntegrationError(
            f"Unknown {element} indices requested: {missing[:10]}"
        )

    result = pd.DataFrame(
        {
            int(index): np.full(n_steps, float(table.at[index, "p_mw"]), dtype=float)
            for index in element_indices
        },
        index=pd.RangeIndex(n_steps, name="time_step"),
    )

    requested = set(element_indices)
    for controller in _controller_objects(net):
        if str(getattr(controller, "element", "")) != element:
            continue
        if str(getattr(controller, "variable", "")) != "p_mw":
            continue

        indices = [int(value) for value in _as_list(getattr(controller, "element_index", None))]
        names = _as_list(getattr(controller, "profile_name", None))
        data_source = getattr(controller, "data_source", None)
        df = getattr(data_source, "df", None)
        if df is None:
            continue
        if len(indices) != len(names):
            if len(names) == 1 and len(indices) > 1:
                names = names * len(indices)
            else:
                raise BESSPandapowerIntegrationError(
                    f"{element} controller has {len(indices)} element indices but "
                    f"{len(names)} profile names."
                )
        if len(df) < n_steps:
            raise BESSPandapowerIntegrationError(
                f"{element} controller profile has {len(df)} rows; expected at least {n_steps}."
            )

        for index, name in zip(indices, names):
            if index not in requested:
                continue
            values = pd.to_numeric(_profile_column(df, name).iloc[:n_steps], errors="coerce")
            array = values.to_numpy(dtype=float)
            if not np.isfinite(array).all():
                raise BESSPandapowerIntegrationError(
                    f"Non-finite p_mw values in {element} controller for index {index}."
                )
            result[index] = array

    # pandapower applies the static scaling and in_service flags in addition to
    # the controller p_mw setpoints. Reproduce that behaviour when calculating
    # the local pre-BESS residual load.
    for index in element_indices:
        factor = 1.0
        if "scaling" in table.columns:
            scaling = pd.to_numeric(
                pd.Series([table.at[index, "scaling"]]), errors="coerce"
            ).iloc[0]
            if pd.isna(scaling) or float(scaling) < 0:
                raise BESSPandapowerIntegrationError(
                    f"Invalid {element} scaling for index {index}: {scaling!r}."
                )
            factor *= float(scaling)
        if "in_service" in table.columns and not bool(table.at[index, "in_service"]):
            factor = 0.0
        result[index] *= factor

    return result


def _find_pv_row(net: Any, pv_allocation_id: str) -> tuple[int, pd.Series]:
    if not hasattr(net, "sgen") or "allocation_id" not in net.sgen.columns:
        raise BESSPandapowerIntegrationError(
            "net.sgen has no allocation_id metadata required for PV-coupled BESS."
        )
    matches = net.sgen.loc[
        net.sgen["allocation_id"].astype(str) == str(pv_allocation_id)
    ]
    if len(matches) != 1:
        raise BESSPandapowerIntegrationError(
            f"Expected exactly one PV sgen for allocation {pv_allocation_id!r}, "
            f"found {len(matches)}."
        )
    index = int(matches.index[0])
    return index, matches.iloc[0]


def _validate_coupling(net: Any, allocation: pd.DataFrame, config: BESSPandapowerConfig) -> None:
    missing_buses = sorted(set(allocation["bus_id"]) - set(net.bus.index.astype(int)))
    if missing_buses:
        raise BESSPandapowerIntegrationError(
            f"BESS allocation references buses absent from base net: {missing_buses[:10]}"
        )

    if hasattr(net, "storage") and "allocation_id" in net.storage.columns:
        existing = set(net.storage["allocation_id"].dropna().astype(str))
        overlap = sorted(existing & set(allocation["allocation_id"].astype(str)))
        if overlap:
            raise BESSPandapowerIntegrationError(
                f"BESS allocations are already integrated: {overlap[:10]}"
            )

    if not config.check_building_bus_match:
        return

    for row in allocation.itertuples(index=False):
        _, pv = _find_pv_row(net, str(row.pv_allocation_id))
        if "in_service" in net.sgen.columns and not bool(pv.get("in_service", True)):
            raise BESSPandapowerIntegrationError(
                f"Coupled PV system is out of service for {row.allocation_id}."
            )
        if int(pv["bus"]) != int(row.bus_id):
            raise BESSPandapowerIntegrationError(
                f"PV/BESS bus mismatch for {row.allocation_id}: "
                f"PV bus={int(pv['bus'])}, BESS bus={int(row.bus_id)}."
            )
        if "building_id" in net.sgen.columns:
            pv_building = str(pv.get("building_id", ""))
            if pv_building and pv_building != str(row.building_id):
                raise BESSPandapowerIntegrationError(
                    f"PV/BESS building mismatch for {row.allocation_id}: "
                    f"PV building={pv_building!r}, BESS building={row.building_id!r}."
                )
        if "scenario_id" in net.sgen.columns:
            pv_scenario = str(pv.get("scenario_id", "")).strip()
            if pv_scenario and pv_scenario != config.scenario_id:
                raise BESSPandapowerIntegrationError(
                    f"PV/BESS scenario mismatch for {row.allocation_id}: "
                    f"PV scenario={pv_scenario!r}, expected {config.scenario_id!r}."
                )
        if "realisation" in net.sgen.columns:
            pv_realisation = pd.to_numeric(
                pd.Series([pv.get("realisation")]), errors="coerce"
            ).iloc[0]
            if pd.notna(pv_realisation) and int(pv_realisation) != config.realisation:
                raise BESSPandapowerIntegrationError(
                    f"PV/BESS realisation mismatch for {row.allocation_id}: "
                    f"PV realisation={int(pv_realisation)}, "
                    f"expected {config.realisation}."
                )


def _validate_combined_net_metadata(
    net: Any,
    config: BESSPandapowerConfig,
) -> bool:
    """Validate combined-network metadata when supplied by the existing pipeline."""

    metadata = net.get("combined_status_quo_metadata")
    if metadata is None:
        return False
    if not isinstance(metadata, dict):
        raise BESSPandapowerIntegrationError(
            "combined_status_quo_metadata must be a mapping."
        )

    expected = {
        "scenario_id": config.scenario_id,
        "realisation": config.realisation,
        "reference_year": config.reference_year,
        "time_step_minutes": config.time_step_minutes,
        "n_time_steps": len(
            build_reference_index(config.reference_year, config.time_step_minutes)
        ),
    }
    mismatches = {
        key: {"expected": value, "actual": metadata.get(key)}
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if mismatches:
        raise BESSPandapowerIntegrationError(
            "Combined-network metadata does not match the BESS configuration: "
            f"{mismatches}."
        )
    return True


def build_bess_timeseries(
    net: Any,
    allocation: pd.DataFrame,
    config: BESSPandapowerConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build mapping, BESS p_mw, SOC and pre-BESS residual profiles."""

    time_index = build_reference_index(config.reference_year, config.time_step_minutes)
    n_steps = len(time_index)
    dt_hours = config.time_step_minutes / 60.0

    mapping_rows: list[dict[str, Any]] = []
    p_columns: dict[str, np.ndarray] = {}
    soc_columns: dict[str, np.ndarray] = {}
    residual_columns: dict[str, np.ndarray] = {}

    for row in allocation.itertuples(index=False):
        pv_index, pv = _find_pv_row(net, str(row.pv_allocation_id))
        bus_id = int(row.bus_id)

        load_indices = net.load.index[net.load["bus"].astype(int) == bus_id].astype(int).tolist()
        if load_indices:
            load_ts = _element_active_power_timeseries(
                net,
                element="load",
                element_indices=load_indices,
                n_steps=n_steps,
            )
            load_kw = load_ts.sum(axis=1).to_numpy(dtype=float) * 1000.0
        else:
            load_kw = np.zeros(n_steps, dtype=float)

        pv_ts = _element_active_power_timeseries(
            net,
            element="sgen",
            element_indices=[pv_index],
            n_steps=n_steps,
        )
        pv_kw = pv_ts[pv_index].to_numpy(dtype=float) * 1000.0
        residual_kw = load_kw - pv_kw

        if "nominal_power_kwp" in net.sgen.columns:
            pv_nominal = pd.to_numeric(pd.Series([pv.get("nominal_power_kwp")]), errors="coerce").iloc[0]
        else:
            pv_nominal = np.nan
        if pd.isna(pv_nominal) or float(pv_nominal) <= 0:
            pv_nominal_kwp = config.default_pv_nominal_power_kwp
        else:
            pv_nominal_kwp = float(pv_nominal)

        usable_capacity_kwh = (
            config.usable_capacity_ratio_kwh_per_kwp * pv_nominal_kwp
        )
        p_max_kw = (
            config.power_to_usable_energy_ratio_per_h * usable_capacity_kwh
        )

        p_storage_kw, soc, residual_after_kw = dispatch_bess_self_consumption(
            residual_kw,
            usable_capacity_kwh=usable_capacity_kwh,
            p_max_kw=p_max_kw,
            eta_charge=config.eta_charge,
            eta_discharge=config.eta_discharge,
            dt_hours=dt_hours,
            soc_min=config.soc_min,
            soc_max=config.soc_max,
            initial_soc=config.initial_soc,
        )

        allocation_id = str(row.allocation_id)
        p_columns[allocation_id] = p_storage_kw / 1000.0
        soc_columns[allocation_id] = soc
        residual_columns[allocation_id] = residual_kw

        mapping_rows.append(
            {
                "allocation_id": allocation_id,
                "pv_allocation_id": str(row.pv_allocation_id),
                "building_id": str(row.building_id),
                "bus_id": bus_id,
                "pv_sgen_index": pv_index,
                "pv_nominal_power_kwp": pv_nominal_kwp,
                "usable_capacity_kwh": usable_capacity_kwh,
                "p_max_kw": p_max_kw,
                "soc_min": config.soc_min,
                "soc_max": config.soc_max,
                "initial_soc": config.initial_soc,
                "eta_charge": config.eta_charge,
                "eta_discharge": config.eta_discharge,
                "post_bess_peak_import_kw": float(np.max(residual_after_kw)),
                "post_bess_peak_export_kw": float(max(0.0, -np.min(residual_after_kw))),
            }
        )

    index = pd.RangeIndex(n_steps, name="time_step")
    mapping_columns = [
        "allocation_id",
        "pv_allocation_id",
        "building_id",
        "bus_id",
        "pv_sgen_index",
        "pv_nominal_power_kwp",
        "usable_capacity_kwh",
        "p_max_kw",
        "soc_min",
        "soc_max",
        "initial_soc",
        "eta_charge",
        "eta_discharge",
        "post_bess_peak_import_kw",
        "post_bess_peak_export_kw",
    ]
    mapping = pd.DataFrame(mapping_rows, columns=mapping_columns)
    p_mw = pd.DataFrame(p_columns, index=index)
    soc = pd.DataFrame(soc_columns, index=index)
    residual_kw = pd.DataFrame(residual_columns, index=index)
    return mapping, p_mw, soc, residual_kw


def _add_bess_storage_elements(
    pp: Any,
    net: Any,
    allocation: pd.DataFrame,
    mapping: pd.DataFrame,
    config: BESSPandapowerConfig,
) -> pd.DataFrame:
    """Create one pandapower storage element per BESS allocation."""

    lookup = mapping.set_index("allocation_id")
    rows: list[dict[str, Any]] = []

    for row in allocation.itertuples(index=False):
        allocation_id = str(row.allocation_id)
        info = lookup.loc[allocation_id]
        usable_capacity_kwh = float(info["usable_capacity_kwh"])
        p_max_kw = float(info["p_max_kw"])
        soc_window = config.soc_max - config.soc_min
        rated_capacity_kwh = usable_capacity_kwh / soc_window

        storage_index = pp.create_storage(
            net,
            bus=int(row.bus_id),
            p_mw=0.0,
            # The Austrian 1.01 kWh/kWp input is usable capacity.  pandapower's
            # max_e_mwh is stored as an equivalent rated capacity so that the
            # configured SOC window represents exactly the same usable energy.
            max_e_mwh=rated_capacity_kwh / 1000.0,
            q_mvar=config.q_mvar,
            sn_mva=p_max_kw / 1000.0,
            soc_percent=100.0 * config.initial_soc,
            name=allocation_id,
            in_service=config.in_service,
        )

        metadata = {
            "technology": "BESS",
            "allocation_id": allocation_id,
            "pv_allocation_id": str(row.pv_allocation_id),
            "building_id": str(row.building_id),
            "scenario_id": config.scenario_id,
            "realisation": config.realisation,
            "usable_capacity_kwh": usable_capacity_kwh,
            "rated_capacity_kwh": rated_capacity_kwh,
            "p_max_kw": p_max_kw,
            "dispatch_strategy": "self_consumption",
            "profile_source": "precomputed_local_residual",
            "model_layer": "technology_storage",
        }
        for column, value in metadata.items():
            if column not in net.storage.columns:
                net.storage[column] = np.nan if isinstance(value, (int, float)) else None
            net.storage.at[storage_index, column] = value

        rows.append(
            {
                "allocation_id": allocation_id,
                **info.to_dict(),
                "rated_capacity_kwh": rated_capacity_kwh,
                "storage_index": int(storage_index),
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            *mapping.columns,
            "rated_capacity_kwh",
            "storage_index",
        ],
    )


def _attach_bess_const_control(
    net: Any,
    mapping: pd.DataFrame,
    p_mw: pd.DataFrame,
) -> int:
    if mapping.empty:
        return 0

    try:
        from pandapower.control import ConstControl
        from pandapower.timeseries import DFData
    except ImportError as exc:  # pragma: no cover
        raise BESSPandapowerIntegrationError(
            "pandapower ConstControl/DFData are required for BESS time series."
        ) from exc

    storage_indices = mapping["storage_index"].astype(int).tolist()
    allocation_ids = mapping["allocation_id"].astype(str).tolist()

    ConstControl(
        net,
        element="storage",
        variable="p_mw",
        element_index=storage_indices,
        profile_name=allocation_ids,
        data_source=DFData(p_mw),
    )

    first = p_mw.iloc[0]
    for storage_index, allocation_id in zip(storage_indices, allocation_ids):
        net.storage.at[storage_index, "p_mw"] = float(first[allocation_id])
    return 1


def integrate_bess(
    config: BESSPandapowerConfig,
) -> BESSPandapowerIntegrationResult:
    """Add precomputed self-consumption BESS profiles to a combined network."""

    config.validate()
    try:
        import pandapower as pp
    except ImportError as exc:  # pragma: no cover
        raise BESSPandapowerIntegrationError("pandapower is required.") from exc

    if not config.base_net_path.exists():
        raise FileNotFoundError(config.base_net_path)

    allocation = _load_allocation(config)
    net = pp.from_pickle(str(config.base_net_path))
    combined_metadata_checked = _validate_combined_net_metadata(net, config)
    _validate_coupling(net, allocation, config)
    base_storage_table = getattr(net, "storage", None)
    base_storage_count = (
        int(len(base_storage_table)) if base_storage_table is not None else 0
    )

    mapping, p_mw, soc, residual_kw = build_bess_timeseries(net, allocation, config)
    mapping = _add_bess_storage_elements(pp, net, allocation, mapping, config)
    controller_count = _attach_bess_const_control(net, mapping, p_mw)

    enriched_storage_count = int(len(net.storage))
    expected_storage_count = base_storage_count + int(len(allocation))
    if enriched_storage_count != expected_storage_count:
        raise BESSPandapowerIntegrationError(
            "Unexpected storage count after BESS integration: "
            f"expected {expected_storage_count}, got {enriched_storage_count}."
        )

    # Structural/time-series validation.
    pmax = mapping.set_index("allocation_id")["p_max_kw"] / 1000.0
    for allocation_id in p_mw.columns:
        if (p_mw[allocation_id].abs() > float(pmax[allocation_id]) + 1e-12).any():
            raise BESSPandapowerIntegrationError(
                f"BESS power limit violated for {allocation_id}."
            )
    if (soc.to_numpy() < config.soc_min - 1e-12).any() or (
        soc.to_numpy() > config.soc_max + 1e-12
    ).any():
        raise BESSPandapowerIntegrationError("BESS SOC bounds are violated.")

    # Sign-rule validation: positive p is only allowed during pre-BESS export;
    # negative p is only allowed during pre-BESS import.
    p_kw = p_mw * 1000.0
    if ((p_kw > 1e-10) & (residual_kw >= -1e-10)).to_numpy().any():
        raise BESSPandapowerIntegrationError("Detected grid charging in baseline BESS dispatch.")
    if ((p_kw < -1e-10) & (residual_kw <= 1e-10)).to_numpy().any():
        raise BESSPandapowerIntegrationError("Detected deliberate battery export in baseline dispatch.")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.output_net_path.parent.mkdir(parents=True, exist_ok=True)

    time_index = build_reference_index(config.reference_year, config.time_step_minutes)
    time_index_csv = config.output_dir / "bess_time_index.csv"
    mapping_csv = config.output_dir / "bess_mapping.csv"
    power_csv = config.output_dir / "bess_power_profiles_mw.csv.gz"
    soc_csv = config.output_dir / "bess_soc_profiles.csv.gz"
    residual_csv = config.output_dir / "bess_pre_dispatch_residual_kw.csv.gz"
    validation_json = config.output_dir / "bess_pandapower_validation.json"
    metadata_json = config.output_dir / "bess_pandapower_metadata.json"

    pd.DataFrame(
        {"time_step": np.arange(len(time_index)), "time": time_index.astype(str)}
    ).to_csv(time_index_csv, index=False)
    mapping.to_csv(mapping_csv, index=False)
    p_mw.to_csv(power_csv, index=True, compression="gzip")
    soc.to_csv(soc_csv, index=True, compression="gzip")
    residual_kw.to_csv(residual_csv, index=True, compression="gzip")

    validation = {
        "all_checks_passed": True,
        "project_name": config.project_name,
        "scenario_id": config.scenario_id,
        "realisation": config.realisation,
        "bess_count": int(len(mapping)),
        "base_storage_count": base_storage_count,
        "enriched_storage_count": enriched_storage_count,
        "storage_count_matches_allocation": (
            enriched_storage_count == expected_storage_count
        ),
        "n_time_steps": int(len(time_index)),
        "reference_year": config.reference_year,
        "time_step_minutes": config.time_step_minutes,
        "pv_coupling_checked": True,
        "combined_network_metadata_available_and_checked": (
            combined_metadata_checked
        ),
        "power_limits_checked": True,
        "soc_bounds_checked": True,
        "grid_charging_forbidden_and_checked": True,
        "battery_export_forbidden_and_checked": True,
        "controller_count_added": controller_count,
        "empty_allocation_handled_as_no_op": int(len(mapping)) == 0,
        "base_net_unchanged_on_disk": config.output_net_path.resolve()
        != config.base_net_path.resolve(),
    }
    validation_json.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    metadata = asdict(config)
    metadata = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in metadata.items()
    }
    metadata["sign_convention"] = (
        "pandapower storage p_mw > 0 charging; p_mw < 0 discharging"
    )
    metadata["usable_capacity_interpretation"] = (
        "The 1.01 kWh/kWp market parameter is already usable capacity. The "
        "dispatch state therefore spans this complete usable window; SOC 20...100% "
        "does not reduce usable capacity again. pandapower max_e_mwh stores the "
        "equivalent rated capacity E_use/(SOC_max-SOC_min) for metadata consistency."
    )
    metadata_json.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    net["bess_metadata"] = {
        "scenario_id": config.scenario_id,
        "realisation": config.realisation,
        "bess_count": int(len(mapping)),
        "reference_year": config.reference_year,
        "time_step_minutes": config.time_step_minutes,
        "dispatch_strategy": "self_consumption",
    }
    pp.to_pickle(net, str(config.output_net_path))

    output_files = {
        "mapping_csv": mapping_csv,
        "power_profiles_csv_gz": power_csv,
        "soc_profiles_csv_gz": soc_csv,
        "pre_dispatch_residual_csv_gz": residual_csv,
        "time_index_csv": time_index_csv,
        "validation_json": validation_json,
        "metadata_json": metadata_json,
        "output_net": config.output_net_path,
    }

    return BESSPandapowerIntegrationResult(
        bess_count=int(len(mapping)),
        n_time_steps=int(len(time_index)),
        reference_year=config.reference_year,
        time_step_minutes=config.time_step_minutes,
        output_net_path=config.output_net_path,
        output_files=output_files,
    )
