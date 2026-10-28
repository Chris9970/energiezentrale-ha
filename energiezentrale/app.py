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
'control_entities':{'mode':'select.sofar_speicher_inverter_energy_storage_mode','grid_setpoint':'number.sofar_speicher_inverter_passive_desired_grid_power','charge_power':'number.sofar_speicher_inverter_passive_maximum_battery_power','discharge_power':'number.sofar_speicher_inverter_passive_minimum_battery_power','apply_button':'button.sofar_speicher_inverter_passive_update_battery_charge_discharge'},'settings':{'grid_import_limit_w':5000,'battery_reserve_percent':25,'inverter_count':2,'control_enabled':False,'mode':'observe','grid_setpoint_sign':'unverified','grid_import_sign':'unverified','battery_power_sign':'negative','morning_start_hour':5,'morning_end_hour':9,'learning_days':14,'morning_min_samples_per_day':60,'battery_capacity_kwh':80,'battery_discharge_power_kw':30,'silage_slots':['06:30','12:00','18:00'],'silage_flex_minutes':45,'silage_duration_minutes':15,'feeding_slots':['06:45','12:00','18:15'],'feeding_flex_minutes':10,'feeding_duration_minutes':8,'feeding_power_w':0,'consumer_surplus_margin_w':1000,'import_price_eur_kwh':0.30,'export_price_eur_kwh':0.04,'peak_alert_w':5000,'balance_alert_pct':15,'pv_forecast_mode':'daily_total'}}
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
    # Reject days with too few points: a handful of samples must not look like a complete morning.
    # At the default 15 s sampling interval, 60 points represent only 15 minutes; this is a
    # conservative minimum-data gate, not a claim of full-window coverage.
    min_points_per_day = max(30, int(st.get('morning_min_samples_per_day', 60)))
    # A high sample count from a short burst is not a complete morning. Require
    # both the configured minimum sample count and coverage across at least half
    # of the configured morning window; gaps are still excluded from integration.
    window_seconds = max(1, morning_end - morning_start) * 3600
    min_coverage_seconds = window_seconds * 0.50
    coverage_seconds = {}
    for day, points in samples_by_day.items():
        stamps = sorted(t for t, _ in points)
        coverage_seconds[day] = (stamps[-1] - stamps[0]) if len(stamps) >= 2 else 0
    valid_days = {
        day for day, points in samples_by_day.items()
        if len(points) >= min_points_per_day
        and coverage_seconds.get(day, 0) >= min_coverage_seconds
    }
    daily_peak_w = {day: daily_peak_w[day] for day in valid_days if day in daily_peak_w}
    daily_excess_kwh = {day: daily_excess_kwh[day] for day in valid_days if day in daily_excess_kwh}
    enough = len(valid_days) >= 3
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
        advice.append(f'Für belastbare Batterieplanung werden mindestens drei Morgen mit genügend Messpunkten und mindestens {int(min_coverage_seconds/60)} Minuten zeitlicher Abdeckung benötigt; gültig: {len(valid_days)}, verworfen: {len(set(samples_by_day)-valid_days)}.')
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
    return {'mode':'advisory_only','commands_sent':False,'history_days_available':len(valid_days),
        'days_rejected_for_sparse_data':len(set(samples_by_day)-valid_days),'minimum_samples_per_day':min_points_per_day,
        'minimum_morning_coverage_minutes':int(min_coverage_seconds/60),
        'morning_coverage_minutes_by_day':{day:round(seconds/60,1) for day,seconds in coverage_seconds.items()},
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
   c['settings']['battery_power_sign']=request.form.get('battery_power_sign','negative') if request.form.get('battery_power_sign','negative') in ('positive','negative') else 'negative'
   c['settings']['import_price_eur_kwh']=max(0,min(5,float(request.form.get('import_price_eur_kwh','0.30'))))
   c['settings']['export_price_eur_kwh']=max(0,min(5,float(request.form.get('export_price_eur_kwh','0.04'))))
   c['settings']['peak_alert_w']=max(500,int(request.form.get('peak_alert_w','5000')))
   c['settings']['balance_alert_pct']=max(1,min(100,float(request.form.get('balance_alert_pct','15'))))
   c['settings']['pv_forecast_mode']=request.form.get('pv_forecast_mode','daily_total') if request.form.get('pv_forecast_mode','daily_total') in ('daily_total','remaining') else 'daily_total'
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


@app.route('/diagnostics')
def diagnostics():
    c=config(); snap=snapshot(); vals={k:((v or {}).get('value')) for k,v in snap.get('values',{}).items()}
    rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    now=datetime.now().astimezone(); cutoff=now.timestamp()-86400
    recent=[]; days=set(); gaps=0; prev=None
    for row in rows:
        try:
            ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            if ts>=cutoff: recent.append(row)
            days.add(datetime.fromtimestamp(ts).astimezone().date().isoformat())
            if prev is not None and ts-prev>max(60, int(os.getenv('SAMPLE_INTERVAL_SECONDS','15'))*4): gaps+=1
            prev=ts
        except Exception: pass
    sensors=[]
    for key,meta in c.get('sensors',{}).items():
        v=(snap.get('values',{}).get(key) or {})
        age=None
        try: age=max(0,int((now-datetime.fromisoformat(v['updated'].replace('Z','+00:00')).astimezone()).total_seconds()))
        except Exception: pass
        value=v.get('value'); status='OK' if value is not None else 'Fehlt / nicht numerisch'
        if age is not None and age>300: status='Veraltet'
        sensors.append({'label':meta.get('label',key),'entity_id':meta.get('entity_id',''),'value':value,'unit':v.get('unit',''),'age':age,'status':status})
    # Compare PV and load without claiming a full physical balance.
    pv=vals.get('pv_power'); load=vals.get('load_power'); grid=vals.get('grid_power'); bat=vals.get('battery_power')
    balance=(pv-load) if isinstance(pv,(int,float)) and isinstance(load,(int,float)) else None
    battery=build_battery_plan(c,rows,snap)
    return render_template('diagnostics.html',cfg=c,sensors=sensors,history_count=len(rows),recent_count=len(recent),days=len(days),gaps=gaps,balance=balance,vals=vals,battery=battery)


@app.route('/energy-report')
def energy_report_page():
    c=config(); snap=snapshot(); rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    now=datetime.now().astimezone(); today=now.date().isoformat()
    by_day={}
    for r in rows:
        try:
            ts=datetime.fromisoformat(r.get('timestamp','').replace('Z','+00:00')).timestamp()
            day=datetime.fromtimestamp(ts).astimezone().date().isoformat()
            by_day.setdefault(day,[]).append((ts,r.get('values',{})))
        except Exception: pass
    def integrate_day(points):
        points.sort(key=lambda x:x[0]); keys=['pv_power','load_power']
        totals={k:0.0 for k in ['pv_kwh','load_kwh','grid_import_kwh','grid_export_kwh','battery_charge_kwh','battery_discharge_kwh']}
        coverage={k:0.0 for k in ['pv_power','load_power','grid_power','battery_power']}; accepted=0; rejected=0
        battery_sign = c.get('settings', {}).get('battery_power_sign', 'negative')
        grid_sign = c.get('settings', {}).get('grid_import_sign', 'negative')
        for (t0,a),(t1,b) in zip(points,points[1:]):
            dt=t1-t0
            if dt<=0 or dt>120: rejected+=1; continue
            accepted+=1
            for k in coverage:
                x=a.get(k); y=b.get(k)
                if isinstance(x,(int,float)) and isinstance(y,(int,float)):
                    energy=((float(x)+float(y))/2.0)*dt/3600000.0
                    coverage[k]+=dt
                    if k=='pv_power': totals['pv_kwh']+=max(0.0,energy)
                    elif k=='load_power': totals['load_kwh']+=max(0.0,energy)
                    elif k=='grid_power':
                        # Split each interval before summing; import and export must not cancel.
                        if grid_sign in ('negative', 'positive'):
                            ix, iy = ((-float(x), -float(y)) if grid_sign == 'negative' else (float(x), float(y)))
                            totals['grid_import_kwh'] += max(0.0,ix)*dt/3600000.0/2 + max(0.0,iy)*dt/3600000.0/2
                            totals['grid_export_kwh'] += max(0.0,-ix)*dt/3600000.0/2 + max(0.0,-iy)*dt/3600000.0/2
                    elif k=='battery_power':
                        # Normalize to positive = discharge, negative = charge.
                        bx, by = ((-float(x), -float(y)) if battery_sign == 'negative' else (float(x), float(y)))
                        totals['battery_discharge_kwh'] += max(0.0,bx)*dt/3600000.0/2 + max(0.0,by)*dt/3600000.0/2
                        totals['battery_charge_kwh'] += max(0.0,-bx)*dt/3600000.0/2 + max(0.0,-by)*dt/3600000.0/2
        supply=totals['pv_kwh']+totals['grid_import_kwh']+totals['battery_discharge_kwh']
        demand=totals['load_kwh']+totals['grid_export_kwh']+totals['battery_charge_kwh']
        residual=supply-demand
        totals.update({'balance_supply_kwh':supply,'balance_demand_kwh':demand,'balance_residual_kwh':residual,
                       'balance_residual_pct':abs(residual)/max(supply,demand,0.01)*100,
                       'accepted':accepted,'rejected':rejected,'samples':len(points),
                       'coverage':{k:round(v/3600,2) for k,v in coverage.items()}})
        return totals
    daily={day:integrate_day(points) for day,points in by_day.items()}
    today_data=daily.get(today,integrate_day([]))
    history_days=[]
    for day in sorted(daily,reverse=True)[:7]:
        history_days.append({'day':day,**daily[day]})
    forecast=(snap.get('values',{}).get('pv_forecast') or {})
    fv=forecast.get('value'); fu=(forecast.get('unit') or c.get('sensors',{}).get('pv_forecast',{}).get('unit','')).lower()
    forecast_kwh=None
    if isinstance(fv,(int,float)):
        forecast_kwh=float(fv)/1000 if 'wh' in fu and 'kwh' not in fu else float(fv)
    # Interpret the configured forecast semantics explicitly; do not silently subtract actual PV
    # from a forecast that already represents the remaining-day production.
    forecast_mode=c.get('settings',{}).get('pv_forecast_mode','daily_total')
    if forecast_kwh is not None and forecast_kwh < 0: forecast_kwh=None
    if forecast_kwh is not None and forecast_mode == 'daily_total':
        pv_remaining_kwh=max(0.0,forecast_kwh-today_data['pv_kwh'])
        pv_projected_total_kwh=max(forecast_kwh,today_data['pv_kwh'])
        forecast_label='Tagesgesamtprognose'
    elif forecast_kwh is not None:
        pv_remaining_kwh=forecast_kwh
        pv_projected_total_kwh=today_data['pv_kwh']+forecast_kwh
        forecast_label='Resttagesprognose'
    else:
        pv_remaining_kwh=None; pv_projected_total_kwh=None; forecast_label='Nicht verfügbar'
    return render_template('energy_report.html',cfg=c,day=today,energy=today_data,history_days=history_days,
      forecast_kwh=forecast_kwh,forecast_age=forecast.get('updated'),forecast_mode=forecast_mode,
      pv_remaining_kwh=pv_remaining_kwh,pv_projected_total_kwh=pv_projected_total_kwh,
      forecast_label=forecast_label,active_control_enabled=False)

@app.route('/api/energy-report')
def api_energy_report():
    c=config(); rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    now=datetime.now().astimezone(); start=now.timestamp()-86400; data=[]
    for r in rows:
        try:
            ts=datetime.fromisoformat(r.get('timestamp','').replace('Z','+00:00')).timestamp()
            if ts>=start:data.append(r)
        except Exception: pass
    def avg(k):
        x=[r.get('values',{}).get(k) for r in data if isinstance(r.get('values',{}).get(k),(int,float))]
        return round(sum(x)/len(x),1) if x else None
    return jsonify({'period':'last_24_hours','samples':len(data),'average_power_w':{'pv':avg('pv_power'),'load':avg('load_power'),'grid_raw':avg('grid_power'),'battery':avg('battery_power')},'note':'Durchschnittsleistungen, keine kWh-Energieintegration. Grid-Vorzeichen gemäß Konfiguration: '+str(c.get('settings',{}).get('grid_import_sign','unverified')),'active_control_enabled':False,'commands_sent':False})



@app.route('/analysis')
def analysis_page():
    """Read-only combined diagnostics: battery, peaks, costs, forecast and advisory loads."""
    c=config(); snap=snapshot(); rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    now=datetime.now().astimezone(); today=now.date().isoformat(); today_rows=[]
    for r in rows:
        try:
            ts=datetime.fromisoformat(r.get('timestamp','').replace('Z','+00:00')).timestamp()
            if datetime.fromtimestamp(ts).astimezone().date().isoformat()==today: today_rows.append((ts,r.get('values',{})))
        except Exception: pass
    today_rows.sort(key=lambda x:x[0]); st=c.get('settings',{})
    peaks=[]; high_seconds=0; pv_kwh=load_kwh=imp_kwh=exp_kwh=charge_kwh=discharge_kwh=0.0; soc_first=soc_last=None; accepted=0; rejected=0; alerts=[]
    grid_sign=st.get('grid_import_sign','unverified'); battery_sign=st.get('battery_power_sign','negative')
    grid_import_multiplier = -1.0 if grid_sign == 'negative' else (1.0 if grid_sign == 'positive' else None)
    battery_discharge_multiplier = -1.0 if battery_sign == 'negative' else 1.0
    for (t0,a),(t1,b) in zip(today_rows,today_rows[1:]):
        dt=t1-t0
        if dt<=0 or dt>120: rejected+=1; continue
        accepted+=1
        for k in ('pv_power','load_power'):
            x,y=a.get(k),b.get(k)
            if isinstance(x,(int,float)) and isinstance(y,(int,float)):
                e=max(0,(float(x)+float(y))*0.5)*dt/3600000
                if k=='pv_power': pv_kwh+=e
                else: load_kwh+=e
        for k in ('grid_power','battery_power'):
            x,y=a.get(k),b.get(k)
            if isinstance(x,(int,float)) and isinstance(y,(int,float)):
                if k=='grid_power':
                    if grid_import_multiplier is not None:
                        imp_kwh+=(max(0,grid_import_multiplier*float(x))+max(0,grid_import_multiplier*float(y)))*0.5*dt/3600000
                        exp_kwh+=(max(0,-grid_import_multiplier*float(x))+max(0,-grid_import_multiplier*float(y)))*0.5*dt/3600000
                else:
                    discharge_kwh+=(max(0,battery_discharge_multiplier*float(x))+max(0,battery_discharge_multiplier*float(y)))*0.5*dt/3600000
                    charge_kwh+=(max(0,-battery_discharge_multiplier*float(x))+max(0,-battery_discharge_multiplier*float(y)))*0.5*dt/3600000
        for v in (a.get('grid_power'),b.get('grid_power')):
            if grid_import_multiplier is not None and isinstance(v,(int,float)) and grid_import_multiplier*float(v)>float(st.get('peak_alert_w',5000)): peaks.append({'w':round(grid_import_multiplier*float(v)),'time':datetime.fromtimestamp(t0).astimezone().strftime('%H:%M')})
        if isinstance(a.get('battery_soc'),(int,float)) and soc_first is None: soc_first=float(a['battery_soc'])
        if isinstance(b.get('battery_soc'),(int,float)): soc_last=float(b['battery_soc'])
    peak=max(peaks,key=lambda x:x['w']) if peaks else None
    if grid_import_multiplier is None:
        alerts.append('Netzvorzeichen ist noch nicht bestätigt; Netzbezug, Einspeisung und Spitzen werden nicht zuverlässig bewertet.')
    forecast_obj=(snap.get('values',{}).get('pv_forecast') or {})
    fv=forecast_obj.get('value'); unit=((forecast_obj.get('unit') or c.get('sensors',{}).get('pv_forecast',{}).get('unit','Wh'))).lower()
    forecast_kwh=(float(fv)/1000 if 'wh' in unit and 'kwh' not in unit else float(fv)) if isinstance(fv,(int,float)) and float(fv)>=0 else None
    forecast_mode=st.get('pv_forecast_mode','daily_total')
    if forecast_kwh is not None and forecast_mode == 'daily_total':
        pv_remaining_kwh=max(0.0,forecast_kwh-pv_kwh)
        pv_projected_total_kwh=max(forecast_kwh,pv_kwh)
        forecast_label='Tagesgesamtprognose'
    elif forecast_kwh is not None:
        pv_remaining_kwh=forecast_kwh
        pv_projected_total_kwh=pv_kwh+forecast_kwh
        forecast_label='Resttagesprognose'
    else:
        pv_remaining_kwh=None
        pv_projected_total_kwh=None
        forecast_label='Nicht verfügbar'
    # Alerts are advisory only; do not infer a fault from an unchanged value alone.
    if rejected: alerts.append(f'{rejected} Messintervalle über 120 s ausgelassen; Tagesenergie kann unterschätzt sein.')
    residual=pv_kwh+imp_kwh+discharge_kwh-load_kwh-exp_kwh-charge_kwh
    residual_pct=abs(residual)/max(pv_kwh+imp_kwh+discharge_kwh,load_kwh+exp_kwh+charge_kwh,0.01)*100
    if residual_pct>float(st.get('balance_alert_pct',15)): alerts.append(f'Bilanzabweichung {residual:+.2f} kWh ({residual_pct:.1f} %): Messpunkte und Sensorvorzeichen prüfen.')
    if peak: alerts.append(f"Netzbezugsspitze über Planungsgrenze: {peak['w']} W um {peak['time']}.")
    price=max(0,float(st.get('import_price_eur_kwh',0.30))); export_price=max(0,float(st.get('export_price_eur_kwh',0.04)))
    costs=imp_kwh*price; revenue=exp_kwh*export_price
    battery_soc_now=(snap.get('values',{}).get('battery_soc') or {}).get('value')
    if battery_soc_now is None: battery_soc_now=soc_last
    # Deduplicate adjacent over-limit samples into events; don't count each sample as a separate peak.
    peak_events=[]; event_start=None; event_last=None; event_max=0.0
    target=max(0.0,float(st.get('peak_alert_w',5000)))
    for ts, values in today_rows:
        raw=values.get('grid_power')
        over=grid_import_multiplier is not None and isinstance(raw,(int,float)) and grid_import_multiplier*float(raw)>target
        if over:
            if event_start is None or event_last is None or ts-event_last>max(60,int(os.getenv('SAMPLE_INTERVAL_SECONDS','15'))*4):
                if event_start is not None: peak_events.append({'start':event_start,'end':event_last,'max_w':round(event_max),'duration_min':round(max(0,event_last-event_start)/60,1)})
                event_start=ts; event_max=grid_import_multiplier*float(raw)
            else: event_max=max(event_max,grid_import_multiplier*float(raw))
            event_last=ts
        elif event_start is not None:
            peak_events.append({'start':event_start,'end':event_last,'max_w':round(event_max),'duration_min':round(max(0,event_last-event_start)/60,1)})
            event_start=event_last=None; event_max=0.0
    if event_start is not None: peak_events.append({'start':event_start,'end':event_last,'max_w':round(event_max),'duration_min':round(max(0,event_last-event_start)/60,1)})
    # SoC delta converted to stored-energy change; compare with integrated AC battery energy only as a rough diagnostic.
    capacity=max(0.0,float(st.get('battery_capacity_kwh',80)))
    soc_delta_kwh=((soc_last-soc_first)*capacity/100.0) if soc_first is not None and soc_last is not None else None
    battery_net_kwh=charge_kwh-discharge_kwh
    soc_energy_gap=(soc_delta_kwh-battery_net_kwh) if soc_delta_kwh is not None else None
    if len(peak_events): alerts.append(f'{len(peak_events)} Netzspitzen-Ereignis(se) über {target:.0f} W erkannt; längstes Ereignis {max(x["duration_min"] for x in peak_events):.1f} min.')
    # Daily rollup over the last seven recorded dates, with the same gap-safe integration.
    grouped={}
    for row in rows:
        try:
            ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            values=row.get('values',{})
            grouped.setdefault(datetime.fromtimestamp(ts).astimezone().date().isoformat(),[]).append((ts,values))
        except Exception:
            continue
    history_days=[]
    for day_key, pts in sorted(grouped.items(),reverse=True)[:7]:
        pts.sort(key=lambda z:z[0]); totals={'pv':0.0,'load':0.0,'import':0.0,'export':0.0,'charge':0.0,'discharge':0.0}
        for (t0,a),(t1,b) in zip(pts,pts[1:]):
            dt=t1-t0
            if dt<=0 or dt>120: continue
            for key in ('pv','load'):
                k='pv_power' if key=='pv' else 'load_power'; x,y=a.get(k),b.get(k)
                if isinstance(x,(int,float)) and isinstance(y,(int,float)): totals[key]+=max(0,(float(x)+float(y))/2)*dt/3600000
            for k,out_key,in_key,multiplier in [('grid_power','import','export',grid_import_multiplier),('battery_power','discharge','charge',battery_discharge_multiplier)]:
                x,y=a.get(k),b.get(k)
                if multiplier is not None and isinstance(x,(int,float)) and isinstance(y,(int,float)):
                    out=lambda z:max(0,multiplier*float(z))
                    inn=lambda z:max(0,-multiplier*float(z))
                    totals[out_key]+=(out(x)+out(y))*dt/7200000; totals[in_key]+=(inn(x)+inn(y))*dt/7200000
        history_days.append({'day':day_key,**{k:round(v,2) for k,v in totals.items()}})
    if soc_energy_gap is not None and abs(soc_energy_gap)>max(5.0,capacity*0.15): alerts.append('SoC-Änderung und integrierte Batterieleistung weichen deutlich ab; AC/DC-Messpunkt und SoC-Sensor prüfen.')
    # Existing consumer plan is displayed as advisory; no entity writes exist in this route.
    consumers=c.get('consumers',[])
    return render_template('analysis.html',cfg=c,day=today,energy={'pv':pv_kwh,'load':load_kwh,'import':imp_kwh,'export':exp_kwh,'charge':charge_kwh,'discharge':discharge_kwh,'residual':residual,'residual_pct':residual_pct},peak=peak,peak_count=len(peaks),peak_events=peak_events,soc_start=soc_first,soc_end=soc_last,soc_now=battery_soc_now,soc_delta_kwh=soc_delta_kwh,soc_energy_gap=soc_energy_gap,history_days=history_days,forecast_kwh=forecast_kwh,forecast_age=(snap.get('values',{}).get('pv_forecast') or {}).get('updated'),forecast_label=forecast_label,pv_remaining_kwh=pv_remaining_kwh,pv_projected_total_kwh=pv_projected_total_kwh,costs=costs,revenue=revenue,price=price,export_price=export_price,alerts=alerts,consumers=consumers,samples=len(today_rows),accepted=accepted,rejected=rejected,active_control_enabled=False)

@app.route('/api/analysis')
def api_analysis():
    return jsonify({'active_control_enabled':False,'commands_sent':False,'note':'Read-only diagnostics; estimates depend on sensor mapping, units and data coverage.','page':'/analysis'})

@app.route('/health')
def health():return jsonify({'status':'ok','mode':'observe','active_control_enabled':False,'timestamp':datetime.now(timezone.utc).isoformat()})
if __name__=='__main__':
 threading.Thread(target=sampler,daemon=True).start();app.run(host='0.0.0.0',port=int(os.getenv('PORT','8099')))
