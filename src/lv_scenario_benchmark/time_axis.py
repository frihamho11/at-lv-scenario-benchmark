"""Common reference-time-axis helpers for benchmark time-series data."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class TimeAxisError(ValueError):
    """Raised when profile timestamps cannot be mapped to the benchmark axis."""


@dataclass(frozen=True)
class TimeAlignmentResult:
    """Aligned profile frame plus source-to-reference provenance."""

    frame: pd.DataFrame
    mapping: pd.DataFrame


def build_reference_time_index(
    reference_year: int,
    time_step_minutes: int = 15,
) -> pd.DatetimeIndex:
    """Return every regular time step of ``reference_year``.

    The end is exclusive and therefore works for leap and non-leap years.
    """

    if reference_year < 1900:
        raise TimeAxisError(
            "reference_year must be >= 1900."
        )

    if (
        time_step_minutes <= 0
        or 1440 % time_step_minutes != 0
    ):
        raise TimeAxisError(
            "time_step_minutes must be positive "
            "and divide 1440 exactly."
        )

    start = pd.Timestamp(
        year=reference_year,
        month=1,
        day=1,
    )

    end = pd.Timestamp(
        year=reference_year + 1,
        month=1,
        day=1,
    )

    return pd.date_range(
        start=start,
        end=end,
        inclusive="left",
        freq=f"{time_step_minutes}min",
        name="time",
    )


def analysis_time_steps(
    reference_index: pd.DatetimeIndex,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> tuple[list[int], pd.DatetimeIndex]:
    """Translate an inclusive timestamp window to integer pandapower steps."""

    if reference_index.empty:
        raise TimeAxisError(
            "reference_index must not be empty."
        )

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    if start_ts > end_ts:
        raise TimeAxisError(
            "analysis.start must be <= analysis.end."
        )

    if (
        start_ts < reference_index[0]
        or end_ts > reference_index[-1]
    ):
        raise TimeAxisError(
            "Analysis window lies outside the configured "
            "reference year: "
            f"{reference_index[0]} ... "
            f"{reference_index[-1]}."
        )

    position = pd.Series(
        np.arange(
            len(reference_index),
            dtype=int,
        ),
        index=reference_index,
    )

    try:
        selected = position.loc[
            start_ts:end_ts
        ]
    except KeyError as exc:
        raise TimeAxisError(
            "Could not select the requested "
            "analysis window."
        ) from exc

    selected_index = pd.DatetimeIndex(
        selected.index,
        name="time",
    )

    if selected.empty:
        raise TimeAxisError(
            "Analysis window contains no time steps."
        )

    if (
        selected_index[0] != start_ts
        or selected_index[-1] != end_ts
    ):
        raise TimeAxisError(
            "analysis.start and analysis.end "
            "must lie exactly on the reference "
            "time-step grid."
        )

    return (
        selected.astype(int).tolist(),
        selected_index,
    )


def _parse_source_time(
    frame: pd.DataFrame,
    time_column: str,
) -> pd.DatetimeIndex:
    """Parse and validate a source timestamp column."""

    if time_column not in frame.columns:
        raise TimeAxisError(
            f"Profile frame has no "
            f"{time_column!r} column."
        )

    raw = frame[time_column]

    parsed = pd.to_datetime(
        raw,
        errors="coerce",
        dayfirst=True,
    )

    if parsed.isna().any():
        bad = (
            raw.loc[parsed.isna()]
            .head(5)
            .astype(str)
            .tolist()
        )

        raise TimeAxisError(
            "Could not parse source timestamps "
            f"in {time_column!r}: {bad}"
        )

    if parsed.duplicated().any():
        raise TimeAxisError(
            "Source profile timestamps are not unique."
        )

    return pd.DatetimeIndex(
        parsed,
        name="source_time",
    )


def _validate_source_resolution(
    source_index: pd.DatetimeIndex,
    time_step_minutes: int,
) -> None:
    """Validate constant source time-step resolution."""

    if len(source_index) < 2:
        raise TimeAxisError(
            "At least two source time steps "
            "are required."
        )

    diffs = (
        source_index
        .to_series()
        .diff()
        .dropna()
    )

    expected = pd.Timedelta(
        minutes=time_step_minutes
    )

    if not (diffs == expected).all():
        raise TimeAxisError(
            "Source profile is not a regular "
            f"{time_step_minutes}-minute series."
        )


def validate_native_reference_time(
    frame: pd.DataFrame,
    reference_year: int,
    *,
    time_column: str = "time",
    time_step_minutes: int = 15,
) -> pd.DataFrame:
    """Validate exact agreement with the reference axis.

    This function is intended for source profiles whose timestamps
    already use the canonical benchmark reference-year timestamps.
    No timestamp mapping or shifting is performed.
    """

    observed = _parse_source_time(
        frame,
        time_column,
    )

    expected = build_reference_time_index(
        reference_year,
        time_step_minutes,
    )

    if len(observed) != len(expected):
        raise TimeAxisError(
            f"Native profile has {len(observed)} "
            f"steps; expected {len(expected)} "
            f"for reference year {reference_year}."
        )

    if not observed.equals(expected):
        mismatch = np.flatnonzero(
            observed.to_numpy()
            != expected.to_numpy()
        )

        first = (
            int(mismatch[0])
            if len(mismatch)
            else 0
        )

        raise TimeAxisError(
            "Native profile timestamps do not "
            "match the benchmark reference axis. "
            f"First mismatch at step {first}: "
            f"observed={observed[first]}, "
            f"expected={expected[first]}."
        )

    return pd.DataFrame(
        {
            "time_step": np.arange(
                len(expected),
                dtype=int,
            ),
            "reference_time": expected,
            "source_time": observed,
            "day_shift": np.zeros(
                len(expected),
                dtype=int,
            ),
            "time_shift_minutes": np.zeros(
                len(expected),
                dtype=int,
            ),
        }
    )


def align_annual_sequence_to_reference_year(
    frame: pd.DataFrame,
    reference_year: int,
    *,
    time_column: str = "time",
    time_step_minutes: int = 15,
) -> TimeAlignmentResult:
    """Map a complete annual source sequence to the reference year.

    The function preserves the source values and their original order.
    Only the timestamp column of the aligned frame is replaced by the
    canonical benchmark reference-year axis.

    This is useful for published annual profile datasets whose first
    raw timestamp does not coincide with 1 January 00:00 of the named
    profile year, while the dataset nevertheless contains exactly one
    complete ordered annual sequence.

    The original source timestamps are retained in ``mapping`` for
    provenance.
    """

    source_index = _parse_source_time(
        frame,
        time_column,
    )

    _validate_source_resolution(
        source_index,
        time_step_minutes,
    )

    reference_index = build_reference_time_index(
        reference_year,
        time_step_minutes,
    )

    if len(source_index) != len(reference_index):
        raise TimeAxisError(
            "Annual source profile length does not "
            "match the benchmark reference year. "
            f"Source has {len(source_index)} steps; "
            f"expected {len(reference_index)} "
            f"for reference year {reference_year}."
        )

    aligned = (
        frame
        .reset_index(drop=True)
        .copy()
    )

    aligned[time_column] = reference_index

    timestamp_shift = (
        reference_index
        - source_index
    )

    time_shift_minutes = (
        timestamp_shift
        / pd.Timedelta(minutes=1)
    ).astype(int)

    day_shift = (
        reference_index.normalize()
        - source_index.normalize()
    ).days

    mapping = pd.DataFrame(
        {
            "time_step": np.arange(
                len(reference_index),
                dtype=int,
            ),
            "reference_time": reference_index,
            "source_time": source_index,
            "day_shift": day_shift,
            "time_shift_minutes": (
                time_shift_minutes
            ),
        }
    )

    return TimeAlignmentResult(
        frame=aligned,
        mapping=mapping,
    )


def _normalize_source_to_fixed_daily_grid(
    frame: pd.DataFrame,
    *,
    time_column: str = "time",
    time_step_minutes: int = 15,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize a DST-affected annual profile to a fixed daily grid.

    SimBench uses local wall-clock timestamps without explicit timezone
    information. Consequently, daylight-saving-time transitions can
    produce missing timestamps in spring and duplicate timestamps in autumn.

    The benchmark uses a fixed number of time steps per day. Therefore,
    each source day is normalized to a regular local-time grid:

    * duplicate wall-clock slots are averaged;
    * missing wall-clock slots are linearly interpolated;
    * normal days remain unchanged.

    The returned metadata records which source days required normalization.
    """

    if time_column not in frame.columns:
        raise TimeAxisError(
            f"Profile frame has no {time_column!r} column."
        )

    raw_time = frame[time_column]
    parsed_time = pd.to_datetime(
        raw_time,
        errors="coerce",
        dayfirst=True,
    )

    if parsed_time.isna().any():
        bad = (
            raw_time.loc[parsed_time.isna()]
            .head(5)
            .astype(str)
            .tolist()
        )
        raise TimeAxisError(
            "Could not parse source timestamps "
            f"in {time_column!r}: {bad}"
        )

    source_years = sorted(
        set(parsed_time.dt.year.astype(int))
    )

    if len(source_years) != 1:
        raise TimeAxisError(
            "Source profile must belong to one calendar year. "
            f"Observed years: {source_years}"
        )

    source_year = source_years[0]

    if (
        time_step_minutes <= 0
        or 1440 % time_step_minutes != 0
    ):
        raise TimeAxisError(
            "time_step_minutes must be positive "
            "and divide 1440 exactly."
        )

    steps_per_day = 1440 // time_step_minutes

    expected_slots = pd.timedelta_range(
        start="0min",
        periods=steps_per_day,
        freq=f"{time_step_minutes}min",
    )

    expected_days = pd.date_range(
        start=pd.Timestamp(
            year=source_year,
            month=1,
            day=1,
        ),
        end=pd.Timestamp(
            year=source_year + 1,
            month=1,
            day=1,
        ),
        inclusive="left",
        freq="D",
    )

    working = (
        frame
        .reset_index(drop=True)
        .copy()
    )

    working["_parsed_time"] = (
        parsed_time
        .reset_index(drop=True)
    )

    value_columns = [
        column
        for column in working.columns
        if column
        not in {
            time_column,
            "_parsed_time",
        }
    ]

    if not value_columns:
        raise TimeAxisError(
            "Source profile contains no value columns."
        )

    for column in value_columns:
        numeric = pd.to_numeric(
            working[column],
            errors="coerce",
        )

        if numeric.isna().any():
            raise TimeAxisError(
                "Source profile column "
                f"{column!r} contains non-numeric "
                "or missing values."
            )

        working[column] = numeric

    normalized_days: list[pd.DataFrame] = []
    metadata_rows: list[dict[str, object]] = []

    normalized_date = (
        working["_parsed_time"]
        .dt.normalize()
    )

    for day in expected_days:
        daily = working.loc[
            normalized_date == day
        ].copy()

        if daily.empty:
            raise TimeAxisError(
                f"Source profile contains no values for {day.date()}."
            )

        daily["_slot"] = (
            daily["_parsed_time"]
            - daily["_parsed_time"].dt.normalize()
        )

        slot_minutes = (
            daily["_slot"]
            / pd.Timedelta(minutes=1)
        ).to_numpy(dtype=float)

        if not np.allclose(
            np.mod(
                slot_minutes,
                time_step_minutes,
            ),
            0.0,
            rtol=0.0,
            atol=1e-9,
        ):
            raise TimeAxisError(
                "Source profile contains timestamps "
                "outside the configured time-step grid "
                f"on {day.date()}."
            )

        grouped = (
            daily
            .groupby(
                "_slot",
                sort=True,
            )[value_columns]
            .mean()
        )

        unexpected_slots = (
            grouped.index
            .difference(expected_slots)
        )

        if len(unexpected_slots):
            raise TimeAxisError(
                "Source profile contains unexpected "
                f"time-of-day positions on {day.date()}: "
                f"{unexpected_slots[:5].tolist()}"
            )

        original_steps = int(len(daily))
        unique_slots = int(len(grouped))
        duplicate_steps = original_steps - unique_slots
        missing_slots = steps_per_day - unique_slots

        fixed = grouped.reindex(expected_slots)

        if fixed.isna().any().any():
            fixed = fixed.interpolate(
                method="linear",
                axis=0,
                limit_direction="both",
            )

        if fixed.isna().any().any():
            raise TimeAxisError(
                "Could not interpolate all missing "
                f"time slots for {day.date()}."
            )

        fixed = fixed.reset_index(drop=True)

        fixed.insert(
            0,
            time_column,
            pd.DatetimeIndex(
                [
                    day + slot
                    for slot in expected_slots
                ]
            ),
        )

        normalized_days.append(fixed)

        metadata_rows.append(
            {
                "source_day": day,
                "original_steps": original_steps,
                "unique_wall_clock_slots": unique_slots,
                "duplicate_steps": duplicate_steps,
                "missing_slots": missing_slots,
                "dst_adjusted": bool(
                    duplicate_steps > 0
                    or missing_slots > 0
                ),
            }
        )

    normalized = pd.concat(
        normalized_days,
        ignore_index=True,
    )

    expected_index = pd.date_range(
        start=pd.Timestamp(
            year=source_year,
            month=1,
            day=1,
        ),
        end=pd.Timestamp(
            year=source_year + 1,
            month=1,
            day=1,
        ),
        inclusive="left",
        freq=f"{time_step_minutes}min",
        name="source_time",
    )

    observed_index = pd.DatetimeIndex(
        normalized[time_column],
        name="source_time",
    )

    if not observed_index.equals(expected_index):
        raise TimeAxisError(
            "DST normalization did not create "
            "the expected fixed source-year axis."
        )

    metadata = pd.DataFrame(metadata_rows)

    return normalized, metadata


def align_month_day_to_reference_year(
    frame: pd.DataFrame,
    reference_year: int,
    *,
    time_column: str = "time",
    time_step_minutes: int = 15,
) -> TimeAlignmentResult:
    """Map by month/day/time-of-day to the reference year.

    Before mapping, DST-affected source timestamps are normalized to
    a fixed number of time steps per day. This preserves seasonal
    position while making the source compatible with the benchmark's
    fixed 15-minute reference axis.

    For a non-leap reference year, 29 February of a leap-year source
    is naturally unused.
    """

    (
        normalized_source,
        source_day_metadata,
    ) = _normalize_source_to_fixed_daily_grid(
        frame,
        time_column=time_column,
        time_step_minutes=time_step_minutes,
    )

    source_index = pd.DatetimeIndex(
        normalized_source[time_column],
        name="source_time",
    )

    reference_index = build_reference_time_index(
        reference_year,
        time_step_minutes,
    )

    source_year = int(source_index[0].year)

    source_lookup = pd.Series(
        np.arange(
            len(source_index),
            dtype=int,
        ),
        index=source_index,
    )

    desired_source: list[pd.Timestamp] = []

    for target in reference_index:
        try:
            desired_source.append(
                target.replace(
                    year=source_year,
                )
            )
        except ValueError as exc:
            raise TimeAxisError(
                "Reference year contains a date "
                "that does not exist in the source year."
            ) from exc

    desired_index = pd.DatetimeIndex(desired_source)

    missing = desired_index.difference(
        source_lookup.index
    )

    if len(missing):
        raise TimeAxisError(
            "Source profile does not cover all "
            "month/day/time positions required "
            f"by reference year {reference_year}. "
            f"First missing: {missing[0]}"
        )

    source_positions = (
        source_lookup
        .loc[desired_index]
        .to_numpy(dtype=int)
    )

    aligned = (
        normalized_source
        .iloc[source_positions]
        .reset_index(drop=True)
        .copy()
    )

    aligned[time_column] = reference_index

    mapped_source_index = source_index[source_positions]

    metadata_lookup = (
        source_day_metadata
        .set_index("source_day")
    )

    mapped_metadata = (
        metadata_lookup
        .loc[mapped_source_index.normalize()]
        .reset_index(drop=True)
    )

    mapping = pd.DataFrame(
        {
            "time_step": np.arange(
                len(reference_index),
                dtype=int,
            ),
            "reference_time": reference_index,
            "source_time": mapped_source_index,
            "day_shift": np.zeros(
                len(reference_index),
                dtype=int,
            ),
            "source_day_original_steps": (
                mapped_metadata[
                    "original_steps"
                ].to_numpy(dtype=int)
            ),
            "source_day_duplicate_steps": (
                mapped_metadata[
                    "duplicate_steps"
                ].to_numpy(dtype=int)
            ),
            "source_day_missing_slots": (
                mapped_metadata[
                    "missing_slots"
                ].to_numpy(dtype=int)
            ),
            "source_day_dst_adjusted": (
                mapped_metadata[
                    "dst_adjusted"
                ].to_numpy(dtype=bool)
            ),
        }
    )

    return TimeAlignmentResult(
        frame=aligned,
        mapping=mapping,
    )


def align_nearest_same_weekday_to_reference_year(
    frame: pd.DataFrame,
    reference_year: int,
    *,
    time_column: str = "time",
    time_step_minutes: int = 15,
) -> TimeAlignmentResult:
    """Map reference days to nearest same-weekday source days.

    DST-affected source timestamps are normalized first. Each
    reference day is then mapped to the nearest source day with the
    same weekday, while preserving time-of-day exactly.
    """

    (
        normalized_source,
        source_day_metadata,
    ) = _normalize_source_to_fixed_daily_grid(
        frame,
        time_column=time_column,
        time_step_minutes=time_step_minutes,
    )

    source_index = pd.DatetimeIndex(
        normalized_source[time_column],
        name="source_time",
    )

    reference_index = build_reference_time_index(
        reference_year,
        time_step_minutes,
    )

    source_year = int(source_index[0].year)

    source_days = pd.DatetimeIndex(
        source_index
        .normalize()
        .unique()
    )

    source_positions = pd.Series(
        np.arange(
            len(source_index),
            dtype=int,
        ),
        index=source_index,
    )

    day_map: dict[
        pd.Timestamp,
        pd.Timestamp,
    ] = {}

    target_days = pd.DatetimeIndex(
        reference_index
        .normalize()
        .unique()
    )

    for target_day in target_days:
        try:
            nominal_source_day = pd.Timestamp(
                year=source_year,
                month=target_day.month,
                day=target_day.day,
            )
        except ValueError as exc:
            raise TimeAxisError(
                "Could not construct the nominal source date "
                f"for {target_day.date()}."
            ) from exc

        candidates = source_days[
            source_days.weekday
            == target_day.weekday()
        ]

        if candidates.empty:
            raise TimeAxisError(
                "No source weekday candidate "
                f"for {target_day.day_name()}."
            )

        deltas = np.abs(
            (
                candidates
                - nominal_source_day
            ).asi8
        )

        chosen = candidates[
            int(np.argmin(deltas))
        ]

        day_map[target_day] = chosen

    chosen_source_times: list[
        pd.Timestamp
    ] = []

    for target in reference_index:
        source_day = day_map[
            target.normalize()
        ]

        source_time = (
            source_day
            + (
                target
                - target.normalize()
            )
        )

        chosen_source_times.append(
            source_time
        )

    chosen_source_index = pd.DatetimeIndex(
        chosen_source_times
    )

    missing = (
        chosen_source_index
        .difference(
            source_positions.index
        )
    )

    if len(missing):
        raise TimeAxisError(
            "Source profile does not contain "
            "every required intraday timestamp "
            "after DST normalization. "
            f"First missing: {missing[0]}"
        )

    positions = (
        source_positions
        .loc[chosen_source_index]
        .to_numpy(dtype=int)
    )

    aligned = (
        normalized_source
        .iloc[positions]
        .reset_index(drop=True)
        .copy()
    )

    aligned[time_column] = reference_index

    nominal_source_dates: list[
        pd.Timestamp
    ] = []

    for target in reference_index:
        nominal_source_dates.append(
            pd.Timestamp(
                year=source_year,
                month=target.month,
                day=target.day,
            )
        )

    nominal_source_index = pd.DatetimeIndex(
        nominal_source_dates
    )

    day_shift = (
        chosen_source_index.normalize()
        - nominal_source_index
    ).days

    metadata_lookup = (
        source_day_metadata
        .set_index("source_day")
    )

    mapped_metadata = (
        metadata_lookup
        .loc[chosen_source_index.normalize()]
        .reset_index(drop=True)
    )

    mapping = pd.DataFrame(
        {
            "time_step": np.arange(
                len(reference_index),
                dtype=int,
            ),
            "reference_time": reference_index,
            "source_time": chosen_source_index,
            "day_shift": day_shift,
            "source_day_original_steps": (
                mapped_metadata[
                    "original_steps"
                ].to_numpy(dtype=int)
            ),
            "source_day_duplicate_steps": (
                mapped_metadata[
                    "duplicate_steps"
                ].to_numpy(dtype=int)
            ),
            "source_day_missing_slots": (
                mapped_metadata[
                    "missing_slots"
                ].to_numpy(dtype=int)
            ),
            "source_day_dst_adjusted": (
                mapped_metadata[
                    "dst_adjusted"
                ].to_numpy(dtype=bool)
            ),
        }
    )

    weekday_equal = (
        mapping[
            "reference_time"
        ]
        .dt.weekday
        .to_numpy()
        ==
        mapping[
            "source_time"
        ]
        .dt.weekday
        .to_numpy()
    )

    if not weekday_equal.all():
        raise TimeAxisError(
            "Weekday-preserving alignment failed."
        )

    expected_steps = len(reference_index)

    if len(aligned) != expected_steps:
        raise TimeAxisError(
            "Aligned profile has "
            f"{len(aligned)} time steps; "
            f"expected {expected_steps}."
        )

    return TimeAlignmentResult(
        frame=aligned,
        mapping=mapping,
    )