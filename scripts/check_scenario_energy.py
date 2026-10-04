from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "outputs" / "Grossschoenau_Neu"

DT_H = 0.25  # 15 min


def analyse_technology(project_dir, scenario, technology):
    folder = (
        project_dir
        / scenario
        / "integration"
        / technology
    )

    mapping_path = (
        folder
        / f"{technology}_pandapower_profile_mapping.csv"
    )

    profile_path = (
        folder
        / f"{technology}_simbench_relative_profile_pool.csv.gz"
    )

    if not mapping_path.exists():
        raise FileNotFoundError(mapping_path)

    if not profile_path.exists():
        raise FileNotFoundError(profile_path)

    mapping = pd.read_csv(mapping_path)
    profiles = pd.read_csv(profile_path)

    total_power_mw = pd.Series(
        0.0,
        index=profiles.index,
        dtype=float,
    )

    per_unit = []

    for _, row in mapping.iterrows():
        profile_id = str(row["profile_id"])
        profile_column = f"{profile_id}_pload"

        if profile_column not in profiles.columns:
            raise KeyError(
                f"{profile_column} missing in {profile_path}"
            )

        relative = pd.to_numeric(
            profiles[profile_column],
            errors="raise",
        )

        # Match the EV integration behaviour:
        # very small numerical negative values are clipped to zero.
        if technology == "ev":
            if relative.min() < -1e-4:
                raise ValueError(
                    f"Unexpected negative EV profile: "
                    f"{profile_id}, min={relative.min()}"
                )
            relative = relative.clip(lower=0.0)

        peak_mw = float(row["simbench_peak_p_mw"])

        power_mw = relative * peak_mw

        annual_energy_mwh = (
            power_mw.sum() * DT_H
        )

        total_power_mw += power_mw

        per_unit.append(
            {
                "allocation_id": row["allocation_id"],
                "profile_id": profile_id,
                "simbench_peak_p_mw": peak_mw,
                "annual_energy_mwh": annual_energy_mwh,
            }
        )

    units = pd.DataFrame(per_unit)

    return {
        "scenario": scenario,
        "technology": technology.upper(),
        "units": len(units),
        "annual_energy_mwh": units["annual_energy_mwh"].sum(),
        "mean_energy_per_unit_mwh": units["annual_energy_mwh"].mean(),
        "mean_peak_power_kw": units["simbench_peak_p_mw"].mean() * 1000,
        "median_peak_power_kw": units["simbench_peak_p_mw"].median() * 1000,
        "max_peak_power_kw": units["simbench_peak_p_mw"].max() * 1000,
        "aggregate_peak_mw": total_power_mw.max(),
        "profile_distribution": units["profile_id"].value_counts().to_dict(),
    }


def main():
    project_dir = PROJECT_DIR

    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project directory not found: {project_dir}"
        )

    print("=" * 80)
    print("Scenario energy check")
    print("=" * 80)
    print(f"Project: {project_dir}")
    print(f"Time step: {DT_H} h")
    print()

    results = []

    for scenario in [
        "status_quo",
        "2x_penetration",
    ]:
        for technology in [
            "ev",
            "hp",
        ]:
            print(
                f"Reading {scenario} / {technology.upper()} ..."
            )

            result = analyse_technology(
                project_dir,
                scenario,
                technology,
            )

            results.append(result)

    summary = pd.DataFrame(
        [
            {
                k: v
                for k, v in result.items()
                if k != "profile_distribution"
            }
            for result in results
        ]
    )

    print()
    print("=" * 80)
    print("ENERGY SUMMARY")
    print("=" * 80)
    print(
        summary.to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}",
        )
    )

    print()
    print("=" * 80)
    print("PROFILE DISTRIBUTIONS")
    print("=" * 80)

    for result in results:
        print(
            f"\n{result['scenario']} / "
            f"{result['technology']}:"
        )

        for profile, count in sorted(
            result["profile_distribution"].items()
        ):
            print(
                f"  {profile}: {count}"
            )

    print()
    print("=" * 80)
    print("2x / STATUS-QUO RATIOS")
    print("=" * 80)

    for technology in [
        "EV",
        "HP",
    ]:
        sq = next(
            x
            for x in results
            if x["scenario"] == "status_quo"
            and x["technology"] == technology
        )

        x2 = next(
            x
            for x in results
            if x["scenario"] == "2x_penetration"
            and x["technology"] == technology
        )

        print(f"\n{technology}")

        print(
            "  unit count ratio:       "
            f"{x2['units'] / sq['units']:.4f}"
        )

        print(
            "  annual energy ratio:    "
            f"{x2['annual_energy_mwh'] / sq['annual_energy_mwh']:.4f}"
        )

        print(
            "  energy/unit ratio:      "
            f"{x2['mean_energy_per_unit_mwh'] / sq['mean_energy_per_unit_mwh']:.4f}"
        )

        print(
            "  aggregate peak ratio:   "
            f"{x2['aggregate_peak_mw'] / sq['aggregate_peak_mw']:.4f}"
        )

    sq_ev = next(
        x
        for x in results
        if x["scenario"] == "status_quo"
        and x["technology"] == "EV"
    )

    sq_hp = next(
        x
        for x in results
        if x["scenario"] == "status_quo"
        and x["technology"] == "HP"
    )

    x2_ev = next(
        x
        for x in results
        if x["scenario"] == "2x_penetration"
        and x["technology"] == "EV"
    )

    x2_hp = next(
        x
        for x in results
        if x["scenario"] == "2x_penetration"
        and x["technology"] == "HP"
    )

    sq_total = (
        sq_ev["annual_energy_mwh"]
        + sq_hp["annual_energy_mwh"]
    )

    x2_total = (
        x2_ev["annual_energy_mwh"]
        + x2_hp["annual_energy_mwh"]
    )

    print()
    print("=" * 80)
    print("COMBINED EV + HP")
    print("=" * 80)

    print(
        f"Status quo EV + HP energy: "
        f"{sq_total:.4f} MWh"
    )

    print(
        f"2x EV + HP energy:         "
        f"{x2_total:.4f} MWh"
    )

    print(
        f"2x / SQ ratio:             "
        f"{x2_total / sq_total:.4f}"
    )

    print()
    print("=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()