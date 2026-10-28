# Energiezentrale HA 1.2.6

## Netzspitzenanalyse mit gemessener Batterieleistung
- Ergänzt die `/api/peak-analysis`-Ausgabe um eine Schätzung, wie viel der Leistung oberhalb der eingestellten Netzbezugsgrenze während der gemessenen Zeitintervalle durch die gleichzeitig gemessene Batterieentladung abgedeckt werden könnte.
- Berechnung begrenzt den rechnerischen Beitrag auf `min(Leistung oberhalb der Grenze, gemessene Batterieentladung)` und integriert nur benachbarte Messpunkte innerhalb des zulässigen Zeitabstands.
- Gibt die Anzahl der Intervalle mit gültigen Batteriedaten aus, damit fehlende Daten sichtbar bleiben.
- Rein beratend: keine Wechselrichterbefehle und keine Änderung der SoC-Untergrenze.

## Einschränkungen
Die Schätzung ist keine kontrafaktische Simulation und kein Beweis, dass der Speicher tatsächlich mehr hätte entladen dürfen. Sie berücksichtigt nicht vollständig SoC-/Leistungsgrenzen, Wechselrichterregeln, AC/DC-Messpunktdifferenzen oder thermische/sonstige Schutzgrenzen. Das Vorzeichen von `battery_power_sign` und `grid_import_sign` muss in der Konfiguration stimmen.

## Prüfungen
- `python -m py_compile` für `energiezentrale/app.py`.
- ZIP-Integritätstest.
- Vollständiger Flask-/Home-Assistant-Laufzeittest ist in dieser Umgebung nicht verfügbar und wird nicht als bestanden behauptet.
