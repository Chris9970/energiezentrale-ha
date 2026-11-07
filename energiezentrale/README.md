## Version 1.2.25 – Energy Brain & optionale Speicherregelung
- Energy Brain zeigt erklärbare Empfehlungen und beantwortet lokale Fragen zu PV, Netz und Speicher.
- Energy Brain-Auswertung wird zwischengespeichert; die fehlende Auffälligkeitsanalyse für die Seite ist ergänzt.
- Optionaler Sofar HYD Passivmodus-Regler für das parallele Master/Slave-Paar: Anlagen-Gesamtleistungen werden durch zwei geteilt. Bei 30 kW Gesamt-Entladegrenze bleiben bis zu −15 kW je Wechselrichter gesetzt. Laden ist auf den gemessenen PV-Überschuss nach Sicherheitsabstand begrenzt.
- Steuerung bleibt standardmäßig aus und wird vor jedem Lauf gegen Sensorstatus, Vorzeichen, Einheiten, Registergrenzen und einen 5-Minuten-Watchdog mit Rückkehr zum vorherigen Modus geprüft.
- Unterstützt wird ein Master/Slave-Paar, bei dem der Master den identischen Sollwert an beide Geräte verteilt; getrennte Steuer-Entitäten sind nicht unterstützt.

# Energiezentrale 1.2.26

Home Assistant energy analysis and optional control add-on. Keeps prior overview, simulation, configuration, consumer planning, learning/history, diagnostics and daily energy pages.

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
Active control is opt-in and remains disabled by default. It supports one configured master control entity set that distributes identical per-inverter settings to a two-inverter master/slave pair. It requires verified grid-sensor polarity, fresh measurements in W and %, compatible Solax Modbus control entities, and a confirmed 5-minute watchdog configured to return to the previous mode. A control failure disables the setting and attempts to restore the saved mode; the inverter watchdog is the fallback. This assumes the master entity broadcasts its per-inverter setpoints to the slave, as confirmed for this installation. Failed state restoration, network interruptions and unknown firmware behavior must be reviewed in Home Assistant before enabling. No consumer devices are switched. Energy estimates also depend on sensor mapping and history coverage.

## Validation
Python syntax/AST and ZIP integrity checked. Python syntax compilation, Jinja template parsing, and ZIP integrity were tested. Full Home Assistant runtime test was not possible in the build environment because Flask is not installed there.


Version 1.1.1: Netz- und Batteriesensor-Vorzeichen werden bei der Tagesenergiebilanz konfigurationsbasiert ausgewertet. Aktive Steuerung bleibt deaktiviert.

## Version 1.1.2
- Speicherreserve-Lernen verwirft Morgen mit zu wenigen Netzleistungs-Messpunkten, damit einzelne kurze Dateninseln nicht als vollständige Lerntage zählen.
- Die API weist die Anzahl gültiger Lerntage, verworfener Tage und den Mindestumfang pro Tag aus.
- Der Mindestumfang ist über `settings.morning_min_samples_per_day` konfigurierbar (Standard: 60 Messpunkte).
- Weiterhin reine Empfehlung; keine Steuerbefehle an Wechselrichter oder Verbraucher.
- Prüfung: Python-Syntax und ZIP-Integrität; Laufzeittest in Home Assistant steht noch aus.
