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
'control_entities':{'mode':'select.sofar_speicher_inverter_energy_storage_mode','grid_setpoint':'number.sofar_speicher_inverter_passive_desired_grid_power','charge_power':'number.sofar_speicher_inverter_passive_maximum_battery_power','discharge_power':'number.sofar_speicher_inverter_passive_minimum_battery_power','apply_button':'button.sofar_speicher_inverter_passive_update_battery_charge_discharge'},'settings':{'grid_import_limit_w':5000,'battery_reserve_percent':25,'inverter_count':2,'control_enabled':False,'mode':'observe','grid_setpoint_sign':'unverified','grid_import_sign':'unverified','morning_start_hour':5,'morning_end_hour':9,'learning_days':14,'battery_capacity_kwh':80,'battery_discharge_power_kw':30,'silage_slots':['06:30','12:00','18:00'],'silage_flex_minutes':45,'silage_duration_minutes':15,'feeding_slots':['06:45','12:00','18:15'],'feeding_flex_minutes':10,'feeding_duration_minutes':8,'feeding_power_w':0,'consumer_surplus_margin_w':1000}}
def config():
 if not CFG.exists(): CFG.write_text(json.dumps(DEFAULT,ensure_ascii=False,indent=2))
 try:
  c=json.loads(CFG.read_text()); c.setdefault('plant_name',DEFAULT['plant_name']); c.setdefault('sensors',{})
  for k,v in DEFAULT['sensors'].items(): c['sensors'].setdefault(k,v)
  c.setdefault('consumers',DEFAULT['consumers']); c.setdefault('settings',{}); c.setdefault('control_entities',DEFAULT['control_entities'])
  for k,v in DEFAULT['settings'].items(): c['settings'].setdefault(k,v)
  # Migrate the known mistaken 30 kW grid-import target to the intended soft target of 5 kW.
  # This affects only the advisory setting; no device commands are sent.
  if c['settings'].get('grid_import_limit_w') == 30000:
   c['settings']['grid_import_limit_w'] = 5000
   try: save(c)
   except Exception: pass
  for k,v in DEFAULT['control_entities'].items(): c['control_entities'].setdefault(k,v)
  return c
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
  time.sleep(max(5,int(os.getenv('SAMPLE_INTERVAL_SECONDS','15'))))


def build_battery_plan(c, rows, snap=None):
    """Advisory battery plan from measured morning peaks and configured PV forecast.
    No inverter/consumer commands are sent by this function."""
    st = c.get('settings', {})
    sign = st.get('grid_import_sign', 'unverified')
    target_w = max(0.0, float(st.get('grid_import_limit_w', 5000)))
    reserve_pct = max(0.0, min(100.0, float(st.get('battery_reserve_percent', 25))))
    capacity_kwh = max(0.0, float(st.get('battery_capacity_kwh', 80)))
    max_discharge_kw = max(0.0, float(st.get('battery_discharge_power_kw', 30)))
    morning_start = int(st.get('morning_start_hour', 5))
    morning_end = int(st.get('morning_end_hour', 9))
    now = datetime.now().astimezone()
    cutoff = now.timestamp() - max(1, int(st.get('learning_days', 14))) * 86400
    daily = {}
    for row in rows:
        try:
            ts = datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            if ts < cutoff: continue
            dt = datetime.fromtimestamp(ts).astimezone()
            if not (morning_start <= dt.hour < morning_end): continue
            raw = row.get('values', {}).get('grid_power')
            if not isinstance(raw, (int,float)): continue
            imp = (-float(raw) if sign == 'negative' else float(raw) if sign == 'positive' else None)
            if imp is None: continue
            daily.setdefault(dt.date().isoformat(), []).append(max(0.0, imp))
        except Exception:
            continue
    # Integrate excess energy only across adjacent, sufficiently close samples.
    # Long gaps are not extrapolated, avoiding a falsely precise reserve estimate.
    daily_excess_kwh = {}
    daily_peak_w = {day: max(vals) if vals else 0.0 for day, vals in daily.items()}
    samples_by_day = {}
    for row in rows:
        try:
            ts = datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            if ts < cutoff: continue
            dt = datetime.fromtimestamp(ts).astimezone()
            if not (morning_start <= dt.hour < morning_end): continue
            raw = row.get('values', {}).get('grid_power')
            if not isinstance(raw, (int,float)): continue
            imp = (-float(raw) if sign == 'negative' else float(raw) if sign == 'positive' else None)
            if imp is None: continue
            samples_by_day.setdefault(dt.date().isoformat(), []).append((ts, max(0.0, imp)))
        except Exception:
            continue
    sample_s = max(5, int(os.getenv('SAMPLE_INTERVAL_SECONDS','15')))
    for day, points in samples_by_day.items():
        points.sort()
        energy = 0.0
        for (t0, p0), (t1, p1) in zip(points, points[1:]):
            dt_s = t1 - t0
            if 0 < dt_s <= sample_s * 2.5:
                # Trapezoid integration of power above the soft grid target.
                a = max(0.0, p0 - target_w)
                b = max(0.0, p1 - target_w)
                energy += ((a + b) / 2.0) * dt_s / 3600.0 / 1000.0
        daily_excess_kwh[day] = energy
    enough = len(daily) >= 3
    peak_median = statistics.median(daily_peak_w.values()) if enough else None
    excess_median = statistics.median(daily_excess_kwh.values()) if enough else None
    vals = {k: ((v or {}).get('value')) for k,v in (snap or snapshot()).get('values',{}).items()}
    def number(x):
        return float(x) if isinstance(x,(int,float)) else None
    soc = number(vals.get('battery_soc'))
    pv_forecast = number(vals.get('pv_forecast'))
    load = number(vals.get('load_power'))
    # Solcast entity commonly reports Wh; convert to kWh if its unit indicates Wh.
    pv_unit = ((snap or snapshot()).get('values',{}).get('pv_forecast') or {}).get('unit','').lower()
    pv_kwh = (pv_forecast/1000.0 if pv_forecast is not None and ('wh' == pv_unit or 'wh' in pv_unit and 'kwh' not in pv_unit) else pv_forecast) if pv_forecast is not None else None
    if soc is not None:
        reserve_kwh = capacity_kwh * reserve_pct / 100.0
        current_kwh = capacity_kwh * max(0.0,min(100.0,soc)) / 100.0
        usable_above_reserve = max(0.0, current_kwh-reserve_kwh)
    else:
        reserve_kwh = current_kwh = usable_above_reserve = None
    # Required energy includes the empirical energy above the soft grid target,
    # but never invents a forecast if insufficient historical data exists.
    required_kwh = max(reserve_kwh or 0.0, (reserve_kwh or 0.0) + (excess_median or 0.0)) if enough else None
    target_soc = min(100.0, required_kwh/capacity_kwh*100.0) if required_kwh is not None and capacity_kwh else None
    advice = []
    if not enough:
        advice.append(f'Für belastbare Batterieplanung werden mindestens drei vollständige Morgen mit gültigen Netzleistungsdaten benötigt; aktuell: {len(daily)}.')
    else:
        advice.append(f'Median der morgendlichen Netzbezugs-Spitzen: {peak_median:.0f} W.')
        advice.append(f'Geschätzte tägliche Energie oberhalb des weichen {target_w:.0f}-W-Ziels: {excess_median:.2f} kWh.')
        advice.append(f'Vorläufig empfohlene Reserve inklusive Grundreserve: {required_kwh:.1f} kWh (ca. {target_soc:.0f} % SoC).')
    if soc is None: advice.append('Batterie-SoC fehlt; aktuelle verfügbare Energie kann nicht berechnet werden.')
    elif usable_above_reserve is not None: advice.append(f'Aktuell geschätzte Energie oberhalb der Grundreserve: {usable_above_reserve:.1f} kWh.')
    if pv_kwh is None: advice.append('Keine gültige PV-Prognose gefunden; Prognose-Entity und Einheit prüfen.')
    else: advice.append(f'PV-Prognose aus Home Assistant: etwa {pv_kwh:.1f} kWh (Einheit anhand Sensorattributen interpretiert).')
    if load is not None: advice.append(f'Aktueller Hausverbrauch: {load:.0f} W; dies ist kein Tagesverbrauchs-Forecast.')
    advice.append('Nur Empfehlung: Diese Planung sendet keine Befehle an Wechselrichter oder Verbraucher.')
    return {'mode':'advisory_only','commands_sent':False,'history_days_available':len(daily),
        'target_grid_import_w':target_w,'grid_import_sign':sign,'battery_capacity_kwh':capacity_kwh,
        'max_discharge_power_kw':max_discharge_kw,'battery_soc_percent':soc,
        'current_energy_kwh':current_kwh,'base_reserve_kwh':reserve_kwh,
        'usable_energy_above_base_reserve_kwh':usable_above_reserve,
        'median_morning_peak_w':peak_median,'median_energy_above_grid_target_kwh':excess_median,
        'recommended_morning_reserve_kwh':required_kwh,'recommended_morning_soc_percent':target_soc,
        'pv_forecast_kwh':pv_kwh,'advice':advice}

@app.route('/')
def index():
 c=config(); s=snapshot(); _,err=states(); return render_template('index.html',cfg=c,snap=s,ha_error=err)
@app.route('/simulation')
def simulation():
 c=config(); snap=snapshot(); vals={k:((v or {}).get('value')) for k,v in snap.get('values',{}).items()}
 st=c.get('settings',{}); sign=st.get('grid_import_sign','unverified'); raw=vals.get('grid_power')
 grid_import=(-raw if sign=='negative' else raw if sign=='positive' else None) if isinstance(raw,(int,float)) else None
 pv=vals.get('pv_power'); load=vals.get('load_power'); soc=vals.get('battery_soc')
 surplus=(pv-load) if isinstance(pv,(int,float)) and isinstance(load,(int,float)) else None
 rows=[]
 if HIST.exists():
  try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
  except Exception: rows=[]
 battery=build_battery_plan(c,rows,snap)
 missing=[c.get('sensors',{}).get(k,{}).get('label',k) for k in ('pv_power','load_power','grid_power','battery_soc') if not isinstance(vals.get(k),(int,float))]
 return render_template('simulation.html',cfg=c,snap=snap,vals=vals,grid_import=grid_import,surplus=surplus,battery=battery,missing=missing,history_count=len(rows),sign=sign)

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
  for k in c['control_entities']:
   val=request.form.get('control_'+k,'').strip()
   if val:c['control_entities'][k]=val
  try:
   c['settings']['grid_import_limit_w']=max(0,int(request.form.get('grid_import_limit_w','5000')))
   c['settings']['battery_reserve_percent']=max(0,min(100,int(request.form.get('battery_reserve_percent','25'))))
   c['settings']['inverter_count']=max(1,min(10,int(request.form.get('inverter_count','2'))))
   c['settings']['battery_capacity_kwh']=max(1,min(500,int(request.form.get('battery_capacity_kwh','80'))))
   c['settings']['battery_discharge_power_kw']=max(1,min(100,int(request.form.get('battery_discharge_power_kw','30'))))
   c['settings']['control_enabled']=False
   c['settings']['mode']='observe'
   c['settings']['morning_start_hour']=max(0,min(23,int(request.form.get('morning_start_hour','5'))))
   c['settings']['morning_end_hour']=max(1,min(24,int(request.form.get('morning_end_hour','9'))))
   c['settings']['grid_import_sign']=request.form.get('grid_import_sign','unverified') if request.form.get('grid_import_sign','unverified') in ('positive','negative','unverified') else 'unverified'
  except ValueError:flash('Grenzwerte müssen Zahlen sein.','error');return render_template('config.html',cfg=c,states=entities,ha_error=err)
  save(c);flash('Konfiguration gespeichert. Es wurden keine Geräte geschaltet.','success');entities,err=states();return render_template('config.html',cfg=c,states=entities,ha_error=err)
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
  slots=[]
  for field in ('silage_slot_1','silage_slot_2','silage_slot_3'):
   value=request.form.get(field,'').strip()
   if value and len(value)==5 and value[2]==':' and value[:2].isdigit() and value[3:].isdigit() and 0<=int(value[:2])<=23 and 0<=int(value[3:])<=59: slots.append(value)
  c['settings']['silage_slots']=slots
  try:c['settings']['silage_flex_minutes']=min(180,max(0,int(request.form.get('silage_flex_minutes','45'))))
  except ValueError:c['settings']['silage_flex_minutes']=45
  try:c['settings']['silage_duration_minutes']=min(120,max(1,int(request.form.get('silage_duration_minutes','15'))))
  except ValueError:c['settings']['silage_duration_minutes']=15
  feeding=[]
  for field in ('feeding_slot_1','feeding_slot_2','feeding_slot_3'):
   value=request.form.get(field,'').strip()
   if value and len(value)==5 and value[2]==':' and value[:2].isdigit() and value[3:].isdigit() and 0<=int(value[:2])<=23 and 0<=int(value[3:])<=59: feeding.append(value)
  c['settings']['feeding_slots']=feeding
  try:c['settings']['feeding_flex_minutes']=min(180,max(0,int(request.form.get('feeding_flex_minutes','10'))))
  except ValueError:c['settings']['feeding_flex_minutes']=10
  try:c['settings']['feeding_duration_minutes']=min(60,max(1,int(request.form.get('feeding_duration_minutes','8'))))
  except ValueError:c['settings']['feeding_duration_minutes']=8
  try:c['settings']['feeding_power_w']=min(100000,max(0,int(request.form.get('feeding_power_w','0'))))
  except ValueError:c['settings']['feeding_power_w']=0
  try:c['settings']['consumer_surplus_margin_w']=min(20000,max(0,int(request.form.get('consumer_surplus_margin_w','1000'))))
  except ValueError:c['settings']['consumer_surplus_margin_w']=1000
  save(c);flash('Verbraucher und flexible Zeitfenster gespeichert. Steuerung bleibt deaktiviert.','success');return render_template('consumers.html',cfg=c)
 return render_template('consumers.html',cfg=c)
@app.route('/learning')
def learning():
    rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    now=datetime.now(timezone.utc)
    days=int(config().get('settings',{}).get('learning_days',14))
    cutoff=now.timestamp()-days*86400
    recent=[]
    for r in rows:
        try:
            ts=datetime.fromisoformat(r.get('timestamp','').replace('Z','+00:00')).timestamp()
            if ts>=cutoff: recent.append((ts,r))
        except Exception: pass
    stats={}
    for k in ['pv_power','load_power','grid_power','battery_soc','battery_power']:
        vals=[r.get('values',{}).get(k) for _,r in recent]
        vals=[float(v) for v in vals if isinstance(v,(int,float))]
        stats[k]={'count':len(vals),'average':round(statistics.mean(vals),1) if vals else None,'min':round(min(vals),1) if vals else None,'max':round(max(vals),1) if vals else None}
    c=config(); st=c.get('settings',{}); sign=st.get('grid_import_sign','unverified')
    morning=[]
    for ts,r in recent:
        dt=datetime.fromtimestamp(ts).astimezone()
        if int(st.get('morning_start_hour',5)) <= dt.hour < int(st.get('morning_end_hour',9)):
            v=r.get('values',{}).get('grid_power')
            if isinstance(v,(int,float)):
                import_w=float(v) if sign=='positive' else (-float(v) if sign=='negative' else None)
                if import_w is not None: morning.append({'day':dt.date().isoformat(),'hour':dt.hour,'grid_import_w':max(0,import_w)})
    daily={}
    for x in morning: daily[x['day']]=max(daily.get(x['day'],0),x['grid_import_w'])
    learned_peak=round(statistics.median(daily.values()),0) if len(daily)>=3 else None
    battery_plan=build_battery_plan(c, rows, snapshot())
    return render_template('learning.html',cfg=c,stats=stats,count=len(recent),history_file=str(HIST),days=days,
        morning_count=len(daily),morning_peak=learned_peak,grid_import_sign=sign,daily_peaks=daily,battery_plan=battery_plan)

@app.route('/api/plan')
def api_plan():
    """Advisory plan only: never sends commands to inverter or consumers."""
    c=config(); snap=snapshot()
    vals={k:((v or {}).get('value')) for k,v in snap.get('values',{}).items()}
    def num(k):
        v=vals.get(k)
        return float(v) if isinstance(v,(int,float)) else None
    pv=num('pv_power'); load=num('load_power'); grid=num('grid_power'); soc=num('battery_soc')
    target=float(c.get('settings',{}).get('grid_import_limit_w',5000))
    reserve=float(c.get('settings',{}).get('battery_reserve_percent',25))
    sign=c.get('settings',{}).get('grid_import_sign','unverified')
    grid_import_w=(-grid if sign=='negative' else grid if sign=='positive' else None) if grid is not None else None
    surplus=(pv-load) if pv is not None and load is not None else None
    quality=[]
    for k in ('pv_power','load_power','grid_power','battery_soc'):
        item=snap.get('values',{}).get(k)
        if not item or item.get('value') is None: quality.append(k)
    advice=[]
    consumers=sorted([x for x in c.get('consumers',[]) if x.get('enabled')], key=lambda x:int(x.get('priority',99)))
    if surplus is not None:
        if surplus > 500:
            available=[x for x in consumers if int(x.get('nominal_power_w',0)) <= surplus]
            names=', '.join(x.get('name','Verbraucher') for x in available[:3])
            advice.append({'type':'surplus','message':f'Geschätzter PV-Überschuss: {surplus:.0f} W.' + (f' Nach Nennleistung passend: {names}.' if names else ' Kein aktivierter Verbraucher passt mit seiner Nennleistung vollständig in den geschätzten Überschuss.')})
        elif surplus < -500: advice.append({'type':'deficit','message':f'PV liegt etwa {abs(surplus):.0f} W unter dem Hausverbrauch.'})
        else: advice.append({'type':'balanced','message':'PV und Hausverbrauch liegen ungefähr auf gleichem Niveau.'})
    if grid_import_w is not None and grid_import_w > target:
        advice.append({'type':'grid_target','message':f'Netzbezug liegt {grid_import_w-target:.0f} W über dem weichen Ziel von {target:.0f} W.'})
    if soc is not None and soc < reserve: advice.append({'type':'reserve','message':f'Batterie-SoC liegt unter der eingestellten Reserve von {reserve:.0f} %.'})
    return jsonify({'timestamp':snap.get('timestamp'),'mode':'advisory_only','commands_sent':False,
        'target_grid_import_w':target,'grid_import_sign':sign,'grid_import_w':grid_import_w,
        'inverter_count':int(c.get('settings',{}).get('inverter_count',2)),'values':vals,
        'estimated_pv_minus_load_w':surplus,'missing_or_invalid_sensors':quality,'advice':advice})

@app.route('/api/consumer-plan')
def api_consumer_plan():
    """Suggest suitable consumer stages from measured grid export; advisory only."""
    c = config()
    snap = snapshot()
    item = (snap.get('values', {}).get('grid_power') or {})
    raw = item.get('value')
    sign = c.get('settings', {}).get('grid_import_sign', 'unverified')
    export_w = None
    if isinstance(raw, (int, float)):
        if sign == 'negative':
            export_w = max(0.0, float(raw))
        elif sign == 'positive':
            export_w = max(0.0, -float(raw))
    margin_w = max(0, int(c.get('settings', {}).get('consumer_surplus_margin_w', 1000)))
    available_w = max(0.0, export_w - margin_w) if export_w is not None else None
    recommendations = []
    consumers = sorted((x for x in c.get('consumers', []) if x.get('enabled')),
                       key=lambda x: int(x.get('priority', 99)))
    remaining = available_w
    if remaining is not None:
        for consumer in consumers:
            try:
                stages = sorted({int(v) for v in consumer.get('stages_w', []) if int(v) > 0})
            except (TypeError, ValueError):
                stages = []
            nominal = max(0, int(consumer.get('nominal_power_w', 0)))
            options = [v for v in stages if v <= remaining]
            chosen = max(options) if options else (nominal if nominal and nominal <= remaining else 0)
            recommendations.append({
                'id': consumer.get('id'), 'name': consumer.get('name', 'Verbraucher'),
                'priority': int(consumer.get('priority', 99)), 'nominal_power_w': nominal,
                'suggested_power_w': chosen,
                'status': 'fits' if chosen > 0 else 'wait',
                'note': (f'{chosen} W passen rechnerisch in den verfügbaren Überschuss.' if chosen > 0
                         else 'Der verfügbare Überschuss reicht mit Sicherheitsabstand nicht für eine Stufe.')
            })
            remaining = max(0.0, remaining - chosen)
    return jsonify({
        'timestamp': snap.get('timestamp'), 'mode': 'advisory_only', 'commands_sent': False,
        'grid_import_sign': sign, 'grid_power_raw_w': raw, 'estimated_export_w': export_w,
        'safety_margin_w': margin_w, 'available_surplus_after_margin_w': available_w,
        'recommendations': recommendations,
        'warning': ('Netzleistungs-Vorzeichen erst in der Konfiguration bestätigen.' if export_w is None else
                    'Nur Vorschlag: keine Verbraucher werden geschaltet. Vor dem Betrieb Anlaufstrom, Mindestlaufzeiten und Verriegelungen berücksichtigen.')
    })

@app.route('/api/battery-plan')
def api_battery_plan():
    rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    return jsonify(build_battery_plan(config(), rows, snapshot()))


@app.route('/api/peak-analysis')
def api_peak_analysis():
    """Historical soft-grid-target analysis; respects actual timestamp gaps."""
    c=config(); st=c.get('settings',{}); sign=st.get('grid_import_sign','unverified')
    target=max(0,float(st.get('grid_import_limit_w',5000)))
    days=max(1,min(90,int(st.get('learning_days',14))))
    rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    cutoff=datetime.now(timezone.utc).timestamp()-days*86400
    samples=[]
    for row in rows:
        try:
            ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            raw=row.get('values',{}).get('grid_power')
            if ts<cutoff or not isinstance(raw,(int,float)): continue
            imp=(-float(raw) if sign=='negative' else float(raw) if sign=='positive' else None)
            if imp is not None: samples.append((ts,max(0,imp)))
        except Exception: continue
    samples.sort(); daily={}; over_count=0; max_gap=max(30,int(os.getenv('SAMPLE_INTERVAL_SECONDS','15'))*2)
    for i,(ts,w) in enumerate(samples):
        day=datetime.fromtimestamp(ts).astimezone().date().isoformat()
        d=daily.setdefault(day,{'peak_w':0,'samples_over_target':0,'estimated_minutes_over_target':0.0})
        d['peak_w']=max(d['peak_w'],round(w));
        if w>target:
            over_count+=1; d['samples_over_target']+=1
            if i+1<len(samples) and samples[i+1][0]-ts<=max_gap:
                d['estimated_minutes_over_target']+=(samples[i+1][0]-ts)/60.0
    return jsonify({'mode':'advisory_only','commands_sent':False,'target_w':target,'sign':sign,'days_requested':days,'valid_samples':len(samples),'samples_over_target':over_count,'daily':daily,'warning':'Dauer oberhalb des Ziels ist nur eine Schätzung aus benachbarten Messpunkten; Datenlücken werden nicht hochgerechnet.' if sign!='unverified' else 'Netzleistungs-Vorzeichen zuerst in der Konfiguration bestätigen.'})

@app.route('/health')
def health():return jsonify({'status':'ok','mode':'observe','active_control_enabled':False,'timestamp':datetime.now(timezone.utc).isoformat()})
if __name__=='__main__':
 threading.Thread(target=sampler,daemon=True).start();app.run(host='0.0.0.0',port=int(os.getenv('PORT','8099')))
