# =============================================================================
# Project:      lv-syn-grid
# Author:       Roman S.
# Modified by:  Friedrich H.
# Created:      2025
# Modified:     2026
#
# Description:
# Project parameters
#
# Modifications:
# Removal of NÖ Atlas-specific parameters and addition of BEV-compatible
# building-height parameters.
#
# License: MIT License
#
# =============================================================================

# imports
import os
from pathlib import Path
from collections import namedtuple

# ******************* project specific parameters *******************
PROJECT = 'Grossschoenau_Neu'   # <-- change for project

# folder structure for data export
# Repository root:
# <repo>/external/seiler/scripts/parameters.py
#                  0       1      2       3
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Data lifecycle
_INTERIM_GRID = _REPO_ROOT / "data" / "interim" / "grids" / PROJECT
_PROCESSED_GRID = _REPO_ROOT / "data" / "processed" / "grids" / PROJECT
_RAW_AOI = _REPO_ROOT / "data" / "raw" / "aoi" / PROJECT
_RAW_SLP = _REPO_ROOT / "data" / "raw" / "slp"

# Generated outputs
_OUTPUT_ROOT = _REPO_ROOT / "outputs" / PROJECT

# Paths used by the adapted Seiler pipeline
FILEPATH_DATA = _INTERIM_GRID.as_posix() + "/"
FILEPATH_GRAPH = (_INTERIM_GRID / "graph").as_posix() + "/"

FILEPATH_LV_GRID = _PROCESSED_GRID.as_posix() + "/"
FILEPATH_MV_GRID = (_PROCESSED_GRID / "mv").as_posix() + "/"

FILEPATH_AOI = _RAW_AOI.as_posix() + "/"
FILEPATH_SLP = _RAW_SLP.as_posix() + "/"

FILEPATH_PLOTS = (_OUTPUT_ROOT / "base_grid" / "figures").as_posix() + "/"
FILEPATH_SIMRES = (
    _OUTPUT_ROOT / "base_grid" / "powerflow" / "seiler"
).as_posix() + "/"

# file paths for data export
FILEPATH_STREETS_PARQUET = 'streets.parquet'
FILEPATH_BUILDINGS_PARQUET = 'buildings.parquet'
FILEPATH_NODES_PARQUET = 'nodes.parquet'
FILEPATH_LINES_PARQUET = 'lines.parquet'
FILEPATH_TRANSFORMERS_PARQUET = 'transformers.parquet'
FILEPATH_PV_PARQUET = 'photovoltaic.parquet'

FILE_STREETS_PARQUET = 'streets.parquet'
FILE_BUILDINGS_PARQUET = 'buildings.parquet'
FILE_NODES_PARQUET = 'nodes.parquet'
FILE_LINES_PARQUET = 'lines.parquet'
FILE_TRANSFORMERS_PARQUET = 'transformers.parquet'
FILE_PV_PARQUET = 'photovoltaic.parquet'

# file paths
FILENAME_POLYGON_CSV = 'polygon_coordinates.csv'
FILENAME_BUILDINGS_PARQUET = 'buildings.parquet'
FILENAME_STREETS_PARQUET = 'streets.parquet'
FILENAME_LINES_PARQUET = 'lines.parquet'
FILENAME_TRANSFORMERS_PARQUET = 'transformers.parquet'
FILENAME_NODES_PARQUET = 'nodes.parquet'

FILE_SIMRES_BUSVOLTAGE = 'res_bus/vm_pu.xlsx'
FILE_SIMRES_LINELOADING = 'res_line/loading_percent.xlsx'
FILE_SIMRES_TRAFOLOADING ='res_trafo/loading_percent.xlsx'

# create folder structure
os.makedirs(FILEPATH_DATA, exist_ok=True)
os.makedirs(FILEPATH_GRAPH, exist_ok=True)
os.makedirs(FILEPATH_LV_GRID, exist_ok=True)
os.makedirs(FILEPATH_MV_GRID, exist_ok=True)
os.makedirs(FILEPATH_AOI, exist_ok=True)
os.makedirs(FILEPATH_SLP, exist_ok=True)
os.makedirs(FILEPATH_PLOTS, exist_ok=True)
os.makedirs(FILEPATH_SIMRES, exist_ok=True)

CRS_GEO = 'EPSG:4326'
CRS_XY = 'EPSG:9273'

# ******************* transformer specific parameters *******************
# transformer types and their capacity in kVA, which should be used for the synthesis

#TRANSFORMER_RATED_POWER = [160, 250]        # countryside
TRANSFORMER_RATED_POWER = [160, 250, 400]   # village
#TRANSFORMER_RATED_POWER = [160, 250, 400, 630] # village, suburb
#TRANSFORMER_RATED_POWER = [160, 250, 400, 630, 800]    # suburb

WORKLOAD = 0.5          # workload, LT = 50 [%]
POWER_FACTOR = 0.95     # lambda   [1]
POWER_TRANSFORMER = 160 # RT = 400 [kVA]
DELTA = 15

# ******************* load profile specific parameters *******************
# synthetic load profiles
FILE_SYNTHETIC_LOAD_PROFILES = 'synthload2025.xlsx'
SLP_REFERENCE_YEAR = 2025
SLPS = ['H0', 'G0', 'G1', 'G2', 'G3', 'G6']

# constants for data acquisition and pre-processing
FOOTPRINT_AREA_THRESHHOLD = 60  #[m2]

TAGS_NONRESIDENTIAL_BUILDINGS = {
    'amenity': True
}

TAGS_RESIDENTIAL_BUILDINGS = {
    'building':'yes',
    'addr:housenumber': True
}

TAGS_STREETS = {
    'highway':  ['primary', 'secondary', 'tertiary', 'residential', 'road', 'unclassified']#, 'track', 'service']
}

# building types
PUBLIC = 'public'
APARTMENTS = 'apartments'
HOUSE = 'house'

# parameters for load estimation
AVERAGE_RESIDENTS = 2.74
CONSUMPTION_PER_RESIDENT = 200
CONSUMPTION_PER_AREA = 9
NUMBER_OF_DEVICES = 8.4
CONSUMPTION_OF_DEVICES = 200
AVERAGE_FLAT_AREA = 101.8
MINIMUM_BUILDING_HEIGHT = 5.0   # [m]
MINIMUM_BUILDING_FLOORS = 1
AVERAGE_ROOM_HEIGHT = 2.6       # [m]

#######################################################################
############## DO NOT CHANGE ##########################################
#######################################################################

# keys for storing the values supply / demand
KEY_SUPPLY_POWER = 'su'
KEY_DEMAND_POWER = 'dv'

# node roles
NODE_ROLE_DEMAND = 'DEMAND' # node is a demand node
NODE_ROLE_SUPPLY = 'SUPPLY' # node is a supply node

# node types
NODE_TYPE_COMMON = 'COMMON' # common node, no specific property, connects street segments
NODE_TYPE_POWCON = 'POWCON' # node works as power connector, either a supply or demand is connected to it
NODE_TYPE_RESDTL = 'RESDTL' # node is a residential building
NODE_TYPE_AMENTY = 'AMENTY' # node is an amenity building
NODE_TYPE_TRFORM = 'TRFORM' # node is a transformer
NODE_TYPE_HOUSE  = 'HOUSE'  # node is a single-family-house
NODE_TYPE_MULTI  = 'APTMNT' # node is a multi-family-building

LINE_MAIN = 'LIMAIN'    # main line, works as a line segment in the lv network
LINE_CONN = 'LICONN'    # represents a line which connects a building to the lv network (lower cross area section, shorter length, etc.)
LINE_TRFM = 'TRCONN'    # represents a line which connects a transformer to the lv network

LOAD_PROFILES = {
    'residential':  'H0',
    'education':    'G1',
    'retail':       'G1',
    'gastro':       'G2',
    'health':       'G3',
    'public':       'G3',
    'culture':      'G6',
    'religion':     'G6',
    'other':        'G0'
}

building_info = namedtuple('building_info', ['category', 'load_profile', 'energy_demand'])


# data from:
# https://www.dena.de/fileadmin/dena/Publikationen/PDFs/2023/STUDIE_Fit_fuer_2045_Zielparameter_fuer_Nichtwohngebaeude_im_Bestand.pdf
AMENITIES = {
    # retail
    'convenience':      building_info('retail', LOAD_PROFILES['retail'], 217),
    'bakery':           building_info('retail', LOAD_PROFILES['retail'], 217),
    'butcher':          building_info('retail', LOAD_PROFILES['retail'], 217),
    'marketplace':      building_info('retail', LOAD_PROFILES['retail'], 217),
    'supermarket':      building_info('retail', LOAD_PROFILES['retail'], 217),
    
    # health
    'clinic':           building_info('health', LOAD_PROFILES['health'], 38),
    'dentist':          building_info('health', LOAD_PROFILES['health'], 38),
    'doctors':          building_info('health', LOAD_PROFILES['health'], 38),
    'hospital':         building_info('health', LOAD_PROFILES['health'], 38),
    'nursing_home':     building_info('health', LOAD_PROFILES['health'], 38),
    'pharmacy':         building_info('health', LOAD_PROFILES['health'], 38),
    
    # public
    'fire_station':     building_info('public', LOAD_PROFILES['public'], 28),
    'police':           building_info('public', LOAD_PROFILES['public'], 28),
    'post_office':      building_info('public', LOAD_PROFILES['public'], 28),
    
    # culture
    'arts_centre':      building_info('culture', LOAD_PROFILES['culture'], 32),
    'cinema':           building_info('culture', LOAD_PROFILES['culture'], 32),
    'theatre':          building_info('culture', LOAD_PROFILES['culture'], 32),
    'stadium':          building_info('culture', LOAD_PROFILES['culture'], 32),
    'sports_centre':    building_info('culture', LOAD_PROFILES['culture'], 32),
    'swimming_pool':    building_info('culture', LOAD_PROFILES['culture'], 32),
    'gym':              building_info('culture', LOAD_PROFILES['culture'], 32),
    'place_of_worship': building_info('education', LOAD_PROFILES['culture'], 32),
    
    # gastro
    'restaurant':       building_info('gastro', LOAD_PROFILES['gastro'], 104),
    'cafe':             building_info('gastro', LOAD_PROFILES['gastro'], 104),
    'bar':              building_info('gastro', LOAD_PROFILES['gastro'], 104),
    'fast_food':        building_info('gastro', LOAD_PROFILES['gastro'], 104),
    'food_court':       building_info('gastro', LOAD_PROFILES['gastro'], 104),
    'pub':              building_info('gastro', LOAD_PROFILES['gastro'], 104),
    
    # education
    'kindergarten':     building_info('education', LOAD_PROFILES['education'], 19),
    'school':           building_info('education', LOAD_PROFILES['education'], 19),
    'college':          building_info('education', LOAD_PROFILES['education'], 29),
    'university':       building_info('education', LOAD_PROFILES['education'], 29),
}
