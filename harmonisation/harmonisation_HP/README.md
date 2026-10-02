# HP Stock Harmonisation

## 1. Purpose

This directory contains the harmonisation workflow for the Austrian stock of
**heating heat pumps** at municipality level.

Target quantity: the estimated number of heating heat pumps in operation per
Austrian municipality in the reference year 2024 (reference date 2024-12-31).

**Excluded** from the target quantity — these are reported as separate
categories in the national source and are never added in:

- domestic-hot-water-only heat pumps (*Brauchwasserwärmepumpen*),
- ventilation heat pumps (*Wohnraumlüftungswärmepumpen*),
- industrial heat pumps (*Industriewärmepumpen*).

**Out of scope for this workflow.** The harmonisation covers the installation
stock only. Electrical rating, thermal rating, COP, seasonal performance
factor, temperature profiles, temporal load profiles, building-level
selection, allocation to grid connection points, and future scenarios are
**not** part of this directory. They belong to the later scenario
implementation of the thesis and must not be mixed with the stock
disaggregation.

The federal-state and municipality values produced here are **model-based
estimates**, not observed heat-pump counts. The method is mass-preserving: a
manually configured national control total is distributed downwards in two
stages, and no installation is created or lost at any point.

The project structure, configuration and path handling, validation style,
auditability and output conventions follow the sibling
`harmonisation_PV` and `harmonisation_EV` workflows as closely as
possible. The subject-matter method is independent of both. Neither sibling
directory is read, written or modified by this workflow.

---

## 2. Role in the thesis

As with the PV and EV workflows, the municipality level serves as a stable
administrative intermediate level for later scenario development and grid
simulation. This directory covers only the harmonisation of the heat-pump
stock; scenarios, building-level allocation, plant sizing and network
simulation are separate, later stages.

---

## 3. Canonical workflow

```text
notebooks/hp_stock_harmonisation.ipynb
```

This is the **only** notebook of the workflow. There are no variants, scratch
notebooks or parallel implementations.

1. keep the input files in `data/`;
2. run the notebook from top to bottom;
3. obtain `outputs/hp_municipality_harmonised.xlsx` and
   `outputs/hp_municipality_audit.parquet`.

The notebook does not read, parse or otherwise depend on the methodological
literature PDFs. Those live outside this project folder, in the shared
`harmonisation/literature/` directory, and are cited bibliographically
only (Section 15).

---

## 4. Directory structure

```text
harmonisation_HP/
├── data/
│   ├── BMIMI-marktstatistik-2024.pdf                    (cited only, never parsed)
│   ├── GesamteinsatzAllerEnergietraeger2003Bis2024.ods  (Stage 1 proxy)
│   ├── Energieeinsatz_HP_Bundesländer.xlsx              (validation only)
│   ├── AEST_Gemeindeergebnisse_2024.ods                 (Stage 2 proxy)
│   └── municipalities_clean.xlsx                        (canonical municipality master)
├── notebooks/
│   └── hp_stock_harmonisation.ipynb                     (the only notebook)
├── outputs/
│   ├── hp_municipality_harmonised.xlsx
│   └── hp_municipality_audit.parquet
└── README.md
```

---

## 5. Input data

All four files read by the notebook are checked together at the start
(Section 3 of the notebook): if any is missing, the notebook stops immediately
with a single `FileNotFoundError` naming every missing file.

### `data/BMIMI-marktstatistik-2024.pdf` — national control total, cited only

| Item | Value |
|---|---|
| Publisher | Bundesministerium für Innovation, Mobilität und Infrastruktur (BMIMI), Radetzkystraße 2, 1030 Wien |
| Title | *Innovative Energietechnologien in Österreich – Marktentwicklung 2024. Biomasse, Photovoltaik, Solarthermie, Wärmepumpen und Windkraft* |
| Series | Berichte aus Energie- und Umweltforschung 23/2025 |
| Scientific project lead, editor, report part heat pumps | ENFOS e.U., Peter Biermayr |
| Place, date | Vienna, May 2025 |
| Reference period | 2024 |
| Spatial resolution | Austria (national) |
| Report part / section / table | Chapter 9 *Wärmepumpen*; Section 9.1.3 *In Betrieb befindliche Anlagen* (report page 147); Table 51 *Entwicklung des Wärmepumpenbestandes in Österreich* (report page 150) |
| Row / column used | year **2024**, column **Heizung** |
| Value used | **407,637** installations |
| Role | The single binding national control total, **entered manually** in the notebook |
| Limitations | Modelled stock; see below |

The PDF is **not parsed**. Its value is transcribed by hand into a clearly
marked configuration cell:

```python
NATIONAL_HEATING_HP_STOCK = 407_637
REFERENCE_YEAR = 2024
REFERENCE_DATE = "2024-12-31"
```

The manually entered value is the **only** binding national stock total of the
workflow, and an assertion in the configuration cell fails if it is changed
away from the documented source value.

**The national stock is itself a modelled stock.** The report derives it from
historical annual domestic sales figures and an assumed technical service life
of 20 years; installations older than that are treated as no longer in
operation. The report states explicitly that no Weibull-distributed retirement
function was implemented, because the data required to parameterise one
empirically were not available. The figure is therefore a transparent model
result, not a census of installed units.

Categories reported separately for 2024 in the same table and excluded here:
*Brauchwasser* 121,616; *WRL & Luft/Luft* 6,775; *Industrie* 935; total across
all categories 536,963.

### `data/GesamteinsatzAllerEnergietraeger2003Bis2024.ods` — Stage 1 proxy

| Item | Value |
|---|---|
| Publisher | STATISTIK AUSTRIA, Energiestatistik (microcensus *Energieeinsatz der Haushalte*) |
| Reference period | survey period **2023/2024** |
| Spatial resolution | federal state |
| Sheets used | one sheet per federal state (`Burgenland` … `Wien`), plus `Österreich` for a control check |
| Block used | `Gesamteinsatz aller Energieträger 2023/2024`, row `Wärmepumpe` |
| Columns used | `Haushalte (HH)` → allocation proxy; `GJ` and `GJ pro HH` → validation only |
| Role | Stage 1 allocation weights |

The **reported household figure is used directly**. It is deliberately *not*
derived from a federal-state energy input divided by a nationwide average GJ
per household. The GJ and GJ-per-household columns never enter the allocation
and are used exclusively for the plausibility checks of Section 10.

The block, its header row, the required columns and the `Wärmepumpe` row are
all located by their labels, not by hard-coded offsets, and each lookup must
match exactly once; a changed source layout raises instead of silently reading
the wrong cells. The block title is additionally checked to name the expected
territory, guarding against a mislabelled or reordered sheet.

Limitation carried into the results: the source counts households once for
**every** energy carrier they use, so the carrier rows overlap by
construction. `hp_households` is the number of households reporting heat-pump
use — not a count of installations.

### `data/Energieeinsatz_HP_Bundesländer.xlsx` — validation only

| Item | Value |
|---|---|
| Publisher | STATISTIK AUSTRIA, STATcube |
| Reference period | 2023/2024, sum of all end uses |
| Spatial resolution | federal state |
| Sheet / row used | `Datenblatt 0`, row `Wärmepumpe`, columns Burgenland … Wien |
| Role | Cross-source comparison of the federal-state heat-pump energy input |
| Limitations | Published as whole GJ, so small rounding deviations against the full-precision household source are expected |

This file **must not** change the stock distribution, and it does not: it feeds
only the reported checks of Section 10, and no automatic correction is derived
from them.

### `data/AEST_Gemeindeergebnisse_2024.ods` — Stage 2 proxy

| Item | Value |
|---|---|
| Publisher | STATISTIK AUSTRIA, *Abgestimmte Erwerbsstatistik 2024 — Ausgewählte Ergebnisse* |
| Reference period | 2024 |
| Spatial resolution | municipality, **territorial status 2026** |
| Sheet used | `Gemeindetab_(Gebietsstand_2026)` |
| Columns used | block *Gebäudebestand*: `Gebäude gesamt`, `Gebäude mit 1 oder 2 Wohnungen in %`, `Gebäude mit 3 oder mehr Wohnungen in %`, `Andere Gebäude1 in %` (last one validation only) |
| Role | Stage 2 allocation weights (main and sensitivity variant) |

The territorial status 2026 matches the territorial status of the canonical
municipality list, so the two datasets join on identical
Gemeindekennziffern.

The sheet `Indikatoren_2024` and the sheet `Gemeindetab_(Gebietsstand_2024)`
are **not used**: the former contains only indicators and no absolute building
counts, and the latter uses a territorial status that does not match the
canonical municipality list.

Limitation: the source publishes the building classes as **percentage shares
rounded to one decimal place**, not as absolute counts. The class counts are
therefore derived (Section 8) and carry a rounding uncertainty of up to
±0.05 % · `Gebäude gesamt` per class. This is quantified against the
independent federal-state rows of the same source (Section 11).

### `data/municipalities_clean.xlsx` — canonical municipality master

| Item | Value |
|---|---|
| Publisher | STATISTIK AUSTRIA, via the sibling EV harmonisation workflow |
| Reference period | territorial status 2026 |
| Spatial resolution | municipality |
| Sheet used | `municipalities` |
| Role | Gemeindekennziffer, municipality name, federal-state code — the only join key of the workflow |

This file is an **unchanged, byte-identical copy** of the canonical
municipality list of the EV workflow:

```text
original path: harmonisation_EV/data/municipalities_clean.xlsx
original name: municipalities_clean.xlsx
status:        unchanged copy (verified byte-identical)
```

The copy exists so that the HP workflow is reproducible on its own. The EV file
itself is never read, written or modified here. The same Gemeindekennziffern,
municipality names, federal-state codes and territorial status are used
(2,092 municipalities including Vienna as GKZ `90001`).

The **GKZ is the primary and only join key**. No name-based matching, no fuzzy
matching and no silent first-match selection is used anywhere. Ambiguous or
missing assignments produce a diagnostic, are written to
`unmatched_records`, and abort the workflow with an explicit error message.

---

## 6. Reference dates and periods

Three temporal references are tracked **separately** and are deliberately not
equated with one another:

```text
REFERENCE_DATE            = 2024-12-31   (heat-pump stock, canonical output)
STATE_PROXY_SURVEY_PERIOD = 2023/2024    (federal-state household weights)
BUILDING_PROXY_YEAR       = 2024         (municipal building weights, territorial status 2026)
```

The survey period 2023/2024 of the federal-state proxy is recorded in the
federal-state audit table, in the municipality audit table
(`survey_period_state_proxy`) and in `source_metadata`. It is **not** a
substitute for a 2024-12-31 household figure.

---

## 7. Method — two-stage mass-preserving disaggregation

```text
Austria  ->  federal states  ->  municipalities
```

### 7.1 Notation

| Symbol | Meaning |
|---|---|
| $N_{\mathrm{AT}}^{HP}$ | national stock of heating heat pumps in Austria |
| $\mathcal{S}$ | set of all Austrian federal states |
| $s, r$ | a federal state; $r$ is the running index over $\mathcal{S}$ |
| $H_s^{HP}$ | number of households using a heat pump in federal state $s$ |
| $w_s^{HP}$ | share of federal state $s$ in all reported heat-pump households |
| $\widetilde{N}_s^{HP}$ | unrounded modelled heat-pump stock of federal state $s$ |
| $N_s^{HP}$ | final integer heat-pump stock of federal state $s$ |
| $E_s^{HP}$ | total heat-pump energy input of federal state $s$ (GJ) |
| $\bar{e}_s^{HP}$ | average energy input per heat-pump household in $s$ (GJ) |
| $\mathcal{M}_s$ | set of all municipalities in federal state $s$ |
| $m, j$ | a municipality; $j$ is the running index over $\mathcal{M}_s$ |
| $B_m^{1}, B_m^{2}, B_m^{3+}$ | residential buildings in $m$ with one, two, three or more dwellings |
| $B_m^{res}$ | total number of residential buildings in municipality $m$ |
| $X_m^{HP}$ | municipal proxy value for the heat-pump distribution |
| $q_{m\mid s}^{HP}$ | share of municipality $m$ in the proxy total of its federal state |
| $\widetilde{N}_m^{HP}$ | unrounded modelled heat-pump stock of municipality $m$ |
| $N_m^{HP}$ | final integer heat-pump stock of municipality $m$ |

Every formula in the notebook restates the meaning of each symbol directly
next to it, so no formula depends on this table alone.

### 7.2 Stage 1 — Austria to federal states

$$
w_s^{HP} = \frac{H_s^{HP}}{\sum_{r\in\mathcal{S}} H_r^{HP}}
\qquad
\widetilde{N}_s^{HP} = N_{\mathrm{AT}}^{HP}\cdot w_s^{HP}
$$

After Largest Remainder rounding (Section 7.4) the following holds exactly:

$$
\sum_{s\in\mathcal{S}} N_s^{HP} = N_{\mathrm{AT}}^{HP} = 407\,637
$$

### 7.3 Stage 2 — federal states to municipalities

Residential buildings are derived from the published class shares:

$$
B_m^{1}+B_m^{2} = B_m^{\text{total}}\cdot\frac{p_m^{1\text{-}2}}{100},
\qquad
B_m^{3+} = B_m^{\text{total}}\cdot\frac{p_m^{3+}}{100},
\qquad
B_m^{res} = \left(B_m^{1}+B_m^{2}\right)+B_m^{3+}
$$

The source combines the one-dwelling and two-dwelling classes into one
published class, so $B_m^{1}$ and $B_m^{2}$ are available only as their sum.
This is sufficient for both variants used here.

**Main variant:**

$$
X_m^{HP} = B_m^{res}
$$

That is: within a federal state the heat-pump stock is distributed across
municipalities in proportion to the number of residential buildings. The main
variant uses **no** population, **no** municipal area and **no** freely chosen
multi-family weighting factor.

$$
q_{m\mid s}^{HP} = \frac{X_m^{HP}}{\sum_{j\in\mathcal{M}_s} X_j^{HP}}
\qquad
\widetilde{N}_m^{HP} = N_s^{HP}\cdot q_{m\mid s}^{HP}
$$

After rounding within each federal state:

$$
\sum_{m\in\mathcal{M}_s} N_m^{HP} = N_s^{HP}
\qquad\text{and}\qquad
\sum_{s\in\mathcal{S}}\sum_{m\in\mathcal{M}_s} N_m^{HP} = 407\,637
$$

Vienna is processed by the same generic routine — there is no Vienna special
case. Because Vienna is a single municipality in this territorial status,
$q_{m\mid s}^{HP}=1$ and it automatically receives the entire Viennese
federal-state stock.

### 7.4 Largest Remainder integer allocation

Applied at federal-state level (Stage 1) and separately within each federal
state (Stage 2):

1. round every unrounded value down;
2. determine the decimal remainders;
3. compute the number of installations still missing;
4. award the missing installations to the entries with the largest remainders.

Tie-breaking is an explicit compound sort key, built and sorted as its own
step — it does not rely on input order or on sort stability:

| Stage | Tie-break order |
|---|---|
| Stage 1 | remainder descending, then federal-state code ascending |
| Stage 2 | remainder descending, then municipal proxy value descending, then Gemeindekennziffer ascending |

Section 5a of the notebook tests all three tie-break levels with artificial
tied values presented in two different (scrambled) input orders and asserts
that both produce identical results. **No random allocation is used anywhere**;
re-running the notebook reproduces byte-identical outputs.

### 7.5 Resolution of the municipal building rows

The AEST sheet mixes hierarchy levels in one identifier column: one-digit codes
are Austria and the federal states, three-digit codes are political districts
(including the 23 Viennese municipal districts), five-digit codes are
municipalities. Every municipality of the canonical master is resolved by
exactly one of three documented rules, each **re-derived and validated from the
master data itself** rather than asserted:

| Rule | Condition | Justification | Count |
|---|---|---|---:|
| `direct_municipality_row` | a five-digit AEST row with the same GKZ exists | ordinary case | 2,077 |
| `statutory_city_political_district_row` | no five-digit row exists, but a three-digit district row exists whose code is the GKZ prefix, **and** the master contains exactly one municipality with that prefix, whose GKZ is that prefix + `01` | an Austrian *Statutarstadt* is simultaneously a political district and a single municipality, so the district row covers exactly that municipality's territory | 14 |
| `vienna_federal_state_row` | GKZ `90001`, resolved against the one-digit federal-state row `9`, **and** the master contains exactly one municipality in federal state 9 | Vienna is simultaneously a federal state and a single municipality; the 23 Viennese district rows are sub-municipal and are not used | 1 |

If any municipality cannot be resolved, or if the source contains a five-digit
code that is not in the canonical master, the affected records are written to
`unmatched_records` and the workflow stops with an explicit error rather than
redistributing a federal state's stock over the remaining municipalities.

Municipality names come from the canonical master only and are never
overwritten by AEST labels. The 25 municipalities whose AEST label differs from
the canonical name are reported in `municipality_name_comparison` — reported,
never applied. Every source row that is not used as a municipal proxy is
recorded in `aest_row_usage` with its reason, so nothing is dropped without a
trace.

---

## 8. Sensitivity variant

Because the source publishes the one-/two-dwelling class separately, a second,
restricted proxy is computed:

$$
X_{m,1\text{-}2}^{HP} = B_m^{1}+B_m^{2}
$$

Its **sole purpose is to examine how sensitive the municipal results are to the
choice of building proxy.** The canonical main output remains based on all
residential buildings.

No weighted expression of the form $B_m^{1}+B_m^{2}+\lambda B_m^{3+}$ is used,
because no evidence-based source for $\lambda$ exists in this project. **No
value for $\lambda$ is invented.** The analysis is therefore restricted to the
two unweighted end members.

Both variants distribute the identical federal-state stocks $N_s^{HP}$, so
every federal-state sum is identical by construction; the comparison measures
redistribution **within** federal states.

The comparison reports, per municipality, the absolute and relative difference,
and, per federal state, the number and share of municipalities changed, the sum
and mean absolute difference, and the largest positive and negative deviations
(`sensitivity_by_state`, `sensitivity_top_deviations`, and the
`sensitivity_*` columns of the audit Parquet).

---

## 9. Canonical output schema

`outputs/hp_municipality_harmonised.xlsx`, sheet `hp_by_municipality`, exactly
these seven columns:

```text
municipality_id, municipality_name, federal_state_code, reference_date,
unit_count, derivation_method, data_quality
```

- `unit_count` is the final integer municipal heat-pump stock $N_m^{HP}$;
- `reference_date` is `2024-12-31`;
- `federal_state_code` uses the full federal-state name, following the EV
  workflow;
- controlled values, marking the result clearly as modelled — the terms
  `observed`, `measured` and `exact` are deliberately not used:

```text
derivation_method = national_heating_hp_stock_state_hp_households_municipal_residential_buildings
data_quality      = modelled_mass_preserving
```

The federal-state proxy originates from the statistical period 2023/2024; this
is recorded separately in the audit tables and in `source_metadata` and is not
equated with the reference date.

---

## 10. Validation

The notebook runs 42 checks in a single validation table (38 critical, 4
reported). Critical checks gate the export: no output file is written while any
of them fails.

**National control total** — the national stock is exactly 407,637.

**Federal-state level** — all nine federal states present; no duplicate
federal-state codes; no negative household values; the nine federal-state
household figures reconstruct the `Österreich` sheet of the same source
(deviation < 1e-9); the federal-state weights sum to 1 within numerical
tolerance; the final federal-state stocks sum to exactly 407,637.

**Energy validation (reported, never gating the allocation)** —
$E_s^{HP} \approx H_s^{HP}\cdot\bar{e}_s^{HP}$ holds for every federal state
(largest relative deviation ≈ 4e-15); both available files report the same
federal-state energy input (largest relative deviation ≈ 9.2e-7); every
cross-source deviation is at most 0.47 GJ and is fully explained by the
validation file publishing whole GJ against the full-precision household
source. The energy shares are additionally compared against the household
shares for information only — the largest difference is Oberösterreich, whose
energy share exceeds its household share by 0.036 (as a fraction). **No
automatic correction is derived from any of these checks.**

**Municipality master** — `municipality_id` unique; 2,092 municipalities;
Vienna present exactly once; no missing federal-state assignment.

**Building proxy** — no negative building counts; the published class shares
sum to 100 % within 0.1 percentage points (one-decimal rounding); every
municipality has building data; no unknown municipality is introduced by the
source; no unmatched records; the municipality-level values reconstruct the
independent federal-state rows of the same source within 1 % (largest actual
deviation 0.077 %, Niederösterreich — the residual comes from the one-decimal
share rounding); no federal state has a proxy total of zero.

**Allocation** — no rows dropped; the output municipality set equals the
canonical set exactly, with no extras; `municipality_id` unique in the output;
`unit_count` integer, non-negative and never missing; each federal state's
municipal sum equals its stock exactly; the national municipal sum is exactly
407,637; the sensitivity variant preserves the same totals.

**No silent data handling** — every excluded source row is recorded with a
reason; no building value is imputed; municipality names are not corrected.

---

## 11. Output files

### `outputs/hp_municipality_harmonised.xlsx`

| Sheet | Content |
|---|---|
| `hp_by_municipality` | canonical municipality-level dataset (seven columns, Section 9) |
| `federal_state_audit` | Stage 1 audit table (Section 12) |
| `validation` | all 42 checks with expected value, actual value, pass flag and criticality |
| `energy_cross_source_validation` | Section 10 energy checks incl. absolute and relative deviations |
| `building_proxy_rule_summary` | number of municipalities resolved by each of the three rules |
| `building_proxy_special_rows` | full evidence for the 15 municipalities resolved from an aggregate row |
| `building_proxy_state_valid` | reconstruction of the AEST federal-state rows from the municipality rows |
| `municipality_name_comparison` | municipalities whose source label differs from the canonical name |
| `unmatched_records` | missing or unassignable records (currently empty) |
| `aest_row_usage` | usage and reason for every row of the building source |
| `sensitivity_by_state` | sensitivity summary per federal state |
| `sensitivity_top_deviations` | 20 largest positive and 20 largest negative municipal deviations |
| `source_metadata` | file, publisher, reference period, spatial resolution, sheet/columns, role, limitations |

### `outputs/hp_municipality_audit.parquet`

The complete municipality audit table, one row per municipality:
`municipality_id`, `municipality_name`, `federal_state_id`,
`federal_state_code`, `state_hp_stock_final`, `buildings_total_all_types`,
`buildings_1_2_dwellings`, `buildings_3_plus_dwellings`,
`residential_buildings`, `municipal_proxy_value`, `state_proxy_total`,
`proxy_share_within_state`, `hp_stock_raw`, `hp_stock_floor`,
`fractional_remainder`, `rounding_adjustment`, `unit_count`, `proxy_variant`,
`building_proxy_resolution_rule`, `aest_source_code`, `aest_source_label`,
`reference_date`, `derivation_method`, `data_quality`,
`sensitivity_proxy_value`, `sensitivity_proxy_share_within_state`,
`sensitivity_hp_stock_raw`, `unit_count_sensitivity`,
`sensitivity_absolute_difference`, `sensitivity_relative_difference`,
`survey_period_state_proxy`, `building_proxy_year`, `value_status`.

Neither file is written while any critical validation fails.

---

## 12. Current results

Stage 1, survey period 2023/2024, national stock 407,637:

| Code | Federal state | HP households | Share | Unrounded | +1 | Final stock |
|---|---|---:|---:|---:|:--:|---:|
| 1 | Burgenland | 39,639.1 | 0.064155 | 26,152.14 | | 26,152 |
| 2 | Kärnten | 41,888.7 | 0.067796 | 27,636.33 | | 27,636 |
| 3 | Niederösterreich | 173,941.8 | 0.281523 | 114,759.07 | | 114,759 |
| 4 | Oberösterreich | 140,525.8 | 0.227439 | 92,712.68 | ✓ | 92,713 |
| 5 | Salzburg | 32,716.1 | 0.052951 | 21,584.60 | ✓ | 21,585 |
| 6 | Steiermark | 76,566.2 | 0.123921 | 50,514.97 | ✓ | 50,515 |
| 7 | Tirol | 48,914.5 | 0.079167 | 32,271.60 | ✓ | 32,272 |
| 8 | Vorarlberg | 38,895.4 | 0.062952 | 25,661.45 | | 25,661 |
| 9 | Wien | 24,773.1 | 0.040095 | 16,344.16 | | 16,344 |
| | **Total** | **617,860.8** | **1.000000** | | **4** | **407,637** |

These federal-state figures are **modelled estimates**, not observed stock
counts.

Stage 2:

| Metric | Value |
|---|---:|
| Municipalities in the output | 2,092 |
| National sum of `unit_count` | 407,637 |
| Municipalities with `unit_count` = 0 | 0 |
| Median `unit_count` | 129 |
| Maximum `unit_count` | 16,344 (Wien) |
| Rounding adjustments (+1) at municipality level | 1,059 |
| Unmatched / unassignable records | 0 |

Sensitivity variant (one-/two-dwelling buildings only):

| Metric | Value |
|---|---:|
| Municipalities with a different value | 2,019 of 2,092 (96.5 %) |
| Units redistributed | 14,274 (3.50 % of the national stock) |
| Deviation range | −2,059 to +50 units |
| Largest negative deviations | Linz −2,059 (−43.2 %), Graz −1,458 (−26.6 %), Innsbruck −1,017 (−49.6 %) |

The pattern is systematic and expected: excluding buildings with three or more
dwellings shifts stock away from the larger cities towards municipalities
dominated by one- and two-dwelling buildings. This quantifies how strongly the
municipal result depends on the treatment of multi-dwelling buildings, which is
the central proxy uncertainty of this workflow.

---

## 13. Reproduction

1. Keep the five files listed in Section 4 in `data/`. Only
   `GesamteinsatzAllerEnergietraeger2003Bis2024.ods`,
   `Energieeinsatz_HP_Bundesländer.xlsx`, `AEST_Gemeindeergebnisse_2024.ods`
   and `municipalities_clean.xlsx` are read; the PDF is cited only and its
   absence does not break the workflow.
2. Confirm `NATIONAL_HEATING_HP_STOCK`, `REFERENCE_YEAR`, `REFERENCE_DATE`,
   `STATE_PROXY_SURVEY_PERIOD` and `BUILDING_PROXY_TERRITORIAL_STATUS` in the
   configuration cell (notebook Section 3).
3. Restart the kernel.
4. Run `notebooks/hp_stock_harmonisation.ipynb` from top to bottom.
5. Confirm that the validation table reports `ALL CRITICAL CHECKS PASSED: True`.
6. Review `federal_state_audit`, `energy_cross_source_validation`,
   `building_proxy_state_valid`, `unmatched_records` and the sensitivity
   sheets.
7. `outputs/hp_municipality_harmonised.xlsx` and
   `outputs/hp_municipality_audit.parquet` are written once every critical
   check passes.

Close `hp_municipality_harmonised.xlsx` before rerunning the export cell. An
open workbook is locked by Excel on Windows and cannot be overwritten; the
notebook raises an explicit `PermissionError` with that instruction.

The workflow is deterministic: two consecutive executions produced a
byte-identical audit Parquet file and an identical workbook.

---

## 14. Methodological limitations

These must be reported whenever the harmonised data are used.

- **The national stock is a modelled stock from the market report.** It is
  calculated from historical domestic sales and an assumed 20-year technical
  service life, not observed by a census of installations. Every downstream
  value inherits this.
- **Households are not identical to heat-pump installations.** The Stage 1
  proxy counts households reporting heat-pump use. One household may operate
  more than one installation, and one installation may serve several
  households. The source also counts a household once for every energy carrier
  it uses, so carrier rows overlap.
- **The federal-state values are modelled distributions**, not observed
  federal-state stocks. They combine a modelled national total with a
  survey-based household distribution.
- **The municipality values are not observed stocks.** They are the result of a
  proportional split within each federal state.
- **All residential buildings are weighted equally in the main variant.** A
  building with three dwellings enters with the same weight as a
  single-family house.
- **Multi-dwelling buildings may be served by one shared installation.** The
  relationship between dwellings, households and installations is not modelled;
  the sensitivity variant of Section 8 quantifies how much this matters
  (−2,059 to +50 units per municipality) but does not resolve it.
- **The building classes are derived from percentage shares rounded to one
  decimal place**, not from published absolute counts. The derived class counts
  carry a rounding uncertainty of up to ±0.05 % · `Gebäude gesamt` per class;
  at federal-state level this shows up as a deviation of at most 0.077 %
  against the source's own state rows.
- **The temporal references of stock and proxies are not fully identical.** The
  stock refers to 2024 (reference date 2024-12-31), the household proxy to the
  survey period 2023/2024, and the building proxy to 2024 at territorial status
  2026. These are tracked separately and are never equated.
- **The method produces a plausible spatial distribution, not an exact
  reconstruction of real installation sites.** It is a mass-preserving
  proportional allocation, not an inventory. It must not be interpreted as
  identifying which buildings actually have a heat pump.
- **No alternative proxy was calibrated against observed municipal heat-pump
  data**, because no such observation exists in this project. The literature of
  Section 15 supports the choice of method and of a building-related proxy; it
  is not empirical evidence for any individual municipality estimate.

---

## 15. Scientific references

The four publications below are located in `harmonisation/literature/`,
outside this project folder. They are cited bibliographically; the notebook
does not read or parse them, and no additional literature from the internet is
used.

- Patil, S., Pflugradt, N., Weinand, J. M., Stolten, D., Kropp, J. (2024). A
  systematic review of spatial disaggregation methods for climate action
  planning. *Energy and AI*, 17, 100386.
  <https://doi.org/10.1016/j.egyai.2024.100386> — supports classifying the
  procedure implemented here as a **proxy-data-based, mass-preserving spatial
  disaggregation**, one of the principal method families identified in that
  review alongside machine-learning and geostatistical model-based approaches.
- Comber, A., Zeng, W. (2019). Spatial interpolation using areal features: A
  review of methods and opportunities using new forms of data with coded
  illustrations. *Geography Compass*, 13(10), e12465.
  <https://doi.org/10.1111/gec3.12465> — supports the use of **suitable
  ancillary information** instead of naive areal (area-proportional)
  weighting. Here the ancillary information is the municipal residential
  building stock, not municipal area.
- Marinello, S., Piccinini, G., Coruzzolo, A. M., Lolli, F., Gamberini, R.
  (2024). Downscaling atmospheric emission inventories with "top–down"
  approach: the support of the literature in choosing proxy variables.
  *International Journal of Environmental Science and Technology*, 21,
  7353–7366. <https://doi.org/10.1007/s13762-024-05490-2> — supports the
  requirement that a top-down proxy variable be **substantively related to the
  target quantity**. A heating heat pump is installed in a building, so the
  residential building stock is the substantively appropriate proxy family.
- Zapparoli, L., Oneto, A., Parajeles Herrera, M., Gjorgiev, B., Hug, G.,
  Sansavini, G. (2025). Future Deployment and Flexibility of Distributed Energy
  Resources in the Distribution Grids of Switzerland. *Scientific Data*, 12,
  1491. <https://doi.org/10.1038/s41597-025-05830-y> — allocates heat pumps to
  individual buildings taken from a building registry and
  derives their rating from building attributes (construction period,
  construction type, heating area). Supports the use of **building-register
  information as the carrier of heat-pump allocation**, and locates rating, COP
  and load-profile modelling in the later scenario stage — explicitly outside
  the scope of this workflow.

These publications support the **method category** and the choice of a
building-related proxy. **They do not prescribe the specific Austrian
distribution key used here.** The concrete Austrian calculation is an own,
transparently documented application to the data available in this project,
and none of these sources is empirical evidence of the actual municipal
heat-pump distribution in Austria.
