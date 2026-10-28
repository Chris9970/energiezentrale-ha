# Energiezentrale 0.5.0

## In 0.5.0 umgesetzt
- Neue beratende PV-Überschussplanung auf der Seite „Verbraucher“.
- Schätzt Einspeisung anhand des konfigurierten Netzleistungs-Vorzeichens.
- Berücksichtigt einen Sicherheitsabstand von 1000 W.
- Ordnet aktivierte Verbraucher nach Priorität und schlägt passende Heizstufen/Nennleistungen vor.
- Keine Schaltbefehle an Verbraucher oder Wechselrichter; aktive Regelung bleibt deaktiviert.

## Weiterhin enthalten
- Home-Assistant-Sensorübersicht und lokale Messwerthistorie.
- Statistiken und beratende Batterie-Morgenreserve aus historischen Daten.
- Konfigurierbares weiches Netzbezugsziel, Batteriekapazität und Reserve.

## Hinweise
- Das Add-on muss über Home Assistant Supervisor gestartet werden, damit die Home-Assistant-API verfügbar ist.
- Die Netzleistungs-Vorzeichenkonfiguration muss anhand realer Messwerte stimmen. Für die beschriebene Anlage gilt: Netzbezug negativ, Einspeisung positiv.
- Die Verbraucherplanung ist nur eine rechnerische Vorauswahl. Vor einer späteren Automatisierung sind Anlaufströme, Mindestlaufzeiten, Druck-/Temperaturgrenzen, gegenseitige Verriegelungen und sichere Ausgänge gesondert zu implementieren und zu testen.
- Python-Syntax wurde geprüft. Ein vollständiger Laufzeittest war in der Erstellungsumgebung nicht möglich, da Flask dort nicht installiert ist.


## Version 0.5.0
- Ergänzte konfigurierbare Zeitfenster für die Flüssigfütterung als reine Lastprognose (Standard: 06:45, 12:00, 18:15; Laufzeit 8 Minuten; Leistung 0 = unbekannt).
- Einstellbarer PV-Überschuss-Sicherheitsabstand.
- Neue historische Spitzenanalyse unter `/api/peak-analysis`; Dauer oberhalb des Ziels wird nur bei lückenarmen benachbarten Messpunkten geschätzt.
- Keine aktiven Wechselrichter- oder Verbraucherbefehle; Steuerung bleibt deaktiviert.


## Version 0.5.1
- Ergänzt eine Simulationsseite mit aktuellen Messwerten, einfacher PV-minus-Last-Näherung und vorläufiger Batterieplanung.
- Fehlende Messwerte werden als fehlend angezeigt.
- Simulation ist rein beratend; es werden keine Steuerbefehle gesendet.
- Vollständiger Laufzeit-/Browser-Test muss in Home Assistant erfolgen.
