from pathlib import Path
p=Path('/mnt/data/ez121work/app.py'); s=p.read_text()
marker='# Multi-channel next-sample forecasts. Separate models preserve the legacy load MLP.'
first=s.find(marker); second=s.find(marker,first+1)
end=s.find('# Energy Brain: local, explainable unsupervised load-event learning.',second)
if second!=-1 and end!=-1: s=s[:second]+s[end:]
s=s.replace("    multichannel=train_multichannel_mlp(rows)\n    multichannel=train_multichannel_mlp(rows)\n","    multichannel=train_multichannel_mlp(rows)\n")
s=s.replace("        mae=sum(abs(pred(x)-y)*scale for x,y in test_seq)/len(test_seq)\n        nxt=pred([v/scale for _,v in vals[-6:]])*scale if len(vals)>=6 else None",
"        mae=sum(abs(pred(x)-y)*scale for x,y in test_seq)/len(test_seq)\n        # Persistence baseline: predict that the next sample equals the latest sample.\n        baseline_mae=sum(abs(x[-1]-y)*scale for x,y in test_seq)/len(test_seq)\n        improvement=((baseline_mae-mae)/baseline_mae*100.0) if baseline_mae>0 else 0.0\n        nxt=pred([v/scale for _,v in vals[-6:]])*scale if len(vals)>=6 else None")
s=s.replace("'validation_samples':len(test_seq),'mae_w':round(mae),'next_w':round(nxt) if nxt is not None else None,'status':'Trainiert · Zukunftsprüfung'",
"'validation_samples':len(test_seq),'mae_w':round(mae),'baseline_mae_w':round(baseline_mae),'improvement_pct':round(improvement,1),'beats_baseline':mae<baseline_mae,'next_w':round(nxt) if nxt is not None else None,'status':'Trainiert · Zukunftsprüfung'")
p.write_text(s)
# update template
p=Path('/mnt/data/ez121work/templates/energy_brain.html'); s=p.read_text()
s=s.replace('<th>Prüffehler MAE</th><th>Nächster Wert</th>', '<th>Netz-MAE</th><th>Einfacher Vergleich (letzter Wert)</th><th>Verbesserung</th><th>Nächster Wert</th>')
s=s.replace("{% if c.mae_w is not none %}{{c.mae_w}} W{% else %}–{% endif %}</td><td>{% if c.next_w is not none %}", "{% if c.mae_w is not none %}{{c.mae_w}} W{% else %}–{% endif %}</td><td>{% if c.baseline_mae_w is defined %}{{c.baseline_mae_w}} W{% else %}–{% endif %}</td><td>{% if c.improvement_pct is defined %}{{c.improvement_pct}} % {% if c.beats_baseline %}besser{% else %}nicht besser{% endif %}{% else %}–{% endif %}</td><td>{% if c.next_w is not none %}")
s=s.replace('MLP je Energiekanal · Architektur', 'MLP je Energiekanal · Architektur')
s=s.replace('Die Vorhersage ist keine Regelung.', 'Der Vergleich zeigt, ob das neuronale Netz besser ist als die einfache Annahme „nächster Wert = letzter Wert“. Negative Verbesserung bedeutet: Das einfache Verfahren ist derzeit besser. Die Vorhersage ist keine Regelung.')
p.write_text(s)
# version metadata
for fn in ['config.yaml','README.md','templates/base.html']:
 p=Path('/mnt/data/ez121work')/fn; t=p.read_text().replace('1.2.20','1.2.21'); p.write_text(t)
Path('/mnt/data/ez121work/RELEASE_NOTES_1.2.21.md').write_text('''# Energiezentrale HA 1.2.21\n\n- Entfernt doppelte Definition des Mehrkanal-Trainings und doppelten Trainingsaufruf pro Seitenaufruf.\n- Ergänzt je Energiekanal den Vergleich des neuronalen Modells mit einer einfachen Persistenz-Prognose (nächster Wert = letzter Messwert).\n- Zeigt MAE, Basis-MAE und prozentuale Verbesserung an. Damit ist sichtbar, ob das neuronale Netz tatsächlich einen Mehrwert liefert.\n- Bestehende Modell- und Verlaufsdateien bleiben kompatibel und werden nicht gelöscht.\n- Weiterhin ausschließlich lokal und beratend; keine Steuerbefehle.\n''')
