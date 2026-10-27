# Energiezentrale 0.1.0

Früher Prototyp einer lokalen Energieübersicht für Home Assistant OS.

- Deutsche Weboberfläche
- Live-Auslesen von Home-Assistant-Entitäten
- Sensorzuordnung über Vorschlagsliste und manuelle Entity-ID
- Anlagen- und Verbraucher-Konfiguration
- Lokale Messwerthistorie und einfache Kennzahlen
- Keine Geräte-Schaltbefehle

Die Lernseite sammelt Daten und berechnet einfache Statistiken; sie ist noch kein selbstlernender Optimierer. Vor produktivem Einsatz müssen Installation, Datenqualität, Vorzeichen/Einheiten, Ausfallsicherheit, Backup/Restore und Sicherheitsgrenzen geprüft werden.


## Version 0.1.4
- Dunkles Dashboard und aktive Navigation.
- Read-only: keine Schaltbefehle an Geräte.
- Konfiguration, Verbraucher und lokale Messwerthistorie bleiben verfügbar.
- Hinweis: Lernen ist derzeit eine lokale Datensammlung mit Kennzahlen, noch kein autonomer Optimierer.


## Update 0.2.0 – Steuerungsvorbereitung
Diese Version setzt das persistente weiche Netzbezugsziel standardmäßig auf 5000 W, speichert die Anzahl parallel geregelter Wechselrichter (Standard 2) und bietet editierbare Felder für die SolaX-Modbus-Steuerungs-Entitäten. Die bestehende Steuerung ist weiterhin absichtlich gesperrt: Es werden keine Schreibbefehle an den Wechselrichter gesendet, bis Vorzeichen und Registersemantik vor Ort sicher geprüft sind. Die Dashboard-Messwerte und die einfache lokale Historie bleiben enthalten.

Noch nicht enthalten: ein aktiver Optimierer, automatische Batterie-/Netzleistungsregelung, Verbraucher-Schaltlogik, Prognose-Lernmodell oder ein vollständig getesteter Produktionsbetrieb.
