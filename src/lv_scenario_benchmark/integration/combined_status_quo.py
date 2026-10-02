"""Combined status-quo integration of PV, EV and HP into one pandapower net.

The module deliberately reuses the three existing technology-specific
integration pipelines. The immutable Seiler ``net.p`` is loaded only by the
first enabled technology. Each following technology receives the output of the
previous stage as its base network. This avoids merging independently enriched
pandapower networks and therefore avoids duplicated buses, lines, transformers,
base loads and controllers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Any

import pandas as pd

from lv_scenario_benchmark.integration.ev_pandapower import (
    EVPandapowerConfig,
    EVPandapowerIntegrationResult,
    integrate_ev_status_quo,
    load_ev_pandapower_config,
)
from lv_scenario_benchmark.integration.hp_pandapower import (
    HPPandapowerConfig,
    HPPandapowerIntegrationResult,
    integrate_hp_status_quo,
    load_hp_pandapower_config,
)
from lv_scenario_benchmark.integration.pv_pandapower import (
    PVPandapowerConfig,
    PVPandapowerIntegrationResult,
    integrate_pv_status_quo,
    load_pv_pandapower_config,
)
from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)


INTEGRATION_ORDER = ("pv", "ev", "hp")


class CombinedStatusQuoIntegrationError(RuntimeError):
    """Raised when combined status-quo integration cannot be completed."""


@dataclass(frozen=True)
class CombinedStatusQuoConfig:
    """Resolved configuration for combined PV/EV/HP integration."""

    project_name: str
    scenario_id: str
    realisation: int

    seiler_parameters_path: Path
    base_net_path: Path
    output_net_path: Path
    output_dir: Path
    figure_dir: Path

    pv_enabled: bool
    ev_enabled: bool
    hp_enabled: bool

    pv_config_path: Path | None = None
    ev_config_path: Path | None = None
    hp_config_path: Path | None = None

    aoi_id: str = ""
    aoi_path: Path | None = None
    grid_buildings_path: Path | None = None
    working_crs: str = "EPSG:9273"
    aoi_crs_if_missing: str | None = "EPSG:4326"
    building_crs_if_missing: str | None = None

    plot_enabled: bool = True
    plot_basemap: bool = True
    plot_dpi: int = 600
    plot_figsize: tuple[float, float] = (12.0, 12.0)
    cleanup_intermediate_files: bool = True

    def validate(self) -> None:
        if not self.project_name.strip():
            raise CombinedStatusQuoIntegrationError(
                "project_name must not be empty."
            )
        if not self.scenario_id.strip():
            raise CombinedStatusQuoIntegrationError(
                "scenario_id must not be empty."
            )
        if self.realisation < 0:
            raise CombinedStatusQuoIntegrationError(
                "realisation must be non-negative."
            )
        if not any((self.pv_enabled, self.ev_enabled, self.hp_enabled)):
            raise CombinedStatusQuoIntegrationError(
                "At least one technology must be enabled."
            )
        if self.output_net_path.resolve() == self.base_net_path.resolve():
            raise CombinedStatusQuoIntegrationError(
                "The combined network must not overwrite the immutable base net.p."
            )
        for technology, enabled, config_path in (
            ("pv", self.pv_enabled, self.pv_config_path),
            ("ev", self.ev_enabled, self.ev_config_path),
            ("hp", self.hp_enabled, self.hp_config_path),
        ):
            if enabled and config_path is None:
                raise CombinedStatusQuoIntegrationError(
                    f"technologies.{technology}.config is required when "
                    f"{technology.upper()} is enabled."
                )
            if enabled and config_path is not None and not config_path.exists():
                raise FileNotFoundError(config_path)
        if self.plot_dpi < 72:
            raise CombinedStatusQuoIntegrationError(
                "plotting.dpi must be at least 72."
            )

    @property
    def enabled_technologies(self) -> tuple[str, ...]:
        enabled: list[str] = []
        if self.pv_enabled:
            enabled.append("pv")
        if self.ev_enabled:
            enabled.append("ev")
        if self.hp_enabled:
            enabled.append("hp")
        return tuple(enabled)


@dataclass(frozen=True)
class CombinedStatusQuoIntegrationResult:
    """Products created by the combined status-quo integration pipeline."""

    enabled_technologies: tuple[str, ...]
    pv_count: int
    ev_count: int
    hp_count: int
    n_time_steps: int
    reference_year: int
    time_step_minutes: int
    output_net_path: Path
    output_files: dict[str, Path]
    validation: dict[str, Any]


def _resolve_path(base: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_combined_status_quo_config(
    path: str | Path,
) -> CombinedStatusQuoConfig:
    """Load the combined YAML and resolve project-specific paths."""

    try:
        import yaml
    except ImportError as exc:
        raise CombinedStatusQuoIntegrationError(
            "PyYAML is required to read the configuration."
        ) from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CombinedStatusQuoIntegrationError(
            "The YAML root must be a mapping."
        )

    project = raw.get("project", {})
    case = raw.get("case", {})
    technologies = raw.get("technologies", {})
    paths = raw.get("paths", {})
    integration = raw.get("integration", {})
    plotting = raw.get("plotting", {})
    spatial = raw.get("spatial", {})
    base = config_path.parent

    parameters_path = _resolve_path(
        base,
        project.get("parameters", "../../external/seiler/scripts/parameters.py"),
    )
    if parameters_path is None:
        raise CombinedStatusQuoIntegrationError(
            "project.parameters is required."
        )

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=project.get(
                "pandapower_net_filename", "net.p"
            ),
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise CombinedStatusQuoIntegrationError(str(exc)) from exc

    scenario_id = str(
        case.get("scenario_id", "status_quo_combined")
    ).strip()
    realisation = int(case.get("realisation", 0))

    integration_output_root = _resolve_path(
        base,
        paths.get("integration_output_root", "../../outputs"),
    )
    if integration_output_root is None:
        raise CombinedStatusQuoIntegrationError(
            "paths.integration_output_root is required."
        )

    output_net_filename = str(
        integration.get(
            "output_net_filename", "net_status_quo_combined.p"
        )
    ).strip()
    if not output_net_filename:
        raise CombinedStatusQuoIntegrationError(
            "integration.output_net_filename must not be empty."
        )
    if Path(output_net_filename).name != output_net_filename:
        raise CombinedStatusQuoIntegrationError(
            "integration.output_net_filename must be a filename, not a path."
        )

    scenario_root = (
        integration_output_root
        / project_context.project_name
        / scenario_id
    ).resolve()
    output_dir = (scenario_root / "integration").resolve()
    figure_dir = (scenario_root / "figures").resolve()

    figsize = plotting.get("figsize", [12, 12])
    if not isinstance(figsize, (list, tuple)) or len(figsize) != 2:
        raise CombinedStatusQuoIntegrationError(
            "plotting.figsize must contain exactly two numbers."
        )

    def technology_settings(name: str) -> tuple[bool, Path | None]:
        value = technologies.get(name, {})
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise CombinedStatusQuoIntegrationError(
                f"technologies.{name} must be a mapping."
            )
        enabled = bool(value.get("enabled", False))
        config_value = value.get("config")
        return enabled, _resolve_path(base, config_value)

    pv_enabled, pv_config_path = technology_settings("pv")
    ev_enabled, ev_config_path = technology_settings("ev")
    hp_enabled, hp_config_path = technology_settings("hp")

    working_crs = spatial.get("working_crs")
    if working_crs is None:
        working_crs = project_context.working_crs

    config = CombinedStatusQuoConfig(
        project_name=project_context.project_name,
        scenario_id=scenario_id,
        realisation=realisation,
        seiler_parameters_path=parameters_path,
        base_net_path=project_context.pandapower_net_path,
        output_net_path=(output_dir / output_net_filename).resolve(),
        output_dir=output_dir,
        figure_dir=figure_dir,
        pv_enabled=pv_enabled,
        ev_enabled=ev_enabled,
        hp_enabled=hp_enabled,
        pv_config_path=pv_config_path,
        ev_config_path=ev_config_path,
        hp_config_path=hp_config_path,
        aoi_id=project_context.project_name,
        aoi_path=project_context.aoi_path,
        grid_buildings_path=project_context.grid_buildings_path,
        working_crs=str(working_crs),
        aoi_crs_if_missing=spatial.get(
            "aoi_crs_if_missing", "EPSG:4326"
        ),
        building_crs_if_missing=spatial.get("building_crs_if_missing"),
        plot_enabled=bool(plotting.get("enabled", True)),
        plot_basemap=bool(plotting.get("basemap", True)),
        plot_dpi=int(plotting.get("dpi", 600)),
        plot_figsize=(float(figsize[0]), float(figsize[1])),
        cleanup_intermediate_files=bool(
            integration.get("cleanup_intermediate_files", True)
        ),
    )
    config.validate()
    return config


def _load_technology_configs(
    config: CombinedStatusQuoConfig,
) -> dict[str, PVPandapowerConfig | EVPandapowerConfig | HPPandapowerConfig]:
    """Load enabled technology configs and force the combined realisation."""

    technology_configs: dict[
        str,
        PVPandapowerConfig | EVPandapowerConfig | HPPandapowerConfig,
    ] = {}

    allocation_dir = (
        config.output_dir.parent
        / "allocation"
    ).resolve()

    if config.pv_enabled:
        assert config.pv_config_path is not None
        pv_config = load_pv_pandapower_config(config.pv_config_path)
        technology_configs["pv"] = replace(
            pv_config,
            scenario_id=config.scenario_id,
            realisation=config.realisation,
            pv_allocation_path=(
                allocation_dir
                / pv_config.pv_allocation_path.name
            ).resolve(),
        )

    if config.ev_enabled:
        assert config.ev_config_path is not None
        ev_config = load_ev_pandapower_config(config.ev_config_path)
        technology_configs["ev"] = replace(
            ev_config,
            scenario_id=config.scenario_id,
            realisation=config.realisation,
            ev_allocation_path=(
                allocation_dir
                / ev_config.ev_allocation_path.name
            ).resolve(),
        )

    if config.hp_enabled:
        assert config.hp_config_path is not None
        hp_config = load_hp_pandapower_config(config.hp_config_path)
        technology_configs["hp"] = replace(
            hp_config,
            scenario_id=config.scenario_id,
            realisation=config.realisation,
            hp_allocation_path=(
                allocation_dir
                / hp_config.hp_allocation_path.name
            ).resolve(),
        )

    for technology, technology_config in technology_configs.items():
        if technology_config.project_name != config.project_name:
            raise CombinedStatusQuoIntegrationError(
                f"{technology.upper()} config resolves PROJECT "
                f"{technology_config.project_name!r}, expected "
                f"{config.project_name!r}."
            )

    return technology_configs


def _validate_configured_time_axis(
    technology_configs: dict[
        str,
        PVPandapowerConfig | EVPandapowerConfig | HPPandapowerConfig,
    ],
) -> tuple[int, int]:
    """Require one common benchmark year and time-step resolution."""

    reference_years = {
        int(technology_config.reference_year)
        for technology_config in technology_configs.values()
    }
    if len(reference_years) != 1:
        details = {
            name: int(technology_config.reference_year)
            for name, technology_config in technology_configs.items()
        }
        raise CombinedStatusQuoIntegrationError(
            "Enabled technologies use different reference years: "
            f"{details}."
        )

    time_steps = {
        int(technology_config.time_step_minutes)
        for technology_config in technology_configs.values()
    }
    if len(time_steps) != 1:
        details = {
            name: int(technology_config.time_step_minutes)
            for name, technology_config in technology_configs.items()
        }
        raise CombinedStatusQuoIntegrationError(
            "Enabled technologies use different time-step resolutions: "
            f"{details}."
        )

    return next(iter(reference_years)), next(iter(time_steps))


def _read_result_time_index(
    technology: str,
    result: PVPandapowerIntegrationResult
    | EVPandapowerIntegrationResult
    | HPPandapowerIntegrationResult,
) -> pd.DatetimeIndex:
    """Read the normalized time axis written by a technology integration."""

    path = result.output_files.get("time_index_csv")
    if path is None:
        raise CombinedStatusQuoIntegrationError(
            f"{technology.upper()} integration did not report a time_index_csv."
        )
    path = Path(path)
    if not path.exists():
        raise CombinedStatusQuoIntegrationError(
            f"{technology.upper()} time-index file does not exist: {path}"
        )

    frame = pd.read_csv(path)
    value_columns = [column for column in frame.columns if column != "time_step"]
    if len(value_columns) != 1:
        raise CombinedStatusQuoIntegrationError(
            f"{technology.upper()} time-index file must contain exactly one "
            f"timestamp column besides 'time_step': {path}"
        )

    timestamps = pd.to_datetime(frame[value_columns[0]], errors="coerce")
    if timestamps.isna().any():
        bad = (
            frame.loc[timestamps.isna(), value_columns[0]]
            .head(5)
            .astype(str)
            .tolist()
        )
        raise CombinedStatusQuoIntegrationError(
            f"Could not parse {technology.upper()} time-index values: {bad}"
        )

    return pd.DatetimeIndex(timestamps)


def _validate_result_time_axes(
    results: dict[
        str,
        PVPandapowerIntegrationResult
        | EVPandapowerIntegrationResult
        | HPPandapowerIntegrationResult,
    ],
) -> int:
    """Require equal number of steps and exactly equal normalized timestamps."""

    n_time_steps = {
        technology: int(result.n_time_steps)
        for technology, result in results.items()
    }
    if len(set(n_time_steps.values())) != 1:
        raise CombinedStatusQuoIntegrationError(
            "Enabled integrations produced different numbers of time steps: "
            f"{n_time_steps}."
        )

    reference_name: str | None = None
    reference_index: pd.DatetimeIndex | None = None
    for technology in INTEGRATION_ORDER:
        if technology not in results:
            continue
        current_index = _read_result_time_index(technology, results[technology])
        if len(current_index) != n_time_steps[technology]:
            raise CombinedStatusQuoIntegrationError(
                f"{technology.upper()} reports {n_time_steps[technology]} time "
                f"steps but its time-index file contains {len(current_index)} rows."
            )
        if reference_index is None:
            reference_name = technology
            reference_index = current_index
            continue
        if not reference_index.equals(current_index):
            mismatch = next(
                (
                    index
                    for index, (left, right) in enumerate(
                        zip(reference_index, current_index)
                    )
                    if left != right
                ),
                None,
            )
            if mismatch is None and len(reference_index) != len(current_index):
                mismatch = min(len(reference_index), len(current_index))
            raise CombinedStatusQuoIntegrationError(
                "Normalized technology time axes are not identical. "
                f"First mismatch between {reference_name.upper()} and "
                f"{technology.upper()} at step {mismatch}."
            )

    return next(iter(n_time_steps.values()))


def _table_counts(net: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ("bus", "line", "trafo", "load", "sgen", "ext_grid", "controller"):
        frame = getattr(net, table, None)
        if frame is not None:
            try:
                counts[table] = int(len(frame))
            except TypeError:
                pass
    return counts


def _technology_count(frame: Any, technology: str) -> int:
    if frame is None or "technology" not in frame.columns:
        return 0
    return int(frame["technology"].astype(str).eq(technology).sum())


def _validate_and_annotate_final_net(
    config: CombinedStatusQuoConfig,
    results: dict[
        str,
        PVPandapowerIntegrationResult
        | EVPandapowerIntegrationResult
        | HPPandapowerIntegrationResult,
    ],
    *,
    reference_year: int,
    time_step_minutes: int,
    n_time_steps: int,
) -> dict[str, Any]:
    """Validate final structure, attach combined metadata, and resave the net."""

    try:
        import pandapower as pp
    except ImportError as exc:
        raise CombinedStatusQuoIntegrationError(
            "pandapower is required for final combined-network validation."
        ) from exc

    if not config.base_net_path.exists():
        raise FileNotFoundError(config.base_net_path)
    if not config.output_net_path.exists():
        raise FileNotFoundError(config.output_net_path)

    base_net = pp.from_pickle(str(config.base_net_path))
    final_net = pp.from_pickle(str(config.output_net_path))
    base_counts = _table_counts(base_net)
    final_counts = _table_counts(final_net)

    for table in ("bus", "line", "trafo", "ext_grid"):
        if table in base_counts and table in final_counts:
            if base_counts[table] != final_counts[table]:
                raise CombinedStatusQuoIntegrationError(
                    f"Base topology table {table!r} changed during combined "
                    f"integration: {base_counts[table]} -> {final_counts[table]}."
                )

    pv_count = int(results["pv"].pv_count) if "pv" in results else 0
    ev_count = int(results["ev"].ev_count) if "ev" in results else 0
    hp_count = int(results["hp"].hp_count) if "hp" in results else 0

    expected_load_count = base_counts.get("load", 0) + ev_count + hp_count
    expected_sgen_count = base_counts.get("sgen", 0) + pv_count
    if final_counts.get("load", 0) != expected_load_count:
        raise CombinedStatusQuoIntegrationError(
            "Unexpected final load count: expected "
            f"{expected_load_count}, got {final_counts.get('load', 0)}."
        )
    if final_counts.get("sgen", 0) != expected_sgen_count:
        raise CombinedStatusQuoIntegrationError(
            "Unexpected final sgen count: expected "
            f"{expected_sgen_count}, got {final_counts.get('sgen', 0)}."
        )

    actual_pv_count = _technology_count(getattr(final_net, "sgen", None), "PV_STATUS_QUO")
    actual_ev_count = _technology_count(getattr(final_net, "load", None), "EV")
    actual_hp_count = _technology_count(getattr(final_net, "load", None), "HP")
    actual_counts = {
        "pv": actual_pv_count,
        "ev": actual_ev_count,
        "hp": actual_hp_count,
    }
    expected_counts = {
        "pv": pv_count,
        "ev": ev_count,
        "hp": hp_count,
    }
    if actual_counts != expected_counts:
        raise CombinedStatusQuoIntegrationError(
            "Technology counts in the final net do not match the integration "
            f"results: expected {expected_counts}, got {actual_counts}."
        )

    metadata = {
        "project_name": config.project_name,
        "scenario_id": config.scenario_id,
        "realisation": config.realisation,
        "enabled_technologies": list(config.enabled_technologies),
        "integration_order": [
            technology
            for technology in INTEGRATION_ORDER
            if technology in results
        ],
        "reference_year": reference_year,
        "time_step_minutes": time_step_minutes,
        "n_time_steps": n_time_steps,
        "pv_count": pv_count,
        "ev_count": ev_count,
        "hp_count": hp_count,
        "base_net_path": str(config.base_net_path),
        "base_table_counts": base_counts,
        "final_table_counts": final_counts,
    }
    final_net["combined_status_quo_metadata"] = metadata
    pp.to_pickle(final_net, str(config.output_net_path))

    return {
        "all_checks_passed": True,
        "base_net_preserved": config.output_net_path.resolve()
        != config.base_net_path.resolve(),
        "project_name": config.project_name,
        "scenario_id": config.scenario_id,
        "realisation": config.realisation,
        "enabled_technologies": list(config.enabled_technologies),
        "integration_order": metadata["integration_order"],
        "reference_year": reference_year,
        "time_step_minutes": time_step_minutes,
        "n_time_steps": n_time_steps,
        "pv_units_added": pv_count,
        "ev_units_added": ev_count,
        "hp_units_added": hp_count,
        "base_table_counts": base_counts,
        "final_table_counts": final_counts,
        "technology_counts_in_final_net": actual_counts,
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


def integrate_combined_status_quo(
    config: CombinedStatusQuoConfig,
) -> CombinedStatusQuoIntegrationResult:
    """Sequentially add enabled technologies to one common pandapower net."""

    config.validate()
    if not config.base_net_path.exists():
        raise FileNotFoundError(config.base_net_path)

    technology_configs = _load_technology_configs(config)
    reference_year, time_step_minutes = _validate_configured_time_axis(
        technology_configs
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    if config.plot_enabled:
        config.figure_dir.mkdir(parents=True, exist_ok=True)

    enabled = [
        technology
        for technology in INTEGRATION_ORDER
        if technology in technology_configs
    ]
    current_net_path = config.base_net_path
    stage_paths: list[Path] = []
    results: dict[
        str,
        PVPandapowerIntegrationResult
        | EVPandapowerIntegrationResult
        | HPPandapowerIntegrationResult,
    ] = {}

    try:
        for index, technology in enumerate(enabled):
            is_last = index == len(enabled) - 1
            if is_last:
                output_net_path = config.output_net_path
            else:
                output_net_path = (
                    config.output_dir
                    / f"_stage_{index + 1:02d}_{technology}.p"
                ).resolve()
                stage_paths.append(output_net_path)

            technology_output_dir = (
                config.output_dir / technology
            ).resolve()
            technology_output_dir.mkdir(parents=True, exist_ok=True)

            if technology == "pv":
                base_config = technology_configs["pv"]
                assert isinstance(base_config, PVPandapowerConfig)
                stage_config = replace(
                    base_config,
                    base_net_path=current_net_path,
                    output_net_path=output_net_path,
                    output_dir=technology_output_dir,
                )
                result = integrate_pv_status_quo(stage_config)
            elif technology == "ev":
                base_config = technology_configs["ev"]
                assert isinstance(base_config, EVPandapowerConfig)
                stage_config = replace(
                    base_config,
                    base_net_path=current_net_path,
                    output_net_path=output_net_path,
                    output_dir=technology_output_dir,
                )
                result = integrate_ev_status_quo(stage_config)
            elif technology == "hp":
                base_config = technology_configs["hp"]
                assert isinstance(base_config, HPPandapowerConfig)
                stage_config = replace(
                    base_config,
                    base_net_path=current_net_path,
                    output_net_path=output_net_path,
                    output_dir=technology_output_dir,
                )
                result = integrate_hp_status_quo(stage_config)
            else:  # pragma: no cover - protected by INTEGRATION_ORDER
                raise CombinedStatusQuoIntegrationError(
                    f"Unsupported technology {technology!r}."
                )

            results[technology] = result
            current_net_path = result.output_net_path

        if current_net_path.resolve() != config.output_net_path.resolve():
            raise CombinedStatusQuoIntegrationError(
                "Combined integration did not produce the configured final net."
            )

        n_time_steps = _validate_result_time_axes(results)
        validation = _validate_and_annotate_final_net(
            config,
            results,
            reference_year=reference_year,
            time_step_minutes=time_step_minutes,
            n_time_steps=n_time_steps,
        )

        validation_json = config.output_dir / "combined_validation.json"
        metadata_json = config.output_dir / "combined_metadata.json"

        validation_json.write_text(
            json.dumps(validation, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        metadata = _json_ready(asdict(config))
        metadata["integration_order"] = enabled
        metadata["technology_configs"] = {
            technology: _json_ready(asdict(technology_configs[technology]))
            for technology in enabled
        }
        metadata["technology_results"] = {
            technology: _json_ready(asdict(results[technology]))
            for technology in enabled
        }
        metadata_json.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        output_files: dict[str, Path] = {
            "validation_json": validation_json,
            "metadata_json": metadata_json,
        }
        for technology, result in results.items():
            for label, path in result.output_files.items():
                output_files[f"{technology}_{label}"] = Path(path)

        if config.plot_enabled:
            from lv_scenario_benchmark.visualisation.combined_allocation import (
                plot_combined_allocation_map,
            )

            allocation_paths = {
                "pv": technology_configs["pv"].pv_allocation_path
                if "pv" in technology_configs
                else None,
                "ev": technology_configs["ev"].ev_allocation_path
                if "ev" in technology_configs
                else None,
                "hp": technology_configs["hp"].hp_allocation_path
                if "hp" in technology_configs
                else None,
            }
            plot_files = plot_combined_allocation_map(
                config,
                {
                    technology: path
                    for technology, path in allocation_paths.items()
                    if path is not None
                },
            )
            output_files.update(plot_files)

        return CombinedStatusQuoIntegrationResult(
            enabled_technologies=tuple(enabled),
            pv_count=int(results["pv"].pv_count) if "pv" in results else 0,
            ev_count=int(results["ev"].ev_count) if "ev" in results else 0,
            hp_count=int(results["hp"].hp_count) if "hp" in results else 0,
            n_time_steps=n_time_steps,
            reference_year=reference_year,
            time_step_minutes=time_step_minutes,
            output_net_path=config.output_net_path,
            output_files=output_files,
            validation=validation,
        )
    finally:
        if config.cleanup_intermediate_files:
            for stage_path in stage_paths:
                try:
                    stage_path.unlink(missing_ok=True)
                except OSError:
                    pass