# Energiezentrale HA 1.2.4

## Monatlich gültigen Tarif automatisch anwenden
- Die Wirtschaftlichkeitsseite und API wählen nun den zuletzt gespeicherten Tarif, dessen Gültigkeitsmonat nicht in der Zukunft liegt.
- Ein zukünftiger Tarif wird nicht vorzeitig angewendet.
- Die Wirtschaftlichkeitsseite zeigt den angewendeten Tarifmonat und ob der Wert aus der Historie oder der aktuellen Konfiguration stammt.
- Die App bleibt beratend; es werden keine Geräte geschaltet und die SoC-Untergrenze wird nicht verändert.

## Prüfung
- Python-Syntaxprüfung und isolierte Tests der Tarifauswahl erfolgreich.
- Flask-Laufzeittest in dieser Umgebung nicht durchgeführt, wenn Flask nicht installiert ist.
