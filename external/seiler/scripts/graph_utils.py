# =============================================================================
# Project:  lv-syn-grid
# Author:   Roman S.
# Created:  2025
#
# Description:
# utils for graph generation
#
# License: MIT License
#
# =============================================================================

import geopandas as gp
import pandas as pd
from shapely import Point, MultiPoint
import networkx as nx
import numpy as np
import random
from scripts import parameters as prm

# ##TEST TODO
import copy


def get_node_type(gdf: gp.GeoDataFrame, node: int) -> str:
    """
    Returns the type of a node.
        
    Parameters:
    -----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing node information.
    node : int
        Node identifier.

    Returns:
    --------
    str
        Type of the node, or None if the node is not found.
    """
    row = gdf.loc[gdf['node'] == node]

    if not row.empty:
        return row.iloc[0]['node_type']
    else:
        return None
    

def get_building_type(gdf: gp.GeoDataFrame, b: str) -> str:
    """
    Returns the building type.

    Parameters:
    -----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing building information.
    b : str
        Building id

    Returns:
    --------
    str
        Building type, or None if the building is not found.
    """
    row = gdf.loc[gdf['id'] == b]

    if not row.empty:
        return row.iloc[0]['node_type']
    else:
        return None


def get_node_role(gdf: gp.GeoDataFrame, node: int) -> str:
    """
    Returns the role of a node.

    Parameters:
    -----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing node information.
    node : int
        Node id

    Returns:
    --------
    str
        Role of the node, or None if the node is not found.
    """
    row = gdf.loc[gdf['node'] == node]

    if not row.empty:
        return row.iloc[0]['node_role']
    else:
        return None


def get_demand_power(gdf: gp.GeoDataFrame, id: int) -> float:
    """
    Returns the peak demand power.

    Parameters:
    -----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing demand information.
    id : int
        Node id

    Returns:
    --------
    float
        Peak demand power, or None if the element is not found.
    """
    row = gdf.loc[gdf['id'] == id]

    if not row.empty:
        return row.iloc[0]['p_peak']
    else:
        return None
    

def get_supply_power(gdf: gp.GeoDataFrame, id: int) -> float:
    """
    Returns the supply power of the given node.

    Parameters:
    -----------
    gdf : geopandas.GeoDataFrame
        GeoDataFrame containing supply information.
    id : int
        Node id

    Returns:
    --------
    float
        Supply power, or None if the node is not found.
    """
    row = gdf.loc[gdf['id'] == id]

    if not row.empty:
        return row.iloc[0]['power']
    else:
        return None
    

def calc_dist(p1: Point, p2: Point):
    """
    Calculates the distance between two points.

    Parameters:
    -----------
    p1 : shapely.geometry.Point
        First point.
    p2 : shapely.geometry.Point
        Second point.

    Returns:
    --------
    float
        Distance between the two points.
    """
    length = p1.distance(p2)
    return length


def get_nodes_by_role(G: nx.Graph, role: str) -> list:
    """
    Returns all nodes with a specific role.

    Parameters:
    -----------
    G : networkx.Graph
        Graph containing node attributes.
    role : str
        Node role to be filtered (e.g. "SUPPLY", "DEMAND").

    Returns:
    --------
    list
        List of nodes matching the specified role.
    """
    nodes = []

    for node, attr in G.nodes(data=True):
        if attr.get('attributes').get('node_role') == role:
            nodes.append(node)

    return nodes


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
        List of nodes matching the specified type.
    """
    nodes = []

    for node, attr in G.nodes(data=True):
        if attr.get('attributes').get('node_type') == type:
            nodes.append(node)

    return nodes


def get_edges_by_type(G: nx.Graph, type: str) -> list:
    """
    Returns all edges with a specific type.

    Parameters:
    -----------
    G : networkx.Graph
        Graph containing edge attributes.
    type : str
        Edge type to be filtered (e.g. "MAIN_LINE", "CONN_LINE").

    Returns:
    --------
    list
        List of edges (u, v, data) matching the specified type.
    """
    edges = []

    for u, v, data in G.edges(data=True):
        if data.get('attributes').get('type') == type:
            edges.append((u, v, data))
    
    return edges


def get_pos_by_node_types(G: nx.Graph, type: list) -> list:
    """
    Returns positions of nodes matching the specified node types.

    Parameters:
    -----------
    G : networkx.Graph
        Graph containing node attributes.
    type : list
        List of node types to be considered (e.g. ["RESDTL", "TRFORM"]).

    Returns:
    --------
    list
        List of node positions corresponding to the specified types.
    """
    nodes = []
    pos = []

    for t in type:
        print(t)
        nodes.append(get_nodes_by_type(G, t))
    
    nodes = nodes[0]

    for node, attr in G.nodes(data=True):
        if node in nodes:
            pos.append(attr['attributes']['pos'])

    return pos


def get_pos_by_nodelist(G: nx.Graph, nodelist: [nx.MultiGraph]) -> list:
    """
    Returns positions of nodes specified in a node list.

    Parameters:
    -----------
    G : networkx.Graph
        Graph containing node attributes.
    nodelist : list
        List of node identifiers.

    Returns:
    --------
    list
        List of node positions corresponding to the given node list.
    """
    pos = []

    for node, attr in G.nodes(data=True):
        if node in nodelist:
            pos.append(attr['attributes']['pos'])

    return pos


def create_G_lv(    l_gdf: gp.GeoDataFrame, n_gdf: gp.GeoDataFrame,
                    b_gdf: gp.GeoDataFrame, t_gdf: gp.GeoDataFrame) -> nx.MultiGraph:
    """
    Creates the low-voltage network graph from geospatial input data.

    Parameters:
    -----------
    l_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing line (street/connection) geometries.
    n_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing network node information.
    b_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing building data.
    t_gdf : geopandas.GeoDataFrame
        GeoDataFrame containing transformer data.

    Returns:
    --------
    networkx.MultiGraph
        Low-voltage network graph constructed from the input data.
    """
    G = nx.Graph()

    # iterate over every line
    for idx, row in l_gdf.iterrows():
        # add the start node of the line
        G.add_node( str(row['start_node']),
                    attributes= {
                                    'id':               str(row['start_node']),
                                    'pos':              (row['start_pos'][0], row['start_pos'][1]),
                                    'node_type':        get_node_type(n_gdf, row['start_node']),
                                    'node_role':        prm.NODE_ROLE_DEMAND,
                                    'dv':               0,
                                    'merged_nodes':     []
                                })
    
        # add the end node of the line
        G.add_node( str(row['end_node']),
                    attributes= {
                                    'id':               str(row['end_node']),    
                                    'pos':              (row['end_pos'][0], row['end_pos'][1]),
                                    'node_type':        get_node_type(n_gdf, row['end_node']),
                                    'node_role':        prm.NODE_ROLE_DEMAND,
                                    'dv':               0,
                                    'merged_nodes':     []
                                })
    
        # add the edge between the start node and the end node of the line
        G.add_edge( str(row['start_node']),
                    str(row['end_node']),
                    attributes = {
                        'id':       'ML' + str(row['line_id']),
                        'type':     prm.LINE_MAIN,
                        'length':   str(calc_dist(   Point(row['start_pos'][0], row['start_pos'][1]),
                                                        Point(row['end_pos'][0], row['end_pos'][1]))),
                    },
                    length  =   str(calc_dist(   Point(row['start_pos'][0], row['start_pos'][1]),
                                                    Point(row['end_pos'][0], row['end_pos'][1]))),
        )


    # iterate over every node stored in the GeoDataFrame nodes and assign the buildings to the nodes in the graph according it
    for idx, row in n_gdf.iterrows():
        buildings = row['buildings']    # get the buildings assigned to the actual node
        transformers = row['transformers']  # get the transformers assigned to the actual node

        node = row['node']  # get the id of the actual node
        node_point = row['geometry']    # get the shapely point of a node
    
        # check if buildings are assigned to this node
        if len(buildings) > 0:
            # iterate over every assigned building
            for b in buildings:
                result = b_gdf[b_gdf['id'] == b]
            
                # get the centroid of each building as Shapely Point
                building_point = result['centroid']
                building_type = result['building_type'].iloc[0]

                pos = ( result['centroid'].x.iloc[0],
                        result['centroid'].y.iloc[0])
            
                G.add_node( str(b),
                            attributes={
                                            'id':               str(b),
                                            'pos':              pos,
                                            'node_type':        str(building_type),#str(get_building_type(buildings_gdf, b)),
                                            'node_role':        prm.NODE_ROLE_DEMAND,
                                            'dv':               get_demand_power(b_gdf, b),
                                            'merged_nodes': []
                            })
            
                # add the edge from the node point and the centroid of the building
                G.add_edge( str(node), 
                            str(b),
                            attributes={
                                'id':       'CL' + str(node),
                                'type':     prm.LINE_CONN,
                                'length':   calc_dist(node_point, building_point).iloc[0]
                            },
                            length = calc_dist(node_point, building_point).iloc[0]
                )

        # check if transformers are assigned to this node
        if len(transformers) > 0:
            # iterate over every assigned transformer
            for t in transformers:
                result = t_gdf[t_gdf['id'] == t]
                # get the point of each transformer as Shapely Point
                transformer_point = result['geometry']

                G.add_node( str(t),
                            attributes={
                                'id':           str(t),
                                'pos':          (result['geometry'].x.iloc[0], result['geometry'].y.iloc[0]),
                                'node_type':    prm.NODE_TYPE_TRFORM,
                                'node_role':    prm.NODE_ROLE_SUPPLY,
                                'su':           str(get_supply_power(t_gdf, t)),
                                'merged_nodes': []
                            })
            

                # add the edge from the node point and the centroid of the building
                G.add_edge( str(node), 
                            str(t),
                            attributes={
                                'id':       'TC' + str(node),
                                'type':     prm.LINE_TRFM,
                                'length':   calc_dist(transformer_point, node_point).iloc[0]
                            },
                            length = calc_dist(transformer_point, node_point).iloc[0]    )

    return G


def delete_isolated_nodes(G: nx.MultiDiGraph):
    """
    Removes isolated common nodes from the graph.

    Parameters:
    -----------
    G : networkx.MultiDiGraph
        Graph from which isolated nodes are removed.

    Returns:
    --------
    networkx.MultiDiGraph
        Graph with isolated nodes removed.
    """
    while(True):
        isolated_nodes = []

        for node, attr in G.nodes(data=True):
            if attr.get('attributes').get('node_type') == 'COMMON' and G.degree[node] == 1:
                isolated_nodes.append(node)
        
        if len(isolated_nodes) > 0:
            G.remove_nodes_from(isolated_nodes)

        if len(isolated_nodes) == 0:
            break
    
    return G


def apply_mst_algorithm(G: nx.MultiDiGraph):
    """
    Calculates the minimum spanning tree (MST) of the given graph.

    Parameters:
    -----------
    G : networkx.MultiDiGraph
        Input graph for which the minimum spanning tree is computed.

    Returns:
    --------
    networkx.Graph
        Minimum spanning tree of the input graph with isolated nodes removed.
    """
    for u, v, data in G.edges(data=True):
        data['length'] = float(data['length'])

    H = nx.minimum_spanning_tree(G, weight='length', algorithm='kruskal')
    H = delete_isolated_nodes(H)
    
    return H


def get_nodes_with_only_leaves(T: nx.Graph) -> list:
    """
    Returns nodes whose neighbors are all leaf nodes.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph.

    Returns:
    --------
    list
        List of nodes whose neighboring nodes are leaves.
    """
    nodes_with_only_leaves = []
    
    # iterate over every node in G
    for node in T.nodes:
        # save all neighbors of each node
        neighbors = list(T.neighbors(node))

        # iterate over every neighbor
        for neighbor in neighbors:
            # if the neighbor has no neighbors, it is a leaf -> so save the node
            if T.degree(neighbor) == 1:
                if node not in nodes_with_only_leaves:
                    nodes_with_only_leaves.append(node)

    return nodes_with_only_leaves


def get_children_demand_vertices(T: nx.Graph, u) -> list:
    """
    Returns all child nodes of a given node that are demand vertices.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph.
    u : hashable
        Node id

    Returns:
    --------
    list
        List of child nodes that are demand vertices.
    """
    # get all neighbors n of the node u
    neighbors = T.neighbors(u)
    D = []

    # iterate over every neighbors n_ of all neighbors n
    for neighbor in neighbors:
        # store only n_ if it is a demand and has degree 1
        if T.degree(neighbor) == 1 and T.nodes[neighbor]['attributes']['node_role'] == prm.NODE_ROLE_DEMAND:
            D.append(neighbor)
    
    return D


def get_n_vertices(T: nx.Graph) -> int:
    """
    Returns the number of vertices in the graph.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph.

    Returns:
    --------
    int
        Number of vertices in the graph.
    """
    return int(len(T.nodes))


def get_children_demand_vertices(T: nx.Graph, u) -> list:
    """
    Returns all child nodes of a given node that are demand vertices.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph.
    u : hashable
        Node id.

    Returns:
    --------
    list
        List of child nodes that are demand vertices.
    """
    # get all neighbors n of the node u
    neighbors = T.neighbors(u)
    D = []

    # iterate over every neighbors n_ of all neighbors n
    for neighbor in neighbors:
        # store only n_ if it is a demand and has degree 1
        if T.degree(neighbor) == 1 and T.nodes[neighbor]['attributes']['node_role'] == prm.NODE_ROLE_DEMAND:
            D.append(neighbor)
    
    return D


def get_vertex_type(T: nx.Graph, u) -> str:
    """
    Returns the type of a vertex.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph containing vertex attributes.
    u : hashable
        Vertex identifier.

    Returns:
    --------
    str
        Vertex type, either supply or demand.
    """
    if T.nodes[u]['attributes']['node_role'] == prm.NODE_ROLE_SUPPLY:
        return prm.NODE_ROLE_SUPPLY
    if T.nodes[u]['attributes']['node_role'] == prm.NODE_ROLE_DEMAND:
        return prm.NODE_ROLE_DEMAND


def set_power_of_supply_node(T: nx.Graph, u, value: float) -> None:
    """
    Sets the power of a supply node.

    Parameters:
    -----------
    T : networkx.Graph
        Graph containing the supply node.
    u : hashable
        Supply node identifier.
    value : float
        Power value to be assigned.

    Returns:
    --------
    None
    """
    T.nodes[u]['attributes'][prm.KEY_SUPPLY_POWER] = value


def set_power_of_demand_node(T: nx.Graph, u, value: float) -> None:
    """
    Sets the power of a demand node.

    Parameters:
    -----------
    T : networkx.Graph
        Graph containing the demand node.
    u : hashable
        Demand node identifier.
    value : float
        Power value to be assigned.

    Returns:
    --------
    None
    """
    T.nodes[u]['attributes'][prm.KEY_DEMAND_POWER] = value


def get_power_of_supply_node(T: nx.Graph, u) -> float:
    """
    Get the power of a supply node.

    Parameters:
    -----------
    T : networkx.Graph
        Graph containing the supply node.
    u : hashable
        Supply node identifier.

    Returns:
    --------
    float:
        Power value of the supply node
    """
    return float(T.nodes[u]['attributes'][prm.KEY_SUPPLY_POWER])


def get_power_of_demand_node(T: nx.Graph, u) -> float:
    """
    Get the power of a demand node.

    Parameters:
    -----------
    T : networkx.Graph
        Graph containing the demand node.
    u : hashable
        Demand node identifier.

    Returns:
    --------
    float:
        Power value of the demand node
    """
    return float(T.nodes[u]['attributes'][prm.KEY_DEMAND_POWER])


def calculate_sum_power(T: nx.Graph, D: list) -> float:
    """
    Calculates the sum of power for a set of nodes.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph containing nodes.
    D : list
        List of node identifiers.

    Returns:
    --------
    float
        Summed power of the given nodes.
    """
    dw = 0

    for node in D:
        dw += get_power_of_demand_node(T, node)

    return dw


def get_children(T: nx.Graph, u) -> list:
    """
    Returns all child nodes of a given node.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph.
    u : hashable
        Node identifier whose children are returned.

    Returns:
    --------
    list
        List of child node identifiers.
    """
    # get all neighbors n of the node u
    neighbors = T.neighbors(u)
    children = []

    # iterate over every neighbors n_ of all neighbors n
    for neighbor in neighbors:
        # store only n_ if it is a demand and has degree 1
        if T.degree(neighbor) == 1:
            children.append(neighbor)
    
    return children


def remove_all_children(T: nx.Graph, D: list) -> None:
    """
    Removes all specified child nodes from the graph.

    Parameters:
    -----------
    T : networkx.Graph
        Graph from which nodes are removed.
    D : list
        List of child node identifiers to be removed.

    Returns:
    --------
    None
    """
    T.remove_nodes_from(D)


def merge_nodes(T: nx.Graph, u, D: {list, str}) -> None:
    """
    Merges one or multiple nodes into a target node.

    Parameters:
    -----------
    T : networkx.Graph
        Graph containing the nodes to be merged.
    u : hashable
        Target node into which other nodes are merged.
    D : list or str
        Node identifier or list of node identifiers to be merged into the target node.

    Returns:
    --------
    None
    """ 

    if isinstance(D, list):
        for d in D:
            if d not in get_merged_nodes(T, u):
                T.nodes[u]['attributes']['merged_nodes'].append(d)

                gmd = get_merged_nodes(T, d)
                if len(gmd) > 0:
                    for g in gmd:
                        T.nodes[u]['attributes']['merged_nodes'].append(g)
    else:
        if D not in get_merged_nodes(T, u):
            T.nodes[u]['attributes']['merged_nodes'].append(D)

        m_n = get_merged_nodes(T, D)
        
        if len(m_n) > 0:
            for n in m_n:
                T.nodes[u]['attributes']['merged_nodes'].append(n)
        else:
            T.nodes[u]['attributes']['merged_nodes'].append(D)
# ### TODO Test (funktionier!):
# def merge_nodes(
#     T: nx.Graph,
#     u,
#     D: {list, str},
# ) -> None:
#     """
#     Merges one or multiple nodes into a target node.
#     """

#     target_merged_nodes = get_merged_nodes(
#         T,
#         u,
#     )

#     if isinstance(D, list):
#         nodes_to_merge = D
#     else:
#         nodes_to_merge = [D]

#     for node in nodes_to_merge:
#         if node not in target_merged_nodes:
#             target_merged_nodes.append(
#                 node
#             )

#         source_merged_nodes = get_merged_nodes(
#             T,
#             node,
#         )

#         for merged_node in source_merged_nodes:
#             if merged_node not in target_merged_nodes:
#                 target_merged_nodes.append(
#                     merged_node
#                 )

def get_merged_nodes(T: nx.Graph, u) -> list:
    """
    Returns the list of nodes merged into a given node.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph containing merged node information.
    u : hashable
        Node identifier.

    Returns:
    --------
    list
        List of merged node identifiers.
    """
    return T.nodes[u]['attributes']['merged_nodes']


def assign_to_supply_node(T: nx.Graph, u, D: list) -> None:
    """
    Assigns demand nodes to a supply node.

    Parameters:
    -----------
    T : networkx.Graph
        Graph containing the supply and demand nodes.
    u : hashable
        Supply node identifier.
    D : list
        List of demand node identifiers to be assigned.

    Returns:
    --------
    None
    """
    T.nodes[u]['attributes']['merged_nodes'].extend(D)


def get_nodes_by_role(G: nx.Graph, role: str) -> list:
    """
    Returns all nodes with a specific role.

    Parameters:
    -----------
    G : networkx.Graph
        Graph containing node attributes.
    role : str
        Node role to be filtered (e.g. "SUPPLY", "DEMAND").

    Returns:
    --------
    list
        List of node identifiers matching the specified role.
    """
    nodes = []

    for node, attr in G.nodes(data=True):
        if attr.get('attributes').get('node_role') == role:
            nodes.append(node)

    return nodes


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


def delete_isolated_nodes(G: nx.MultiDiGraph):
    """
    Removes isolated common nodes from the graph.

    Parameters:
    -----------
    G : networkx.MultiDiGraph
        Graph from which isolated nodes are removed.

    Returns:
    --------
    networkx.MultiDiGraph
        Graph with isolated nodes removed.
    """
    while(True):
        isolated_nodes = []

        for node, attr in G.nodes(data=True):
            if attr.get('attributes').get('node_type') == 'COMMON' and G.degree[node] == 1:
                isolated_nodes.append(node)
        
        if len(isolated_nodes) > 0:
            G.remove_nodes_from(isolated_nodes)

        if len(isolated_nodes) == 0:
            break
    
    return G


def get_nodes_of_partition(T: nx.MultiGraph, G: nx.MultiGraph) -> dict:
    """
    Retrieves nodes belonging to a partition.

    Parameters:
    -----------
    T : networkx.MultiGraph
        Partitioned graph.
    G : networkx.MultiGraph
        Original graph.

    Returns:
    --------
    tuple
        Tuple containing:
        - list
            List of node identifiers belonging to the partition.
        - dict
            Dictionary mapping node identifiers to their positions.
    """
    part_nodes = []

    for node in T:
        if node not in part_nodes:
            part_nodes.append(node)
            part_nodes.extend(x for x in get_merged_nodes(T, node) if x not in part_nodes)

    # get the position of each node of the original Graph
    pos = {}

    for node in part_nodes:
        pos[node] = G.nodes[node]['attributes']['pos']

    return part_nodes, pos


def generate_colors(n: int) -> list:
    """
    Generates random HEX color codes.

    Parameters:
    -----------
    n : int
        Number of colors to generate.

    Returns:
    --------
    list
        List of HEX color codes.
    """
    colors = []

    for i in range(n):
        color = np.random.randint(0, 256, size=3)
        colors.append('#{:02X}{:02X}{:02X}'.format(color[0], color[1], color[2]))

    return colors


def generate_single_color():
    """
    Generates a single random HEX color code.

    Parameters:
    -----------
    None

    Returns:
    --------
    str
        Randomly generated HEX color code.
    """

    return "#%06x" % random.randint(0, 0xFFFFFF)


def partition(T: nx.Graph) -> nx.Graph:
    """
    Partitions the given graph into subgraphs.

    Parameters:
    -----------
    T : networkx.Graph
        Input graph to be partitioned.

    Returns:
    --------
    networkx.Graph
        Partitioned graph.
    """

    # begin
    # while T has two or more vertices do
    while get_n_vertices(T) >= 2:
        # begin
        # Choose an arbitrary internal vertex u of T all of whose children are leaves {Fig2(a)-(c)}
        leaves = get_nodes_with_only_leaves(T)

        
        if leaves:
            u = random.choice(leaves)

        if len(leaves) == 0:
            break        


        # Let D be the set of all children of u that are demand vertices
        D = get_children_demand_vertices(T, u)
        # if u is a supply vertex then
        if get_vertex_type(T, u) == prm.NODE_ROLE_SUPPLY:
            # if s(u) < sum(d(w)) then
            d_w = calculate_sum_power(T, D)
            if get_power_of_supply_node(T, u) < d_w:
                break
            elif get_power_of_supply_node(T, u) >= d_w:
                # begin
                    # All the vertices in D must be supplied power from u
                    merge_nodes(T, u, D)

                    # Delete all the children of u from T
                    children = get_children(T, u)

                    remove_all_children(T, children)

                    # Let s(u) := s(u) - sum(d(w))
                    set_power_of_supply_node(T, u, get_power_of_supply_node(T, u) - d_w)
                #end
        # u is a demand vertex. All demand vertices in D{u} should be supplied power from the same supply vertex
        else:
            # begin
            # {merge all the demand vertices in D{u} into a new single demand vertex u}
            # Let d(u) := d(u) + sum(d(w))
            d_w = calculate_sum_power(T, D)
            set_power_of_demand_node(T, u, get_power_of_demand_node(T, u) + d_w)
            merge_nodes(T, u, D)
            # Delete all vertices in D from T
            T.remove_nodes_from(D)

            # Let T be the resulting tree
            if get_n_vertices(T) <= 2:
                break            
    
            children = get_children(T, u)
            # if u has a child then
            if len(children) > 0:
                # begin
                # all the children of u are supply vertices, and u must be supplied either from a child of u or through the parent of u
                # Find a child v of u whose supply is maximum among all children of u
                v = max(children, key=lambda n: T.nodes[n]['attributes']['su'])

                # delete all the other children of u from T
                children_copy = list(children)
                children_copy.remove(v)
                T.remove_nodes_from(children_copy)
                
                # Let T be the resulting tree
                # if d(u) <= s(v) then
                if get_power_of_demand_node(T, u) <= get_power_of_supply_node(T, v):
                    # begin
                    # One may assume that u is supplied power from v
                    merge_nodes(T, v, u)
                    # Delete u from T
                    # Join v with the parent of u
                    # Let s(v) := s(v) - d(u)
                    # Let T be the resulting tree
                    #print(f'children: {children}')
                    neighbors = T.neighbors(u)
            
                    parents = []
                    if neighbors:
                        for n in neighbors:
                            #print(f'n: {n}')
                            if n not in children:
                                #parent = n
                                parents.append(n)
                                #break
            
                    s_v = float(T.nodes[v]['attributes']['su'])
                    T.nodes[v]['attributes']['su'] = s_v - float(T.nodes[u]['attributes']['dv'])
            
                    # if u has none parents
                    if len(parents) == 0:
                        None
                    # if u has exactly one parent
                    elif len(parents) == 1:
                        T.remove_edge(parents[0], u)
                        T.remove_edge(u, v)
                        T.add_edge(parents[0], v)
                        T.remove_node(u)
                    elif len(parents) == 2:
                        T.remove_edge(parents[0], u)
                        T.remove_edge(u, v)
                        # Join v with the parent of u
                        T.add_edge(parents[0], v)
                        T.remove_node(u)

                        # remove edge between parents[1] and u
                        #T.remove_edge(parents[1], u)
                        # create edge between parents[0] and parents[1]
                        T.add_edge(parents[0], parents[1])
            
                # Let T be the resulting tree
                else:
                    # d(u) > s(v). u must be supplied power through the parent of u
                    # begin
                    #print('u must be supplied power through the parent of u')            
                    T.remove_node(v)
                    # end
                # end

    return T


def partition_trafo_check(assoc_nodes):
    """
    Checks whether a partition contains a transformer node.

    Parameters:
    -----------
    assoc_nodes : iterable
        Iterable of associated node identifiers.

    Returns:
    --------
    bool
        True if at least one transformer node is present, otherwise False.
    """
    return any(str(n).startswith('TR') for n in assoc_nodes)


# def part_H(G: nx.Graph, df: pd.DataFrame) -> dict:
#     """
#     Partitions a graph into connected subgraphs and stores the results in a DataFrame.

#     Parameters:
#     -----------
#     G : networkx.Graph
#         Input graph to be partitioned.
#     df : pandas.DataFrame
#         DataFrame used to store partition metadata (e.g., subgraph, nodes, positions).

#     Returns:
#     --------
#     pandas.DataFrame
#         DataFrame containing the generated partitions and associated metadata.
#     """

#     colors = []
#     G_work = G.copy()
#     partition_index = 0

#     used_nodes = set()

#     while G_work.number_of_nodes() > 2:
#         active_nodes = [n for n in G.nodes if n not in used_nodes]
#         T_active = G.subgraph(active_nodes).copy()
#         T_part = partition(T_active.copy())

#         if not nx.is_connected(T_part):
#             components = list(nx.connected_components(T_part))
#             largest_component = max(components, key=len)
#             T_part = T_part.subgraph(largest_component).copy()
        
#         part_nodes, pos = get_nodes_of_partition(T_part, G)

#         if len(part_nodes) == 0:
#             break

#         subgraph = G.subgraph(part_nodes).copy()
#         df.loc[len(df)] = [partition_index, f'H_s_{partition_index}.gml', subgraph, part_nodes, pos]
#         colors.append(generate_single_color())

#         # mark already used nodes
#         used_nodes.update(part_nodes)

#         # remov used nodes from G_work
#         G_work.remove_nodes_from(part_nodes)

#         partition_index += 1
    
#     df['color'] = colors
#     df['contains_trafo'] = df['associated_nodes'].apply(partition_trafo_check)

#     return df

def part_H(
    G: nx.Graph,
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Partitions a graph into connected, non-overlapping subgraphs.
    """

    colors = []
    partition_index = 0

    # Deep copy because partition() modifies nested node attributes.
    G_work = copy.deepcopy(G)

    while G_work.number_of_nodes() > 2:
        # Work only on a deep copy of the remaining graph.
        T_part = partition(
            copy.deepcopy(G_work)
        )

        if T_part.number_of_nodes() == 0:
            break

        if not nx.is_connected(T_part):
            components = list(
                nx.connected_components(T_part)
            )

            largest_component = max(
                components,
                key=len,
            )

            T_part = T_part.subgraph(
                largest_component
            ).copy()

        part_nodes, pos = get_nodes_of_partition(
            T_part,
            G,
        )

        # Remove possible duplicate entries while preserving order.
        part_nodes = list(
            dict.fromkeys(part_nodes)
        )

        if len(part_nodes) == 0:
            break

        subgraph = G.subgraph(
            part_nodes
        ).copy()

        df.loc[len(df)] = [
            partition_index,
            f"H_s_{partition_index}.gml",
            subgraph,
            part_nodes,
            pos,
        ]

        colors.append(
            generate_single_color()
        )

        # Nodes assigned to this partition cannot be used again.
        G_work.remove_nodes_from(
            part_nodes
        )

        partition_index += 1

    df["color"] = colors

    df["contains_trafo"] = (
        df["associated_nodes"]
        .apply(partition_trafo_check)
    )

    return df
#### TODO TEST
# def part_H(
#     G: nx.Graph,
#     df: pd.DataFrame,
# ) -> pd.DataFrame:
#     """
#     Partitions a graph into non-overlapping connected subgraphs.

#     A deep copy is required because the partitioning algorithm modifies
#     nested node attributes such as ``attributes["merged_nodes"]``,
#     supply power and demand power.
#     """

#     colors = []
#     partition_index = 0
#     used_nodes = set()

#     # Ensure that repeated calls do not retain rows from an earlier run.
#     df = df.iloc[0:0].copy()

#     # The working graph is only reduced by removing completed partitions.
#     G_work = copy.deepcopy(G)

#     while G_work.number_of_nodes() > 2:
#         # partition() modifies nested node attributes. A normal NetworkX
#         # copy would share these nested objects with the source graph.
#         T_active = copy.deepcopy(G_work)
#         T_part = partition(T_active)

#         if T_part.number_of_nodes() == 0:
#             break

#         if not nx.is_connected(T_part):
#             components = list(
#                 nx.connected_components(T_part)
#             )

#             largest_component = max(
#                 components,
#                 key=len,
#             )

#             T_part = T_part.subgraph(
#                 largest_component
#             ).copy()

#         part_nodes, pos = get_nodes_of_partition(
#             T_part,
#             G,
#         )

#         # Preserve order while removing duplicates within one partition.
#         part_nodes = list(dict.fromkeys(part_nodes))

#         if len(part_nodes) == 0:
#             break

#         # A node must never occur in more than one partition.
#         overlapping_nodes = sorted(
#             set(part_nodes).intersection(used_nodes),
#             key=str,
#         )

#         if overlapping_nodes:
#             raise RuntimeError(
#                 "Nodes were assigned to multiple partitions. "
#                 f"Examples: {overlapping_nodes[:20]}"
#             )

#         unavailable_nodes = [
#             node
#             for node in part_nodes
#             if node not in G_work
#         ]

#         if unavailable_nodes:
#             raise RuntimeError(
#                 "Partition contains nodes that are no longer "
#                 "available in the working graph. "
#                 f"Examples: {unavailable_nodes[:20]}"
#             )

#         subgraph = G.subgraph(
#             part_nodes
#         ).copy()

#         df.loc[len(df)] = [
#             partition_index,
#             f"H_s_{partition_index}.gml",
#             subgraph,
#             part_nodes,
#             pos,
#         ]

#         colors.append(
#             generate_single_color()
#         )

#         used_nodes.update(
#             part_nodes
#         )

#         G_work.remove_nodes_from(
#             part_nodes
#         )

#         partition_index += 1

#     df["color"] = colors

#     df["contains_trafo"] = (
#         df["associated_nodes"]
#         .apply(partition_trafo_check)
#     )

#     return df

def extract_H_s(df: pd.DataFrame, G: nx.MultiGraph) -> list:
    """
    Extracts subgraphs containing transformers from the partition DataFrame.

    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame containing partition information and associated nodes.
    G : networkx.MultiGraph
        Original graph from which subgraphs are extracted.

    Returns:
    --------
    list
        List of extracted subgraphs containing transformer nodes.
    """
    subgraphs_arr = []
    subgraphs_filenames = []

    for idx, row in df.iterrows():
        if row['contains_trafo'] == True:
            nodes = row['subgraph']
            subgraphs_filenames.append(row['subgraph_file'])

            G_s = G.subgraph(nodes).copy()

            attributes = nx.get_node_attributes(G, 'attributes')
            pos = {k: v['pos'] for k, v in attributes.items() if k in nodes}

            nx.set_node_attributes(G_s, {n: attributes[n] for n in G_s.nodes if n in attributes}, 'attributes')
            nx.set_node_attributes(G_s, pos, 'pos')

            edge_attr = {(u, v): d for u, v, d in G.edges(data=True)
                    if u in nodes and v in nodes}
    
            for (u, v), d in edge_attr.items():
                if G_s.has_edge(u, v):
                    G_s[u][v].update(d)

            G_s = delete_isolated_nodes(G_s) # delete isolated nodes

            subgraphs_arr.append(G_s)
        else:
            None
    
    return subgraphs_arr


def network_demand_power(G: nx.MultiGraph) -> float:
    """
    Calculates the total demand power of the network.

    Parameters:
    -----------
    G : networkx.MultiGraph
        Network graph containing demand node attributes.

    Returns:
    --------
    float
        Total demand power of the network.
    """
    demand_nodes =  get_nodes_by_type(G, 'RESDTL') + get_nodes_by_type(G, 'APTMNT') + get_nodes_by_type(G, 'HOUSE') + get_nodes_by_type(G, 'AMENTY')
    dv = []

    for node, attr in G.nodes(data=True):
        if node in demand_nodes:
            dv.append(attr['attributes']['dv'])

    dv = np.sum(np.array(dv))
    
    return dv


def network_trafo_rated_power(G: nx.MultiGraph, rated_values: list) -> float:
    """
    Determines the required transformer rated power for the network.

    Parameters:
    -----------
    G : networkx.MultiGraph
        Network graph containing demand information.
    rated_values : list
        List of available transformer rated power values.

    Returns:
    --------
    float
        Selected transformer rated power sufficient to supply the network demand.
    """

    p_demand = network_demand_power(G)/(prm.WORKLOAD * prm.POWER_FACTOR)

    if rated_values is None:
        rated_values = prm.TRANSFORMER_RATED_POWER

    for t in rated_values:
        if p_demand <= t:
            return t
    
    return max(rated_values)


def resize_network_transformers(G_: list[nx.MultiGraph]) -> list[nx.MultiGraph]:
    """
    Resizes transformer rated power for each network based on its demand.

    Parameters:
    -----------
    G_ : list of networkx.MultiGraph
        List of network subgraphs containing transformer and demand nodes.

    Returns:
    --------
    list of networkx.MultiGraph
        List of network subgraphs with updated transformer rated power.
    """

    for idx, G in enumerate(G_):
        tr_node = get_nodes_by_type(G, prm.NODE_TYPE_TRFORM)[0]
        tr_rated_power = network_trafo_rated_power(G, prm.TRANSFORMER_RATED_POWER)
        set_power_of_supply_node(G, tr_node, tr_rated_power)

    return G_


def calculate_subgraph_center(G: nx.MultiGraph):
    """
    Calculates the centroid of a subgraph based on its node positions.

    Parameters:
    -----------
    G : networkx.MultiGraph
        Graph or subgraph whose geometric center is calculated.

    Returns:
    --------
    tuple
        Coordinates (x, y) of the calculated subgraph centroid.
    """
    attributes = nx.get_node_attributes(G, 'attributes')
    pos = {k: v['pos'] for k, v in attributes.items()}

    coords = list(pos.values())
    hull = MultiPoint(coords).convex_hull

    # calculate center of the hull
    c_x, c_y = hull.centroid.x, hull.centroid.y
    c = (c_x, c_y)
    
    return c


def separate_networks(G_: list[nx.MultiGraph], tr_syn_gdf: pd.DataFrame) -> list:
    """
    Separates disconnected network graphs and ensures transformer placement.

    Parameters:
    -----------
    G_ : list of networkx.MultiGraph
        List of network graphs to be checked and separated.
    tr_syn_gdf : pandas.DataFrame
        DataFrame containing existing synthetic transformer information.

    Returns:
    --------
    list
        List of connected network graphs with ensured transformer placement.
    """
    Gs = []

    # iterate over every given graph
    for G in G_:
        if not nx.is_connected(G):
            # if G is not connected, separate all components
            components = [G.subgraph(c).copy() for c in nx.connected_components(G)]
            
            # add the components to the graph list
            for component in components:
                # check if component has trafo, if ther is no trafo -> one has to be placed
                if(len(get_nodes_by_type(component, 'TRFORM')) == 0):
                    center = list(calculate_subgraph_center(component))
                    powcon_nodes = get_nodes_by_type(component, 'POWCON') # search all powcon nodes in graph G
                    
                    if len(powcon_nodes) == 0:
                        break
                    #node_pos = gu.get_pos_by_nodelist(G, powcon_nodes)
                    idx, nearest_node, shortest_distance = nearest_node_to(center=center, G=component, nodelist=powcon_nodes)
                    
                    last_tr_id = tr_syn_gdf["id"].iloc[-1]
                    last_number = int(last_tr_id.replace("TR", ""))
                    new_id = f"TR{last_number+1:08d}"

                    # place transformer in network
                    place_tr_node(G=component, u=new_id, v=nearest_node, l=shortest_distance, pos=center)
                
                Gs.append(component)
        else:
            # if G is connected, add it to the graph list
            Gs.append(G)

    return Gs


def nearest_node_to(center: list, G: nx.MultiGraph, nodelist: list[nx.MultiGraph]) -> tuple:
    """
    Finds the nearest node to a given point.

    Parameters:
    -----------
    center : list
        Coordinates [x, y] of the reference point.
    G : networkx.MultiGraph
        Graph containing the nodes.
    nodelist : list
        List of node identifiers to be considered.

    Returns:
    --------
    tuple
        Tuple:
        - int
            Index of the nearest node in the node list.
        - hashable
            Identifier of the nearest node.
        - float
            Distance to the nearest node.
    """
    nearest_node = None
    shortest_distance = np.inf

    points = get_pos_by_nodelist(G, nodelist)

    distances = np.linalg.norm(np.array(points) - np.array(center), axis=1)
    idx = np.argmin(distances)

    nearest_node = nodelist[idx]
    shortest_distance = distances[idx]
    
    return idx, nearest_node, shortest_distance


def place_tr_node(G: nx.MultiGraph, u: str, v: str, l: float, pos: list) -> nx.MultiGraph:
    """
    Places a transformer node in the graph and connects it to a given node.

    Parameters:
    -----------
    G : networkx.MultiGraph
        Graph in which the transformer node is placed.
    u : str
        Identifier of the new transformer node.
    v : str
        Identifier of the existing node to which the transformer is connected.
    l : float
        Length of the connecting edge.
    pos : list
        Coordinates [x, y] of the transformer position.

    Returns:
    --------
    networkx.MultiGraph
        Updated graph with the inserted transformer node.
    """

    # add node u as start node (center point of given graph)
    G.add_node( u,
                attributes= {
                                'id':               'ND' + u,
                                'pos':              (pos[0], pos[1]),
                                'node_type':        'TRFORM',
                                'node_role':        'SUPPLY',
                                'su':               0,
                                'merged_nodes':     []
                            })
    

    
    # add the edge from the node point and the centroid of the building
    G.add_edge( u, 
                v,
                attributes={
                            'id':       'TC' + u,
                            'type':     prm.LINE_TRFM,
                            'length':   l
                        },
                        length = l   )
    

def get_graph_elements(G: nx.MultiGraph) -> tuple:
    """
    Extracts nodes, edges, positions, and attributes from a network graph.

    Parameters:
    -----------
    G : networkx.MultiGraph
        Network graph containing node and edge attributes.

    Returns:
    --------
    tuple
        Tuple:
        - dict
            Node attributes keyed by node identifier.
        - dict
            Dictionary mapping node identifiers to positions.
        - list
            Transformer node identifiers.
        - list
            Common node identifiers.
        - list
            Power connection node identifiers.
        - list
            Residential node identifiers.
        - list
            Amenity node identifiers.
        - list
            House node identifiers.
        - list
            Apartment node identifiers.
        - list
            Edge list with attributes.
    """
    attributes = nx.get_node_attributes(G, 'attributes')    # get all attributes for each node of graph G
    pos = {k: v['pos'] for k, v in attributes.items()}      # get the position of each node of graph G
    nodes_transformers = get_nodes_by_type(G, 'TRFORM')  # get all transformer nodes of graph G
    nodes_common = get_nodes_by_type(G, 'COMMON')        # get all common nodes of graph G
    nodes_powcon = get_nodes_by_type(G, 'POWCON')        # get all powcon nodes of graph G
    line_edges = list(G.edges(data=True))

    nodes_resdtl = get_nodes_by_type(G, 'RESDTL')
    nodes_amenty = get_nodes_by_type(G, 'AMENTY')
    nodes_house = get_nodes_by_type(G, 'HOUSE')
    nodes_aptmnt = get_nodes_by_type(G, 'APTMNT')

    return attributes, pos, nodes_transformers, nodes_common, nodes_powcon, nodes_resdtl, nodes_amenty, nodes_house, nodes_aptmnt, line_edges
