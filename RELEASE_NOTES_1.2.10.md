# Energiezentrale HA 1.2.10

## Korrektur
- Behebt einen Fehler im API-Endpunkt `/api/night-plan`: Die Startstunde des Morgenfensters wurde verwendet, ohne zuvor aus den Einstellungen gelesen zu werden.
- Das Morgenfenster wird nun aus `morning_start_hour` geladen und auf den gültigen Bereich 0–23 begrenzt.

## Unverändert
- Nur beratender Betrieb; keine automatischen Schreibbefehle an Home Assistant oder den Wechselrichter.
- Lernhistorie wird weiterhin ab dem gespeicherten Lernstart verwendet.
- Die Version verändert keine Wechselrichter-Mindest-SoC-Einstellung.

## Hinweis
- Syntax- und gezielte Funktionstests sind keine vollständige Laufzeitprüfung in einer echten Home-Assistant-Installation. Sensorzuordnung, Einheiten und Vorzeichen müssen dort weiterhin geprüft werden.
