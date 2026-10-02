from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lv_scenario_benchmark.integration.combined_status_quo import (  # noqa: E402
    CombinedStatusQuoConfig,
    CombinedStatusQuoIntegrationError,
    _load_technology_configs,
    _validate_configured_time_axis,
    integrate_combined_status_quo,
)
from lv_scenario_benchmark.integration.ev_pandapower import (  # noqa: E402
    EVPandapowerConfig,
    EVPandapowerIntegrationResult,
)
from lv_scenario_benchmark.integration.hp_pandapower import (  # noqa: E402
    HPPandapowerConfig,
    HPPandapowerIntegrationResult,
)
from lv_scenario_benchmark.integration.pv_pandapower import (  # noqa: E402
    PVPandapowerConfig,
    PVPandapowerIntegrationResult,
)


class CombinedStatusQuoIntegrationTest(unittest.TestCase):
    def _combined_config(
        self,
        root: Path,
        *,
        pv: bool = True,
        ev: bool = True,
        hp: bool = True,
        plot_enabled: bool = True,
    ) -> CombinedStatusQuoConfig:
        base_net = root / "net.p"
        base_net.touch()
        for name in ("pv.yaml", "ev.yaml", "hp.yaml"):
            (root / name).touch()

        return CombinedStatusQuoConfig(
            project_name="Test",
            scenario_id="status_quo_combined",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=base_net,
            output_net_path=root / "integration" / "net_status_quo_combined.p",
            output_dir=root / "integration",
            figure_dir=root / "figures",
            pv_enabled=pv,
            ev_enabled=ev,
            hp_enabled=hp,
            pv_config_path=root / "pv.yaml" if pv else None,
            ev_config_path=root / "ev.yaml" if ev else None,
            hp_config_path=root / "hp.yaml" if hp else None,
            aoi_id="Test",
            aoi_path=root / "aoi.csv",
            grid_buildings_path=root / "buildings.parquet",
            plot_enabled=plot_enabled,
            cleanup_intermediate_files=False,
        )

    def _pv_config(self, root: Path) -> PVPandapowerConfig:
        return PVPandapowerConfig(
            project_name="Test",
            scenario_id="pv_status_quo",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=root / "net.p",
            pv_allocation_path=root / "pv.parquet",
            output_net_path=root / "pv_out.p",
            output_dir=root / "pv_diag",
            profile_path=root / "apcs.csv",
            reference_year=2025,
            time_step_minutes=15,
            time_alignment_method="annual_sequence",
        )

    def _ev_config(self, root: Path) -> EVPandapowerConfig:
        return EVPandapowerConfig(
            project_name="Test",
            scenario_id="ev_status_quo",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=root / "net.p",
            ev_allocation_path=root / "ev.parquet",
            output_net_path=root / "ev_out.p",
            output_dir=root / "ev_diag",
            simbench_source_grid_codes=("1-LV-rural1--2-sw",),
            simbench_expected_ev_profile_count=6,
            reference_year=2025,
            time_alignment_method="nearest_same_weekday",
            time_step_minutes=15,
        )

    def _hp_config(self, root: Path) -> HPPandapowerConfig:
        return HPPandapowerConfig(
            project_name="Test",
            scenario_id="hp_status_quo",
            realisation=0,
            seiler_parameters_path=root / "parameters.py",
            base_net_path=root / "net.p",
            hp_allocation_path=root / "hp.parquet",
            output_net_path=root / "hp_out.p",
            output_dir=root / "hp_diag",
            simbench_source_grid_codes=("1-LV-rural1--2-sw",),
            simbench_expected_hp_profile_count=8,
            reference_year=2025,
            time_alignment_method="month_day",
            time_step_minutes=15,
        )

    @staticmethod
    def _write_time_index(path: Path, n_steps: int = 4) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamps = pd.date_range(
            "2025-01-01 00:00:00",
            periods=n_steps,
            freq="15min",
        )
        pd.DataFrame(
            {
                "time_step": range(n_steps),
                "time": timestamps.astype(str),
            }
        ).to_csv(path, index=False)


    def test_technology_configs_follow_combined_scenario(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = self._combined_config(root)
            config = CombinedStatusQuoConfig(
                **{
                    **config.__dict__,
                    "scenario_id": "high",
                    "realisation": 3,
                    "output_dir": root / "high" / "integration",
                    "output_net_path": (
                        root / "high" / "integration" / "net_high_combined.p"
                    ),
                }
            )

            with (
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_pv_pandapower_config",
                    return_value=self._pv_config(root),
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_ev_pandapower_config",
                    return_value=self._ev_config(root),
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_hp_pandapower_config",
                    return_value=self._hp_config(root),
                ),
            ):
                technology_configs = _load_technology_configs(config)

            allocation_dir = root / "high" / "allocation"
            self.assertEqual(technology_configs["pv"].scenario_id, "high")
            self.assertEqual(technology_configs["ev"].scenario_id, "high")
            self.assertEqual(technology_configs["hp"].scenario_id, "high")
            self.assertEqual(technology_configs["pv"].realisation, 3)
            self.assertEqual(technology_configs["ev"].realisation, 3)
            self.assertEqual(technology_configs["hp"].realisation, 3)
            self.assertEqual(
                technology_configs["pv"].pv_allocation_path,
                allocation_dir / "pv.parquet",
            )
            self.assertEqual(
                technology_configs["ev"].ev_allocation_path,
                allocation_dir / "ev.parquet",
            )
            self.assertEqual(
                technology_configs["hp"].hp_allocation_path,
                allocation_dir / "hp.parquet",
            )

    def test_integrates_pv_ev_hp_in_fixed_order(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = self._combined_config(root)
            pv_config = self._pv_config(root)
            ev_config = self._ev_config(root)
            hp_config = self._hp_config(root)

            seen_base_paths: list[tuple[str, Path]] = []

            def pv_side_effect(stage_config: PVPandapowerConfig):
                seen_base_paths.append(("pv", stage_config.base_net_path))
                stage_config.output_net_path.parent.mkdir(parents=True, exist_ok=True)
                stage_config.output_net_path.touch()
                time_index = stage_config.output_dir / "pv_time.csv"
                self._write_time_index(time_index)
                return PVPandapowerIntegrationResult(
                    pv_count=3,
                    base_sgen_count=0,
                    enriched_sgen_count=3,
                    n_time_steps=4,
                    output_net_path=stage_config.output_net_path,
                    output_files={"time_index_csv": time_index},
                    validation={"all_checks_passed": True},
                )

            def ev_side_effect(stage_config: EVPandapowerConfig):
                seen_base_paths.append(("ev", stage_config.base_net_path))
                stage_config.output_net_path.parent.mkdir(parents=True, exist_ok=True)
                stage_config.output_net_path.touch()
                time_index = stage_config.output_dir / "ev_time.csv"
                self._write_time_index(time_index)
                return EVPandapowerIntegrationResult(
                    ev_count=4,
                    base_load_count=10,
                    enriched_load_count=14,
                    n_time_steps=4,
                    n_profiles_used=2,
                    output_net_path=stage_config.output_net_path,
                    output_files={"time_index_csv": time_index},
                    validation={"all_checks_passed": True},
                )

            def hp_side_effect(stage_config: HPPandapowerConfig):
                seen_base_paths.append(("hp", stage_config.base_net_path))
                stage_config.output_net_path.parent.mkdir(parents=True, exist_ok=True)
                stage_config.output_net_path.touch()
                time_index = stage_config.output_dir / "hp_time.csv"
                self._write_time_index(time_index)
                return HPPandapowerIntegrationResult(
                    hp_count=5,
                    base_load_count=14,
                    enriched_load_count=19,
                    n_time_steps=4,
                    n_profiles_used=3,
                    output_net_path=stage_config.output_net_path,
                    output_files={"time_index_csv": time_index},
                    validation={"all_checks_passed": True},
                )

            combined_validation = {
                "all_checks_passed": True,
                "final_table_counts": {"load": 19, "sgen": 3},
            }
            plot_paths = {
                "combined_map_png": root / "figures" / "combined.png",
                "combined_map_svg": root / "figures" / "combined.svg",
            }

            with (
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_pv_pandapower_config",
                    return_value=pv_config,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_ev_pandapower_config",
                    return_value=ev_config,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_hp_pandapower_config",
                    return_value=hp_config,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.integrate_pv_status_quo",
                    side_effect=pv_side_effect,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.integrate_ev_status_quo",
                    side_effect=ev_side_effect,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.integrate_hp_status_quo",
                    side_effect=hp_side_effect,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo._validate_and_annotate_final_net",
                    return_value=combined_validation,
                ),
                patch(
                    "lv_scenario_benchmark.visualisation.combined_allocation.plot_combined_allocation_map",
                    return_value=plot_paths,
                ) as plot_mock,
            ):
                result = integrate_combined_status_quo(config)

            self.assertEqual(result.enabled_technologies, ("pv", "ev", "hp"))
            self.assertEqual(result.pv_count, 3)
            self.assertEqual(result.ev_count, 4)
            self.assertEqual(result.hp_count, 5)
            self.assertEqual(result.n_time_steps, 4)
            self.assertEqual(result.reference_year, 2025)
            self.assertEqual(result.time_step_minutes, 15)
            self.assertEqual(result.output_net_path, config.output_net_path)

            stage_pv = config.output_dir / "_stage_01_pv.p"
            stage_ev = config.output_dir / "_stage_02_ev.p"
            self.assertEqual(
                seen_base_paths,
                [
                    ("pv", config.base_net_path),
                    ("ev", stage_pv),
                    ("hp", stage_ev),
                ],
            )
            plot_mock.assert_called_once()
            self.assertIn("combined_map_png", result.output_files)
            self.assertTrue((config.output_dir / "combined_validation.json").exists())
            self.assertTrue((config.output_dir / "combined_metadata.json").exists())

    def test_disabled_technologies_are_not_called(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = self._combined_config(
                root,
                pv=False,
                ev=True,
                hp=False,
                plot_enabled=False,
            )
            ev_config = self._ev_config(root)

            def ev_side_effect(stage_config: EVPandapowerConfig):
                stage_config.output_net_path.parent.mkdir(parents=True, exist_ok=True)
                stage_config.output_net_path.touch()
                time_index = stage_config.output_dir / "ev_time.csv"
                self._write_time_index(time_index)
                return EVPandapowerIntegrationResult(
                    ev_count=2,
                    base_load_count=10,
                    enriched_load_count=12,
                    n_time_steps=4,
                    n_profiles_used=1,
                    output_net_path=stage_config.output_net_path,
                    output_files={"time_index_csv": time_index},
                    validation={"all_checks_passed": True},
                )

            with (
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.load_ev_pandapower_config",
                    return_value=ev_config,
                ),
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.integrate_ev_status_quo",
                    side_effect=ev_side_effect,
                ) as ev_mock,
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.integrate_pv_status_quo"
                ) as pv_mock,
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo.integrate_hp_status_quo"
                ) as hp_mock,
                patch(
                    "lv_scenario_benchmark.integration.combined_status_quo._validate_and_annotate_final_net",
                    return_value={"all_checks_passed": True},
                ),
            ):
                result = integrate_combined_status_quo(config)

            self.assertEqual(result.enabled_technologies, ("ev",))
            self.assertEqual(result.ev_count, 2)
            ev_mock.assert_called_once()
            pv_mock.assert_not_called()
            hp_mock.assert_not_called()

    def test_rejects_different_reference_years_before_integration(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pv_config = self._pv_config(root)
            ev_config = self._ev_config(root)
            ev_config = EVPandapowerConfig(
                **{
                    **ev_config.__dict__,
                    "reference_year": 2026,
                }
            )

            with self.assertRaisesRegex(
                CombinedStatusQuoIntegrationError,
                "different reference years",
            ):
                _validate_configured_time_axis(
                    {"pv": pv_config, "ev": ev_config}
                )

    def test_rejects_different_time_step_resolutions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pv_config = self._pv_config(root)
            hp_config = self._hp_config(root)
            hp_config = HPPandapowerConfig(
                **{
                    **hp_config.__dict__,
                    "time_step_minutes": 30,
                }
            )

            with self.assertRaisesRegex(
                CombinedStatusQuoIntegrationError,
                "different time-step resolutions",
            ):
                _validate_configured_time_axis(
                    {"pv": pv_config, "hp": hp_config}
                )

    def test_requires_at_least_one_enabled_technology(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = self._combined_config(
                root,
                pv=False,
                ev=False,
                hp=False,
                plot_enabled=False,
            )
            with self.assertRaisesRegex(
                CombinedStatusQuoIntegrationError,
                "At least one technology",
            ):
                config.validate()


if __name__ == "__main__":
    unittest.main()