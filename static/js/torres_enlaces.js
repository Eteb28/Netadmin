/* ════════════════════════════════════════════════════════
   torres.js — Vista de Enlaces de Torres
   Equipos Master/Slave (5GHz) y APs detectados por el torre_poller
   ════════════════════════════════════════════════════════ */
let _torresEnlacesData = [];

async function loadTorresEnlaces(){
  const cont = document.getElementById('torres-lista');
  cont.innerHTML = '<div style="color:#888;padding:1rem">Cargando equipos de torre...</div>';
  const d = await api('/api/torres/enlaces');
  if(!d || !d.equipos?.length){
    const aviso = d?.aviso ? ` (${d.aviso})` : '';
    cont.innerHTML = `<div style="color:#888;padding:1rem">No hay equipos de torre detectados todavía${aviso}.<br>Corré el poller de torres: <code>python3 torre_poller.py --apply</code></div>`;
    document.getElementById('torre-resumen').textContent = '';
    return;
  }
  _torresEnlacesData = d.equipos;
  document.getElementById('torre-resumen').textContent = `${d.total} equipos`;
  renderTorresEnlaces(_torresEnlacesData);
}

function filtrarTorresEnlaces(){
  const q = document.getElementById('torre-buscar').value.toLowerCase();
  if(!q){ renderTorresEnlaces(_torresEnlacesData); return; }
  const f = _torresEnlacesData.filter(e =>
    [e.nombre, e.ssid, e.ip, e.device_model, e.mac].some(v => (v||'').toLowerCase().includes(q)));
  renderTorresEnlaces(f);
}

const _CLASE_INFO_ENLACES = {
  'Master enlace': {ico:'🗼', color:'#1565c0', desc:'Irradia el enlace (5 GHz, modo AP)'},
  'Slave enlace':  {ico:'📡', color:'#6a1b9a', desc:'Recibe el enlace de otra torre (5 GHz, modo STA)'},
  'AP clientes':   {ico:'📶', color:'#2e7d32', desc:'Da servicio a clientes (2.4 GHz, modo AP)'},
};

function renderTorresEnlaces(equipos){
  const cont = document.getElementById('torres-lista');
  if(!equipos.length){ cont.innerHTML = '<div style="color:#888;padding:1rem">Sin resultados</div>'; return; }
  // Agrupar por clasificación
  const grupos = {};
  equipos.forEach(e => { (grupos[e.clasificacion] = grupos[e.clasificacion]||[]).push(e); });
  // Orden: Master, Slave, AP clientes, resto
  const orden = ['Master enlace','Slave enlace','AP clientes'];
  const clases = Object.keys(grupos).sort((a,b)=>{
    const ia = orden.indexOf(a), ib = orden.indexOf(b);
    return (ia<0?99:ia) - (ib<0?99:ib);
  });
  cont.innerHTML = clases.map(clase=>{
    const info = _CLASE_INFO_ENLACES[clase] || {ico:'❓', color:'#888', desc:''};
    const items = grupos[clase].map(e=>`<tr style="cursor:pointer" onclick="abrirModalEquipoTorre(${e.subred},${e.host})" title="Ver detalle del equipo">
      <td style="padding:.35rem .5rem;font-family:monospace">${escHtml(e.ip)}</td>
      <td style="padding:.35rem .5rem"><b>${escHtml(e.nombre)||'—'}</b></td>
      <td style="padding:.35rem .5rem">${escHtml(e.device_model)||'—'}</td>
      <td style="padding:.35rem .5rem">${escHtml(e.banda)||'—'} ${e.modo?'/'+escHtml(e.modo):''}</td>
      <td style="padding:.35rem .5rem">${escHtml(e.ssid)||'—'}</td>
      <td style="padding:.35rem .5rem;font-family:monospace;font-size:.74rem">${escHtml(e.mac)||'—'}</td>
      <td style="padding:.35rem .5rem;font-size:.72rem;color:#999">${escHtml((e.ultimo_sondeo||'').slice(0,16))}</td>
    </tr>`).join('');
    return `<div style="border:1px solid var(--brd);border-radius:10px;margin-bottom:.8rem;overflow:hidden">
      <div style="background:${info.color};color:#fff;padding:.55rem .9rem;display:flex;justify-content:space-between;flex-wrap:wrap;gap:.4rem;align-items:center">
        <div><b style="font-size:.95rem">${info.ico} ${escHtml(clase)}</b>
          <span style="font-size:.75rem;opacity:.85;margin-left:.5rem">${escHtml(info.desc)}</span></div>
        <b style="font-size:.85rem">${grupos[clase].length} equipo(s)</b>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead><tr style="background:var(--card)">
          <th style="text-align:left;padding:.35rem .5rem">IP</th>
          <th style="text-align:left;padding:.35rem .5rem">Nombre</th>
          <th style="text-align:left;padding:.35rem .5rem">Modelo</th>
          <th style="text-align:left;padding:.35rem .5rem">Banda/Modo</th>
          <th style="text-align:left;padding:.35rem .5rem">SSID</th>
          <th style="text-align:left;padding:.35rem .5rem">MAC</th>
          <th style="text-align:left;padding:.35rem .5rem">Últ. sondeo</th>
        </tr></thead>
        <tbody>${items}</tbody>
      </table>
    </div>`;
  }).join('');
}

// ── Modal de detalle de un equipo de torre ──
async function abrirModalEquipoTorre(subred, host){
  const d = await api(`/api/torres/equipo/${subred}/${host}`);
  if(!d || d.error){ alert(d?.error || 'No se pudo cargar el equipo'); return; }
  const ch = d.ultimo_chequeo || {};
  const fila = (lbl,val) => val!=null && val!=='' ? `<div style="display:flex;justify-content:space-between;padding:.25rem 0;border-bottom:1px solid var(--brd)"><span style="color:#777">${lbl}</span><b>${val}</b></div>` : '';

  // Bloque de clientes vinculados (si es AP de clientes)
  let clientesHtml = '';
  if(d.clientes && d.clientes.length){
    clientesHtml = `<div style="margin-top:.8rem">
      <div style="font-weight:700;margin-bottom:.4rem">👥 ${d.total_clientes} cliente(s) vinculado(s)</div>
      <table style="width:100%;font-size:.8rem;border-collapse:collapse">
        <thead><tr style="background:var(--card)">
          <th style="text-align:left;padding:.3rem">Cliente</th>
          <th style="text-align:right;padding:.3rem">Señal</th>
          <th style="text-align:left;padding:.3rem">Localidad</th>
        </tr></thead>
        <tbody>${d.clientes.map(c=>{
          const col = c.signal>-65?'#2e7d32':c.signal>-75?'#e65100':'#c62828';
          return `<tr style="cursor:pointer" onclick="closeModal('modal-equipo-torre');openModalCliente(${c.cliente_id})">
            <td style="padding:.3rem">${c.nombre} <span style="color:#999">#${c.nro_cliente||'s/n'}</span></td>
            <td style="padding:.3rem;text-align:right;color:${col};font-weight:600">${c.signal!=null?c.signal+' dBm':'—'}</td>
            <td style="padding:.3rem">${c.localidad||'—'}</td>
          </tr>`;
        }).join('')}</tbody>
      </table></div>`;
  } else if((d.clasificacion||'').includes('AP clientes')){
    clientesHtml = '<div style="margin-top:.8rem;color:#888;font-size:.82rem">Sin clientes vinculados detectados todavía (se vinculan cuando se sondean los clientes y coincide el AP MAC).</div>';
  }

  document.getElementById('met-titulo').textContent = d.nombre || d.ip;
  document.getElementById('met-body').innerHTML = `
    <div style="font-size:.85rem">
      ${fila('IP', d.ip)}
      ${fila('Clasificación', d.clasificacion)}
      ${fila('Modelo', d.device_model)}
      ${fila('MAC (WLAN0)', d.mac)}
      ${fila('Banda / Modo', (d.banda||'') + (d.modo?' / '+d.modo:''))}
      ${fila('SSID', d.ssid)}
      ${fila('Firmware', d.firmware)}
      ${fila('Enlazado a (AP MAC)', d.ap_mac_enlace)}
      ${fila('Señal', ch.signal!=null?ch.signal+' dBm':'')}
      ${fila('CCQ', ch.ccq!=null?ch.ccq+'%':'')}
      ${fila('TX/RX', (ch.tx_rate||ch.rx_rate)?`${ch.tx_rate||'?'}/${ch.rx_rate||'?'}`:'')}
      ${fila('Frecuencia', ch.frecuencia || d.frecuencia)}
      ${fila('Uptime', ch.uptime_txt)}
      ${fila('Último sondeo', (d.ultimo_sondeo||'').slice(0,16))}
      ${fila('Notas', d.notas)}
    </div>
    ${clientesHtml}`;
  document.getElementById('modal-equipo-torre').style.display = 'flex';
}
