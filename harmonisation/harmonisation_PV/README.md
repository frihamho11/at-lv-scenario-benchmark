# PV Register Harmonisation

## Purpose

This directory contains the harmonisation workflow for Austrian photovoltaic (PV) register data.

The workflow combines the nine federal-state plant-register files published by E-Control with the official Statistik Austria list of municipalities, localities and postcodes. Its purpose is to create a reproducible municipality-level PV dataset for subsequent scenario development, spatial allocation to buildings or grid connection points, and power-flow analysis in synthetic Austrian low-voltage grids.

This directory covers only the harmonisation of observed register data. Scenario generation, building-level allocation and electrical grid simulation are separate later stages of the master thesis.

---

## Role in the master thesis

The master thesis develops an open-data-based scenario and benchmark framework for synthetic Austrian low-voltage distribution grids.

The intended workflow is:

1. harmonise observed technology data to a common spatial level;
2. derive regional PV scenarios;
3. allocate municipality-level PV quantities to buildings or grid connection points;
4. simulate the resulting synthetic low-voltage grids;
5. evaluate voltage, line-loading and transformer-loading indicators.

The municipality level is used as the common administrative intermediate level because it provides a stable official identifier and can be linked to regional statistics, spatial data and synthetic grid study areas.

---

## Canonical workflow

The canonical notebook is:

```text
notebooks/pv_register_harmonisation_ortsliste_revised.ipynb
```

Older notebooks in the directory are not part of the current workflow and should not be used to regenerate the final outputs.

The current notebook was independently checked against the stored outputs. The plant-level assignments, derivation methods and municipality aggregates were reproduced without differences across all processed PV register rows.

---

## Input data

### E-Control Anlagenregister

Nine Excel files are used, one for each Austrian federal state:

```text
Anlagenregister_Burgenland.xlsx
Anlagenregister_Kärnten.xlsx
Anlagenregister_Niederösterreich.xlsx
Anlagenregister_Oberösterreich.xlsx
Anlagenregister_Salzburg.xlsx
Anlagenregister_Steiermark.xlsx
Anlagenregister_Tirol.xlsx
Anlagenregister_Vorarlberg.xlsx
Anlagenregister_Wien.xlsx
```

The required register columns are:

| Source column | Use |
|---|---|
| `ID` | Original file-local register identifier retained for traceability |
| `Plz` | Postcode used in the municipality mapping |
| `Ort` | Place name compared with official locality and municipality names |
| `Bundesland` | Source federal-state code |
| `Technologie` | Technology filter |
| `Engpassleistung (kW <sub>el</sub>)` | Electrical bottleneck capacity in kW |

The E-Control Anlagenregister publishes plants registered in its guarantees-of-origin database. The published fields include plant technology, location, bottleneck capacity and annual generation.[^1]

The input files are treated as a common snapshot. The configured `REFERENCE_DATE` represents the common download or snapshot date of the nine workbooks. It is not interpreted as an installation or commissioning date.

### Statistik Austria Ortsliste

The administrative reference is:

```text
data/ortsliste.xls
```

The file contains:

- municipality identifier (*Gemeindekennziffer*, GKZ),
- municipality name,
- locality identifier,
- locality name,
- postcode.

The Ortsliste is used because the `Ort` field in the register can contain either a political municipality or a locality belonging to a municipality.[^2]

The official five-digit GKZ is used as the final municipality identifier. Its first digit identifies the federal state.[^3]

### Vienna

The version of the Ortsliste used by this workflow contains 2,091 municipalities and does not include Vienna. Vienna is therefore added programmatically as:

```text
municipality_id: 90001
municipality_name: Wien
federal_state_code: W
```

The official Statistik Austria municipality list is used to validate Vienna and the complete set of 2,092 Austrian municipalities.[^4]

The raw Ortsliste is not edited manually.

---

## Technology selection

The accepted technology labels are configured explicitly:

```python
PV_TECHNOLOGY_VALUES = {
    "photovoltaik",
}
```

The complete distribution of source technology values is exported to `technology_summary`.

Technology values containing terms such as `solar` or `photovolta`, but not included in `PV_TECHNOLOGY_VALUES`, are retained in the `excluded_solar_like` review sheet instead of being silently discarded.

In the current snapshot, twelve solar-like rows are excluded from the main PV dataset. Their total capacity is negligible relative to the national dataset, but the exclusion remains visible and reproducible.

---

## Data standardisation

### Identifiers and postcodes

- municipality identifiers are converted to five-character strings;
- locality identifiers are converted to eight-character strings;
- postcodes are extracted as four-character strings;
- Ortsliste rows containing multiple postcodes are expanded to one row per postcode;
- invalid identifiers and postcodes are excluded from lookup construction.

### Place-name normalisation

Register and reference names are normalised using the same deterministic procedure:

1. Unicode NFKC normalisation;
2. Unicode-aware lower-case conversion;
3. replacement of `ß` with `ss`;
4. expansion of common Austrian place-name abbreviations;
5. replacement of hyphens, slashes and underscores with spaces;
6. removal of other punctuation;
7. collapse of repeated whitespace.

The abbreviation rules include:

```python
text = re.sub(r"\bst\b\.?\s*", "sankt ", text)
text = re.sub(r"\ba\b\.?\s*d\b\.?\s*", "an der ", text)
text = re.sub(r"\ba\b\.?\s*m\b\.?\s*", "am ", text)
```

Examples:

```text
St.Magdalena  -> sankt magdalena
St. Magdalena -> sankt magdalena
a.d.Thaya     -> an der thaya
a.m.See       -> am see
```

The word boundaries prevent regular names such as `Steyr`, `Steinbrunn` and `Amstetten` from being modified.

The workflow does not use fuzzy matching. This keeps every accepted assignment deterministic and auditable.

---

## Municipality reference and lookup construction

A municipality master table is created from unique combinations of:

```text
municipality_id
municipality_name
federal_state_code
```

Vienna is appended once. The resulting master must contain exactly 2,092 unique municipalities.

The following lookup tables are created from the expanded Ortsliste:

1. source federal state + postcode + locality name;
2. source federal state + postcode + municipality name;
3. national postcode + locality name;
4. national postcode + municipality name;
5. source federal state + locality name;
6. source federal state + municipality name;
7. source federal state + postcode.

A lookup key is retained only when it points to exactly one municipality identifier. Ambiguous keys are excluded.

A municipality-to-postcode set is also constructed. It is used to check whether a name-only candidate is compatible with the postcode recorded in the register.

---

## Mapping hierarchy

Each PV register row is processed using a fixed hierarchy. The first successful deterministic rule assigns the municipality.

| Priority | Rule | `derivation_method` |
|---:|---|---|
| 1 | Source register is Vienna and postcode is between 1010 and 1230, or place name is exactly `Wien` | `vienna_postcode_or_name` |
| 2 | Exact source state + postcode + locality name | `exact_locality_name_postcode` |
| 3 | Exact source state + postcode + municipality name | `exact_municipality_name_postcode` |
| 4 | Exact national postcode + locality name | `exact_national_locality_name_postcode` |
| 5 | Exact national postcode + municipality name | `exact_national_municipality_name_postcode` |
| 6 | Locality name uniquely identifies one municipality in the source state and the postcode is missing or compatible | `exact_unique_locality_name_postcode_compatible` |
| 7 | Municipality name uniquely identifies one municipality in the source state and the postcode is missing or compatible | `exact_unique_municipality_name_postcode_compatible` |
| 8 | Postcode uniquely identifies one municipality in the source state | `unique_postcode` |
| 9 | No rule succeeds | `unresolved` |

### National exact matches

The national postcode-and-name rules allow a row to be assigned outside the federal state indicated by the source workbook.

This is necessary because the source register's federal-state field does not always represent the geographical federal state of the address. The national rules correct known border and registration cases while still requiring an exact postcode-and-name combination.

The plant-level output stores both:

```text
source_federal_state_code
federal_state_code
```

A different value is marked by:

```text
cross_state_assignment = True
```

### Name–postcode conflicts

If a unique name-only candidate exists but the recorded postcode is not listed for that municipality, the row receives:

```text
mapping_issue = name_postcode_conflict
```

The row is not assigned by the name-only rule.

The final unique-postcode fallback is nevertheless allowed to assign such a row when the postcode uniquely identifies another municipality in the source state. The conflict flag remains stored in the plant-level output. This makes these cases explicitly reviewable rather than hiding the contradiction.

Consequently, a row can be:

```text
mapping_issue = name_postcode_conflict
derivation_method = unique_postcode
```

This behaviour is intentional in the current implementation and must be considered when interpreting the weakest fallback assignments.

---

## Capacity processing

The source field `Engpassleistung (kW <sub>el</sub>)` is converted to numeric kilowatts.

The parser supports:

- numeric Excel cells;
- German decimal commas;
- decimal points;
- mixed thousands and decimal separators;
- whitespace and non-breaking spaces.

Rows with missing or non-positive capacity are retained in the plant-level dataset and exported to `invalid_capacity`.

Current treatment:

- a resolved zero-capacity row contributes one record to `unit_count`;
- it contributes zero to `installed_capacity_kw`;
- missing numeric capacity does not contribute to the capacity sum.

No silent capacity replacement is performed.

---

## Unit count and duplicates

`unit_count` is defined as the number of mapped PV register rows.

It is not interpreted as an independently verified count of physically distinct PV installations.

The source `ID` behaves as a file-local running identifier and is not used for cross-file or physical-plant deduplication. The current source files do not provide a reliable national plant identifier that would support a defensible automatic deduplication procedure.

---

## Municipality-level aggregation

Only rows with a resolved municipality identifier are included in municipality totals.

For municipality `m` and reference date `t`:

```text
unit_count(m,t) =
    number of resolved register rows assigned to municipality m
```

```text
installed_capacity_kw(m,t) =
    sum of numeric bottleneck capacities of those rows
```

The municipality-level `derivation_method` is:

- the method name when every mapped row used the same method;
- `mixed` when several mapping methods were used;
- `not_applicable` for municipalities without mapped rows.

The aggregation is left-joined to the complete municipality master. Municipalities without mapped PV records therefore remain present with:

```text
unit_count = 0
installed_capacity_kw = 0.0
derivation_method = not_applicable
```

---

## Output files

The workflow creates:

```text
outputs/pv_municipality_harmonised.xlsx
outputs/pv_plants_harmonised.parquet
```

### Municipality workbook

The Excel workbook contains:

| Sheet | Content |
|---|---|
| `pv_by_municipality` | Final municipality-level PV dataset |
| `state_mapping_report` | Unit and capacity mapping rates by source federal state |
| `mapping_summary` | Counts and capacities by mapping method |
| `unresolved_top_places` | Grouped unresolved place and postcode combinations |
| `unresolved_units` | All unresolved plant-register rows |
| `invalid_capacity` | Rows with missing or non-positive capacity |
| `source_report` | Input and parsing summary for each workbook |
| `technology_summary` | Complete distribution of source technology labels |
| `excluded_solar_like` | Solar-like rows not included in the configured PV filter |
| `validation` | Automated validation checks |

### Plant-level Parquet file

The Parquet output preserves the audit trail for every accepted PV source row, including:

```text
source_file
source_row_number
source_register_id
source_row_key
postcode_raw
place_name_raw
capacity_raw
postcode
place_name
source_federal_state_code
federal_state_code
reference_date
municipality_id
municipality_name
derivation_method
mapping_issue
cross_state_assignment
installed_capacity_kw
```

Raw mixed-type Excel fields are converted explicitly before Parquet export.

---

## Validation

The current notebook verifies:

1. the final municipality table contains 2,092 rows;
2. municipality identifiers are unique;
3. the number of aggregated rows equals the number of resolved plant rows;
4. mapped capacity is conserved during aggregation within a tolerance of 0.01 kW;
5. every resolved municipality has a valid federal-state code derived from its GKZ.

The stored outputs were also independently reproduced from the current notebook logic without differences at plant or municipality level.

---

## Current snapshot results

The following values apply only to the register snapshot configured in the current notebook:

| Metric | Value |
|---|---:|
| Processed PV register rows | 581,075 |
| Resolved rows | 559,072 |
| Unresolved rows | 22,003 |
| Unit mapping rate | 96.21% |
| Mapped capacity | approximately 11,233.9 MW |
| Unresolved capacity | approximately 377.3 MW |
| Capacity mapping rate | approximately 96.75% |
| Cross-state assignments | 1,852 |
| Name–postcode conflicts | 1,921 |
| Municipalities in final table | 2,092 |
| Municipalities without mapped PV rows | 1 |

The national mapping rate must not hide regional differences. Styria has the largest unresolved share:

```text
unresolved rows: approximately 12,940
unresolved capacity: approximately 209 MW
unit mapping rate: approximately 86.6%
capacity mapping rate: approximately 89.5%
```

The remaining gap is mainly associated with source naming conventions such as abbreviated municipality suffixes, district or locality names, transliterations and short forms. It is retained as a quantified limitation rather than resolved through undocumented fuzzy matching.

---

## Interpretation for scenario development

The municipality table is suitable as an observed regional PV input for the later thesis stages because it provides:

- a complete official municipality key;
- mapped register-record counts;
- mapped installed capacity;
- a plant-level audit trail;
- explicit unresolved and fallback information;
- regional mapping-quality indicators.

The output is not itself a future scenario. It represents a harmonised observation layer from which scenario parameters may later be derived.

The later scenario methodology must distinguish between:

1. observed mapped register totals;
2. assumptions about future PV uptake;
3. allocation of municipality values to buildings;
4. electrical network simulation.

For municipalities or federal states with lower mapping coverage, scenario interpretation should explicitly account for the unresolved share. This is particularly important for Styria.

---

## Reproduction

1. Place the nine register workbooks and `ortsliste.xls` in `data/`.
2. Confirm the expected file names in `REGISTER_FILES`.
3. Set `REFERENCE_DATE` to the common register snapshot date.
4. Review `PV_TECHNOLOGY_VALUES`.
5. Restart the kernel.
6. Run the canonical notebook from top to bottom.
7. Confirm that every validation row has `passed = True`.
8. Review:
   - `state_mapping_report`,
   - `excluded_solar_like`,
   - `unresolved_top_places`,
   - `unresolved_units`,
   - `invalid_capacity`,
   - cross-state assignments and name–postcode conflicts in the Parquet file.
9. Save the notebook and outputs together with the source snapshot metadata.

Close `pv_municipality_harmonised.xlsx` before rerunning the export cell. An open workbook is locked by Excel on Windows and cannot be overwritten.

---

## Methodological limitations

- The E-Control Anlagenregister includes plants registered in its guarantees-of-origin database and is not treated as a complete physical PV cadastre.[^1]
- `unit_count` counts register rows, not verified distinct installations.
- unresolved rows are excluded from municipality totals;
- mapping coverage differs between federal states;
- the weakest fallback relies on a postcode being unique within the source federal state;
- the Ortsliste may not represent every postcode convention occurring in the register;
- some name–postcode conflicts are resolved by the unique-postcode fallback but remain flagged;
- cross-state assignments assume that an exact address postcode and name are geographically more informative than the source register's federal-state field;
- zero-capacity register rows remain in the record count;
- no fuzzy matching or hidden manual correction is applied;
- the municipality master is tied to the Statistik Austria territorial status used by the Ortsliste;
- later joins must use compatible territorial reference dates.

These limitations should be reported when the harmonised data are used to derive regional scenarios.

---

## Recommended project structure

```text
harmonisation_PV/
├── data/
│   ├── ortsliste.xls
│   └── Anlagenregister_*.xlsx
├── notebooks/
│   ├── pv_register_harmonisation_ortsliste_revised.ipynb
│   └── archive/
│       ├── pv_register_harmonisation_ortsliste.ipynb
│       └── pv_harmonisation.ipynb
├── outputs/
│   ├── pv_municipality_harmonised.xlsx
│   └── pv_plants_harmonised.parquet
└── README.md
```

The archived notebooks must not write to the current output paths.

---

## Sources

[^1]: E-Control, **Anlagenregister**. Public register of plants recorded in the guarantees-of-origin database, including technology, location, bottleneck capacity and annual generation. <https://www.e-control.at/anlagenregister> (accessed 19 July 2026).

[^2]: Statistik Austria, **Gemeinden mit Ortschaften und Postleitzahlen, Gebietsstand 2026** (`ortsliste.xls`). <https://www.statistik.at/verzeichnis/reglisten/ortsliste.xls> (accessed 19 July 2026).

[^3]: Statistik Austria, **Gemeindeverzeichnis**. Documentation of the five-digit municipality identifier and its administrative structure. <https://www.statistik.at/fileadmin/publications/Gemeindeverzeichnis_Stand_1.1.2021.pdf> (accessed 19 July 2026).

[^4]: Statistik Austria, **Gemeindeliste sortiert nach Gemeindenamen, Gebietsstand 2026**. Used to validate the complete municipality set and Vienna as GKZ `90001`. <https://www.statistik.at/verzeichnis/reglisten/gemliste_nam.pdf> (accessed 19 July 2026).
