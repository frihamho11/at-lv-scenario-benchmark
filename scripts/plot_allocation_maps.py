#!/usr/bin/env python
r"""Create consistent allocation maps for all thesis benchmark scenarios.

The script visualises the already generated allocation results without
re-running allocation or integration.

Generated maps
--------------
Base:
    - Base grid

For every requested scenario (default: status_quo, high_penetration):
    - PV only
    - EV only
    - HP only
    - BESS only
    - Combined PV + EV + HP
    - Combined PV + EV + HP + BESS

The visual style follows the existing project visualisation modules:
    - grey grid-building footprints
    - light/dark network lines
    - black transformer squares
    - dashed AOI boundary
    - optional OpenStreetMap basemap
    - technology-specific colours/markers
    - PNG and SVG output

BESS allocation is stored as an ordinary tabular file without geometry.
Therefore all technology locations are consistently reconstructed from
building_id and the Seiler grid-building geometries.

Usage
-----
From the repository root:

    python .\scripts\plot_allocation_maps.py

Only status quo:

    python .\scripts\plot_allocation_maps.py --scenarios status_quo

Without online basemap:

    python .\scripts\plot_allocation_maps.py --no-basemap

Different realisation:

    python .\scripts\plot_allocation_maps.py --realisation 1
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd


# -----------------------------------------------------------------------------
# Project imports
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lv_scenario_benchmark.integration.combined_status_quo import (  # noqa: E402
    load_combined_status_quo_config,
)
from lv_scenario_benchmark.spatial import load_aoi, read_vector  # noqa: E402
from lv_scenario_benchmark.visualisation.pv_allocation import (  # noqa: E402
    _bus_coordinate_map,
    _clip_to_aoi,
    _network_lines,
    _set_aoi_extent,
    _transformer_points,
)


COMBINED_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "integration"
    / "status_quo_combined.yaml"
)


# -----------------------------------------------------------------------------
# Styles
# -----------------------------------------------------------------------------

# Single-technology footprint styles follow the existing allocation plots.
SINGLE_TECH_STYLE = {
    "pv": {
        "label": "PV",
        "facecolor": "darkorange",
        "edgecolor": "orangered",
    },
    "ev": {
        "label": "EV",
        "facecolor": "royalblue",
        "edgecolor": "navy",
    },
    "hp": {
        "label": "HP",
        "facecolor": "#009E73",
        "edgecolor": "#006B4F",
    },
    # No BESS map style exists in the current project context. Purple is used
    # here as a distinct fourth technology colour.
    "bess": {
        "label": "BESS",
        "facecolor": "mediumpurple",
        "edgecolor": "indigo",
    },
}

# Combined-map styles preserve the current PV/EV/HP marker convention and add
# one clearly distinguishable BESS marker.
COMBINED_TECH_STYLE = {
    "pv": {
        "label": "PV",
        "color": "darkorange",
        "edgecolor": "saddlebrown",
        "marker": "o",
    },
    "ev": {
        "label": "EV",
        "color": "royalblue",
        "edgecolor": "navy",
        "marker": "^",
    },
    "hp": {
        "label": "HP",
        "color": "forestgreen",
        "edgecolor": "darkgreen",
        "marker": "D",
    },
    "bess": {
        "label": "BESS",
        "color": "mediumpurple",
        "edgecolor": "indigo",
        "marker": "P",
    },
}

TECH_ORDER = ("pv", "ev", "hp", "bess")

ALLOCATION_FILENAMES = {
    "pv": "pv_status_quo_allocation.parquet",
    "ev": "ev_status_quo_allocation.parquet",
    "hp": "hp_status_quo_allocation.parquet",
    "bess": "bess_allocation.parquet",
}


# -----------------------------------------------------------------------------
# Data containers
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PlotContext:
    project_name: str
    aoi_id: str
    working_crs: str
    aoi: gpd.GeoDataFrame
    aoi_geometry: Any
    grid_buildings: gpd.GeoDataFrame
    building_id_column: str
    network_lines: gpd.GeoDataFrame
    transformers: gpd.GeoDataFrame
    project_output_root: Path
    figsize: tuple[float, float]
    dpi: int
    basemap: bool


@dataclass(frozen=True)
class TechnologySelection:
    technology: str
    allocation: pd.DataFrame
    selected_rows: pd.DataFrame
    selected_buildings: gpd.GeoDataFrame

    @property
    def unit_count(self) -> int:
        return int(len(self.selected_rows))

    @property
    def building_count(self) -> int:
        return int(self.selected_rows["building_id"].astype(str).nunique())


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _scenario_label(scenario_id: str) -> str:
    if scenario_id == "status_quo":
        return "Status quo"
    if scenario_id == "high_penetration":
        return "High penetration"
    return scenario_id.replace("_", " ").title()


def _read_table(path: Path) -> pd.DataFrame:
    """Read Parquet, falling back to CSV when required."""

    actual_path = path

    if not actual_path.exists():
        csv_path = path.with_suffix(".csv")
        if csv_path.exists():
            actual_path = csv_path
        else:
            raise FileNotFoundError(path)

    if actual_path.suffix.lower() == ".csv":
        return pd.read_csv(actual_path)

    if actual_path.suffix.lower() in {".parquet", ".pq"}:
        # Use pandas deliberately. Geometry is reconstructed from the canonical
        # grid-building file for every technology, including BESS.
        return pd.read_parquet(actual_path)

    raise ValueError(f"Unsupported allocation format: {actual_path}")


def _detect_building_id_column(grid_buildings: gpd.GeoDataFrame) -> str:
    """Find the Seiler building identifier column."""

    for candidate in ("id", "building_id"):
        if candidate in grid_buildings.columns:
            return candidate

    raise RuntimeError(
        "Could not find the grid-building identifier column. "
        "Expected 'id' or 'building_id'."
    )


def _load_selection(
    ctx: PlotContext,
    *,
    scenario_id: str,
    technology: str,
    realisation: int,
) -> TechnologySelection:
    """Load one scenario/technology allocation and attach building geometry."""

    allocation_path = (
        ctx.project_output_root
        / scenario_id
        / "allocation"
        / ALLOCATION_FILENAMES[technology]
    )

    allocation = _read_table(allocation_path)

    required = {"building_id", "realisation"}
    missing = sorted(required - set(allocation.columns))
    if missing:
        raise RuntimeError(
            f"{allocation_path} is missing required columns: {missing}"
        )

    selected = allocation.loc[
        pd.to_numeric(
            allocation["realisation"],
            errors="coerce",
        ).eq(realisation)
    ].copy()

    if "scenario_id" in selected.columns and not selected.empty:
        selected = selected.loc[
            selected["scenario_id"].astype(str).eq(scenario_id)
        ].copy()

    selected["building_id"] = selected["building_id"].astype(str)

    selected_ids = set(selected["building_id"])

    buildings = ctx.grid_buildings.copy()
    building_ids = buildings[ctx.building_id_column].astype(str)

    selected_buildings = buildings.loc[
        building_ids.isin(selected_ids)
    ].copy()

    selected_buildings["building_id"] = (
        selected_buildings[ctx.building_id_column].astype(str)
    )

    # One footprint is drawn per building even when EV allocation contains
    # several vehicles at the same building.
    selected_buildings = selected_buildings.drop_duplicates(
        "building_id"
    ).copy()

    matched_ids = set(selected_buildings["building_id"])
    missing_ids = sorted(selected_ids - matched_ids)

    if missing_ids:
        preview = missing_ids[:10]
        raise RuntimeError(
            f"{technology.upper()} allocation contains {len(missing_ids)} "
            "building_id values that are absent from the grid-building file. "
            f"Examples: {preview}"
        )

    return TechnologySelection(
        technology=technology,
        allocation=allocation,
        selected_rows=selected,
        selected_buildings=selected_buildings,
    )


def _add_basemap(ax: Any, ctx: PlotContext) -> None:
    if not ctx.basemap:
        return

    try:
        import contextily as cx

        cx.add_basemap(
            ax,
            crs=ctx.working_crs,
            source=cx.providers.OpenStreetMap.Mapnik,
            headers={
                "User-Agent": (
                    "at-lv-scenario-benchmark/1.0 "
                    "(academic research)"
                )
            },
            alpha=0.38,
            reset_extent=True,
            zorder=1,
        )
    except ImportError:
        print("Warning: contextily is not installed; basemap skipped.")
    except Exception as exc:
        print(f"Warning: basemap could not be added: {exc}")


def _draw_background(ax: Any, ctx: PlotContext) -> None:
    """Draw the common AOI/grid background used by every map."""

    ctx.grid_buildings.plot(
        ax=ax,
        facecolor="lightgray",
        edgecolor="gray",
        linewidth=0.25,
        alpha=0.75,
        zorder=2,
    )

    if not ctx.network_lines.empty:
        connection_mask = ctx.network_lines["line_type"].eq("LICONN")

        ctx.network_lines.loc[connection_mask].plot(
            ax=ax,
            color="silver",
            linewidth=0.45,
            alpha=0.8,
            zorder=3,
        )

        ctx.network_lines.loc[~connection_mask].plot(
            ax=ax,
            color="dimgray",
            linewidth=1.1,
            alpha=0.9,
            zorder=4,
        )

    if not ctx.transformers.empty:
        ctx.transformers.plot(
            ax=ax,
            marker="s",
            color="black",
            edgecolor="white",
            linewidth=0.7,
            markersize=42,
            zorder=7,
        )

    ctx.aoi.boundary.plot(
        ax=ax,
        color="black",
        linewidth=1.6,
        linestyle="--",
        zorder=8,
    )

    _set_aoi_extent(
        ax,
        ctx.aoi,
        padding_fraction=0.03,
    )

    _add_basemap(ax, ctx)


def _background_legend_handles() -> list[object]:
    return [
        Patch(
            facecolor="lightgray",
            edgecolor="gray",
            label="Grid building",
        ),
        Line2D(
            [0],
            [0],
            marker="s",
            color="none",
            markerfacecolor="black",
            markeredgecolor="white",
            markersize=7,
            label="Transformer",
        ),
        Line2D(
            [0],
            [0],
            color="black",
            linestyle="--",
            linewidth=1.5,
            label="Study-area boundary",
        ),
    ]


def _finalise_and_save(
    fig: Any,
    ax: Any,
    *,
    ctx: PlotContext,
    title: str,
    output_base: Path,
    legend_handles: list[object],
) -> dict[str, Path]:

    legend = ax.legend(
        handles=legend_handles,
        loc="upper right",
        frameon=True,
    )

    # Keep the legend above all map layers.
    legend.set_zorder(100)

    # Opaque legend background.
    legend.get_frame().set_facecolor("white")
    legend.get_frame().set_alpha(1.0)

    #ax.set_title(title)
    ax.set_aspect("equal")
    ax.set_axis_off()

    output_base.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    png_path = output_base.with_suffix(".png")
    svg_path = output_base.with_suffix(".svg")

    fig.savefig(
        png_path,
        dpi=ctx.dpi,
        bbox_inches="tight",
    )
    fig.savefig(
        svg_path,
        format="svg",
        dpi=ctx.dpi,
        bbox_inches="tight",
    )

    plt.close(fig)

    print(f"  PNG: {png_path}")
    print(f"  SVG: {svg_path}")

    return {
        "png": png_path,
        "svg": svg_path,
    }

def _selection_points(
    selection: TechnologySelection,
    *,
    working_crs: str,
) -> gpd.GeoDataFrame:
    """Convert selected building footprints to representative points."""

    buildings = selection.selected_buildings.copy()

    if buildings.empty:
        return gpd.GeoDataFrame(
            columns=["building_id", "geometry"],
            geometry="geometry",
            crs=working_crs,
        )

    buildings = buildings.to_crs(working_crs)

    buildings["geometry"] = (
        buildings.geometry.representative_point()
    )

    return gpd.GeoDataFrame(
        buildings[["building_id", "geometry"]],
        geometry="geometry",
        crs=working_crs,
    )


def _apply_overlap_offsets(
    points_by_technology: dict[str, gpd.GeoDataFrame],
    *,
    offset_distance: float,
) -> dict[str, gpd.GeoDataFrame]:
    """Separate markers when several technologies occupy the same building."""

    technology_by_building: dict[str, list[str]] = {}

    for technology, points in points_by_technology.items():
        if points.empty:
            continue

        for building_id in points["building_id"].astype(str):
            technology_by_building.setdefault(
                building_id,
                [],
            ).append(technology)

    result = {
        technology: points.copy()
        for technology, points in points_by_technology.items()
    }

    for technology, points in result.items():
        if points.empty:
            continue

        for row_index, row in points.iterrows():
            building_id = str(row["building_id"])

            present = [
                tech
                for tech in TECH_ORDER
                if tech in technology_by_building.get(
                    building_id,
                    [],
                )
            ]

            if len(present) <= 1:
                continue

            rank = present.index(technology)
            centred_rank = rank - (len(present) - 1) / 2.0

            geometry = row.geometry

            points.at[row_index, "geometry"] = type(geometry)(
                geometry.x + centred_rank * offset_distance,
                geometry.y,
            )

    return result


# -----------------------------------------------------------------------------
# Plot functions
# -----------------------------------------------------------------------------

def plot_base_grid(ctx: PlotContext) -> dict[str, Path]:
    print("\nBase grid")

    fig, ax = plt.subplots(figsize=ctx.figsize)
    _draw_background(ax, ctx)

    title = f"Base grid – {ctx.aoi_id}"

    output_base = (
        ctx.project_output_root
        / "base"
        / "figures"
        / "base_grid_map"
    )

    return _finalise_and_save(
        fig,
        ax,
        ctx=ctx,
        title=title,
        output_base=output_base,
        legend_handles=_background_legend_handles(),
    )


def plot_single_technology(
    ctx: PlotContext,
    *,
    scenario_id: str,
    technology: str,
    realisation: int,
) -> dict[str, Path]:
    selection = _load_selection(
        ctx,
        scenario_id=scenario_id,
        technology=technology,
        realisation=realisation,
    )

    style = SINGLE_TECH_STYLE[technology]
    scenario_label = _scenario_label(scenario_id)

    print(
        f"\n{scenario_label} – {style['label']} only: "
        f"{selection.unit_count} units at "
        f"{selection.building_count} buildings"
    )

    fig, ax = plt.subplots(figsize=ctx.figsize)
    _draw_background(ax, ctx)

    if not selection.selected_buildings.empty:
        selection.selected_buildings.plot(
            ax=ax,
            facecolor=style["facecolor"],
            edgecolor=style["edgecolor"],
            linewidth=0.55,
            alpha=0.95,
            zorder=6,
        )

    technology_handle = Patch(
        facecolor=style["facecolor"],
        edgecolor=style["edgecolor"],
        label=f"Building with allocated {style['label']}",
    )

    title = (
        f"{style['label']} allocation – {scenario_label} – {ctx.aoi_id}\n"
        f"realisation {realisation}, "
        f"{selection.unit_count} units at "
        f"{selection.building_count} buildings"
    )

    output_base = (
        ctx.project_output_root
        / scenario_id
        / "figures"
        / (
            f"{scenario_id}_{technology}_only_map_"
            f"r{realisation:03d}"
        )
    )

    return _finalise_and_save(
        fig,
        ax,
        ctx=ctx,
        title=title,
        output_base=output_base,
        legend_handles=[
            _background_legend_handles()[0],
            technology_handle,
            *_background_legend_handles()[1:],
        ],
    )


def plot_combined(
    ctx: PlotContext,
    *,
    scenario_id: str,
    technologies: tuple[str, ...],
    realisation: int,
    filename_suffix: str,
) -> dict[str, Path]:
    selections = {
        technology: _load_selection(
            ctx,
            scenario_id=scenario_id,
            technology=technology,
            realisation=realisation,
        )
        for technology in technologies
    }

    points_by_technology = {
        technology: _selection_points(
            selection,
            working_crs=ctx.working_crs,
        )
        for technology, selection in selections.items()
    }

    for technology, points in list(points_by_technology.items()):
        points_by_technology[technology] = _clip_to_aoi(
            points,
            ctx.aoi_geometry,
        )

    min_x, _, max_x, _ = ctx.aoi.total_bounds
    width = float(max_x - min_x)

    offset_distance = (
        width * 0.003
        if width > 0
        else 2.0
    )

    display_points = _apply_overlap_offsets(
        points_by_technology,
        offset_distance=offset_distance,
    )

    scenario_label = _scenario_label(scenario_id)

    print(
        f"\n{scenario_label} – "
        + " + ".join(
            COMBINED_TECH_STYLE[t]["label"]
            for t in technologies
        )
    )

    fig, ax = plt.subplots(figsize=ctx.figsize)
    _draw_background(ax, ctx)

    technology_handles: list[object] = []

    for technology in technologies:
        points = display_points[technology]
        style = COMBINED_TECH_STYLE[technology]

        if not points.empty:
            points.plot(
                ax=ax,
                marker=style["marker"],
                color=style["color"],
                edgecolor=style["edgecolor"],
                linewidth=0.7,
                markersize=48,
                alpha=0.95,
                zorder=6,
            )

        technology_handles.append(
            Line2D(
                [0],
                [0],
                marker=style["marker"],
                color="none",
                markerfacecolor=style["color"],
                markeredgecolor=style["edgecolor"],
                markersize=8,
                label=style["label"],
            )
        )

    title_parts = [
        (
            f"{COMBINED_TECH_STYLE[technology]['label']}: "
            f"{selections[technology].unit_count} units / "
            f"{selections[technology].building_count} buildings"
        )
        for technology in technologies
    ]

    if "bess" in technologies:
        heading = "Combined technology allocation + BESS"
    else:
        heading = "Combined technology allocation"

    title = (
        f"{heading} – {scenario_label} – {ctx.aoi_id}\n"
        f"realisation {realisation} | "
        + " | ".join(title_parts)
    )

    output_base = (
        ctx.project_output_root
        / scenario_id
        / "figures"
        / (
            f"{scenario_id}_{filename_suffix}_"
            f"r{realisation:03d}"
        )
    )

    return _finalise_and_save(
        fig,
        ax,
        ctx=ctx,
        title=title,
        output_base=output_base,
        legend_handles=[
            _background_legend_handles()[0],
            *technology_handles,
            *_background_legend_handles()[1:],
        ],
    )


# -----------------------------------------------------------------------------
# Context construction
# -----------------------------------------------------------------------------

def build_plot_context(
    *,
    basemap: bool,
    dpi: int | None,
    figsize: tuple[float, float] | None,
) -> PlotContext:
    if not COMBINED_CONFIG.exists():
        raise FileNotFoundError(COMBINED_CONFIG)

    config = load_combined_status_quo_config(
        COMBINED_CONFIG
    )

    if config.aoi_path is None:
        raise RuntimeError(
            "Combined configuration did not resolve an AOI path."
        )

    if config.grid_buildings_path is None:
        raise RuntimeError(
            "Combined configuration did not resolve a grid-buildings path."
        )

    if not config.base_net_path.exists():
        raise FileNotFoundError(config.base_net_path)

    aoi = load_aoi(
        config.aoi_path,
        aoi_id=config.aoi_id,
        working_crs=config.working_crs,
        crs_if_missing=config.aoi_crs_if_missing,
    )

    aoi_geometry = aoi.geometry.iloc[0]

    grid_buildings = read_vector(
        config.grid_buildings_path,
        crs_if_missing=config.building_crs_if_missing,
    ).to_crs(config.working_crs)

    grid_buildings = grid_buildings.loc[
        grid_buildings.geometry.notna()
        & ~grid_buildings.geometry.is_empty
        & grid_buildings.geometry.geom_type.isin(
            ["Polygon", "MultiPolygon"]
        )
    ].copy()

    grid_buildings = _clip_to_aoi(
        grid_buildings,
        aoi_geometry,
    )

    building_id_column = _detect_building_id_column(
        grid_buildings
    )

    try:
        import pandapower as pp
    except ImportError as exc:
        raise RuntimeError(
            "pandapower is required for allocation-map plotting."
        ) from exc

    net = pp.from_pickle(
        str(config.base_net_path)
    )

    bus_coordinates = _bus_coordinate_map(net)

    if not bus_coordinates:
        raise RuntimeError(
            "No usable bus geodata were found in the base network."
        )

    network_lines = _clip_to_aoi(
        _network_lines(
            net,
            bus_coordinates,
            config.working_crs,
        ),
        aoi_geometry,
    )

    transformers = _clip_to_aoi(
        _transformer_points(
            net,
            bus_coordinates,
            config.working_crs,
        ),
        aoi_geometry,
    )

    # In the scenario runner the project output directory is obtained from
    # combined_base.output_dir.parents[1]. Reuse exactly that convention.
    project_output_root = (
        config.output_dir.parents[1]
    ).resolve()

    return PlotContext(
        project_name=config.project_name,
        aoi_id=config.aoi_id,
        working_crs=config.working_crs,
        aoi=aoi,
        aoi_geometry=aoi_geometry,
        grid_buildings=grid_buildings,
        building_id_column=building_id_column,
        network_lines=network_lines,
        transformers=transformers,
        project_output_root=project_output_root,
        figsize=(
            figsize
            if figsize is not None
            else config.plot_figsize
        ),
        dpi=(
            int(dpi)
            if dpi is not None
            else int(config.plot_dpi)
        ),
        basemap=basemap,
    )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Visualise all generated technology allocations for the "
            "active Seiler PROJECT."
        )
    )

    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=[
            "status_quo",
            "high_penetration",
        ],
        help=(
            "Scenario directories to visualise. "
            "Default: status_quo high_penetration"
        ),
    )

    parser.add_argument(
        "--realisation",
        type=int,
        default=0,
        help="Realisation to visualise. Default: 0",
    )

    parser.add_argument(
        "--no-basemap",
        action="store_true",
        help="Do not add the OpenStreetMap basemap.",
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help=(
            "Override output DPI. Default: use plotting.dpi from "
            "status_quo_combined.yaml."
        ),
    )

    parser.add_argument(
        "--figsize",
        nargs=2,
        type=float,
        metavar=("WIDTH", "HEIGHT"),
        default=None,
        help=(
            "Override figure size in inches, e.g. --figsize 12 12."
        ),
    )

    parser.add_argument(
        "--skip-base",
        action="store_true",
        help="Skip the base-grid map.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.realisation < 0:
        raise ValueError("--realisation must be non-negative.")

    if args.dpi is not None and args.dpi < 72:
        raise ValueError("--dpi must be at least 72.")

    figsize = (
        tuple(float(value) for value in args.figsize)
        if args.figsize is not None
        else None
    )

    ctx = build_plot_context(
        basemap=not args.no_basemap,
        dpi=args.dpi,
        figsize=figsize,
    )

    print("============================================================")
    print("Allocation visualisation")
    print("============================================================")
    print(f"PROJECT:      {ctx.project_name}")
    print(f"AOI:          {ctx.aoi_id}")
    print(f"Output root:  {ctx.project_output_root}")
    print(f"Realisation:  {args.realisation}")
    print(f"Basemap:      {ctx.basemap}")
    print(f"DPI:          {ctx.dpi}")

    if not args.skip_base:
        plot_base_grid(ctx)

    for scenario_id in args.scenarios:
        scenario_root = (
            ctx.project_output_root
            / scenario_id
        )

        if not scenario_root.exists():
            print(
                f"\nWARNING: scenario directory does not exist; "
                f"skipping {scenario_id}: {scenario_root}"
            )
            continue

        print()
        print("============================================================")
        print(f"Scenario: {_scenario_label(scenario_id)}")
        print("============================================================")

        for technology in TECH_ORDER:
            allocation_path = (
                scenario_root
                / "allocation"
                / ALLOCATION_FILENAMES[technology]
            )

            csv_fallback = allocation_path.with_suffix(".csv")

            if not allocation_path.exists() and not csv_fallback.exists():
                print(
                    f"\nWARNING: {technology.upper()} allocation missing; "
                    f"skipping map: {allocation_path}"
                )
                continue

            plot_single_technology(
                ctx,
                scenario_id=scenario_id,
                technology=technology,
                realisation=args.realisation,
            )

        required_combined = [
            scenario_root / "allocation" / ALLOCATION_FILENAMES["pv"],
            scenario_root / "allocation" / ALLOCATION_FILENAMES["ev"],
            scenario_root / "allocation" / ALLOCATION_FILENAMES["hp"],
        ]

        if all(path.exists() or path.with_suffix(".csv").exists() for path in required_combined):
            plot_combined(
                ctx,
                scenario_id=scenario_id,
                technologies=("pv", "ev", "hp"),
                realisation=args.realisation,
                filename_suffix="combined_map",
            )
        else:
            print(
                "\nWARNING: PV/EV/HP allocation incomplete; "
                "combined map skipped."
            )

        required_combined_bess = [
            scenario_root / "allocation" / ALLOCATION_FILENAMES["pv"],
            scenario_root / "allocation" / ALLOCATION_FILENAMES["ev"],
            scenario_root / "allocation" / ALLOCATION_FILENAMES["hp"],
            scenario_root / "allocation" / ALLOCATION_FILENAMES["bess"],
        ]

        if all(path.exists() or path.with_suffix(".csv").exists() for path in required_combined_bess):
            plot_combined(
                ctx,
                scenario_id=scenario_id,
                technologies=("pv", "ev", "hp", "bess"),
                realisation=args.realisation,
                filename_suffix="combined_bess_map",
            )
        else:
            print(
                "\nWARNING: at least one PV/EV/HP/BESS allocation is "
                "missing; combined+BESS map skipped."
            )

    print()
    print("============================================================")
    print("Visualisation completed.")
    print("============================================================")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
