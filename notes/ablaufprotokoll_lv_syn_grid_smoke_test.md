# Ablaufprotokoll: Erster erfolgreicher Durchlauf von `lv-syn-grid`

## 1. Ziel des Durchlaufs

Ziel dieses Durchlaufs war ein technischer Smoke-Test der Baseline-Pipeline von Seilers Projekt. Es sollte geprüft werden, ob die Kernmodule vollständig auf dem lokalen Windows-/Conda-Setup lauffähig sind.

Die erfolgreich getestete Pipeline war:

```text
GeoDAQ -> GeoGraphModel -> GeoGridModel -> pandapower-Zeitreihensimulation
```

PV wurde bewusst noch nicht integriert, weil dafür zusätzliche Eingangsdaten benötigt werden und zuerst die Baseline ohne PV stabil funktionieren sollte.

---

## 2. Arbeitsverzeichnis

Gearbeitet wurde im Projektordner:

```powershell
C:\Users\friha\TU Wien\Diplomarbeit\code\at-lv-scenario-benchmark\external\lv-syn-grid
```

---

## 3. Conda-Umgebungen erstellen

### Ausgeführt

```powershell
conda env create -f lv_env.yml
conda env create -f pv_env.yml
```

### Erklärung

- `lv_env.yml` erzeugt die Python-Umgebung für die Hauptpipeline: OSM-Daten, GeoPandas, Graphmodell, pandapower-Netzmodell und Simulation.
- `pv_env.yml` erzeugt eine separate Umgebung für die PV-Modellierung mit `pvlib`.
- Für diesen ersten Baseline-Durchlauf wurde praktisch nur `lv_env` verwendet.

### Ergebnis

Die beiden Umgebungen wurden erfolgreich erstellt:

```text
lv_env
pv_env
```

---

## 4. `lv_env` aktivieren und Jupyter-Kernel registrieren

### Ausgeführt

```powershell
conda activate lv_env
python -m ipykernel install --user --name lv_env --display-name "Python (lv_env)"
```

### Erklärung

- `conda activate lv_env` aktiviert die für die Hauptpipeline benötigte Python-Umgebung.
- `python -m ipykernel install ...` registriert diese Umgebung als Jupyter-Kernel.
- Dadurch kann in JupyterLab direkt der Kernel `Python (lv_env)` ausgewählt werden.

### Ergebnis

Der Kernel wurde erfolgreich registriert und stand anschließend in JupyterLab zur Auswahl.

---

## 5. JupyterLab installieren und starten

### Ausgeführt

```powershell
conda install -c conda-forge jupyterlab -y
jupyter lab
```

### Erklärung

- `conda install -c conda-forge jupyterlab -y` installiert JupyterLab in der aktiven Umgebung `lv_env`.
- `jupyter lab` startet die Notebook-Oberfläche im Browser.

### Ergebnis

JupyterLab wurde gestartet. In den Notebooks wurde der Kernel ausgewählt:

```text
Python (lv_env)
```

---

## 6. Projektparameter setzen

### Datei

```text
scripts/parameters.py
```

### Änderung

Für den Smoke-Test wurde das Projekt auf `Test` gesetzt:

```python
PROJECT = 'Test'
```

Dadurch werden alle erzeugten Daten unter diesem Projektordner abgelegt:

```text
grids/Test/
```

### Wirkung im Code

Aus `PROJECT` werden im Projekt mehrere Pfade abgeleitet, zum Beispiel:

```python
FILEPATH_DATA = 'grids/' + PROJECT + '/data/'
FILEPATH_LV_GRID = 'grids/' + PROJECT + '/lvgrid/'
FILEPATH_PLOTS = 'grids/' + PROJECT + '/plots/'
FILEPATH_SIMRES = 'grids/' + PROJECT + '/simresults/'
```

Damit schreiben `GeoDAQ`, `GeoGraphModel` und `GeoGridModel` ihre Daten konsistent in denselben Projektordner.

### Temporäre Smoke-Test-Anpassung

Für das kleine Testgebiet wurde zusätzlich empfohlen, die Transformatorleistung temporär kleiner zu setzen:

```python
POWER_TRANSFORMER = 50
```

### Erklärung

Die Trafo-Schätzung basiert auf der abgeschätzten Gesamtlast. Bei einem kleinen Testpolygon kann eine kleinere angenommene Transformatorleistung dazu führen, dass der Algorithmus mehrere Transformatorcluster erzeugt. Das macht den Smoke-Test robuster.

Für wissenschaftliche Läufe sollte dieser Wert später wieder fachlich begründet gesetzt werden.

---

## 7. Test-Lastprofile erzeugen

### Neue Datei

```text
tools/create_smoke_test_inputs.py
```

### Zweck

Das Projekt erwartet eine Excel-Datei mit Standardlastprofilen:

```text
grids/Test/data/synthload2025.xlsx
```

Für den Smoke-Test wurde diese Datei künstlich erzeugt, damit die Zeitreihenpipeline technisch getestet werden konnte.

### Code

```python
from pathlib import Path
import numpy as np
import pandas as pd

project = "Test"
out_dir = Path("grids") / project / "data"
out_dir.mkdir(parents=True, exist_ok=True)

ts = pd.date_range("2025-01-01 00:00:00", "2025-12-31 23:45:00", freq="15min")

hour = ts.hour.to_numpy() + ts.minute.to_numpy() / 60.0
day_of_year = ts.dayofyear.to_numpy()

morning_peak = np.exp(-0.5 * ((hour - 7.0) / 1.8) ** 2)
evening_peak = np.exp(-0.5 * ((hour - 19.0) / 2.3) ** 2)
midday_peak = np.exp(-0.5 * ((hour - 13.0) / 3.0) ** 2)
night_base = 0.35 * np.ones_like(hour)

season = 1.0 + 0.15 * np.cos(2 * np.pi * (day_of_year - 15) / 365.0)

def normalize_to_1000_kwh(shape):
    shape = np.maximum(shape, 0.001)
    profile = shape * season
    return profile / profile.sum() * 1000.0

df = pd.DataFrame({"ts": ts})

df["H0"] = normalize_to_1000_kwh(night_base + 0.8 * morning_peak + 1.2 * evening_peak)
df["G0"] = normalize_to_1000_kwh(0.3 + 0.9 * midday_peak)
df["G1"] = normalize_to_1000_kwh(np.where((hour >= 8) & (hour <= 18), 1.0, 0.15))
df["G2"] = normalize_to_1000_kwh(0.2 + 1.2 * evening_peak)
df["G3"] = normalize_to_1000_kwh(0.8 + 0.2 * midday_peak)
df["G6"] = normalize_to_1000_kwh(0.4 + 0.7 * midday_peak)

file = out_dir / "synthload2025.xlsx"
df.to_excel(file, index=False)

print(f"created: {file}")
print(df.head())
```

### Erklärung des Codes

- `Path("grids") / project / "data"` baut den erwarteten Datenordner für das Projekt `Test`.
- `mkdir(parents=True, exist_ok=True)` legt den Ordner an, falls er noch nicht existiert.
- `pd.date_range(..., freq="15min")` erzeugt einen Zeitindex für das gesamte Jahr 2025 in 15-Minuten-Auflösung.
- `morning_peak`, `evening_peak` und `midday_peak` erzeugen einfache künstliche Tagesverläufe.
- `season` erzeugt eine einfache saisonale Gewichtung.
- `normalize_to_1000_kwh()` normiert jedes Profil auf 1000 kWh Jahresenergie.
- Die Spalten `H0`, `G0`, `G1`, `G2`, `G3`, `G6` entsprechen den vom Projekt erwarteten Standardlastprofilen.
- Die Datei wird als Excel-Datei gespeichert, weil die Projektfunktionen `pd.read_excel(...)` verwenden.

### Ausgeführt

```powershell
python tools\create_smoke_test_inputs.py
```

### Ergebnis

Erzeugt wurde:

```text
grids/Test/data/synthload2025.xlsx
```

---

## 8. `GeoDAQ.ipynb` ausführen

### Datei

```text
GeoDAQ.ipynb
```

### Rolle von `GeoDAQ`

`GeoDAQ` ist das Datenakquisitions- und Vorverarbeitungsmodul. Es lädt OSM-Daten, extrahiert Straßen und Gebäude, schätzt Gebäudelasten, positioniert synthetische Transformatoren und exportiert die Daten für die nächsten Module.

---

### 8.1 Imports und Klasse ausführen

### Ausgeführt

```text
Imports
class DataAcquisitionInfrastructure
daqinfra = DataAcquisitionInfrastructure()
daqinfra.load_synthetic_profiles()
```

### Erklärung

- Die Import-Zelle lädt Bibliotheken wie GeoPandas, OSMnx, Shapely, NumPy, Pandas und die Projektparameter.
- Die Klassenzelle definiert alle Methoden für Datenakquisition, Lastabschätzung, Trafo-Positionierung und Export.
- `daqinfra = DataAcquisitionInfrastructure()` erzeugt ein Objekt, das intern GeoDataFrames für Straßen, Gebäude, Knoten, Leitungen und Transformatoren verwaltet.
- `load_synthetic_profiles()` lädt `synthload2025.xlsx`, konvertiert die Spalte `ts` zu Zeitstempeln, filtert den Zeitraum aus `parameters.py` und behält die erwarteten SLP-Spalten.

---

### 8.2 Polygon direkt im Notebook setzen

### Datei

```text
GeoDAQ.ipynb
```

### Geänderte Zelle

Die originale Polygon-Ladezelle wurde für den Smoke-Test durch ein direkt definiertes Testpolygon ersetzt:

```python
from shapely.geometry import Polygon

polygon = Polygon([
    (14.9250, 48.6380),
    (14.9520, 48.6380),
    (14.9520, 48.6600),
    (14.9250, 48.6600),
    (14.9250, 48.6380),
])

daqinfra.extract_streets_from_polygon(
    polygon,
    prm.TAGS_STREETS
)

daqinfra.extract_buildings_from_polygon(
    polygon,
    prm.TAGS_NONRESIDENTIAL_BUILDINGS,
    prm.TAGS_RESIDENTIAL_BUILDINGS
)

print("streets:", len(daqinfra.get_streets()))
print("buildings:", len(daqinfra.get_buildings()))
```

### Erklärung

- Das Originalprojekt erwartet normalerweise eine externe Datei `polygon_coordinates.csv`.
- Für den Smoke-Test wurde stattdessen ein kleines Testpolygon direkt im Notebook definiert.
- Die Koordinaten sind in WGS84 angegeben, also `(longitude, latitude)`.
- `extract_streets_from_polygon(...)` ruft über OSMnx Straßenobjekte innerhalb des Polygons ab.
- `extract_buildings_from_polygon(...)` ruft Wohn- und Nichtwohngebäude innerhalb des Polygons ab.
- Die `print(...)`-Ausgaben prüfen, ob tatsächlich Straßen und Gebäude gefunden wurden.

### Wirkung der Methoden

`extract_streets_from_polygon()`:

- lädt OSM-Straßengeometrien innerhalb des Polygons,
- schneidet Geometrien auf das Polygon zu,
- projiziert die Daten nach `EPSG:9273`, damit Längen metrisch berechnet werden können,
- berechnet Straßenlängen,
- behält die relevanten Spalten.

`extract_buildings_from_polygon()`:

- lädt Wohngebäude und Nichtwohngebäude,
- kombiniert beide Datensätze,
- erzeugt eindeutige Gebäude-IDs wie `BD000001`,
- berechnet Gebäudeschwerpunkte (`centroid`),
- berechnet Gebäudegrundflächen (`area`).

---

### 8.3 Gebäudehöhen künstlich setzen

### Datei

```text
GeoDAQ.ipynb
```

### Geänderte Zelle

Die originale Höhenverarbeitungszelle wurde für den Smoke-Test durch künstliche Höhenwerte ersetzt:

```python
b = daqinfra.get_buildings()

b["surface"] = 310.0
b["sea_level"] = 300.0
b["height"] = 10.0
b["floors"] = 3

print(b[["id", "area", "height", "floors"]].head())
print("buildings with test heights:", len(b))
```

### Erklärung

- `daqinfra.get_buildings()` gibt den internen Gebäude-GeoDataFrame zurück.
- `surface` und `sea_level` ersetzen die Höhenwerte, die im Originalworkflow aus externen Höhendaten kommen würden.
- `height = 10.0` setzt für alle Gebäude eine künstliche Gebäudehöhe von 10 m.
- `floors = 3` setzt für alle Gebäude drei Stockwerke.
- Diese Werte sind nur für den technischen Smoke-Test gedacht, weil die folgende Lastabschätzung Gebäudehöhen bzw. Stockwerkszahlen benötigt.

### Hinweis für spätere Läufe

Für wissenschaftliche Läufe muss dieser Schritt durch echte oder nachvollziehbar abgeleitete Gebäudehöhendaten ersetzt werden, z. B. durch BEV-DLM, NÖ-Atlas oder eine andere belastbare Höhenquelle.

---

### 8.4 Lastabschätzung, Knotenzuordnung und Linienextraktion

### Datei

```text
GeoDAQ.ipynb
```

### Ausgeführt

```python
daqinfra.load_estimation()
_ = daqinfra.assign_buildings_to_nodes()
_ = daqinfra.extract_lines()
```

### Erklärung `load_estimation()`

Diese Funktion schätzt die elektrische Last je Gebäude.

Sie macht unter anderem:

- setzt Standardwerte für Gebäudetyp, SLP und Energiebedarf,
- berechnet die Gesamtfläche als `area * floors`,
- unterscheidet grob zwischen Einfamilienhaus, Mehrparteienhaus und Nichtwohngebäude,
- ordnet passende Standardlastprofile zu,
- berechnet Energiebedarf und Spitzenleistung `p_peak`,
- filtert Ausreißer.

Die künstlich gesetzten `floors` gehen direkt in diese Berechnung ein.

### Erklärung `assign_buildings_to_nodes()`

Diese Funktion verbindet Gebäude mit dem Straßennetz:

- extrahiert alle OSM-Straßenknoten,
- berechnet für jedes Gebäude den Abstand zu jedem Straßenknoten,
- ordnet jedes Gebäude dem nächstgelegenen Straßenknoten zu,
- speichert diese Beziehung im Knoten-GeoDataFrame.

Das ist wichtig, weil Gebäude später als Lastknoten in den Netzgraphen eingebunden werden müssen.

### Erklärung `extract_lines()`

Diese Funktion zerlegt Straßenzüge in einzelne Leitungssegmente:

- geht alle Straßen-LineStrings durch,
- erzeugt zwischen aufeinanderfolgenden OSM-Knoten jeweils ein Segment,
- speichert Startknoten, Endknoten, Geometrie und IDs,
- erzeugt Leitungs-IDs wie `LI000001`.

Diese Linien werden später als mögliche Leitungsführung des Niederspannungsnetzes verwendet.

---

### 8.5 Synthetische Transformatoren schätzen

### Datei

```text
GeoDAQ.ipynb
```

### Ausgeführt

```python
tr_syn_gdf, model_opt, X = daqinfra.estimate_synthetic_transformers()
```

### Erklärung

Diese Funktion positioniert synthetische Transformatoren über K-Means-Clustering.

Sie macht im Kern:

- nimmt Gebäudekoordinaten und Gebäudelasten als Eingang,
- testet verschiedene Clusteranzahlen,
- bewertet die Clusterung über Silhouette-Scores,
- wählt eine geeignete Clusteranzahl,
- berechnet pro Cluster eine synthetische Trafoposition,
- weist jedem synthetischen Trafo eine Bemessungsleistung zu.

### Ergebnis

Die Zelle lief erfolgreich durch und erzeugte synthetische Transformatoren für das Testgebiet.

---

### 8.6 Transformatoren Straßenknoten zuordnen

### Datei

```text
GeoDAQ.ipynb
```

### Ausgeführt

```python
daqinfra.assign_transformers_to_nodes()
```

### Erklärung

Analog zu den Gebäuden werden auch die synthetischen Transformatoren dem nächstgelegenen Straßenknoten zugeordnet.

Das ist notwendig, damit die Transformatoren im späteren Netzgraphen an konkrete Knoten im Straßennetz angebunden werden können.

---

### 8.7 GeoDAQ-Daten exportieren

### Datei

```text
GeoDAQ.ipynb
```

### Ausgeführt

```python
daqinfra.export_data()
```

### Erklärung

Diese Funktion exportiert die vorbereiteten GeoDataFrames als Parquet-Dateien.

### Ergebnisdateien

```text
grids/Test/data/buildings.parquet
grids/Test/data/streets.parquet
grids/Test/data/nodes.parquet
grids/Test/data/lines.parquet
grids/Test/data/transformers.parquet
```

### Bedeutung

Diese Dateien sind der Übergabepunkt von `GeoDAQ` zu `GeoGraphModel`.

---

## 9. `GeoGraphModel.ipynb` ausführen

### Datei

```text
GeoGraphModel.ipynb
```

### Rolle von `GeoGraphModel`

`GeoGraphModel` liest die von `GeoDAQ` erzeugten Parquet-Dateien ein und erzeugt daraus ein Graphmodell des Niederspannungsnetzes. Danach wird ein Minimum Spanning Tree berechnet und in Teilnetze partitioniert.

---

### 9.1 Imports, Klasse und Objekt ausführen

### Ausgeführt

```text
Imports
class GeoGraphModel
ggm = GeoGraphModel()
```

### Erklärung

Beim Erzeugen von `ggm` werden die exportierten Daten geladen:

```text
buildings.parquet
streets.parquet
nodes.parquet
lines.parquet
transformers.parquet
```

Diese bilden die Datengrundlage für das Graphmodell.

---

### 9.2 Graph-Erzeugungszelle ändern und ausführen

### Datei

```text
GeoGraphModel.ipynb
```

### Geänderte Zelle

Die Graph-Erzeugungszelle wurde für den ersten Lauf so gesetzt:

```python
ggm.create_G_lv()
ggm.create_H_lv()
ggm.create_H_sg_lv()
ggm.rework_H_s_lv()
```

### Erklärung `create_G_lv()`

- erstellt den vollständigen Niederspannungs-Netzgraphen aus Straßen, Gebäuden und Transformatoren,
- verbindet Gebäude- und Trafoknoten mit den zuvor zugeordneten Straßenknoten,
- erzeugt den Ausgangsgraphen `G_lv`.

### Erklärung `create_H_lv()`

- wendet den Minimum-Spanning-Tree-Algorithmus auf `G_lv` an,
- erzeugt daraus einen radialen Graphen `H_lv`,
- entfernt Schleifen und behält eine minimale zusammenhängende Struktur.

### Erklärung `create_H_sg_lv()`

- partitioniert den MST in zusammenhängende Teilnetze,
- ordnet Teilgraphen den synthetischen Transformatoren zu,
- erzeugt die Subgraphenstruktur `H_s_lv`.

### Erklärung `rework_H_s_lv()`

- trennt die Teilnetze sauber,
- passt die Transformatorleistungen an die Lasten der jeweiligen Teilnetze an,
- bereitet die Teilnetze für das pandapower-Modell vor.

---

### 9.3 Graphen plotten

### Datei

```text
GeoGraphModel.ipynb
```

### Ausgeführt

```python
ggm.plot_G_lv()
ggm.plot_H_lv()
ggm.plot_H_s_lv()
```

### Erklärung

- `plot_G_lv()` zeigt den vollständigen Netzgraphen.
- `plot_H_lv()` zeigt den Minimum-Spanning-Tree.
- `plot_H_s_lv()` zeigt die partitionierten Teilnetze.

Diese Plots dienen zur visuellen Plausibilitätskontrolle.

---

### 9.4 Graphen speichern

### Datei

```text
GeoGraphModel.ipynb
```

### Ausgeführt

```python
ggm.save_graph_model()
```

### Ergebnisdateien

```text
grids/Test/data/G_lv.gml
grids/Test/data/H_lv.gml
grids/Test/data/H_s_lv.pkl
```

### Erklärung

- `G_lv.gml`: vollständiger Graph.
- `H_lv.gml`: radialer Minimum-Spanning-Tree.
- `H_s_lv.pkl`: partitionierte Teilnetze als Python-Pickle.

`H_s_lv.pkl` ist besonders wichtig, weil `GeoGridModel` daraus das pandapower-Netz erstellt.

---

### 9.5 Graphplots speichern

### Datei

```text
GeoGraphModel.ipynb
```

### Ausgeführt

```python
ggm.save_fig_G_lv(filename='G_lv')
ggm.save_fig_H_lv(filename='H_lv')
ggm.save_fig_H_s_lv(filename='H_s_lv')
```

### Ergebnisdateien

```text
grids/Test/plots/G_lv.png
grids/Test/plots/H_lv.png
grids/Test/plots/H_s_lv.png
```

---

## 10. `GeoGridModel.ipynb` ausführen

### Datei

```text
GeoGridModel.ipynb
```

### Rolle von `GeoGridModel`

`GeoGridModel` erzeugt aus den partitionierten Graph-Teilnetzen ein pandapower-Netzmodell, importiert Lastprofile, erstellt Zeitreihen-Controller, führt die Lastflussrechnung aus und speichert Simulationsergebnisse.

---

### 10.1 Imports, Parameter, Klasse und Objekt ausführen

### Ausgeführt

```text
Imports
FILE_LOAD_PROFILES / LP_T_START / LP_T_END
class GeoGridModel
grm = GeoGridModel()
```

### Erklärung

- Die Parameterzelle definiert die Lastprofildatei und den Simulationszeitraum.
- `grm = GeoGridModel()` lädt die zuvor erzeugten Parquet-Dateien sowie `H_s_lv.pkl`.
- Das Objekt enthält danach Gebäude, Straßen, Linien, Transformatoren und die partitionierten Teilnetze.

---

### 10.2 pandapower-Netz erzeugen

### Datei

```text
GeoGridModel.ipynb
```

### Ausgeführt

```python
grm.create_power_grid()
```

### Erklärung

Diese Funktion erstellt das elektrische Netzmodell.

Sie macht im Kern:

- erzeugt Transformator-Typen und Trafoelemente,
- erzeugt Niederspannungs-Busse aus den Graphknoten,
- erzeugt Leitungen aus den Graphkanten,
- erzeugt Lasten an Gebäudebussen,
- setzt Geokoordinaten für Busse und Leitungen,
- setzt die Geokoordinate des übergeordneten HV-Busses auf den Mittelpunkt des Netzes.

Nach diesem Schritt existiert intern ein pandapower-Netz in:

```python
grm.get_net()
```

---

### 10.3 Netz prüfen

### Datei

```text
GeoGridModel.ipynb
```

### Neue Prüfzelle

```python
net = grm.get_net()

print("buses:", len(net.bus))
print("lines:", len(net.line))
print("loads:", len(net.load))
print("trafos:", len(net.trafo))

display(net.bus.head())
display(net.line.head())
display(net.load.head())
display(net.trafo.head())
```

### Zweck

Damit wurde geprüft, ob das pandapower-Netz tatsächlich elektrische Elemente enthält.

Erwartet wurde:

```text
buses > 0
lines > 0
loads > 0
trafos > 0
```

Diese Prüfung war erfolgreich.

---

### 10.4 Lastprofile importieren und Lastzeitreihen berechnen

### Datei

```text
GeoGridModel.ipynb
```

### Ausgeführt

```python
grm.import_load_profiles()
grm.calculate_load_timeseries()
#grm.implement_pv_systems()
grm.create_controller()
grm.create_output_writer()
```

### Erklärung `import_load_profiles()`

- liest `grids/Test/data/synthload2025.xlsx`,
- konvertiert `ts` in Zeitstempel,
- filtert den Zeitraum zwischen `LP_T_START` und `LP_T_END`,
- behält nur die SLP-Spalten `H0`, `G0`, `G1`, `G2`, `G3`, `G6`,
- speichert die Anzahl der Zeitschritte.

### Erklärung `calculate_load_timeseries()`

Für jede Last im pandapower-Netz:

- wird die Gebäude-ID aus `net.load.name` gelesen,
- wird der jährliche Energiebedarf des Gebäudes aus `buildings.parquet` geholt,
- wird das zugehörige SLP gelesen,
- wird daraus ein Leistungsprofil in MW berechnet,
- alle Gebäudeprofile werden zu einem DataFrame kombiniert.

Die Umrechnung nutzt die 15-Minuten-Auflösung:

```text
p_kw = SLP-Wert * Jahresenergie / 1000 / 0.25
```

Danach wird in MW umgerechnet.

### Warum PV auskommentiert blieb

```python
#grm.implement_pv_systems()
```

PV wurde noch nicht verwendet, weil für diesen Schritt zusätzliche PV-Daten nötig sind, insbesondere:

```text
grids/Test/data/pv_systems.csv
```

### Erklärung `create_controller()`

Diese Funktion erstellt pandapower-Zeitreihencontroller:

- einen Controller für das externe Netz,
- einen Controller für die Lasten,
- optional einen Controller für PV-Anlagen, falls PV-Zeitreihen vorhanden wären.

Der Lastcontroller schreibt pro Zeitschritt neue `p_mw`-Werte in die pandapower-Lasten.

### Erklärung `create_output_writer()`

Diese Funktion definiert, welche Simulationsergebnisse gespeichert werden:

- Busspannungen `res_bus.vm_pu`,
- Leitungsauslastungen `res_line.loading_percent`,
- Transformatorauslastungen `res_trafo.loading_percent`.

Die Ergebnisse werden als Excel-Dateien in `grids/Test/simresults/` gespeichert.

---

### 10.5 Lastzeitreihen prüfen

### Datei

```text
GeoGridModel.ipynb
```

### Neue Prüfzelle

```python
load_ts = grm.get_load_time_series()

print(load_ts.shape)
display(load_ts.head())
display(load_ts.describe())
```

### Zweck

Damit wurde geprüft, ob die Lastzeitreihen korrekt erzeugt wurden.

Bei einem Tag in 15-Minuten-Auflösung werden 96 Zeitschritte erwartet:

```text
(96, Anzahl_der_Loads)
```

Diese Prüfung war erfolgreich.

---

### 10.6 Netz speichern

### Datei

```text
GeoGridModel.ipynb
```

### Ausgeführt

```python
grm.save_net('net')
```

### Ergebnisdatei

```text
grids/Test/lvgrid/net.p
```

### Erklärung

Das pandapower-Netz wird als Pickle-Datei gespeichert und kann später erneut geladen werden, ohne den gesamten vorherigen Prozess neu auszuführen.

---

### 10.7 Zeitreihensimulation ausführen

### Datei

```text
GeoGridModel.ipynb
```

### Ausgeführt

```python
grm.run_simulation()
```

### Erklärung

Diese Funktion startet die pandapower-Zeitreihensimulation:

```python
timeseries.run_timeseries(self.__net, time_steps=list(range(self.__n_ts)))
```

Für jeden Zeitschritt wird eine Lastflussrechnung durchgeführt. Die Controller aktualisieren die Lasten, danach berechnet pandapower Spannungen und Betriebsmittelauslastungen.

### Ergebnis

Die Simulation lief vollständig durch.

---

### 10.8 Simulationsergebnisse erzeugen

### Ergebnisordner

```text
grids/Test/simresults/
```

### Ergebnisdateien

```text
grids/Test/simresults/res_bus/vm_pu.xlsx
grids/Test/simresults/res_line/loading_percent.xlsx
grids/Test/simresults/res_trafo/loading_percent.xlsx
```

### Bedeutung

- `vm_pu.xlsx`: Spannungen an den Bussen in per unit.
- `loading_percent.xlsx` in `res_line`: Leitungsauslastungen in Prozent.
- `loading_percent.xlsx` in `res_trafo`: Transformatorauslastungen in Prozent.

---

### 10.9 Ergebnisse einlesen und Netzbelastung plotten

### Datei

```text
GeoGridModel.ipynb
```

### Ausgeführt

```python
grm.read_sim_results()
grm.plot_grid_loading_osm()
```

### Erklärung `read_sim_results()`

Diese Funktion liest die gespeicherten Excel-Dateien wieder ein:

- Transformatorauslastung,
- Leitungsauslastung,
- Busspannungen.

Danach werden Zeitindizes mit 15-Minuten-Auflösung gesetzt.

### Erklärung `plot_grid_loading_osm()`

Diese Funktion erzeugt eine geografische Darstellung der Netzbelastung auf OSM-Basis.

Sie verwendet:

- das pandapower-Netz,
- die Leitungsauslastungen,
- die Busspannungen,
- die Straßengeometrien.

---

### 10.10 Plot speichern

### Datei

```text
GeoGridModel.ipynb
```

### Ausgeführt

```python
grm.save_fig_grid_loading(filename='grid_loading')
```

### Ergebnisdateien

```text
grids/Test/plots/grid_loading.png
grids/Test/plots/grid_loading.svg
```

---

## 11. Gesamtergebnis des Durchlaufs

Die vollständige Baseline-Pipeline lief erfolgreich durch:

```text
GeoDAQ
  -> OSM-Daten extrahiert
  -> Gebäude verarbeitet
  -> künstliche Gebäudehöhen gesetzt
  -> Lasten abgeschätzt
  -> synthetische Transformatoren positioniert
  -> Parquet-Dateien exportiert

GeoGraphModel
  -> vollständigen Graphen G_lv erzeugt
  -> Minimum-Spanning-Tree H_lv erzeugt
  -> Teilnetze H_s_lv erzeugt
  -> Graphdateien und Plots gespeichert

GeoGridModel
  -> pandapower-Netz erzeugt
  -> Lastprofile importiert
  -> Lastzeitreihen berechnet
  -> Controller und OutputWriter erzeugt
  -> Zeitreihen-Lastflussrechnung ausgeführt
  -> Ergebnisse gespeichert
  -> Netzbelastungsplot erzeugt
```

---

## 12. Erzeugte Dateien

### Eingangsdaten für Smoke-Test

```text
grids/Test/data/synthload2025.xlsx
```

### GeoDAQ-Ausgaben

```text
grids/Test/data/buildings.parquet
grids/Test/data/streets.parquet
grids/Test/data/nodes.parquet
grids/Test/data/lines.parquet
grids/Test/data/transformers.parquet
```

### GeoGraphModel-Ausgaben

```text
grids/Test/data/G_lv.gml
grids/Test/data/H_lv.gml
grids/Test/data/H_s_lv.pkl
```

### Graphplots

```text
grids/Test/plots/G_lv.png
grids/Test/plots/H_lv.png
grids/Test/plots/H_s_lv.png
```

### pandapower-Netz

```text
grids/Test/lvgrid/net.p
```

### Simulationsergebnisse

```text
grids/Test/simresults/res_bus/vm_pu.xlsx
grids/Test/simresults/res_line/loading_percent.xlsx
grids/Test/simresults/res_trafo/loading_percent.xlsx
```

### Netzbelastungsplot

```text
grids/Test/plots/grid_loading.png
grids/Test/plots/grid_loading.svg
```

---

## 13. Temporäre Smoke-Test-Vereinfachungen

Für diesen ersten Durchlauf wurden mehrere Vereinfachungen gemacht:

1. Das Polygon wurde direkt im Notebook definiert statt über `polygon_coordinates.csv` geladen.
2. Gebäudehöhen wurden künstlich gesetzt statt aus externen Höhendaten bestimmt.
3. Die Lastprofile wurden künstlich erzeugt statt echte APCS-/SLP-Daten zu verwenden.
4. PV wurde bewusst deaktiviert.
5. Optional wurde `POWER_TRANSFORMER` kleiner gesetzt, um den kleinen Testfall stabiler zu machen.

Diese Vereinfachungen sind für einen technischen Smoke-Test sinnvoll, aber nicht ausreichend für den finalen wissenschaftlichen Benchmark.

---

## 14. Nächste sinnvolle Schritte

Für die weitere Masterarbeit sollte der Smoke-Test schrittweise durch realistischere Daten ersetzt werden:

1. echtes Untersuchungsgebiet sauber über Polygondatei oder GeoJSON definieren,
2. echte oder nachvollziehbar abgeleitete Gebäudehöhen einbinden,
3. echte Standardlastprofile bzw. sauber dokumentierte synthetische Profile verwenden,
4. Parameter in `scripts/parameters.py` fachlich begründen,
5. PV/EV/WP/BESS-Szenarien als eigene Erweiterung auf die Baseline-Pipeline aufsetzen,
6. Ergebnisse quantitativ auswerten: Spannungsband, Leitungsauslastung, Trafoauslastung, kritische Zeitschritte.

---

## 15. Wichtigste Erkenntnis

Die Grundpipeline des Seiler-Projekts funktioniert auf dem lokalen Windows-/Conda-Setup. Der erfolgreiche Durchlauf bestätigt, dass die technische Basis für die weitere Szenario- und Benchmark-Arbeit vorhanden ist.
