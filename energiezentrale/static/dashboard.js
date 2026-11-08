(() => {
  const chart = document.getElementById('power-chart');
  if (!chart) return;
  const ctx = chart.getContext('2d');
  const keys = ['pv_power', 'load_power', 'grid_power', 'battery_power'];
  const palette = {
    pv:{color:'#ffd34e',dash:[]},
    load:{color:'#42a5ff',dash:[9,4]},
    grid:{color:'#27e0a0',dash:[3,3]},
    battery:{color:'#d28cff',dash:[10,3,2,3]}
  };
  const points = [];
  const maxPoints = 360;
  const status = document.getElementById('live-status');
  const number = value => Number.isFinite(Number(value)) ? Number(value) : null;
  const fmt = (value, digits=0) => value === null ? '–' : value.toLocaleString('de-AT', {maximumFractionDigits:digits});

  function draw() {
    const rect = chart.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    chart.width = Math.max(320, rect.width * ratio);
    chart.height = Math.max(180, rect.height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const w = rect.width, h = rect.height, pad = {l:48,r:12,t:12,b:26};
    ctx.clearRect(0,0,w,h);
    if (points.length < 2) { ctx.fillStyle='#8da0af'; ctx.fillText('Messwerte für den Verlauf werden gesammelt …', 15, 28); return; }
    const series = keys.map(k => points.map(p => p[k]).filter(v => v !== null));
    const maxAbs = Math.max(1000, ...series.flat().map(v => Math.abs(v)));
    const bound = Math.ceil(maxAbs / 1000) * 1000;
    const x0=pad.l, x1=w-pad.r, y0=pad.t, y1=h-pad.b;
    const y = v => y0 + (bound-v)/(2*bound)*(y1-y0);
    ctx.font='10px system-ui'; ctx.lineWidth=1; ctx.strokeStyle='#263746'; ctx.fillStyle='#8da0af';
    for(let i=0;i<=4;i++){const v=bound-i*bound/2, yy=y(v);ctx.beginPath();ctx.moveTo(x0,yy);ctx.lineTo(x1,yy);ctx.stroke();ctx.fillText((v/1000).toFixed(0)+'k',4,yy+3);}
    const zero=y(0);ctx.strokeStyle='#607483';ctx.beginPath();ctx.moveTo(x0,zero);ctx.lineTo(x1,zero);ctx.stroke();
    keys.forEach(k=>{
      const style=palette[k];ctx.save();ctx.beginPath();ctx.globalAlpha=1;ctx.strokeStyle=style.color;
      ctx.lineWidth=2.8;ctx.lineCap='round';ctx.lineJoin='round';ctx.setLineDash(style.dash);let started=false;
      points.forEach((p,i)=>{const v=p[k];if(v===null){started=false;return;}const xx=x0+i/(points.length-1)*(x1-x0), yy=y(v);if(!started){ctx.moveTo(xx,yy);started=true;}else ctx.lineTo(xx,yy);});
      ctx.stroke();ctx.restore();
    });
    const first=new Date(points[0].timestamp), last=new Date(points[points.length-1].timestamp);
    ctx.fillStyle='#8da0af';ctx.fillText(first.toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'}),x0,y1+17);
    const label=last.toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'});ctx.fillText(label,x1-ctx.measureText(label).width,y1+17);
  }
  function addPoint(timestamp, values) {
    const point={timestamp:timestamp || new Date().toISOString()};
    keys.forEach(k=>point[k]=number(values?.[k]));
    if(points.length && points[points.length-1].timestamp===point.timestamp)return;
    points.push(point); if(points.length>maxPoints)points.shift(); draw();
  }
  function updateCard(key, value, digits=0) {
    const el=document.getElementById('live-'+key); if(el)el.innerHTML=fmt(value,digits)+'<small> '+(key==='battery_soc'?'%':'W')+'</small>';
  }
  async function refresh() {
    try {
      const response=await fetch('./api/snapshot',{cache:'no-store'}); if(!response.ok)throw new Error('HTTP '+response.status);
      const data=await response.json(), values={};
      Object.entries(data.values||{}).forEach(([k,v])=>{values[k]=number(v?.value);if(['pv_power','load_power','grid_power','battery_power','battery_soc','inverter_output'].includes(k))updateCard(k,values[k],k==='battery_soc'?1:0);});
      addPoint(data.timestamp,values);
      const soc=values.battery_soc,fill=document.getElementById('soc-fill'); if(fill&&soc!==null)fill.style.width=Math.max(0,Math.min(100,soc))+'%';
      document.getElementById('live-updated').textContent='Aktualisiert '+new Date(data.timestamp).toLocaleTimeString('de-AT');
      status.textContent=data.ha_error?'● Verbindung gestört':'● Live · '+new Date(data.timestamp).toLocaleTimeString('de-AT');
      status.classList.toggle('status-error',!!data.ha_error);
    } catch(e) {status.textContent='● Live-Daten nicht erreichbar';status.classList.add('status-error');}
  }
  async function loadHistory() {
    try {
      const r=await fetch('./api/dashboard-history',{cache:'no-store'});if(!r.ok)return;
      const data=await r.json();(data.samples||[]).forEach(row=>addPoint(row.timestamp,row.values||{}));
    } catch(e) { /* Live samples will populate the chart. */ }
  }
  async function loadMorningPlan() {
    try {
      const r=await fetch('./api/battery-plan',{cache:'no-store'}); if(!r.ok)return;
      const d=await r.json(),target=d.recommended_morning_soc_percent,current=d.battery_soc_percent;
      document.getElementById('morning-target').textContent=target===null||target===undefined?'Zu wenig Daten':fmt(target,0)+' %';
      const gap=target!==null&&target!==undefined&&current!==null&&current!==undefined?Math.max(0,target-current):null;
      document.getElementById('morning-gap').textContent=gap===null?'–':fmt(gap,0)+' %-Punkte';
      const charge=d.estimated_grid_charge_kwh_to_target;
      let message=(d.advice||[]).find(x=>x.startsWith('Median der morgendlichen'))||'Für die Morgenprognose werden mindestens drei ausreichend vollständige Morgen benötigt.';
      if(d.learned_strategy)message+=' Lernmodell: '+d.learned_strategy.status+'.';
      if(charge!==null&&charge!==undefined)message+=' Vom aktuellen SoC bis zum gelernten Ziel wären rechnerisch etwa '+fmt(charge,1)+' kWh Netzladung nötig – nur eine Simulation, kein Steuerbefehl.';
      document.getElementById('morning-reason').textContent=message+' Netzstrom direkt für den aktuellen Hausverbrauch zu nutzen spart Speicherzyklen; er steht dadurch aber nicht zusätzlich für spätere Spitzen bereit.';
    } catch(e) {document.getElementById('morning-reason').textContent='Morgenempfehlung derzeit nicht verfügbar.';}
  }
  loadHistory().then(refresh); loadMorningPlan(); setInterval(refresh,10000);
  window.addEventListener('resize',draw);
})();
