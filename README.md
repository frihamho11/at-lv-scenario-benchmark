# Austrian LV Scenario Benchmark Framework

Open-data-based scenario generation, technology allocation and time-series power-flow benchmarking for synthetic Austrian low-voltage distribution grids.

This repository contains the software developed as part of the master's thesis:

**Open-Data-Based Scenario and Benchmark Framework for Regional PV, EV, HP and BESS Penetration in Synthetic Austrian Low-Voltage Grids**

The framework combines publicly available Austrian data with synthetic low-voltage networks in order to create reproducible benchmark scenarios for photovoltaic systems (PV), electric vehicles (EV), heat pumps (HP) and battery energy storage systems (BESS).

The main workflow is:

```text
Public Austrian data
        │
        ▼
Technology-stock harmonisation
(PV / EV / HP)
        │
        ▼
Municipality-level technology stocks
        │
        ▼
Municipality → study-area transfer
        │
        ▼
Building-level technology allocation
        │
        ▼
Electrical representation
(PV / EV / HP / BESS)
        │
        ▼
Synthetic LV network
        │
        ▼
Scenario benchmark
        │
        ▼
15-minute time-series power flow
```

---

## 1. Scope

The framework focuses on five main tasks:

* harmonisation of heterogeneous Austrian open-data sources;
* derivation of municipality-level PV, EV and HP stocks;
* reproducible spatial allocation of technologies to synthetic grid buildings;
* electrical integration of PV, EV, HP and PV-coupled BESS into pandapower networks;
* reproducible time-series power-flow benchmark simulations.

The synthetic low-voltage network itself is generated using a modified version of Roman Seiler's `lv-syn-grid` workflow, which is included under:

```text
external/seiler/
```

The framework does **not** attempt to reconstruct the actual distribution network of a municipality. The resulting networks and technology locations are synthetic benchmark representations intended for reproducible power-system studies.

---

## 2. Main Technologies

The framework currently supports:

| Technology | Spatial stock                                 | Allocation            | Electrical representation |
| ---------- | --------------------------------------------- | --------------------- | ------------------------- |
| PV         | municipality-level harmonised register stock  | residential buildings | pandapower `sgen`         |
| EV         | municipality-level estimated BEV stock        | residential buildings | pandapower `load`         |
| HP         | municipality-level estimated heating-HP stock | residential buildings | pandapower `load`         |
| BESS       | derived from allocated PV systems             | subset of PV hosts    | pandapower `storage`      |

BESS is not treated as an independently harmonised municipality stock. Instead, a configurable fraction of allocated PV systems receives a coupled battery system.

---

## 3. Repository Structure

The main repository structure is:

```text
at-lv-scenario-benchmark/
│
├── README.md
├── LICENSE
├── CITATION.cff
├── THIRD_PARTY_NOTICES.md
├── environment.yaml
│
├── configs/
│   ├── allocation/
│   │   ├── pv_status_quo.yaml
│   │   ├── ev_status_quo.yaml
│   │   ├── hp_status_quo.yaml
│   │   └── bess_status_quo.yaml
│   │
│   ├── integration/
│   │   ├── pv_pandapower.yaml
│   │   ├── ev_pandapower.yaml
│   │   ├── hp_pandapower.yaml
│   │   ├── bess_pandapower.yaml
│   │   └── status_quo_combined.yaml
│   │
│   ├── scenarios/
│   │   ├── status_quo.yaml
│   │   └── 2x_penetration.yaml
│   │
│   └── benchmarks/
│       ├── base_full_year.yaml
│       ├── status_quo_full_year.yaml
│       ├── 2x_penetration_full_year.yaml
│       ├── status_quo_winter_week.yaml
│       └── status_quo_winter_week_bess.yaml
│
├── data/
│   ├── raw/
│   └── processed/
│
├── external/
│   └── seiler/
│       ├── GeoDAQ.ipynb
│       ├── GeoGraphModel.ipynb
│       ├── GeoGridModel.ipynb
│       ├── LICENSE.txt
│       └── scripts/
│
├── harmonisation/
│   ├── harmonisation_PV/
│   ├── harmonisation_EV/
│   └── harmonisation_HP/
│
├── scripts/
│
├── src/
│   └── lv_scenario_benchmark/
│       ├── allocation/
│       ├── data_sources/
│       ├── integration/
│       ├── simulation/
│       └── visualisation/
│
└── tests/
```

Generated scenario and simulation results are written below:

```text
outputs/
```

and should normally not be committed to the repository.

---

# 4. Installation

## 4.1 Prerequisites

The recommended installation uses Conda or Miniforge.

The development environment is based on:

```text
Python 3.10.16
pandapower 3.5.4
SimBench 1.6.2
```

The complete set of direct dependencies is defined in:

```text
environment.yaml
```

---

## 4.2 Clone the Repository

```bash
git clone <repository-url>
cd at-lv-scenario-benchmark
```

Replace `<repository-url>` with the URL of this repository.

---

## 4.3 Create the Conda Environment

Run:

```bash
conda env create -f environment.yaml
```

Then activate the environment:

```bash
conda activate at-lv-scenario-benchmark
```

The first creation may take several minutes because the environment contains geospatial dependencies such as GeoPandas, OSMnx and PyProj.

---

## 4.4 Verify the Installation

Check the most important packages:

```bash
python -c "import pandapower, simbench, geopandas, osmnx, pandas; print('Environment OK')"
```

Expected output:

```text
Environment OK
```

Then run the automated tests:

```bash
pytest
```

---

# 5. Data Requirements

The complete workflow combines several public data sources.

The raw input data are separated from generated and processed files:

```text
data/
├── raw/
└── processed/
```

Some source files are intentionally not redistributed with this repository because redistribution conditions differ between data providers. Obtain these files from the original publisher and store them under the filenames expected by the configuration files and harmonisation notebooks. Always check the current licence and terms of use of the respective data provider.

The individual harmonisation directories contain additional documentation for their respective source data.

## 5.0 Data Acquisition Overview

| Input | Provider / source | How it is obtained | Local use in this repository |
| --- | --- | --- | --- |
| Austrian municipality boundaries and municipality codes (GKZ) | Statistik Austria, *Gliederung Österreichs in Gemeinden* | Download the municipality boundary dataset for the required territorial status as SHAPE-ZIP / WFS | `data/raw/gkz_polygon/` |
| Building footprints and road network | OpenStreetMap | Retrieved automatically by the adapted Seiler workflow via OSMnx / OpenStreetMap services | No permanent manual raw download required for the standard workflow |
| Building-height information | BEV, *Digitales Landschaftsmodell – Bauwerke* (`DLM_8000_BAUWERK`) | Download the free Austria-wide GeoPackage from the BEV Geoportal | `data/raw/bev/` |
| Austrian standardised load profiles / generation profiles | APCS Power Clearing and Settlement AG, *Synthetische Lastprofile* | Download the APCS load-profile archive for the benchmark year; this release uses 2025 | `data/raw/APCS_synthload_2025.csv` after extraction/preparation |
| EV and heat-pump reference profiles | SimBench | Installed with the pinned Python package; no separate manual profile download is required | Accessed through the `simbench` Python package |
| AOI polygon | User-defined input | Create from the desired study-area coordinates | `data/raw/aoi/<PROJECT>/polygon_coordinates.csv` |

The sections below provide the exact source pages and release-specific instructions.

---

## 5.1 Municipality Boundaries and GKZ

Municipality polygons are expected under:

```text
data/raw/gkz_polygon/
```

The current configuration uses the official **Statistik Austria** municipality boundary dataset with territorial status **1 January 2026**:

```text
STATISTIK_AUSTRIA_GEM_20260101.shp
STATISTIK_AUSTRIA_GEM_20260101.dbf
STATISTIK_AUSTRIA_GEM_20260101.prj
STATISTIK_AUSTRIA_GEM_20260101.shx
```

Official source and metadata:

<https://data.statistik.gv.at/web/meta.jsp?dataset=OGDEXT_GEM_1>

Direct 2026 SHAPE-ZIP download:

<https://www.statistik.gv.at/gs-open/GEODATA/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=GEODATA:STATISTIK_AUSTRIA_GEM_20260101&outputFormat=SHAPE-ZIP&format_options=CHARSET:UTF-8>

The dataset contains the municipality geometry together with the municipality identifier (`ID`, i.e. the municipality code / GKZ) and municipality name. Statistik Austria provides the data in **MGI Lambert (EPSG:31287)**.

After downloading, extract the ZIP archive and place all shapefile components in:

```text
data/raw/gkz_polygon/
```

The associated `.shp`, `.dbf`, `.prj` and `.shx` files must remain together in the same directory.

If a later territorial status is used, update the expected filename and ensure that all municipality-level input data are harmonised to the same administrative reference.

---

## 5.2 Area of Interest

Each synthetic grid requires an area of interest (AOI).

For the included workflow, AOI coordinates can be stored under:

```text
data/raw/aoi/<PROJECT>/polygon_coordinates.csv
```

where `<PROJECT>` is the project name configured in:

```text
external/seiler/scripts/parameters.py
```

The AOI defines the spatial extent used during synthetic grid generation.

Building footprints and the road network inside and around the AOI are retrieved from **OpenStreetMap** by the adapted Seiler workflow. No separate OSM export is required for the standard workflow.

OpenStreetMap:

<https://www.openstreetmap.org/>

OpenStreetMap copyright and licence information:

<https://www.openstreetmap.org/copyright>

---

## 5.3 Austrian BEV/DLM Building-Height Data

The modified grid-generation workflow can use the official Austrian **BEV Digitales Landschaftsmodell (DLM) – Bauwerke** dataset to improve building-height estimates.

Official product page:

<https://www.bev.gv.at/Services/Produkte/Digitales-Landschaftsmodell/Bauwerke.html>

BEV Geoportal / download entry point:

<https://data.bev.gv.at/>

The required product is:

```text
DLM_8000_BAUWERK
```

It is provided free of charge as an Austria-wide **GeoPackage (GPKG)**. The relevant building-polygon layer is:

```text
BWK_8100_BAUWERK_F
```

The BEV dataset contains several height attributes for the building polygons, which is why it is used as an optional height-information source in the adapted grid-generation workflow.

For the provided workflow, the downloaded GeoPackage is expected under:

```text
data/raw/bev/
```

For example, the release configuration may reference:

```text
data/raw/bev/DLM_8000_BAUWERK_20230125.gpkg
```

BEV publishes updated versions of the dataset. If a newer GeoPackage is downloaded, keep the original provider file if possible and update the corresponding input path in the project configuration/code instead of silently replacing a release-specific file.

The exact path and layer configuration are defined by the corresponding project code and configuration.

---

## 5.4 APCS Synthetic Load Profiles (2025)

Austrian standardised 15-minute load and generation profiles are obtained from **APCS Power Clearing and Settlement AG**.

Official APCS source page:

<https://www.apcs.at/clearing/technisches-clearing>

On that page, navigate to **Synthetische Lastprofile** and download **Lastprofile 2025**.

Direct archive used for the 2025 release:

<https://www.apcs.at/fileadmin/user_upload/APCS/Clearing/Lastprofile/synthload2025.zip>

The current repository configuration expects the prepared 2025 profile table as:

```text
data/raw/APCS_synthload_2025.csv
```

Therefore:

1. download the APCS 2025 load-profile archive;
2. extract the source profile file;
3. prepare/copy it using the filename expected by this repository:
   `data/raw/APCS_synthload_2025.csv`.

The APCS archive contains the Austrian standardised profiles used for small-consumer / small-generator representation. In this framework, **profile type 15 (`E1`)** is used as the temporal shape for photovoltaic generation.

The applicable Austrian market rules describe `E1` as the standardised profile for photovoltaic feed-in. The APCS source page also provides the yearly profile archives and links to the corresponding market-rule documentation.

For PV integration, the selected E1 time series is used as a **temporal shape** and is subsequently energy-normalised using the configured specific annual PV yield. It is not peak-normalised.

The same APCS source dataset is also relevant to the adapted Seiler grid-generation workflow where Austrian standard load profiles are required for conventional demand representation.

---

## 5.5 SimBench EV and Heat-Pump Profiles

EV and heat-pump demand profiles are taken from the **SimBench** benchmark dataset.

Official SimBench download page:

<https://simbench.de/en/download/>

Python package:

<https://pypi.org/project/simbench/>

Source repository:

<https://github.com/e2nIEE/simbench>

This release pins:

```text
simbench 1.6.2
```

through `environment.yaml`.

No separate SimBench profile file needs to be downloaded manually when the environment is created from `environment.yaml`, because the required dataset is distributed with the Python package.

The framework accesses rural LV reference grids and their assigned time series through the `simbench` Python API. EV charging profiles and heat-pump profiles are sampled reproducibly from these reference data.

---

# 6. Full Reproduction Workflow

The complete workflow consists of the following stages:

```text
1. Create synthetic base grid
2. Harmonise technology stocks
3. Build municipality-wide building cache
4. Allocate PV / EV / HP
5. Integrate PV / EV / HP
6. Allocate and integrate BESS
7. Run benchmark power flow
```

Each stage is described below.

---

# 7. Step 1 — Generate the Synthetic Base Grid

Synthetic LV grid generation is based on the `lv-syn-grid` workflow developed by Roman Seiler and adapted for this project.

The relevant files are located in:

```text
external/seiler/
```

## 7.1 Configure the Study Area

Open:

```text
external/seiler/scripts/parameters.py
```

and configure the desired project.

The parameter file controls, among other things:

* project name;
* study area;
* coordinate reference system;
* grid-generation parameters;
* transformer assumptions;
* building and load assumptions;
* output paths.

The selected project name is subsequently used throughout the scenario framework.

---

## 7.2 Run the Grid-Generation Notebooks

Start JupyterLab from the repository root:

```bash
jupyter lab
```

Then execute the following notebooks in order:

```text
1. external/seiler/GeoDAQ.ipynb
2. external/seiler/GeoGraphModel.ipynb
3. external/seiler/GeoGridModel.ipynb
```

### GeoDAQ

`GeoDAQ.ipynb` performs the geographic data acquisition and preprocessing, including:

* AOI loading;
* OpenStreetMap building retrieval;
* road-network retrieval;
* building processing;
* building-height processing;
* initial demand estimation.

### GeoGraphModel

`GeoGraphModel.ipynb` converts the spatial input into a graph representation and constructs the candidate LV network topology.

### GeoGridModel

`GeoGridModel.ipynb` builds the pandapower LV network and transformer structure.

The resulting base network must be available as:

```text
net.p
```

at the project location expected by the scenario configurations.

### Important

`GeoPVModel.ipynb` is **not required for this benchmark framework**.

PV systems are integrated later by the scenario framework itself. The scenario workflow therefore starts from the synthetic base grid without scenario-specific PV, EV, HP or BESS additions.

---

# 8. Step 2 — Harmonise the Technology Stocks

PV, EV and HP stocks are harmonised separately.

The resulting municipality-level datasets form the input to the scenario-allocation framework.

BESS does not have a separate municipality-level harmonisation stage.

---

## 8.1 PV Harmonisation

Directory:

```text
harmonisation/harmonisation_PV/
```

Canonical notebook:

```text
harmonisation/harmonisation_PV/notebooks/pv_register_harmonisation.ipynb
```

The workflow combines the nine Austrian federal-state E-Control PV register files with official municipality/locality information.

Run:

```bash
jupyter lab
```

and execute the notebook from top to bottom.

The main resulting municipality-level file is:

```text
harmonisation/harmonisation_PV/outputs/pv_municipality_harmonised.xlsx
```

Additional plant-level and audit outputs may also be generated.

See:

```text
harmonisation/harmonisation_PV/README.md
```

for details on input files, mapping rules and audit outputs.

---

## 8.2 EV Harmonisation

Directory:

```text
harmonisation/harmonisation_EV/
```

Canonical notebook:

```text
harmonisation/harmonisation_EV/notebooks/ev_stock_harmonisation.ipynb
```

The workflow derives municipality-level estimates for battery-electric passenger cars of vehicle class M1.

Execute the notebook from top to bottom.

The main output is:

```text
harmonisation/harmonisation_EV/outputs/ev_municipality_harmonised.xlsx
```

The municipality values are model-based estimates derived from official stock data and must not be interpreted as observed municipality-level vehicle counts.

For details, see:

```text
harmonisation/harmonisation_EV/README.md
```

---

## 8.3 Heat-Pump Harmonisation

Directory:

```text
harmonisation/harmonisation_HP/
```

Canonical notebook:

```text
harmonisation/harmonisation_HP/notebooks/hp_stock_harmonisation.ipynb
```

The workflow estimates the municipality-level stock of heating heat pumps.

Execute the notebook from top to bottom.

The main output is:

```text
harmonisation/harmonisation_HP/outputs/hp_municipality_harmonised.xlsx
```

For details on the national control total, distribution proxies and validation checks, see:

```text
harmonisation/harmonisation_HP/README.md
```

---

# 9. Step 3 — Build the Municipality Building Cache

Technology stocks are available at municipality level, while the synthetic network covers only its AOI.

To transfer municipality-level technology stocks to the AOI, the framework first determines the complete eligible building stock of each municipality touched by the AOI.

The building cache is generated from OpenStreetMap.

For the current PV configuration, run:

```bash
python scripts/build_municipality_buildings.py --config configs/allocation/pv_status_quo.yaml
```

Existing cache files are reused automatically.

To overwrite existing files and rebuild the cache:

```bash
python scripts/build_municipality_buildings.py --config configs/allocation/pv_status_quo.yaml --force
```

The generated municipality-wide building files are written to the cache directory specified in the allocation configuration.

The cache contains both the spatial building data and metadata describing the extraction.

---

# 10. Step 4 — Define a Scenario

Scenario definitions are stored under:

```text
configs/scenarios/
```

Two scenarios are included.

## 10.1 Status Quo

```text
configs/scenarios/status_quo.yaml
```

with:

```yaml
case:
  scenario_id: status_quo
  realisations: 1

penetration_factors:
  pv: 1.0
  ev: 1.0
  hp: 1.0
```

A penetration factor of `1.0` transfers the harmonised status-quo stock without additional scenario scaling.

---

## 10.2 2× Penetration

```text
configs/scenarios/2x_penetration.yaml
```

with:

```yaml
case:
  scenario_id: 2x_penetration
  realisations: 1

penetration_factors:
  pv: 2.0
  ev: 2.0
  hp: 2.0
```

The factors are applied to the harmonised municipality-level status-quo stocks before AOI transfer and allocation.

Additional scenarios can be created by adding another YAML file using the same structure.

For example:

```yaml
case:
  scenario_id: custom_scenario
  realisations: 1

penetration_factors:
  pv: 1.5
  ev: 3.0
  hp: 2.0
```

All penetration factors must be greater than zero.

---

# 11. Step 5 — Allocate and Integrate PV, EV and HP

The scenario runner performs the following sequence automatically:

```text
PV allocation
    ↓
EV allocation
    ↓
HP allocation
    ↓
combined pandapower integration
```

## Status quo

Run:

```bash
python scripts/run_benchmark_scenario.py --scenario configs/scenarios/status_quo.yaml
```

## 2× penetration

Run:

```bash
python scripts/run_benchmark_scenario.py --scenario configs/scenarios/2x_penetration.yaml
```

The runner reads the technology-specific configuration files under:

```text
configs/allocation/
```

and applies the penetration factors from the selected scenario YAML.

For a single realisation, the combined network is written using the pattern:

```text
net_<scenario_id>_combined.p
```

For example:

```text
net_status_quo_combined.p
net_2x_penetration_combined.p
```

---

# 12. Step 6 — Add PV-Coupled BESS

The recommended complete benchmark workflow includes BESS.

The BESS wrapper first runs the PV/EV/HP scenario pipeline and then:

1. selects a reproducible subset of allocated PV systems;
2. attaches BESS units to the selected PV hosts;
3. derives the battery size from the associated PV system;
4. calculates chronological battery dispatch;
5. adds the resulting storage elements to the combined pandapower network.

## 12.1 Status Quo with BESS

Run:

```bash
python scripts/run_benchmark_scenario_with_bess.py --scenario configs/scenarios/status_quo.yaml --bess-allocation-config configs/allocation/bess_status_quo.yaml --bess-integration-config configs/integration/bess_pandapower.yaml
```

## 12.2 2× Penetration with BESS

Run:

```bash
python scripts/run_benchmark_scenario_with_bess.py --scenario configs/scenarios/2x_penetration.yaml --bess-allocation-config configs/allocation/bess_status_quo.yaml --bess-integration-config configs/integration/bess_pandapower.yaml
```

The BESS allocation configuration contains the attachment-rate assumption and random seed.

The resulting network follows the naming convention:

```text
net_<scenario_id>_combined_bess.p
```

For example:

```text
net_status_quo_combined_bess.p
net_2x_penetration_combined_bess.p
```

---

## 12.3 Reuse Existing PV/EV/HP Results

If the base scenario has already been generated, it can be reused:

```bash
python scripts/run_benchmark_scenario_with_bess.py --scenario configs/scenarios/status_quo.yaml --bess-allocation-config configs/allocation/bess_status_quo.yaml --bess-integration-config configs/integration/bess_pandapower.yaml --skip-base-scenario
```

Use this option only when the corresponding allocation files and combined PV/EV/HP network already exist.

---

# 13. Electrical Representation

The technology-specific electrical models are configured under:

```text
configs/integration/
```

## 13.1 PV

PV systems are represented as pandapower static generators (`sgen`).

The default configuration uses:

```text
12 kWp nominal PV capacity per represented installation
```

The APCS E1 profile provides the temporal generation shape.

The annual profile is energy-normalised using the configured specific PV yield.

---

## 13.2 Electric Vehicles

EVs are represented as additional pandapower loads.

Charging profiles are sampled reproducibly from SimBench household charging profiles.

The implementation uses household charging profiles from rural LV reference grids.

A fixed random seed makes profile selection reproducible.

---

## 13.3 Heat Pumps

Heat pumps are represented as additional pandapower loads.

Profiles and corresponding electrical parameters are sampled from rural SimBench heat-pump reference loads.

The configured profile set includes air-source and ground-source heat-pump profiles.

---

## 13.4 Battery Storage

BESS units are represented as pandapower storage elements coupled to allocated PV systems.

The default model uses a chronological self-consumption strategy.

Battery operation therefore depends on the local residual power after accounting for:

* base demand;
* EV demand;
* heat-pump demand;
* PV generation.

The BESS model is intended as a transparent benchmark representation rather than a detailed optimisation or market-dispatch model.

---

# 14. Step 7 — Run the Time-Series Power-Flow Benchmarks

Benchmark configurations are located in:

```text
configs/benchmarks/
```

The generic simulation command is:

```bash
python scripts/run_benchmark_simulation.py --config <benchmark-config>
```

---

## 14.1 Base Grid — Full Year

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/base_full_year.yaml
```

This runs the original synthetic base grid without the added scenario technologies.

---

## 14.2 Status Quo — Full Year

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/status_quo_full_year.yaml
```

The current full-year status-quo benchmark uses the BESS-enhanced combined network.

---

## 14.3 2× Penetration — Full Year

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/2x_penetration_full_year.yaml
```

---

## 14.4 Status-Quo Winter Week

A shorter winter-week benchmark is also available:

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/status_quo_winter_week_bess.yaml
```

The configured winter window is:

```text
2025-01-15 00:00
to
2025-01-21 23:45
```

with a resolution of:

```text
15 minutes
```

---

# 15. Benchmark Configuration

A benchmark configuration defines:

```yaml
project:
  parameters: ../../external/seiler/scripts/parameters.py
  pandapower_net_filename: net.p

network:
  scenario_filename: net_status_quo_combined_bess.p

benchmark:
  id: full_year_bess
  reference_year: 2025
  time_step_minutes: 15

case:
  scenario_id: status_quo
  realisation: 0

analysis:
  start: "2025-01-01T00:00:00"
  end: "2025-12-31T23:45:00"

outputs:
  root: ../../outputs
  file_type: .csv

solver:
  continue_on_divergence: false
```

This separates the benchmark definition from the simulation implementation and allows new analysis windows or scenario networks to be added without changing Python code.

---

# 16. Outputs

Scenario results are written below:

```text
outputs/<PROJECT>/<SCENARIO>/
```

A typical scenario output contains:

```text
outputs/
└── <PROJECT>/
    └── <SCENARIO>/
        ├── allocation/
        ├── figures/
        ├── integration/
        └── powerflow/
```

## Allocation outputs

Typical allocation files include:

```text
pv_status_quo_allocation.parquet
ev_status_quo_allocation.parquet
hp_status_quo_allocation.parquet
bess_allocation.parquet
```

These files contain the reproducible technology-to-building assignments.

---

## Integration outputs

Typical integrated networks include:

```text
net_status_quo_combined.p
net_status_quo_combined_bess.p
```

The integration stage also produces technology-specific diagnostic and validation information.

---

## Power-flow outputs

The benchmark runner stores time-series result tables for quantities such as:

* bus voltage magnitude;
* line loading;
* transformer loading;
* active power;
* reactive power;
* upstream-grid exchange.

All benchmark time series use the common configured time axis.

---

# 17. Reproducibility

Reproducibility is a central design goal of the framework.

The following mechanisms are used:

### Fixed random seeds

Stochastic allocations and profile assignments use configurable deterministic seeds.

Repeated runs with unchanged:

* input data;
* project configuration;
* scenario configuration;
* software environment;

therefore produce reproducible results.

### Explicit scenario configuration

Scenario assumptions are stored in YAML files rather than being hidden in Python source code.

### Common time axis

PV, EV, HP, BESS and the benchmark runner use a common reference time axis.

The current benchmark reference year is:

```text
2025
```

with:

```text
15-minute resolution
```

### Immutable base grid

Scenario technologies are added to copies of the synthetic base grid.

The original:

```text
net.p
```

is not overwritten by technology integration.

### Audit outputs

The harmonisation and allocation workflows generate intermediate and audit outputs that allow municipality totals and assignments to be checked independently.

---

# 18. Running the Tests

Run the complete test suite from the repository root:

```bash
pytest
```

The tests cover, among other things:

* PV allocation;
* EV allocation;
* HP allocation;
* BESS allocation and dispatch;
* PV pandapower integration;
* EV pandapower integration;
* HP pandapower integration;
* combined scenario integration;
* benchmark scenario generation;
* benchmark simulation behaviour.

A clean public release should pass the complete test suite in a newly created environment.

---

# 19. Adding a New Study Area

To use the framework for another Austrian municipality or study area:

1. define a new AOI;
2. configure the new project in `external/seiler/scripts/parameters.py`;
3. generate the synthetic LV base network using the Seiler notebooks;
4. ensure the corresponding `net.p` exists;
5. build the municipality-wide building cache;
6. reuse the national harmonised PV, EV and HP datasets;
7. run the desired scenario;
8. integrate BESS if required;
9. run the benchmark simulation.

The harmonised national technology datasets do not need to be regenerated simply because a new AOI is selected, provided that the underlying source-data version and administrative reference remain unchanged.

---

# 20. Adding a New Scenario

Create another file under:

```text
configs/scenarios/
```

using:

```yaml
case:
  scenario_id: example
  realisations: 1

penetration_factors:
  pv: 1.0
  ev: 1.0
  hp: 1.0
```

Then run:

```bash
python scripts/run_benchmark_scenario_with_bess.py --scenario configs/scenarios/example.yaml --bess-allocation-config configs/allocation/bess_status_quo.yaml --bess-integration-config configs/integration/bess_pandapower.yaml
```

A corresponding benchmark YAML can then be created under:

```text
configs/benchmarks/
```

to define the simulation period and scenario network.

---

# 21. Methodological Limitations

The framework deliberately prioritises transparency and reproducibility. Several limitations should therefore be considered when interpreting its outputs.

## Synthetic network

The LV network is synthetic.

It is not intended to reproduce the exact topology, equipment or operating state of the real distribution network in the selected municipality.

---

## Municipality-level technology stocks

The harmonised technology datasets have different underlying data quality and spatial resolution.

PV is derived from plant-register information, whereas municipality-level EV and HP values require additional disaggregation or allocation assumptions.

The resulting municipality-level quantities should therefore be interpreted as scenario inputs rather than perfect observations of local technology stocks.

---

## Building-level allocation

No dataset identifies the actual building connections of all PV systems, EVs or heat pumps.

Building-level technology placement is therefore synthetic.

An allocated technology at a particular building must not be interpreted as evidence that the real building hosts that technology.

---

## PV system size

A fixed nominal PV system size is used for electrical representation.

The framework therefore preserves the scenario's number and spatial distribution of represented PV installations but does not reproduce the actual capacity of every individual installation.

---

## Temporal profiles

PV, EV and heat-pump profiles are representative profiles rather than measured time series from the selected case-study area.

Consequently, individual time-step results represent benchmark operating conditions and should not be interpreted as reconstructed historical operation.

---

## Battery storage

BESS deployment is derived from PV allocation using a national attachment-rate assumption.

It is not an observed municipality-level BESS stock.

The implemented dispatch strategy represents PV self-consumption and is not intended to reproduce every possible household, market or grid-support operating strategy.

---

## Power-flow interpretation

The framework supports numerical consistency checks and physical plausibility assessment.

Without measured voltage, loading and power-flow time series from the actual distribution network, the generated operational time series cannot be validated against the real network on a time-step-by-time-step basis.

---

# 22. Third-Party Code

Synthetic LV grid generation builds on:

**Roman Seiler — `lv-syn-grid`**

Repository:

https://github.com/lemonraiser/lv-syn-grid

The included third-party code is located under:

```text
external/seiler/
```

The original MIT licence is retained under:

```text
external/seiler/LICENSE.txt
```

The version included in this repository contains modifications made for this framework.

Further information is provided in:

```text
THIRD_PARTY_NOTICES.md
```

If the Seiler grid-generation code is used in scientific work, please also cite the associated work listed in:

```text
external/seiler/CITATION.cff
```

---

# 23. Citation

If you use this framework in academic work, please cite the associated master's thesis and/or software release.

Machine-readable citation metadata are provided in:

```text
CITATION.cff
```

GitHub can use this file to display the repository's **Cite this repository** function.

When the synthetic grid-generation component is used, the underlying Seiler work should be cited separately as described above.

---

# 24. Licence

The original code developed for this repository is released under the MIT License.

See:

```text
LICENSE
```

Third-party components remain subject to their respective licences.

See:

```text
THIRD_PARTY_NOTICES.md
```

for details.

---

# 25. Quick Start

For users who already have:

* the harmonised PV/EV/HP datasets;
* a generated synthetic `net.p`;
* the required raw profile and municipality files;

the complete status-quo benchmark can be created with the following commands.

## Create environment

```bash
conda env create -f environment.yaml
conda activate at-lv-scenario-benchmark
```

## Run tests

```bash
pytest
```

## Build municipality building cache

```bash
python scripts/build_municipality_buildings.py --config configs/allocation/pv_status_quo.yaml
```

## Generate status-quo scenario including BESS

```bash
python scripts/run_benchmark_scenario_with_bess.py --scenario configs/scenarios/status_quo.yaml --bess-allocation-config configs/allocation/bess_status_quo.yaml --bess-integration-config configs/integration/bess_pandapower.yaml
```

## Run base-grid full-year benchmark

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/base_full_year.yaml
```

## Run status-quo full-year benchmark

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/status_quo_full_year.yaml
```

## Generate 2× penetration scenario including BESS

```bash
python scripts/run_benchmark_scenario_with_bess.py --scenario configs/scenarios/2x_penetration.yaml --bess-allocation-config configs/allocation/bess_status_quo.yaml --bess-integration-config configs/integration/bess_pandapower.yaml
```

## Run 2× full-year benchmark

```bash
python scripts/run_benchmark_simulation.py --config configs/benchmarks/2x_penetration_full_year.yaml
```

This produces the complete sequence:

```text
Base Grid
   │
   ├──► Base full-year benchmark
   │
   ├──► Status quo
   │       ├── PV
   │       ├── EV
   │       ├── HP
   │       └── BESS
   │            └──► Status-quo full-year benchmark
   │
   └──► 2× penetration
           ├── PV
           ├── EV
           ├── HP
           └── BESS
                └──► 2× full-year benchmark
```

---

## Acknowledgements

This project was developed at TU Wien within the scope of a master's thesis on open-data-based benchmark generation for Austrian low-voltage distribution grids.

The synthetic LV grid-generation approach builds on the work of Roman Seiler. See `THIRD_PARTY_NOTICES.md` and `external/seiler/CITATION.cff` for details.
