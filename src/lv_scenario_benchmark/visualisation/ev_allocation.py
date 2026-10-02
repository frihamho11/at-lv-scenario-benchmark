"""Visualisation of polygon-based electric-vehicle allocations."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from lv_scenario_benchmark.allocation.ev_status_quo import EVStatusQuoConfig
from lv_scenario_benchmark.spatial import load_aoi, read_vector
from .pv_allocation import (
    _bus_coordinate_map,
    _clip_to_aoi,
    _network_lines,
    _set_aoi_extent,
    _transformer_points,
)


class EVPlottingError(RuntimeError):
    """Raised when an EV allocation map cannot be produced."""


def plot_ev_allocation_maps(
    allocation: gpd.GeoDataFrame,
    config: EVStatusQuoConfig,
) -> dict[str, Path]:
    """Create one study-area map for every stochastic EV realisation."""

    if not config.plot_enabled:
        return {}
    if allocation.empty:
        raise EVPlottingError("Cannot plot an empty EV allocation.")
    if "realisation" not in allocation.columns:
        raise EVPlottingError("The allocation table has no 'realisation' column.")

    try:
        import pandapower as pp
    except ImportError as exc:
        raise EVPlottingError("pandapower is required for the map output.") from exc

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
        & grid_buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ].copy()
    grid_buildings = _clip_to_aoi(grid_buildings, aoi_geometry)

    net = pp.from_pickle(str(config.pandapower_net_path))
    bus_coordinates = _bus_coordinate_map(net)
    if not bus_coordinates:
        raise EVPlottingError("No usable bus geodata were found in the network.")

    network_lines = _clip_to_aoi(
        _network_lines(net, bus_coordinates, config.working_crs),
        aoi_geometry,
    )
    transformers = _clip_to_aoi(
        _transformer_points(net, bus_coordinates, config.working_crs),
        aoi_geometry,
    )

    config.map_output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: dict[str, Path] = {}

    for realisation in sorted(allocation["realisation"].unique()):
        selected = allocation.loc[
            allocation["realisation"] == realisation
        ].copy()
        selected = selected.to_crs(config.working_crs)
        selected = _clip_to_aoi(selected, aoi_geometry)
        selected_buildings = selected.drop_duplicates("building_id")

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

        selected_buildings.plot(
            ax=ax,
            facecolor="royalblue",
            edgecolor="navy",
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
        _set_aoi_extent(ax, aoi, padding_fraction=0.03)

        if config.plot_basemap:
            try:
                import contextily as ctx

                ctx.add_basemap(
                    ax,
                    crs=config.working_crs,
                    source=ctx.providers.OpenStreetMap.Mapnik,
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
                print(f"Warning: basemap could not be added: {exc}")

        legend_handles = [
            Patch(facecolor="lightgray", edgecolor="gray", label="Grid building"),
            Patch(
                facecolor="royalblue",
                edgecolor="navy",
                label="Building with allocated EV",
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
            f"EV status-quo allocation – {config.aoi_id}\n"
            f"realisation {int(realisation)}, {len(selected)} EVs at "
            f"{len(selected_buildings)} buildings"
        )
        ax.set_aspect("equal")
        ax.set_axis_off()

        png_path = config.map_output_dir / f"ev_status_quo_map_r{int(realisation):03d}.png"
        svg_path = config.map_output_dir / f"ev_status_quo_map_r{int(realisation):03d}.svg"
        fig.savefig(png_path, dpi=config.plot_dpi, bbox_inches="tight")
        fig.savefig(svg_path, format="svg", dpi=config.plot_dpi, bbox_inches="tight")
        plt.close(fig)

        output_paths[f"map_png_r{int(realisation):03d}"] = png_path
        output_paths[f"map_svg_r{int(realisation):03d}"] = svg_path

    return output_paths
