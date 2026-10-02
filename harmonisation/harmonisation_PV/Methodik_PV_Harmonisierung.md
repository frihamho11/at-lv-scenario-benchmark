# Methodik_PV_Harmonisierung

## 1. Zweck und Abgrenzung

- Ziel der PV-Harmonisierung ist die Erzeugung eines reproduzierbaren, österreichweit einheitlichen Datensatzes zur regionalen Verteilung von Photovoltaikanlagen, der anschließend als Eingangsdatenbasis für:
  - Status-quo-Szenarien,
  - räumliche Allokation auf Gebäude bzw. Netzanschlusspunkte,
  - Integration in synthetische österreichische Niederspannungsnetze,
  - und zeitabhängige Lastflussberechnungen
  verwendet werden kann.

- Die Harmonisierung bildet **nicht den gesamten österreichischen PV-Anlagenbestand unabhängig von der Netzebene** ab.

- Der für die Masterarbeit relevante Scope umfasst PV-Anlagen, die plausibel dem **Niederspannungsnetz (Netzebene 7)** zugeordnet werden können.

- Die Harmonisierung selbst endet auf Gemeindeebene.
  - Zukunftsszenarien,
  - Gebäudeallokation,
  - elektrische Integration in pandapower,
  - Standardprofile,
  - und Power-Flow-Simulation
  sind nachgelagerte Schritte und werden methodisch getrennt behandelt.

---

## 2. Datenbasis

### 2.1 E-Control Anlagenregister

- Verwendet werden die neun bundeslandspezifischen Anlagenregister-Dateien von E-Control:
  - Burgenland,
  - Kärnten,
  - Niederösterreich,
  - Oberösterreich,
  - Salzburg,
  - Steiermark,
  - Tirol,
  - Vorarlberg,
  - Wien.

- Relevante Quellspalten:
  - `ID`
    - dateiinterne Register-ID,
    - nur zur Rückverfolgbarkeit verwendet,
    - nicht als österreichweit eindeutige Anlagen-ID interpretiert.
  - `Plz`
    - Postleitzahl zur räumlichen Zuordnung.
  - `Ort`
    - Orts-, Ortschafts- oder Gemeindebezeichnung zur räumlichen Zuordnung.
  - `Bundesland`
    - Bundeslandangabe der Quelldatei.
  - `Technologie`
    - zur Auswahl der Photovoltaikanlagen.
  - `Engpassleistung (kW <sub>el</sub>)`
    - installierte Engpassleistung der Stromerzeugungsanlage in kW.

- Die Registerdateien werden als gemeinsamer Daten-Snapshot behandelt.
  - `REFERENCE_DATE` dokumentiert den verwendeten Download-/Bearbeitungsstand.
  - Der Wert ist **kein Inbetriebnahmedatum einzelner Anlagen**.

### 2.2 Statistik Austria Ortsliste

- Die offizielle Statistik-Austria-Ortsliste wird als administrative Referenz verwendet.

- Verwendete Attribute:
  - Gemeindekennziffer (GKZ),
  - Gemeindename,
  - Ortschaftskennziffer,
  - Ortschaftsname,
  - Postleitzahl.

- Ziel ist eine eindeutige Zuordnung der Registerzeilen zu einer politischen Gemeinde.

- Die fünfstellige GKZ wird als kanonischer Gemeinde-Identifier verwendet.

### 2.3 Wien

- In der für den Workflow verwendeten Ortsliste fehlen die Wiener Gemeindedaten in der sonst verwendeten Form.

- Wien wird daher programmgesteuert ergänzt als:
  - `municipality_id = 90001`
  - `municipality_name = Wien`
  - `federal_state_code = W`

- Die Roh-Ortsliste wird nicht manuell verändert.

---

## 3. Gesetzliche Abgrenzung des Niederspannungs-Scope

### 3.1 Netzebene 7

- Das österreichische **Elektrizitätswirtschaftsgesetz (ElWG), BGBl. I Nr. 91/2025**, definiert in § 106 Abs. 1 Z 7:
  - **Netzebene 7 = Niederspannung mit 1 kV und darunter.**

- Damit entspricht Netzebene 7 dem Spannungsbereich, der in dieser Masterarbeit durch die synthetischen Niederspannungsnetze modelliert wird.

### 3.2 Gesetzliche Zuordnung anhand der netzwirksamen Leistung

- § 97 Abs. 1 ElWG legt den Netzanschlusspunkt grundsätzlich anhand der **netzwirksamen Leistung** fest.

- Die gesetzlichen Größenklassen sind:
  - bis einschließlich **100 kW netzwirksame Leistung**:
    - Netzebene 7,
  - mehr als 100 kW bis einschließlich 400 kW:
    - Netzebene 6,
  - mehr als 400 kW bis einschließlich 5.000 kW:
    - Netzebene 5,
  - mehr als 5.000 kW bis einschließlich 200 MW:
    - Netzebene 4 oder 3.

- Für den hier betrachteten Niederspannungs-Scope ist daher die gesetzliche Referenzgrenze:
  - **100 kW netzwirksame Leistung.**

### 3.3 Gesetzliche Ausnahmen

- Die Größenklassen des § 97 Abs. 1 dürfen nicht als ausnahmslose physikalische Klassifikation jeder existierenden Anlage interpretiert werden.

- § 97 Abs. 3 ElWG erlaubt eine von den Größenklassen abweichende Festlegung des Netzanschlusspunktes:
  - wenn dies aus technischen Gründen zwingend erforderlich ist,
  - oder wenn Anschlusswerber und Netzbetreiber dies einvernehmlich vereinbaren.

- Die 100-kW-Grenze wird daher in dieser Arbeit als **gesetzliche Regelzuordnung** für Netzebene 7 verwendet, nicht als Beweis für den tatsächlichen Netzanschlusspunkt jeder einzelnen Registeranlage.

---

## 4. Engpassleistung und netzwirksame Leistung

### 4.1 Engpassleistung

- Das ElWG definiert in § 6 Z 105 die **Maximalkapazität (Engpassleistung)** als die maximale kontinuierliche Wirkleistung, die eine Stromerzeugungsanlage erzeugen kann, abzüglich des ausschließlich für den Eigenbetrieb der Stromerzeugungsanlage benötigten Anteils.

- Vereinfacht beschreibt die Engpassleistung:
  - die maximale Erzeugungsleistung der Anlage selbst.

- Das E-Control Anlagenregister stellt für die betrachteten PV-Anlagen diese Engpassleistung bereit.

### 4.2 Netzwirksame Leistung

- § 6 Z 117 ElWG definiert die **netzwirksame Leistung** als die im Vertrag über Netzanschluss und Netzzugang vereinbarte maximale Leistung in Einspeise- oder Bezugsrichtung am Netzanschlusspunkt.

- Dabei werden insbesondere berücksichtigt:
  - die gesamte Anordnung der Anlage,
  - Stromerzeugung,
  - Verbrauch,
  - Energiespeicher,
  - Regelung,
  - und das Betriebskonzept.

- Vereinfacht beschreibt die netzwirksame Leistung:
  - die maximale Leistung, die am Netzanschlusspunkt gegenüber dem öffentlichen Netz wirksam werden darf.

### 4.3 Konsequenz für die Harmonisierung

- Für die gesetzliche Netzebenenzuordnung ist die **netzwirksame Leistung** relevant.

- Der verwendete E-Control-Datensatz enthält jedoch die **Engpassleistung** und keine vertraglich vereinbarte netzwirksame Leistung.

- Deshalb kann mit dem Anlagenregister der tatsächliche Netzanschlusspunkt einzelner Anlagen **nicht exakt rekonstruiert** werden.

- Eine Anlage kann beispielsweise:
  - eine Engpassleistung von mehr als 100 kW besitzen,
  - ihre Einspeisung aber durch Eigenverbrauch, Speicher, Regelung oder vertragliche Begrenzung auf höchstens 100 kW netzwirksame Leistung beschränken.

- Umgekehrt ermöglicht § 97 Abs. 3 in begründeten Fällen eine abweichende Netzebenzuordnung.

- § 101 Abs. 2 ElWG zeigt zusätzlich ausdrücklich, dass bei Photovoltaikanlagen eine Begrenzung der netzwirksamen Leistung vorgesehen sein kann.

---

## 5. Methodische Entscheidung zur LV-Abgrenzung

### 5.1 Proxy-Regel

- Da die netzwirksame Leistung im E-Control Anlagenregister nicht verfügbar ist, wird die Engpassleistung als **konservativer Proxy** verwendet.

- Für den LV-orientierten PV-Datensatz gilt:

```text
0 kW < Engpassleistung <= 100 kW
    -> im harmonisierten LV-PV-Datensatz enthalten

Engpassleistung > 100 kW
    -> aus dem LV-PV-Datensatz ausgeschlossen

Engpassleistung fehlt oder <= 0 kW
    -> ungültige bzw. nicht klassifizierbare Kapazitätsangabe;
       nicht in die finale LV-Aggregation übernommen
```

- Die Grenze von **100 kW wird einschließlich 100 kW** angewendet.

### 5.2 Interpretation

- Die Regel bedeutet ausdrücklich **nicht**:
  - dass jede Anlage mit Engpassleistung <= 100 kW nachweislich an Netzebene 7 angeschlossen ist;
  - oder dass jede Anlage mit Engpassleistung > 100 kW nachweislich oberhalb von Netzebene 7 angeschlossen ist.

- Die Regel bedeutet:
  - Anlagen mit einer Engpassleistung von maximal 100 kW liegen bereits ohne zusätzliche Annahme über Einspeisebegrenzungen innerhalb der gesetzlichen Größenklasse für Netzebene 7.
  - Anlagen über 100 kW werden konservativ ausgeschlossen, weil mit den vorhandenen Daten nicht nachgewiesen werden kann, dass ihre netzwirksame Leistung trotzdem höchstens 100 kW beträgt.

### 5.3 Erwarteter Fehler des Proxys

- Der Filter minimiert offensichtlich ungeeignete Zuordnungen sehr großer Anlagen zum synthetischen LV-Netz.

- Mögliche **False Negatives**:
  - Anlagen mit Engpassleistung > 100 kW,
  - aber tatsächlich auf <= 100 kW begrenzter netzwirksamer Leistung,
  - werden ausgeschlossen.

- Mögliche **abweichende reale Anschlussfälle**:
  - Anlagen <= 100 kW können aufgrund § 97 Abs. 3 ElWG technisch oder vertraglich abweichend angeschlossen sein.

- Diese Unsicherheit wird als Datenlimitierung dokumentiert und nicht durch unbelegte Annahmen korrigiert.

---

## 6. Gesamtworkflow der Harmonisierung

### Schritt 1 – Quelldateien einlesen

- Alle neun bundeslandspezifischen Registerdateien werden eingelesen.
- Das erwartete Spaltenschema wird geprüft.
- Fehlende Pflichtspalten führen zu einem Abbruch.
- Die Quelldatei und ursprüngliche Zeilennummer werden für die Auditierbarkeit gespeichert.

### Schritt 2 – Technologieauswahl

- Der Technologieeintrag wird deterministisch normalisiert.

- Aktuell akzeptierter Wert:

```python
PV_TECHNOLOGY_VALUES = {
    "photovoltaik",
}
```

- Andere solarähnliche Technologiebezeichnungen werden nicht still verworfen.
- Sie werden separat in `excluded_solar_like` dokumentiert.

### Schritt 3 – Engpassleistung parsen

- Die Quellspalte `Engpassleistung (kW <sub>el</sub>)` wird in numerische kW-Werte überführt.

- Der Parser berücksichtigt:
  - numerische Excel-Zellen,
  - deutsches Dezimalkomma,
  - Dezimalpunkt,
  - gemischte Tausender- und Dezimaltrennzeichen,
  - Leerzeichen,
  - geschützte Leerzeichen.

- Es findet keine stille Schätzung oder Ersetzung fehlender Kapazitätswerte statt.

### Schritt 4 – LV-Scope filtern

- Nach der numerischen Kapazitätskonvertierung wird jede PV-Registerzeile genau einer Scope-Kategorie zugeordnet:

```text
included_lv_proxy
excluded_above_100kw
invalid_capacity
```

- `included_lv_proxy`:
  - numerische Engpassleistung,
  - größer als 0 kW,
  - kleiner oder gleich 100 kW.

- `excluded_above_100kw`:
  - numerische Engpassleistung > 100 kW.

- `invalid_capacity`:
  - fehlende oder nicht numerisch interpretierbare Kapazität,
  - Engpassleistung <= 0 kW.

- Nur `included_lv_proxy` wird anschließend für die Gemeindezuordnung und die finale Gemeindeaggregation verwendet.

- Ausgeschlossene Zeilen bleiben als Audit-Daten erhalten.

### Schritt 5 – Administrative Referenz aufbauen

- Die Statistik-Austria-Ortsliste wird standardisiert.
- Mehrfach-Postleitzahlen werden auf einzelne Lookup-Zeilen expandiert.
- Es wird eine vollständige Gemeindereferenz mit 2.092 österreichischen Gemeinden erzeugt.
- Wien wird kontrolliert ergänzt.
- Die GKZ wird als kanonischer Schlüssel verwendet.

### Schritt 6 – Ortsnamen normalisieren

- Register- und Referenznamen werden mit derselben deterministischen Funktion normalisiert.

- Verarbeitung unter anderem:
  - Unicode-Normalisierung,
  - Kleinschreibung,
  - Normalisierung deutscher Sonderzeichen,
  - Entfernung vorangestellter Postleitzahlen im Ortsfeld,
  - Expansion häufiger österreichischer Abkürzungen,
  - Vereinheitlichung von Trennzeichen,
  - Entfernung weiterer Satzzeichen,
  - Zusammenführen mehrfacher Leerzeichen.

- Beispiele:

```text
St. Magdalena -> sankt magdalena
a.d.Thaya     -> an der thaya
a.m.See       -> am see
```

- Es wird kein undokumentiertes Fuzzy Matching eingesetzt.

### Schritt 7 – Eindeutige Lookup-Tabellen erzeugen

- Es werden nur Lookup-Schlüssel verwendet, die eindeutig genau einer Gemeinde zugeordnet werden können.

- Verwendete Lookup-Typen:
  - Bundesland + PLZ + Ortschaft,
  - Bundesland + PLZ + Gemeinde,
  - national PLZ + Ortschaft,
  - national PLZ + Gemeinde,
  - Bundesland + eindeutiger Ortschaftsname,
  - Bundesland + eindeutiger Gemeindename,
  - Bundesland + eindeutige PLZ.

### Schritt 8 – Gemeindezuordnung

- Jede in-scope PV-Zeile wird anhand einer festen Priorität verarbeitet.

| Priorität | Regel | `derivation_method` |
|---:|---|---|
| 1 | Wien-Datei und Wiener PLZ bzw. exakter Name `Wien` | `vienna_postcode_or_name` |
| 2 | Bundesland + PLZ + exakter Ortschaftsname | `exact_locality_name_postcode` |
| 3 | Bundesland + PLZ + exakter Gemeindename | `exact_municipality_name_postcode` |
| 4 | National: PLZ + exakter Ortschaftsname | `exact_national_locality_name_postcode` |
| 5 | National: PLZ + exakter Gemeindename | `exact_national_municipality_name_postcode` |
| 6 | Eindeutiger Ortschaftsname im Bundesland und PLZ kompatibel/fehlend | `exact_unique_locality_name_postcode_compatible` |
| 7 | Eindeutiger Gemeindename im Bundesland und PLZ kompatibel/fehlend | `exact_unique_municipality_name_postcode_compatible` |
| 8 | Im Bundesland eindeutige PLZ | `unique_postcode` |
| 9 | keine Regel erfolgreich | `unresolved` |

- Die erste erfolgreiche Regel bestimmt die Zuordnung.

### Schritt 9 – Konflikte transparent markieren

- Name-PLZ-Widersprüche werden als:

```text
mapping_issue = name_postcode_conflict
```

  gespeichert.

- Ein späterer eindeutiger PLZ-Fallback darf den Datensatz trotzdem zuordnen.
- Das Konfliktflag bleibt dabei erhalten.

- Bundeslandübergreifende Korrekturen über eindeutige nationale PLZ-Namens-Kombinationen werden als:

```text
cross_state_assignment = True
```

  markiert.

### Schritt 10 – Gemeindeaggregation

- Nur:
  - im LV-Proxy-Scope enthaltene,
  - und erfolgreich einer Gemeinde zugeordnete
  PV-Zeilen werden aggregiert.

- Für Gemeinde `m` und Referenzdatum `t`:

```text
unit_count(m,t)
    = Anzahl der enthaltenen und gemappten PV-Registerzeilen
```

```text
installed_capacity_kw(m,t)
    = Summe ihrer Engpassleistungen
```

- `unit_count` ist damit:
  - keine unabhängig verifizierte Anzahl physisch eindeutiger Anlagen,
  - sondern die Anzahl der verwendeten Registerzeilen.

- Die dateiinterne `ID` wird nicht zur bundeslandübergreifenden Deduplizierung verwendet.

### Schritt 11 – Vollständiges Gemeinderaster

- Die Aggregation wird per Left Join auf die vollständige Liste aller 2.092 Gemeinden übertragen.

- Gemeinden ohne enthaltene und gemappte PV-Zeile erhalten:

```text
unit_count = 0
installed_capacity_kw = 0.0
derivation_method = not_applicable
```

---

## 7. Ausschlussstatistik

### 7.1 Zweck

- Der 100-kW-Filter darf nicht als stiller Datenverlust umgesetzt werden.

- Deshalb wird automatisch dokumentiert:
  - wie viele PV-Zeilen vor der LV-Abgrenzung vorlagen,
  - wie viele Zeilen im LV-Proxy-Scope verbleiben,
  - wie viele Anlagen aufgrund `Engpassleistung > 100 kW` ausgeschlossen werden,
  - wie viel Engpassleistung diese ausgeschlossenen Anlagen repräsentieren,
  - wie viele Zeilen wegen fehlender bzw. nicht positiver Kapazität nicht klassifizierbar sind.

### 7.2 Auswertung je Bundesland

Für jedes Quellbundesland werden mindestens folgende Kennzahlen ausgegeben:

```text
pv_rows_before_lv_scope_filter
lv_proxy_rows
excluded_above_100kw_rows
invalid_capacity_rows

positive_capacity_kw_before_lv_scope_filter
lv_proxy_capacity_kw
excluded_above_100kw_capacity_kw

lv_proxy_unit_share
lv_proxy_capacity_share
```

### 7.3 Österreichweite Zusammenfassung

- Zusätzlich wird eine österreichweite Gesamtsumme erzeugt.

- Die Statistik soll insbesondere beantworten:
  - Welcher Anteil der PV-Registerzeilen wird für das LV-Modell verwendet?
  - Welcher Anteil der im Register enthaltenen positiven Engpassleistung bleibt nach dem LV-Scope-Filter?
  - Wie groß ist der durch die Scope-Abgrenzung bewusst entfernte Anlagenbestand?

### 7.4 Audit-Tabelle der ausgeschlossenen Anlagen

- Alle Anlagen mit:

```text
Engpassleistung > 100 kW
```

  werden in einer separaten Review-Tabelle gespeichert.

- Empfohlener Excel-Sheetname:

```text
excluded_above_100kw
```

- Zu speichernde Spalten mindestens:
  - `source_file`
  - `source_row_number`
  - `source_register_id`
  - `Plz`
  - `Ort`
  - `Bundesland`
  - `Technologie`
  - `capacity_raw`
  - `installed_capacity_kw`
  - `lv_scope_status`
  - `lv_scope_reason`

### 7.5 Keine erfundenen Snapshot-Zahlen

- Die bisher dokumentierten Snapshot-Kennzahlen wurden **vor Einführung des 100-kW-LV-Filters** erzeugt.

- Nach Änderung der Pipeline müssen:
  - `unit_count`,
  - `installed_capacity_kw`,
  - Mapping-Raten,
  - Bundeslandberichte,
  - und nationale Summen
  neu berechnet werden.

- Die neuen Ausschlusszahlen sind erst nach erneutem Lauf mit den neun Original-Registerdateien belastbar.

---

## 8. Empfohlene konkrete Codeänderungen im bestehenden Notebook

Die folgenden Änderungen beziehen sich auf den bestehenden Workflow `pv_register_harmonisation_ortsliste_revised.ipynb`.

### 8.1 Konfiguration ergänzen

In der Konfigurationszelle ergänzen:

```python
# Conservative proxy for PV installations relevant to LV grid level 7.
# Legal reference: ElWG § 97(1) uses net-effective power <= 100 kW.
# The E-Control register provides bottleneck capacity instead, therefore
# this threshold is applied as a documented proxy rather than an exact
# reconstruction of the actual connection voltage level.
LV_PROXY_MAX_BOTTLENECK_CAPACITY_KW = 100.0
```

### 8.2 Sammellisten vor dem Register-Loop ergänzen

```python
register_frames = []
register_report_rows = []
technology_summary_frames = []
excluded_solar_like_frames = []

excluded_above_lv_capacity_frames = []
invalid_capacity_frames = []
```

### 8.3 Scope-Klassifikation nach dem Kapazitätsparsing

Direkt nach:

```python
register["installed_capacity_kw"] = (
    register[CAPACITY_COLUMN].map(parse_capacity_kw)
)
register["reference_date"] = REFERENCE_DATE
```

ergänzen:

```python
capacity = register["installed_capacity_kw"]

invalid_capacity_mask = (
    capacity.isna()
    | capacity.le(0)
)

excluded_above_lv_capacity_mask = (
    capacity.gt(LV_PROXY_MAX_BOTTLENECK_CAPACITY_KW)
)

included_lv_proxy_mask = (
    capacity.gt(0)
    & capacity.le(LV_PROXY_MAX_BOTTLENECK_CAPACITY_KW)
)

assert (
    invalid_capacity_mask
    | excluded_above_lv_capacity_mask
    | included_lv_proxy_mask
).all()

assert not (
    invalid_capacity_mask & excluded_above_lv_capacity_mask
).any()

assert not (
    invalid_capacity_mask & included_lv_proxy_mask
).any()

assert not (
    excluded_above_lv_capacity_mask & included_lv_proxy_mask
).any()
```

### 8.4 Ausgeschlossene Zeilen auditierbar speichern

```python
invalid_capacity = register[
    invalid_capacity_mask
].copy()

invalid_capacity["lv_scope_status"] = "invalid_capacity"
invalid_capacity["lv_scope_reason"] = (
    "missing_or_non_positive_bottleneck_capacity"
)

if not invalid_capacity.empty:
    invalid_capacity_frames.append(invalid_capacity)


excluded_above_lv_capacity = register[
    excluded_above_lv_capacity_mask
].copy()

excluded_above_lv_capacity["lv_scope_status"] = (
    "excluded_above_100kw"
)
excluded_above_lv_capacity["lv_scope_reason"] = (
    "bottleneck_capacity_above_lv_proxy_threshold"
)

if not excluded_above_lv_capacity.empty:
    excluded_above_lv_capacity_frames.append(
        excluded_above_lv_capacity
    )
```

### 8.5 Source-Report um Scope-Kennzahlen erweitern

Vor dem eigentlichen Filtern:

```python
positive_capacity_mask = capacity.gt(0)

register_report_rows.append(
    {
        "source_file": path.name,
        "source_federal_state_code": expected_state_code,
        "raw_rows": len(register_raw),

        "pv_rows_before_lv_scope_filter": len(register),
        "lv_proxy_rows": int(included_lv_proxy_mask.sum()),
        "excluded_above_100kw_rows": int(
            excluded_above_lv_capacity_mask.sum()
        ),
        "invalid_capacity_rows": int(
            invalid_capacity_mask.sum()
        ),

        "positive_capacity_kw_before_lv_scope_filter": (
            capacity.loc[positive_capacity_mask]
            .sum(min_count=1)
        ),
        "lv_proxy_capacity_kw": (
            capacity.loc[included_lv_proxy_mask]
            .sum(min_count=1)
        ),
        "excluded_above_100kw_capacity_kw": (
            capacity.loc[excluded_above_lv_capacity_mask]
            .sum(min_count=1)
        ),

        "excluded_solar_like_rows": len(excluded_solar_like),
        "missing_postcode": register["postcode"].isna().sum(),
        "missing_place_name": (
            register["place_name_normalized"].isna().sum()
        ),
        "missing_capacity": capacity.isna().sum(),
        "non_positive_capacity": capacity.le(0).sum(),
    }
)
```

Danach erst:

```python
register = register[
    included_lv_proxy_mask
].copy()

register["lv_scope_status"] = "included_lv_proxy"
register["lv_scope_reason"] = (
    "positive_bottleneck_capacity_at_or_below_100kw"
)

register_frames.append(register)
```

### 8.6 Nach dem Loop Audit-Tabellen zusammensetzen

```python
if excluded_above_lv_capacity_frames:
    excluded_above_lv_capacity_rows = pd.concat(
        excluded_above_lv_capacity_frames,
        ignore_index=True,
        sort=False,
    )
else:
    excluded_above_lv_capacity_rows = pd.DataFrame()


if invalid_capacity_frames:
    invalid_capacity_rows = pd.concat(
        invalid_capacity_frames,
        ignore_index=True,
        sort=False,
    )
else:
    invalid_capacity_rows = pd.DataFrame()
```

### 8.7 LV-Scope-Statistik erzeugen

```python
register_report["lv_proxy_unit_share"] = (
    register_report["lv_proxy_rows"]
    / register_report["pv_rows_before_lv_scope_filter"]
)

register_report["lv_proxy_capacity_share"] = (
    register_report["lv_proxy_capacity_kw"]
    / register_report[
        "positive_capacity_kw_before_lv_scope_filter"
    ]
)

lv_scope_summary = pd.DataFrame(
    [
        {
            "scope": "Austria",
            "pv_rows_before_lv_scope_filter": int(
                register_report[
                    "pv_rows_before_lv_scope_filter"
                ].sum()
            ),
            "lv_proxy_rows": int(
                register_report["lv_proxy_rows"].sum()
            ),
            "excluded_above_100kw_rows": int(
                register_report[
                    "excluded_above_100kw_rows"
                ].sum()
            ),
            "invalid_capacity_rows": int(
                register_report[
                    "invalid_capacity_rows"
                ].sum()
            ),
            "positive_capacity_kw_before_lv_scope_filter": (
                register_report[
                    "positive_capacity_kw_before_lv_scope_filter"
                ].sum()
            ),
            "lv_proxy_capacity_kw": (
                register_report[
                    "lv_proxy_capacity_kw"
                ].sum()
            ),
            "excluded_above_100kw_capacity_kw": (
                register_report[
                    "excluded_above_100kw_capacity_kw"
                ].sum()
            ),
        }
    ]
)

lv_scope_summary["lv_proxy_unit_share"] = (
    lv_scope_summary["lv_proxy_rows"]
    / lv_scope_summary["pv_rows_before_lv_scope_filter"]
)

lv_scope_summary["lv_proxy_capacity_share"] = (
    lv_scope_summary["lv_proxy_capacity_kw"]
    / lv_scope_summary[
        "positive_capacity_kw_before_lv_scope_filter"
    ]
)
```

### 8.8 Zusätzliche Validierungen

Zusätzlich zu den bestehenden Prüfungen:

```python
scope_rows_expected = int(
    register_report[
        "pv_rows_before_lv_scope_filter"
    ].sum()
)

scope_rows_actual = int(
    register_report["lv_proxy_rows"].sum()
    + register_report["excluded_above_100kw_rows"].sum()
    + register_report["invalid_capacity_rows"].sum()
)

positive_capacity_expected = (
    register_report[
        "positive_capacity_kw_before_lv_scope_filter"
    ].sum()
)

positive_capacity_actual = (
    register_report["lv_proxy_capacity_kw"].sum()
    + register_report[
        "excluded_above_100kw_capacity_kw"
    ].sum()
)

scope_validation_rows = pd.DataFrame(
    [
        {
            "check": "lv_scope_row_partition",
            "expected": scope_rows_expected,
            "actual": scope_rows_actual,
            "passed": scope_rows_expected == scope_rows_actual,
        },
        {
            "check": "lv_scope_positive_capacity_partition",
            "expected": positive_capacity_expected,
            "actual": positive_capacity_actual,
            "passed": np.isclose(
                positive_capacity_expected,
                positive_capacity_actual,
                rtol=0,
                atol=0.01,
            ),
        },
        {
            "check": "included_capacity_max_100kw",
            "expected": True,
            "actual": bool(
                mapped_units["installed_capacity_kw"]
                .le(LV_PROXY_MAX_BOTTLENECK_CAPACITY_KW)
                .all()
            ),
            "passed": bool(
                mapped_units["installed_capacity_kw"]
                .le(LV_PROXY_MAX_BOTTLENECK_CAPACITY_KW)
                .all()
            ),
        },
        {
            "check": "included_capacity_positive",
            "expected": True,
            "actual": bool(
                mapped_units["installed_capacity_kw"]
                .gt(0)
                .all()
            ),
            "passed": bool(
                mapped_units["installed_capacity_kw"]
                .gt(0)
                .all()
            ),
        },
    ]
)

validation_report = pd.concat(
    [
        validation_report,
        scope_validation_rows,
    ],
    ignore_index=True,
)
```

### 8.9 Export erweitern

Im Excel-Export ergänzen:

```python
lv_scope_summary.to_excel(
    writer,
    sheet_name="lv_scope_summary",
    index=False,
)

if not excluded_above_lv_capacity_rows.empty:
    excluded_above_lv_capacity_rows.to_excel(
        writer,
        sheet_name="excluded_above_100kw",
        index=False,
    )

if not invalid_capacity_rows.empty:
    invalid_capacity_rows.to_excel(
        writer,
        sheet_name="invalid_capacity",
        index=False,
    )
```

- Die bisherige Erzeugung von `invalid_capacity` aus `mapped_units` entfällt, weil ungültige Kapazitätszeilen nun bewusst **vor** der Gemeindezuordnung aus dem verwendeten LV-Datensatz entfernt und separat auditiert werden.

### 8.10 Final Summary erweitern

```python
summary = lv_scope_summary.iloc[0]

print(
    "PV rows before LV scope filter:",
    int(summary["pv_rows_before_lv_scope_filter"]),
)

print(
    "PV rows included in LV proxy:",
    int(summary["lv_proxy_rows"]),
)

print(
    "PV rows excluded above 100 kW:",
    int(summary["excluded_above_100kw_rows"]),
)

print(
    "Rows with invalid capacity:",
    int(summary["invalid_capacity_rows"]),
)

print(
    "LV proxy unit share:",
    f"{summary['lv_proxy_unit_share']:.2%}",
)

print(
    "LV proxy capacity share:",
    f"{summary['lv_proxy_capacity_share']:.2%}",
)

print(
    "Excluded capacity above 100 kW [MW]:",
    f"{summary['excluded_above_100kw_capacity_kw'] / 1000:.3f}",
)
```

---

## 9. Outputdateien nach der Änderung

### `pv_municipality_harmonised.xlsx`

Empfohlene Sheets:

| Sheet | Inhalt |
|---|---|
| `pv_by_municipality` | finaler LV-orientierter Gemeindedatensatz |
| `lv_scope_summary` | österreichweite Statistik des 100-kW-Filters |
| `source_report` | Scope- und Parsing-Statistik je Bundesland |
| `state_mapping_report` | Mapping-Erfolg der nach dem Scope-Filter verbleibenden PV-Zeilen |
| `mapping_summary` | Verteilung der Gemeinde-Mappingmethoden |
| `unresolved_top_places` | größte nicht auflösbare Orts-/PLZ-Gruppen |
| `unresolved_units` | alle in-scope, aber nicht räumlich aufgelösten Zeilen |
| `invalid_capacity` | PV-Zeilen mit fehlender/nicht positiver Kapazität |
| `excluded_above_100kw` | aufgrund des LV-Scope ausgeschlossene PV-Zeilen |
| `technology_summary` | vollständige Technologieverteilung der Quellen |
| `excluded_solar_like` | solarähnliche, aber nicht als PV akzeptierte Technologieeinträge |
| `validation` | automatisierte Konsistenzprüfungen |

### `pv_plants_harmonised.parquet`

- Enthält nur PV-Zeilen, die:
  - den Technologie-Filter bestehen,
  - eine gültige positive Engpassleistung besitzen,
  - `Engpassleistung <= 100 kW` erfüllen,
  - und anschließend durch den räumlichen Mapping-Workflow verarbeitet wurden.

- Empfohlene zusätzliche Felder:

```text
lv_scope_status
lv_scope_reason
```

---

## 10. Validierung

Nach jedem vollständigen Lauf sind mindestens folgende Prüfungen erforderlich:

- Gemeinde-Master:
  - exakt 2.092 Gemeinden,
  - eindeutige GKZ.

- LV-Scope:
  - jede PV-Zeile vor der Scope-Abgrenzung ist genau einer der drei Kategorien zugeordnet;
  - keine enthaltene Anlage hat `installed_capacity_kw > 100`;
  - keine enthaltene Anlage hat `installed_capacity_kw <= 0`;
  - Summe der positiven Kapazitäten vor dem Filter entspricht:
    - enthaltener Kapazität
    - plus Kapazität der Anlagen > 100 kW.

- Räumliches Mapping:
  - Summe der Gemeinde-`unit_count` entspricht der Anzahl räumlich aufgelöster in-scope Registerzeilen;
  - aggregierte Kapazität entspricht der Kapazität der räumlich aufgelösten in-scope Registerzeilen;
  - jede aufgelöste GKZ besitzt einen konsistenten Bundeslandcode.

- Auditierbarkeit:
  - jede Anlage > 100 kW bleibt im Ausschlussreport nachvollziehbar;
  - jede ungültige Kapazitätszeile bleibt im Review-Output nachvollziehbar;
  - keine manuelle, nicht dokumentierte Kapazitätskorrektur.

---

## 11. Methodische Grenzen

- Das E-Control Anlagenregister wird nicht als vollständiges physisches Anlagenkataster interpretiert.

- Die tatsächliche Netzebene einzelner Anlagen ist im verwendeten Datensatz nicht enthalten.

- Die gesetzliche Netzebenenzuordnung beruht auf **netzwirksamer Leistung**, nicht auf Engpassleistung.

- Der Filter `Engpassleistung <= 100 kW` ist deshalb ein **Proxy**.

- Mögliche Anlagen mit:
  - Engpassleistung > 100 kW,
  - aber netzwirksamer Leistung <= 100 kW
  werden nicht erfasst.

- § 97 Abs. 3 ElWG erlaubt technisch oder vertraglich begründete Abweichungen von der regulären Netzebenenklassifikation.

- `unit_count` zählt Registerzeilen, nicht unabhängig verifizierte physisch eindeutige PV-Anlagen.

- Nicht räumlich auflösbare in-scope Zeilen werden nicht in Gemeindeaggregate aufgenommen.

- Mapping-Qualität kann regional unterschiedlich sein.

- Es wird kein verstecktes Fuzzy Matching verwendet.

- Die Gemeindezuordnung ist an den verwendeten Gebietsstand der Statistik-Austria-Referenz gebunden.

---

## 12. Formulierung für die Masterarbeit

### Ausführliche Fassung

> For the PV harmonisation, the scope was restricted to installations that can plausibly be associated with the Austrian low-voltage level. According to § 97(1) of the Austrian Electricity Industry Act (Elektrizitätswirtschaftsgesetz, ElWG), grid connection points are generally assigned based on the grid-effective power (netzwirksame Leistung), with installations up to and including 100 kW assigned to grid level 7. Grid level 7 is defined in § 106(1) as low voltage of 1 kV and below. The E-Control plant register used in this work, however, reports the bottleneck capacity (Engpassleistung) rather than the contractually agreed grid-effective power. According to § 6 ElWG, these are distinct quantities: bottleneck capacity describes the maximum continuous active power of the generation plant, whereas grid-effective power describes the maximum power agreed at the grid connection point while considering the overall arrangement and operating concept of the connected installation.
>
> Since the actual grid-effective power and the physical voltage level of each registered PV installation are not available, bottleneck capacity is used as a conservative proxy. PV register entries with a valid positive bottleneck capacity of up to and including 100 kW are retained for the low-voltage-oriented dataset, whereas entries above 100 kW are excluded. Records with missing or non-positive capacity are retained only for auditing and are not included in the final municipality aggregation. This rule does not imply that the actual connection level of every retained or excluded installation is known. In particular, installations with a bottleneck capacity above 100 kW may have a grid-effective power limited to 100 kW or less, and § 97(3) ElWG allows deviations from the standard grid-level assignment for technical reasons or by mutual agreement. The applied threshold therefore represents a transparent scope approximation necessitated by the available open data rather than an exact reconstruction of individual network connections.

### Kurze Fassung

> To restrict the PV dataset to installations relevant to the low-voltage scope, a maximum bottleneck capacity of 100 kW is applied. The threshold is derived from § 97(1) ElWG, which generally assigns installations with a grid-effective power of up to 100 kW to grid level 7; § 106 ElWG defines grid level 7 as low voltage (≤1 kV). Since the E-Control register reports bottleneck capacity instead of grid-effective power, the 100 kW threshold is used as a conservative proxy rather than as an exact identification of the physical connection level. Installations above this threshold and records with invalid capacity information are excluded from the final LV-oriented municipality aggregation but retained in separate audit outputs.

---

## 13. Quellen

### Gesetzliche Hauptquelle

- **Republik Österreich (2025): Bundesgesetz zur Regelung der Elektrizitätswirtschaft (Elektrizitätswirtschaftsgesetz – ElWG), BGBl. I Nr. 91/2025.**
  - § 6 Z 105:
    - Definition `Maximalkapazität (Engpassleistung)`.
  - § 6 Z 117:
    - Definition `netzwirksame Leistung`.
  - § 97 Abs. 1:
    - reguläre Netzebenenzuordnung anhand der netzwirksamen Leistung;
    - bis einschließlich 100 kW -> Netzebene 7.
  - § 97 Abs. 3:
    - Möglichkeit einer technisch erforderlichen oder einvernehmlich vereinbarten abweichenden Zuordnung.
  - § 101 Abs. 2:
    - Möglichkeit der Begrenzung der netzwirksamen Leistung bei Photovoltaikanlagen.
  - § 106 Abs. 1 Z 7:
    - Netzebene 7 = Niederspannung, 1 kV und darunter.
  - RIS, Bundesrecht:
    - https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20013066&Paragraf=6
    - https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20013066&Paragraf=97
    - https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20013066&Paragraf=101
    - https://www.ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Gesetzesnummer=20013066&Paragraf=106
  - Zugriff: 26.08.2026.

### Weitere Datenquellen

- **E-Control: Anlagenregister.**
  - Öffentlicher Anlagenregister-Datensatz als Quelle für Technologie, Standortinformation und Engpassleistung.
  - https://www.e-control.at/anlagenregister

- **Statistik Austria: Gemeinden mit Ortschaften und Postleitzahlen, Gebietsstand 2026 (`ortsliste.xls`).**
  - Administrative Referenz für GKZ, Gemeinden, Ortschaften und Postleitzahlen.
  - https://www.statistik.at/verzeichnis/reglisten/ortsliste.xls

- **Statistik Austria: Gemeindeverzeichnis / Gemeindeliste.**
  - Referenz zur Prüfung der vollständigen österreichischen Gemeindestruktur und der GKZ.
  - https://www.statistik.at/verzeichnis/reglisten/gemliste_nam.pdf

---

## 14. Methodischer Gesamtworkflow

```text
E-Control Anlagenregister der 9 Bundesländer
        |
        v
Technologie = Photovoltaik
        |
        v
Engpassleistung numerisch harmonisieren
        |
        +-----------------------------+
        |                             |
        | fehlend / <= 0 kW           | > 100 kW
        v                             v
invalid_capacity              excluded_above_100kw
        |                             |
        +---------- Audit ------------+
        |
        | 0 < Engpassleistung <= 100 kW
        v
LV-Proxy-Datensatz
        |
        v
PLZ / Ortsname / Bundesland normalisieren
        |
        v
Statistik-Austria-Ortsliste + GKZ
        |
        v
deterministische Gemeindezuordnung
        |
        +--> unresolved -> Audit
        |
        v
erfolgreich zugeordnete LV-PV-Registerzeilen
        |
        v
Aggregation je Gemeinde
        |
        +--> unit_count
        +--> installed_capacity_kw
        +--> derivation_method
        |
        v
vollständiges 2.092-Gemeinden-Raster
        |
        v
Status-quo-PV-Datensatz für spätere
Allokation und LV-Power-Flow-Simulation
```
