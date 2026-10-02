# lv-syn-grid
An algorithmic approach for synthesizing realistic low-voltage distribution grids from spatial data using graph-based methods.

### Overview
This python-based tool provides an algorithmic workflow for generating synthetic low-voltage distribution grids from Open Data. Using publicly available OpenStreetMap data, the tool extracts buildings and road networks, estimates electricity demand, derives a radial grid topology with graph-based methods, places transformers, and builds a pandapower network model for power flow and time-series simulations.

### Core Features
- **Automated low-voltage grid synthesis**<br>
  Generation of low-voltage distribution networks based on publicly available geospatial data (e.g., OpenStreetMap, statistical data.
- **Demand estimation based on building data**<br>
  Estimation of electrical loads using building footprints, usage types, and attributes such as floor area and estimated bulding height.
- **Transformer Placement via Clustering**<br>
  Automatic sizing and placement of transformers based on load estimation using the K-Means algorithm.
- **Graph based network construction**<br>
  Representation of the network model using graph theory. A minimum spanning tree (MST) is applied to derive radial grid topologies typical for rural low-voltage grids.
- **Photovoltaic (PV) integration**<br>
Integration of PV systems into the synthesized grid model for simulation.
- **Load flow calculation**<br>
Automatic conversion of the generated graph into a pandapower model, enabling load flow and time series simulations. For the simulation of grid behavior over time standardized load profiles are used, allowing analysis of voltage levels, line loading.
- **Geospatial visualization**<br>
Visualization of networks, loads, and simulation results on geographic maps, enabling intuitive analysis.

### Study Area
Within the scope of the thesis, see section Citation, three rural regions in Lower Austria (Niederösterreich) were selected as case studies. Those areas were chosen primarily due to the availability of data required for model validation.<br>
<br>
While the implemented algorithm is demonstrated using these specific regions, it also can be applied to other geographical areas by adapting input data and parameters.

### Data Sources & Preprocessing
<ins>Main Data Sources:</ins><br>
The model is based on a combination of **geospatial, infrastructural, and statistical open data**. The primary data source consists of building and infrastructure data, which form the basis for network synthesis and load estimation.<br>
- **OpenStreetMap (OSM)**<br>
  Provides geospatial data such as:<br>
  - Building footprints (basis for load allocation)
  - Road networks (used for graph construction)
- **Building-related Data**<br>
  Additional attributes (e.g., building height or type) are used to improve load estimation by enabling approximations of usable floor area
- **Statistical Data**<br>
  Used for scaling and distribution of loads and generation:<br>
  - Population data
  - Regional energy statistics (e.g., PV capacity)
- **Photovoltaic Data**<br>
Locations of PV systems are derived and processed, with typical system parameters (e.g., 12 kWp per installation) assumed for modelling
- **Standardized Load Profiles**<br>
Used to model time-dependent electricity demand for different consumer types

<ins>Preprocessing Steps:</ins><br>
Before the actual network synthesis, the input data undergoes several preprocessing steps to ensure consistency and usability:<br>
- **Data Extraction and Filtering**<br>
Relevant features (e.g., buildings and roads) are extracted from OSM and filtered to the selected study area
- **Coordinate Transformation**<br>
All geospatial data is transformed into a **metric coordinate reference system (CRS) to allow accurate distance calculations and spatial operations
- **Building Processing**<br>
  - Calculation of building centroids
  - Estimation of building characteristics (e.g., height, floor area)
  - Assignment of building types of categories
- **Load Allocation Preparation**<br>
Buildings are prepared for load estimation based on statistical assumptions and available attributes
- **PV Data Integration**<br>
  - PV system locations are mapped to nearby buildings
  - Coordinates are transformed to a consistent CRS
  - Standardized system parameters are assigned for simulation
- **Graph Preparation**<br>
The road network is converted into a graph structure, which serves as the basis for later network generation

### Quick Start
For using this tool a Miniconda installation and a Python installation 3.10+ is recommended. Follow these steps to set up the environment to execute the workflow for synthetic low-voltage grid generation.

**1. Create the environment**
Create the conda environment for the low-voltage grid workflow and PV-related analysis:
```bash
conda env create -f lv_env.yml
conda env create -f pv_env.yml
```
**2. Select study area**
The study area is defined using a user-created polygon in WGS84 format, which is imported within the execution of GeoDAQ.ipynb for further processing. The polygon serves as the spatial boundary for the data acquisition process. Based on this area of interest, relevant OpenStreetMap (OSM) features located within the polygon are automatically retrieved, including:<br/>
- building footprints
- road networks

**3. Set parameters**
The workflow behavior can be configured through the `parameters.py` file. This central configuration file contains all project-specific settings, file paths, technical assumptions, and model parameters required for the generation of synthetic low-voltage-grids.<br/>

- **Project and export settings**<br/>
  - project name
  - output directories
  - file names and data structure
- **Transformer configuration**<br/>
  - available transformer rated powers
  - transformer workload assumptions
  - power factor settings
- **Parameters for load estimation**<br/>
  - average household size
  - energy consumption assumptions
  - building-related demand parameters
  - minimum building dimensions

**4. Execute the workflow**<br/>
Run the notebooks in the following order:<br/>

1. GeoDAQ.ipynb – data acquisition and preprocessing<br/>
2. GeoGraphModel.ipynb – graph construction<br/>
3. GeoGridModel.ipynb – grid synthesis<br/>
4. GeoPVModel.ipynb – PV integration and extension<br/>

**5. Results**

### Scientific Background
This tool was developed as part of a master’s thesis at Vienna University of Technology (TU Wien). Further details on the methodology, assumptions, and results of the
presented approach for a selected set of rural areas can be found in the corresponding thesis: [Open-Data basierte Synthese bestehender Niederspannungsnetze ruraler Gebiete](https://repositum.tuwien.at/handle/20.500.12708/223910)

# License
This project is licensed under the MIT License.<br>
Please see the [LICENSE](LICENSE.txt) file for details.

# Citation
If you use this code in a scientific publication, please cite the associated thesis:
- Seiler, R. (2025). [Open-Data basierte Synthese bestehender Niederspannungsnetze ruraler Gebiete](https://repositum.tuwien.at/handle/20.500.12708/223910)
