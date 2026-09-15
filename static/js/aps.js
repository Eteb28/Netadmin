/* ════════════════════════════════════════════════════════
   aps.js — Vista de APs: clientes conectados a cada AP con su señal
   Fuente preferida: la instantánea SNMP del AP (snmp_estaciones), que ve todas
   sus estaciones de una. Si no hay datos SNMP, cae al último sondeo por cliente
   del poller HTTP. El backend informa cuál usó en d.fuente.
   ════════════════════════════════════════════════════════ */
let _apsData = [];

async function loadAPs(){
  const cont = document.getElementById('aps-lista');
  cont.innerHTML = '<div style="color:#888;padding:1rem">Cargando APs...</div>';
  const d = await api('/api/aps');
  if(!d || !d.aps?.length){
    cont.innerHTML = '<div style="color:#888;padding:1rem">No hay APs detectados todavía. Los APs aparecen a medida que se sondean los equipos de los clientes.</div>';
    document.getElementById('ap-resumen').textContent = '';
    return;
  }
  _apsData = d.aps;
  const nCli = _apsData.reduce((s,a)=>s+a.total_clientes,0);
  const sinCruzar = _apsData.reduce((s,a)=>s+a.clientes.filter(c=>c.sin_cruzar).length,0);
  const fuente = d.fuente === 'snmp'
    ? '<span class="ap-chip">vía SNMP</span>'
    : '<span class="ap-chip warn">vía poller HTTP (SNMP sin datos)</span>';
  document.getElementById('ap-resumen').innerHTML =
    `${d.total_aps} AP(s) · ${nCli} estaciones ` + fuente +
    (sinCruzar ? ` <span class="ap-chip warn">${sinCruzar} sin cliente en Pucará</span>` : '');
  renderAPs(_apsData);
}

function filtrarAPs(){
  const q = document.getElementById('ap-buscar').value.toLowerCase();
  if(!q){ renderAPs(_apsData); return; }
  const filtrados = _apsData.filter(a =>
    (a.ssid||'').toLowerCase().includes(q) || (a.ap_mac||'').toLowerCase().includes(q) ||
    (a.torre_nombre||'').toLowerCase().includes(q) ||
    (a.clientes||[]).some(c=>(c.nombre||'').toLowerCase().includes(q)));
  renderAPs(filtrados);
}

function _colorSenal(s){
  if(s == null) return '#999';
  if(s > -65) return '#2e7d32';   // buena
  if(s > -75) return '#e65100';   // media
  return '#c62828';               // mala
}

function renderAPs(aps){
  const cont = document.getElementById('aps-lista');
  if(!aps.length){ cont.innerHTML = '<div style="color:#888;padding:1rem">Sin resultados para ese filtro</div>'; return; }
  cont.innerHTML = aps.map(ap=>{
    const promCol = _colorSenal(ap.signal_promedio);
    const clientesHtml = ap.clientes.map(c=>{
      const col = _colorSenal(c.signal);
      const estadoBadge = c.estado==='activo'
        ? '<span style="color:#2e7d32">●</span>'
        : c.estado==='suspendido' ? '<span style="color:#e65100">●</span>' : '<span style="color:#999">●</span>';
      // Las estaciones sin cliente cargado no abren ficha: no hay a dónde ir.
      const click = c.cliente_id ? `onclick="openModalCliente(${c.cliente_id})"` : '';
      const nombre = c.sin_cruzar
        ? `<span title="El AP la reporta pero no hay cliente con esa MAC/IP en Pucará">${escHtml(c.nombre)} <span class="ap-chip warn" style="font-size:.6rem">sin cruzar</span></span>`
        : escHtml(c.nombre);
      return `<tr style="cursor:${c.cliente_id?'pointer':'default'}" ${click}>
        <td style="padding:.3rem .5rem">${estadoBadge} ${nombre}</td>
        <td style="padding:.3rem .5rem;font-family:monospace;font-size:.78rem">${c.nro_cliente?'#'+escHtml(c.nro_cliente):escHtml(c.mac)||'s/n'}</td>
        <td style="padding:.3rem .5rem">${escHtml(c.localidad)||'—'}</td>
        <td style="padding:.3rem .5rem;color:${col};font-weight:700;text-align:right">${c.signal!=null?escHtml(c.signal)+' dBm':'—'}</td>
        <td style="padding:.3rem .5rem;text-align:right">${c.snr!=null?escHtml(c.snr)+' dB':(c.ccq!=null?escHtml(c.ccq)+'%':'—')}</td>
        <td style="padding:.3rem .5rem;text-align:right;font-size:.75rem">${c.distancia_m!=null?escHtml(Math.round(c.distancia_m))+' m':'—'}</td>
        <td style="padding:.3rem .5rem;font-size:.72rem;color:#999">${escHtml((c.fecha||'').slice(0,16))}</td>
      </tr>`;
    }).join('');
    return `<div style="border:1px solid var(--brd);border-radius:10px;margin-bottom:.8rem;overflow:hidden">
      <div style="background:#1a3d6b;color:#fff;padding:.6rem .9rem;display:flex;justify-content:space-between;flex-wrap:wrap;gap:.5rem;align-items:center">
        <div>
          <b style="font-size:.95rem">📡 ${escHtml(ap.ssid)||'(sin SSID)'}</b>
          <span style="font-family:monospace;font-size:.78rem;opacity:.85;margin-left:.6rem">${escHtml(ap.ap_mac)}</span>
          <button onclick="verEquipoTorrePorMac('${escJs(ap.ap_mac)}')" style="margin-left:.6rem;background:rgba(255,255,255,.2);color:#fff;border:none;border-radius:4px;padding:.15rem .5rem;font-size:.72rem;cursor:pointer">🗼 ver equipo</button>
        </div>
        <div style="font-size:.82rem">
          <b>${ap.total_clientes}</b> cliente(s) · señal prom:
          <b style="color:${ap.signal_promedio>-65?'var(--tint-verde)':ap.signal_promedio>-75?'var(--tint-rojo)':'#ff8a80'}">${ap.signal_promedio!=null?ap.signal_promedio+' dBm':'—'}</b>
        </div>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:.84rem">
        <thead><tr style="background:var(--card)">
          <th style="text-align:left;padding:.3rem .5rem">Cliente</th>
          <th style="text-align:left;padding:.3rem .5rem">N° / MAC</th>
          <th style="text-align:left;padding:.3rem .5rem">Localidad</th>
          <th style="text-align:right;padding:.3rem .5rem">Señal</th>
          <th style="text-align:right;padding:.3rem .5rem" title="SNR en Cambium, CCQ en Ubiquiti">SNR/CCQ</th>
          <th style="text-align:right;padding:.3rem .5rem">Dist.</th>
          <th style="text-align:left;padding:.3rem .5rem">Últ. sondeo</th>
        </tr></thead>
        <tbody>${clientesHtml}</tbody>
      </table>
    </div>`;
  }).join('');
}

// ── Saltar de un AP (por su MAC) al modal del equipo de torre ──
async function verEquipoTorrePorMac(mac){
  const r = await api(`/api/torres/por_mac/${encodeURIComponent(mac)}`);
  if(!r || r.error){
    alert(r?.error || 'No hay un equipo de torre cargado con esa MAC.\nSe vincula cuando el poller de torres detecta ese equipo.');
    return;
  }
  if(typeof abrirModalEquipoTorre === 'function'){
    abrirModalEquipoTorre(r.subred, r.host);
  }
}
