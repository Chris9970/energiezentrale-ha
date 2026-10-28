# Energiezentrale 1.0.0

Read-only Home Assistant energy analysis add-on. Keeps prior overview, simulation, configuration, consumer planning, learning/history, diagnostics and daily energy pages.

## New in 1.0.0
- SoC-derived stored-energy change compared with integrated battery energy as a rough diagnostic.
- Grid peaks grouped into approximate events instead of only counting repeated over-limit samples.
- Seven-day energy rollup table for PV, load, grid import/export and battery charge/discharge.

## Retained from 0.9.0
- Combined Anlagenanalyse page: daily PV/load/grid/battery integration, battery SoC snapshot comparison, grid peak sample detection, energy balance residual, tariff-based estimated import costs/export revenue, forecast value display, data-gap counts, warnings and advisory consumer list.
- Configurable import price, export tariff, grid peak warning threshold and balance warning threshold.
- All calculations are advisory. The PV forecast is deliberately not treated as remaining-day surplus until the configured sensor's meaning is known.

## Safety
Active control is forced off and the application does not send inverter or consumer commands. Energy estimates depend on sensor mapping, units, sign conventions and history coverage. Large data gaps are skipped; peak counts are samples above threshold, not deduplicated events. The battery power convention used is negative=discharge and positive=charge, based on the observed Sofar history.

## Validation
Python syntax/AST and ZIP integrity checked. Python syntax compilation, Jinja template parsing, and ZIP integrity were tested. Full Home Assistant runtime test was not possible in the build environment because Flask is not installed there.
