(() => {
  const $ = id => document.getElementById(id);
  const fmt = (x, digits=1) => x===null || x===undefined || !Number.isFinite(Number(x)) ? '–' : Number(x).toLocaleString('de-AT',{maximumFractionDigits:digits});
  const num = x => x===null || x===undefined || !Number.isFinite(Number(x)) ? null : Number(x);
  const status=$('live-status');
  async function refreshLive(){
    try{
      const r=await fetch('./api/snapshot',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);
      const d=await r.json(),v=d.values||{};
      const soc=num(v.battery_soc?.value);
      $('live-battery_soc').innerHTML=fmt(soc,1)+'<small> %</small>';
      if(soc!==null)$('soc-fill').style.width=Math.max(0,Math.min(100,soc))+'%';
      $('live-updated').textContent='Aktualisiert '+new Date(d.timestamp).toLocaleTimeString('de-AT');
      status.textContent=d.ha_error?'● Verbindung gestört':'● Live · '+new Date(d.timestamp).toLocaleTimeString('de-AT');
      status.classList.toggle('status-error',!!d.ha_error);
      $('live-pv').innerHTML=fmt(num(v.pv_power?.value),0)+' <small>W</small>';
      $('live-load').innerHTML=fmt(num(v.load_power?.value),0)+' <small>W</small>';
      const raw=num(v.grid_power?.value);$('live-grid').innerHTML=fmt(raw,0)+' <small>W · Sensorsignal</small>';
      const pv=num(v.pv_power?.value), load=num(v.load_power?.value), batt=num(v.battery_power?.value), signs=d.signs||{};
      const gridImport=raw===null||!['positive','negative'].includes(signs.grid_import_sign)?null:raw*(signs.grid_import_sign==='negative'?-1:1);
      const discharge=batt===null?null:batt*(signs.battery_power_sign==='negative'?-1:1);
      const charging=discharge!==null&&discharge < -100, discharging=discharge!==null&&discharge > 100;
      const setFlow=(id,on,reverse=false,power=0)=>{const el=$(id);if(!el)return;el.classList.toggle('active',!!on);el.classList.toggle('reverse',!!on&&!!reverse);el.style.strokeWidth=String(2+Math.min(1,Math.max(0,power)/30000)*5);el.style.animationDuration=Math.max(.7,3-Math.max(0,power)/15000)+'s';};
      setFlow('flow-pv-home',pv!==null&&pv>50&&load!==null&&load>50,false,pv||0);
      setFlow('flow-pv-battery',pv!==null&&pv>50&&charging,false,Math.max(0,pv-(load||0)));
      const batteryPath=$('flow-battery-home');setFlow('flow-battery-home',charging||discharging,charging,Math.abs(discharge||0));
      if(batteryPath){batteryPath.removeAttribute('marker-start');batteryPath.removeAttribute('marker-end');if(discharging)batteryPath.setAttribute('marker-end','url(#arrow-battery)');if(charging)batteryPath.setAttribute('marker-start','url(#arrow-battery)');}
      setFlow('flow-grid-import',gridImport!==null&&gridImport>50,false,gridImport||0);setFlow('flow-grid-export',gridImport!==null&&gridImport< -50,false,gridImport===null?0:-gridImport);
      $('flow-pv-value').textContent=fmt(pv,0)+' W';$('flow-load-value').textContent=fmt(load,0)+' W';
      const battKw=Math.abs(discharge||0)>=1000?fmt(Math.abs(discharge||0)/1000,1)+' kW':fmt(Math.abs(discharge||0),0)+' W';
      $('flow-battery-value').textContent=(charging?'Lädt ':discharging?'Entlädt ':'')+battKw+' · '+fmt(soc,0)+'%';
      const gridKw=gridImport===null?null:Math.abs(gridImport)>=1000?fmt(Math.abs(gridImport)/1000,1)+' kW':fmt(Math.abs(gridImport),0)+' W';
      $('flow-grid-value').textContent=gridImport===null?'Vorzeichen ungeprüft':gridImport>50?gridKw+' Bezug':gridImport< -50?gridKw+' Einspeisung':'Nahe 0 W';
      $('flow-updated').textContent='Live · '+new Date(d.timestamp).toLocaleTimeString('de-AT');
    }catch(e){status.textContent='● Live-Daten nicht erreichbar';status.classList.add('status-error');}
  }
  function addTimeline(list,time,title,description,kind=''){
    const li=document.createElement('li');if(kind)li.className=kind;
    const t=document.createElement('time');t.textContent=time;
    const wrap=document.createElement('div');const b=document.createElement('b');b.textContent=title;
    const p=document.createElement('p');p.textContent=description;wrap.append(b,p);li.append(t,wrap);list.append(li);
  }
  async function refreshPlan(){
    try{
      const r=await fetch('./api/night-plan',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);
      const d=await r.json();
      $('night-soc').innerHTML=fmt(d.estimated_battery_soc_at_morning_percent,1)+'<small> %</small>';
      $('morning-target').innerHTML=fmt(d.recommended_morning_soc_percent,0)+'<small> % SoC</small>';
      const confidence=d.learned_night_confidence||'keine';
      const strategy=d.learned_strategy||{};
      $('night-confidence').textContent=(d.learned_night_battery_discharge_slots>0?'Nachtprofil '+fmt(d.learned_night_profile_coverage_percent,0)+' % vollständig · Vertrauen '+confidence:'Zu wenig Nachtverlauf für eine SoC-Prognose')+' · '+(strategy.status||'Lernmodell wartet');
      $('grid-purchase').innerHTML=fmt(d.estimated_reserve_gap_after_night_kwh,2)+'<small> kWh</small>';
      $('grid-purchase-time').textContent=d.suggested_grid_purchase_before?'Morgen-Ziel voraussichtlich ab '+d.suggested_grid_purchase_before+' unterschritten · kein Ladebefehl':'Keine Lücke zum strategischen Morgen-Ziel prognostiziert';
      $('night-explanation').textContent=(d.recommendation||'Keine Nachtplanung verfügbar.')+' Grundlage: '+(d.selected_strategy||'historische Lernwerte')+'.';
      const timeline=$('night-timeline');timeline.replaceChildren();
      const now=new Date().toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'});
      const current=d.battery_soc_percent;
      addTimeline(timeline,now,'Jetzt · Speicherstand '+(current===null?'unbekannt':fmt(current,1)+' %'),
        d.current_battery_energy_kwh===null?'Batterie-SoC oder Speicherkapazität fehlt.':fmt(d.current_battery_energy_kwh,1)+' kWh gespeicherte Energie laut konfigurierter Kapazität.');
      const morning=d.morning_start_label||('Morgen '+(d.morning_start||'05:00'));
      if(d.night_start_label)addTimeline(timeline,d.night_start_label,'Gelernter Nachtplan startet','Ab hier wird die typische Entladung aus historischen 15-Minuten-Zeitfenstern geschätzt.');
      (d.night_forecast_slots||[]).filter((x,i,a)=>x.time.endsWith(':00')||i===a.length-1).forEach(x=>{
        if(x.expected_soc_after_percent!==null)addTimeline(timeline,x.time,'Prognose · '+fmt(x.expected_soc_after_percent,1)+' % SoC',fmt(x.expected_discharge_w,0)+' W typische Entladung · '+x.days_seen+' Messtage.');
      });
      if(d.estimated_battery_soc_at_morning_percent!==null&&d.estimated_battery_soc_at_morning_percent!==undefined){
        addTimeline(timeline,'bis '+morning,'Erwarteter Morgenstand '+fmt(d.estimated_battery_soc_at_morning_percent,1)+' %',
          'Noch erwartete Nachtentladung: '+fmt(d.expected_remaining_night_discharge_kwh,2)+' kWh; Vertrauen: '+confidence+'.');
      }else{
        addTimeline(timeline,'bis '+morning,'Morgen-SoC noch nicht berechenbar',
          'Für genügend Nachtmessungen mit bestätigtem Batterie-Vorzeichen fehlen noch Daten.');
      }
      if(num(d.estimated_reserve_gap_after_night_kwh)!==null&&Number(d.estimated_reserve_gap_after_night_kwh)>0.25){
        addTimeline(timeline,'ab '+(d.suggested_grid_purchase_before||morning),'Mögliche Lücke zum Morgen-Ziel '+fmt(d.estimated_reserve_gap_after_night_kwh,2)+' kWh',
          'Die Batterieprognose läuft bis zur Hardware-Untergrenze von '+fmt(d.hardware_min_soc_percent,0)+' %. Danach versorgt Netzstrom den Hausverbrauch direkt. Die Lücke zum höheren strategischen Ziel ist nur ein Hinweis; es wird keine Batterie-Netzladung angefordert.','timeline-action');
      }else if(d.status==='morgenreserve_erreichbar'){
        addTimeline(timeline,'bis '+morning,'Morgen-Ziel voraussichtlich erreichbar',
          'Die gelernte Nachtentladung lässt voraussichtlich genügend Energie für das strategische Morgen-Ziel. Die Hardware-Untergrenze bleibt bei '+fmt(d.hardware_min_soc_percent,0)+' %.');
      }else{
        addTimeline(timeline,'vor '+morning,'Netzzukauf noch offen',
          'Die Daten reichen noch nicht für eine belastbare Schätzung, ob und wann Netzstrom zugekauft werden sollte.');
      }
      const consumers=$('night-consumers');consumers.replaceChildren();
      if(!(d.consumers||[]).length){const p=document.createElement('p');p.className='hint';p.textContent='Keine aktivierten Verbraucher für den Plan eingetragen.';consumers.append(p);}
      (d.consumers||[]).forEach(c=>{
        const row=document.createElement('div');row.className='line';
        const left=document.createElement('span');const b=document.createElement('b');b.textContent=c.name;
        const small=document.createElement('small');small.textContent=c.nominal_power_w+' W · '+c.management;left.append(b,small);
        const right=document.createElement('span');right.className='tag';right.textContent=c.state==='on'?'Läuft':c.state==='off'?'Aus':c.state;
        row.append(left,right);const note=document.createElement('p');note.className='hint';note.textContent=c.note;consumers.append(row,note);
      });
    }catch(e){$('night-explanation').textContent='Nachtplan derzeit nicht verfügbar: '+e.message;}
  }
  function svgEl(name,attrs={}){const el=document.createElementNS('http://www.w3.org/2000/svg',name);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));return el;}
  function renderDayPlanChart(steps){
    const svg=$('day-plan-chart');svg.replaceChildren();
    if(!steps.length){const t=svgEl('text',{x:480,y:125,'text-anchor':'middle',fill:'#8da0af'});t.textContent='Noch keine berechenbaren 15-Minuten-Schritte';svg.append(t);return;}
    const left=52,right=20,top=24,socBottom=174,barsTop=204,barsBottom=238,width=960,leftX=left,rightX=width-right;
    [20,40,60,80,100].forEach(v=>{const y=socBottom-(v/100)*(socBottom-top);svg.append(svgEl('line',{x1:leftX,y1:y,x2:rightX,y2:y,stroke:'#263746','stroke-width':1}));const label=svgEl('text',{x:8,y:y+4,fill:'#8da0af','font-size':11});label.textContent=v+'%';svg.append(label)});
    const maxBar=Math.max(1000,...steps.map(x=>Number(x.grid_import_w)||0),...steps.map(x=>Number(x.planned_consumer_w)||0));
    const slotWidth=(rightX-leftX)/Math.max(steps.length,1);const socY=v=>socBottom-(Math.max(0,Math.min(100,Number(v)||0))/100)*(socBottom-top);
    let d='';steps.forEach((x,i)=>{const px=leftX+slotWidth*(i+.5),py=socY(x.soc_percent);d+=(i?' L ':'M ')+px.toFixed(1)+' '+py.toFixed(1);
      const g=Math.max(0,Number(x.grid_import_w)||0),c=Math.max(0,Number(x.planned_consumer_w)||0),bar=Math.max(1,slotWidth*.55);
      if(g>25){const h=Math.max(2,g/maxBar*(barsBottom-barsTop));svg.append(svgEl('rect',{x:px-bar/2,y:barsBottom-h,width:bar,height:h,rx:2,fill:'#39d5a0',opacity:.78}));}
      if(c>25){const h=Math.max(2,c/maxBar*(barsBottom-barsTop));svg.append(svgEl('rect',{x:px-bar/2,y:barsTop,width:bar,height:h,rx:2,fill:'#f6bd4b',opacity:.82}));}
    });
    svg.append(svgEl('path',{d,fill:'none',stroke:'#bd91ff','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'}));
    const count=Math.min(5,steps.length);for(let i=0;i<count;i++){const idx=Math.round(i*(steps.length-1)/Math.max(1,count-1)),x=steps[idx],label=svgEl('text',{x:leftX+slotWidth*(idx+.5),y:255,'text-anchor':'middle',fill:'#8da0af','font-size':11});label.textContent=new Date(x.time).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'});svg.append(label);}
    const b1=svgEl('text',{x:leftX,y:195,fill:'#8da0af','font-size':10});b1.textContent='Netzbezug / Zusatzverbrauch';svg.append(b1);
  }
  async function refreshDayPlan(){
    try{
      const r=await fetch('./api/day-plan',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);
      const d=await r.json(),steps=d.steps||[],timeline=$('day-plan-timeline');
      $('day-plan-title').textContent=d.phase==='night'?'Nachtplan bis zum Morgen':'Optimierter Ablauf bis zum Abend';
      $('day-plan-status').textContent=(d.status||'Plan')+' · '+(d.phase==='night'?'Nacht':'bis '+(d.charge_deadline?new Date(d.charge_deadline).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'}):'morgen'));
      $('plan-end-soc').innerHTML=fmt(d.predicted_soc_at_deadline_percent,1)+'<small> %</small>';
      $('plan-end-label').textContent=d.charge_deadline?'Prognose zur Abendfrist '+new Date(d.charge_deadline).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'}):'Prognose bis '+new Date(d.horizon_end).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'});
      $('plan-grid-kwh').innerHTML=fmt(d.expected_grid_import_kwh,2)+'<small> kWh</small>';
      $('plan-pv-kwh').innerHTML=fmt(d.forecast_remaining_kwh,1)+'<small> kWh</small>';
      $('plan-forecast-source').textContent=(d.forecast_source||'Keine PV-Prognose')+(d.profile_days?' · '+d.profile_days+' Profil-Tage':'');
      $('plan-priority').textContent=d.phase==='night'?'Batterie bis Hardware-Minimum':d.battery_target_reachable?'Vollladung voraussichtlich erreichbar':'Speicher zuerst · Stufen gesperrt';
      $('day-plan-explanation').textContent=d.phase==='night'?'Nachtprognose bis zum Morgen. Erwarteter Netzbezug versorgt den Hausverbrauch erst, wenn die Batterie ihre Hardware-Untergrenze erreicht; Netzladung ist nicht eingeplant. '+(d.notes||[]).join(' '):(d.battery_target_reachable?'Der prognostizierte PV-Ertrag reicht voraussichtlich, um bis zur Abendfrist mindestens 98,5 % zu erreichen.':'Die Batterie-only-Rechnung erreicht das Abendziel voraussichtlich nicht; geplante Zusatzverbraucher bleiben gesperrt.')+' '+(d.notes||[]).join(' ');
      renderDayPlanChart(steps);timeline.replaceChildren();
      if(!steps.length){addTimeline(timeline,'jetzt','Kein Plan berechenbar',(d.status||'SoC oder Zeitplan fehlt')+'. Sensoren, PV-Prognose und Datenalter prüfen.','timeline-action');return;}
      const endTime=d.charge_deadline||d.horizon_end;
      addTimeline(timeline,'bis '+new Date(endTime).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'}),d.phase==='night'?'Erwarteter Morgenstand':d.battery_target_reachable?'Batterieziel voraussichtlich erreichbar':'Speicherziel voraussichtlich nicht erreichbar',
        'Prognose '+fmt(d.predicted_soc_at_deadline_percent,1)+' % SoC; Hardware-Untergrenze '+fmt(d.hard_min_soc_percent,0)+' %. '+(d.forecast_source||''),d.battery_target_reachable?'':'timeline-action');
      (d.consumer_windows||[]).forEach(x=>addTimeline(new Date(x.start).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'}),x.name+' · '+fmt(x.power_w,0)+' W',
        'Mögliches Überschussfenster bis '+new Date(x.end).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'})+' · angenommene Laufzeit '+x.duration_minutes+' min · '+(x.management==='external'?'HA-Automation':'nur Vorschlag')+'. '+(x.reason||'')+' Kein zukünftiger Impuls wird vorgemerkt.','timeline-action'));
      let importStart=null,importWMinutes=0,importMinutes=0,importEnergy=0,lastEnd=null;
      const finishImport=()=>{if(importStart){addTimeline(new Date(importStart).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'}),'Möglicher Netzbezug · '+fmt(importEnergy,2)+' kWh',
        'Prognostizierter Mittelwert '+fmt(importWMinutes/Math.max(1,importMinutes),0)+' W bis '+new Date(lastEnd).toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'})+'; deckt den Hausverbrauch nach Erreichen der Speicher-Untergrenze. Keine Netzladung.','timeline-action');importStart=null;importWMinutes=0;importMinutes=0;importEnergy=0;}};
      steps.forEach(x=>{const imp=Number(x.grid_import_w)||0,minutes=Number(x.minutes)||15;if(imp>100){if(!importStart)importStart=x.time;importWMinutes+=imp*minutes;importMinutes+=minutes;importEnergy+=imp*minutes/60000;lastEnd=new Date(new Date(x.time).getTime()+minutes*60000).toISOString();}else finishImport();});finishImport();
      if(!(d.consumer_windows||[]).length)addTimeline('PV-Fenster','Kein Zusatzverbrauch geplant',d.phase==='night'?'Nachtphase: nur Batterie- und Netzversorgung wird prognostiziert.':d.battery_target_reachable?'Kein stabil passender Verbraucher-Schritt im aktuellen Planfenster.':'Der Speicher braucht die prognostizierte Energie zuerst.');
    }catch(e){$('day-plan-status').textContent='Plan nicht verfügbar';$('day-plan-explanation').textContent='Schattenplan konnte nicht geladen werden: '+e.message;}
  }
  refreshLive();refreshPlan();refreshDayPlan();setInterval(refreshLive,10000);setInterval(refreshPlan,300000);setInterval(refreshDayPlan,300000);
})();
