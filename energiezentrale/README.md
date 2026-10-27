# Energiezentrale 0.4.0

Home Assistant Add-on mit lokalem Dashboard, konfigurierbaren Sensoren und Verbraucher-Stammdaten.

## In 0.4.0 umgesetzt
- Persistente Konfiguration in `/data/config.json`.
- Home-Assistant-Entity-IDs für Messwerte und SolaX-Modbus-Steuerungsentitäten frei konfigurierbar.
- Konfigurierbares Messintervall über Add-on-Option `sample_interval_seconds` (Standard 15 s).
- Messwerthistorie in `/data/history.jsonl` mit Größenbegrenzung.
- Statistik über vorhandene historische Messwerte.
- Historische morgendliche Netzbezugs-Spitzen: täglicher Höchstwert und Median, nur wenn das Vorzeichen des Netzleistungssensors ausdrücklich konfiguriert und mindestens drei Tage Daten vorhanden sind.
- Beratender Plan-Endpunkt `/api/plan`, der PV minus Last, weiches Netzbezugsziel und passende Verbraucher nach Nennleistung anzeigt.
- Keine Steuerbefehle werden gesendet. Aktive Steuerung ist absichtlich gesperrt.

## Noch nicht umgesetzt
- Keine autonome Optimierung, kein ML-Modell und keine automatischen Batterie-Sollwerte.
- Keine Schaltung von Verbrauchern.
- Keine aktive Steuerung der Wechselrichter.
- Keine Garantie für vollständige Kompatibilität mit jedem Home-Assistant-/Ingress-Setup ohne Test auf dem Zielsystem.

Vor einer Steuerungsfreigabe müssen Registersemantik, Vorzeichen, Einheiten, Skalierung beider Wechselrichter und Fehlerverhalten an der realen Anlage verifiziert werden.
