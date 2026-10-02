"""Resolve the active lv-syn-grid project from ``scripts/parameters.py``.

The selected area is controlled by ``PROJECT`` in the existing Seiler
parameter file. No study-area name or project-specific grid path is duplicated
in the PV allocation configuration.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
from types import ModuleType


class ProjectContextError(RuntimeError):
    """Raised when the active Seiler project cannot be resolved."""


@dataclass(frozen=True)
class SeilerProjectContext:
    """Resolved paths and parameters for the active lv-syn-grid project."""

    project_name: str
    lv_syn_grid_root: Path
    parameters_path: Path
    data_dir: Path
    lvgrid_dir: Path
    plots_dir: Path
    aoi_path: Path
    grid_buildings_path: Path
    pandapower_net_path: Path
    working_crs: str
    minimum_footprint_area_m2: float


@contextmanager
def _temporary_working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _load_parameters_module(parameters_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lv_syn_grid_parameters_for_project_context",
        parameters_path,
    )
    if spec is None or spec.loader is None:
        raise ProjectContextError(
            f"Could not import Seiler parameters from {parameters_path}."
        )

    module = importlib.util.module_from_spec(spec)
    lv_syn_grid_root = parameters_path.parent.parent

    # parameters.py creates project folders through relative paths. Import it
    # from the submodule root so these paths are resolved exactly as in the
    # existing notebook workflow.
    with _temporary_working_directory(lv_syn_grid_root):
        spec.loader.exec_module(module)

    return module


def _required_text(module: ModuleType, name: str) -> str:
    if not hasattr(module, name):
        raise ProjectContextError(
            f"Seiler parameter file is missing required value {name!r}."
        )
    value = str(getattr(module, name)).strip()
    if not value:
        raise ProjectContextError(
            f"Seiler parameter value {name!r} must not be empty."
        )
    return value


def _resolve_submodule_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _resolve_net_path(
    lvgrid_dir: Path,
    configured_filename: str | None,
) -> Path:
    if configured_filename:
        return (lvgrid_dir / configured_filename).resolve()

    preferred = lvgrid_dir / "net.p"
    if preferred.exists():
        return preferred.resolve()

    candidates = sorted(lvgrid_dir.glob("*.p")) if lvgrid_dir.exists() else []
    if len(candidates) == 1:
        return candidates[0].resolve()
    if not candidates:
        # Return the conventional location. The allocation runner gives a
        # clear FileNotFoundError after GeoGridModel has not yet produced it.
        return preferred.resolve()

    raise ProjectContextError(
        "More than one pandapower pickle exists in "
        f"{lvgrid_dir}. Set project.pandapower_net_filename in the YAML. "
        f"Candidates: {[path.name for path in candidates]}"
    )


def load_seiler_project_context(
    parameters_path: str | Path,
    *,
    pandapower_net_filename: str | None = None,
) -> SeilerProjectContext:
    """Read ``PROJECT`` and derive all project-specific input/output paths."""

    parameters_path = Path(parameters_path).resolve()
    if not parameters_path.exists():
        raise FileNotFoundError(parameters_path)

    module = _load_parameters_module(parameters_path)
    lv_syn_grid_root = parameters_path.parent.parent.resolve()

    project_name = _required_text(module, "PROJECT")
    data_dir = _resolve_submodule_path(
        lv_syn_grid_root,
        _required_text(module, "FILEPATH_DATA"),
    )
    lvgrid_dir = _resolve_submodule_path(
        lv_syn_grid_root,
        _required_text(module, "FILEPATH_LV_GRID"),
    )
    plots_dir = _resolve_submodule_path(
        lv_syn_grid_root,
        _required_text(module, "FILEPATH_PLOTS"),
    )

    aoi_root_value = getattr(module, "FILEPATH_AOI", None)

    if aoi_root_value:
        aoi_dir = _resolve_submodule_path(
            parameters_path,
            str(aoi_root_value),
        )
    else:
        # Backward compatibility with the original Seiler directory layout,
        # where the AOI CSV was stored together with the grid input data.
        aoi_dir = data_dir

    polygon_filename = _required_text(module, "FILENAME_POLYGON_CSV")
    building_filename = (
        str(getattr(module, "FILE_BUILDINGS_PARQUET", "")).strip()
        or str(getattr(module, "FILENAME_BUILDINGS_PARQUET", "")).strip()
    )
    if not building_filename:
        raise ProjectContextError(
            "Seiler parameter file contains neither FILE_BUILDINGS_PARQUET "
            "nor FILENAME_BUILDINGS_PARQUET."
        )

    working_crs = str(getattr(module, "CRS_XY", "EPSG:9273"))
    minimum_area = float(getattr(module, "FOOTPRINT_AREA_THRESHHOLD", 60.0))

    return SeilerProjectContext(
        project_name=project_name,
        lv_syn_grid_root=lv_syn_grid_root,
        parameters_path=parameters_path,
        data_dir=data_dir,
        lvgrid_dir=lvgrid_dir,
        plots_dir=plots_dir,
        aoi_path=(aoi_dir / polygon_filename).resolve(),
        grid_buildings_path=(data_dir / building_filename).resolve(),
        pandapower_net_path=_resolve_net_path(
            lvgrid_dir,
            pandapower_net_filename,
        ),
        working_crs=working_crs,
        minimum_footprint_area_m2=minimum_area,
    )
