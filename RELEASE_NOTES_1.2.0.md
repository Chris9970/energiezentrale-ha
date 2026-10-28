# Energiezentrale HA 1.2.0

- Neuer beratender Endpunkt `/api/night-plan`.
- Vergleicht den aktuellen SoC-basierten Energieinhalt mit der empfohlenen Morgenreserve.
- Meldet, ob rechnerisch keine Reserve-Lücke oder eine Reserve-Lücke besteht; zeigt eine vorsichtige Empfehlung.
- Verwendet die konfigurierten Import-/Exportpreise nur als Hinweis, nicht als vollständige Wirtschaftlichkeitsoptimierung.
- Sendet keine Befehle und startet keine Netzladung.

## Grenzen
Die Nachtplanung ist ein erster Hinweis auf eine Reserve-Lücke, noch kein stundenaufgelöster Optimierer. Sie modelliert nicht vollständig den verbleibenden Nachtverbrauch, zeitabhängige Strompreise, Batterie-Umwandlungsverluste oder PV-Prognoseunsicherheit. Mit realen HA-Daten testen, bevor Empfehlungen als belastbar gelten.
