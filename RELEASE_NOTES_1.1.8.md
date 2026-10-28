# Energiezentrale HA 1.1.8

- Ergänzt eine automatische, beratende Erkennung wiederkehrender Hausverbrauchsmuster in 15-Minuten-Zeitfenstern.
- Verwendet pro Tag und Zeitfenster den Median, damit einzelne kurze Lastspitzen das Muster nicht dominieren.
- Zeigt typische Leistung, Anzahl beobachteter Tage und eine einfache Vertrauensstufe in „Lernen & Verlauf“.
- Neue JSON-Ansicht: `/api/learned-load-patterns`.
- Muster beziehen sich auf den Gesamtverbrauch; es wird keine Maschine ohne eigene Messung identifiziert.
- Weiterhin reine Beobachtung: keine Steuerbefehle an Wechselrichter oder Verbraucher.

Hinweis: Diese Version ergänzt die automatische Mustererkennung. Die Muster sind noch nicht als vollständige Lastprognose in die Batterieplanung integriert; das ist ein nächster Entwicklungsschritt.
