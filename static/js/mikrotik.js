/* ════════════════════════════════════════════════════════
   mikrotik.js — Pantalla "🧭 Routers MikroTik"
   Muestra lo que dejó mikrotik_poller: salud del equipo (temperaturas,
   ventiladores, fuentes), CPU/memoria, sesiones PPPoE y vecinos vistos.
   ════════════════════════════════════════════════════════ */

/* Umbrales de temperatura. El CPU de un CCR corre más caliente que la placa,
   así que no comparten umbral: en el equipo de referencia la placa marca 43°C
   y el CPU 58°C, y ninguno de los dos es un problema. */
const _MKT_TEMP = {
  cpu:   {alerta: 75, critico: 85},
  otros: {alerta: 60, critico: 70},
};

function _mktColorTemp(valor, tipo){
  if(valor == null) return 'var(--txt2)';
  const u = _MKT_TEMP[tipo] || _MKT_TEMP.otros;
  if(valor >= u.critico) return 'var(--critico,#c62828)';
  if(valor >= u.alerta)  return 'var(--alerta,#e8a13b)';
  return 'var(--optimo,#2e7d32)';
}

function _mktUptime(seg){
  if(!seg) return '—';
  const d = Math.floor(seg/86400), h = Math.floor((seg%86400)/3600);
  return d ? `${d}d ${h}h` : `${h}h`;
}

function _mktMB(kb){
  if(kb == null) return '—';
  return kb >= 1024*1024 ? (kb/1024/1024).toFixed(1)+' GB' : Math.round(kb/1024)+' MB';
}

async function loadMikrotik(){
  const cont = document.getElementById('mkt-lista');
  const res  = document.getElementById('mkt-resumen');
  if(!cont) return;
  cont.innerHTML = '<div style="color:var(--txt2);padding:1rem">Cargando…</div>';
  const d = await api('/api/mikrotik');
  if(!d){ cont.innerHTML = '<div style="color:var(--critico);padding:1rem">No se pudo cargar.</div>'; return; }

  if(d.sin_datos || !d.routers.length){
    if(res) res.innerHTML = '';
    cont.innerHTML = `<div style="color:var(--txt2);padding:1rem;line-height:1.6">
      Todavía no hay datos de MikroTik.<br>
      <span style="font-size:.85rem">Los routers se toman del inventario de torres (fabricante MikroTik
      o modelo CCR/RouterBoard). Una vez cargados, corré
      <code>python3 mikrotik_poller.py</code> — o probá uno suelto con
      <code>python3 mikrotik_poller.py --diag &lt;IP&gt;</code>.</span></div>`;
    return;
  }

  const r = d.resumen || {};
  if(res){
    const kpi = (v,l,c) => `<div class="ap-kpi k-${c}"><div class="v">${v}</div><div class="l">${l}</div></div>`;
    res.className = 'ap-resumen';
    res.innerHTML = kpi(r.total||0,'Routers','total') +
                    kpi(r.online||0,'En línea','optimo') +
                    kpi((r.total||0)-(r.online||0),'Sin responder', (r.total||0)-(r.online||0) ? 'critico':'total') +
                    kpi(r.sesiones_ppp||0,'Sesiones PPPoE','total');
  }

  cont.innerHTML = d.routers.map(m=>{
    const off = !m.online;
    const cls = off ? 'muerto' : 'optimo';
    // Sensores: se listan los que el equipo declare, sin asumir cuáles existen
    const sensores = m.sensores || {};
    const temps = Object.entries(sensores)
      .filter(([n,s]) => s && s.unidad === 'C' && s.valor != null)
      .map(([n,s])=>{
        const tipo = n.includes('cpu') ? 'cpu' : 'otros';
        return `<div class="ap-metrica"><span class="v" style="color:${_mktColorTemp(s.valor,tipo)}">${escHtml(s.valor)}°</span>
                <span class="l">${escHtml(n.replace('-temperature','').replace('temperature','placa'))}</span></div>`;
      }).join('');
    // Ventiladores y fuentes sólo se muestran si el equipo los reporta
    const fans = Object.entries(sensores).filter(([n,s]) => n.includes('fan') && s.valor != null);
    const fanTxt = fans.length
      ? `<span class="ap-chip">${fans.filter(([,s])=>s.valor>0).length}/${fans.length} ventiladores girando</span>` : '';
    const psus = Object.entries(sensores).filter(([n,s]) => n.includes('psu'));
    const psuTxt = psus.length
      ? psus.map(([n,s])=>`<span class="ap-chip${s.valor?'':' warn'}">${escHtml(n.replace('-state',''))}: ${s.valor?'OK':'sin alimentación'}</span>`).join('') : '';

    const memPct = m.mem_pct;
    const cpuPct = m.cpu_prom;
    const barra = (pct, label, extra) => pct == null ? '' : `
      <div class="ap-ocup">
        <div class="ap-ocup-tit"><span>${label}</span><b>${pct}%${extra?' · '+extra:''}</b></div>
        <div class="ap-barra" style="--umbral:80%"><i style="width:${Math.min(pct,100)}%"></i></div>
      </div>`;

    return `<div class="ap-card e-${cls}">
      <div class="ap-cab">
        <span class="ap-nom" title="${escAttr(m.descr||m.modelo||'')}">${escHtml(m.identidad||m.ip||'MikroTik')}</span>
        <span class="ap-torre">${escHtml(m.torre_nombre)||escHtml(m.ip)||''}</span>
        <span class="ap-pill">${off?'sin responder':'en línea'}</span>
      </div>
      <div style="font-size:.72rem;color:var(--txt2);margin:.15rem 0 .4rem">
        ${escHtml(m.modelo)||'—'} · RouterOS ${escHtml(m.version)||'—'}
        ${m.serial?' · s/n '+escHtml(m.serial):''} · up ${_mktUptime(m.uptime_seg)}
      </div>
      ${off ? '<div class="ap-motivo"><b>El router no respondió el último sondeo SNMP.</b></div>' : `
        <div class="ap-metricas">
          <div class="ap-metrica"><span class="v">${m.cpu_nucleos||'—'}</span><span class="l">núcleos</span></div>
          ${temps}
        </div>
        ${barra(cpuPct,'CPU promedio', m.cpu_max!=null?`pico ${m.cpu_max}%`:'')}
        ${barra(memPct,'Memoria', `${_mktMB(m.mem_usada_kb)} de ${_mktMB(m.mem_total_kb)}`)}
        <div class="ap-avisos" style="margin-top:.4rem">
          <span class="ap-chip">${m.sesiones_ppp||0} sesiones PPPoE</span>
          <span class="ap-chip">${m.vecinos||0} vecinos vistos</span>
          ${fanTxt}${psuTxt}
        </div>`}
      <div style="font-size:.66rem;color:var(--txt2);margin-top:.4rem">
        último sondeo: ${escHtml(m.last_check)||'—'}</div>
    </div>`;
  }).join('');
}
