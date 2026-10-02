"""Run selected benchmark windows on simulation-ready pandapower networks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from lv_scenario_benchmark.project_context import (
    ProjectContextError,
    load_seiler_project_context,
)
from lv_scenario_benchmark.time_axis import (
    TimeAxisError,
    analysis_time_steps,
    build_reference_time_index,
)


class BenchmarkSimulationError(RuntimeError):
    """Raised when benchmark simulation configuration or execution is invalid."""


@dataclass(frozen=True)
class BenchmarkSimulationConfig:
    """Resolved configuration for one benchmark simulation run."""

    project_name: str
    benchmark_id: str
    scenario_id: str
    realisation: int
    parameters_path: Path
    net_path: Path
    output_dir: Path
    reference_year: int
    time_step_minutes: int
    analysis_start: pd.Timestamp
    analysis_end: pd.Timestamp
    output_file_type: str = ".csv"
    continue_on_divergence: bool = False

    def validate(self) -> None:
        if not self.project_name.strip():
            raise BenchmarkSimulationError("project_name must not be empty.")
        if not self.benchmark_id.strip():
            raise BenchmarkSimulationError("benchmark_id must not be empty.")
        if not self.scenario_id.strip():
            raise BenchmarkSimulationError("scenario_id must not be empty.")
        if self.realisation < 0:
            raise BenchmarkSimulationError("realisation must be non-negative.")
        if self.reference_year < 1900:
            raise BenchmarkSimulationError("reference_year must be >= 1900.")
        if self.time_step_minutes <= 0:
            raise BenchmarkSimulationError("time_step_minutes must be positive.")
        if self.analysis_start > self.analysis_end:
            raise BenchmarkSimulationError("analysis.start must be <= analysis.end.")
        if self.output_file_type not in {".csv", ".json", ".pickle", ".xlsx"}:
            raise BenchmarkSimulationError(
                "output_file_type must be one of .csv, .json, .pickle, .xlsx."
            )


@dataclass(frozen=True)
class BenchmarkSimulationResult:
    """Outputs of one benchmark time-series run."""

    n_time_steps: int
    first_time_step: int
    last_time_step: int
    analysis_start: pd.Timestamp
    analysis_end: pd.Timestamp
    output_dir: Path
    output_files: dict[str, Path]


def _resolve_path(base: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_benchmark_simulation_config(
    path: str | Path,
) -> BenchmarkSimulationConfig:
    """Load a benchmark-case YAML and resolve the active Seiler project."""

    try:
        import yaml
    except ImportError as exc:
        raise BenchmarkSimulationError(
            "PyYAML is required to read the benchmark configuration."
        ) from exc

    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BenchmarkSimulationError("The YAML root must be a mapping.")

    base = config_path.parent
    project = raw.get("project", {})
    network = raw.get("network", {})
    benchmark = raw.get("benchmark", {})
    case = raw.get("case", {})
    analysis = raw.get("analysis", {})
    outputs = raw.get("outputs", {})
    solver = raw.get("solver", {})

    parameters_path = _resolve_path(
        base,
        project.get(
            "parameters",
            "../../external/seiler/scripts/parameters.py",
        ),
    )
    if parameters_path is None:
        raise BenchmarkSimulationError("project.parameters is required.")

    net_filename = str(project.get("pandapower_net_filename", "net.p")).strip()
    if not net_filename or Path(net_filename).name != net_filename:
        raise BenchmarkSimulationError(
            "project.pandapower_net_filename must be a filename."
        )

    try:
        project_context = load_seiler_project_context(
            parameters_path,
            pandapower_net_filename=net_filename,
        )
    except (ProjectContextError, FileNotFoundError) as exc:
        raise BenchmarkSimulationError(str(exc)) from exc

    network_path = _resolve_path(
        base,
        network.get("path"),
    )
    scenario_network_filename_value = network.get("scenario_filename")
    scenario_network_filename = (
        str(scenario_network_filename_value).strip()
        if scenario_network_filename_value is not None
        else ""
    )
    if network_path is not None and scenario_network_filename:
        raise BenchmarkSimulationError(
            "network.path and network.scenario_filename are mutually exclusive."
        )
    if scenario_network_filename and (
        Path(scenario_network_filename).name != scenario_network_filename
    ):
        raise BenchmarkSimulationError(
            "network.scenario_filename must be a filename, not a path."
        )

    benchmark_id = str(benchmark.get("id", "benchmark_case")).strip()
    scenario_id = str(case.get("scenario_id", "base")).strip()
    realisation = int(case.get("realisation", 0))
    reference_year = int(benchmark.get("reference_year", 2025))
    time_step_minutes = int(benchmark.get("time_step_minutes", 15))

    if "start" not in analysis or "end" not in analysis:
        raise BenchmarkSimulationError(
            "analysis.start and analysis.end are required."
        )
    analysis_start = pd.Timestamp(analysis["start"])
    analysis_end = pd.Timestamp(analysis["end"])

    output_root = _resolve_path(
        base,
        outputs.get("root", "../../outputs"),
    )
    if output_root is None:
        raise BenchmarkSimulationError("outputs.root is required.")

    scenario_folder = (
        "base_grid"
        if scenario_id == "base"
        else scenario_id
    )

    if network_path is not None:
        # Explicit path relative to the benchmark YAML.
        net_path = network_path
    elif scenario_network_filename:
        # Scenario network below outputs/<PROJECT>/<scenario>/integration/.
        # This avoids duplicating the active Seiler PROJECT in every YAML.
        net_path = (
            output_root
            / project_context.project_name
            / scenario_folder
            / "integration"
            / scenario_network_filename
        ).resolve()
    else:
        # Default base-grid behaviour.
        net_path = project_context.pandapower_net_path

    output_dir = (
        output_root
        / project_context.project_name
        / scenario_folder
        / "powerflow"
        / "benchmark"
        / benchmark_id
        / f"{scenario_id}_r{realisation:03d}"
    ).resolve()

    config = BenchmarkSimulationConfig(
        project_name=project_context.project_name,
        benchmark_id=benchmark_id,
        scenario_id=scenario_id,
        realisation=realisation,
        parameters_path=parameters_path,
        net_path=net_path,
        output_dir=output_dir,
        reference_year=reference_year,
        time_step_minutes=time_step_minutes,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        output_file_type=str(outputs.get("file_type", ".csv")).strip(),
        continue_on_divergence=bool(solver.get("continue_on_divergence", False)),
    )
    config.validate()
    return config


def _clear_existing_output_writers(net: Any) -> None:
    """Output locations belong to the benchmark run, not to the stored net."""

    table = getattr(net, "output_writer", None)
    if isinstance(table, pd.DataFrame) and not table.empty:
        table.drop(table.index, inplace=True)


def _attach_output_writer(
    net: Any,
    config: BenchmarkSimulationConfig,
    time_steps: list[int],
) -> None:
    try:
        from pandapower.timeseries import OutputWriter
    except ImportError as exc:
        raise BenchmarkSimulationError(
            "pandapower OutputWriter is required for benchmark simulation."
        ) from exc

    writer = OutputWriter(
        net,
        time_steps=time_steps,
        output_path=str(config.output_dir),
        output_file_type=config.output_file_type,
    )
    writer.log_variable("res_bus", "vm_pu")
    writer.log_variable("res_line", "loading_percent")
    writer.log_variable("res_trafo", "loading_percent")
    writer.log_variable("res_trafo", "p_hv_mw")
    writer.log_variable("res_trafo", "q_hv_mvar")
    writer.log_variable("res_ext_grid", "p_mw")
    writer.log_variable("res_ext_grid", "q_mvar")
    if hasattr(net, "storage") and not net.storage.empty:
        writer.log_variable("res_storage", "p_mw")
        writer.log_variable("res_storage", "q_mvar")


def run_benchmark_simulation(
    config: BenchmarkSimulationConfig,
) -> BenchmarkSimulationResult:
    """Run only the configured inclusive date/time window."""

    config.validate()
    if not config.net_path.exists():
        raise FileNotFoundError(config.net_path)

    try:
        import pandapower as pp
        from pandapower import timeseries
    except ImportError as exc:
        raise BenchmarkSimulationError(
            "pandapower is required for benchmark simulation."
        ) from exc

    reference_index = build_reference_time_index(
        config.reference_year,
        config.time_step_minutes,
    )
    try:
        time_steps, selected_index = analysis_time_steps(
            reference_index,
            config.analysis_start,
            config.analysis_end,
        )
    except TimeAxisError as exc:
        raise BenchmarkSimulationError(str(exc)) from exc

    net = pp.from_pickle(str(config.net_path))
    config.output_dir.mkdir(parents=True, exist_ok=True)

    _clear_existing_output_writers(net)
    _attach_output_writer(net, config, time_steps)

    timeseries.run_timeseries(
        net,
        time_steps=time_steps,
        continue_on_divergence=config.continue_on_divergence,
    )

    time_index_csv = config.output_dir / "analysis_time_index.csv"
    pd.DataFrame(
        {
            "time_step": time_steps,
            "time": selected_index,
        }
    ).to_csv(time_index_csv, index=False)

    metadata_json = config.output_dir / "benchmark_run_metadata.json"
    metadata = asdict(config)
    metadata = {
        key: str(value) if isinstance(value, (Path, pd.Timestamp)) else value
        for key, value in metadata.items()
    }
    metadata.update(
        {
            "n_time_steps": len(time_steps),
            "first_time_step": time_steps[0],
            "last_time_step": time_steps[-1],
        }
    )
    metadata_json.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return BenchmarkSimulationResult(
        n_time_steps=len(time_steps),
        first_time_step=time_steps[0],
        last_time_step=time_steps[-1],
        analysis_start=selected_index[0],
        analysis_end=selected_index[-1],
        output_dir=config.output_dir,
        output_files={
            "time_index_csv": time_index_csv,
            "metadata_json": metadata_json,
        },
    )
