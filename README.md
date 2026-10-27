# Energiezentrale für Home Assistant

Dieses Repository enthält die frühe, lokale Home-Assistant-App **Energiezentrale**.

## Status

**Prototyp / Testversion 0.1.0.** Nicht als produktionsreife Kundenlösung betrachten. Vor dem produktiven Einsatz müssen insbesondere Installationsfähigkeit auf aktuellen Home-Assistant-Versionen, Einheiten und Vorzeichen der Sensoren, Fehlerbehandlung, Backup/Restore und Sicherheitsgrenzen geprüft werden.

## Installation (nach Veröffentlichung auf GitHub)

1. Dieses Repository auf GitHub unter `Chris9970/energiezentrale-ha` als **Public** veröffentlichen.
2. In Home Assistant OS zu **Einstellungen → Apps** (in älteren Versionen **Add-ons**) gehen.
3. Über das Menü `⋮` → **Repositories** die Repository-URL `https://github.com/Chris9970/energiezentrale-ha` hinzufügen.
4. Energiezentrale in der App-Liste auswählen, installieren und starten.

Wenn der Build oder Start fehlschlägt, bitte die App-Protokolle sichern. Die Struktur allein garantiert noch keine erfolgreiche Installation auf jeder Home-Assistant-Version.

## Datenschutz und Betrieb

- Die App ist für den lokalen Betrieb gedacht.
- In dieser Version werden Home-Assistant-Entitäten gelesen; sie sendet keine Schaltbefehle.
- Die Sensor-IDs in der Oberfläche sind Beispiele/Startwerte und müssen auf jeder Installation geprüft werden.
- Keine Passwörter, Tokens oder persönlichen Konfigurationsdateien in dieses Repository hochladen.

## Ordnerstruktur

- `repository.yaml`: Metadaten für das Home-Assistant-App-Repository
- `energiezentrale/config.yaml`: App-Metadaten
- `energiezentrale/Dockerfile`: Container-Build
- `energiezentrale/app.py`: Webanwendung
- `energiezentrale/templates/` und `energiezentrale/static/`: Oberfläche


## Update 0.1.4
Diese Version ergänzt das dunkle Dashboard und die sichtbare aktive Navigation. Die App bleibt strikt im Beobachtungsmodus. Die Lernseite sammelt Messpunkte und zeigt Kennzahlen; fortgeschrittene Prognose-/Optimierungsfunktionen sind noch nicht als fertig zu betrachten.


## Update 0.2.0 – Steuerungsvorbereitung
Diese Version setzt das persistente weiche Netzbezugsziel standardmäßig auf 5000 W, speichert die Anzahl parallel geregelter Wechselrichter (Standard 2) und bietet editierbare Felder für die SolaX-Modbus-Steuerungs-Entitäten. Die bestehende Steuerung ist weiterhin absichtlich gesperrt: Es werden keine Schreibbefehle an den Wechselrichter gesendet, bis Vorzeichen und Registersemantik vor Ort sicher geprüft sind. Die Dashboard-Messwerte und die einfache lokale Historie bleiben enthalten.

Noch nicht enthalten: ein aktiver Optimierer, automatische Batterie-/Netzleistungsregelung, Verbraucher-Schaltlogik, Prognose-Lernmodell oder ein vollständig getesteter Produktionsbetrieb.
