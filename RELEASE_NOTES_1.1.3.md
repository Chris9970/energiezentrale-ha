# Energiezentrale 1.1.3

- Added configuration for PV forecast semantics: whole-day total or remaining-day forecast.
- Anlagenanalyse now shows estimated remaining PV generation and projected daily production.
- The UI warns that remaining PV production is not equivalent to usable surplus because load, storage charging, weather and data gaps matter.
- Read-only operation remains enforced; no inverter or consumer commands are sent.

Validation: Python compilation and ZIP integrity check passed. Home Assistant runtime not tested in this environment.
