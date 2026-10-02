"""Focused tests for the PV -> pandapower -> APCS integration."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from lv_scenario_benchmark.integration.pv_pandapower import (
    PVPandapowerConfig,
    PVPandapowerIntegrationError,
    _validate_bus_mapping,
    build_pv_absolute_timeseries,
    load_apcs_pv_profile,
)


class FakeNet:
    def __init__(self) -> None:
        self.bus = pd.DataFrame(
            {"node_id": ["BD001", "BD002"]}, index=[10, 11]
        )
        self.sgen = pd.DataFrame()


class TestPVPandapowerIntegration(unittest.TestCase):
    def _config(self, root: Path) -> PVPandapowerConfig:
        return PVPandapowerConfig(
            project_name="Testgebiet",
            scenario_id="pv_status_quo",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=root / "net.p",
            pv_allocation_path=root / "pv.csv",
            output_net_path=root / "net_status_quo_pv.p",
            output_dir=root / "out",
            profile_path=root / "APCS_synthload_2025.csv",
            nominal_power_kwp=12.0,
        )

    def test_peak_normalizes_apcs_profile_to_zero_one(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "APCS_synthload_2025.csv"
            path.write_text(
                "Typnummer;Zeit;Wert\n"
                "15;2025-06-01T12:00:00;0,05\n"
                "15;2025-06-01T12:15:00;0,10\n"
                "15;2025-06-01T12:30:00;0,00\n"
                "1;2025-06-01T12:00:00;0,90\n",
                encoding="latin1",
            )

            profile = load_apcs_pv_profile(path)

            self.assertEqual(len(profile), 3)
            self.assertAlmostEqual(float(profile["pv_pu"].min()), 0.0)
            self.assertAlmostEqual(float(profile["pv_pu"].max()), 1.0)
            self.assertAlmostEqual(float(profile.iloc[0]["pv_pu"]), 0.5)

    def test_12_kwp_peak_becomes_0012_mw(self) -> None:
        mapping = pd.DataFrame(
            {
                "allocation_id": ["PV_A", "PV_B"],
                "nominal_power_kwp": [12.0, 12.0],
            }
        )
        profile = pd.DataFrame(
            {
                "time": pd.to_datetime(
                    ["2025-06-01T12:00:00", "2025-06-01T12:15:00"]
                ),
                "pv_pu": [0.5, 1.0],
            }
        )

        absolute, _ = build_pv_absolute_timeseries(mapping, profile)

        self.assertAlmostEqual(float(absolute.loc[0, "PV_A"]), 0.006)
        self.assertAlmostEqual(float(absolute.loc[1, "PV_A"]), 0.012)
        self.assertAlmostEqual(float(absolute.loc[1, "PV_B"]), 0.012)

    def test_bus_building_mismatch_is_detected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            config = self._config(Path(temporary_directory))
            allocation = pd.DataFrame(
                {
                    "allocation_id": ["PV_A"],
                    "building_id": ["BD999"],
                    "bus_id": [10],
                    "scenario_id": ["pv_status_quo"],
                    "realisation": [0],
                }
            )

            with self.assertRaises(PVPandapowerIntegrationError):
                _validate_bus_mapping(FakeNet(), allocation, config)

    def test_output_must_not_overwrite_base_net(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = self._config(root)
            invalid = PVPandapowerConfig(
                **{
                    **config.__dict__,
                    "output_net_path": config.base_net_path,
                }
            )

            with self.assertRaises(PVPandapowerIntegrationError):
                invalid.validate()

    def test_profile_rejects_negative_values(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "APCS_synthload_2025.csv"
            path.write_text(
                "Typnummer;Zeit;Wert\n"
                "15;2025-01-01T00:00:00;-0,01\n"
                "15;2025-01-01T00:15:00;0,02\n",
                encoding="latin1",
            )

            with self.assertRaises(PVPandapowerIntegrationError):
                load_apcs_pv_profile(path)


if __name__ == "__main__":
    unittest.main()
