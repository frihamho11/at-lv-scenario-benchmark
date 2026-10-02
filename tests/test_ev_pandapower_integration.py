from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lv_scenario_benchmark.integration.ev_pandapower import (  # noqa: E402
    EVPandapowerConfig,
    EVPandapowerIntegrationError,
    integrate_ev_status_quo,
)


class FakeNet(dict):
    """Small pandapowerNet-like object used without the real dependency."""

    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(
            self,
            "bus",
            pd.DataFrame(
                {
                    "node_id": [None, "BD001", "BD002"],
                    "node_type": [None, "BUILDING", "BUILDING"],
                },
                index=[0, 10, 11],
            ),
        )
        object.__setattr__(
            self,
            "load",
            pd.DataFrame(
                {
                    "bus": [10, 11],
                    "p_mw": [0.001, 0.002],
                    "q_mvar": [0.0, 0.0],
                    "name": ["BD001", "BD002"],
                    "in_service": [True, True],
                },
                index=[0, 1],
            ),
        )
        object.__setattr__(self, "line", pd.DataFrame(index=[0]))
        object.__setattr__(self, "trafo", pd.DataFrame(index=[0]))
        object.__setattr__(self, "sgen", pd.DataFrame())
        object.__setattr__(self, "ext_grid", pd.DataFrame(index=[0]))
        object.__setattr__(self, "controller", pd.DataFrame(columns=["object"]))

    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def fake_create_load(net, *, bus, p_mw, q_mvar, name, in_service):
    index = 0 if net.load.empty else int(max(net.load.index)) + 1
    for column in ["bus", "p_mw", "q_mvar", "name", "in_service"]:
        if column not in net.load.columns:
            net.load[column] = None
    net.load.loc[index, ["bus", "p_mw", "q_mvar", "name", "in_service"]] = [
        bus,
        p_mw,
        q_mvar,
        name,
        in_service,
    ]
    return index


class FakeDFData:
    def __init__(self, df):
        self.df = df.copy()


class FakeConstControl:
    def __init__(
        self,
        net,
        *,
        element,
        variable,
        element_index,
        profile_name,
        data_source,
    ):
        self.element = element
        self.variable = variable
        self.element_index = list(element_index)
        self.profile_name = list(profile_name)
        self.data_source = data_source
        index = len(net.controller)
        net.controller.at[index, "object"] = self


def make_fake_simbench_module() -> ModuleType:
    module = ModuleType("simbench")
    module.__version__ = "test"

    relative = pd.DataFrame(
        {
            "time": ["t0", "t1", "t2", "t3"],
            "HLS_A_3.7_pload": [0.0, 1.0, 0.25, 0.0],
            "HLS_A_3.7_qload": [0.0, 1.0, 0.25, 0.0],
            "HLS_B_11.0_pload": [0.0, 0.5, 1.0, 0.0],
            "HLS_B_11.0_qload": [0.0, 0.5, 1.0, 0.0],
            "HLS_A_22.0_pload": [0.25, 1.0, 0.5, 0.0],
            "HLS_A_22.0_qload": [0.25, 1.0, 0.5, 0.0],
            # Workplace profile is deliberately present but must not enter the pool.
            "APLS_A_11.0_pload": [0.0, 0.0, 1.0, 0.0],
            "APLS_A_11.0_qload": [0.0, 0.0, 1.0, 0.0],
        }
    )

    def get_simbench_net(code):
        net = SimpleNamespace()
        net.load = pd.DataFrame(
            {
                "name": [
                    f"{code}_home37",
                    f"{code}_home11",
                    f"{code}_home22",
                    f"{code}_work11",
                    "normal_load",
                ],
                "profile": [
                    "HLS_A_3.7",
                    "HLS_B_11.0",
                    "HLS_A_22.0",
                    "APLS_A_11.0",
                    "H0",
                ],
                "p_mw": [0.0037, 0.0109, 0.0218, 0.0109, 0.001],
                "q_mvar": [0.0014, 0.0043, 0.0086, 0.0043, 0.0],
            },
            index=[100, 101, 102, 103, 104],
        )
        net.profiles = {"load": relative.copy()}
        return net

    module.get_simbench_net = get_simbench_net
    return module


class EVPandapowerSimBenchIntegrationTest(unittest.TestCase):
    def _config(self, root: Path, allocation_path: Path) -> EVPandapowerConfig:
        return EVPandapowerConfig(
            project_name="Test",
            scenario_id="ev_status_quo",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=root / "net.p",
            ev_allocation_path=allocation_path,
            output_net_path=root / "net_status_quo_ev.p",
            output_dir=root / "diagnostics",
            simbench_source_grid_codes=("1-LV-rural-test--2-sw",),
            simbench_ev_profile_prefixes=("HLS_",),
            simbench_expected_ev_profile_count=3,
            profile_assignment_seed=42,
            use_reactive_power=True,
            time_alignment_method="none",
        )

    def _run_with_fakes(self, config, base_net):
        saved = {}
        fake_pp = ModuleType("pandapower")
        fake_pp.from_pickle = lambda _: base_net
        fake_pp.create_load = fake_create_load
        fake_pp.to_pickle = lambda net, path: saved.update({"net": net, "path": path})

        fake_control = ModuleType("pandapower.control")
        fake_control.ConstControl = FakeConstControl
        fake_timeseries = ModuleType("pandapower.timeseries")
        fake_timeseries.DFData = FakeDFData
        fake_sb = make_fake_simbench_module()

        with patch.dict(
            sys.modules,
            {
                "pandapower": fake_pp,
                "pandapower.control": fake_control,
                "pandapower.timeseries": fake_timeseries,
                "simbench": fake_sb,
            },
        ):
            result = integrate_ev_status_quo(config)
        return result, saved

    def test_integrates_home_profiles_and_allows_multiple_evs_per_building(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allocation_path = root / "ev.csv"
            (root / "net.p").touch()

            pd.DataFrame(
                {
                    "allocation_id": ["EV_A", "EV_B", "EV_C"],
                    "building_id": ["BD001", "BD001", "BD002"],
                    "bus_id": [10, 10, 11],
                    "scenario_id": ["ev_status_quo"] * 3,
                    "realisation": [0, 0, 0],
                    "municipality_id": ["31403"] * 3,
                    "vehicle_category": ["BEV_M1"] * 3,
                    "unit_at_building": [1, 2, 1],
                }
            ).to_csv(allocation_path, index=False)

            config = self._config(root, allocation_path)
            base_net = FakeNet()
            result, saved = self._run_with_fakes(config, base_net)

            # Base net remains unchanged and three dedicated EV loads are added.
            self.assertEqual(len(base_net.load), 2)
            self.assertEqual(result.base_load_count, 2)
            self.assertEqual(result.ev_count, 3)
            self.assertEqual(result.enriched_load_count, 5)
            self.assertEqual(result.n_time_steps, 4)

            enriched = saved["net"]
            ev = enriched.load.loc[enriched.load["technology"] == "EV"].copy()
            self.assertEqual(set(ev["allocation_id"]), {"EV_A", "EV_B", "EV_C"})
            self.assertEqual((ev["building_id"] == "BD001").sum(), 2)
            self.assertEqual((pd.to_numeric(ev.loc[ev["building_id"] == "BD001", "bus"]) == 10).sum(), 2)

            # Household-only pool: workplace APLS must never be assigned.
            self.assertTrue(ev["profile_id"].astype(str).str.startswith("HLS_").all())
            self.assertFalse(ev["profile_id"].astype(str).str.startswith("APLS_").any())
            self.assertTrue(ev["charging_power_kw"].isin([3.7, 11.0, 22.0]).all())
            self.assertTrue((pd.to_numeric(ev["electrical_peak_power_kw"]) > 0).all())

            mapping = pd.read_csv(result.output_files["mapping_csv"])
            self.assertEqual(len(mapping), 3)
            self.assertTrue(
                set(mapping["charging_power_kw"].astype(float)).issubset(
                    {3.7, 11.0, 22.0}
                )
            )

            # Saved static values represent t=0, not simultaneous charging peaks.
            for row in mapping.itertuples(index=False):
                load_row = enriched.load.loc[int(row.load_index)]
                if row.profile_id in {"HLS_A_3.7", "HLS_B_11.0"}:
                    self.assertAlmostEqual(float(load_row.p_mw), 0.0)
                elif row.profile_id == "HLS_A_22.0":
                    self.assertAlmostEqual(
                        float(load_row.p_mw), float(row.simbench_peak_p_mw) * 0.25
                    )

            # One p-controller and one q-controller control EV loads only.
            self.assertEqual(len(enriched.controller), 2)
            variables = {controller.variable for controller in enriched.controller["object"]}
            self.assertEqual(variables, {"p_mw", "q_mvar"})
            ev_indices = set(mapping["load_index"].astype(int))
            for controller in enriched.controller["object"]:
                self.assertEqual(set(controller.element_index), ev_indices)
                self.assertEqual(controller.element, "load")
                self.assertEqual(controller.data_source.df.shape, (4, 3))

            self.assertTrue(result.output_files["validation_json"].exists())
            self.assertTrue(result.output_files["relative_profiles_csv_gz"].exists())
            self.assertTrue(enriched["ev_timeseries_metadata"]["home_charging_only"])
            self.assertTrue(
                enriched["ev_timeseries_metadata"]["multiple_evs_per_building_allowed"]
            )

    def test_profile_assignment_is_reproducible(self) -> None:
        from lv_scenario_benchmark.integration.ev_pandapower import (
            _sample_simbench_templates,
        )

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allocation_path = root / "ev.csv"
            allocation = pd.DataFrame(
                {
                    "allocation_id": [f"EV_{idx:02d}" for idx in range(30)],
                    "building_id": [f"BD{idx // 2:03d}" for idx in range(30)],
                    "bus_id": [idx // 2 for idx in range(30)],
                    "scenario_id": ["ev_status_quo"] * 30,
                    "realisation": [0] * 30,
                }
            )
            pool = pd.DataFrame(
                {
                    "profile": ["HLS_A_3.7", "HLS_B_11.0", "HLS_A_22.0"],
                    "p_mw": [0.0037, 0.0109, 0.0218],
                    "q_mvar": [0.0014, 0.0043, 0.0086],
                    "source_grid_code": ["a", "a", "a"],
                    "source_load_index": [1, 2, 3],
                    "source_load_name": ["a1", "a2", "a3"],
                }
            )
            config = self._config(root, allocation_path)
            first = _sample_simbench_templates(allocation, pool, config)
            second = _sample_simbench_templates(allocation, pool, config)
            pd.testing.assert_frame_equal(first, second)

    def test_fails_if_allocation_bus_points_to_other_building(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allocation_path = root / "ev.csv"
            (root / "net.p").touch()
            pd.DataFrame(
                {
                    "allocation_id": ["EV_A"],
                    "building_id": ["BD999"],
                    "bus_id": [10],
                    "scenario_id": ["ev_status_quo"],
                    "realisation": [0],
                }
            ).to_csv(allocation_path, index=False)

            config = self._config(root, allocation_path)
            fake_pp = ModuleType("pandapower")
            fake_pp.from_pickle = lambda _: FakeNet()
            fake_pp.create_load = fake_create_load
            fake_pp.to_pickle = lambda *_: None

            with patch.dict(sys.modules, {"pandapower": fake_pp}):
                with self.assertRaises(EVPandapowerIntegrationError):
                    integrate_ev_status_quo(config)


if __name__ == "__main__":
    unittest.main()
