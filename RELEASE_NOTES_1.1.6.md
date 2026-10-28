# Energiezentrale 1.1.6

- Verbessert die Datenqualität der lernenden morgendlichen Speicherreserve.
- Ein Morgen wird nur dann als gültig gewertet, wenn er sowohl die Mindestzahl an Messpunkten als auch mindestens 50 % zeitliche Abdeckung des konfigurierten Morgenfensters erreicht.
- Zeigt Mindestabdeckung und Abdeckung je Tag in der API-Planantwort an.
- Weiterhin ausschließlich beratender Nur-Lese-Betrieb; keine Befehle an Wechselrichter oder Verbraucher.

Hinweis: Syntax- und Funktionstests wurden lokal ausgeführt; ein Laufzeittest in Home Assistant muss vor Ort erfolgen.
