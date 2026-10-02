"""Combined map for PV, EV and HP scenario allocations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd

from lv_scenario_benchmark.spatial import load_aoi, read_vector
from lv_scenario_benchmark.visualisation.pv_allocation import (
    _bus_coordinate_map,
    _clip_to_aoi,
    _network_lines,
    _set_aoi_extent,
    _transformer_points,
)

if TYPE_CHECKING:
    from lv_scenario_benchmark.integration.combined_status_quo import (
        CombinedStatusQuoConfig,
    )


class CombinedAllocationPlottingError(RuntimeError):
    """Raised when the combined technology map cannot be created."""


_TECHNOLOGY_STYLE = {
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
}


def _read_allocation(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()

    if suffix in {".parquet", ".pq"}:
        frame = gpd.read_parquet(path)
    elif suffix in {".gpkg", ".geojson", ".json", ".shp"}:
        frame = gpd.read_file(path)
    else:
        raise CombinedAllocationPlottingError(
            "Combined allocation plotting requires a geospatial allocation "
            f"file; unsupported suffix {path.suffix!r} for {path}."
        )

    if not isinstance(frame, gpd.GeoDataFrame):
        raise CombinedAllocationPlottingError(
            f"Allocation file is not geospatial: {path}"
        )

    if frame.crs is None:
        raise CombinedAllocationPlottingError(
            f"Allocation file has no CRS metadata: {path}"
        )

    required = {
        "building_id",
        "realisation",
    }

    missing = required - set(frame.columns)

    if missing:
        raise CombinedAllocationPlottingError(
            f"Allocation file {path} misses columns {sorted(missing)}."
        )

    if frame.geometry.isna().all():
        raise CombinedAllocationPlottingError(
            f"Allocation file contains no usable geometries: {path}"
        )

    return frame


def _selected_building_points(
    allocation: gpd.GeoDataFrame,
    *,
    realisation: int,
    working_crs: str,
) -> gpd.GeoDataFrame:
    selected = allocation.loc[
        pd.to_numeric(
            allocation["realisation"],
            errors="coerce",
        ).eq(realisation)
    ].copy()

    if selected.empty:
        return gpd.GeoDataFrame(
            columns=[
                "building_id",
                "geometry",
            ],
            geometry="geometry",
            crs=working_crs,
        )

    selected = selected.to_crs(working_crs)

    selected = selected.loc[
        selected.geometry.notna()
        & ~selected.geometry.is_empty
    ].copy()

    selected = selected.drop_duplicates(
        "building_id"
    ).copy()

    selected["building_id"] = (
        selected["building_id"].astype(str)
    )

    # representative_point() remains inside polygons and is therefore more
    # robust for concave building footprints than centroid().
    selected["geometry"] = (
        selected.geometry.representative_point()
    )

    return gpd.GeoDataFrame(
        selected,
        geometry="geometry",
        crs=working_crs,
    )


def _apply_overlap_offsets(
    points_by_technology: dict[str, gpd.GeoDataFrame],
    *,
    offset_distance: float,
) -> dict[str, gpd.GeoDataFrame]:
    """
    Separate markers only where the same building hosts several technologies.
    """

    technology_by_building: dict[str, list[str]] = {}

    for technology, points in points_by_technology.items():
        for building_id in points["building_id"].astype(str):
            technology_by_building.setdefault(
                building_id,
                [],
            ).append(technology)

    result: dict[str, gpd.GeoDataFrame] = {
        technology: points.copy()
        for technology, points in points_by_technology.items()
    }

    for technology, points in result.items():
        if points.empty:
            continue

        for row_index, row in points.iterrows():
            building_id = str(
                row["building_id"]
            )

            present = [
                name
                for name in (
                    "pv",
                    "ev",
                    "hp",
                )
                if name
                in technology_by_building.get(
                    building_id,
                    [],
                )
            ]

            if len(present) <= 1:
                continue

            rank = present.index(
                technology
            )

            centered_rank = (
                rank
                - (len(present) - 1) / 2.0
            )

            geometry = row.geometry

            points.at[
                row_index,
                "geometry",
            ] = type(geometry)(
                geometry.x
                + centered_rank
                * offset_distance,
                geometry.y,
            )

    return result


def plot_combined_allocation_map(
    config: "CombinedStatusQuoConfig",
    allocation_paths: dict[str, Path],
) -> dict[str, Path]:
    """
    Create one AOI map showing all enabled scenario technologies.
    """

    if not config.plot_enabled:
        return {}

    if (
        config.aoi_path is None
        or config.grid_buildings_path is None
    ):
        raise CombinedAllocationPlottingError(
            "AOI and grid-building paths are required for combined plotting."
        )

    if not allocation_paths:
        raise CombinedAllocationPlottingError(
            "No allocation paths were supplied for combined plotting."
        )

    unsupported = (
        set(allocation_paths)
        - set(_TECHNOLOGY_STYLE)
    )

    if unsupported:
        raise CombinedAllocationPlottingError(
            "Unsupported technologies for plotting: "
            f"{sorted(unsupported)}."
        )

    try:
        import pandapower as pp
    except ImportError as exc:
        raise CombinedAllocationPlottingError(
            "pandapower is required for the combined map."
        ) from exc

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
    ).to_crs(
        config.working_crs
    )

    grid_buildings = grid_buildings.loc[
        grid_buildings.geometry.notna()
        & ~grid_buildings.geometry.is_empty
        & grid_buildings.geometry.geom_type.isin(
            [
                "Polygon",
                "MultiPolygon",
            ]
        )
    ].copy()

    grid_buildings = _clip_to_aoi(
        grid_buildings,
        aoi_geometry,
    )

    net = pp.from_pickle(
        str(config.base_net_path)
    )

    bus_coordinates = _bus_coordinate_map(
        net
    )

    if not bus_coordinates:
        raise CombinedAllocationPlottingError(
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

    allocations: dict[
        str,
        gpd.GeoDataFrame,
    ] = {
        technology: _read_allocation(
            Path(path)
        )
        for technology, path
        in allocation_paths.items()
    }

    points_by_technology = {
        technology: _selected_building_points(
            allocation,
            realisation=config.realisation,
            working_crs=config.working_crs,
        )
        for technology, allocation
        in allocations.items()
    }

    for technology, points in list(
        points_by_technology.items()
    ):
        points_by_technology[
            technology
        ] = _clip_to_aoi(
            points,
            aoi_geometry,
        )

    min_x, _, max_x, _ = (
        aoi.total_bounds
    )

    width = float(
        max_x - min_x
    )

    offset_distance = (
        width * 0.003
        if width > 0
        else 2.0
    )

    display_points = (
        _apply_overlap_offsets(
            points_by_technology,
            offset_distance=offset_distance,
        )
    )

    fig, ax = plt.subplots(
        figsize=config.plot_figsize
    )

    grid_buildings.plot(
        ax=ax,
        facecolor="lightgray",
        edgecolor="gray",
        linewidth=0.25,
        alpha=0.70,
        zorder=2,
    )

    if not network_lines.empty:
        connection_mask = (
            network_lines[
                "line_type"
            ].eq("LICONN")
        )

        network_lines.loc[
            connection_mask
        ].plot(
            ax=ax,
            color="silver",
            linewidth=0.45,
            alpha=0.8,
            zorder=3,
        )

        network_lines.loc[
            ~connection_mask
        ].plot(
            ax=ax,
            color="dimgray",
            linewidth=1.1,
            alpha=0.9,
            zorder=4,
        )

    for technology in (
        "pv",
        "ev",
        "hp",
    ):
        if technology not in display_points:
            continue

        points = display_points[
            technology
        ]

        if points.empty:
            continue

        style = _TECHNOLOGY_STYLE[
            technology
        ]

        points.plot(
            ax=ax,
            marker=style["marker"],
            color=style["color"],
            edgecolor=style[
                "edgecolor"
            ],
            linewidth=0.7,
            markersize=48,
            alpha=0.95,
            zorder=6,
        )

    if not transformers.empty:
        transformers.plot(
            ax=ax,
            marker="s",
            color="black",
            edgecolor="white",
            linewidth=0.7,
            markersize=42,
            zorder=7,
        )

    aoi.boundary.plot(
        ax=ax,
        color="black",
        linewidth=1.6,
        linestyle="--",
        zorder=8,
    )

    _set_aoi_extent(
        ax,
        aoi,
        padding_fraction=0.03,
    )

    if config.plot_basemap:
        try:
            import contextily as ctx

            ctx.add_basemap(
                ax,
                crs=config.working_crs,
                source=(
                    ctx.providers
                    .OpenStreetMap
                    .Mapnik
                ),
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
            pass

        except Exception as exc:
            print(
                "Warning: basemap could not "
                f"be added: {exc}"
            )

    legend_handles: list[object] = [
        Patch(
            facecolor="lightgray",
            edgecolor="gray",
            label="Grid building",
        ),
    ]

    for technology in (
        "pv",
        "ev",
        "hp",
    ):
        if technology not in display_points:
            continue

        style = _TECHNOLOGY_STYLE[
            technology
        ]

        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker=style[
                    "marker"
                ],
                color="none",
                markerfacecolor=style[
                    "color"
                ],
                markeredgecolor=style[
                    "edgecolor"
                ],
                markersize=8,
                label=style[
                    "label"
                ],
            )
        )

    legend_handles.extend(
        [
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
    )

    ax.legend(
        handles=legend_handles,
        loc="upper right",
        frameon=True,
    )

    title_parts: list[str] = []

    for technology in (
        "pv",
        "ev",
        "hp",
    ):
        if technology not in allocations:
            continue

        allocation = allocations[
            technology
        ]

        selected = allocation.loc[
            pd.to_numeric(
                allocation[
                    "realisation"
                ],
                errors="coerce",
            ).eq(
                config.realisation
            )
        ]

        unit_count = int(
            len(selected)
        )

        building_count = int(
            selected[
                "building_id"
            ]
            .astype(str)
            .nunique()
        )

        title_parts.append(
            f"{_TECHNOLOGY_STYLE[technology]['label']}: "
            f"{unit_count} units / "
            f"{building_count} buildings"
        )

    scenario_ids = {
        str(value)
        for allocation in allocations.values()
        if "scenario_id" in allocation.columns
        for value in allocation[
            "scenario_id"
        ].dropna().unique()
    }

    if len(scenario_ids) != 1:
        raise CombinedAllocationPlottingError(
            "Combined allocation files must contain "
            "exactly one common scenario_id. "
            f"Found: {sorted(scenario_ids)}"
        )

    scenario_id = next(
        iter(scenario_ids)
    )

    scenario_label = (
        scenario_id
        .replace("_", " ")
        .title()
    )

    ax.set_title(
        f"Combined technology allocation – "
        f"{scenario_label} – "
        f"{config.aoi_id}\n"
        f"realisation "
        f"{config.realisation} | "
        + " | ".join(
            title_parts
        )
    )

    ax.set_aspect(
        "equal"
    )

    ax.set_axis_off()

    config.figure_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    png_path = (
        config.figure_dir
        / (
            f"{scenario_id}_"
            f"combined_map_"
            f"r{config.realisation:03d}"
            f".png"
        )
    )

    svg_path = (
        config.figure_dir
        / (
            f"{scenario_id}_"
            f"combined_map_"
            f"r{config.realisation:03d}"
            f".svg"
        )
    )

    fig.savefig(
        png_path,
        dpi=config.plot_dpi,
        bbox_inches="tight",
    )

    fig.savefig(
        svg_path,
        format="svg",
        dpi=config.plot_dpi,
        bbox_inches="tight",
    )

    plt.close(fig)

    return {
        "combined_map_png": png_path,
        "combined_map_svg": svg_path,
    }