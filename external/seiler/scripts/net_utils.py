# =============================================================================
# Project:  lv-syn-grid
# Author:   Roman S.
# Created:  2025
#
# Description:
# utils for lv grid generation for simulation purposes
#
# License: MIT License
#
# =============================================================================

import pandapower.control as control
import pandapower.topology as top
import pandapower.networks as nw
import pandapower.timeseries as timeseries
from pandapower.timeseries.data_sources.frame_data import DFData
from pandapower.auxiliary import pandapowerNet
import networkx as nx
import pandapower as pp
import json
import numpy as np
import geopandas as gp
import pandas as pd
from scripts import parameters as prm

def get_nodes_by_type(G: nx.Graph, type: str) -> list:
    """
    Returns all nodes with a specific type.

    Parameters:
    -----------
    G : networkx.Graph
        Graph containing node attributes.
    type : str
        Node type to be filtered (e.g. "RESDTL", "TRFORM").

    Returns:
    --------
    list
        List of node identifiers matching the specified type.
    """
    nodes = []

    for node, attr in G.nodes(data=True):
        if attr.get('attributes').get('node_type') == type:
            nodes.append(node)

    return nodes


def get_node_by_transformer(df, t_id: int) -> int:
    """
    Returns the node by given transformer id.

    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame.
    t_id : int
        Transformer identifier.

    Returns:
    --------
    int
        Node id, or None if not found.
    """
    row = df[df['transformers'].apply(lambda x: t_id in x)]
    if not row.empty:
        return row.iloc[0]['node']
    else:
        return None


def get_node_by_building(df, b_id: int) -> int:
    """
    Returns the node by given building id.

    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame.
    b_id : int
        Building identifier.

    Returns:
    --------
    int
        Node id, or None if not found.
    """
    row = df[df['buildings'].apply(lambda x: b_id in x)]
    if not row.empty:
        return row.iloc[0]['node']
    else:
        return None
    

def get_bus_by_name(net: pandapowerNet, name: str):
    """
    Returns the bus index corresponding to a given bus name.

    Parameters:
    -----------
    net : pandapowerNet
        pandapower network containing bus data.
    name : str
        Name of the bus.

    Returns:
    --------
    int
        Index of the bus with the given name, or None if not found.
    """
    b = net.bus[net.bus.name == name]
    if not b.empty:
        return b.index[0]
    else:
        return None
    

def get_bus_geodata(net: pandapowerNet, idx: int):
    """
    Returns the geographical coordinates of a bus.

    Parameters:
    -----------
    net : pandapowerNet
        pandapower network containing bus geodata.
    idx : int
        Bus index.

    Returns:
    --------
    tuple
        Tuple (x, y) of the bus coordinates.
    """
    geo = json.loads(net.bus.at[idx, "geo"])
    x, y = geo["coordinates"]

    return x, y


def get_bus_by_node_id(net, node_id: str):
    """
    Returns the bus index corresponding to a given node identifier.

    Parameters:
    -----------
    net : pandapowerNet
        pandapower network containing bus data.
    node_id : str
        Node identifier associated with the bus.

    Returns:
    --------
    int
        Index of the bus corresponding to the given node identifier,
        or None if not found.
    """
    b = net.bus[net.bus.node_id == node_id]
    if not b.empty:
        return b.index[0]
    else:
        return None
    

def get_bus_indices_by_node_type(net, node_types):
    """
    Returns bus indices by node type.

    Parameters:
    -----------
    net : pandapowerNet
        pandapower network containing bus data.
    node_types : iterable
        Iterable of node types to be considered.

    Returns:
    --------
    dict
        Dictionary mapping each node type to a list of corresponding bus indices.
    """
    result = {}
    for node_type in node_types:
        indices = net.bus[net.bus['node_type'] == node_type].index.tolist()
        result[node_type] = indices
    return result


def get_line_indices_by_type(net, line_types):
    """
    Returns line indices by line type.

    Parameters:
    -----------
    net : pandapowerNet
        pandapower network containing line data.
    line_types : iterable
        Iterable of line types to be considered.

    Returns:
    --------
    dict
        Dictionary mapping each line type to a list of corresponding line indices.
    """
    result = {}
    for line_type in line_types:
        indices = net.line[net.line['name'] == line_type].index.tolist()
        result[line_type] = indices
    return result


def create_trafo(sn_mva: float) -> dict:
    """
    Create a dictionary of transformer parameters for a 20/0.4 kV
    medium-voltage to low-voltage distribution transformer.

    Parameters
    ----------
    sn_mva : float
        Rated apparent power of the transformer in MVA.

    Returns
    -------
    dict
        Dictionary containing transformer parameters compatible with
        pandapower.create_transformer_from_parameters().
    """
    parameters = {  
                    "sn_mva": sn_mva,
                    "vn_hv_kv": 20.0,
                    "vn_lv_kv": 0.4,
                    "vk_percent": 6.0,
                    "vkr_percent": 0.5,
                    "pfe_kw": 1.2,            
                    "i0_percent": 0.15,
                    "shift_degree": 0.0,
                    "tap_side": "hv",
                    "tap_neutral": 0,
                    "tap_min": -5,
                    "tap_max": 5,
                    "tap_step_percent": 1.5,
                    "tap_step_degree": 0.0
    }

    return parameters


def create_lv_busses(G: nx.MultiGraph, net: pandapowerNet, b_gdf: gp.GeoDataFrame) -> pandapowerNet:
    """
    Create low-voltage buses and associated elements in a pandapower network
    based on a graph representation of a low-voltage grid.

    Parameters
    ----------
    G : nx.MultiGraph
        Graph representing the low-voltage network topology.
    net : pandapowerNet
        Existing pandapower network to which LV buses, transformers, and loads
        are added.
    b_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing building data, including peak load values
        ('p_peak') indexed by building ID.

    Returns
    -------
    pandapowerNet
        Updated pandapower network including newly created LV buses,
        transformers, and loads.
    """
    for node, data in G.nodes(data=True):
        attr = data['attributes']   # get the attributes of each node
        pos = attr['pos']   # get the position of each node
        node_type = attr['node_type']
        id = attr['id']
    
        x = pos[0]
        y = pos[1]

        hv_bus = net.bus.query("name == 'HV_BUS'").index[0]

        if node_type == prm.NODE_TYPE_COMMON: # create a bus for a node with type common
            bus = pp.create_bus(net, vn_kv=0.4, name=f'COMMON_{id}', geodata=(x, y))
        
        if node_type == prm.NODE_TYPE_POWCON: # create a bus for a node with type powcon
            bus = pp.create_bus(net, vn_kv=0.4, name=f'POWCON_{id}', geodata=(x, y))
        
        if node_type == prm.NODE_TYPE_TRFORM: # create a bus for a transformer
            p_kva = int(attr['su'])

            if id.startswith('ND'):
                id = id[2:]

            if p_kva == 160:
                bus = pp.create_bus(net, vn_kv=0.4, name=f'TRFORM_{id}', geodata=(x, y))
                trform = pp.create_transformer(net, hv_bus=hv_bus, lv_bus=bus, std_type="0.16 MVA 20/0.4 kV", name="Trafo")
            if p_kva == 250:
                bus = pp.create_bus(net, vn_kv=0.4, name=f'TRFORM_{id}', geodata=(x, y))
                trform = pp.create_transformer(net, hv_bus=hv_bus, lv_bus=bus, std_type="0.25 MVA 20/0.4 kV", name="Trafo")
            if p_kva == 400:
                bus = pp.create_bus(net, vn_kv=0.4, name=f'TRFORM_{id}', geodata=(x, y))
                trform = pp.create_transformer(net, hv_bus=hv_bus, lv_bus=bus, std_type="0.4 MVA 20/0.4 kV", name="Trafo")
            if p_kva == 630:
                bus = pp.create_bus(net, vn_kv=0.4, name=f'TRFORM_{id}', geodata=(x, y))
                trform = pp.create_transformer(net, hv_bus=hv_bus, lv_bus=bus, std_type="0.63 MVA 20/0.4 kV", name="Trafo")
            if p_kva == 800:
                bus = pp.create_bus(net, vn_kv=0.4, name=f'TRFORM_{id}', geodata=(x, y))
                trform = pp.create_transformer(net, hv_bus=hv_bus, lv_bus=bus, std_type="0.8 MVA 20/0.4 kV", name="Trafo")
            if p_kva == 1000:
                bus = pp.create_bus(net, vn_kv=0.4, name=f'TRFORM_{id}', geodata=(x, y))
                trform = pp.create_transformer(net, hv_bus=hv_bus, lv_bus=bus, std_type="1.0 MVA 20/0.4 kV", name="Trafo")
            
        if node_type in {prm.NODE_TYPE_HOUSE, prm.NODE_TYPE_MULTI, prm.NODE_TYPE_AMENTY}: # create a bus for a residential building
            bus = pp.create_bus(net, vn_kv=0.4, name=f'BUILDING_{id}', geodata=(x, y))
            rsdtl = pp.create_load( net,
                                    p_mw             = b_gdf[b_gdf['id'] == id]['p_peak'].values[0]/1e3,
                                    name             = f'{id}',
                                    building_type    = node_type,
                                    bus=bus)
            
    for col in ["node_type", "node_id"]:
        if col not in net.bus.columns:
            net.bus[col] = np.nan   # or None

    parts = net.bus["name"].str.extract(r'^(?P<node_type>[A-Z]+)_?(?P<node_id>.*)$')
    net.bus[["node_type","node_id"]] = parts
            
    return net


def create_lv_lines(G: nx.MultiGraph, net: pandapowerNet) -> pandapowerNet:
    """
    Create low-voltage lines in a pandapower network based on the edges
    of a graph representation of a low-voltage grid.

    Parameters
    ----------
    G : nx.MultiGraph
        Graph representing the low-voltage network topology.
    net : pandapowerNet
        Existing pandapower network to which low-voltage lines are added.

    Returns
    -------
    pandapowerNet
        Updated pandapower network including newly created low-voltage
        line elements.
    """

    if "line" not in net.std_types or "NAYY 4x240 SE" not in net.std_types["line"]:
        net = create_lines(net)
    
    for u, v, data in G.edges(data=True):
        bus_0 = get_bus_by_node_id(net, u)
        bus_1 = get_bus_by_node_id(net, v)

        #if bus_0 and bus_1 is not None:
        line = pp.create_line(  net,
                                from_bus=bus_0,
                                to_bus=bus_1,
                                length_km=data['length']/1e3,
                                std_type="NAYY 4x150 SE",
                                name=data['attributes']['type'],
                                geodata=(get_bus_geodata(net, bus_0), get_bus_geodata(net, bus_1))    )
        
    return net


def create_transformers(net: pandapowerNet) -> pandapowerNet:
    """
    Create and register standard transformer types in a pandapower network.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network in which transformer standard types are created
        and stored.

    Returns
    -------
    pandapowerNet
        Updated pandapower network containing the required transformer
        standard types.
    """
    need = {
        '0.16 MVA 20/0.4 kV': create_trafo(sn_mva=0.16),
        '0.63 MVA 20/0.4 kV': create_trafo(sn_mva=0.63),
        '0.8 MVA 20/0.4 kV' : create_trafo(sn_mva=0.8),
        '1.0 MVA 20/0.4 kV' : create_trafo(sn_mva=1.0),
    }
    net.std_types.setdefault('trafo', {})
    for name, data in need.items():
        if name not in net.std_types['trafo']:
            pp.create_std_type(net, data, name=name, element='trafo')

    return net


def create_lines(net: pandapowerNet) -> pandapowerNet:
    """
    Create and register standard low-voltage cable types in a pandapower network.

    Parameters
    ----------
    net : pandapowerNet
        Pandapower network in which line standard types are created and stored.

    Returns
    -------
    pandapowerNet
        Updated pandapower network containing the required line standard types.
    """
    need = {
        'NAYY 4x95 SE':  {"r_ohm_per_km": 0.320, "x_ohm_per_km": 0.08,  "c_nf_per_km": 220, "max_i_ka": 0.200, "type": "cs"},
        'NAYY 4x240 SE': {"r_ohm_per_km": 0.125, "x_ohm_per_km": 0.08,  "c_nf_per_km": 240, "max_i_ka": 0.33,  "type": "cs"}
    }

    net.std_types.setdefault('line', {})

    for name, data in need.items():
        if name not in net.std_types['line']:
            pp.create_std_type(net, data, name=name, element='line')

    return net


def create_power_grid(net: pandapowerNet, Gs: [nx.MultiGraph], b_gdf: gp.GeoDataFrame) -> pandapowerNet:
    """
    Create a complete pandapower representation of a low-voltage power grid.

    Parameters
    ----------
    net : pandapowerNet
        Empty or partially initialized pandapower network that will be
        populated with buses, lines, transformers, loads, and an external grid.
    Gs : list of nx.MultiGraph
        List of graph objects representing individual low-voltage subnetworks.
    b_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing building data and peak load information used
        to create load elements at building nodes.

    Returns
    -------
    pandapowerNet
        Fully constructed pandapower network representing the combined
        medium-voltage and low-voltage grid.
    """
    # create the hv bus
    hv_bus = pp.create_bus(net, vn_kv=20., name="HV_BUS", index=0)

    if "HV_BUS" in net.bus.get("name", []):
        hv_bus = net.bus.index[net.bus["name"] == "HV_BUS"][0]
    else:
        hv_bus = pp.create_bus(net, vn_kv=20.0, name="HV_BUS")
        pp.create_ext_grid(net, hv_bus, vm_pu=1.02)

    # create the external grid
    pp.create_ext_grid(net, hv_bus, vm_pu = 1)

    # create custom transformers and lines
    net = create_transformers(net)
    net = create_lines(net)
    
    for G in Gs:
        net = create_lv_busses(G, net, b_gdf)
        net = create_lv_lines(G, net)

    coords = [
        json.loads(g)["coordinates"]
        for g in net.bus["geo"].dropna()
    ]

    # calculate mean for x, y coordinates
    xs, ys = zip(*coords)
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)

    # set geo for HV bus
    net.bus.loc[net.bus["name"] == "HV_BUS", "geo"] = json.dumps({"coordinates": [x_mean, y_mean]})

    return net


def create_load_profiles(file: str, t_start: str, t_end: str) -> tuple:
    """
    Load and preprocess standardized load profiles for a given time range.

    Parameters
    ----------
    file : str
        Name of the Excel file containing the load profiles.
    t_start : str
        Start timestamp of the desired time range (parsable by pandas).
    t_end : str
        End timestamp of the desired time range (parsable by pandas).

    Returns
    -------
    tuple
        A tuple containing:
        - pandas.DataFrame: Time-indexed load profiles for the specified period.
        - int: Number of time steps in the resulting time series.
    """
    lp_df = pd.read_excel(prm.FILEPATH_SLP + file) # load the load profiles into a dataframe

    lp_df['ts'] = pd.to_datetime(lp_df['ts'])   
    t_start = pd.Timestamp(t_start)
    t_end = pd.Timestamp(t_end)

    lp_ts_df = lp_df[(lp_df['ts'] >= t_start) & (lp_df['ts'] <= t_end)].set_index('ts')  # only keep the data within the given time span (ts) and set time step index

    columns_to_keep = ['H0', 'G0', 'G1', 'G2', 'G3', 'G6'] # only keep following load profiles
    columns_to_drop = [col for col in lp_ts_df.columns if col not in columns_to_keep]
    lp_ts_df.drop(columns=columns_to_drop, inplace=True)

    return lp_ts_df, len(lp_ts_df)
