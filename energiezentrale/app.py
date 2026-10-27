import os,json,time,threading,statistics
from datetime import datetime,timezone
from pathlib import Path
from flask import Flask,render_template,request,redirect,url_for,flash,jsonify
import requests
app=Flask(__name__); app.secret_key='local-energy-app'
DATA=Path('/data'); DATA.mkdir(exist_ok=True); CFG=DATA/'config.json'; HIST=DATA/'history.jsonl'
DEFAULT={'plant_name':'Meine Energiezentrale','sensors':{
'pv_power':{'label':'PV-Leistung','entity_id':'sensor.sofar_speicher_pv_power_total','unit':'W'},
'load_power':{'label':'Hausverbrauch','entity_id':'sensor.sofar_speicher_active_power_load_sys','unit':'W'},
'grid_power':{'label':'Netzbezug / Einspeisung','entity_id':'sensor.sofar_speicher_active_power_pcc_total','unit':'W'},
'battery_power':{'label':'Batterieleistung','entity_id':'sensor.sofar_speicher_battery_power_total','unit':'W'},
'battery_soc':{'label':'Batterieladezustand (SoC)','entity_id':'sensor.sofar_speicher_battery_soc','unit':'%'},
'inverter_output':{'label':'Wechselrichter-Ausgangsleistung','entity_id':'sensor.sofar_speicher_active_power_output_total','unit':'W'},
'pv_forecast':{'label':'PV-Prognose','entity_id':'sensor.solcast_pv_forecast_prognose_heute','unit':'Wh'}},
'consumers':[{'id':'heater','name':'Elektroheizung','type':'heater','enabled':True,'nominal_power_w':30000,'stages_w':[7500,15000,22500,30000],'priority':1},{'id':'compressor','name':'Kompressor','type':'motor','enabled':True,'nominal_power_w':11000,'stages_w':[],'priority':2}],
'settings':{'grid_import_limit_w':30000,'battery_reserve_percent':25,'mode':'observe'}}
def config():
 if not CFG.exists(): CFG.write_text(json.dumps(DEFAULT,ensure_ascii=False,indent=2))
 try:
  c=json.loads(CFG.read_text()); c.setdefault('plant_name',DEFAULT['plant_name']); c.setdefault('sensors',{})
  for k,v in DEFAULT['sensors'].items(): c['sensors'].setdefault(k,v)
  c.setdefault('consumers',DEFAULT['consumers']); c.setdefault('settings',DEFAULT['settings']); return c
 except Exception: return json.loads(json.dumps(DEFAULT))
def save(c): CFG.write_text(json.dumps(c,ensure_ascii=False,indent=2))
def ha(path):
 token=os.getenv('SUPERVISOR_TOKEN')
 if not token:return None,'Supervisor-Token fehlt – bitte als Home-Assistant-Add-on starten.'
 try:
  r=requests.get('http://supervisor/core/api/'+path.lstrip('/'),headers={'Authorization':'Bearer '+token},timeout=8);r.raise_for_status();return r.json(),None
 except Exception as e:return None,str(e)
def states():
 data,err=ha('states')
 if err:return [],err
 return [{'entity_id':s.get('entity_id',''),'name':s.get('attributes',{}).get('friendly_name',s.get('entity_id','')),'state':s.get('state','unknown'),'unit':s.get('attributes',{}).get('unit_of_measurement','')} for s in data],None
def get_value(eid):
 if not eid:return None
 s,err=ha('states/'+eid)
 if err or not isinstance(s,dict):return None
 try:v=float(s.get('state'))
 except (ValueError,TypeError):v=None
 return {'value':v,'state':s.get('state'),'unit':s.get('attributes',{}).get('unit_of_measurement',''),'updated':s.get('last_updated')}
def snapshot():
 c=config(); return {'timestamp':datetime.now(timezone.utc).isoformat(),'values':{k:get_value(v.get('entity_id','')) for k,v in c['sensors'].items()}}
def sampler():
 while True:
  try:
   s=snapshot(); row={'timestamp':s['timestamp'],'values':{k:(v or {}).get('value') for k,v in s['values'].items()}}
   with HIST.open('a') as f:f.write(json.dumps(row)+'\n')
   if HIST.stat().st_size>15000000:
    lines=HIST.read_text().splitlines()[-10000:]; HIST.write_text('\n'.join(lines)+'\n')
  except Exception:pass
  time.sleep(max(60,int(os.getenv('SAMPLE_INTERVAL_SECONDS','300'))))
@app.route('/')
def index():
 c=config(); s=snapshot(); _,err=states(); return render_template('index.html',cfg=c,snap=s,ha_error=err)
@app.route('/api/snapshot')
def api_snapshot():return jsonify(snapshot())
@app.route('/config',methods=['GET','POST'])
def config_page():
 c=config(); entities,err=states()
 if request.method=='POST':
  c['plant_name']=request.form.get('plant_name','Meine Energiezentrale').strip() or 'Meine Energiezentrale'
  for k,v in c['sensors'].items():
   val=request.form.get('sensor_'+k,'').strip()
   if val:v['entity_id']=val
  try:c['settings']['grid_import_limit_w']=max(0,int(request.form.get('grid_import_limit_w','30000')));c['settings']['battery_reserve_percent']=max(0,min(100,int(request.form.get('battery_reserve_percent','25'))))
  except ValueError:flash('Grenzwerte müssen Zahlen sein.','error');return render_template('config.html',cfg=c,states=entities,ha_error=err)
  save(c);flash('Konfiguration gespeichert. Es wurden keine Geräte geschaltet.','success');return redirect(url_for('config_page'))
 return render_template('config.html',cfg=c,states=entities,ha_error=err)
@app.route('/consumers',methods=['GET','POST'])
def consumers():
 c=config()
 if request.method=='POST':
  names=request.form.getlist('consumer_name'); powers=request.form.getlist('consumer_power'); priorities=request.form.getlist('consumer_priority'); enabled=request.form.getlist('consumer_enabled')
  for i,x in enumerate(c['consumers']):
   try:x['name']=names[i].strip() or x['name'];x['nominal_power_w']=max(0,int(powers[i]));x['priority']=max(1,int(priorities[i]))
   except (IndexError,ValueError):pass
   x['enabled']=str(i) in enabled
  name=request.form.get('new_name','').strip()
  if name:
   try:p=max(0,int(request.form.get('new_power','0')))
   except ValueError:p=0
   c['consumers'].append({'id':'consumer_'+str(int(time.time())),'name':name,'type':'custom','enabled':True,'nominal_power_w':p,'stages_w':[],'priority':3})
  save(c);flash('Verbraucher gespeichert. Steuerung bleibt deaktiviert.','success');return redirect(url_for('consumers'))
 return render_template('consumers.html',cfg=c)
@app.route('/learning')
def learning():
 rows=[]
 if HIST.exists():
  try:rows=[json.loads(x) for x in HIST.read_text().splitlines()[-288:] if x.strip()]
  except Exception:pass
 stats={}
 for k in ['pv_power','load_power','grid_power','battery_soc']:
  vals=[r.get('values',{}).get(k) for r in rows];vals=[float(v) for v in vals if isinstance(v,(int,float))]
  stats[k]={'count':len(vals),'average':round(statistics.mean(vals),1) if vals else None,'min':round(min(vals),1) if vals else None,'max':round(max(vals),1) if vals else None}
 return render_template('learning.html',stats=stats,count=len(rows),history_file=str(HIST))
@app.route('/health')
def health():return jsonify({'status':'ok','mode':'read_only','timestamp':datetime.now(timezone.utc).isoformat()})
if __name__=='__main__':
 threading.Thread(target=sampler,daemon=True).start();app.run(host='0.0.0.0',port=int(os.getenv('PORT','8099')))
