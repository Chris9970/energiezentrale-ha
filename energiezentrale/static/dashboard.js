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
      $('grid-purchase').innerHTML=fmt(d.recommended_grid_purchase_kwh,2)+'<small> kWh</small>';
      $('grid-purchase-time').textContent=d.suggested_grid_purchase_before?'Reserve vorsorglich sichern vor '+d.suggested_grid_purchase_before:'Kein Zukauf vor dem Morgen prognostiziert';
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
      if(num(d.recommended_grid_purchase_kwh)!==null&&Number(d.recommended_grid_purchase_kwh)>0.25){
        addTimeline(timeline,'vor '+(d.suggested_grid_purchase_before||morning),'Möglicher Netzzukauf '+fmt(d.recommended_grid_purchase_kwh,2)+' kWh',
          'Das wäre nötig, um die geschätzte Morgenreserve inklusive Ladeverlusten zu erreichen. Die App kauft nicht selbst ein; ohne zeitabhängigen Tarif lässt sich keine günstigste Uhrzeit bestimmen.','timeline-action');
      }else if(d.status==='kein_zukauf_erforderlich'){
        addTimeline(timeline,'vor '+morning,'Kein zusätzlicher Zukauf empfohlen',
          'Die gelernte Nachtentladung lässt voraussichtlich genügend Energie für das Morgen-Ziel.');
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
  refreshLive();refreshPlan();setInterval(refreshLive,10000);setInterval(refreshPlan,300000);
})();
