"""Integrate allocated photovoltaic systems and APCS E1 into pandapower.

The spatial PV allocation determines where each photovoltaic system is connected.
This module adds one dedicated pandapower ``sgen`` per allocated PV unit, assigns
one configurable nominal power, and attaches a common normalized APCS E1 time
profile through ``ConstControl``.

The default model intentionally stays simple:

* one allocation row = one ``sgen``;
* 12 kWp per PV unit;
* APCS E1 (type 15) as common 15-minute temporal shape;
* annual-yield scaling to 1000 kWh/kWp by default;
* ``P(t) = P_nom * pv_pu(t)``;
* ``q_mvar = 0``.

The base ``net.p`` is loaded as immutable input and is never overwritten.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)
from lv_scenario_benchmark.time_axis import (
    TimeAxisError,
    align_annual_sequence_to_reference_year,
)


class PVPandapowerIntegrationError(RuntimeError):
    """Raised when PV/pandapower/APCS integration is inconsistent."""


@dataclass(frozen=True)
class PVPandapowerConfig:
    """Resolved configuration for PV-to-pandapower time-series integration."""

    project_name: str
    scenario_id: str
    realisation: int

    seiler_parameters_path: Path
    base_net_path: Path
    pv_allocation_path: Path
    output_net_path: Path
    output_dir: Path
    profile_path: Path

    in_service: bool = True
    check_building_bus_match: bool = True
    nominal_power_kwp: float = 12.0
    q_mvar: float = 0.0

    profile_source: str = "APCS"
    profile_type_number: int = 15
    profile_id: str = "APCS_E1_2025"
    # profile_normalization: str = "peak"
    profile_normalization: str = "annual_yield"
    specific_yield_kwh_per_kwp: float = 1000.0
    time_step_minutes: int = 15
    reference_year: int = 2025
    time_alignment_method: str = "annual_sequence"

    def validate(self) -> None:
        if not self.project_name.strip():
            raise PVPandapowerIntegrationError(
                "project_name must not be empty."
            )

        if not self.scenario_id.strip():
            raise PVPandapowerIntegrationError(
                "scenario_id must not be empty."
            )

        if self.realisation < 0:
            raise PVPandapowerIntegrationError(
                "realisation must be non-negative."
            )

        if self.output_net_path.resolve() == self.base_net_path.resolve():
            raise PVPandapowerIntegrationError(
                "The enriched PV network must not overwrite the base net.p."
            )

        if self.nominal_power_kwp <= 0:
            raise PVPandapowerIntegrationError(
                "nominal_power_kwp must be positive."
            )

        if self.q_mvar != 0.0:
            raise PVPandapowerIntegrationError(
                "The current simple PV model supports q_mvar = 0 only."
            )

        if self.profile_type_number <= 0:
            raise PVPandapowerIntegrationError(
                "profile_type_number must be positive."
            )

        if not self.profile_id.strip():
            raise PVPandapowerIntegrationError(
                "profile_id must not be empty."
            )

        # if self.profile_normalization != "peak":
        #     raise PVPandapowerIntegrationError(
        #         "The current PV implementation supports "
        #         "profile.normalization='peak' only."
        #     )
        if self.profile_normalization != "annual_yield":
            raise PVPandapowerIntegrationError(
                "The current PV implementation supports "
                "profile.normalization='annual_yield' only."
            )

        if self.specific_yield_kwh_per_kwp <= 0:
            raise PVPandapowerIntegrationError(
                "specific_yield_kwh_per_kwp must be positive."
            )

        if self.time_step_minutes <= 0:
            raise PVPandapowerIntegrationError(
                "time_step_minutes must be positive."
            )

        if self.reference_year < 1900:
            raise PVPandapowerIntegrationError(
                "reference_year must be >= 1900."
            )

        if self.time_alignment_method != "annual_sequence":
            raise PVPandapowerIntegrationError(
                "PV time_alignment_method must be 'annual_sequence'."
            )


@dataclass(frozen=True)
class PVPandapowerIntegrationResult:
    """Products created by PV + APCS pandapower integration."""

    pv_count: int
    base_sgen_count: int
    enriched_sgen_count: int
    n_time_steps: int
    output_net_path: Path
    output_files: dict[str, Path]
    validation: dict[str, Any]


def _resolve_path(
    base: Path,
    value: str | Path | None,
) -> Path | None:
    if value is None:
        return None

    path = Path(value)

    if path.is_absolute():
        return path.resolve()

    return (base / path).resolve()


def load_pv_pandapower_config(
    path: str | Path,
) -> PVPandapowerConfig:
    """Load YAML configuration and derive project-specific paths."""

    try:
        import yaml
    except ImportError as exc:
        raise PVPandapowerIntegrationError(
            "PyYAML is required to read the configuration."
        ) from exc

    config_path = Path(path).resolve()

    raw = yaml.safe_load(
        config_path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(raw, dict):
        raise PVPandapowerIntegrationError(
            "The YAML root must be a mapping."
        )

    project = raw.get("project", {})
    case = raw.get("case", {})
    paths = raw.get("paths", {})
    integration = raw.get("integration", {})
    profile = raw.get("profile", {})
    time_alignment = raw.get(
        "time_alignment",
        {},
    )

    base = config_path.parent

    parameters_path = _resolve_path(
        base,
        project.get(
            "parameters",
            "../../external/seiler/scripts/parameters.py",
        ),
    )

    if parameters_path is None:
        raise PVPandapowerIntegrationError(
            "project.parameters is required."
        )

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get(
                "pandapower_net_filename",
                "net.p",
            ),
        )
    except (
        ProjectContextError,
        FileNotFoundError,
    ) as exc:
        raise PVPandapowerIntegrationError(
            str(exc)
        ) from exc

    scenario_id = str(
        case.get(
            "scenario_id",
            "pv_status_quo",
        )
    ).strip()

    realisation = int(
        case.get(
            "realisation",
            0,
        )
    )

    allocation_output_root = _resolve_path(
        base,
        paths.get(
            "allocation_output_root",
            "../../outputs",
        ),
    )

    integration_output_root = _resolve_path(
        base,
        paths.get(
            "integration_output_root",
            "../../outputs",
        ),
    )

    profile_path = _resolve_path(
        base,
        profile.get(
            "file",
            "../data/raw/APCS_synthload_2025.csv",
        ),
    )

    if (
        allocation_output_root is None
        or integration_output_root is None
    ):
        raise PVPandapowerIntegrationError(
            "paths.allocation_output_root and "
            "paths.integration_output_root are required."
        )

    if profile_path is None:
        raise PVPandapowerIntegrationError(
            "profile.file is required."
        )

    allocation_filename = str(
        paths.get(
            "allocation_filename",
            "pv_status_quo_allocation.parquet",
        )
    ).strip()

    if not allocation_filename:
        raise PVPandapowerIntegrationError(
            "paths.allocation_filename must not be empty."
        )

    output_net_filename = str(
        integration.get(
            "output_net_filename",
            "net_status_quo_pv.p",
        )
    ).strip()

    if not output_net_filename:
        raise PVPandapowerIntegrationError(
            "integration.output_net_filename must not be empty."
        )

    if Path(output_net_filename).name != output_net_filename:
        raise PVPandapowerIntegrationError(
            "integration.output_net_filename must be "
            "a filename, not a path."
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

    config = PVPandapowerConfig(
        project_name=project_context.project_name,
        scenario_id=scenario_id,
        realisation=realisation,
        seiler_parameters_path=parameters_path,
        base_net_path=project_context.pandapower_net_path,
        pv_allocation_path=(allocation_dir / allocation_filename).resolve(),
        output_net_path=(integration_dir / output_net_filename).resolve(),
        output_dir=integration_dir,
        profile_path=profile_path,
        in_service=bool(
            integration.get(
                "in_service",
                True,
            )
        ),
        check_building_bus_match=bool(
            integration.get(
                "check_building_bus_match",
                True,
            )
        ),
        nominal_power_kwp=float(
            integration.get(
                "nominal_power_kwp",
                12.0,
            )
        ),
        q_mvar=float(
            integration.get(
                "q_mvar",
                0.0,
            )
        ),
        profile_source=str(
            profile.get(
                "source",
                "APCS",
            )
        ).strip(),
        profile_type_number=int(
            profile.get(
                "type_number",
                15,
            )
        ),
        profile_id=str(
            profile.get(
                "profile_id",
                "APCS_E1_2025",
            )
        ).strip(),
        # profile_normalization=str(
        #     profile.get(
        #         "normalization",
        #         "peak",
        #     )
        # ).strip(),
        # time_step_minutes=int(
        #     profile.get(
        #         "time_step_minutes",
        #         15,
        #     )
        # ),
        profile_normalization=str(
            profile.get(
                "normalization",
                "annual_yield",
            )
        ).strip(),
        specific_yield_kwh_per_kwp=float(
            profile.get(
                "specific_yield_kwh_per_kwp",
                1000.0,
            )
        ),
        time_step_minutes=int(
            profile.get(
                "time_step_minutes",
                15,
            )
        ),
        reference_year=int(
            time_alignment.get(
                "reference_year",
                2025,
            )
        ),
        time_alignment_method=str(
            time_alignment.get(
                "method",
                "annual_sequence",
            )
        ).strip(),
    )

    config.validate()

    return config


def _load_allocation(
    config: PVPandapowerConfig,
) -> pd.DataFrame:
    """Load and validate the selected PV allocation realisation."""

    path = config.pv_allocation_path

    if not path.exists():
        csv_fallback = path.with_suffix(
            ".csv"
        )

        if csv_fallback.exists():
            path = csv_fallback
        else:
            raise FileNotFoundError(
                config.pv_allocation_path
            )

    if path.suffix.lower() == ".parquet":
        allocation = pd.read_parquet(
            path
        )

    elif path.suffix.lower() == ".csv":
        allocation = pd.read_csv(
            path
        )

    else:
        raise PVPandapowerIntegrationError(
            "Unsupported PV allocation format: "
            f"{path.suffix}"
        )

    required = {
        "allocation_id",
        "building_id",
        "bus_id",
        "scenario_id",
        "realisation",
    }

    missing = sorted(
        required
        - set(allocation.columns)
    )

    if missing:
        raise PVPandapowerIntegrationError(
            "PV allocation is missing required columns: "
            f"{missing}"
        )

    selected = allocation.loc[
        (
            allocation[
                "scenario_id"
            ].astype(str)
            == config.scenario_id
        )
        & (
            pd.to_numeric(
                allocation["realisation"],
                errors="coerce",
            )
            == config.realisation
        )
    ].copy()

    if selected.empty:
        raise PVPandapowerIntegrationError(
            "No PV allocation rows for "
            f"scenario={config.scenario_id!r}, "
            f"realisation={config.realisation}."
        )

    selected["allocation_id"] = (
        selected["allocation_id"]
        .astype(str)
        .str.strip()
    )

    selected["building_id"] = (
        selected["building_id"]
        .astype(str)
        .str.strip()
    )

    if (
        selected[
            "allocation_id"
        ].eq("").any()
        or selected[
            "building_id"
        ].eq("").any()
    ):
        raise PVPandapowerIntegrationError(
            "allocation_id and building_id "
            "must not be empty."
        )

    if selected[
        "allocation_id"
    ].duplicated().any():
        raise PVPandapowerIntegrationError(
            "allocation_id is not unique "
            "in the selected PV realisation."
        )

    bus_numeric = pd.to_numeric(
        selected["bus_id"],
        errors="coerce",
    )

    if bus_numeric.isna().any():
        bad = selected.loc[
            bus_numeric.isna(),
            "allocation_id",
        ].tolist()

        raise PVPandapowerIntegrationError(
            "Non-numeric bus_id in "
            f"PV allocation: {bad[:10]}"
        )

    selected["bus_id"] = (
        bus_numeric.astype(int)
    )

    return (
        selected
        .sort_values("allocation_id")
        .reset_index(drop=True)
    )


def _validate_bus_mapping(
    net: Any,
    allocation: pd.DataFrame,
    config: PVPandapowerConfig,
) -> None:
    """Ensure every allocation bus exists and belongs to the same building."""

    missing_buses = sorted(
        set(allocation["bus_id"])
        - set(net.bus.index)
    )

    if missing_buses:
        raise PVPandapowerIntegrationError(
            "PV allocation references buses "
            "absent from base net: "
            f"{missing_buses[:10]}"
        )

    if not config.check_building_bus_match:
        return

    if "node_id" not in net.bus.columns:
        raise PVPandapowerIntegrationError(
            "net.bus has no 'node_id' column required "
            "for building/bus validation."
        )

    mismatches: list[
        tuple[str, int, str]
    ] = []

    for row in allocation.itertuples(
        index=False
    ):
        actual = str(
            net.bus.at[
                int(row.bus_id),
                "node_id",
            ]
        ).strip()

        if (
            actual
            != str(row.building_id).strip()
        ):
            mismatches.append(
                (
                    str(row.building_id),
                    int(row.bus_id),
                    actual,
                )
            )

    if mismatches:
        raise PVPandapowerIntegrationError(
            "At least one PV building no longer "
            "matches its stored pandapower bus. "
            f"Examples: {mismatches[:10]}"
        )


def _ensure_not_already_integrated(
    net: Any,
    allocation: pd.DataFrame,
) -> None:
    """Fail instead of silently duplicating PV sgens."""

    if net.sgen.empty:
        return

    allocation_ids = set(
        allocation[
            "allocation_id"
        ].astype(str)
    )

    if "allocation_id" in net.sgen.columns:
        existing = (
            set(
                net.sgen[
                    "allocation_id"
                ]
                .dropna()
                .astype(str)
            )
            & allocation_ids
        )

        if existing:
            raise PVPandapowerIntegrationError(
                "The selected PV allocation is already "
                "present in the input net. "
                f"Examples: {sorted(existing)[:10]}"
            )

    if "name" in net.sgen.columns:
        existing_names = (
            set(
                net.sgen["name"]
                .dropna()
                .astype(str)
            )
            & allocation_ids
        )

        if existing_names:
            raise PVPandapowerIntegrationError(
                "PV sgen names already exist "
                "in the input net. "
                f"Examples: {sorted(existing_names)[:10]}"
            )


# def load_apcs_pv_profile(
#     path: str | Path,
#     type_number: int = 15,
#     normalization: str = "peak",
# ) -> pd.DataFrame:
#     """Load APCS E1 and return the normalized temporal PV shape.

#     The returned frame contains ``time`` and ``pv_pu``.
#     With peak normalization the highest APCS E1 value becomes 1.0.

#     The source timestamps are intentionally preserved here.
#     Mapping to the canonical benchmark reference-year axis is
#     performed separately by ``align_annual_sequence_to_reference_year``.
#     """

#     profile_path = Path(path)

#     if not profile_path.exists():
#         raise FileNotFoundError(
#             profile_path
#         )

#     if normalization != "peak":
#         raise PVPandapowerIntegrationError(
#             "Only peak normalization is supported "
#             "for APCS PV profiles."
#         )

#     frame = pd.read_csv(
#         profile_path,
#         sep=";",
#         decimal=",",
#         encoding="latin1",
#     )

#     required = {
#         "Typnummer",
#         "Zeit",
#         "Wert",
#     }

#     missing = sorted(
#         required
#         - set(frame.columns)
#     )

#     if missing:
#         raise PVPandapowerIntegrationError(
#             "APCS profile file is missing "
#             f"required columns: {missing}"
#         )

#     frame["Typnummer"] = pd.to_numeric(
#         frame["Typnummer"],
#         errors="coerce",
#     )

#     selected = frame.loc[
#         frame["Typnummer"]
#         == int(type_number),
#         [
#             "Zeit",
#             "Wert",
#         ],
#     ].copy()

#     if selected.empty:
#         raise PVPandapowerIntegrationError(
#             "No APCS profile rows found for "
#             f"Typnummer {type_number}."
#         )

#     selected["time"] = pd.to_datetime(
#         selected["Zeit"],
#         errors="raise",
#     )

#     selected["value"] = pd.to_numeric(
#         selected["Wert"],
#         errors="raise",
#     )

#     selected = (
#         selected[
#             [
#                 "time",
#                 "value",
#             ]
#         ]
#         .sort_values("time")
#         .reset_index(drop=True)
#     )

#     if selected[
#         "time"
#     ].duplicated().any():
#         raise PVPandapowerIntegrationError(
#             "APCS PV profile contains "
#             "duplicate timestamps."
#         )

#     if not np.isfinite(
#         selected[
#             "value"
#         ].to_numpy(dtype=float)
#     ).all():
#         raise PVPandapowerIntegrationError(
#             "APCS PV profile contains "
#             "non-finite values."
#         )

#     if (
#         selected["value"]
#         < 0
#     ).any():
#         raise PVPandapowerIntegrationError(
#             "APCS PV profile contains "
#             "negative values."
#         )

#     maximum = float(
#         selected["value"].max()
#     )

#     if maximum <= 0:
#         raise PVPandapowerIntegrationError(
#             "APCS PV profile maximum "
#             "must be greater than zero."
#         )

#     selected["pv_pu"] = (
#         selected["value"]
#         / maximum
#     )

#     return selected[
#         [
#             "time",
#             "pv_pu",
#         ]
#     ]
def load_apcs_pv_profile(
    path: str | Path,
    type_number: int = 15,
    normalization: str = "annual_yield",
    specific_yield_kwh_per_kwp: float = 1000.0,
    time_step_minutes: int = 15,
) -> pd.DataFrame:
    """Load APCS E1 and scale it to a specific annual PV yield.

    The returned frame contains ``time`` and ``pv_pu``.

    The temporal shape of the APCS E1 profile is preserved. Instead of
    normalising the profile to its annual maximum, it is scaled such that
    the annual integral of ``pv_pu`` equals the configured specific annual
    PV yield in kWh/kWp.

    Multiplying ``pv_pu`` by the nominal PV power in kW therefore yields
    the absolute PV power time series in kW.

    Parameters
    ----------
    path : str | Path
        Path to the APCS synthetic load-profile CSV file.
    type_number : int, optional
        APCS profile type number. Type 15 corresponds to E1 photovoltaic
        generation, by default 15.
    normalization : str, optional
        Profile scaling method. Currently only ``annual_yield`` is
        supported.
    specific_yield_kwh_per_kwp : float, optional
        Assumed annual PV yield in kWh per installed kWp, by default
        1000 kWh/kWp/a.
    time_step_minutes : int, optional
        Temporal resolution of the APCS profile in minutes, by default
        15 minutes.

    Returns
    -------
    pd.DataFrame
        DataFrame containing ``time`` and the scaled relative PV profile
        ``pv_pu``.

    Raises
    ------
    PVPandapowerIntegrationError
        If the APCS data or configuration is inconsistent.
    """

    profile_path = Path(path)

    if not profile_path.exists():
        raise FileNotFoundError(
            profile_path
        )

    if normalization != "annual_yield":
        raise PVPandapowerIntegrationError(
            "Only annual_yield normalization is supported "
            "for APCS PV profiles."
        )

    if specific_yield_kwh_per_kwp <= 0:
        raise PVPandapowerIntegrationError(
            "specific_yield_kwh_per_kwp must be positive."
        )

    if time_step_minutes <= 0:
        raise PVPandapowerIntegrationError(
            "time_step_minutes must be positive."
        )

    frame = pd.read_csv(
        profile_path,
        sep=";",
        decimal=",",
        encoding="latin1",
    )

    required = {
        "Typnummer",
        "Zeit",
        "Wert",
    }

    missing = sorted(
        required
        - set(frame.columns)
    )

    if missing:
        raise PVPandapowerIntegrationError(
            "APCS profile file is missing "
            f"required columns: {missing}"
        )

    frame["Typnummer"] = pd.to_numeric(
        frame["Typnummer"],
        errors="coerce",
    )

    selected = frame.loc[
        frame["Typnummer"]
        == int(type_number),
        [
            "Zeit",
            "Wert",
        ],
    ].copy()

    if selected.empty:
        raise PVPandapowerIntegrationError(
            "No APCS profile rows found for "
            f"Typnummer {type_number}."
        )

    selected["time"] = pd.to_datetime(
        selected["Zeit"],
        errors="raise",
    )

    selected["value"] = pd.to_numeric(
        selected["Wert"],
        errors="raise",
    )

    selected = (
        selected[
            [
                "time",
                "value",
            ]
        ]
        .sort_values("time")
        .reset_index(drop=True)
    )

    if selected[
        "time"
    ].duplicated().any():
        raise PVPandapowerIntegrationError(
            "APCS PV profile contains "
            "duplicate timestamps."
        )

    values = selected[
        "value"
    ].to_numpy(
        dtype=float
    )

    if not np.isfinite(
        values
    ).all():
        raise PVPandapowerIntegrationError(
            "APCS PV profile contains "
            "non-finite values."
        )

    if (
        selected["value"]
        < 0
    ).any():
        raise PVPandapowerIntegrationError(
            "APCS PV profile contains "
            "negative values."
        )

    dt_h = (
        time_step_minutes
        / 60.0
    )

    raw_annual_integral = float(
        selected["value"].sum()
        * dt_h
    )

    if raw_annual_integral <= 0:
        raise PVPandapowerIntegrationError(
            "APCS PV profile annual integral "
            "must be greater than zero."
        )

    scale_factor = (
        specific_yield_kwh_per_kwp
        / raw_annual_integral
    )

    selected["pv_pu"] = (
        selected["value"]
        * scale_factor
    )

    observed_specific_yield = float(
        selected["pv_pu"].sum()
        * dt_h
    )

    if not np.isclose(
        observed_specific_yield,
        specific_yield_kwh_per_kwp,
        rtol=0,
        atol=1e-6,
    ):
        raise PVPandapowerIntegrationError(
            "Scaled APCS PV profile does not reproduce "
            "the configured specific annual yield."
        )

    profile_peak_pu = float(
        selected["pv_pu"].max()
    )

    if profile_peak_pu > 1.0 + 1e-12:
        raise PVPandapowerIntegrationError(
            "Annual-yield-scaled PV profile exceeds "
            "1.0 p.u. and would therefore exceed the "
            "configured nominal PV power."
        )

    return selected[
        [
            "time",
            "pv_pu",
        ]
    ]

def _add_pv_sgens(
    pp: Any,
    net: Any,
    allocation: pd.DataFrame,
    config: PVPandapowerConfig,
) -> pd.DataFrame:
    """Create one pandapower sgen per allocated PV unit."""

    nominal_power_mw = (
        config.nominal_power_kwp
        / 1000.0
    )

    mapping_rows: list[
        dict[str, Any]
    ] = []

    for row in allocation.itertuples(
        index=False
    ):
        sgen_index = pp.create_sgen(
            net,
            bus=int(row.bus_id),
            p_mw=0.0,
            q_mvar=config.q_mvar,
            sn_mva=nominal_power_mw,
            name=str(
                row.allocation_id
            ),
            in_service=config.in_service,
        )

        metadata = {
            "technology": "PV_STATUS_QUO",
            "allocation_id": str(
                row.allocation_id
            ),
            "building_id": str(
                row.building_id
            ),
            "scenario_id": str(
                row.scenario_id
            ),
            "realisation": int(
                row.realisation
            ),
            "nominal_power_kwp": float(
                config.nominal_power_kwp
            ),
            "profile_id": str(
                config.profile_id
            ),
            "profile_source": str(
                config.profile_source
            ),
            "model_layer": (
                "technology_generation"
            ),
            "source": (
                "status_quo_allocation+APCS"
            ),
        }

        for column, value in metadata.items():
            if column not in net.sgen.columns:
                net.sgen[column] = (
                    np.nan
                    if isinstance(
                        value,
                        (float, int),
                    )
                    else None
                )

            net.sgen.at[
                sgen_index,
                column,
            ] = value

        mapping_rows.append(
            {
                "sgen_index": int(
                    sgen_index
                ),
                "allocation_id": str(
                    row.allocation_id
                ),
                "building_id": str(
                    row.building_id
                ),
                "bus_id": int(
                    row.bus_id
                ),
                "scenario_id": str(
                    row.scenario_id
                ),
                "realisation": int(
                    row.realisation
                ),
                "nominal_power_kwp": float(
                    config.nominal_power_kwp
                ),
                "profile_id": str(
                    config.profile_id
                ),
            }
        )

    return pd.DataFrame(
        mapping_rows
    )


def build_pv_absolute_timeseries(
    mapping: pd.DataFrame,
    normalized_profile: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.Series,
]:
    """Build absolute PV active-power time series in MW."""

    if mapping.empty:
        raise PVPandapowerIntegrationError(
            "Cannot build PV time series "
            "for empty mapping."
        )

    if normalized_profile.empty:
        raise PVPandapowerIntegrationError(
            "Normalized PV profile is empty."
        )

    if (
        "pv_pu"
        not in normalized_profile.columns
    ):
        raise PVPandapowerIntegrationError(
            "Normalized PV profile has "
            "no pv_pu column."
        )

    pu = pd.to_numeric(
        normalized_profile[
            "pv_pu"
        ],
        errors="coerce",
    ).to_numpy(
        dtype=float
    )

    if not np.isfinite(
        pu
    ).all():
        raise PVPandapowerIntegrationError(
            "pv_pu contains "
            "non-finite values."
        )

    if (
        (pu < -1e-12).any()
        or (
            pu
            > 1.0 + 1e-12
        ).any()
    ):
        raise PVPandapowerIntegrationError(
            "pv_pu must remain within 0...1."
        )

    allocation_ids = (
        mapping[
            "allocation_id"
        ]
        .astype(str)
        .tolist()
    )

    nominal_mw = (
        pd.to_numeric(
            mapping[
                "nominal_power_kwp"
            ],
            errors="raise",
        )
        .to_numpy(
            dtype=float
        )
        / 1000.0
    )

    if (
        nominal_mw
        <= 0
    ).any():
        raise PVPandapowerIntegrationError(
            "PV nominal power must be positive."
        )

    values = (
        pu.reshape(-1, 1)
        * nominal_mw.reshape(
            1,
            -1,
        )
    )

    p_absolute = pd.DataFrame(
        values,
        index=pd.RangeIndex(
            len(
                normalized_profile
            ),
            name="time_step",
        ),
        columns=allocation_ids,
    )

    if (
        "time"
        in normalized_profile.columns
    ):
        time_labels = (
            normalized_profile[
                "time"
            ]
            .reset_index(
                drop=True
            )
            .copy()
        )
    else:
        time_labels = pd.Series(
            np.arange(
                len(
                    normalized_profile
                )
            ),
            name="time",
        )

    time_labels.name = "time"

    return (
        p_absolute,
        time_labels,
    )


def _attach_pv_const_control(
    net: Any,
    mapping: pd.DataFrame,
    p_absolute: pd.DataFrame,
) -> int:
    """Attach one pandapower ConstControl for PV active power."""

    try:
        from pandapower.control import (
            ConstControl,
        )
        from pandapower.timeseries import (
            DFData,
        )
    except ImportError as exc:
        raise PVPandapowerIntegrationError(
            "pandapower ConstControl/DFData "
            "are required for PV time series."
        ) from exc

    sgen_indices = (
        mapping[
            "sgen_index"
        ]
        .astype(int)
        .tolist()
    )

    allocation_ids = (
        mapping[
            "allocation_id"
        ]
        .astype(str)
        .tolist()
    )

    ConstControl(
        net,
        element="sgen",
        variable="p_mw",
        element_index=sgen_indices,
        profile_name=allocation_ids,
        data_source=DFData(
            p_absolute
        ),
    )

    first_p = (
        p_absolute.iloc[0]
    )

    for (
        sgen_index,
        allocation_id,
    ) in zip(
        sgen_indices,
        allocation_ids,
    ):
        net.sgen.at[
            sgen_index,
            "p_mw",
        ] = float(
            first_p[
                allocation_id
            ]
        )

    return 1


def _table_counts(
    net: Any,
) -> dict[str, int]:
    result: dict[
        str,
        int,
    ] = {}

    for name in [
        "bus",
        "line",
        "trafo",
        "load",
        "ext_grid",
        "sgen",
    ]:
        table = getattr(
            net,
            name,
            None,
        )

        if table is not None:
            result[name] = int(
                len(table)
            )

    return result


def integrate_pv_status_quo(
    config: PVPandapowerConfig,
) -> PVPandapowerIntegrationResult:
    """Create a simulation-ready PV-enriched pandapower network."""

    config.validate()

    try:
        import pandapower as pp
    except ImportError as exc:
        raise PVPandapowerIntegrationError(
            "pandapower is required "
            "for PV network integration."
        ) from exc

    if not config.base_net_path.exists():
        raise FileNotFoundError(
            config.base_net_path
        )

    if not config.profile_path.exists():
        raise FileNotFoundError(
            config.profile_path
        )

    allocation = _load_allocation(
        config
    )

    base_net = pp.from_pickle(
        str(
            config.base_net_path
        )
    )

    _validate_bus_mapping(
        base_net,
        allocation,
        config,
    )

    _ensure_not_already_integrated(
        base_net,
        allocation,
    )

    # normalized_profile = (
    #     load_apcs_pv_profile(
    #         config.profile_path,
    #         type_number=(
    #             config.profile_type_number
    #         ),
    #         normalization=(
    #             config.profile_normalization
    #         ),
    #     )
    # )
    normalized_profile = (
        load_apcs_pv_profile(
            config.profile_path,
            type_number=(
                config.profile_type_number
            ),
            normalization=(
                config.profile_normalization
            ),
            specific_yield_kwh_per_kwp=(
                config.specific_yield_kwh_per_kwp
            ),
            time_step_minutes=(
                config.time_step_minutes
            ),
        )
    )

    try:
        alignment = (
            align_annual_sequence_to_reference_year(
                normalized_profile,
                config.reference_year,
                time_column="time",
                time_step_minutes=(
                    config.time_step_minutes
                ),
            )
        )
    except TimeAxisError as exc:
        raise PVPandapowerIntegrationError(
            "Could not align APCS PV profile "
            "to the benchmark reference year: "
            f"{exc}"
        ) from exc

    normalized_profile = (
        alignment.frame
    )

    time_alignment_mapping = (
        alignment.mapping
    )

    base_counts = _table_counts(
        base_net
    )

    base_sgen_count = int(
        len(
            base_net.sgen
        )
    )

    enriched_net = deepcopy(
        base_net
    )

    mapping = _add_pv_sgens(
        pp,
        enriched_net,
        allocation,
        config,
    )

    (
        p_absolute,
        time_labels,
    ) = build_pv_absolute_timeseries(
        mapping,
        normalized_profile,
    )

    controller_count_added = (
        _attach_pv_const_control(
            enriched_net,
            mapping,
            p_absolute,
        )
    )

    enriched_counts = _table_counts(
        enriched_net
    )

    enriched_sgen_count = int(
        len(
            enriched_net.sgen
        )
    )

    expected_sgen_count = (
        base_sgen_count
        + len(allocation)
    )

    if (
        enriched_sgen_count
        != expected_sgen_count
    ):
        raise PVPandapowerIntegrationError(
            "Unexpected sgen count "
            "after PV integration: "
            f"expected {expected_sgen_count}, "
            f"got {enriched_sgen_count}."
        )

    for table in [
        "bus",
        "line",
        "trafo",
        "load",
        "ext_grid",
    ]:
        if (
            table in base_counts
            and table in enriched_counts
        ):
            if (
                base_counts[table]
                != enriched_counts[table]
            ):
                raise PVPandapowerIntegrationError(
                    f"Table {table!r} changed "
                    "during PV-only integration."
                )

    pv_rows = (
        enriched_net.sgen.loc[
            enriched_net.sgen[
                "technology"
            ]
            .astype(str)
            .eq(
                "PV_STATUS_QUO"
            )
        ]
    )

    if (
        len(pv_rows)
        != len(allocation)
    ):
        raise PVPandapowerIntegrationError(
            "Integrated PV sgen count "
            "does not match the "
            "selected allocation."
        )

    # peak_power_mw = (
    #     config.nominal_power_kwp
    #     / 1000.0
    # )

    # observed_peak_mw = float(
    #     p_absolute
    #     .to_numpy()
    #     .max()
    # )

    # if not np.isclose(
    #     observed_peak_mw,
    #     peak_power_mw,
    #     rtol=0,
    #     atol=1e-12,
    # ):
    #     raise PVPandapowerIntegrationError(
    #         "Peak-normalized PV profile "
    #         "does not reach the configured "
    #         "nominal power."
    #     )
    dt_h = (
        config.time_step_minutes
        / 60.0
    )

    observed_specific_yield = float(
        normalized_profile["pv_pu"].sum()
        * dt_h
    )

    if not np.isclose(
        observed_specific_yield,
        config.specific_yield_kwh_per_kwp,
        rtol=0,
        atol=1e-6,
    ):
        raise PVPandapowerIntegrationError(
            "PV profile does not reproduce the configured "
            "specific annual yield."
        )

    peak_power_mw = (
        config.nominal_power_kwp
        / 1000.0
    )

    observed_peak_mw = float(
        p_absolute
        .to_numpy()
        .max()
    )

    if observed_peak_mw > peak_power_mw + 1e-12:
        raise PVPandapowerIntegrationError(
            "PV profile exceeds the configured "
            "nominal PV power."
        )

    annual_energy_per_unit_kwh = (
        config.nominal_power_kwp
        * observed_specific_yield
    )

    total_pv_annual_energy_mwh = (
        annual_energy_per_unit_kwh
        * len(mapping)
        / 1000.0
    )

    enriched_net[
        "pv_timeseries_metadata"
    ] = {
        "source": (
            config.profile_source
        ),
        "profile_id": (
            config.profile_id
        ),
        "profile_type_number": (
            config.profile_type_number
        ),
        # "normalization": (
        #     "value / max(value)"
        # ),
        "normalization": (
            "annual_yield"
        ),
        "specific_yield_kwh_per_kwp": (
            config.specific_yield_kwh_per_kwp
        ),
        "annual_energy_per_unit_kwh": (
            annual_energy_per_unit_kwh
        ),
        "total_pv_annual_energy_mwh": (
            total_pv_annual_energy_mwh
        ),
        "nominal_power_kwp": (
            config.nominal_power_kwp
        ),
        "q_mvar": (
            config.q_mvar
        ),
        "n_time_steps": int(
            len(
                p_absolute
            )
        ),
        "time_step_minutes": (
            config.time_step_minutes
        ),
        "reference_year": (
            config.reference_year
        ),
        "time_alignment_method": (
            config.time_alignment_method
        ),
        "pv_sgen_indices": (
            mapping[
                "sgen_index"
            ]
            .astype(int)
            .tolist()
        ),
    }

    config.output_net_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    config.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pp.to_pickle(
        enriched_net,
        str(
            config.output_net_path
        ),
    )

    mapping_csv = (
        config.output_dir
        / "pv_pandapower_mapping.csv"
    )

    normalized_profile_csv = (
        config.output_dir
        / "pv_apcs_e1_2025_normalized.csv"
    )

    time_index_csv = (
        config.output_dir
        / "pv_apcs_time_index.csv"
    )

    alignment_mapping_csv = (
        config.output_dir
        / "pv_time_alignment_mapping.csv"
    )

    validation_json = (
        config.output_dir
        / "pv_pandapower_validation.json"
    )

    metadata_json = (
        config.output_dir
        / "pv_pandapower_metadata.json"
    )

    mapping.to_csv(
        mapping_csv,
        index=False,
    )

    normalized_profile.to_csv(
        normalized_profile_csv,
        index=False,
    )

    pd.DataFrame(
        {
            "time_step": np.arange(
                len(
                    time_labels
                ),
                dtype=int,
            ),
            "time": (
                time_labels
                .astype(str)
                .to_numpy()
            ),
        }
    ).to_csv(
        time_index_csv,
        index=False,
    )

    time_alignment_mapping.to_csv(
        alignment_mapping_csv,
        index=False,
    )

    validation = {
        "pv_count": int(
            len(mapping)
        ),
        "base_sgen_count": (
            base_sgen_count
        ),
        "enriched_sgen_count": (
            enriched_sgen_count
        ),
        "n_time_steps": int(
            len(
                p_absolute
            )
        ),
        "profile_min_pu": float(
            normalized_profile[
                "pv_pu"
            ].min()
        ),
        "profile_max_pu": float(
            normalized_profile[
                "pv_pu"
            ].max()
        ),
        "nominal_power_kwp": float(
            config.nominal_power_kwp
        ),
        "absolute_peak_mw": (
            observed_peak_mw
        ),
        "specific_yield_target_kwh_per_kwp": float(
            config.specific_yield_kwh_per_kwp
        ),
        "specific_yield_observed_kwh_per_kwp": float(
            observed_specific_yield
        ),
        "annual_energy_per_unit_kwh": float(
            annual_energy_per_unit_kwh
        ),
        "total_pv_annual_energy_mwh": float(
            total_pv_annual_energy_mwh
        ),
        "controller_count_added": (
            controller_count_added
        ),
        "base_net_unchanged_on_disk": True,
        "reference_year": (
            config.reference_year
        ),
        "time_alignment_method": (
            config.time_alignment_method
        ),
    }

    validation_json.write_text(
        json.dumps(
            validation,
            indent=2,
        ),
        encoding="utf-8",
    )

    metadata = asdict(
        config
    )

    metadata = {
        key: (
            str(value)
            if isinstance(
                value,
                Path,
            )
            else value
        )
        for key, value
        in metadata.items()
    }

    # metadata[
    #     "profile_formula"
    # ] = (
    #     "pv_pu(t) = APCS_E1(t) / max(APCS_E1)"
    # )
    metadata[
        "profile_formula"
    ] = (
        "pv_pu(t) = APCS_E1(t) * "
        "specific_yield_kwh_per_kwp / "
        "(sum(APCS_E1) * delta_t_h)"
    )

    metadata[
        "power_formula"
    ] = (
        "p_mw_i(t) = nominal_power_kwp_i "
        "/ 1000 * pv_pu(t)"
    )

    metadata_json.write_text(
        json.dumps(
            metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    output_files = {
        "mapping_csv": (
            mapping_csv
        ),
        "normalized_profile_csv": (
            normalized_profile_csv
        ),
        "time_index_csv": (
            time_index_csv
        ),
        "alignment_mapping_csv": (
            alignment_mapping_csv
        ),
        "validation_json": (
            validation_json
        ),
        "metadata_json": (
            metadata_json
        ),
    }

    return PVPandapowerIntegrationResult(
        pv_count=int(
            len(mapping)
        ),
        base_sgen_count=(
            base_sgen_count
        ),
        enriched_sgen_count=(
            enriched_sgen_count
        ),
        n_time_steps=int(
            len(
                p_absolute
            )
        ),
        output_net_path=(
            config.output_net_path
        ),
        output_files=(
            output_files
        ),
        validation=(
            validation
        ),
    )