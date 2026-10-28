# Energiezentrale HA 1.2.2

- Nachtreserve nutzt jetzt historische Batterieleistung (`battery_power`) statt Hausverbrauch (`load_power`).
- Batterieleistung wird anhand der Einstellung `battery_power_sign` auf positive Entladung normalisiert.
- Pro 15-Minuten-Zeitfenster werden Tagesmediane gebildet; Zeitfenster werden erst ab mindestens drei Messtagen berücksichtigt.
- Wenn keine ausreichend belegten Batteriedaten vorhanden sind, wird keine Morgenenergie aus Nachtentladung geschätzt; die API meldet dann keine Reserve-Lücken-Prognose statt Hausverbrauch fälschlich als Batterieentladung anzurechnen.
- Rein beratend: keine Wechselrichter- oder Verbraucherbefehle. SoC-Untergrenze wird nicht verändert.

## Teststatus

- Python-Syntaxprüfung und ZIP-Integritätsprüfung durchgeführt.
- Isolierte Tests der Berechnungslogik mit synthetischen Messreihen durchgeführt.
- Vollständiger Flask-/Home-Assistant-Laufzeittest ist in dieser Umgebung nicht möglich, da Flask bzw. eine laufende Home-Assistant-Instanz nicht verfügbar ist.
