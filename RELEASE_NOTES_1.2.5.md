# Energiezentrale HA 1.2.5

## Netzspitzen-Auswertung
- `/api/peak-analysis` ergänzt geschätzte Energie oberhalb der eingestellten Netzbezugsgrenze (kWh), Netzbezugsenergie während Peak-Intervallen und die Anzahl erkannter Spitzenereignisse.
- Spitzenereignisse werden anhand aufeinanderfolgender Messpunkte gebildet und bei Datenlücken getrennt; Zeitlücken werden nicht hochgerechnet.
- Tageswerte und bis zu 20 stärkste Ereignisse enthalten Spitzenleistung, Dauer und geschätzte Energie oberhalb der Grenze.
- Die Analyse bleibt rein beratend. Importenergie während Peak-Intervallen ist nicht automatisch vollständig vermeidbar und wird entsprechend gekennzeichnet.

## Prüfung
- Python-Syntaxprüfung durchgeführt.
- Rechenlogik für trapezförmige Energieintegration und Überschuss über der Grenze mit isolierten Beispielrechnungen geprüft.
- ZIP-Integrität wird nach Erstellung geprüft.
- Vollständiger Laufzeittest der Flask-Route in Home Assistant wurde in dieser Umgebung nicht durchgeführt.
