# Energiezentrale HA 1.2.3

- Ergänzt monatliche Tarifhistorie für Netzbezug und Einspeisung (Gültigkeit JJJJ-MM).
- Ergänzt ein beratendes Wirtschaftlichkeitsmodell: Netzbezugspreis versus entgangener Einspeisewert unter Berücksichtigung eines einstellbaren geschätzten Batterie-Rundlaufwirkungsgrads.
- Preise sind weiterhin manuell änderbar; alte Monate bleiben als Verlauf erhalten und derselbe Monat wird beim erneuten Speichern aktualisiert.
- Neue Seite `/economics` und API `/api/economic-assessment`.
- Keine Steuerbefehle; `control_enabled` bleibt deaktiviert und die SoC-Untergrenze wird nicht automatisch verändert.

## Einschränkungen

Die Berechnung ist eine vereinfachte Grenzkostenabschätzung. Sie berücksichtigt keine Batteriealterung, Fixkosten, Steuern/Abgaben, dynamische Stundenpreise oder Lade-/Entladeleistungsgrenzen. Sie ist keine vollumfängliche Optimierungsentscheidung.

## Prüfungen

Syntax- und Archivprüfungen sind Teil des lokalen Prüfablaufs. Der Flask-Laufzeittest muss in der Add-on-Umgebung erfolgen, falls Flask in der Entwicklungsumgebung nicht installiert ist.
