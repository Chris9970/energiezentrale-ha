# Energiezentrale HA 1.2.8

- Ergänzt einen sichtbaren Lernstatus mit Lernstart, Anzahl neuer Messpunkte und Morgen-Messwerten.
- Zeigt ausdrücklich an, wenn das Vorzeichen des Netzleistungssensors noch nicht konfiguriert ist; bei der beschriebenen Anlage ist Netzbezug negativ und Einspeisung positiv.
- Keine Steuerbefehle: nur lesende Auswertung und Empfehlungen.
- Lernhistorie bleibt auf Messungen ab dem gespeicherten Lernstart begrenzt.

Validierung: Python-Syntax und ZIP-Integrität geprüft. Kein Live-Test in Home Assistant möglich.
