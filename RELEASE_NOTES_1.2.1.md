# Energiezentrale HA 1.2.1

## Nachtplanung: gelernter Nachtverbrauch
- Die beratende Nachtplanung berücksichtigt jetzt zusätzlich wiederkehrende Hauslastmuster zwischen 00:00 Uhr und dem konfigurierten Morgenfenster.
- Die API liefert geschätzten Nachtverbrauch, Vertrauensstufe, geschätzte Batterieenergie am Morgen und eine mögliche Reserve-Lücke nach dem Nachtverbrauch.
- Bei erwarteter Reserve-Lücke wird zunächst eine vorsichtige Prüfung empfohlen; es wird weder Netzladung ausgelöst noch ein Wechselrichter gesteuert.
- Preiswerte bleiben indikativ. Zeitabhängige Tarife, PV während der Nacht-/Morgenstunden und gemessene Rundlaufverluste sind nicht vollständig modelliert.

## Validierung
- Python-Syntaxprüfung erfolgreich.
- ZIP-Integrität geprüft.
- API-Routentest konnte in der Arbeitsumgebung nicht ausgeführt werden, da Flask nicht installiert ist; kein erfolgreicher Laufzeittest behauptet.
- Kein vollständiger Home-Assistant-Lauf mit echten Anlagenmessdaten durchgeführt.
