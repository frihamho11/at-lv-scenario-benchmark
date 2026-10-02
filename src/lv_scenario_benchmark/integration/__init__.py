"""Integration of allocated technologies into pandapower networks."""

__all__: list[str] = []

# Keep each technology optional so this file remains usable on branches where
# only part of the integration stack is present.
try:
    from .hp_pandapower import (
        HPPandapowerConfig,
        HPPandapowerIntegrationError,
        HPPandapowerIntegrationResult,
        build_hp_absolute_timeseries,
        integrate_hp_status_quo,
        load_hp_pandapower_config,
    )
except ModuleNotFoundError:
    pass
else:
    __all__ += [
        "HPPandapowerConfig",
        "HPPandapowerIntegrationError",
        "HPPandapowerIntegrationResult",
        "build_hp_absolute_timeseries",
        "integrate_hp_status_quo",
        "load_hp_pandapower_config",
    ]

try:
    from .ev_pandapower import (
        EVPandapowerConfig,
        EVPandapowerIntegrationError,
        EVPandapowerIntegrationResult,
        build_ev_absolute_timeseries,
        integrate_ev_status_quo,
        load_ev_pandapower_config,
    )
except ModuleNotFoundError:
    pass
else:
    __all__ += [
        "EVPandapowerConfig",
        "EVPandapowerIntegrationError",
        "EVPandapowerIntegrationResult",
        "build_ev_absolute_timeseries",
        "integrate_ev_status_quo",
        "load_ev_pandapower_config",
    ]

from .pv_pandapower import (
    PVPandapowerConfig,
    PVPandapowerIntegrationError,
    PVPandapowerIntegrationResult,
    build_pv_absolute_timeseries,
    integrate_pv_status_quo,
    load_apcs_pv_profile,
    load_pv_pandapower_config,
)

__all__ += [
    "PVPandapowerConfig",
    "PVPandapowerIntegrationError",
    "PVPandapowerIntegrationResult",
    "build_pv_absolute_timeseries",
    "integrate_pv_status_quo",
    "load_apcs_pv_profile",
    "load_pv_pandapower_config",
]
