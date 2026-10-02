# =============================================================================
# Project:  lv-syn-grid
# Author:   Roman S.
# Created:  2025
#
# Description:
# utils for plotting the results
#
# License: MIT License
#
# =============================================================================

import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import contextily as ctx
import networkx as nx
from scripts import graph_utils as gu
import geopandas as gp
import random
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
from scripts import net_utils as nu
import pandapower.plotting as plot
from pandapower.auxiliary import pandapowerNet
import pandas as pd
import geopandas as gpd
import numpy as np

FIGSIZE_SMALL = [6, 6]
FIGSIZE_MEDIUM = [12, 12]
FIGSIZE_LARGE = [20, 20]

ALPHA_POLYGON_AREA = 0.05

# use Times New Roman as text font
plt.rcParams.update({
    "text.usetex": True,
    "font.family": "serif",
    "font.serif": ["Times New Roman"]
})


def set_margins_units(ax, *, left=0, right=0, bottom=0, top=0):
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    new_xmin = x_min + left
    new_xmax = x_max - right
    new_ymin = y_min + bottom
    new_ymax = y_max - top

    if new_xmin < new_xmax and new_ymin < new_ymax:
        ax.set_xlim(new_xmin, new_xmax)
        ax.set_ylim(new_ymin, new_ymax)

def set_margins_pct(ax, *, left=0.0, right=0.0, bottom=0.0, top=0.0):
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    x_rng = x_max - x_min
    y_rng = y_max - y_min
    new_xmin = x_min + left  * x_rng
    new_xmax = x_max - right * x_rng
    new_ymin = y_min + bottom * y_rng
    new_ymax = y_max - top    * y_rng
    if new_xmin < new_xmax and new_ymin < new_ymax:
        ax.set_xlim(new_xmin, new_xmax)
        ax.set_ylim(new_ymin, new_ymax)


# ***************************************************************************************************************************************************
# ******************************************************** Pandapower Results Plot Functions ********************************************************
# ***************************************************************************************************************************************************

def plot_grid_loading_osm(net: pandapowerNet, simres_line_loading_df: pd.DataFrame, simres_bus_voltage_df: pd.DataFrame, s_gdf: gp.GeoDataFrame) -> plt.figure:
    """
    Plot the low-voltage grid on an OpenStreetMap basemap, visualizing
    line loading and bus voltage extremes over a time series.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network containing buses, lines, and optional sgens (PV).
    simres_line_loading_df : pandas.DataFrame
        Time series results of line loadings in percent.
    simres_bus_voltage_df : pandas.DataFrame
        Time series results of bus voltages in p.u.
    s_gdf : geopandas.GeoDataFrame
        GeoDataFrame providing the coordinate reference system (CRS) used
        for plotting and for adding the OSM basemap.

    Returns
    -------
    matplotlib.figure.Figure
        Matplotlib figure object containing the generated plot.
    """
    fig, ax = plt.subplots(figsize=[12, 12])

    vmin = 0.9
    vmax = 1.10

    norm_vm = mcolors.Normalize(vmin=vmin, vmax=vmax)
    norm_ll = mcolors.Normalize(vmin=0.0, vmax=1.0)
        

    colors_vm = [
        (0.0, 'red'), # < 0.90
        ((0.90  - vmin) / (vmax - vmin), 'red'),
        ((0.93  - vmin) / (vmax - vmin), 'orange'),
        ((0.95  - vmin) / (vmax - vmin), 'yellow'),
        ((1.00  - vmin) / (vmax - vmin), 'green'),
        ((1.05  - vmin) / (vmax - vmin), 'yellow'),
        ((1.07  - vmin) / (vmax - vmin), 'orange'),
        ((1.10  - vmin) / (vmax - vmin), 'red'),
        (1.0, 'red') # > 1.10
    ]

    colors_ll = [
        (0.0, 'green'),           
        (norm_ll(0.5), 'lightgreen'),
        (norm_ll(0.7), 'yellow'),
        (norm_ll(0.85), 'orange'),
        (norm_ll(0.95), 'red'),
        (norm_ll(1.0), 'darkred')
    ]

    cmap_vm = mcolors.LinearSegmentedColormap.from_list('vm_map', colors_vm)
    cmap_ll = mcolors.LinearSegmentedColormap.from_list("custom", colors_ll)
        
    # get the indices for the bus collections
    trafo_indices = nu.get_bus_indices_by_node_type(net, ['TRFORM'])['TRFORM']
    powcon_indices = nu.get_bus_indices_by_node_type(net, ['POWCON'])['POWCON']
    building_indices = nu.get_bus_indices_by_node_type(net, ['BUILDING'])['BUILDING']

    # get the indices for the line collections
    building_connections = nu.get_line_indices_by_type(net, ['LICONN'])['LICONN']
    trafo_connections = nu.get_line_indices_by_type(net, ['TRCONN'])['TRCONN']
    main_lines = nu.get_line_indices_by_type(net, ['LIMAIN'])['LIMAIN']
    lv_lines = trafo_connections + main_lines

    # calculate color map for line loading
    line_loading_max = simres_line_loading_df[lv_lines].max(axis=0) / 100
    color_ll = [cmap_ll(norm_ll(l)) for l in line_loading_max]

    # calculate color map for bus voltage
    bus_voltage_min = simres_bus_voltage_df[powcon_indices].min(axis=0)
    bus_voltage_max = simres_bus_voltage_df[powcon_indices].max(axis=0)

    diff_min = np.abs(bus_voltage_min - 1.0)    # calculate difference between p.u. = 1 and the lowest bus voltage
    diff_max = np.abs(bus_voltage_max - 1.0)    # calculate difference between p.u. = 1 and the highgest bus voltage

    bus_voltage_min_max = np.where(diff_max > diff_min, bus_voltage_max, bus_voltage_min)
    color_vm = [cmap_vm(norm_vm(vm)) for vm in bus_voltage_min_max]

    # create the plot collections
    trafo_collection = plot.create_bus_collection(net, trafo_indices, size=7.5, color='black', zorder=10, patch_type='rect')
    building_collection = plot.create_bus_collection(net, building_indices, size=2.5, color='gray', zorder=10, patch_type='circle')    
    
    powcon_edge_collection = plot.create_bus_collection(net, powcon_indices, size=4, color='black', zorder=10)  # draw black edges around the colored powcon voltage circles
    powcon_collection = plot.create_bus_collection(net, powcon_indices, size=2, color=color_vm, zorder=20)
    
    lv_lines_collection = plot.create_line_collection(net, lv_lines, color=color_ll, linewidths=2, use_bus_geodata=False)
    building_lines_collection = plot.create_line_collection(net, building_connections, color='gray', linewidths=1, use_bus_geodata=False)

    pv_systems_collection = None
    if len(net.sgen) > 0:
        pv_systems_collection = plot.create_bus_collection(net, net.sgen['bus'], size=7, color='orange', zorder=20, patch_type='poly3')

    plot.draw_collections([lv_lines_collection, building_collection, trafo_collection, building_lines_collection, powcon_collection, powcon_edge_collection, pv_systems_collection], ax=ax, figsize=(18,12))
    ctx.add_basemap(
        ax,
        crs=s_gdf.crs.to_string(),
        source=ctx.providers.OpenStreetMap.Mapnik,
        headers={
            "User-Agent": "at-lv-scenario-benchmark/1.0 (academic research)"
        },
        timeout=30,
    )
    ax.set_aspect('equal')
    ax.images[-1].set_alpha(0.33)
    ax.set_axis_off()  

    # save the x and y margins for plot
    plot_x_min, plot_x_max = ax.get_xlim()
    plot_y_min, plot_y_max = ax.get_ylim()

    # get the original limits
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    return fig


# ***************************************************************************************************************************************************
# ************************************************************** Graph Plot Functions ***************************************************************
# ***************************************************************************************************************************************************
def random_color() -> str:
    """
    Generate a random hexadecimal color string.

    Returns
    -------
    str
        Random color in hexadecimal format (e.g. '#3fa9d1').
    """
    return '#{:06x}'.format(random.randint(0, 0xFFFFFF))


def random_dark_color() -> str:
    """
    Generate a random dark hexadecimal color string.

    The RGB values are limited to lower ranges to ensure darker colors,
    which are suitable for plotting on light backgrounds.

    Returns
    -------
    str
        Random dark color in hexadecimal format (e.g. '#4a6b2f').
    """
    r = random.randint(0, 200)
    g = random.randint(0, 175)
    b = random.randint(0, 150)
    
    return f"#{r:02x}{g:02x}{b:02x}"


def plot_G_lv(G: nx.MultiGraph, s_gdf: gp.GeoDataFrame, figsize=[9, 9], color='black') -> plt.figure:
    """
    Plot a low-voltage network graph on an OpenStreetMap basemap.

    Parameters
    ----------
    G : nx.MultiGraph
        Graph representing a low-voltage network, including node positions
        and edge geometry.
    s_gdf : geopandas.GeoDataFrame
        GeoDataFrame providing the coordinate reference system (CRS) for
        adding the OpenStreetMap basemap.
    figsize : list, optional
        Figure size in inches, by default [9, 9].
    color : str, optional
        Color used for nodes and edges, by default 'black'.

    Returns
    -------
    matplotlib.figure.Figure
        Matplotlib figure object containing the generated plot.
    """
    fig, ax = plt.subplots(
        figsize=figsize
    )
         
    attributes, pos, nodes_transformers, nodes_common, nodes_powcon, nodes_resdtl, nodes_amenty, nodes_house, nodes_aptmnt, line_edges = gu.get_graph_elements(G)
        
    color = color
    nodes_demand = nodes_resdtl + nodes_amenty + nodes_house + nodes_aptmnt

    # draw the powcon nodes
    nx.draw_networkx_nodes(
        G=G,
        pos=pos,
        nodelist=nodes_demand,
        node_color=color,
        node_size=4.5,
        ax=ax
    )

    # draw the network edges
    nx.draw_networkx_edges(
        G=G,
        pos=pos,
        edgelist=line_edges,
        width=1.25,
        edge_color=color,
        alpha=0.75
    )

    ctx.add_basemap(
        ax,
        crs=s_gdf.crs.to_string(),
        source=ctx.providers.OpenStreetMap.Mapnik,
        headers={
            "User-Agent": "at-lv-scenario-benchmark/1.0 (academic research)"
        },
        timeout=30,
    )
    ax.set_aspect('equal')
    ax.images[-1].set_alpha(0.75)
    ax.set_axis_off()

    # save the x and y margins for plot
    plot_x_min, plot_x_max = ax.get_xlim()
    plot_y_min, plot_y_max = ax.get_ylim()

    # Original-Limits holen
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    return fig


def plot_H_s_lv(Hs: list, s_gdf: gp.GeoDataFrame, figsize=[9, 9]) -> plt.figure:
    """
    Plot multiple low-voltage subnetworks on a common OpenStreetMap basemap.

    Parameters
    ----------
    Hs : list of nx.MultiGraph
        List of low-voltage subgraphs, each representing a transformer
        supply area.
    s_gdf : geopandas.GeoDataFrame
        GeoDataFrame providing the coordinate reference system (CRS) for
        adding the OpenStreetMap basemap.
    figsize : list, optional
        Figure size in inches, by default [9, 9].

    Returns
    -------
    matplotlib.figure.Figure
        Matplotlib figure object containing the generated plot.
    """
    fig, ax = plt.subplots(
        figsize=figsize
    )
    legend_elements = []

    # iterate over every graph
    for i, H in enumerate(Hs):            
        attributes, pos, nodes_transformers, nodes_common, nodes_powcon, nodes_resdtl, nodes_amenty, nodes_house, nodes_aptmnt, line_edges = gu.get_graph_elements(H)
        
        color = random_color()
        nodes_demand = nodes_resdtl + nodes_amenty + nodes_house + nodes_aptmnt

        # draw the powcon nodes
        nx.draw_networkx_nodes(
            G=H,
            pos=pos,
            nodelist=nodes_demand,
            node_color=color,
            node_size=4.5,
            ax=ax
        )

        # draw the network edges
        nx.draw_networkx_edges(
            G=H,
            pos=pos,
            edgelist=line_edges,
            width=1.25,
            edge_color=color,
            alpha=0.75
        )

        # draw all transformers
        nx.draw_networkx_nodes(
            G=H,
            pos=pos,
            nodelist=nodes_transformers,
            node_color='gray',
            edgecolors='black',
            linewidths=1.5,
            node_shape='s',
            node_size=30.0,
            ax = ax
        )

        legend_elements.append(
            mpatches.Patch(color=color, label=f"Trafo {i+1}: {attributes[nodes_transformers[0]]['su']}  kVA")
        )

    ctx.add_basemap(
        ax,
        crs=s_gdf.crs.to_string(),
        source=ctx.providers.OpenStreetMap.Mapnik,
        headers={
            "User-Agent": "at-lv-scenario-benchmark/1.0 (academic research)"
        },
        timeout=30,
    )
    ax.set_aspect('equal')
    ax.images[-1].set_alpha(0.75)
    ax.set_axis_off()

    # add the legend for many trafos (splitted legend)
    n = len(legend_elements)
    split = n // 2 + n % 2

    legend_left = legend_elements[:split]
    legend_right = legend_elements[split:]

    legend1 = ax.legend(
        handles = legend_left,
        loc='upper left',
        frameon=True,
        facecolor='white',
        framealpha=0.9,
        edgecolor='black',
        fontsize=10,
        labelspacing=0.3
    )
    ax.add_artist(legend1)

    ax.legend(
        handles = legend_right,
        loc='upper right',
        frameon=True,
        facecolor='white',
        framealpha=0.9,
        edgecolor='black',
        fontsize=10,
        labelspacing=0.3
    )

    # save the x and y margins for plot
    plot_x_min, plot_x_max = ax.get_xlim()
    plot_y_min, plot_y_max = ax.get_ylim()

    # get original limits
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    return fig


def plot_nx_graph(G_lv: nx.MultiDiGraph, G_mv: nx.MultiDiGraph, b_gdf: gp.GeoDataFrame, s_gdf: gp.GeoDataFrame, 
                  plot_config: dict, poly_outline=None, figsize=[6, 6], save_img=False, filename='default'):
    """
    Plot LV and MV NetworkX graphs together with building geometries on an
    OpenStreetMap basemap.

    Parameters
    ----------
    G_lv : nx.MultiDiGraph or None
        Low-voltage graph to be plotted. If None, LV elements are skipped.
    G_mv : nx.MultiDiGraph or None
        Medium-voltage graph to be plotted. If None, MV elements are skipped.
    b_gdf : geopandas.GeoDataFrame
        GeoDataFrame of building geometries. Footprints and centroids are plotted.
    s_gdf : geopandas.GeoDataFrame
        GeoDataFrame providing the CRS used for adding the OpenStreetMap basemap.
    plot_config : dict
        Plot configuration dictionary (e.g., styling options).
    poly_outline : optional
        Optional polygon outline to be drawn (e.g., study area boundary).
    figsize : list, optional
        Figure size in inches, by default [6, 6].
    save_img : bool, optional
        If True, the plot is saved as SVG and PNG using `filename`, by default False.
    filename : str, optional
        Base filename (without extension) used when saving images, by default 'default'.

    Returns
    -------
    None
        The function displays the plot via `plt.show()` and does not return a figure.
    """

    fig, ax = plt.subplots(
        figsize=figsize
    )

    # plot the buildings centroids
    b_gdf.plot(
        ax=ax,
        color='lightgray', 
        figsize=figsize,
        edgecolor='gray', 
        label='Buildings', 
        alpha=0.85)
    
    b_gdf.centroid.plot(
        color="black",
        markersize=3,
        ax=ax,
        label="Centroids"
    )

    if G_lv != None:
        attributes = nx.get_node_attributes(G_lv, 'attributes')
        pos = {k: v['pos'] for k, v in attributes.items()}

        nodes_transformers = gu.get_nodes_by_type(G_lv, 'TRFORM')
        nodes_common = gu.get_nodes_by_type(G_lv, 'COMMON')
        nodes_powcon = gu.get_nodes_by_type(G_lv, 'POWCON')
        line_edges = list(G_lv.edges(data=True))

        # plot the buildings centroids
        nx.draw_networkx_nodes(
            G=G_lv,
            pos=pos,
            nodelist=nodes_transformers,
            node_color='firebrick',
            node_shape='o',
            node_size=15,
            ax = ax
        )

        # draw the powcon nodes
        nx.draw_networkx_nodes(
            G=G_lv,
            pos=pos,
            nodelist=nodes_powcon,
            node_color='green',
            node_size=3.0,
            ax=ax
        )

        # draw the lines (edges of the graph)
        nx.draw_networkx_edges(
            G=G_lv,
            pos=pos,
            edgelist=line_edges,
            width=1.25,
            edge_color='gray'
        )

    if G_mv != None:
        attributes = nx.get_node_attributes(G_mv, 'attributes')
        pos = {k: v['pos'] for k, v in attributes.items()}
        line_edges = list(G_mv.edges(data=True))

        nx.draw_networkx_edges(
            G=G_mv,
            pos=pos,
            edgelist=line_edges,
            width=3.0,
            edge_color='blue',
            alpha=0.5
        )

    ctx.add_basemap(
        ax,
        crs=s_gdf.crs.to_string(),
        source=ctx.providers.OpenStreetMap.Mapnik,
        headers={
            "User-Agent": "at-lv-scenario-benchmark/1.0 (academic research)"
        },
        timeout=30,
    )
    ax.set_aspect('equal')
    ax.images[-1].set_alpha(0.75)
    ax.set_axis_off()

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # save the x and y margins for plot
    plot_x_min, plot_x_max = ax.get_xlim()
    plot_y_min, plot_y_max = ax.get_ylim()

    if save_img == True:
        plt.savefig(f'{filename}.svg', format='svg', dpi=600, bbox_inches='tight', transparent=True)
        plt.savefig(f'{filename}.png', format='png', dpi=600, bbox_inches='tight', transparent=True)

    plt.axis('off')
    plt.show()


# ***************************************************************************************************************************************************
# *********************************************************** Cluster Plot Functions ****************************************************************
# ***************************************************************************************************************************************************
def plot_clusters(model, scaler, data) -> None:
    """
    Plot k-means clustering results and transformer locations in 2D space.

    Parameters
    ----------
    model : sklearn.cluster.KMeans
        Trained k-means model containing cluster labels and cluster centers.
    scaler : sklearn.preprocessing object
        Fitted scaler used to normalize the input data.
    data : array-like
        Input data points used for clustering.

    Returns
    -------
    None
        The function displays the cluster plot using matplotlib.
    """
    labels = model.labels_
    centroids = scaler.inverse_transform(model.cluster_centers_)[:, :2]
    print(centroids)
    colors = ['red', 'blue', 'green', 'orange', 'purple', 'cyan', 'brown', 'olive', 'pink', 'gray']

    # plot the building in clusters
    for i in range(model.n_clusters):
        cluster_points = data[labels == i]
        plt.scatter(cluster_points[:, 0], cluster_points[:, 1], color=colors[i % len(colors)], label=f'Cluster {i+1}', alpha=0.7)

    # transformers, cluster centers
    plt.scatter(centroids[:, 0], centroids[:, 1], color='black', marker='X', s=150, label='Transformator (Clusterzentrum)')

    plt.xlabel('X-Koordinate')
    plt.ylabel('Y-Koordinate')
    plt.title('k-Means Cluster der Hausanschlüsse')
    plt.legend()
    plt.grid(True)
    plt.axis('equal')
    plt.tight_layout()
    plt.show()


def plot_cluster_with_osm(model, data, tr_gdf, s_gdf, tr_apriori_gdf=None) -> None:
    """
    Plot k-means clustering results and transformer locations on an
    OpenStreetMap basemap.

    Parameters
    ----------
    model : sklearn.cluster.KMeans or None
        Trained k-means model used for clustering.
    data : array-like
        Input data points used for clustering.
    tr_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing transformer locations and rated power.
    s_gdf : geopandas.GeoDataFrame
        GeoDataFrame providing the CRS used for adding the OpenStreetMap
        basemap.
    tr_apriori_gdf : geopandas.GeoDataFrame, optional
        Optional GeoDataFrame containing a-priori transformer locations
        for comparison.

    Returns
    -------
    None
        The function saves the plot as PNG and SVG and displays it using
        matplotlib.
    """
    ax = None

    if model == None:
        print('only 1 Trafo should be plotted')
    else:
        print('more than 1 Trafo should be plotted')

    ax = s_gdf.plot(
        figsize=[12, 12],
        color='black',
        linewidth=0.0
    )

    labels = model.labels_
    colors = ['green', 'blue', 'red', 'orange', 'purple', 'cyan', 'brown', 'olive', 'pink', 'gray']

    # plot the clusters
    for i in range(model.n_clusters):
        cluster_points = data[labels == i]
        ax.scatter(cluster_points[:, 0], cluster_points[:, 1], color=colors[i % len(colors)], label=f'Cluster {i+1}', alpha=0.5, s=10)

    # plot the transformers
    ax.scatter(
        tr_gdf.geometry.x,
        tr_gdf.geometry.y,
        s=tr_gdf['power'] * 0.2,
        c='purple',
        marker='X'
    )

    for idx, row in tr_gdf.iterrows():
        circle = Circle(
        (row.geometry.x, row.geometry.y),
        radius=100,             # e.g. 100 m
        linewidth=1.5,
        edgecolor='purple',
        facecolor='none',
        linestyle='--'
    )
    ax.add_patch(circle)

    # power labels for transformers
    for idx, row in tr_gdf.iterrows():
        ax.text(
            row.geometry.x + 15,
            row.geometry.y + 15,
            f"{row['power']} kVA",
            fontsize=14,
            ha='left',
            va='bottom',
            color='black'
        )

    # add the basemap of Open Street Map
    ctx.add_basemap(
        ax,
        crs=s_gdf.crs.to_string(),
        source=ctx.providers.OpenStreetMap.Mapnik,
        headers={
            "User-Agent": "at-lv-scenario-benchmark/1.0 (academic research)"
        },
        timeout=30,
    )
    ax.set_aspect('equal')
    ax.images[-1].set_alpha(0.33)
    ax.set_axis_off()

    # save the x and y margins for plot
    plot_x_min, plot_x_max = ax.get_xlim()
    plot_y_min, plot_y_max = ax.get_ylim()

    plt.savefig('trafo_placement.png', format='png', dpi=600, bbox_inches='tight', transparent=True)
    plt.savefig('trafo_placement.svg', format='svg', dpi=600, bbox_inches='tight', transparent=True)

    plt.axis('off')
    plt.show()
