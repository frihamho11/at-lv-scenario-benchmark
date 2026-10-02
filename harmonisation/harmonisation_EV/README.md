# EV Stock Harmonisation

## 1. Purpose

This directory contains the harmonisation workflow for the observed Austrian
stock of battery-electric passenger cars (BEV, vehicle class M1) at
municipality level.

Target quantity: the estimated number of battery-electric passenger cars of
vehicle class M1 per Austrian municipality at 2025-12-31. Plug-in hybrids and
other vehicle types are excluded. Wallboxes, home-charging shares, charging
power, charging profiles, and building-level allocation are **not** part of
this harmonisation.

The municipality values produced here are **model-based estimates**, not
observed municipality-level BEV counts. The method is mass-preserving:
population is used only to distribute the observed registration-district
passenger-car stock within a registration district; the observed
passenger-car stock itself is the higher-level transport proxy that
distributes the observed federal-state BEV stock. No charging-infrastructure
assumptions are included anywhere in this chain.

The project structure, configuration and path handling, data validation,
auditability, and the manual-review workflow follow the sibling
`harmonisation_PV` workflow as closely as possible. The subject-matter
method is independent of it.

---

## 2. Role in the thesis

As with the PV workflow, the municipality level serves as a stable
administrative intermediate level for later scenario development and grid
simulation. This directory covers only the harmonisation of the observed EV
stock; scenarios, building-level allocation, and network simulation are
separate, later stages of the thesis.

---

## 3. Canonical workflow

```text
notebooks/ev_stock_harmonisation.ipynb
```

Operate it the same way as the PV notebook:

1. place the raw/reference input files in `data/`;
2. run the notebook from top to bottom;
3. if `outputs/registration_district_review.xlsx` was generated or updated,
   inspect and, where justified, complete the pending rows;
4. rerun the notebook;
5. obtain `outputs/ev_municipality_harmonised.xlsx` and
   `outputs/ev_municipality_audit.parquet` once every review case is
   resolved.

The notebook does not read, parse, decrypt, or otherwise depend on the
methodological literature PDFs. Those live outside this project folder, in
the shared `harmonisation/literature/` directory, and are cited
bibliographically only (Section 19).

---

## 4. Directory structure

```text
harmonisation_EV/
├── data/
│   ├── kfz-bestand_2025.ods
│   ├── population_austria.ods
│   ├── municipalities_clean.xlsx
│   └── kfz_bestand_pro_1000.csv                (canonical, validation-only, see Section 5)
├── notebooks/
│   └── ev_stock_harmonisation.ipynb             (the only notebook in the canonical workflow)
├── outputs/
│   └── registration_district_review.xlsx
└── README.md
```

`harmonisation_EV/` contains **only** these four top-level components —
`data/`, `notebooks/`, `outputs/`, `README.md` — the same basic structure as
the PV workflow. `outputs/` additionally gains
`ev_municipality_harmonised.xlsx` and `ev_municipality_audit.parquet` once
the pending review is resolved and export is unblocked (Section 14).

Everything not required by the canonical workflow has been moved (not
deleted; this project has no version control to recover a deletion) to a
shared archive one level up, outside either project folder:

```text
harmonisation/archive/ev_harmonisation_pre_refactor/
├── Textdokument (neu).txt                        (unrelated notes, out of scope)
├── notebooks/
│   └── ev_bestand_harmonisation.ipynb            (superseded pre-refactor notebook)
└── data/
    ├── PKW_Bundesland_Energiequelle.csv          (redundant control extract of tab_3)
    ├── Quellen.txt                                (source notes, content merged into Section 18)
    └── reference/
        └── municipality_registration_district_crosswalk.csv   (superseded, manually maintained crosswalk)
```

None of these five files are raw inputs of the canonical workflow — they
were either produced by an earlier iteration of this same project or are
unrelated notes that never fed the notebook. Nothing in
`ev_stock_harmonisation.ipynb` reads from `archive/`. The complete
municipality-to-registration-district mapping is generated reproducibly
inside the canonical notebook itself (Section 8).

---

## 5. Input data

All four files below are required inputs, checked together at the start of
the notebook (Section 3): if any are missing, the notebook stops
immediately with a single `FileNotFoundError` naming every missing file,
rather than failing later at an unrelated file-open step.

### `data/kfz-bestand_2025.ods` — sole canonical vehicle-stock source

Statistik Austria, passenger-car stock at 2025-12-31.

| Sheet | Use |
|---|---|
| `tab_1` | National control totals ("Personenkraftwagen Kl. M1 insgesamt", "Elektro") |
| `tab_3` | Passenger-car stock by energy source × federal state — rows "Elektro" (federal-state BEV stock) and "Pkw insgesamt" (federal-state total passenger-car stock) |
| `tab_6` | Population by federal state / chartered city — read and used in Section 9a for a supplementary, non-blocking population plausibility check |
| `tab_7` | Passenger-car stock by federal state and **registration district** — column "Pkw" |

`data/PKW_Bundesland_Energiequelle.csv` is a redundant control extract of
`tab_3` (values were checked and are identical) and is **not read at all**:
it is not used as a parallel calculation input and not used for any
validation check either.

### `data/kfz_bestand_pro_1000.csv` — canonical validation-only input

This file **is** read by the notebook (Section 9a), not merely excluded. It
is a canonical part of the workflow in the sense that it is a documented,
required part of the reproducible validation story — but it is **not an
allocation input**: its passenger-cars-per-1,000-inhabitants values (2024-12-31,
political-district level) are never permitted to influence allocation
weights or any final `unit_count`. What the notebook actually does with it:
multiplies each political district's rate by its own population at the
matching reference date (2025-01-01, the "population zu Jahresbeginn"
counterpart of 2024-12-31) to obtain an independently implied passenger-car
total, aggregates that to federal-state level, and compares it against the
`tab_3` federal-state total from the *actual* allocation source
(2025-12-31) as a labelled **cross-period** plausibility check
(`validation_only_plausibility` in the output workbook). This never gates
`all_critical_checks_passed`.

### `data/population_austria.ods`, sheet "Insgesamt"

Statistik Austria, population at the beginning of the year. Contains
municipality, political-district, and federal-state levels for 2002–2026.
Used here for two purposes, both already canonical:

- municipality population at **2026-01-01** (`population_reference_date`);
- political-district names (3-digit rows), used only to build the default
  political-district-to-registration-district mapping and to label review
  rows — no new file dependency is introduced for this.

### `data/municipalities_clean.xlsx`, sheet "municipalities"

Municipality master data (2,092 municipalities including Vienna as GKZ
`90001`): `municipality_id`, `municipality_name`, `status`, `primary_postcode`,
`all_postcodes`. Postcodes are not needed for this harmonisation.

---

## 6. Vehicle category definition

The Statistik Austria category "Elektro" is, by construction, purely
battery-electric: plug-in and non-plug-in hybrids are recorded separately
under the "Benzin/Elektro (hybrid)" and "Diesel/Elektro (hybrid)" categories
and are never included in "Elektro". No additional filtering step is
required to exclude plug-in hybrids from `unit_count`.

"Pkw" in this Statistik Austria publication refers specifically to vehicle
class M1 (`tab_1` labels the corresponding row "Personenkraftwagen Kl. M1
insgesamt"), matching the target definition.

---

## 7. Reference dates

Vehicle and population reference dates are tracked separately and are not
equated:

```text
reference_date            = 2025-12-31   (vehicle stock)
population_reference_date = 2026-01-01   (population)
```

The official municipality population at 1 January 2026 is used as the
spatial weighting variable. This date immediately follows the vehicle-stock
reference date of 31 December 2025; it is not a replacement value for a
missing 31 December population figure. `tab_6` references the same
administrative status ("Gebietsstand 01.01.2026"), which supports the
consistency of the two dates.

---

## 8. Municipality-to-registration-district mapping

The complete mapping is generated reproducibly inside the notebook — there
is no manually maintained full crosswalk CSV to edit. The workflow:

1. **Deterministic default mapping**: a political district (from
   `municipality_id[:3]`) is assigned automatically when its normalised name
   matches the normalised name of exactly one registration district in the
   same federal state. Normalisation is limited to whitespace collapse,
   case-folding, two fixed and documented Austrian abbreviation expansions
   ("St." → "Sankt", "Wr." → "Wiener"), and removal of parenthesis
   punctuation together with a purely generic trailing "Bezirk" qualifier.
   This is exact, deterministic matching — **no fuzzy string matching or
   similarity scoring is used anywhere in this workflow**. Two explicit
   guards run before the match dictionary is built: no two
   registration-district labels within the same federal state may
   normalise to the same name, and no political district may match more
   than one registration-district row; either condition raises an explicit
   error instead of allowing a silent first-match (`iloc[0]`) or a
   dictionary construction that silently overwrites an earlier match. The
   same principle applies to parenthetical-reference matching (Section 9,
   rule 2): zero matches defers to the next rule, exactly one match is
   applied, and more than one match raises an explicit ambiguity error.
2. **Documented single-municipality / district-remainder overrides**
   (Section 10) take precedence over the default mapping where the source
   table structure requires it.
3. **Generic ambiguity detection** (Section 9) for whatever remains: any
   political district that corresponds to more than one registration
   district in the source data.
4. Unresolved cases are written to an editable Excel review workbook.
5. Only approved, valid review decisions are applied.
6. The complete mapping is validated (uniqueness, completeness, exact
   existence of every applied registration-district name in the `tab_7`
   source).
7. The final mapping is included in the audit output, not treated as a raw
   input file.

The mapping was validated for the administrative and statistical data
release used in this workflow (see Section 16 for the currently observed
result).

---

## 9. Generic ambiguity-review workflow

The ambiguity detector does not contain any logic specific to the
municipality named Liezen, does not hard-code the number of unresolved
municipalities, and does not treat political district 612 as the only
possible future ambiguous case. Conceptually:

```text
if a political district maps uniquely to one registration district:
    apply the automatic mapping
elif a documented single-municipality override exists:
    apply the override
else:
    mark all affected municipalities for review
```

Candidate registration districts are associated with a political district
by exactly three rules, applied in this order and recorded with full
evidence for every candidate (not merely the fact that some
registration-district row was left unused):

1. **`direct_self_match`** — the political district's own normalised name
   equals a registration district's normalised name in the same federal
   state.
2. **`parenthetical_reference`** — an otherwise-unclaimed registration
   district row ends in "(&lt;name&gt;)", where `&lt;name&gt;` normalises to
   match another political district's own name in the same federal state.
3. **`unclaimed_fallback_unique_ambiguous_district_in_state`** — a
   registration-district row with no direct or referential attribution at
   all. This is only ever applied automatically when *exactly one* political
   district in the same federal state is already ambiguous from rules 1–2
   (there is no other candidate district it could be confused with). If
   zero, or more than one, such district exists in a future data release,
   the notebook raises an explicit error instead of guessing — this is what
   keeps the mechanism logically valid if more than one ambiguous political
   district exists at the same time, rather than silently relying on there
   being only one, which is a known limitation of a naive "attribute every
   leftover row to whatever is already ambiguous" rule that this workflow
   deliberately does not use.

A political district is generically ambiguous once it has **more than one**
associated candidate.

For the data release currently used in this workflow, this mechanism
identifies exactly political district 612 (Liezen) as ambiguous, with
candidates `Liezen` (rule 1), `Bad Aussee (Liezen)` (rule 2), and
`Pol. Exp. Gröbming` (rule 3). This is the *currently observed application*
of the generic mechanism, not a hard-coded special case — see the full
evidence trail below.

### Candidate-detection diagnostics

`candidate_detection_diagnostics` (notebook Section 11a; also exported as a
workbook sheet) lists, for every ambiguous political district and every one
of its candidates: `political_district_id`, `political_district_name`,
`candidate_registration_districts`, `candidate_detection_rule`, `evidence`,
and `number_of_affected_municipalities`. For the current data release:

| political_district_id | political_district_name | candidate_registration_districts | candidate_detection_rule | number_of_affected_municipalities |
|---|---|---|---|---:|
| 612 | Liezen | Bad Aussee (Liezen) | parenthetical_reference | 29 |
| 612 | Liezen | Liezen | direct_self_match | 29 |
| 612 | Liezen | Pol. Exp. Gröbming | unclaimed_fallback_unique_ambiguous_district_in_state | 29 |

(the `evidence` column, omitted above for width, spells out the exact
textual match or fallback reasoning for each row).

### Review workbook

`outputs/registration_district_review.xlsx`, sheet
`registration_district_review`, one row per unresolved municipality:

| Column | Editable |
|---|---|
| `municipality_id`, `municipality_name`, `political_district_id`, `political_district_name`, `review_reason`, `candidate_registration_districts`, `suggested_registration_district` | No — auto-generated |
| `review_status`, `approved_registration_district`, `review_note` | Yes |

`review_reason = multiple_registration_districts` for all currently
generated rows. `candidate_registration_districts` lists the candidates in a
deterministic, readable format, e.g. `Liezen | Bad Aussee (Liezen) | Pol.
Exp. Gröbming`. `suggested_registration_district` is intentionally left
blank: no principled ranking exists among the candidates without an
authoritative administrative reference applicable to the registration-district
structure used in the vehicle-stock source, and suggesting one would amount
to a guess.

Allowed `review_status` values: `pending_review`, `approved`, `rejected`,
`insufficient_information`.

Formatting follows the PV review workbook: frozen header row, autofilter, a
formatted table, dropdown validation on `review_status` and on
`approved_registration_district` (restricted to the valid candidates for
each row's own group), status-based conditional formatting
(pending_review = yellow, approved = green, rejected = red,
insufficient_information = orange), highlighted editable columns,
`municipality_id`/`political_district_id` stored as text, and an
accompanying instructions sheet.

A row is applied only if **both** hold: `review_status = approved` **and**
`approved_registration_district` is one of that row's own candidate values.
An approved row with an invalid or empty assignment is treated as a critical
validation failure. Manual decisions are preserved by `municipality_id`
across notebook reruns; rows that no longer correspond to a currently
unresolved mapping are reported, not silently dropped. An open or locked
review workbook produces a clear error message instead of failing silently.

**Final harmonised outputs remain blocked** while any ambiguous municipality
has no review row, a `review_status` other than `approved`, an empty
approved registration district, or an approved registration district
outside its candidate set. No partial national output is written; the
affected federal state is never silently omitted.

---

## 10. Documented automatic overrides

Kept as a compact, hard-coded, documented configuration section — not
inferred from `status` values (`SR`/`ST`/`M`) and not derived from any
generic textual pattern, because the source-table structure behind them is
already known:

| Municipality / group | Registration district | Why the default mapping is not sufficient |
|---|---|---|
| Eisenstadt | Eisenstadt (Stadt inkl. Rust) | `tab_7` merges Eisenstadt's registration district with Rust |
| Rust | Eisenstadt (Stadt inkl. Rust) | No separate registration district for Rust in `tab_7` |
| Klosterneuburg | Klosterneuburg (BH Tulln) | Separate registration district, carved out of political district Tulln |
| Schwechat | Schwechat | Separate registration district, carved out of political district Bruck an der Leitha |
| Leoben (city) | Leoben (Stadt) | `tab_7` splits political district Leoben into a city and a remaining part |
| Remaining municipalities of political district Leoben | Leoben (Land) | Documented district-remainder override for the same split |
| Vienna | — (direct) | Vienna is simultaneously a federal state and a municipality; no registration-district disaggregation applies |

### Override validation table

Notebook Section 10a re-derives, from the actual municipality master data
(not asserted), exactly which and how many municipalities each override
rule affects — the traceability behind the "5 single-municipality overrides
+ 15 district-remainder-override municipalities = 20" total reported in
Section 16:

| override_type | political_district_id | target_registration_district | affected_municipality_ids | number_of_affected_municipalities |
|---|---|---|---|---:|
| single_municipality | 101 | Eisenstadt (Stadt inkl. Rust) | 10101 | 1 |
| single_municipality | 102 | Eisenstadt (Stadt inkl. Rust) | 10201 | 1 |
| single_municipality | 321 | Klosterneuburg (BH Tulln) | 32144 | 1 |
| single_municipality | 307 | Schwechat | 30740 | 1 |
| single_municipality | 611 | Leoben (Stadt) | 61108 | 1 |
| district_remainder | 611 | Leoben (Land) | 61101, 61105, 61106, 61107, 61109, 61110, 61111, 61112, 61113, 61114, 61115, 61116, 61118, 61119, 61120 | 15 |

This table is also exported as the `override_validation` sheet in the
harmonised workbook once export is unblocked.

---

## 11. Mathematical disaggregation method

A **hierarchical, mass-preserving proxy chain** — not a statistically
calibrated multi-proxy method:

```text
federal-state BEV stock
    -> registration district, weighted by observed passenger-car stock
    -> municipality, weighted by population
```

For municipality *m* in registration district *z*:

```text
A_m = C_z · (P_m / P_z)
```

where `C_z` is the observed total passenger-car stock of registration
district *z*, `P_m` is the population of municipality *m*, and `P_z` is the
population sum of registration district *z*. `A_m` is the estimated
municipality passenger-car proxy — an intermediate transport proxy, not an
observed municipal car count.

For municipality *m* in federal state *s*:

```text
E_raw_m = E_s · (A_m / Σ_j A_j)      for j in s
```

where `E_s` is the observed federal-state BEV stock and `E_raw_m` is the
unrounded municipality BEV estimate (`estimated_unit_count_raw` — an
estimate, not an observed real value).

Equivalent hierarchical closed form:

```text
E_raw_m = E_s · (C_z / C_s) · (P_m / P_z)
```

No rounding occurs at registration-district level. Integer allocation
happens exactly once, at municipality level (Section 12).

Vienna: `derivation_method = direct_state_to_municipality`,
`data_quality = reported`. All other municipalities:
`derivation_method = registration_district_pkw_population_proxy`,
`data_quality = estimated`.

---

## 12. Largest Remainder integer allocation

Applied separately within each federal state:

```text
estimated_unit_count_floor(m) = floor(E_raw_m)
fractional_remainder(m)       = E_raw_m − estimated_unit_count_floor(m)
shortfall(s)                  = E_s − Σ estimated_unit_count_floor(m)   for m in s
```

The `shortfall(s)` municipalities with the largest `fractional_remainder`
receive `rounding_adjustment = True` (+1). Tie-breaking is an explicit
compound sort key — (fractional remainder descending, `municipality_id`
ascending), built and sorted as its own step — not a reliance on the input
order of the underlying `Series` or on sort stability. A dedicated notebook
cell (Section 4a) tests this with artificial, tied values presented in two
different (scrambled) input orders and asserts both produce the identical
result, with the smallest `municipality_id` always receiving the additional
unit. Result: `Σ unit_count(m) = E_s` exactly, for every federal state.

---

## 13. Validation

The notebook checks, among others:

**Municipality master data** — `municipality_id` unique; municipality count
equals 2,092 for the data release used here; Vienna occurs exactly once; no
missing municipality names.

**Population data** — the `municipality_id` set from
`municipalities_clean.xlsx` exactly equals the `municipality_id` set from
`population_austria.ods`; every municipality has a positive population; no
duplicate population records.

**Vehicle source data** — `tab_3` national BEV and passenger-car totals equal
the `tab_1` totals; federal-state passenger-car totals from `tab_3` equal the
sums of registration-district values from `tab_7`.

**Mapping** — every non-Vienna municipality has exactly one final
registration district; no municipality has multiple final mappings; every
applied registration-district name exists exactly in the parsed `tab_7`
source labels (no fuzzy matching); every approved review assignment belongs
to its row's candidate set; unresolved review cases block final export;
Vienna is excluded from registration-district disaggregation.

**Proxy and allocation** — registration-district population sums are
greater than zero; municipality passenger-car proxies sum to the observed
passenger-car stock of each registration district within numerical
tolerance; unrounded municipality BEV estimates sum to the federal-state BEV
total within tolerance; final integer counts sum exactly to each
federal-state BEV total; the national sum equals 257,717; `unit_count` is
integer, non-negative, and never missing; Largest Remainder tie-breaking is
deterministic.

**Canonical validation-only inputs** — `kfz_bestand_pro_1000.csv` and `tab_6`
are read and produce nine reported plausibility checks (eight cross-period
federal-state checks, one cross-reference population check), all currently
within 5% / 0.1% respectively; none of the nine affects allocation weights,
`unit_count`, or `all_critical_checks_passed`.

**Final harmonised outputs are written only if every critical check above
passes** — the validation-only plausibility checks are informational and
never block export by themselves.

---

## 14. Output files

### `outputs/ev_municipality_harmonised.xlsx`

Canonical sheet `ev_by_municipality`, exactly these seven columns:
`municipality_id, municipality_name, federal_state_code, reference_date,
unit_count, derivation_method, data_quality`. `unit_count` is the estimated
number of battery-electric passenger cars of vehicle class M1 at
2025-12-31. No intermediate variables are included in this sheet.

Additional sheets: `validation`, `federal_state_validation`,
`registration_district_validation`, `final_registration_district_mapping`,
`special_cases`, `override_validation` (Section 10),
`candidate_detection_diagnostics` (Section 9), `validation_only_plausibility`
(Section 9a / 13), `source_metadata`.

### `outputs/ev_municipality_audit.parquet`

All proxy, crosswalk, population, and rounding variables live here, not in
the canonical workbook: population, registration/political district
identifiers and names, mapping method, review status, registration-district
population and passenger-car stock, federal-state totals, population and
passenger-car shares, the passenger-car proxy, the allocation weight, the
unrounded estimate, its floor and fractional remainder, the rounding
adjustment flag, and the final `unit_count`.

Neither file is written while any critical validation fails.

---

## 15. Reproduction

1. Place `kfz-bestand_2025.ods`, `population_austria.ods`,
   `municipalities_clean.xlsx`, and `kfz_bestand_pro_1000.csv` in `data/`.
   The fourth file is a canonical validation-only input — it is read
   unconditionally (missing it stops the notebook with a clear error, see
   Section 3) but must never affect allocation weights or final
   `unit_count` values; it only feeds the non-blocking plausibility checks
   in Section 9a.
2. Run `notebooks/ev_stock_harmonisation.ipynb` from top to bottom.
3. If `outputs/registration_district_review.xlsx` lists `pending_review`
   rows, resolve them against an authoritative administrative reference,
   set `review_status = approved` and `approved_registration_district` to
   one of the listed candidates, add a `review_note`, save, and close the
   file.
4. Rerun the notebook.
5. `outputs/ev_municipality_harmonised.xlsx` and
   `outputs/ev_municipality_audit.parquet` are written once every check
   passes.

---

## 16. Current review status

As last executed against the present data release:

| Metric | Value |
|---|---:|
| Municipalities total | 2,092 |
| Resolved by deterministic default mapping | 2,042 |
| Resolved by a documented override | 20 |
| Ambiguous, pending manual review | 29 (political district 612, Liezen) |
| Federal states fully computable | Burgenland, Kärnten, Niederösterreich, Oberösterreich, Salzburg, Tirol, Vorarlberg, Wien |
| Federal state blocked | Steiermark |
| Final harmonised export completed | No |

The proxy chain and Largest Remainder allocation were independently
re-verified end to end in an isolated test run with the 29 pending rows
provisionally (not authoritatively) approved: all mass-preservation checks
passed exactly, including the national total of 257,717.

---

## 17. Methodological limitations

- Population is a proxy, not an observed municipal passenger-car or BEV
  count; vehicle ownership does not correlate perfectly with population.
- Political district 612 (Liezen) remains unresolved. An authoritative
  administrative reference applicable to the registration-district
  structure used in the vehicle-stock source is required before the
  pending municipality assignments can be approved; it must not be
  resolved by guessing. No specific historical reform date is assumed in
  advance to define which reference is required — that determination is
  part of the still-pending research.
- Rule 3 of the candidate-detection mechanism (Section 9,
  `unclaimed_fallback_unique_ambiguous_district_in_state`) only ever
  attributes an unreferenced leftover registration-district row
  automatically when exactly one political district is already ambiguous
  in the same federal state. If a future data release has an unreferenced
  leftover row alongside zero or multiple already-ambiguous districts in
  the same state, the notebook raises an explicit error rather than
  guessing; the detection rule would then need to be extended deliberately,
  not silently relied upon. This rule is a **bounded candidate-generation
  fallback for manual review only**: it identifies that a registration
  district row plausibly belongs to a given political district's set of
  candidates. It does **not** prove which municipality within that
  district the row corresponds to, it does **not** replace an
  authoritative administrative source, and it never approves or applies a
  final municipality assignment by itself — every municipality it
  generates a candidate list for still requires an explicit `approved`
  decision in the review workbook (Section 9) before it can be included in
  the harmonised output.
- The three cited literature sources (Section 19) support the choice of
  method — a mass-preserving, proxy-based, hierarchical disaggregation using
  population and an observed intermediate transport stock as combined
  proxies — not the empirical correctness of any individual municipality
  estimate.
- `kfz_bestand_pro_1000.csv` and `PKW_Bundesland_Energiequelle.csv` were not
  used as calculation inputs (Section 5).

---

## 18. Source metadata

Transferred from `data/Quellen.txt`:

- `PKW_Bundesland_Energiequelle.csv`: Statistik Austria, Kfz-Bestand,
  <https://www.statistik.at/statistiken/tourismus-und-verkehr/fahrzeuge/kfz-bestand>
  (downloaded 2026-07-23). Not used as a calculation input (Section 5).
- `kfz_bestand_pro_1000.csv`: Statistik Austria, Kfz-Bestand interactive map,
  <https://www.statistik.at/statistiken/tourismus-und-verkehr/fahrzeuge/kfz-bestand>.
  Validation-only (Section 5).
- `population_austria.ods`: Statistik Austria, population at the beginning
  of the year/quarter,
  <https://www.statistik.at/statistiken/bevoelkerung-und-soziales/bevoelkerung/bevoelkerungsstand/bevoelkerung-zu-jahres-/-quartalsanfang>.
- `kfz-bestand_2025.ods`: Statistik Austria, Kfz-Bestand publication for the
  same subject area as above (`tab_1`, `tab_3`, `tab_6`, `tab_7`).

---

## 19. Scientific references

- Patil, S., Pflugradt, N., Weinand, J. M., Stolten, D., Kropp, J. (2024). A
  systematic review of spatial disaggregation methods for climate action
  planning. *Energy and AI*, 17, 100386.
  <https://doi.org/10.1016/j.egyai.2024.100386> — supports the choice of a
  mass-preserving, proxy-data-based disaggregation method and the use of an
  already-available, coarser stock (registration-district passenger cars) as
  an intermediate proxy where no proxy exists directly at municipality
  level.
- Comber, A., Zeng, W. (2019). Spatial interpolation using areal features: A
  review of methods and opportunities using new forms of data with coded
  illustrations. *Geography Compass*, 13(10), e12465.
  <https://doi.org/10.1111/gec3.12465> — supports distinguishing naive areal
  (population-only) weighting from methods that use suitable ancillary data;
  population is used here only within an already-observed
  registration-district passenger-car stock, not as a stand-alone areal
  weight.
- Marinello, S., Piccinini, G., Coruzzolo, A. M., Lolli, F., Gamberini, R.
  (2024). Downscaling atmospheric emission inventories with "top–down"
  approach: the support of the literature in choosing proxy variables.
  *International Journal of Environmental Science and Technology*, 21,
  7353–7366. <https://doi.org/10.1007/s13762-024-05490-2> — identifies
  population as one of the most common proxy variables in the transport
  top-down disaggregation literature and supports combining it with an
  observed intermediate stock.

None of these sources is empirical evidence of the actual municipal BEV
distribution in Austria; they support the choice of method only.
