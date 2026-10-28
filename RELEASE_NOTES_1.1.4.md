# Energiezentrale 1.1.4

- Fix: `/analysis` now passes `forecast_label`, `pv_remaining_kwh`, and `pv_projected_total_kwh` to the Jinja template. This resolves the reported `UndefinedError` for `pv_remaining_kwh`.
- PV forecast conversion and interpretation now use the configured forecast mode, matching the Tagesenergie page.
- Read-only behavior retained; no inverter or consumer commands are sent.
- Validation: Python syntax, template rendering with mocked context, ZIP integrity. Full Home Assistant runtime test still required.
