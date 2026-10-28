# Energiezentrale HA 1.2.7

## Lernbasis nur aus neuen Messdaten
- Der Lernstart wird einmalig in `/data/learning_state.json` gespeichert.
- Lernfunktionen verwenden nur Messproben mit Zeitstempel ab diesem Lernstart.
- Alte Home-Assistant-Langzeitstatistiken werden nicht als Lerninput abgefragt.
- Der Lernstart bleibt im persistenten `/data`-Verzeichnis über Add-on-Neustarts erhalten.
- Die App bleibt beratend; es werden keine Steuerbefehle an Wechselrichter oder Verbraucher gesendet und die SoC-Untergrenze wird nicht automatisch verändert.

## Verifikation in dieser Umgebung
- Python-Syntaxprüfung: bestanden.
- ZIP-Integritätstest: bestanden.
- Home-Assistant-Laufzeittest: nicht durchgeführt; muss nach Installation in der realen HA-Umgebung geprüft werden.
