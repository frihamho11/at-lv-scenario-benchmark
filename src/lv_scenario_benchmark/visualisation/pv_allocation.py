"""Visualisation of polygon-based photovoltaic allocations.

The module creates one map for each stochastic realisation. The map is
restricted to the configured study-area polygon. Buildings selected for a
photovoltaic system are highlighted by their building footprints rather than
by additional point markers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd
from shapely.geometry import LineString, Point

from lv_scenario_benchmark.allocation.pv_status_quo import PVStatusQuoConfig
from lv_scenario_benchmark.spatial import load_aoi, read_vector


class PlottingError(RuntimeError):
    """Raised when a photovoltaic allocation map cannot be produced."""


def _parse_bus_coordinates(value: Any) -> tuple[float, float] | None:
    """Convert a pandapower bus geodata value into an ``(x, y)`` tuple.

    Parameters
    ----------
    value:
        Bus geodata as JSON text, mapping, list, tuple, or missing value.

    Returns
    -------
    tuple[float, float] | None
        Parsed coordinates, or ``None`` when the value cannot be interpreted.
    """

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None

    if isinstance(value, dict):
        coordinates = value.get("coordinates")
        if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
            return float(coordinates[0]), float(coordinates[1])

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return float(value[0]), float(value[1])

    return None


def _bus_coordinate_map(net: Any) -> dict[int, tuple[float, float]]:
    """Build a mapping from pandapower bus indices to planar coordinates.

    Coordinates are read first from ``net.bus['geo']`` and then completed from
    ``net.bus_geodata`` where available.

    Parameters
    ----------
    net:
        Loaded pandapower network.

    Returns
    -------
    dict[int, tuple[float, float]]
        Mapping from integer bus index to ``(x, y)`` coordinates.
    """

    coordinates: dict[int, tuple[float, float]] = {}

    if "geo" in net.bus.columns:
        for bus_id, value in net.bus["geo"].items():
            parsed = _parse_bus_coordinates(value)
            if parsed is not None:
                coordinates[int(bus_id)] = parsed

    if hasattr(net, "bus_geodata") and not net.bus_geodata.empty:
        required = {"x", "y"}
        if required.issubset(net.bus_geodata.columns):
            for bus_id, row in net.bus_geodata.iterrows():
                coordinates.setdefault(
                    int(bus_id),
                    (float(row["x"]), float(row["y"])),
                )

    return coordinates


def _network_lines(
    net: Any,
    bus_coordinates: dict[int, tuple[float, float]],
    crs: str,
) -> gpd.GeoDataFrame:
    """Convert pandapower lines into a georeferenced line layer.

    Parameters
    ----------
    net:
        Loaded pandapower network.
    bus_coordinates:
        Mapping from bus indices to coordinates.
    crs:
        Coordinate reference system assigned to the output layer.

    Returns
    -------
    geopandas.GeoDataFrame
        Network line geometries with line index and line type.
    """

    rows: list[dict[str, Any]] = []

    for line_id, row in net.line.iterrows():
        from_bus = int(row["from_bus"])
        to_bus = int(row["to_bus"])

        if from_bus not in bus_coordinates or to_bus not in bus_coordinates:
            continue

        rows.append(
            {
                "line_id": int(line_id),
                "line_type": str(row.get("name", "")),
                "geometry": LineString(
                    [bus_coordinates[from_bus], bus_coordinates[to_bus]]
                ),
            }
        )

    if not rows:
        return gpd.GeoDataFrame(
            columns=["line_id", "line_type", "geometry"],
            geometry="geometry",
            crs=crs,
        )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def _transformer_points(
    net: Any,
    bus_coordinates: dict[int, tuple[float, float]],
    crs: str,
) -> gpd.GeoDataFrame:
    """Convert pandapower transformers into a georeferenced point layer.

    The transformer position is taken from its low-voltage bus.

    Parameters
    ----------
    net:
        Loaded pandapower network.
    bus_coordinates:
        Mapping from bus indices to coordinates.
    crs:
        Coordinate reference system assigned to the output layer.

    Returns
    -------
    geopandas.GeoDataFrame
        Transformer point geometries.
    """

    rows: list[dict[str, Any]] = []

    for trafo_id, row in net.trafo.iterrows():
        lv_bus = int(row["lv_bus"])
        coordinate = bus_coordinates.get(lv_bus)

        if coordinate is None:
            continue

        rows.append(
            {
                "trafo_id": int(trafo_id),
                "sn_mva": row.get("sn_mva", pd.NA),
                "geometry": Point(coordinate),
            }
        )

    if not rows:
        return gpd.GeoDataFrame(
            columns=["trafo_id", "sn_mva", "geometry"],
            geometry="geometry",
            crs=crs,
        )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def _clip_to_aoi(
    layer: gpd.GeoDataFrame,
    aoi_geometry: Any,
) -> gpd.GeoDataFrame:
    """Restrict a geospatial layer to the study-area geometry.

    Polygon and line geometries are intersected with the study area. Point
    geometries are retained when they lie inside or on the boundary.

    Parameters
    ----------
    layer:
        Layer to restrict.
    aoi_geometry:
        Study-area polygon or multipolygon.

    Returns
    -------
    geopandas.GeoDataFrame
        Restricted layer with empty geometries removed.
    """

    if layer.empty:
        return layer.copy()

    geometry_types = set(layer.geometry.geom_type.unique())
    point_only = geometry_types.issubset({"Point", "MultiPoint"})

    if point_only:
        result = layer[
            layer.geometry.within(aoi_geometry)
            | layer.geometry.touches(aoi_geometry)
        ].copy()
    else:
        result = layer[layer.geometry.intersects(aoi_geometry)].copy()
        result["geometry"] = result.geometry.intersection(aoi_geometry)

    result = result[
        result.geometry.notna()
        & ~result.geometry.is_empty
    ].copy()

    return gpd.GeoDataFrame(result, geometry="geometry", crs=layer.crs)


def _set_aoi_extent(
    ax: Any,
    aoi: gpd.GeoDataFrame,
    *,
    padding_fraction: float = 0.03,
) -> None:
    """Set the map extent to the study area with a small proportional margin.

    Parameters
    ----------
    ax:
        Matplotlib axis to update.
    aoi:
        Study-area GeoDataFrame.
    padding_fraction:
        Fraction of the AOI width and height added as map margin.
    """

    min_x, min_y, max_x, max_y = aoi.total_bounds
    width = max_x - min_x
    height = max_y - min_y

    x_padding = width * padding_fraction if width > 0 else 1.0
    y_padding = height * padding_fraction if height > 0 else 1.0

    ax.set_xlim(min_x - x_padding, max_x + x_padding)
    ax.set_ylim(min_y - y_padding, max_y + y_padding)


def plot_pv_allocation_maps(
    allocation: gpd.GeoDataFrame,
    config: PVStatusQuoConfig,
) -> dict[str, Path]:
    """Create one study-area map for every stochastic PV realisation.

    Only the configured study-area polygon is displayed. Municipality
    boundaries are deliberately omitted. All eligible grid buildings are shown
    in grey, while buildings selected for a PV system are highlighted by their
    complete footprints in orange. No additional triangle markers are drawn.

    Parameters
    ----------
    allocation:
        Allocated PV systems. The active geometry must contain the selected
        building footprint and the table must contain a ``realisation`` column.
    config:
        Validated PV status-quo configuration.

    Returns
    -------
    dict[str, pathlib.Path]
        Output paths of the generated PNG and SVG files.

    Raises
    ------
    PlottingError
        If required data are missing or the map cannot be generated.
    """

    if not config.plot_enabled:
        return {}

    try:
        import pandapower as pp
    except ImportError as exc:
        raise PlottingError(
            "pandapower is required for the map output."
        ) from exc

    if allocation.empty:
        raise PlottingError("Cannot plot an empty PV allocation.")

    if "realisation" not in allocation.columns:
        raise PlottingError(
            "The allocation table has no 'realisation' column."
        )

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
    grid_buildings = grid_buildings[
        grid_buildings.geometry.notna()
        & ~grid_buildings.geometry.is_empty
        & grid_buildings.geometry.geom_type.isin(
            ["Polygon", "MultiPolygon"]
        )
    ].copy()
    grid_buildings = _clip_to_aoi(grid_buildings, aoi_geometry)

    net = pp.from_pickle(str(config.pandapower_net_path))
    bus_coordinates = _bus_coordinate_map(net)

    if not bus_coordinates:
        raise PlottingError("No usable bus geodata were found in the network.")

    network_lines = _clip_to_aoi(
        _network_lines(net, bus_coordinates, config.working_crs),
        aoi_geometry,
    )
    transformers = _clip_to_aoi(
        _transformer_points(net, bus_coordinates, config.working_crs),
        aoi_geometry,
    )

    figure_dir = config.map_output_dir
    figure_dir.mkdir(parents=True, exist_ok=True)
    output_paths: dict[str, Path] = {}

    for realisation in sorted(allocation["realisation"].unique()):
        selected = allocation[
            allocation["realisation"] == realisation
        ].copy()
        selected = selected.to_crs(config.working_crs)
        selected = _clip_to_aoi(selected, aoi_geometry)

        fig, ax = plt.subplots(figsize=config.plot_figsize)

        grid_buildings.plot(
            ax=ax,
            facecolor="lightgray",
            edgecolor="gray",
            linewidth=0.25,
            alpha=0.75,
            zorder=2,
        )

        if not network_lines.empty:
            connection_mask = network_lines["line_type"].eq("LICONN")

            network_lines[connection_mask].plot(
                ax=ax,
                color="silver",
                linewidth=0.45,
                alpha=0.8,
                zorder=3,
            )
            network_lines[~connection_mask].plot(
                ax=ax,
                color="dimgray",
                linewidth=1.1,
                alpha=0.9,
                zorder=4,
            )

        # Highlight selected PV buildings by their footprint. No point or
        # triangle marker is added, which keeps dense allocations readable.
        selected.plot(
            ax=ax,
            facecolor="darkorange",
            edgecolor="orangered",
            linewidth=0.55,
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

        # Fix the visible extent explicitly to the AOI. This prevents larger
        # municipality geometries or other layers from changing the map scale.
        _set_aoi_extent(ax, aoi, padding_fraction=0.03)

        if config.plot_basemap:
            try:
                import contextily as ctx

                osm_headers = {
                    "User-Agent": (
                        "at-lv-scenario-benchmark/1.0 "
                        "(academic research)"
                    )
                }

                ctx.add_basemap(
                    ax,
                    crs=config.working_crs,
                    source=ctx.providers.OpenStreetMap.Mapnik,
                    headers=osm_headers,
                    alpha=0.38,
                    reset_extent=True,
                    zorder=1,
                )
            except ImportError:
                pass
            except Exception as exc:
                print(f"Warning: basemap could not be added: {exc}")

        legend_handles = [
            Patch(
                facecolor="lightgray",
                edgecolor="gray",
                label="Grid building",
            ),
            Patch(
                facecolor="darkorange",
                edgecolor="orangered",
                label="Building with allocated PV",
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
        ax.legend(handles=legend_handles, loc="upper right", frameon=True)

        ax.set_title(
            f"PV status-quo allocation – {config.aoi_id}\n"
            f"realisation {int(realisation)}, {len(selected)} PV systems"
        )
        ax.set_aspect("equal")
        ax.set_axis_off()

        png_path = (
            figure_dir / f"pv_status_quo_map_r{int(realisation):03d}.png"
        )
        svg_path = (
            figure_dir / f"pv_status_quo_map_r{int(realisation):03d}.svg"
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

        output_paths[f"map_png_r{int(realisation):03d}"] = png_path
        output_paths[f"map_svg_r{int(realisation):03d}"] = svg_path

    return output_paths