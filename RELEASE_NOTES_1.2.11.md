# Energiezentrale HA 1.2.11

## Verbraucher-Seite verbessert
- Zeigt jetzt automatisch erkannte, wiederkehrende Gesamtverbrauchsmuster direkt auf der Verbraucher-Seite.
- Zeigt Anzahl gültiger Tage, Mindestanzahl von Tagen je Muster, typische Leistung je 15-Minuten-Zeitfenster und Vertrauensstufe.
- Erklärt klar, dass die Muster aus dem Gesamtverbrauch gelernt werden und keine einzelne Maschine identifizieren.
- Wenn noch keine Muster erkannt wurden, erklärt die Seite die Mindestanforderung von drei Tagen und fordert dazu auf, die Lernphase nicht zurückzusetzen.
- Verbraucher-Stammdaten und Zeitfenster sind ausdrücklich als optionale Planungsdaten gekennzeichnet; sie sind keine Voraussetzung für das Lernen.

## Unverändert
- Nur beratender Betrieb; keine Steuerbefehle an Home Assistant, Wechselrichter oder Verbraucher.
- Es werden ausschließlich Messungen seit dem gespeicherten Lernstart verwendet.
- Die feste Mindest-SoC-Grenze wird nicht geändert.

## Prüfung
- Python-Syntax geprüft.
- Template-JavaScript und API-Aufrufe wurden statisch geprüft; kein vollständiger Live-Test in Home Assistant.
