# Energiezentrale HA 1.1.9

- Bindet die automatisch erkannten, wiederkehrenden Hauslastmuster im konfigurierten Morgenfenster als vorsichtiges Zusatzsignal in die beratende Speicherreserve ein.
- Zeigt die geschätzte Energie in erkannten 15-Minuten-Zeitfenstern und eine Vertrauensstufe an.
- Die aus historischen Netzspitzen berechnete Zusatzenergie bleibt maßgeblich; gelernte Last wird nicht unkritisch addiert, sondern maximal zu 50 % als alternatives Zusatzsignal berücksichtigt, um Doppelzählungen zu begrenzen.
- Bei unzureichenden gültigen Morgenmessungen wird keine Reserveprognose erfunden.
- Keine Steuerbefehle an Wechselrichter oder Verbraucher.

Hinweis: Dies ist eine konservative erste Kopplung. PV-Abdeckung einzelner Lastfenster lässt sich ohne verlässliche zeitgleiche PV-/Lastbilanz nicht exakt zuordnen; daher ist die Empfehlung weiterhin beratend und muss mit realen Home-Assistant-Daten überprüft werden.
