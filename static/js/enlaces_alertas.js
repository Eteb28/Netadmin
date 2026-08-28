/* ════════════════════════════════════════════════════════
   enlaces_alertas.js — Enlaces de clientes con problemas de calidad
   Bandera (revisión): alguna condición mala
   Alerta (crítico): señal + ccq + tx/rx las tres malas
   ════════════════════════════════════════════════════════ */

async function loadEnlacesAlertas(){
  const cont = document.getElementById('enlaces-alertas-cont');
  cont.innerHTML = '<div style="color:#888;padding:1rem">Cargando enlaces...</div>';
  const d = await api('/api/enlaces/problematicos');
  if(!d){ cont.innerHTML = '<div style="color:#888;padding:1rem">No se pudo cargar</div>'; return; }
  const u = d.umbrales || {};
  const total = (d.total_alertas||0) + (d.total_revisar||0);
  if(total === 0){
    cont.innerHTML = `<div style="color:#2e7d32;padding:1rem;font-size:.9rem">✅ Ningún enlace con problemas detectado.<br>
      <small style="color:#999">Umbrales: señal ≤ ${u.senal} dBm · CCQ < ${u.ccq}% · TX/RX < ${u.txrx} Mbps</small></div>`;
    return;
  }

  const filaCliente = (e, esAlerta) => {
    const probs = (e.problemas||[]).map(p=>{
      const map = {'señal':'📶 señal','ccq':'📊 CCQ','tx/rx':'⚡ TX/RX'};
      return `<span style="background:var(--card);color:#c62828;border-radius:4px;padding:1px 6px;font-size:.72rem;margin-right:.3rem">${map[p]||p}</span>`;
    }).join('');
    const sigCol = e.signal>-65?'#2e7d32':e.signal>-75?'#e65100':'#c62828';
    return `<tr style="cursor:pointer" onclick="openModalCliente(${e.cliente_id})">
      <td style="padding:.4rem .5rem">${esAlerta?'🔴':'⚠'} <b>${escHtml(e.nombre)}</b> <span style="color:#999">#${escHtml(e.nro_cliente)||'s/n'}</span></td>
      <td style="padding:.4rem .5rem;color:${sigCol};font-weight:700;text-align:right">${e.signal!=null?e.signal+' dBm':'—'}</td>
      <td style="padding:.4rem .5rem;text-align:right">${e.ccq!=null?e.ccq+'%':'—'}</td>
      <td style="padding:.4rem .5rem;text-align:right">${escHtml(e.tx_rate)||'?'}/${escHtml(e.rx_rate)||'?'}</td>
      <td style="padding:.4rem .5rem">${escHtml(e.ssid)||'—'}</td>
      <td style="padding:.4rem .5rem">${probs}</td>
    </tr>`;
  };

  const tabla = (titulo, items, esAlerta, color) => {
    if(!items.length) return '';
    return `<div style="border:1px solid ${color};border-radius:10px;margin-bottom:1rem;overflow:hidden">
      <div style="background:${color};color:#fff;padding:.55rem .9rem;font-weight:700">
        ${titulo} — ${items.length} enlace(s)
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead><tr style="background:var(--card)">
          <th style="text-align:left;padding:.4rem .5rem">Cliente</th>
          <th style="text-align:right;padding:.4rem .5rem">Señal</th>
          <th style="text-align:right;padding:.4rem .5rem">CCQ</th>
          <th style="text-align:right;padding:.4rem .5rem">TX/RX</th>
          <th style="text-align:left;padding:.4rem .5rem">AP</th>
          <th style="text-align:left;padding:.4rem .5rem">Problemas</th>
        </tr></thead>
        <tbody>${items.map(e=>filaCliente(e, esAlerta)).join('')}</tbody>
      </table>
    </div>`;
  };

  cont.innerHTML = `
    <div style="font-size:.8rem;color:#777;margin-bottom:.8rem">
      Umbrales: señal ≤ ${u.senal} dBm · CCQ < ${u.ccq}% · TX/RX < ${u.txrx} Mbps ·
      <b style="color:#c62828">${d.total_alertas} alerta(s)</b> · <b style="color:#e65100">${d.total_revisar} a revisar</b>
    </div>
    ${tabla('🔴 ALERTA — enlaces críticos (las 3 condiciones malas)', d.alertas, true, '#c62828')}
    ${tabla('⚠ Para revisar (alguna condición mala)', d.revisar, false, '#e65100')}
    <div id="enlaces-concentracion" style="margin-top:1rem"></div>`;
  loadConcentracion();
}

// ── Mapa de calor de problemas: dónde se concentran ──
async function loadConcentracion(){
  const cont = document.getElementById('enlaces-concentracion');
  if(!cont) return;
  const d = await api('/api/enlaces/concentracion');
  if(!d || (!d.por_ap?.length && !d.por_zona?.length)) return;
  const barra = (item, label) => {
    const pct = item.pct || 0;
    const col = item.alertas>0 ? '#c62828' : pct>=50 ? '#e65100' : '#f9a825';
    return `<div style="margin-bottom:.4rem">
      <div style="display:flex;justify-content:space-between;font-size:.8rem">
        <span><b>${escHtml(label)}</b> ${item.alertas>0?`<span style="color:#c62828">🔴 ${item.alertas}</span>`:''}</span>
        <span style="color:#777">${item.problemas}/${item.total} (${pct}%)</span>
      </div>
      <div style="background:var(--card);border-radius:4px;height:8px;overflow:hidden">
        <div style="background:${col};width:${pct}%;height:100%"></div>
      </div></div>`;
  };
  let html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">';
  if(d.por_ap?.length){
    html += `<div><div style="font-weight:700;margin-bottom:.5rem">📡 Por AP (más afectados)</div>
      ${d.por_ap.slice(0,10).map(a=>barra(a, a.ssid||a.ap_mac||'?')).join('')}</div>`;
  }
  if(d.por_zona?.length){
    html += `<div><div style="font-weight:700;margin-bottom:.5rem">📍 Por localidad</div>
      ${d.por_zona.slice(0,10).map(z=>barra(z, z.localidad)).join('')}</div>`;
  }
  html += '</div>';
  html += '<div style="font-size:.75rem;color:#999;margin-top:.6rem">Si un AP concentra muchos problemas, puede estar saturado o mal orientado — revisalo antes que los clientes sueltos.</div>';
  cont.innerHTML = `<div style="border-top:2px solid var(--brd);padding-top:1rem">
    <div style="font-size:.95rem;font-weight:700;margin-bottom:.6rem">🔥 Dónde se concentran los problemas</div>${html}</div>`;
}
