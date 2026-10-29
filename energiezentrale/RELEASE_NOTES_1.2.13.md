# Energiezentrale HA 1.2.13

## Verbraucher-Sensoren und Kompressor-Diagnose

- Verbraucher können optional Druck- und Temperatursensoren verwenden; aktuelle Messwerte werden in den Verbraucherempfehlungen berücksichtigt.
- Beim Kompressor können Kesselvolumen (Voreinstellung 500 Liter), Ein-/Ausschaltdruck und optional ein Kompressorstatus-Sensor eingetragen werden.
- Neue Druckverlustanalyse zeigt einen vorsichtigen Schätzwert in Liter/Stunde anhand gespeicherter Druckmessungen der letzten 12 Stunden.
- Die Analyse kennzeichnet den Wert ausdrücklich als Verdacht/Schätzung; Temperaturänderungen und unbemerkter Luftverbrauch können die Messung verfälschen.
- Sensorwerte der Verbraucher werden zusätzlich zu den bisherigen Messwerten protokolliert. Bestehende Konfiguration und Lernhistorie werden nicht zurückgesetzt.
- Weiterhin beratender Betrieb: keine Verbraucher- oder Wechselrichterbefehle werden gesendet.
