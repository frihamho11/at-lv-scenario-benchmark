"""Focused unit tests for the PV-coupled BESS implementation.

Repository target:
    tests/test_bess_model.py
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from lv_scenario_benchmark.allocation.bess_status_quo import (
    BESSAllocationConfig,
    round_half_up,
    run_bess_allocation,
)
from lv_scenario_benchmark.integration.bess_pandapower import (
    BESSPandapowerConfig,
    _add_bess_storage_elements,
    _element_active_power_timeseries,
    _load_allocation,
    _validate_combined_net_metadata,
    build_reference_index,
    dispatch_bess_self_consumption,
)


def test_half_up_rounding_is_deterministic() -> None:
    assert round_half_up(0.0) == 0
    assert round_half_up(0.49) == 0
    assert round_half_up(0.50) == 1
    assert round_half_up(2.50) == 3
    assert round_half_up(2.51) == 3


def test_dispatch_charges_from_surplus_and_discharges_to_demand() -> None:
    p_kw, soc, residual_after = dispatch_bess_self_consumption(
        [-5.0, 0.0, 5.0],
        usable_capacity_kwh=10.0,
        p_max_kw=3.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        dt_hours=1.0,
        soc_min=0.20,
        soc_max=1.00,
        initial_soc=0.20,
    )

    np.testing.assert_allclose(p_kw, [3.0, 0.0, -3.0])
    np.testing.assert_allclose(residual_after, [-2.0, 0.0, 2.0])
    np.testing.assert_allclose(soc, [0.44, 0.44, 0.20])


def test_efficiencies_are_applied_to_the_energy_state() -> None:
    p_kw, soc, _ = dispatch_bess_self_consumption(
        [-4.0, 4.0],
        usable_capacity_kwh=10.0,
        p_max_kw=10.0,
        eta_charge=0.8,
        eta_discharge=0.8,
        dt_hours=1.0,
        soc_min=0.20,
        soc_max=1.00,
        initial_soc=0.20,
    )

    # 4 kW charged for 1 h stores 3.2 kWh. At eta_dis=0.8 the largest
    # subsequent AC-side discharge is therefore 2.56 kW for one hour.
    np.testing.assert_allclose(p_kw, [4.0, -2.56], atol=1e-12)
    np.testing.assert_allclose(soc[-1], 0.20, atol=1e-12)


def test_usable_capacity_is_not_reduced_by_soc_floor_twice() -> None:
    p_kw, soc, _ = dispatch_bess_self_consumption(
        [100.0],
        usable_capacity_kwh=10.0,
        p_max_kw=100.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        dt_hours=1.0,
        soc_min=0.20,
        soc_max=1.00,
        initial_soc=1.00,
    )

    # The empirical 10 kWh is already a usable capacity. A full usable window
    # can therefore deliver 10 kWh; the 20% SOC floor is only the mapped lower
    # state bound and must not turn 10 kWh into 8 kWh again.
    np.testing.assert_allclose(p_kw, [-10.0])
    np.testing.assert_allclose(soc, [0.20])


def test_dispatch_never_grid_charges_or_deliberately_exports() -> None:
    residual = np.array([-2.0, 3.0, -1.0, 4.0])
    p_kw, _, residual_after = dispatch_bess_self_consumption(
        residual,
        usable_capacity_kwh=5.0,
        p_max_kw=2.0,
        eta_charge=0.96,
        eta_discharge=0.96,
        dt_hours=0.25,
    )

    assert not np.any((p_kw > 0.0) & (residual >= 0.0))
    assert not np.any((p_kw < 0.0) & (residual <= 0.0))
    assert not np.any((residual > 0.0) & (residual_after < -1e-12))
    assert not np.any((residual < 0.0) & (residual_after > 1e-12))


def _allocation_config(root: Path, *, attachment_rate: float = 0.40) -> BESSAllocationConfig:
    return BESSAllocationConfig(
        project_name="Test",
        aoi_id="Test",
        scenario_id="status_quo",
        realisations=1,
        pv_allocation_path=root / "pv_allocation.csv",
        output_dir=root / "output",
        attachment_rate=attachment_rate,
        base_seed=42,
    )


def _pv_rows(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "allocation_id": [f"PV_Test_30101_R000_{i:05d}" for i in range(count)],
            "building_id": [f"B{i}" for i in range(count)],
            "bus_id": list(range(100, 100 + count)),
            "scenario_id": ["status_quo"] * count,
            "realisation": [0] * count,
            "municipality_id": ["30101"] * count,
        }
    )


def test_allocation_is_deterministic_and_keeps_pv_coupling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _allocation_config(tmp_path)
    _pv_rows(5).to_csv(config.pv_allocation_path, index=False)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda *args, **kwargs: None)

    first = run_bess_allocation(config)
    second = run_bess_allocation(config)

    assert len(first.allocation) == 2
    assert first.allocation["pv_allocation_id"].tolist() == second.allocation[
        "pv_allocation_id"
    ].tolist()
    assert set(first.allocation["pv_allocation_id"]).issubset(
        set(_pv_rows(5)["allocation_id"])
    )
    assert first.validation["target_count_matches_allocation"]


def test_zero_target_is_a_valid_allocation(tmp_path: Path, monkeypatch) -> None:
    config = _allocation_config(tmp_path)
    _pv_rows(1).to_csv(config.pv_allocation_path, index=False)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda *args, **kwargs: None)

    result = run_bess_allocation(config)

    assert result.allocation.empty
    assert result.validation["empty_allocation_is_valid"]
    assert result.validation["allocation_rows"] == 0


def _integration_config(root: Path) -> BESSPandapowerConfig:
    return BESSPandapowerConfig(
        project_name="Test",
        scenario_id="status_quo",
        realisation=0,
        base_net_path=root / "base.p",
        bess_allocation_path=root / "bess_allocation.csv",
        output_net_path=root / "output.p",
        output_dir=root / "diagnostics",
    )


def test_empty_allocation_file_is_accepted_as_no_op(tmp_path: Path) -> None:
    config = _integration_config(tmp_path)
    pd.DataFrame(
        columns=[
            "allocation_id",
            "pv_allocation_id",
            "building_id",
            "bus_id",
            "scenario_id",
            "realisation",
        ]
    ).to_csv(config.bess_allocation_path, index=False)

    selected = _load_allocation(config)

    assert selected.empty
    assert selected["bus_id"].dtype == "int64"


def test_storage_mapping_preserves_allocation_id(tmp_path: Path) -> None:
    config = _integration_config(tmp_path)
    allocation = pd.DataFrame(
        {
            "allocation_id": ["BESS_A"],
            "pv_allocation_id": ["PV_A"],
            "building_id": ["B1"],
            "bus_id": [5],
        }
    )
    mapping = pd.DataFrame(
        {
            "allocation_id": ["BESS_A"],
            "usable_capacity_kwh": [12.12],
            "p_max_kw": [3.03],
        }
    )
    net = SimpleNamespace(
        storage=pd.DataFrame(
            columns=[
                "bus",
                "p_mw",
                "max_e_mwh",
                "q_mvar",
                "sn_mva",
                "soc_percent",
                "name",
                "in_service",
            ]
        )
    )

    class FakePandapower:
        @staticmethod
        def create_storage(net, **values):
            index = len(net.storage)
            for key, value in values.items():
                net.storage.loc[index, key] = value
            return index

    enriched_mapping = _add_bess_storage_elements(
        FakePandapower,
        net,
        allocation,
        mapping,
        config,
    )

    assert enriched_mapping["allocation_id"].tolist() == ["BESS_A"]
    assert enriched_mapping["storage_index"].tolist() == [0]
    assert net.storage.loc[0, "allocation_id"] == "BESS_A"


def test_residual_reconstruction_applies_scaling_and_in_service() -> None:
    net = SimpleNamespace(
        load=pd.DataFrame(
            {
                "p_mw": [1.0, 3.0],
                "scaling": [2.0, 4.0],
                "in_service": [True, False],
            },
            index=[10, 11],
        ),
        controller=pd.DataFrame(columns=["object"]),
    )

    values = _element_active_power_timeseries(
        net,
        element="load",
        element_indices=[10, 11],
        n_steps=3,
    )

    np.testing.assert_allclose(values[10], [2.0, 2.0, 2.0])
    np.testing.assert_allclose(values[11], [0.0, 0.0, 0.0])


def test_combined_network_metadata_matches_bess_axis(tmp_path: Path) -> None:
    config = _integration_config(tmp_path)
    net = {
        "combined_status_quo_metadata": {
            "scenario_id": "status_quo",
            "realisation": 0,
            "reference_year": 2025,
            "time_step_minutes": 15,
            "n_time_steps": 35040,
        }
    }

    assert _validate_combined_net_metadata(net, config)
    assert len(build_reference_index(2025, 15)) == 35040
