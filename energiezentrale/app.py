import os,json,time,threading,statistics,math
from datetime import datetime,timezone,timedelta
from pathlib import Path
from flask import Flask,render_template,request,redirect,url_for,flash,jsonify
import requests
app=Flask(__name__); app.secret_key='local-energy-app'
DATA=Path('/data'); DATA.mkdir(exist_ok=True); CFG=DATA/'config.json'; HIST=DATA/'history.jsonl'; LEARN_STATE=DATA/'learning_state.json'

def learning_start_timestamp():
    """Persist the start of the new learning period; old history is excluded."""
    try:
        state=json.loads(LEARN_STATE.read_text()); value=float(state['started_at'])
        if value > 0: return value
    except Exception: pass
    value=time.time()
    try:
        tmp=LEARN_STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps({'started_at':value,'started_at_iso':datetime.fromtimestamp(value,timezone.utc).isoformat(),'policy':'new_samples_only'}))
        tmp.replace(LEARN_STATE)
    except Exception: pass
    return value

def learning_rows(limit=100000):
    """Return only samples recorded since this learning feature was first activated."""
    started=learning_start_timestamp()
    if not HIST.exists(): return []
    rows=[]
    try:
        for line in HIST.read_text().splitlines()[-limit:]:
            if not line.strip(): continue
            try: row=json.loads(line); ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            except Exception: continue
            if ts >= started: rows.append(row)
    except Exception: return []
    return rows

BRAIN_PATTERN_MEMORY = DATA/'brain_pattern_memory.json'
BRAIN_PATTERN_LOCK = threading.Lock()

def update_brain_pattern_memory(events):
    """Persist coarse recurring load-step signatures; process each event once."""
    empty = {'stored_signatures':0,'new_events':0,'top_patterns':[],
             'status':'Noch keine Muster gespeichert','last_event_ts':None}
    with BRAIN_PATTERN_LOCK:
        state = {'schema_version':1,'last_event_ts':0.0,'patterns':{}}
        if BRAIN_PATTERN_MEMORY.exists():
            try:
                loaded = json.loads(BRAIN_PATTERN_MEMORY.read_text())
                if not isinstance(loaded,dict) or not isinstance(loaded.get('patterns',{}),dict):
                    raise ValueError('Ungültiges Muster-Gedächtnisformat')
                state.update(loaded)
            except Exception as exc:
                empty['status'] = 'Musterdatei konnte nicht gelesen werden: ' + str(exc)[:120]
                return empty
        try:
            cursor = float(state.get('last_event_ts') or 0.0)
        except (TypeError,ValueError):
            cursor = 0.0
        patterns = state.setdefault('patterns',{})
        if not isinstance(patterns,dict):
            empty['status'] = 'Musterdatei enthält ungültige Daten'
            return empty
        new_events = 0
        newest = cursor
        for event in sorted(events, key=lambda e: float(e.get('ts',0) or 0)):
            try:
                ts = float(event.get('ts'))
                delta = float(event.get('delta'))
                if not math.isfinite(ts) or not math.isfinite(delta) or ts <= cursor:
                    continue
                magnitude = abs(delta)
                if magnitude < 900:
                    continue
                hour = datetime.fromtimestamp(ts).hour
                bucket_kw = max(1, int(round(magnitude/1000.0)))
                direction = 'Anstieg' if delta > 0 else 'Abfall'
                key = f'{direction}|{bucket_kw}|{hour:02d}'
                item = patterns.get(key)
                if not isinstance(item,dict):
                    item = {'direction':direction,'power_bucket_kw':bucket_kw,'hour':hour,
                            'count':0,'first_seen':ts,'last_seen':ts}
                    patterns[key] = item
                item['count'] = int(item.get('count',0)) + 1
                item['first_seen'] = min(float(item.get('first_seen',ts)),ts)
                item['last_seen'] = max(float(item.get('last_seen',ts)),ts)
                newest = max(newest,ts)
                new_events += 1
            except (TypeError,ValueError,OverflowError,OSError):
                continue
        # Bound storage while retaining the most frequently observed signatures.
        if len(patterns) > 200:
            keep = sorted(patterns.items(),key=lambda kv:int((kv[1] or {}).get('count',0)),reverse=True)[:200]
            patterns = dict(keep)
            state['patterns'] = patterns
        state['schema_version'] = 1
        state['last_event_ts'] = newest
        try:
            tmp = BRAIN_PATTERN_MEMORY.with_suffix('.tmp')
            tmp.write_text(json.dumps(state,ensure_ascii=False,separators=(',',':')))
            tmp.replace(BRAIN_PATTERN_MEMORY)
        except Exception as exc:
            empty['status'] = 'Muster konnten nicht dauerhaft gespeichert werden: ' + str(exc)[:120]
            return empty
        top = sorted(patterns.values(),key=lambda x:int(x.get('count',0)),reverse=True)[:8]
        return {'stored_signatures':len(patterns),'new_events':new_events,
                'top_patterns':top,'status':'Dauerhaft gespeichert' if patterns else 'Noch keine Muster gespeichert',
                'last_event_ts':newest or None}


DEFAULT={'plant_name':'Meine Energiezentrale','sensors':{
'pv_power':{'label':'PV-Leistung','entity_id':'sensor.sofar_speicher_pv_power_total','unit':'W'},
'load_power':{'label':'Hausverbrauch','entity_id':'sensor.sofar_speicher_active_power_load_sys','unit':'W'},
'grid_power':{'label':'Netzbezug / Einspeisung','entity_id':'sensor.sofar_speicher_active_power_pcc_total','unit':'W'},
'battery_power':{'label':'Batterieleistung','entity_id':'sensor.sofar_speicher_battery_power_total','unit':'W'},
'battery_soc':{'label':'Batterieladezustand (SoC)','entity_id':'sensor.sofar_speicher_battery_soc','unit':'%'},
'inverter_output':{'label':'Wechselrichter-Ausgangsleistung','entity_id':'sensor.sofar_speicher_active_power_output_total','unit':'W'},
'pv_forecast':{'label':'PV-Prognose','entity_id':'sensor.solcast_pv_forecast_prognose_heute','unit':'Wh'}},
'consumers':[{'id':'heater','name':'Elektroheizung','type':'heater','enabled':True,'nominal_power_w':30000,'stages_w':[7500,15000,22500,30000],'priority':1,'temperature_sensor_entity':'','target_temperature_c':55.0},{'id':'compressor','name':'Kompressor','type':'motor','enabled':True,'nominal_power_w':11000,'stages_w':[],'priority':2,'pressure_sensor_entity':'','pressure_min_bar':4.5,'pressure_max_bar':7.0,'receiver_volume_l':500,'compressor_on_bar':6.0,'compressor_off_bar':8.0,'leak_monitor_enabled':True,'compressor_state_entity':'','temperature_sensor_entity':'','target_temperature_c':20.0}],
'control_entities':{'mode':'select.sofar_speicher_inverter_energy_storage_mode','grid_setpoint':'number.sofar_speicher_inverter_passive_desired_grid_power','charge_power':'number.sofar_speicher_inverter_passive_maximum_battery_power','discharge_power':'number.sofar_speicher_inverter_passive_minimum_battery_power','apply_button':'button.sofar_speicher_inverter_passive_update_battery_charge_discharge'},'settings':{'grid_import_limit_w':5000,'battery_reserve_percent':25,'inverter_count':2,'control_enabled':False,'mode':'observe','grid_setpoint_sign':'unverified','grid_import_sign':'unverified','battery_power_sign':'negative','morning_start_hour':5,'morning_end_hour':9,'learning_days':14,'morning_min_samples_per_day':60,'battery_capacity_kwh':80,'battery_discharge_power_kw':30,'silage_slots':['06:30','12:00','18:00'],'silage_flex_minutes':45,'silage_duration_minutes':15,'feeding_slots':['06:45','12:00','18:15'],'feeding_flex_minutes':10,'feeding_duration_minutes':8,'feeding_power_w':0,'consumer_surplus_margin_w':1000,'import_price_eur_kwh':0.30,'export_price_eur_kwh':0.04,'tariff_effective_month':'','tariff_history':[],'battery_roundtrip_efficiency':0.90,'peak_alert_w':5000,'balance_alert_pct':15,'pv_forecast_mode':'daily_total'}}
def config():
 if not CFG.exists(): CFG.write_text(json.dumps(DEFAULT,ensure_ascii=False,indent=2))
 try:
  c=json.loads(CFG.read_text()); c.setdefault('plant_name',DEFAULT['plant_name']); c.setdefault('sensors',{})
  for k,v in DEFAULT['sensors'].items(): c['sensors'].setdefault(k,v)
  c.setdefault('consumers',DEFAULT['consumers']); c.setdefault('settings',{}); c.setdefault('control_entities',DEFAULT['control_entities'])
  c['control_entities'].setdefault('passive_timeout','select.sofar_speicher_inverter_passive_timeout')
  c['control_entities'].setdefault('passive_timeout_action','select.sofar_speicher_inverter_passive_timeout_action')
  c['control_entities'].setdefault('timeout_apply_button','button.sofar_speicher_inverter_passive_update_timeout')
  c['settings'].setdefault('control_margin_w',300); c['settings'].setdefault('battery_charge_power_kw',30)
  for k,v in DEFAULT['settings'].items(): c['settings'].setdefault(k,v)
  # Migrate the known mistaken 30 kW grid-import target to the intended soft target of 5 kW.
  # This affects only the advisory setting; no device commands are sent.
  if c['settings'].get('grid_import_limit_w') == 30000:
   c['settings']['grid_import_limit_w'] = 5000
   try: save(c)
   except Exception: pass
  for k,v in DEFAULT['control_entities'].items(): c['control_entities'].setdefault(k,v)
  for consumer in c.get('consumers',[]):
   consumer.setdefault('management_mode','advisory')
   consumer.setdefault('external_reserve_power_w',consumer.get('nominal_power_w',0))
  return c
 except Exception: return json.loads(json.dumps(DEFAULT))
def save(c): CFG.write_text(json.dumps(c,ensure_ascii=False,indent=2))
def ha(path):
 token=os.getenv('SUPERVISOR_TOKEN')
 if not token:return None,'Supervisor-Token fehlt – bitte als Home-Assistant-Add-on starten.'
 try:
  r=requests.get('http://supervisor/core/api/'+path.lstrip('/'),headers={'Authorization':'Bearer '+token},timeout=8);r.raise_for_status();return r.json(),None
 except Exception as e:return None,str(e)
def ha_service(domain,service,data):
 token=os.getenv('SUPERVISOR_TOKEN')
 if not token:return False,'Supervisor-Token fehlt.'
 try:
  r=requests.post(f'http://supervisor/core/api/services/{domain}/{service}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},json=data,timeout=8);r.raise_for_status();return True,None
 except Exception as e:return False,str(e)

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
def _value_from_state(state):
 if not isinstance(state,dict):return None
 try:v=float(state.get('state'))
 except (ValueError,TypeError):v=None
 return {'value':v,'state':state.get('state'),'unit':state.get('attributes',{}).get('unit_of_measurement',''),'updated':state.get('last_updated')}
def snapshot():
 c=config()
 all_states,err=ha('states')
 by_id={s.get('entity_id'):s for s in all_states if isinstance(s,dict)} if isinstance(all_states,list) else {}
 values={k:_value_from_state(by_id.get(v.get('entity_id',''))) for k,v in c['sensors'].items()}
 consumer_values={}
 for consumer in c.get('consumers',[]):
  cid=str(consumer.get('id',''))
  if not cid: continue
  cv={}
  for key in ('pressure_sensor_entity','temperature_sensor_entity','compressor_state_entity'):
   entity=consumer.get(key,'')
   if entity:
    cv[key]=_value_from_state(by_id.get(entity))
  if cv: consumer_values[cid]=cv
 return {'timestamp':datetime.now(timezone.utc).isoformat(),'values':values,'consumer_values':consumer_values,'ha_error':err}
def sampler():
 while True:
  try:
   s=snapshot(); row={'timestamp':s['timestamp'],'values':{k:(v or {}).get('value') for k,v in s['values'].items()},
             'consumer_values':{cid:{key:(val or {}).get('value') for key,val in vals.items()} for cid,vals in s.get('consumer_values',{}).items()}}
   with HIST.open('a') as f:f.write(json.dumps(row)+'\n')
   if HIST.stat().st_size>15000000:
    lines=HIST.read_text().splitlines()[-10000:]; HIST.write_text('\n'.join(lines)+'\n')
  except Exception:pass
  time.sleep(max(5,int(os.getenv('SAMPLE_INTERVAL_SECONDS','10'))))


def learn_morning_energy_need(daily_excess_kwh, daily_peak_w):
    """Walk-forward shadow forecast: next morning resembles recent mornings.
    Uses only complete days and is accepted only if it beats yesterday-as-baseline.
    """
    days=sorted(set(daily_excess_kwh)&set(daily_peak_w))
    pairs=[]
    for day in days:
        previous=(datetime.fromisoformat(day).date()-timedelta(days=1)).isoformat()
        if previous in daily_excess_kwh and previous in daily_peak_w:
            pairs.append(([1.0,float(daily_excess_kwh[previous]),float(daily_peak_w[previous])/10000.0],
                          float(daily_excess_kwh[day])))
    if len(pairs)<12:
        return {'status':'Lernt noch','trained':False,'days':len(days),'pairs':len(pairs),
                'prediction_kwh':None,'mae_kwh':None,'baseline_mae_kwh':None,'beats_baseline':False}
    holdout=max(3,int(len(pairs)*0.2)); train=pairs[:-holdout]; check=pairs[-holdout:]
    # Ridge regression solved with small Gauss-Jordan elimination; no ML package required.
    n=3; matrix=[[0.0]*(n+1) for _ in range(n)]
    for x,y in train:
        for i in range(n):
            for j in range(n): matrix[i][j]+=x[i]*x[j]
            matrix[i][n]+=x[i]*y
    matrix[1][1]+=0.15; matrix[2][2]+=0.15
    try:
        for col in range(n):
            pivot=max(range(col,n),key=lambda r:abs(matrix[r][col]))
            if abs(matrix[pivot][col])<1e-9: raise ValueError('singular')
            matrix[col],matrix[pivot]=matrix[pivot],matrix[col]
            scale=matrix[col][col]; matrix[col]=[v/scale for v in matrix[col]]
            for row in range(n):
                if row==col: continue
                factor=matrix[row][col]
                matrix[row]=[matrix[row][j]-factor*matrix[col][j] for j in range(n+1)]
        weights=[matrix[i][n] for i in range(n)]
    except (ValueError,ZeroDivisionError):
        return {'status':'Zu wenig unabhängige Daten','trained':False,'days':len(days),'pairs':len(pairs),
                'prediction_kwh':None,'mae_kwh':None,'baseline_mae_kwh':None,'beats_baseline':False}
    predict=lambda x:max(0.0,sum(a*b for a,b in zip(weights,x)))
    model_mae=sum(abs(predict(x)-y) for x,y in check)/len(check)
    baseline_mae=sum(abs(x[1]-y) for x,y in check)/len(check)
    latest_day=days[-1]
    latest_x=[1.0,float(daily_excess_kwh[latest_day]),float(daily_peak_w[latest_day])/10000.0]
    beats=model_mae+0.03<baseline_mae
    return {'status':'Aktiv · besser als Vortag' if beats else 'Schattenmodell · derzeit nicht besser',
            'trained':True,'days':len(days),'pairs':len(pairs),
            'prediction_kwh':round(predict(latest_x),2) if beats else None,
            'mae_kwh':round(model_mae,2),'baseline_mae_kwh':round(baseline_mae,2),
            'beats_baseline':beats,'holdout_days':len(check)}

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
    sample_s = max(5, int(os.getenv('SAMPLE_INTERVAL_SECONDS','10')))
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
    # Bring recurring aggregate house-load patterns into the morning-reserve
    # estimate. This is deliberately conservative: it is an estimate of the
    # learned recurring load in the configured morning window, not a claim that
    # the battery must supply all of it (PV may cover part of it).
    learned = learn_load_patterns(rows, st.get('learning_days', 14))
    morning_patterns = []
    for pattern in learned.get('patterns', []):
        try:
            hh, mm = (int(part) for part in pattern['time'].split(':'))
            if morning_start <= hh < morning_end:
                morning_patterns.append(pattern)
        except (ValueError, KeyError, TypeError):
            continue
    learned_morning_load_kwh = sum(float(p.get('median_w', 0)) * 0.25 / 1000.0 for p in morning_patterns)
    learned_days_min = min((int(p.get('days_seen', 0)) for p in morning_patterns), default=0)
    learned_morning_confidence = ('hoch' if morning_patterns and all(p.get('confidence') == 'hoch' for p in morning_patterns)
                                  else 'mittel' if morning_patterns and learned_days_min >= 5 else 'vorläufig' if morning_patterns else 'keine')
    # The learned profile is a cross-check, not blindly added to measured grid
    # excess (which would double-count energy). Use at most half of the learned
    # morning load as a provisional reserve signal, and only with >=3 valid
    # morning grid-history days. Existing measured excess remains authoritative.
    learned_reserve_signal_kwh = learned_morning_load_kwh * 0.5 if enough and morning_patterns else 0.0
    strategy = learn_morning_energy_need(daily_excess_kwh, daily_peak_w)
    strategy_need_kwh = strategy.get('prediction_kwh') if strategy.get('beats_baseline') else None
    reserve_addition_kwh = max(excess_median or 0.0, learned_reserve_signal_kwh,
                               strategy_need_kwh or 0.0) if enough else None
    required_kwh = min(capacity_kwh, max(reserve_kwh or 0.0, (reserve_kwh or 0.0) + reserve_addition_kwh)) if enough and capacity_kwh else None
    target_soc = min(100.0, required_kwh/capacity_kwh*100.0) if required_kwh is not None and capacity_kwh else None
    charge_efficiency = max(0.5, min(1.0, float(st.get('battery_roundtrip_efficiency', 0.90) or 0.90)))
    estimated_grid_charge_kwh = (max(0.0, required_kwh-current_kwh)/charge_efficiency
                                 if required_kwh is not None and current_kwh is not None else None)
    advice = []
    if not enough:
        advice.append(f'Für belastbare Batterieplanung werden mindestens drei Morgen mit genügend Messpunkten und mindestens {int(min_coverage_seconds/60)} Minuten zeitlicher Abdeckung benötigt; gültig: {len(valid_days)}, verworfen: {len(set(samples_by_day)-valid_days)}.')
    else:
        advice.append(f'Median der morgendlichen Netzbezugs-Spitzen: {peak_median:.0f} W.')
        advice.append(f'Geschätzte tägliche Energie oberhalb des weichen {target_w:.0f}-W-Ziels: {excess_median:.2f} kWh.')
        if strategy.get('beats_baseline'):
            advice.append(f'Das lernende Schattenmodell erwartet für den nächsten Morgen etwa {strategy_need_kwh:.2f} kWh oberhalb des Netzbezugsziels. Die Schätzung wird nur übernommen, wenn sie im zeitlichen Rücktest besser war als „wie gestern“; niedrigere Werte senken die Reserve nicht unter den historischen Median.')
        else:
            advice.append(f'Schattenmodell: {strategy.get("status")} (Prüffehler {strategy.get("mae_kwh", "–")} kWh gegenüber {strategy.get("baseline_mae_kwh", "–")} kWh beim Vortagsvergleich). Die bisherige Median-Schätzung bleibt maßgeblich.')
        if morning_patterns:
            advice.append(f'Gelernte wiederkehrende Morgenlast: ca. {learned_morning_load_kwh:.2f} kWh in {len(morning_patterns)} erkannten 15-Minuten-Zeitfenstern; Vertrauensstufe: {learned_morning_confidence}.')
            advice.append('Die gelernte Last beeinflusst die Reserve nur vorsichtig (höchstens 50 % als Zusatzsignal), da PV-Erzeugung und Netz-/Batterieanteile nicht für jede Last sicher getrennt werden können.')
        else:
            advice.append('Noch kein ausreichend wiederkehrendes Hausverbrauchsmuster im eingestellten Morgenfenster erkannt; Reserve basiert vorerst auf den gemessenen Netzspitzen.')
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
        'learned_morning_pattern_slots':len(morning_patterns),
        'learned_morning_load_estimate_kwh':round(learned_morning_load_kwh, 3),
        'learned_morning_confidence':learned_morning_confidence,
        'learned_reserve_signal_kwh':round(learned_reserve_signal_kwh, 3),
        'learned_strategy':strategy,
        'recommended_morning_reserve_kwh':required_kwh,'recommended_morning_soc_percent':target_soc,
        'estimated_grid_charge_kwh_to_target':round(estimated_grid_charge_kwh,2) if estimated_grid_charge_kwh is not None else None,
        'pv_forecast_kwh':pv_kwh,'advice':advice}

@app.route('/')
def index():
 c=config(); s=snapshot(); return render_template('index.html',cfg=c,snap=s,ha_error=s.get('ha_error'),control_runtime=dict(CONTROL_RUNTIME))
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
@app.route('/api/dashboard-history')
def api_dashboard_history():
    """Small recent sample window for the live dashboard chart."""
    rows=[]
    if HIST.exists():
        try:
            for line in HIST.read_text().splitlines()[-360:]:
                if not line.strip(): continue
                row=json.loads(line)
                rows.append({'timestamp':row.get('timestamp'),'values':row.get('values',{})})
        except Exception:
            rows=[]
    return jsonify({'samples':rows,'sample_interval_seconds':max(5,int(os.getenv('SAMPLE_INTERVAL_SECONDS','10')))})
@app.route('/config',methods=['GET','POST'])
def config_page():
 c=config(); entities,err=states()
 if request.method=='POST':
  if c.get('settings',{}).get('control_enabled') or ('CONTROL_STATE_FILE' in globals() and CONTROL_STATE_FILE.exists()):
   changed=[k for k,v in c.get('control_entities',{}).items() if request.form.get('control_'+k,'').strip() and request.form.get('control_'+k,'').strip()!=v]
   changed += ['sensor_'+k for k,v in c.get('sensors',{}).items() if request.form.get('sensor_'+k,'').strip() and request.form.get('sensor_'+k,'').strip()!=v.get('entity_id','')]
   if request.form.get('grid_import_sign',c.get('settings',{}).get('grid_import_sign'))!=c.get('settings',{}).get('grid_import_sign'):
    changed.append('grid_import_sign')
   if changed:
    flash('Steuer-Entitäten erst ändern, nachdem die Regelung ausgeschaltet und die Rückschaltung bestätigt wurde.','error')
    return render_template('config.html',cfg=c,states=entities,ha_error=err)
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
   c['settings']['inverter_count']=max(1,min(2,int(request.form.get('inverter_count','2'))))
   c['settings']['battery_capacity_kwh']=max(1,min(500,int(request.form.get('battery_capacity_kwh','80'))))
   c['settings']['battery_discharge_power_kw']=max(1,min(100,int(request.form.get('battery_discharge_power_kw','30'))))
   c['settings']['control_margin_w']=max(100,min(3000,int(request.form.get('control_margin_w','300'))))
   c['settings']['battery_charge_power_kw']=max(1,min(100,int(request.form.get('battery_charge_power_kw','30'))))
   c['settings']['control_enabled']=(request.form.get('control_enabled')=='on')
   c['settings']['mode']='passive' if c['settings']['control_enabled'] else 'observe'
   c['settings']['morning_start_hour']=max(0,min(23,int(request.form.get('morning_start_hour','5'))))
   c['settings']['morning_end_hour']=max(1,min(24,int(request.form.get('morning_end_hour','9'))))
   c['settings']['grid_import_sign']=request.form.get('grid_import_sign','unverified') if request.form.get('grid_import_sign','unverified') in ('positive','negative','unverified') else 'unverified'
   c['settings']['battery_power_sign']=request.form.get('battery_power_sign','negative') if request.form.get('battery_power_sign','negative') in ('positive','negative') else 'negative'
   import_price=max(0,min(5,float(request.form.get('import_price_eur_kwh','0.30'))))
   export_price=max(0,min(5,float(request.form.get('export_price_eur_kwh','0.04'))))
   effective_month=request.form.get('tariff_effective_month','').strip()
   if effective_month and (len(effective_month)!=7 or effective_month[4]!='-' or not effective_month[:4].isdigit() or not effective_month[5:7].isdigit() or not 1<=int(effective_month[5:7])<=12):
    raise ValueError('Gültigkeitsmonat muss im Format JJJJ-MM angegeben werden.')
   c['settings']['import_price_eur_kwh']=import_price
   c['settings']['export_price_eur_kwh']=export_price
   c['settings']['tariff_effective_month']=effective_month
   c['settings']['battery_roundtrip_efficiency']=max(0.50,min(1.0,(float(request.form.get('battery_roundtrip_efficiency','90'))/100.0)))
   if effective_month:
    history=c['settings'].setdefault('tariff_history',[])
    entry={'month':effective_month,'import_price_eur_kwh':import_price,'export_price_eur_kwh':export_price}
    history[:]=[x for x in history if x.get('month')!=effective_month]
    history.append(entry); history.sort(key=lambda x:x.get('month',''))
   c['settings']['peak_alert_w']=max(500,int(request.form.get('peak_alert_w','5000')))
   c['settings']['balance_alert_pct']=max(1,min(100,float(request.form.get('balance_alert_pct','15'))))
   c['settings']['pv_forecast_mode']=request.form.get('pv_forecast_mode','daily_total') if request.form.get('pv_forecast_mode','daily_total') in ('daily_total','remaining') else 'daily_total'
  except ValueError:flash('Grenzwerte müssen Zahlen sein.','error');return render_template('config.html',cfg=c,states=entities,ha_error=err)
  save(c);flash('Konfiguration gespeichert. Die Steuerung wird nur bei bestandener Sicherheitsprüfung freigegeben.' if c['settings']['control_enabled'] else 'Konfiguration gespeichert. Steuerung bleibt ausgeschaltet.','success');entities,err=states();return render_template('config.html',cfg=c,states=entities,ha_error=err)
 return render_template('config.html',cfg=c,states=entities,ha_error=err)

CONTROL_STATE_FILE=DATA/'control_state.json'
CONTROL_RUNTIME={'status':'Steuerung aus','ready':False,'active':False,'last_update':None,'reasons':[],'recommendation':None}
CONTROL_LOCK=threading.Lock()

def control_preflight(c=None):
    c=c or config(); st=c.get('settings',{}); ce=c.get('control_entities',{})
    reasons=[]; data,err=ha('states')
    if err or not isinstance(data,list):
        return {'ready':False,'reasons':['Home Assistant nicht erreichbar: '+str(err or 'keine Zustandsliste')],'entities':{},'sensors':{}}
    entities={item.get('entity_id'):item for item in data if isinstance(item,dict)}
    required=('mode','grid_setpoint','charge_power','discharge_power','apply_button','passive_timeout','passive_timeout_action','timeout_apply_button')
    selected={}
    for key in required:
        eid=ce.get(key,''); item=entities.get(eid)
        selected[key]=item
        if not item or item.get('state') in ('unknown','unavailable','None'):
            reasons.append(f'Steuerungs-Entität {key} fehlt oder ist nicht verfügbar ({eid or "nicht konfiguriert"}).')
    if st.get('grid_import_sign') not in ('positive','negative'):
        reasons.append('Vorzeichen des Netzleistungssensors ist nicht bestätigt.')
    if int(st.get('inverter_count',1) or 1) not in (1,2):
        reasons.append('Aktive Regelung unterstützt derzeit höchstens zwei parallel arbeitende Wechselrichter.')
    sensor_values={}
    for key in ('pv_power','load_power','grid_power','battery_soc'):
        eid=c.get('sensors',{}).get(key,{}).get('entity_id',''); item=entities.get(eid)
        if not item:
            reasons.append(f'Sensor {key} fehlt ({eid or "nicht konfiguriert"}).'); continue
        try:
            value=float(item.get('state'))
            if not math.isfinite(value): raise ValueError()
            if (key=='battery_soc' and not 0<=value<=100) or (key in ('pv_power','load_power') and not 0<=value<=250000) or (key=='grid_power' and abs(value)>250000): raise ValueError('Wert außerhalb des zulässigen Bereichs')
            updated=datetime.fromisoformat(item.get('last_updated','').replace('Z','+00:00')).timestamp()
            if time.time()-updated>180: raise ValueError('veraltet')
            unit=str((item.get('attributes') or {}).get('unit_of_measurement','')).lower()
            if key=='battery_soc' and unit not in ('%','percent'): raise ValueError('Einheit muss % sein')
            if key!='battery_soc' and unit not in ('w','watt'): raise ValueError('Einheit muss W sein')
            sensor_values[key]=value
        except (TypeError,ValueError,OverflowError):
            reasons.append(f'Sensor {key} ist ungültig, älter als 180 Sekunden oder hat keine erwartete Einheit.')
    mode=selected.get('mode') or {}; mode_options=(mode.get('attributes') or {}).get('options',[])
    if not any('passive' in str(x).casefold() for x in mode_options): reasons.append('Betriebsmodus-Entität bietet keine Auswahl „Passive Mode“.')
    timeout=selected.get('passive_timeout') or {}; timeout_options=(timeout.get('attributes') or {}).get('options',[])
    if not any('5 minute' in str(x).casefold() for x in timeout_options): reasons.append('Passivmodus-Watchdog bietet keine 5-Minuten-Einstellung.')
    action=selected.get('passive_timeout_action') or {}; action_options=(action.get('attributes') or {}).get('options',[])
    if not any('previous' in str(x).casefold() for x in action_options): reasons.append('Watchdog bietet keine Aktion „Return to Previous Mode“.')
    watchdog_armed=(str(timeout.get('state','')).casefold()=='5 minutes' and 'previous' in str(action.get('state','')).casefold())
    number_specs=(('grid_setpoint',0,0),('charge_power',0,1),('discharge_power',-1,0))
    for key,need_min,need_max in number_specs:
        item=selected.get(key) or {}; attrs=item.get('attributes') or {}
        try:
            lo=float(attrs.get('min',attrs.get('min_value',attrs.get('native_min_value'))))
            hi=float(attrs.get('max',attrs.get('max_value',attrs.get('native_max_value'))))
            if lo>need_min or hi<need_max: reasons.append(f'Sollwertbereich von {key} unterstützt die benötigten Sicherheitswerte nicht.')
        except (TypeError,ValueError): reasons.append(f'Sollwertgrenzen von {key} sind nicht lesbar.')
    return {'ready':not reasons,'reasons':reasons,'entities':selected,'sensors':sensor_values,'ha_states':entities,'watchdog_armed':watchdog_armed}

def _control_call(domain,service,eid,extra=None):
    payload={'entity_id':eid}; payload.update(extra or {})
    ok,error=ha_service(domain,service,payload)
    if not ok: raise RuntimeError(f'{domain}.{service} für {eid}: {error}')

def _arm_passive_watchdog(c,pre):
    ce=c['control_entities']; states=pre['ha_states']
    timeout=states.get(ce['passive_timeout'],{}); action=states.get(ce['passive_timeout_action'],{})
    if str(timeout.get('state','')).casefold()!='5 minutes':
        _control_call('select','select_option',ce['passive_timeout'],{'option':'5 Minutes'})
    if 'previous' not in str(action.get('state','')).casefold():
        option=next((str(x) for x in (action.get('attributes') or {}).get('options',[]) if 'previous' in str(x).casefold()),None)
        if not option: raise RuntimeError('Watchdog-Aktion „Return to Previous Mode“ fehlt.')
        _control_call('select','select_option',ce['passive_timeout_action'],{'option':option})
    _control_call('button','press',ce['timeout_apply_button'])
    time.sleep(2)
    check=control_preflight(c)
    confirmed_timeout=check['ha_states'].get(ce['passive_timeout'],{}).get('state','')
    confirmed_action=check['ha_states'].get(ce['passive_timeout_action'],{}).get('state','')
    if str(confirmed_timeout).casefold()!='5 minutes' or 'previous' not in str(confirmed_action).casefold():
        raise RuntimeError('Der 5-Minuten-Watchdog mit Rückkehr zum vorherigen Modus wurde vom Wechselrichter nicht bestätigt.')
    if not check['ready']:
        # Only the selected timeout state may be in flight; every other failure blocks arming.
        bad=[x for x in check['reasons'] if 'SoC-Reserve' not in x]
        if bad: raise RuntimeError('; '.join(bad))

def _write_passive_targets(c,pre):
    st=c['settings']; ce=c['control_entities']; sensors=pre['sensors']; states=pre['ha_states']
    raw_grid=sensors['grid_power']; sign=st['grid_import_sign']
    export_w=max(0.0,raw_grid) if sign=='negative' else max(0.0,-raw_grid)
    margin=float(st.get('control_margin_w',300))
    number_attrs=(states.get(ce['charge_power'],{}).get('attributes') or {})
    charge_hw_max=float(number_attrs.get('max',number_attrs.get('max_value',number_attrs.get('native_max_value',0))))
    inverter_count=max(1,int(st.get('inverter_count',1) or 1))
    # The configured master/passive setpoint is applied by the parallel
    # master/slave pair to each inverter, so convert plant totals to per-unit W.
    charge_cap=min(float(st.get('battery_charge_power_kw',30))*1000/inverter_count,
                    charge_hw_max,max(0.0,export_w-margin)/inverter_count)
    discharge_attrs=(states.get(ce['discharge_power'],{}).get('attributes') or {})
    discharge_hw_min=abs(float(discharge_attrs.get('min',discharge_attrs.get('min_value',discharge_attrs.get('native_min_value',0)))))
    reserve=float(st.get('battery_reserve_percent',25)); soc=sensors['battery_soc']
    discharge_cap=min(float(st.get('battery_discharge_power_kw',30))*1000/inverter_count,discharge_hw_min) if soc>reserve else 0
    # Passive mode uses positive battery watts for charging and negative for discharge.
    _control_call('number','set_value',ce['grid_setpoint'],{'value':0})
    _control_call('number','set_value',ce['charge_power'],{'value':int(charge_cap//100*100)})
    _control_call('number','set_value',ce['discharge_power'],{'value':-int(discharge_cap//100*100)})
    _control_call('button','press',ce['apply_button'])
    return {'charge_power_per_inverter_w':int(charge_cap//100*100),
            'discharge_power_limit_per_inverter_w':-int(discharge_cap//100*100)}

def _restore_control_mode():
    try: previous=json.loads(CONTROL_STATE_FILE.read_text()).get('previous_mode')
    except Exception: previous=None
    c=config(); eid=c.get('control_entities',{}).get('mode','')
    if previous and eid:
        _control_call('select','select_option',eid,{'option':previous})
        time.sleep(1)
        restored,_=ha('states/'+eid)
        if not isinstance(restored,dict) or str(restored.get('state','')).casefold()!=str(previous).casefold():
            raise RuntimeError('Vorheriger Speichermodus wurde nicht bestätigt; der Wechselrichter-Watchdog bleibt als Rückfallebene aktiv.')
    try: CONTROL_STATE_FILE.unlink(missing_ok=True)
    except Exception: pass

def control_tick():
    c=config(); enabled=bool(c.get('settings',{}).get('control_enabled',False))
    with CONTROL_LOCK:
        previous_state={}
        try: previous_state=json.loads(CONTROL_STATE_FILE.read_text())
        except Exception: pass
        if not enabled:
            if previous_state.get('active'):
                try: _restore_control_mode(); CONTROL_RUNTIME.update(active=False,status='Steuerung ausgeschaltet · vorheriger Modus wiederhergestellt',ready=False,reasons=[])
                except Exception as exc: CONTROL_RUNTIME.update(active=True,status='Rückschaltung fehlgeschlagen',ready=False,reasons=[str(exc)])
            else: CONTROL_RUNTIME.update(active=False,ready=False,status='Steuerung aus',reasons=[])
            return
        pre=control_preflight(c)
        if previous_state.get('active') and not pre.get('watchdog_armed'):
            pre['ready']=False; pre['reasons'].append('Der aktive Regler hat keinen bestätigten 5-Minuten-Watchdog mit Rückkehr zum vorherigen Modus.')
        if not pre['ready']:
            restore_failed=False
            if previous_state.get('active'):
                try: _restore_control_mode(); c['settings']['control_enabled']=False; c['settings']['mode']='observe'; save(c)
                except Exception as exc: restore_failed=True; pre['reasons'].append('Rückschaltung fehlgeschlagen: '+str(exc))
            CONTROL_RUNTIME.update(active=restore_failed,ready=False,status='Sicherheitsprüfung nicht bestanden'+(' · Watchdog-Rückfall aktiv' if restore_failed else ''),reasons=pre['reasons'])
            return
        sign=c['settings']['grid_import_sign']; raw_grid=pre['sensors']['grid_power']
        export_w=max(0.0,raw_grid) if sign=='negative' else max(0.0,-raw_grid)
        try:
            if not previous_state.get('active'):
                mode_item=pre['entities']['mode']; current=mode_item.get('state')
                if 'passive' in str(current).casefold(): raise RuntimeError('Wechselrichter ist bereits im Passivmodus; vorherigen Modus zuerst manuell prüfen.')
                previous_state={'previous_mode':current,'active':True}
                tmp=CONTROL_STATE_FILE.with_suffix('.tmp'); tmp.write_text(json.dumps(previous_state)); tmp.replace(CONTROL_STATE_FILE)
                _arm_passive_watchdog(c,pre)
                pre=control_preflight(c)
                if not pre['ready'] or not pre.get('watchdog_armed'): raise RuntimeError('; '.join(pre['reasons']) or 'Watchdog nicht bestätigt.')
            last=float(previous_state.get('last_apply',0) or 0)
            targets=CONTROL_RUNTIME.get('recommendation') or {}
            if not targets or time.time()-last>=25:
                targets=_write_passive_targets(c,pre)
                mode_options=(pre['entities']['mode'].get('attributes') or {}).get('options',[])
                passive=next(str(x) for x in mode_options if 'passive' in str(x).casefold())
                if str(pre['entities']['mode'].get('state','')).casefold()!=passive.casefold():
                    _control_call('select','select_option',c['control_entities']['mode'],{'option':passive})
                previous_state['last_apply']=time.time(); tmp=CONTROL_STATE_FILE.with_suffix('.tmp'); tmp.write_text(json.dumps(previous_state)); tmp.replace(CONTROL_STATE_FILE)
            per_limit=targets.get('discharge_power_limit_per_inverter_w')
            CONTROL_RUNTIME.update(active=True,ready=True,status=f'Aktiv · {int(c["settings"].get("inverter_count",1))} Wechselrichter · Entladegrenze {per_limit} W je Gerät · Watchdog aktiv',reasons=[],last_update=datetime.now(timezone.utc).isoformat(),recommendation={**targets,'target_grid_w_per_inverter':0,'pv_export_w_total':round(export_w),'battery_soc_percent':pre['sensors']['battery_soc']})
        except Exception as exc:
            restore_failed=False
            try: _restore_control_mode()
            except Exception as restore_exc: restore_failed=True; CONTROL_RUNTIME['reasons']=['Steuerfehler: '+str(exc),'Rückschaltung fehlgeschlagen: '+str(restore_exc)]
            c['settings']['control_enabled']=False; c['settings']['mode']='observe'; save(c)
            CONTROL_RUNTIME.update(active=restore_failed,ready=False,status='Automatisch gesperrt · Steuerfehler'+(' · Watchdog-Rückfall aktiv' if restore_failed else ''),reasons=CONTROL_RUNTIME.get('reasons') or [str(exc)])

def controller_loop():
    while True:
        try: control_tick()
        except Exception as exc: app.logger.exception('Speicherregler-Fehler'); CONTROL_RUNTIME.update(status='Reglerfehler',ready=False,reasons=[str(exc)])
        time.sleep(10)

@app.route('/api/control/status')
def api_control_status():
    c=config(); check=control_preflight(c)
    return jsonify({'enabled':bool(c.get('settings',{}).get('control_enabled',False)),
        'preflight_ready':check['ready'],'preflight_reasons':check['reasons'],
        'runtime':dict(CONTROL_RUNTIME),'mode':'active_control' if CONTROL_RUNTIME.get('active') else 'advisory_only',
        'commands_sent':bool(CONTROL_RUNTIME.get('active'))})
@app.route('/consumers',methods=['GET','POST'])
def consumers():
 c=config()
 valid_types={'heater','motor','heat_pump','air_conditioner','pump','custom'}
 def num(value, default=0, lo=0, hi=250000):
  try: return min(hi,max(lo,int(float(value))))
  except (ValueError,TypeError): return default
 if request.method=='POST':
  remove_id=request.form.get('remove_consumer')
  if remove_id:
   c['consumers']=[x for x in c.get('consumers',[]) if str(x.get('id'))!=remove_id]
   save(c); flash('Verbraucher entfernt. Lernhistorie und übrige Einstellungen bleiben erhalten.','success')
   return redirect(url_for('consumers'))
  ids=request.form.getlist('consumer_id')
  names=request.form.getlist('consumer_name'); types=request.form.getlist('consumer_type')
  powers=request.form.getlist('consumer_power'); priorities=request.form.getlist('consumer_priority')
  management_modes=request.form.getlist('consumer_management_mode'); external_reserves=request.form.getlist('consumer_external_reserve')
  enabled=request.form.getlist('consumer_enabled'); modes=request.form.getlist('consumer_mode')
  stages_list=request.form.getlist('consumer_stages'); mins=request.form.getlist('consumer_min_power'); maxs=request.form.getlist('consumer_max_power')
  sensors=request.form.getlist('consumer_pressure_sensor'); pmins=request.form.getlist('consumer_pressure_min'); pmaxs=request.form.getlist('consumer_pressure_max')
  volumes=request.form.getlist('consumer_receiver_volume'); onbars=request.form.getlist('consumer_on_bar'); offbars=request.form.getlist('consumer_off_bar')
  leakflags=request.form.getlist('consumer_leak_monitor'); states=request.form.getlist('consumer_state_sensor')
  temps=request.form.getlist('consumer_temperature_sensor'); targets=request.form.getlist('consumer_target_temperature')
  for i,x in enumerate(c.get('consumers',[])):
   x.setdefault('id','consumer_'+str(i)); x['name']=(names[i].strip() if i<len(names) else x.get('name','Verbraucher')) or x.get('name','Verbraucher')
   x['type']=types[i] if i<len(types) and types[i] in valid_types else x.get('type','custom')
   x['nominal_power_w']=num(powers[i] if i<len(powers) else x.get('nominal_power_w',0),x.get('nominal_power_w',0))
   x['priority']=num(priorities[i] if i<len(priorities) else x.get('priority',3),3,1,99)
   x['enabled']=str(x['id']) in request.form.getlist('consumer_enabled') or str(i) in enabled
   x['management_mode']=management_modes[i] if i<len(management_modes) and management_modes[i] in ('advisory','external') else x.get('management_mode','advisory')
   x['external_reserve_power_w']=num(external_reserves[i] if i<len(external_reserves) else x.get('external_reserve_power_w',x.get('nominal_power_w',0)),x.get('nominal_power_w',0),0,250000)
   x['operation_mode']=modes[i] if i<len(modes) and modes[i] in ('staged','stepless') else x.get('operation_mode','staged')
   raw=stages_list[i] if i<len(stages_list) else ''
   try: parsed=sorted({num(v.strip(),0,1,x['nominal_power_w'] or 250000) for v in raw.replace(';',',').split(',') if v.strip()})
   except Exception: parsed=[]
   x['stages_w']=parsed if x['operation_mode']=='staged' else []
   x['min_power_w']=num(mins[i] if i<len(mins) else x.get('min_power_w',0),0,0,x['nominal_power_w'])
   x['max_power_w']=num(maxs[i] if i<len(maxs) else x.get('max_power_w',x['nominal_power_w']),x['nominal_power_w'],0,250000)
   entity=(sensors[i].strip() if i<len(sensors) else x.get('pressure_sensor_entity',''))
   x['pressure_sensor_entity']=entity if not entity or (entity.startswith(('sensor.','input_number.')) and ' ' not in entity) else ''
   try:x['pressure_min_bar']=max(0.0,min(30.0,float(pmins[i]))) if i<len(pmins) and pmins[i].strip() else x.get('pressure_min_bar',4.5)
   except ValueError:x['pressure_min_bar']=4.5
   try:x['pressure_max_bar']=max(0.0,min(30.0,float(pmaxs[i]))) if i<len(pmaxs) and pmaxs[i].strip() else x.get('pressure_max_bar',7.0)
   except ValueError:x['pressure_max_bar']=7.0
   def valid_entity(value):
    value=(value or '').strip()
    return value if not value or (value.startswith(('sensor.','input_number.','binary_sensor.')) and ' ' not in value) else ''
   x['receiver_volume_l']=num(volumes[i] if i<len(volumes) else x.get('receiver_volume_l',500),500,1,100000)
   try:x['compressor_on_bar']=max(0.0,min(30.0,float(onbars[i]))) if i<len(onbars) and onbars[i].strip() else x.get('compressor_on_bar',6.0)
   except ValueError:x['compressor_on_bar']=6.0
   try:x['compressor_off_bar']=max(0.0,min(30.0,float(offbars[i]))) if i<len(offbars) and offbars[i].strip() else x.get('compressor_off_bar',8.0)
   except ValueError:x['compressor_off_bar']=8.0
   
   if x.get('type')=='motor':
    x['leak_monitor_enabled']=str(x['id']) in request.form.getlist('consumer_leak_monitor')
   # For other consumer types, retain any stored compressor-specific setting.
   x['compressor_state_entity']=valid_entity(states[i] if i<len(states) else x.get('compressor_state_entity',''))
   x['temperature_sensor_entity']=valid_entity(temps[i] if i<len(temps) else x.get('temperature_sensor_entity',''))
   try:x['target_temperature_c']=max(-20.0,min(100.0,float(targets[i]))) if i<len(targets) and targets[i].strip() else x.get('target_temperature_c',20.0)
   except ValueError:x['target_temperature_c']=20.0
  name=request.form.get('new_name','').strip()
  if name:
   typ=request.form.get('new_type','custom'); typ=typ if typ in valid_types else 'custom'
   power=num(request.form.get('new_power','0'))
   mode=request.form.get('new_mode','staged'); mode=mode if mode in ('staged','stepless') else 'staged'
   raw=request.form.get('new_stages','')
   stages=sorted({num(v.strip(),0,1,power or 250000) for v in raw.replace(';',',').split(',') if v.strip()}) if mode=='staged' else []
   entity=request.form.get('new_pressure_sensor','').strip()
   if entity and not (entity.startswith(('sensor.','input_number.')) and ' ' not in entity): entity=''
   c['consumers'].append({'id':'consumer_'+str(time.time_ns()),'name':name,'type':typ,'enabled':True,'nominal_power_w':power,'stages_w':stages,'priority':num(request.form.get('new_priority','3'),3,1,99),'management_mode':request.form.get('new_management_mode','advisory') if request.form.get('new_management_mode') in ('advisory','external') else 'advisory','external_reserve_power_w':num(request.form.get('new_external_reserve',str(power)),power,0,250000),'operation_mode':mode,'min_power_w':num(request.form.get('new_min_power','0'),0,0,power),'max_power_w':num(request.form.get('new_max_power',str(power)),power,0,250000),'pressure_sensor_entity':entity,'pressure_min_bar':max(0.0,min(30.0,float(request.form.get('new_pressure_min','4.5') or 4.5))),'pressure_max_bar':max(0.0,min(30.0,float(request.form.get('new_pressure_max','7') or 7))),
    'receiver_volume_l':num(request.form.get('new_receiver_volume','500'),500,1,100000),
    'compressor_on_bar':max(0.0,min(30.0,float(request.form.get('new_on_bar','6') or 6))),
    'compressor_off_bar':max(0.0,min(30.0,float(request.form.get('new_off_bar','8') or 8))),
    'leak_monitor_enabled':request.form.get('new_leak_monitor')=='on',
    'compressor_state_entity':request.form.get('new_state_sensor','').strip(),
    'temperature_sensor_entity':request.form.get('new_temperature_sensor','').strip(),
    'target_temperature_c':max(-20.0,min(100.0,float(request.form.get('new_target_temperature','20') or 20)))})
  save(c); flash('Verbraucher gespeichert. Extern geregelte Lasten werden in der Überschussplanung berücksichtigt; diese App schaltet keine Verbraucher.','success')
  return redirect(url_for('consumers'))
 return render_template('consumers.html',cfg=c)

def learn_load_patterns(rows, days=14, min_power_w=1000, min_days=3):
    """Learn recurring aggregate house-load patterns in local 15-minute slots.

    Uses per-day medians so a single brief spike cannot dominate the learned
    profile. It does not identify individual appliances and never controls loads.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(days)) * 86400
    per_slot_day = {}
    valid_days = set()
    for row in rows:
        try:
            ts = datetime.fromisoformat(row.get('timestamp', '').replace('Z', '+00:00')).timestamp()
            if ts < cutoff:
                continue
            raw = row.get('values', {}).get('load_power')
            if not isinstance(raw, (int, float)) or raw < 0 or raw > 250000:
                continue
            dt = datetime.fromtimestamp(ts).astimezone()
            slot = (dt.hour * 60 + (dt.minute // 15) * 15)
            day = dt.date().isoformat()
            per_slot_day.setdefault(slot, {}).setdefault(day, []).append(float(raw))
            valid_days.add(day)
        except (ValueError, TypeError, OverflowError):
            continue
    profile = []
    for slot, day_values in per_slot_day.items():
        if len(day_values) < min_days:
            continue
        daily_medians = [statistics.median(v) for v in day_values.values() if v]
        typical = statistics.median(daily_medians) if daily_medians else 0
        if typical < min_power_w:
            continue
        profile.append({
            'time': f'{slot // 60:02d}:{slot % 60:02d}',
            'median_w': round(typical),
            'days_seen': len(day_values),
            'confidence': 'hoch' if len(day_values) >= 7 else 'mittel' if len(day_values) >= 5 else 'vorläufig'
        })
    profile.sort(key=lambda x: x['time'])
    return {'days_with_load_data': len(valid_days), 'patterns': profile,
            'min_days_required': min_days, 'slot_minutes': 15,
            'note': 'Aggregate house load; appliance identity is not inferred.'}



# Tiny trainable neural network (one hidden layer), implemented with Python stdlib.
# Self-supervised next-sample forecasting: previous six load samples -> next load.
# This is a real trained MLP, but it predicts aggregate load; it does not label appliances.
BRAIN_MODEL = DATA / 'brain_mlp_model.json'
BRAIN_TRAIN_LOCK=threading.Lock()
MODEL_RETRAIN_BATCH=300
MORNING_STRATEGY_STATE=DATA/'morning_strategy_state.json'

def _sigmoid_tanh(x):
    x=max(-20.0,min(20.0,x))
    return (2.0/(1.0+pow(2.718281828459045,-2.0*x)))-1.0

def train_load_mlp(rows, force=False):
    valid=[]
    for row in rows[-50000:]:
        try:
            ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            v=float((row.get('values') or {}).get('load_power'))
            if 0 <= v <= 250000: valid.append((ts,v))
        except (ValueError,TypeError,OverflowError): continue
    # Only build sequences from near-regular samples; discard gaps.
    seq=[]
    for i in range(6,len(valid)):
        window=valid[i-6:i+1]
        if all(5 <= window[j+1][0]-window[j][0] <= 20 for j in range(6)):
            seq.append(([x[1]/20000.0 for x in window[:6]],window[6][1]/20000.0))
    if len(seq)<120:
        return {'trained':False,'status':'Zu wenige zusammenhängende Messwerte','training_samples':len(seq),'mae_w':None,'next_load_prediction_w':None,'model':'MLP 6-8-1'}
    signature=len(seq)
    # Chronological holdout: the newest 20% are reserved for evaluation,
    # so the displayed MAE measures unseen future samples rather than training fit.
    split=max(100, int(len(seq)*0.8))
    train_seq=seq[:split]
    test_seq=seq[split:] or seq[-min(100,len(seq)):]
    try:
        old=json.loads(BRAIN_MODEL.read_text())
        old_samples=int(old.get('training_samples',0))
        if (not force and old.get('version')==2 and signature>=old_samples
                and signature-old_samples<MODEL_RETRAIN_BATCH):
            model=old
        else: model=None
    except Exception: model=None
    newly_trained = model is None
    if model is None:
        # Deterministic small initial weights, no external packages or network.
        h=8; w1=[[(((i+1)*(j+3)%17)-8)*0.006 for i in range(6)] for j in range(h)]
        b1=[0.0]*h; w2=[(((j+2)%7)-3)*0.01 for j in range(h)]; b2=0.0
        lr=0.018
        # Fixed ordering keeps the local training reproducible.
        for epoch in range(7):
            for x,y in train_seq:
                hidden=[_sigmoid_tanh(sum(w1[j][k]*x[k] for k in range(6))+b1[j]) for j in range(h)]
                pred=sum(w2[j]*hidden[j] for j in range(h))+b2
                err=max(-1.5,min(1.5,pred-y))
                old_w2=w2[:]
                for j in range(h):
                    grad=err*old_w2[j]*(1-hidden[j]*hidden[j])
                    w1[j]=[w1[j][k]-lr*grad*x[k] for k in range(6)]
                    b1[j]-=lr*grad
                    w2[j]-=lr*err*hidden[j]
                b2-=lr*err
        model={'model':'MLP 6-8-1','version':2,'trained_at':datetime.now(timezone.utc).isoformat(),
               'training_samples':signature,'training_sequences':len(train_seq),'validation_sequences':len(test_seq),'w1':w1,'b1':b1,'w2':w2,'b2':b2}
        try:
            tmp=BRAIN_MODEL.with_suffix('.tmp'); tmp.write_text(json.dumps(model)); tmp.replace(BRAIN_MODEL)
        except Exception: pass
    def predict(x):
        hidden=[_sigmoid_tanh(sum(model['w1'][j][k]*x[k] for k in range(6))+model['b1'][j]) for j in range(8)]
        return sum(model['w2'][j]*hidden[j] for j in range(8))+model['b2']
    check=test_seq
    mae=sum(abs(predict(x)-y)*20000.0 for x,y in check)/len(check)
    baseline_mae=sum(abs(x[-1]-y)*20000.0 for x,y in check)/len(check)
    improvement=((baseline_mae-mae)/baseline_mae*100.0) if baseline_mae>0 else 0.0
    latest=[v/20000.0 for _,v in valid[-6:]]
    next_w=max(0.0,predict(latest)*20000.0) if len(latest)==6 else None
    return {'trained':True,'status':'Neu trainiert' if newly_trained else 'Aktiv · wartet auf weiteren Lernblock',
            'training_samples':model.get('training_samples',signature),'available_sequences':signature,'training_sequences':model.get('training_sequences',len(train_seq)),'validation_sequences':len(test_seq),'mae_w':round(mae),'baseline_mae_w':round(baseline_mae),'improvement_pct':round(improvement,1),'beats_baseline':mae<baseline_mae,'next_load_prediction_w':round(next_w) if next_w is not None else None,
            'model':model['model'],'trained_at':model.get('trained_at'),'architecture':'6 Eingänge · 8 Neuronen · 1 Ausgang',
            'target':'Hausverbrauch in ca. 10 Sekunden; selbstüberwachtes Prognose-Training'}

# Multi-channel next-sample forecasts. Separate models preserve the legacy load MLP.
BRAIN_MULTI_MODEL = DATA / 'brain_multichannel_model.json'
BRAIN_CHANNELS = {
    'load_power': ('Hauslast', 250000, True),
    'pv_power': ('PV-Leistung', 250000, True),
    'grid_power': ('Netzleistung', 250000, False),
    'battery_power': ('Batterieleistung', 100000, False),
}

def train_multichannel_mlp(rows, force=False):
    result=[]; models={}; signatures={}
    old={}
    try: old=json.loads(BRAIN_MULTI_MODEL.read_text())
    except Exception: pass
    for key,(label,scale,nonnegative) in BRAIN_CHANNELS.items():
        vals=[]
        for row in rows[-50000:]:
            try:
                ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
                v=float((row.get('values') or {}).get(key))
                if abs(v)<=scale and (not nonnegative or v>=0): vals.append((ts,v))
            except (ValueError,TypeError,OverflowError): continue
        seq=[]
        for i in range(6,len(vals)):
            w=vals[i-6:i+1]
            if all(5 <= w[j+1][0]-w[j][0] <= 20 for j in range(6)):
                seq.append(([x[1]/scale for x in w[:6]],w[6][1]/scale))
        sig=len(seq); signatures[key]=sig
        if sig < 120:
            if isinstance(old.get('channels',{}).get(key),dict): models[key]=old['channels'][key]
            result.append({'key':key,'label':label,'trained':False,'samples':sig,'mae_w':None,'next_w':None,'status':'Zu wenige zusammenhängende Messwerte'})
            continue
        split=max(100,int(sig*.8)); train_seq=seq[:split]; test_seq=seq[split:] or seq[-min(100,len(seq)):]
        model=old.get('channels',{}).get(key)
        old_samples=int(model.get('training_samples',0)) if isinstance(model,dict) else 0
        newly_trained = (force or not isinstance(model,dict) or model.get('version')!=1
                or sig<old_samples or sig-old_samples>=MODEL_RETRAIN_BATCH)
        if newly_trained:
            h=8; w1=[[((((i+1)*(j+3))%17)-8)*.006 for i in range(6)] for j in range(h)]
            b1=[0.0]*h; w2=[((((j+2)%7)-3)*.01) for j in range(h)]; b2=0.0; lr=.015
            for epoch in range(9):
                for x,y in train_seq:
                    hidden=[_sigmoid_tanh(sum(w1[j][k]*x[k] for k in range(6))+b1[j]) for j in range(h)]
                    pred=sum(w2[j]*hidden[j] for j in range(h))+b2; err=max(-1.5,min(1.5,pred-y)); ow=w2[:]
                    for j in range(h):
                        grad=err*ow[j]*(1-hidden[j]*hidden[j])
                        w1[j]=[w1[j][k]-lr*grad*x[k] for k in range(6)]; b1[j]-=lr*grad; w2[j]-=lr*err*hidden[j]
                    b2-=lr*err
            model={'version':1,'training_samples':sig,'trained_at':datetime.now(timezone.utc).isoformat(),'w1':w1,'b1':b1,'w2':w2,'b2':b2}
        def pred(x):
            hidden=[_sigmoid_tanh(sum(model['w1'][j][k]*x[k] for k in range(6))+model['b1'][j]) for j in range(8)]
            return sum(model['w2'][j]*hidden[j] for j in range(8))+model['b2']
        mae=sum(abs(pred(x)-y)*scale for x,y in test_seq)/len(test_seq)
        # Persistence baseline: predict that the next sample equals the latest sample.
        baseline_mae=sum(abs(x[-1]-y)*scale for x,y in test_seq)/len(test_seq)
        improvement=((baseline_mae-mae)/baseline_mae*100.0) if baseline_mae>0 else 0.0
        nxt=pred([v/scale for _,v in vals[-6:]])*scale if len(vals)>=6 else None
        if nonnegative and nxt is not None: nxt=max(0,nxt)
        models[key]=model
        result.append({'key':key,'label':label,'trained':True,'samples':sig,'training_samples':model.get('training_samples',sig),'available_samples':sig,'validation_samples':len(test_seq),'mae_w':round(mae),'baseline_mae_w':round(baseline_mae),'improvement_pct':round(improvement,1),'beats_baseline':mae<baseline_mae,'next_w':round(nxt) if nxt is not None else None,'status':'Neu trainiert · Zukunftsprüfung' if newly_trained else 'Aktiv · wartet auf weiteren Lernblock'})
    if models:
        try:
            tmp=BRAIN_MULTI_MODEL.with_suffix('.tmp'); tmp.write_text(json.dumps({'version':1,'channels':models,'signatures':signatures})); tmp.replace(BRAIN_MULTI_MODEL)
        except Exception: pass
    return {'channels':result,'model':'MLP je Energiekanal','architecture':'je Kanal: 6 Messwerte · 8 Neuronen · 1 Ausgang','target':'Nächster Messwert je Kanal (ca. 10 Sekunden)','trained_channels':sum(1 for x in result if x['trained'])}

# Energy Brain: local, explainable unsupervised load-event learning. No cloud/commands.
def build_energy_brain(rows):
    with BRAIN_TRAIN_LOCK:
        neural=train_load_mlp(rows)
        multichannel=train_multichannel_mlp(rows)
    events=[]; prev=None
    for row in rows[-50000:]:
        try:
            ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            vals=row.get('values') or {}; load=float(vals.get('load_power'))
            grid=vals.get('grid_power'); batt=vals.get('battery_power'); pv=vals.get('pv_power')
            if prev:
                dt=ts-prev['ts']; delta=load-prev['load']
                if 5 <= dt <= 35 and abs(delta)>=900:
                    events.append({'ts':ts,'delta':delta,'load':load,'duration_hint':dt,
                      'grid':float(grid) if grid is not None else None,'battery':float(batt) if batt is not None else None,'pv':float(pv) if pv is not None else None,
                      'grid_delta':(float(grid)-float(prev['grid'])) if grid is not None and prev.get('grid') is not None else None,
                      'battery_delta':(float(batt)-float(prev['battery'])) if batt is not None and prev.get('battery') is not None else None,
                      'pv_delta':(float(pv)-float(prev['pv'])) if pv is not None and prev.get('pv') is not None else None})
            prev={'ts':ts,'load':load,'grid':float(grid) if grid is not None else None,'battery':float(batt) if batt is not None else None,'pv':float(pv) if pv is not None else None}
        except (ValueError,TypeError): continue
    pattern_memory = update_brain_pattern_memory(events)
    # Greedy clustering by direction and step magnitude; transparent tolerance, not a neural model.
    clusters=[]
    for e in events:
        mag=abs(e['delta']); direction='Lastanstieg' if e['delta']>0 else 'Lastabfall'
        match=None
        for c in clusters:
            if c['direction']==direction and abs(mag-c['mean_w']) <= max(1200, c['mean_w']*.22): match=c; break
        if match is None:
            match={'direction':direction,'mean_w':mag,'events':[]}; clusters.append(match)
        match['events'].append(e); match['mean_w']=sum(abs(x['delta']) for x in match['events'])/len(match['events'])
    profiles=[]
    for i,c in enumerate(sorted(clusters,key=lambda x:len(x['events']),reverse=True)[:12],1):
        ev=c['events']; hours=[datetime.fromtimestamp(x['ts'],timezone.utc).astimezone().strftime('%H:%M') for x in ev]
        mins=[]
        for x in ev:
            # event duration cannot be inferred from a single transition; keep explicitly unknown
            pass
        n=len(ev); confidence='vorläufig' if n<5 else 'mittel' if n<15 else 'hoch'
        profiles.append({'id':f'P{i:02d}','direction':c['direction'],'mean_step_w':round(c['mean_w']),
          'events':n,'confidence':confidence,'typical_times':hours[:8],
          'explanation':f'{n} ähnliche {c["direction"].lower()}-Ereignisse; mittlere Änderung etwa {round(c["mean_w"])} W. Verbraucheridentität nicht bekannt.'})
    # Pair start/end transitions conservatively. A short maximum window avoids
    # joining unrelated events hours apart; matching considers all available channels.
    rises=sorted([e for e in events if e['delta']>0], key=lambda e:e['ts'])
    falls=sorted([e for e in events if e['delta']<0], key=lambda e:e['ts'])
    used_falls=set(); cycles=[]
    for rise in rises:
        candidates=[]
        for idx,fall in enumerate(falls):
            if idx in used_falls or fall['ts'] <= rise['ts']: continue
            duration=fall['ts']-rise['ts']
            if duration > 45*60: break
            magnitude=abs(rise['delta']); endmag=abs(fall['delta'])
            tolerance=max(1200, magnitude*0.20)
            if abs(magnitude-endmag) > tolerance: continue
            # Prefer similar grid/battery/PV response where both readings exist.
            channel_penalty=0.0; compared=0
            for key in ('grid_delta','battery_delta','pv_delta'):
                a,b=rise.get(key),fall.get(key)
                if a is not None and b is not None:
                    channel_penalty += min(abs(a+b),12000)/12000; compared += 1
            score=abs(magnitude-endmag)/max(tolerance,1) + duration/(45*60)*0.15 + (channel_penalty/compared if compared else 0)*0.25
            candidates.append((score,idx,fall,duration))
        if candidates:
            _,idx,fall,duration=min(candidates,key=lambda x:x[0])
            used_falls.add(idx)
            cycles.append({'start_ts':rise['ts'],'duration_s':duration,
                'power_w':(abs(rise['delta'])+abs(fall['delta']))/2,
                'grid_delta_w':None if rise.get('grid_delta') is None or fall.get('grid_delta') is None else (rise['grid_delta']+fall['grid_delta'])/2,
                'battery_delta_w':None if rise.get('battery_delta') is None or fall.get('battery_delta') is None else (rise['battery_delta']+fall['battery_delta'])/2,
                'pv_delta_w':None if rise.get('pv_delta') is None or fall.get('pv_delta') is None else (rise['pv_delta']+fall['pv_delta'])/2})
    cycle_groups=[]
    for cycle in cycles:
        match=None
        for group in cycle_groups:
            power_close=abs(cycle['power_w']-group['mean_power_w']) <= max(1200,group['mean_power_w']*.18)
            duration_close=abs(cycle['duration_s']-group['median_duration_s']) <= max(180,group['median_duration_s']*.60)
            if power_close and duration_close:
                match=group; break
        if match is None:
            match={'mean_power_w':cycle['power_w'],'median_duration_s':cycle['duration_s'],'items':[]}; cycle_groups.append(match)
        match['items'].append(cycle)
        match['mean_power_w']=sum(x['power_w'] for x in match['items'])/len(match['items'])
        match['median_duration_s']=statistics.median(x['duration_s'] for x in match['items'])
    learned_cycles=[]
    for i,g in enumerate(sorted(cycle_groups,key=lambda x:len(x['items']),reverse=True)[:10],1):
        items=g['items']; durations=[x['duration_s'] for x in items]
        def avg_channel(key):
            vals=[x[key] for x in items if x.get(key) is not None]
            return round(statistics.median(vals)) if vals else None
        learned_cycles.append({'id':f'Z{i:02d}','cycles':len(items),'mean_power_w':round(g['mean_power_w']),
            'median_duration_s':round(statistics.median(durations)),
            'grid_response_w':avg_channel('grid_delta_w'),'battery_response_w':avg_channel('battery_delta_w'),'pv_response_w':avg_channel('pv_delta_w'),
            'confidence':'vorläufig' if len(items)<5 else 'mittel' if len(items)<15 else 'hoch',
            'times':[datetime.fromtimestamp(x['start_ts'],timezone.utc).astimezone().strftime('%H:%M') for x in items[:8]]})
    # Coarse data quality summary
    gaps=[]
    for a,b in zip(rows[-50000:],rows[-50000:][1:]):
        try:
            ta=datetime.fromisoformat(a['timestamp'].replace('Z','+00:00')).timestamp(); tb=datetime.fromisoformat(b['timestamp'].replace('Z','+00:00')).timestamp();
            if tb-ta>30: gaps.append(tb-ta)
        except Exception: pass
    # Cross-channel energy balance check. Sign convention: grid positive=export,
    # battery positive=charging, PV/load positive. Approximate AC balance:
    # PV - battery - grid - load ~= 0. This is diagnostic only.
    balance_residuals=[]
    balance_valid=0
    balance_skipped=0
    for row in rows[-50000:]:
        vals=row.get('values') or {}
        try:
            pv=float(vals.get('pv_power')); load=float(vals.get('load_power'))
            grid=float(vals.get('grid_power')); batt=float(vals.get('battery_power'))
            if not all(math.isfinite(x) for x in (pv,load,grid,batt)):
                balance_skipped += 1; continue
            if pv < 0 or load < 0 or abs(grid)>100000 or abs(batt)>100000 or pv>100000 or load>100000:
                balance_skipped += 1; continue
            balance_residuals.append(abs(pv-batt-grid-load))
            balance_valid += 1
        except (TypeError,ValueError,OverflowError):
            balance_skipped += 1
    balance_mae = round(sum(balance_residuals)/len(balance_residuals)) if balance_residuals else None
    balance_median = round(statistics.median(balance_residuals)) if balance_residuals else None
    balance_status = ('Zu wenige gemeinsame Messwerte' if balance_valid < 30 else
                      'Plausibel' if balance_median is not None and balance_median <= 1500 else
                      'Abweichung prüfen')
    # The Energy Brain template displays this field. Keep the calculation
    # defensive so an empty or malformed history still renders the page.
    hourly_counts={}
    for row in rows[-50000:]:
        try:
            ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp()
            hour=datetime.fromtimestamp(ts).astimezone().hour
            hourly_counts[hour]=hourly_counts.get(hour,0)+1
        except (TypeError,ValueError,OverflowError,OSError):
            continue
    anomaly_threshold=max(1500, round(statistics.median([abs(e['delta']) for e in events])*3)) if events else 1500
    recent_cutoff=time.time()-3600
    recent_anomalies=[{'timestamp':datetime.fromtimestamp(e['ts']).astimezone().strftime('%d.%m.%Y %H:%M:%S'),
                       'delta_w':round(e['delta']),'threshold_w':anomaly_threshold}
                      for e in events if e['ts']>=recent_cutoff and abs(e['delta'])>=anomaly_threshold][-20:]
    recurrence_analysis={
      'anomaly_threshold_w':anomaly_threshold,
      'recent_anomalies':recent_anomalies,
      'most_sampled_hours':[{'hour':h,'samples':n} for h,n in sorted(hourly_counts.items(),key=lambda item:item[1],reverse=True)[:5]],
      'note':'Auffälligkeitsschwelle basiert auf der historischen Verteilung der erkannten Lastsprünge; sie benennt keinen Verbraucher.'}
    # Advisory-only instantaneous interpretation. Do not propose battery/grid
    # actions until the grid sensor sign has been verified by the installer.
    latest_values=(rows[-1].get('values') or {}) if rows else {}
    try: current_load=max(0,round(float(latest_values.get('load_power'))))
    except (TypeError,ValueError,OverflowError): current_load=None
    try: current_pv=max(0,round(float(latest_values.get('pv_power'))))
    except (TypeError,ValueError,OverflowError): current_pv=None
    st=config().get('settings',{})
    limit=int(st.get('grid_import_limit_w',5000) or 5000)
    recommendation_reasons=[]
    if current_load is None or current_pv is None:
        recommendation='Noch keine ausreichenden aktuellen Hauslast- und PV-Werte für eine Empfehlung.'
        recommendation_reasons.append('Mindestens ein erforderlicher Messwert fehlt oder ist ungültig.')
    elif st.get('grid_import_sign','unverified')=='unverified':
        recommendation='Zuerst das Vorzeichen des Netzleistungssensors in der Konfiguration bestätigen. Bis dahin keine Netz- oder Speicherempfehlung.'
        recommendation_reasons.append('Das Netzleistungs-Vorzeichen ist nicht bestätigt; Netzbezug und Einspeisung wären sonst verwechselbar.')
    elif current_pv>=current_load:
        recommendation='Die gemessene PV-Leistung deckt die aktuelle Hauslast rechnerisch. Speicherladung oder Einspeisung hängt von den tatsächlichen Wechselrichterwerten ab.'
        recommendation_reasons.append(f'PV {current_pv} W liegt mindestens auf Höhe der Hauslast {current_load} W.')
    else:
        deficit=current_load-current_pv
        recommendation=f'Aktuell fehlen gegenüber der Hauslast rund {deficit} W PV-Leistung. Der Speicher kann diesen Anteil nur innerhalb seiner Leistungsgrenze und oberhalb der Reserve übernehmen; andernfalls bleibt Netzbezug.'
        recommendation_reasons.append(f'Hauslast {current_load} W minus PV {current_pv} W ergibt rechnerisch {deficit} W Restbedarf.')
        recommendation_reasons.append(f'Konfigurierte Netzbezugsgrenze: {limit} W; dies ist ein Zielwert, keine Abschaltung.')
    return {'engine':'Energy Brain local v3','method':'Anlagenweite Musteranalyse aus Hauslast, Netz, Batterie und PV; Lastsprünge und Zyklusprofile sind erklärbare statistische Merkmale. Das neuronale Netz prognostiziert den aggregierten Hausverbrauch. Geräteidentitäten sind ausdrücklich nicht erforderlich.',
      'samples_used':min(len(rows),50000),'events_found':len(events),'profiles':profiles,
      'paired_cycles_found':len(cycles),'cycle_profiles':learned_cycles,
      'persistent_pattern_memory':pattern_memory,
      'data_gaps_over_30s':len(gaps),'sample_interval_target_seconds':10,
      'status':'Lernphase – Muster werden mit mehr Wiederholungen stabiler',
      'energy_balance':{'formula':'PV − Batterie − Netz − Hauslast','valid_samples':balance_valid,
          'skipped_samples':balance_skipped,'mae_w':balance_mae,'median_abs_error_w':balance_median,
          'status':balance_status,'note':'Diagnosewert; Abweichungen können durch Messpunkte, Verluste und unterschiedliche Sensorzeitpunkte entstehen.'},
      'recurrence_analysis':recurrence_analysis,
      'recommendation':{'text':recommendation,'reasons':recommendation_reasons,'current_load_w':current_load,'current_pv_w':current_pv,'grid_import_limit_w':limit,'mode':'Nur Empfehlung; keine Steuerbefehle.'},
      'limitations':['Das Ziel ist die Erkennung wiederkehrender Anlagen- und Energiemuster; Gerätenamen oder manuelle Gerätezuordnungen sind nicht erforderlich.','Zykluslaufzeiten sind heuristische Zuordnungen innerhalb eines 45-Minuten-Fensters; überlagerte Lasten können sie weiterhin verfälschen.','Das neuronale Netz prognostiziert aktuell den aggregierten Hausverbrauch und klassifiziert noch keine Betriebszustände.','Prognosen und Profile sind Beobachtungswerte, keine Steuerentscheidungen.'],
      'neural_network':neural, 'multichannel_forecast':multichannel, 'multichannel_forecast':multichannel,'active_control_enabled':False,'commands_sent':False}

ENERGY_BRAIN_CACHE={'key':None,'created':0.0,'result':None}
ENERGY_BRAIN_CACHE_LOCK=threading.Lock()

def get_energy_brain():
    """Avoid retraining all local models on every page render or question."""
    try:
        stat=HIST.stat()
        key=(stat.st_mtime_ns,stat.st_size)
    except OSError:
        key=(None,0)
    now=time.time()
    with ENERGY_BRAIN_CACHE_LOCK:
        if (ENERGY_BRAIN_CACHE['result'] is not None
                and now-ENERGY_BRAIN_CACHE['created']<30):
            return ENERGY_BRAIN_CACHE['result']
        result=build_energy_brain(learning_rows())
        ENERGY_BRAIN_CACHE.update(key=key,created=now,result=result)
        return result

def model_learning_loop():
    """Train local forecasts in bounded batches without requiring a page visit."""
    while True:
        try:
            rows=learning_rows()
            with BRAIN_TRAIN_LOCK:
                load_model=train_load_mlp(rows)
                channel_models=train_multichannel_mlp(rows)
            if rows:
                latest_values=rows[-1].get('values',{})
                plan_snapshot={'values':{k:{'value':v,'unit':'Wh' if k=='pv_forecast' else '%' if k=='battery_soc' else 'W'}
                                         for k,v in latest_values.items()}}
                strategy=build_battery_plan(config(),rows,plan_snapshot).get('learned_strategy',{})
                old_state={}
                try: old_state=json.loads(MORNING_STRATEGY_STATE.read_text())
                except Exception: pass
                tmp=MORNING_STRATEGY_STATE.with_suffix('.tmp')
                tmp.write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),**strategy},ensure_ascii=False))
                tmp.replace(MORNING_STRATEGY_STATE)
                if strategy.get('status')!=old_state.get('status'):
                    app.logger.info('Morgen-Schattenstrategie aktualisiert: %s (%s Morgenpaare).',strategy.get('status'),strategy.get('pairs',0))
            if load_model.get('status')=='Neu trainiert' or any(
                    str(c.get('status','')).startswith('Neu trainiert')
                    for c in channel_models.get('channels',[])):
                app.logger.info('Energy Brain hat neue lokale Lernmodelle trainiert (%s Messfolgen).',len(rows))
            if 'ENERGY_BRAIN_CACHE' in globals(): ENERGY_BRAIN_CACHE['created']=0
        except Exception:
            app.logger.exception('Lokales Energy-Brain-Training fehlgeschlagen')
        time.sleep(300)

@app.route('/energy-brain')
def energy_brain():
    try:
        result=get_energy_brain()
        return render_template('energy_brain.html',brain=result)
    except Exception as exc:
        app.logger.exception('Energy Brain konnte nicht aufgebaut werden')
        return render_template('energy_brain.html',brain={
            'samples_used':0,'events_found':0,'profiles':[],'data_gaps_over_30s':0,
            'status':'Auswertung fehlgeschlagen: '+str(exc)[:240],
            'neural_network':{'model':'–','training_samples':0,'mae_w':None,'next_load_prediction_w':None,'status':'Nicht verfügbar'},
            'multichannel_forecast':{'channels':[],'model':'–','architecture':'–','trained_channels':0},
            'persistent_pattern_memory':{'stored_signatures':0,'new_events':0,'top_patterns':[],'status':'Nicht verfügbar'},
            'recurrence_analysis':{'anomaly_threshold_w':0,'recent_anomalies':[],'most_sampled_hours':[]},
            'recommendation':{'text':'Keine Empfehlung verfügbar.','reasons':[],'current_load_w':None,'current_pv_w':None,'mode':'Nur Empfehlung; keine Steuerbefehle.'},
            'paired_cycles_found':0,'cycle_profiles':[],'method':'Die Details stehen im Home-Assistant-Protokoll.',
            'limitations':['Die Auswertung konnte nicht abgeschlossen werden. Bitte Home-Assistant-Protokoll prüfen.']})

@app.route('/api/energy-brain')
def api_energy_brain():
    return jsonify(get_energy_brain())

@app.route('/api/energy-brain/explain',methods=['POST'])
def api_energy_brain_explain():
    """Give a local, source-grounded explanation of the current advisory."""
    question=(request.get_json(silent=True) or {}).get('question','')
    question=' '.join(str(question).strip().split())[:500]
    if not question:
        return jsonify({'answer':'Bitte stelle eine kurze Frage zur aktuellen Empfehlung.'}),400
    brain=get_energy_brain()
    rec=brain.get('recommendation') or {}
    q=question.casefold()
    reasons=rec.get('reasons') or []
    answer=' '.join([rec.get('text','Zurzeit liegt keine Empfehlung vor.'),*reasons])
    if any(word in q for word in ('netz','strom','spitze','limit')):
        answer += f" Netzbezugsgrenze laut Konfiguration: {rec.get('grid_import_limit_w','unbekannt')} W. Sie ist ein Zielwert und keine harte Abschaltung."
        if config().get('settings',{}).get('grid_import_sign','unverified')=='unverified':
            answer += ' Das Vorzeichen des Netzsensors ist noch nicht bestätigt; deshalb wird kein Netzbezug aus dem Messwert abgeleitet.'
    if any(word in q for word in ('speicher','batterie','akku','reserve')):
        answer += ' Eine konkrete Lade- oder Entladevorgabe wird derzeit nicht berechnet, weil SoC, Batterie-Leistungsgrenzen, Reserve und geprüfte Register gemeinsam bewertet werden müssen. Es werden keine Wechselrichterbefehle gesendet.'
    if any(word in q for word in ('pv','solar','sonne')):
        answer += f" Verwendete Momentanwerte: PV {rec.get('current_pv_w','unbekannt')} W, Hauslast {rec.get('current_load_w','unbekannt')} W. Das ist eine Momentaufnahme, keine Tagesprognose."
    return jsonify({'question':question,'answer':answer,'mode':'lokal · regelbasiert und messwertgestützt','commands_sent':False})

@app.route('/api/learned-load-patterns')
def api_learned_load_patterns():
    rows = learning_rows()
    st = config().get('settings', {})
    result = learn_load_patterns(rows, st.get('learning_days', 14))
    result['learning_started_at'] = datetime.fromtimestamp(learning_start_timestamp(), timezone.utc).isoformat()
    result['historical_statistics_used'] = False
    return jsonify(result)


@app.route('/learning')
def learning():
    rows=learning_rows()
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
    morning_days_with_samples=set()
    for ts,r in recent:
        dt=datetime.fromtimestamp(ts).astimezone()
        if int(st.get('morning_start_hour',5)) <= dt.hour < int(st.get('morning_end_hour',9)):
            raw_grid = r.get('values',{}).get('grid_power')
            if isinstance(raw_grid,(int,float)):
                morning_days_with_samples.add(dt.date().isoformat())
            v=r.get('values',{}).get('grid_power')
            if isinstance(v,(int,float)):
                import_w=float(v) if sign=='positive' else (-float(v) if sign=='negative' else None)
                if import_w is not None: morning.append({'day':dt.date().isoformat(),'hour':dt.hour,'grid_import_w':max(0,import_w)})
    daily={}
    for x in morning: daily[x['day']]=max(daily.get(x['day'],0),x['grid_import_w'])
    learned_peak=round(statistics.median(daily.values()),0) if len(daily)>=3 else None
    battery_plan=build_battery_plan(c, rows, snapshot())
    load_patterns=learn_load_patterns(rows, days)
    return render_template('learning.html',cfg=c,stats=stats,count=len(recent),history_file=str(HIST),days=days, learning_started_at=datetime.fromtimestamp(learning_start_timestamp(),timezone.utc).astimezone().strftime('%d.%m.%Y %H:%M'),
        morning_count=len(daily),morning_peak=learned_peak,grid_import_sign=sign,daily_peaks=daily,
        morning_days_with_samples=len(morning_days_with_samples),
        morning_sample_count=len(morning), learning_started_timestamp=learning_start_timestamp(),
        battery_plan=battery_plan,load_patterns=load_patterns)

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
    external_reserved_w = 0
    state_text = {'on','true','1','running','heat','heating'}
    external_states = {}
    for consumer in consumers:
        if consumer.get('management_mode') != 'external':
            continue
        consumer_snapshot = (snap.get('consumer_values', {}).get(str(consumer.get('id','')), {}) or {})
        state = consumer_snapshot.get('compressor_state_entity') or {}
        raw_state = str(state.get('state', '')).strip().lower()
        active = raw_state in state_text
        external_states[str(consumer.get('id'))] = (active, raw_state)
        if not active:
            external_reserved_w += max(0, int(consumer.get('external_reserve_power_w', consumer.get('nominal_power_w', 0)) or 0))
    if remaining is not None:
        remaining = max(0.0, remaining - external_reserved_w)
    if remaining is not None:
        for consumer in consumers:
            if consumer.get('management_mode') == 'external':
                active, raw_state = external_states.get(str(consumer.get('id')), (False, ''))
                reserve = 0 if active else max(0, int(consumer.get('external_reserve_power_w', consumer.get('nominal_power_w', 0)) or 0))
                recommendations.append({'id':consumer.get('id'),'name':consumer.get('name','Verbraucher'),
                    'priority':int(consumer.get('priority',99)),'nominal_power_w':max(0,int(consumer.get('nominal_power_w',0))),
                    'suggested_power_w':0,'status':'external','pressure_bar':None,'temperature_c':None,
                    'note':('Läuft laut Statussensor; der aktuelle Verbrauch steckt bereits in der Netzmessung.' if active else
                            f'Extern geregelt durch Home Assistant; {reserve} W vorsorglich reserviert. Status unbekannt/aus ({raw_state or "kein Statussensor"}).')})
                continue
            try:
                stages = sorted({int(v) for v in consumer.get('stages_w', []) if int(v) > 0})
            except (TypeError, ValueError):
                stages = []
            nominal = max(0, int(consumer.get('nominal_power_w', 0)))
            options = [v for v in stages if v <= remaining]
            chosen = max(options) if options else (nominal if nominal and nominal <= remaining else 0)
            consumer_snapshot=(snap.get('consumer_values',{}).get(str(consumer.get('id','')),{}) or {})
            pressure=consumer_snapshot.get('pressure_sensor_entity')
            temp=consumer_snapshot.get('temperature_sensor_entity')
            note = (f'{chosen} W passen rechnerisch in den verfügbaren Überschuss.' if chosen > 0
                    else 'Der verfügbare Überschuss reicht mit Sicherheitsabstand nicht für eine Stufe.')
            if pressure and pressure.get('value') is not None:
                pv = pressure['value']
                note += f' Drucksensor: {pv:.1f} bar.'
                if consumer.get('type') == 'motor' and pv < float(consumer.get('pressure_min_bar',4.5)):
                    note = f'Druck unter Mindestwert ({pv:.1f} bar): Kompressorbedarf hat Vorrang. ' + note
            if temp and temp.get('value') is not None:
                tv = temp['value']
                target = float(consumer.get('target_temperature_c',20.0))
                note += f' Temperatur: {tv:.1f} °C (Ziel {target:.1f} °C).'
                if consumer.get('type') in ('heater','heat_pump') and tv >= target:
                    chosen = 0
                    note = f'Temperaturziel erreicht ({tv:.1f} °C); keine zusätzliche Heizempfehlung.'
            recommendations.append({
                'id': consumer.get('id'), 'name': consumer.get('name', 'Verbraucher'),
                'priority': int(consumer.get('priority', 99)), 'nominal_power_w': nominal,
                'suggested_power_w': chosen,
                'status': 'fits' if chosen > 0 else 'wait',
                'pressure_bar': pressure.get('value') if pressure else None,
                'temperature_c': temp.get('value') if temp else None,
                'note': note
            })
            remaining = max(0.0, remaining - chosen)
    return jsonify({
        'timestamp': snap.get('timestamp'), 'mode': 'advisory_only', 'commands_sent': False,
        'grid_import_sign': sign, 'grid_power_raw_w': raw, 'estimated_export_w': export_w,
        'safety_margin_w': margin_w, 'available_surplus_after_margin_w': available_w,
        'external_reserved_w': external_reserved_w,
        'recommendable_surplus_w': max(0.0, available_w-external_reserved_w) if available_w is not None else None,
        'recommendations': recommendations,
        'warning': ('Netzleistungs-Vorzeichen erst in der Konfiguration bestätigen.' if export_w is None else
                    'Nur Vorschlag: keine Verbraucher werden geschaltet. Vor dem Betrieb Anlaufstrom, Mindestlaufzeiten und Verriegelungen berücksichtigen.')
    })

@app.route('/api/compressor-analysis')
def api_compressor_analysis():
    """Estimate receiver pressure decay from stored samples; never claims a confirmed leak."""
    c=config(); now=time.time(); results=[]; snap=snapshot()
    try: rows=[json.loads(line) for line in HIST.read_text().splitlines()[-50000:] if line.strip()] if HIST.exists() else []
    except Exception: rows=[]
    for consumer in c.get('consumers',[]):
        if consumer.get('type')!='motor' or not consumer.get('pressure_sensor_entity') or not consumer.get('leak_monitor_enabled',True):
            continue
        cid=str(consumer.get('id','')); entity=consumer.get('pressure_sensor_entity')
        points=[]
        for row in rows:
            cv=row.get('consumer_values',{}).get(cid,{})
            val=cv.get('pressure_sensor_entity')
            try: ts=datetime.fromisoformat(row.get('timestamp','').replace('Z','+00:00')).timestamp(); p=float(val)
            except (TypeError,ValueError): continue
            if now-12*3600 <= ts <= now and 0 <= p <= 30: points.append((ts,p))
        points.sort()
        # Compare early and late medians over the last 12 hours; this is a screening estimate only.
        loss=None; rate=None; span=0
        if len(points)>=8:
            span=(points[-1][0]-points[0][0])/3600
            if span>=1:
                n=max(3,len(points)//5)
                drop=statistics.median(p for _,p in points[:n])-statistics.median(p for _,p in points[-n:])
                if drop>0:
                    rate=drop/span
                    volume=max(1,float(consumer.get('receiver_volume_l',500)))
                    loss=volume*rate # approximate free-air L/h, gauge pressure drop approximation
        current=(snap.get('consumer_values',{}).get(cid,{}) or {}).get('pressure_sensor_entity')
        results.append({'id':cid,'name':consumer.get('name','Kompressor'),'receiver_volume_l':consumer.get('receiver_volume_l',500),
            'pressure_bar':current.get('value') if current else None,'pressure_min_bar':consumer.get('pressure_min_bar',4.5),
            'compressor_on_bar':consumer.get('compressor_on_bar',6),'compressor_off_bar':consumer.get('compressor_off_bar',8),
            'pressure_drop_bar_per_hour':round(rate,3) if rate is not None else None,
            'estimated_air_loss_l_per_hour':round(loss,1) if loss is not None else None,
            'sample_span_hours':round(span,1),'samples':len(points),
            'status':'Verdacht auf Druckverlust' if loss is not None and loss>=max(20,volume*0.1) else ('Noch zu wenig Messdaten' if loss is None else 'Kein auffälliger Druckabfall erkannt'),
            'warning':'Schätzwert: Temperaturänderungen und unbemerkter Luftverbrauch können den Druckabfall erklären. Für aussagekräftige Messungen Kompressor-Aus-Zeiten und druckluftfreie Zeiträume berücksichtigen.'})
    return jsonify({'timestamp':datetime.now(timezone.utc).isoformat(),'results':results,'commands_sent':False})

@app.route('/api/battery-plan')
def api_battery_plan():
    rows=[]
    if HIST.exists():
        try: rows=[json.loads(x) for x in HIST.read_text().splitlines()[-100000:] if x.strip()]
        except Exception: rows=[]
    return jsonify(build_battery_plan(config(), rows, snapshot()))


@app.route('/api/peak-analysis')
def api_peak_analysis():
    """Advisory peak analysis with estimated excess energy; never extrapolates gaps."""
    c=config(); st=c.get('settings',{}); sign=st.get('grid_import_sign','unverified')
    target=max(0.0,float(st.get('peak_alert_w', st.get('grid_import_limit_w',5000))))
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
            if imp is not None:
                battery_raw=row.get('values',{}).get('battery_power')
                battery_sign=st.get('battery_power_sign','negative')
                if isinstance(battery_raw,(int,float)) and battery_sign in ('negative','positive'):
                    battery_discharge=max(0.0, -float(battery_raw) if battery_sign=='negative' else float(battery_raw))
                else: battery_discharge=None
                samples.append((ts,max(0.0,imp),battery_discharge))
        except Exception: continue
    samples.sort(); daily={}; over_count=0; max_gap=max(30,int(os.getenv('SAMPLE_INTERVAL_SECONDS','10'))*2)
    excess_kwh=peak_import_kwh=0.0; valid_intervals=0; events=[]; active=None
    for i,(ts,w,batt_w) in enumerate(samples):
        day=datetime.fromtimestamp(ts).astimezone().date().isoformat()
        d=daily.setdefault(day,{'peak_w':0,'samples_over_target':0,'estimated_minutes_over_target':0.0,'excess_energy_kwh':0.0})
        d['peak_w']=max(d['peak_w'],round(w))
        if w>target:
            over_count+=1; d['samples_over_target']+=1
            if active is None: active={'start':ts,'end':ts,'max_w':w,'excess_kwh':0.0,'import_kwh':0.0,'battery_offset_kwh':0.0,'battery_data_intervals':0,'samples':1}
            else: active['end']=ts; active['max_w']=max(active['max_w'],w); active['samples']+=1
        if i+1<len(samples):
            t2,w2,batt_w2=samples[i+1]; dt=t2-ts
            if 0<dt<=max_gap:
                valid_intervals+=1
                # Trapezoidal integration over the observed interval only.
                excess=max(0.0,w-target); excess2=max(0.0,w2-target)
                e=(excess+excess2)*0.5*dt/3600000.0
                if batt_w is not None and batt_w2 is not None:
                    offset=(min(excess,batt_w)+min(excess2,batt_w2))*0.5*dt/3600000.0
                else: offset=None
                imp_e=(w+w2)*0.5*dt/3600000.0 if (w>target or w2>target) else 0.0
                if w>target or w2>target:
                    excess_kwh+=e; peak_import_kwh+=imp_e
                    d['excess_energy_kwh']+=e
                    if active is not None:
                        active['excess_kwh']+=e; active['import_kwh']+=imp_e
                        if offset is not None:
                            active['battery_offset_kwh']+=offset; active['battery_data_intervals']+=1
                if active is not None and w2<=target and w<=target:
                    events.append(active); active=None
                elif active is not None and w2<=target:
                    active['end']=t2; events.append(active); active=None
            elif active is not None:
                # Do not bridge a data gap; end the event at the last known sample.
                events.append(active); active=None
    if active is not None: events.append(active)
    for d in daily.values(): d['excess_energy_kwh']=round(d['excess_energy_kwh'],3)
    for d in daily.values(): d['estimated_minutes_over_target']=round(d['samples_over_target']*max_gap/60.0,1)
    top_events=[]
    for e in sorted(events,key=lambda x:x['max_w'],reverse=True)[:20]:
        top_events.append({'start':datetime.fromtimestamp(e['start']).astimezone().isoformat(timespec='minutes'),
          'end':datetime.fromtimestamp(e['end']).astimezone().isoformat(timespec='minutes'),
          'duration_min':round(max(0,e['end']-e['start'])/60,1),'max_w':round(e['max_w']),
          'excess_energy_kwh':round(e['excess_kwh'],3),'grid_import_energy_kwh_during_event':round(e['import_kwh'],3),'estimated_peak_reduction_if_battery_discharge_was_available_kwh':round(e['battery_offset_kwh'],3),'battery_data_intervals':e['battery_data_intervals'],'samples':e['samples']})
    return jsonify({'mode':'advisory_only','commands_sent':False,'target_w':target,'sign':sign,'days_requested':days,
      'valid_samples':len(samples),'valid_intervals':valid_intervals,'samples_over_target':over_count,
      'estimated_excess_energy_kwh':round(excess_kwh,3),'estimated_grid_import_energy_during_peak_intervals_kwh':round(peak_import_kwh,3),
      'estimated_peak_reduction_if_battery_discharge_was_available_kwh':round(sum(e['battery_offset_kwh'] for e in events),3),
      'battery_data_coverage_intervals':sum(e['battery_data_intervals'] for e in events),
      'peak_events_count':len(events),'top_peak_events':top_events,'daily':daily,
      'warning':'Energie ist aus benachbarten Messpunkten trapezförmig geschätzt; Zeitlücken werden nicht überbrückt. Importenergie während Peak-Intervallen ist nicht gleich vermeidbare Energie. Netz-Vorzeichen prüfen.' if sign in ('negative','positive') else 'Netzleistungs-Vorzeichen zuerst in der Konfiguration bestätigen.'})


def economic_assessment(import_price_eur_kwh, export_price_eur_kwh, roundtrip_efficiency=0.90):
    """Marginal value of using stored battery energy instead of exporting it.
    Advisory only; efficiency is a user-configured estimate, not a measured value.
    """
    buy=max(0.0,min(5.0,float(import_price_eur_kwh)))
    sell=max(0.0,min(5.0,float(export_price_eur_kwh)))
    eta=max(0.50,min(1.0,float(roundtrip_efficiency)))
    export_opportunity_cost=sell/eta
    net=buy-export_opportunity_cost
    return {'import_price_eur_kwh':round(buy,4),'export_price_eur_kwh':round(sell,4),
            'roundtrip_efficiency':eta,'export_opportunity_cost_eur_per_delivered_kwh':round(export_opportunity_cost,4),
            'net_benefit_eur_per_delivered_kwh':round(net,4),
            'net_benefit_cent_per_delivered_kwh':round(net*100,2),
            'recommendation':'Speichern und später selbst nutzen ist preislich vorteilhaft (ohne Alterungskosten).' if net>0.005 else ('Einspeisen ist preislich mindestens gleichwertig; Speicherverluste sprechen eher gegen Laden nur für späteren Eigenverbrauch.' if net < -0.005 else 'Beide Wege sind preislich ungefähr gleichwertig; Verluste und Alterung beachten.'),
            'advisory_only':True}

def active_tariff(settings, current_month=None):
    """Choose the latest saved tariff whose effective month is not in the future."""
    month = current_month or datetime.now().strftime('%Y-%m')
    history = settings.get('tariff_history', [])
    eligible = [x for x in history if isinstance(x, dict) and isinstance(x.get('month'), str) and len(x['month']) == 7 and x['month'] <= month]
    if eligible:
        chosen = max(eligible, key=lambda x: x['month'])
        return {'month': chosen['month'], 'import_price_eur_kwh': float(chosen.get('import_price_eur_kwh', settings.get('import_price_eur_kwh', 0.30))), 'export_price_eur_kwh': float(chosen.get('export_price_eur_kwh', settings.get('export_price_eur_kwh', 0.04))), 'source': 'history'}
    return {'month': settings.get('tariff_effective_month') or '', 'import_price_eur_kwh': float(settings.get('import_price_eur_kwh', 0.30)), 'export_price_eur_kwh': float(settings.get('export_price_eur_kwh', 0.04)), 'source': 'current_settings'}

@app.route('/economics')
def economics_page():
    c=config(); st=c.get('settings',{}); tariff=active_tariff(st)
    assessment=economic_assessment(tariff['import_price_eur_kwh'],tariff['export_price_eur_kwh'],st.get('battery_roundtrip_efficiency',0.90))
    return render_template('economics.html',cfg=c,assessment=assessment,history=st.get('tariff_history',[]),tariff=tariff)

@app.route('/api/economic-assessment')
def api_economic_assessment():
    st=config().get('settings',{}); tariff=active_tariff(st)
    result=economic_assessment(tariff['import_price_eur_kwh'],tariff['export_price_eur_kwh'],st.get('battery_roundtrip_efficiency',0.90))
    result['applied_tariff_month']=tariff['month']; result['tariff_source']=tariff['source']
    return jsonify(result)

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
            if prev is not None and ts-prev>max(60, int(os.getenv('SAMPLE_INTERVAL_SECONDS','10'))*4): gaps+=1
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
            if event_start is None or event_last is None or ts-event_last>max(60,int(os.getenv('SAMPLE_INTERVAL_SECONDS','10'))*4):
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



@app.route('/api/night-plan')
def api_night_plan():
    """Advisory-only overnight strategy; never requests charging or inverter control."""
    c = config()
    rows = learning_rows()
    snap = snapshot()
    plan = build_battery_plan(c, rows, snap)
    values = (snap or {}).get('values', {})
    soc_item = values.get('battery_soc') or {}
    try:
        soc = float(soc_item.get('value'))
    except (TypeError, ValueError):
        soc = None
    st = c.get('settings', {})
    capacity = max(0.0, float(st.get('battery_capacity_kwh', 80)))
    reserve_kwh = plan.get('recommended_morning_reserve_kwh')
    current_kwh = capacity * max(0.0, min(100.0, soc)) / 100.0 if soc is not None else None
    gap_kwh = max(0.0, float(reserve_kwh) - current_kwh) if reserve_kwh is not None and current_kwh is not None else None
    import_price = max(0.0, float(st.get('import_price_eur_kwh', 0.30)))
    export_price = max(0.0, float(st.get('export_price_eur_kwh', 0.04)))
    # Estimate overnight battery discharge from historical battery_power readings,
    # not from house load. Normalize sign so positive means discharge. Use per-day
    # medians per 15-minute slot and require at least 3 separate days per slot.
    st = c.get('settings', {})
    learned_days = max(1, int(st.get('learning_days', 14)))
    cutoff = datetime.now(timezone.utc).timestamp() - learned_days * 86400
    morning_start = max(0, min(23, int(st.get('morning_start_hour', 5))))
    sign = st.get('battery_power_sign', 'negative')
    slot_days = {}
    for row in rows:
        try:
            ts = datetime.fromisoformat(row.get('timestamp', '').replace('Z', '+00:00')).timestamp()
            if ts < cutoff:
                continue
            raw = row.get('values', {}).get('battery_power')
            if not isinstance(raw, (int, float)) or abs(raw) > 100000:
                continue
            dt = datetime.fromtimestamp(ts).astimezone()
            if not (0 <= dt.hour < morning_start):
                continue
            discharge_w = max(0.0, -float(raw) if sign == 'negative' else float(raw))
            slot = dt.hour * 60 + (dt.minute // 15) * 15
            slot_days.setdefault(slot, {}).setdefault(dt.date().isoformat(), []).append(discharge_w)
        except (ValueError, TypeError, OverflowError):
            continue
    discharge_slots = []
    for slot, by_day in slot_days.items():
        if len(by_day) < 3:
            continue
        daily_medians = [statistics.median(samples) for samples in by_day.values() if samples]
        if daily_medians:
            discharge_slots.append({'median_w': statistics.median(daily_medians), 'days_seen': len(daily_medians)})
    night_discharge_kwh = sum(max(0.0, p['median_w']) * 0.25 / 1000.0 for p in discharge_slots)
    night_confidence = ('hoch' if discharge_slots and min(p['days_seen'] for p in discharge_slots) >= 7
                        else 'mittel' if discharge_slots and min(p['days_seen'] for p in discharge_slots) >= 5
                        else 'vorläufig' if discharge_slots else 'keine')
    estimated_night_end_kwh = max(0.0, current_kwh - night_discharge_kwh) if current_kwh is not None and discharge_slots else None
    reserve_gap_after_night_kwh = max(0.0, float(reserve_kwh) - estimated_night_end_kwh) if reserve_kwh is not None and estimated_night_end_kwh is not None else None
    charge_efficiency=max(0.5,min(1.0,float(st.get('battery_roundtrip_efficiency',0.90) or 0.90)))
    recommended_grid_purchase_kwh=(reserve_gap_after_night_kwh/charge_efficiency
                                   if reserve_gap_after_night_kwh is not None else None)
    # A simple cost comparison is intentionally only indicative: without a time-of-use
    # tariff and measured round-trip efficiency, it cannot prove a grid purchase is cheaper.
    indicative_grid_cost = recommended_grid_purchase_kwh * import_price if recommended_grid_purchase_kwh is not None else None
    indicative_export_value = reserve_gap_after_night_kwh * export_price if reserve_gap_after_night_kwh is not None else None
    if gap_kwh is None:
        status = 'nicht_bewertbar'
        recommendation = 'Keine belastbare Empfehlung: SoC oder Morgenreserve fehlt. Vorzeichen und Messdaten prüfen.'
    elif reserve_gap_after_night_kwh is not None and reserve_gap_after_night_kwh <= 0.25:
        status = 'kein_zukauf_erforderlich'
        recommendation = 'Unter Berücksichtigung der gelernten typischen Nachtentladung bleibt voraussichtlich genügend Energie für die Morgenreserve. Kein zusätzlicher Netzbezug empfohlen.'
    elif reserve_gap_after_night_kwh is not None:
        status = 'nachtreserve_luecke'
        recommendation = (f'Bei Fortsetzung der gelernten Nachtentladung könnten bis zum Morgen etwa {reserve_gap_after_night_kwh:.1f} kWh zur Reserve fehlen. '
                          'Zuerst prüfen, ob die Nachtentladung sinkt oder lokal begrenzt werden kann. Netzbezug nur erwägen, wenn die Reserve wichtig ist und der Tarifvergleich inklusive Speicherverlusten dafür spricht.')
    else:
        status = 'nachtentladung_unbekannt'
        recommendation = 'Die Nachtentladung kann aus den vorhandenen Batterieleistungsdaten nicht zuverlässig geschätzt werden. Messhistorie und Vorzeichen-Einstellung prüfen; keine Reserveprognose ableiten.'
    night_consumers=[]
    for consumer in c.get('consumers',[]):
        if not consumer.get('enabled'): continue
        cv=(snap.get('consumer_values',{}).get(str(consumer.get('id','')),{}) or {})
        state=(cv.get('compressor_state_entity') or {}).get('state')
        external=consumer.get('management_mode')=='external'
        night_consumers.append({'name':consumer.get('name','Verbraucher'),'nominal_power_w':int(consumer.get('nominal_power_w',0) or 0),
            'management':'Home-Assistant-Automation' if external else 'Nur berücksichtigen',
            'state':state or 'unbekannt','future_switch_time':None,
            'note':('Derzeit von deiner HA-Automation geregelt; eine zukünftige Schaltzeit ist für die Energiezentrale nicht sichtbar.' if external else 'Keine automatische Schaltung eingerichtet.')})
    morning_start=max(0,min(23,int(st.get('morning_start_hour',5))))
    next_morning=datetime.now().astimezone().replace(hour=morning_start,minute=0,second=0,microsecond=0)
    if next_morning<=datetime.now().astimezone(): next_morning+=timedelta(days=1)
    morning_label=('Morgen ' if next_morning.date()!=datetime.now().astimezone().date() else 'Heute ')+next_morning.strftime('%H:%M')
    raw_grid=(values.get('grid_power') or {}).get('value')
    grid_sign=st.get('grid_import_sign','unverified')
    grid_import_w=(-float(raw_grid) if grid_sign=='negative' else float(raw_grid) if grid_sign=='positive' else None) if isinstance(raw_grid,(int,float)) else None
    return jsonify({'mode':'advisory_only','commands_sent':False,'status':status,
        'battery_soc_percent':soc,'current_battery_energy_kwh':round(current_kwh,2) if current_kwh is not None else None,
        'pv_power_w':(values.get('pv_power') or {}).get('value'),'load_power_w':(values.get('load_power') or {}).get('value'),
        'grid_import_w':round(grid_import_w) if grid_import_w is not None else None,
        'recommended_morning_reserve_kwh':reserve_kwh,'reserve_gap_kwh':round(gap_kwh,2) if gap_kwh is not None else None,
        'recommended_morning_soc_percent':plan.get('recommended_morning_soc_percent'),
        'learned_night_battery_discharge_slots':len(discharge_slots),'learned_night_battery_discharge_estimate_kwh':round(night_discharge_kwh,2),
        'learned_night_confidence':night_confidence,
        'estimated_battery_energy_at_morning_kwh':round(estimated_night_end_kwh,2) if estimated_night_end_kwh is not None else None,
        'estimated_battery_soc_at_morning_percent':round(estimated_night_end_kwh/capacity*100,1) if estimated_night_end_kwh is not None and capacity>0 else None,
        'estimated_reserve_gap_after_night_kwh':round(reserve_gap_after_night_kwh,2) if reserve_gap_after_night_kwh is not None else None,
        'recommended_grid_purchase_kwh':round(recommended_grid_purchase_kwh,2) if recommended_grid_purchase_kwh is not None else None,
        'suggested_grid_purchase_before':f'{morning_start:02d}:00' if reserve_gap_after_night_kwh is not None and reserve_gap_after_night_kwh>0.25 else None,
        'morning_start':f'{morning_start:02d}:00','morning_start_label':morning_label,'grid_import_sign':grid_sign,'consumers':night_consumers,
        'indicative_grid_cost_eur':round(indicative_grid_cost,2) if indicative_grid_cost is not None else None,
        'indicative_export_value_eur':round(indicative_export_value,2) if indicative_export_value is not None else None,
        'import_price_eur_kwh':import_price,'export_price_eur_kwh':export_price,
        'recommendation':recommendation,
        'limitations':['Keine automatische Netzladung und keine Wechselrichtersteuerung.',
          'Die Nachtentladung wird aus historischen Batterieleistungswerten geschätzt; nur Zeitfenster mit mindestens drei Messtagen werden verwendet.',
          'Bei fehlenden oder falsch konfigurierten Batterie-Vorzeichen ist keine belastbare Nachtentladungsschätzung möglich.',
          'Preisvergleich berücksichtigt hier noch keine vollständigen Umwandlungsverluste oder zeitabhängigen Tarife.']})


@app.route('/health')
def health():return jsonify({'status':'ok','mode':'active_control' if CONTROL_RUNTIME.get('active') else 'observe','active_control_enabled':bool(CONTROL_RUNTIME.get('active')),'timestamp':datetime.now(timezone.utc).isoformat()})
if __name__=='__main__':
 threading.Thread(target=sampler,daemon=True).start();threading.Thread(target=model_learning_loop,daemon=True).start();threading.Thread(target=controller_loop,daemon=True).start();app.run(host='0.0.0.0',port=int(os.getenv('PORT','8099')))
