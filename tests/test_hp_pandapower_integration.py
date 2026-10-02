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

from lv_scenario_benchmark.integration.hp_pandapower import (  # noqa: E402
    HPPandapowerConfig,
    HPPandapowerIntegrationError,
    integrate_hp_status_quo,
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
            "Air_Parallel_1_pload": [0.0, 0.5, 1.0, 0.25],
            "Air_Parallel_1_qload": [0.0, 0.5, 1.0, 0.25],
            "Soil_Alternative_1_pload": [0.25, 1.0, 0.5, 0.0],
            "Soil_Alternative_1_qload": [0.25, 1.0, 0.5, 0.0],
        }
    )

    def get_simbench_net(code):
        net = SimpleNamespace()
        net.load = pd.DataFrame(
            {
                "name": [f"{code}_air", f"{code}_soil", "normal_load"],
                "profile": ["Air_Parallel_1", "Soil_Alternative_1", "H0"],
                "p_mw": [0.006, 0.010, 0.001],
                "q_mvar": [0.0012, 0.0020, 0.0],
            },
            index=[100, 101, 102],
        )
        net.profiles = {"load": relative.copy()}
        return net

    module.get_simbench_net = get_simbench_net
    return module


class HPPandapowerSimBenchIntegrationTest(unittest.TestCase):
    def _config(self, root: Path, allocation_path: Path) -> HPPandapowerConfig:
        return HPPandapowerConfig(
            project_name="Test",
            scenario_id="hp_status_quo",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=root / "net.p",
            hp_allocation_path=allocation_path,
            output_net_path=root / "net_status_quo_hp.p",
            output_dir=root / "diagnostics",
            simbench_source_grid_codes=("1-LV-rural-test--2-sw",),
            simbench_hp_profile_prefixes=("Air_", "Soil_"),
            simbench_expected_hp_profile_count=2,
            profile_assignment_seed=42,
            use_reactive_power=True,
        )

    def test_integrates_profiles_peak_powers_and_const_controls(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allocation_path = root / "hp.csv"
            (root / "net.p").touch()

            pd.DataFrame(
                {
                    "allocation_id": ["HP_A", "HP_B"],
                    "building_id": ["BD001", "BD002"],
                    "bus_id": [10, 11],
                    "scenario_id": ["hp_status_quo", "hp_status_quo"],
                    "realisation": [0, 0],
                    "municipality_id": ["31403", "31403"],
                    "hp_category": ["heating_heat_pump", "heating_heat_pump"],
                }
            ).to_csv(allocation_path, index=False)

            config = self._config(root, allocation_path)
            base_net = FakeNet()
            saved = {}

            fake_pp = ModuleType("pandapower")
            fake_pp.from_pickle = lambda _: base_net
            fake_pp.create_load = fake_create_load
            fake_pp.to_pickle = lambda net, path: saved.update(
                {"net": net, "path": path}
            )

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
                result = integrate_hp_status_quo(config)

            # Input net is still the untouched base net.
            self.assertEqual(len(base_net.load), 2)
            self.assertEqual(result.base_load_count, 2)
            self.assertEqual(result.hp_count, 2)
            self.assertEqual(result.enriched_load_count, 4)
            self.assertEqual(result.n_time_steps, 4)

            enriched = saved["net"]
            hp = enriched.load.loc[enriched.load["technology"] == "HP"].copy()
            self.assertEqual(set(hp["allocation_id"]), {"HP_A", "HP_B"})
            self.assertTrue(hp["profile_id"].notna().all())
            self.assertTrue((pd.to_numeric(hp["electrical_peak_power_kw"]) > 0).all())

            # Saved static values represent t=0, not all HPs at their maxima.
            mapping = pd.read_csv(result.output_files["mapping_csv"])
            for row in mapping.itertuples(index=False):
                load_row = enriched.load.loc[int(row.load_index)]
                if row.profile_id == "Air_Parallel_1":
                    self.assertAlmostEqual(float(load_row.p_mw), 0.0)
                elif row.profile_id == "Soil_Alternative_1":
                    self.assertAlmostEqual(
                        float(load_row.p_mw), float(row.simbench_peak_p_mw) * 0.25
                    )

            # One p-controller and one q-controller control HP loads only.
            self.assertEqual(len(enriched.controller), 2)
            variables = {
                controller.variable for controller in enriched.controller["object"]
            }
            self.assertEqual(variables, {"p_mw", "q_mvar"})
            hp_indices = set(mapping["load_index"].astype(int))
            for controller in enriched.controller["object"]:
                self.assertEqual(set(controller.element_index), hp_indices)
                self.assertEqual(controller.element, "load")
                self.assertEqual(controller.data_source.df.shape, (4, 2))

            self.assertTrue(result.output_files["validation_json"].exists())
            self.assertTrue(result.output_files["relative_profiles_csv_gz"].exists())
            self.assertEqual(
                enriched["hp_timeseries_metadata"]["profile_assignment_seed"], 42
            )

    def test_profile_assignment_is_reproducible(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allocation_path = root / "hp.csv"
            (root / "net.p").touch()
            pd.DataFrame(
                {
                    "allocation_id": [f"HP_{idx:02d}" for idx in range(20)],
                    "building_id": ["BD001"] * 20,
                    "bus_id": [10] * 20,
                    "scenario_id": ["hp_status_quo"] * 20,
                    "realisation": [0] * 20,
                }
            ).to_csv(allocation_path, index=False)

            # This test only exercises assignment reproducibility, therefore allow
            # repeated buildings by calling the internal routine through two valid
            # single-building allocations instead of integration.
            from lv_scenario_benchmark.integration.hp_pandapower import (
                _sample_simbench_templates,
            )

            allocation = pd.DataFrame(
                {
                    "allocation_id": [f"HP_{idx:02d}" for idx in range(20)],
                    "building_id": [f"BD{idx:03d}" for idx in range(20)],
                    "bus_id": range(20),
                    "scenario_id": ["hp_status_quo"] * 20,
                    "realisation": [0] * 20,
                }
            )
            pool = pd.DataFrame(
                {
                    "profile": ["Air_Parallel_1", "Soil_Alternative_1"],
                    "p_mw": [0.006, 0.010],
                    "q_mvar": [0.0012, 0.0020],
                    "source_grid_code": ["a", "a"],
                    "source_load_index": [1, 2],
                    "source_load_name": ["a1", "a2"],
                }
            )
            config = self._config(root, allocation_path)
            first = _sample_simbench_templates(allocation, pool, config)
            second = _sample_simbench_templates(allocation, pool, config)
            pd.testing.assert_frame_equal(first, second)

    def test_fails_if_allocation_bus_points_to_other_building(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allocation_path = root / "hp.csv"
            (root / "net.p").touch()
            pd.DataFrame(
                {
                    "allocation_id": ["HP_A"],
                    "building_id": ["BD999"],
                    "bus_id": [10],
                    "scenario_id": ["hp_status_quo"],
                    "realisation": [0],
                }
            ).to_csv(allocation_path, index=False)

            config = self._config(root, allocation_path)
            fake_pp = ModuleType("pandapower")
            fake_pp.from_pickle = lambda _: FakeNet()
            fake_pp.create_load = fake_create_load
            fake_pp.to_pickle = lambda *_: None

            with patch.dict(sys.modules, {"pandapower": fake_pp}):
                with self.assertRaises(HPPandapowerIntegrationError):
                    integrate_hp_status_quo(config)


if __name__ == "__main__":
    unittest.main()
