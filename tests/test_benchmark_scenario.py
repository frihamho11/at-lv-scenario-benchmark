from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MODULE_PATH = ROOT / "scripts" / "run_benchmark_scenario.py"
SPEC = importlib.util.spec_from_file_location(
    "run_benchmark_scenario",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
load_scenario = MODULE.load_scenario


class BenchmarkScenarioTest(unittest.TestCase):
    def test_loads_status_quo_factors(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "scenario.yaml"
            path.write_text(
                """
case:
  scenario_id: status_quo
  realisations: 2
penetration_factors:
  pv: 1.0
  ev: 1.0
  hp: 1.0
""".strip(),
                encoding="utf-8",
            )

            scenario_id, realisations, factors = load_scenario(path)

            self.assertEqual(scenario_id, "status_quo")
            self.assertEqual(realisations, 2)
            self.assertEqual(
                factors,
                {"pv": 1.0, "ev": 1.0, "hp": 1.0},
            )

    def test_rejects_non_positive_factor(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "scenario.yaml"
            path.write_text(
                """
case:
  scenario_id: invalid
penetration_factors:
  pv: 0.0
  ev: 1.0
  hp: 1.0
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "penetration_factors.pv",
            ):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
