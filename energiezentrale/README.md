## Version 1.2.17 – Energy Brain
- Lokale Lastsprung-Erkennung und Gruppierung ähnlicher Ereignisse; neue Seite `/energy-brain` und API `/api/energy-brain`.
- Keine Cloud, keine Steuerbefehle; Erkennungen bleiben zunächst unbestätigte Profile.

# Energiezentrale 1.1.3

Read-only Home Assistant energy analysis add-on. Keeps prior overview, simulation, configuration, consumer planning, learning/history, diagnostics and daily energy pages.

## New in 1.1.3
- PV forecast semantics can be configured as whole-day total or remaining-day forecast.
- Anlagenanalyse estimates remaining PV generation and projected daily total according to that choice; it explicitly warns that this is not the same as surplus energy.

## New in 1.1.1
- SoC-derived stored-energy change compared with integrated battery energy as a rough diagnostic.
- Grid peaks grouped into approximate events instead of only counting repeated over-limit samples.
- Seven-day energy rollup table for PV, load, grid import/export and battery charge/discharge.

## Retained from 0.9.0
- Combined Anlagenanalyse page: daily PV/load/grid/battery integration, battery SoC snapshot comparison, grid peak sample detection, energy balance residual, tariff-based estimated import costs/export revenue, forecast value display, data-gap counts, warnings and advisory consumer list.
- Configurable import price, export tariff, grid peak warning threshold and balance warning threshold.
- All calculations are advisory. The PV forecast is interpreted according to the explicit configuration choice (daily total vs. remaining-day forecast); this remains an estimate, not a guaranteed surplus.

## Safety
Active control is forced off and the application does not send inverter or consumer commands. Energy estimates depend on sensor mapping, units, sign conventions and history coverage. Large data gaps are skipped; peak counts are samples above threshold, not deduplicated events. The battery power convention used is negative=discharge and positive=charge, based on the observed Sofar history.

## Validation
Python syntax/AST and ZIP integrity checked. Python syntax compilation, Jinja template parsing, and ZIP integrity were tested. Full Home Assistant runtime test was not possible in the build environment because Flask is not installed there.


Version 1.1.1: Netz- und Batteriesensor-Vorzeichen werden bei der Tagesenergiebilanz konfigurationsbasiert ausgewertet. Aktive Steuerung bleibt deaktiviert.

## Version 1.1.2
- Speicherreserve-Lernen verwirft Morgen mit zu wenigen Netzleistungs-Messpunkten, damit einzelne kurze Dateninseln nicht als vollständige Lerntage zählen.
- Die API weist die Anzahl gültiger Lerntage, verworfener Tage und den Mindestumfang pro Tag aus.
- Der Mindestumfang ist über `settings.morning_min_samples_per_day` konfigurierbar (Standard: 60 Messpunkte).
- Weiterhin reine Empfehlung; keine Steuerbefehle an Wechselrichter oder Verbraucher.
- Prüfung: Python-Syntax und ZIP-Integrität; Laufzeittest in Home Assistant steht noch aus.
