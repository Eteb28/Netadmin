/* ════════════════════════════════════════════════════════
   reclamos.js — Vista de reclamos espejados de Tero HelpDesk.
   ════════════════════════════════════════════════════════ */

let _teroOperadores = {};

function _nombreOperador(u){
  if(!u) return '—';
  return _teroOperadores[u] || u;
}

async function loadReclamos(){
  const dias = document.getElementById('rec-dias')?.value || 90;
  try { _teroOperadores = await api('/api/reclamos/operadores') || {}; } catch(e){}
  const d = await api(`/api/reclamos/stats?dias=${dias}`);
  if(!d) return;
  const k = d.kpi || {};
  // KPIs
  const kpi = (val, lbl, color) => `<div style="background:var(--surf2);border-radius:10px;padding:.8rem;text-align:center;border-top:3px solid ${color}">
    <div style="font-size:1.6rem;font-weight:700;color:${color}">${val ?? 0}</div>
    <div style="font-size:.72rem;color:var(--txt2);text-transform:uppercase">${lbl}</div></div>`;
  document.getElementById('rec-kpis').innerHTML =
    kpi(k.total, 'Total', '#5B9BD5') +
    kpi(k.abiertos, 'Abiertos', '#E0A838') +
    kpi(k.cerrados, 'Cerrados', '#4FB3AA') +
    kpi(d.tiempo_prom_horas != null ? d.tiempo_prom_horas + 'h' : '—', 'Tiempo prom. cierre', '#9676F1') +
    kpi(k.sin_cruzar, 'Sin cliente', '#566B84');

  // Ranking de operadores
  const ops = d.operadores || [];
  const maxOp = Math.max(...ops.map(o => o.total), 1);
  document.getElementById('rec-operadores').innerHTML = `
    <h3 style="font-size:.95rem;margin-bottom:.6rem">👤 Ranking de operadores</h3>
    <div class="tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:.82rem">
      <thead><tr style="background:var(--card)"><th style="text-align:left;padding:.4rem">Operador</th><th style="text-align:right;padding:.4rem">Total</th><th style="text-align:right;padding:.4rem">Cerr.</th><th style="text-align:right;padding:.4rem">Abiertos</th><th></th></tr></thead>
      <tbody>${ops.map(o => `<tr>
        <td style="padding:.4rem"><b>${escHtml(_nombreOperador(o.operador))}</b>${_teroOperadores[o.operador]?`<br><span style="font-size:.66rem;color:var(--txt2)">${escHtml(o.operador)}</span>`:''}</td>
        <td style="padding:.4rem;text-align:right">${o.total}</td>
        <td style="padding:.4rem;text-align:right;color:#4FB3AA">${o.cerrados}</td>
        <td style="padding:.4rem;text-align:right;color:#E0A838">${o.abiertos}</td>
        <td style="width:80px;padding:.4rem"><div style="background:var(--card);border-radius:3px;height:10px"><div style="background:#5B9BD5;height:100%;border-radius:3px;width:${Math.round(o.total/maxOp*100)}%"></div></div></td>
      </tr>`).join('') || '<tr><td colspan="5" style="padding:.6rem;color:var(--txt2)">Sin datos. Sincronizá primero.</td></tr>'}</tbody>
    </table></div>`;

  // Categorías y canales
  document.getElementById('rec-categorias').innerHTML = _recBarras('🏷 Por categoría', d.categorias, 'categoria', '#E08063');
  document.getElementById('rec-canales').innerHTML = _recBarras('📞 Por canal', d.canales, 'canal', '#4FB3AA');
}

function _recBarras(titulo, items, campo, color){
  items = items || [];
  const max = Math.max(...items.map(i => i.total), 1);
  return `<h3 style="font-size:.95rem;margin-bottom:.6rem">${escHtml(titulo)}</h3>
    ${items.slice(0, 10).map(i => `<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem;font-size:.8rem">
      <span style="min-width:120px">${escHtml(i[campo]) || '(sin dato)'}</span>
      <div style="flex:1;background:var(--card);border-radius:3px;height:14px"><div style="background:${color};height:100%;border-radius:3px;width:${Math.round(i.total/max*100)}%"></div></div>
      <b style="min-width:32px;text-align:right">${escHtml(i.total)}</b>
    </div>`).join('') || '<div style="color:var(--txt2);font-size:.8rem">Sin datos</div>'}`;
}

async function syncTero(){
  const btn = event?.target;
  if(btn){ btn.disabled = true; btn.textContent = '⏳ Sincronizando…'; }
  const r = await api('/api/tero/sync', 'POST');
  if(btn){ btn.disabled = false; btn.textContent = '🔄 Sincronizar'; }
  if(r && r.error){ alert('Error: ' + r.error); return; }
  if(r){ alert(`Sincronizado: ${r.tickets_sincronizados||0} reclamos, ${r.tickets_vinculados_a_cliente||0} vinculados a cliente.`); }
  loadReclamos();
}

// ── Reclamos en la ficha del cliente ──
async function _cargarReclamosCliente(nroCliente){
  const panel = document.getElementById('mcli-reclamos');
  if(!panel || !nroCliente) return;
  panel.style.display = 'none';
  let d = null;
  try { d = await api(`/api/reclamos/cliente/${nroCliente}`); } catch(e){ return; }
  if(!d || !d.total){ return; }
  panel.style.display = 'block';
  const badge = (est) => est === 'cerrado'
    ? '<span style="background:rgba(79,179,170,.2);color:#4FB3AA;font-size:.66rem;padding:.1rem .4rem;border-radius:8px">cerrado</span>'
    : '<span style="background:rgba(224,168,56,.2);color:#E0A838;font-size:.66rem;padding:.1rem .4rem;border-radius:8px">abierto</span>';
  const filas = d.reclamos.slice(0, 20).map(r => `<tr style="cursor:pointer" onclick="verDetalleReclamo(${r.tero_id})" title="Ver detalle completo en Tero">
    <td style="padding:.3rem .4rem;font-size:.72rem;color:var(--txt2)">${escHtml((r.created_at||'').slice(0,10))}</td>
    <td style="padding:.3rem .4rem"><b>${escHtml(r.titulo)||'—'}</b> ${badge(r.estado)}<br><span style="font-size:.7rem;color:var(--txt2)">${escHtml(r.categoria)}${r.subcategoria?' · '+escHtml(r.subcategoria):''} · ${escHtml(r.canal)}</span></td>
    <td style="padding:.3rem .4rem;font-size:.72rem">${escHtml(_nombreOperador(r.asign_to||r.created_by))}</td>
  </tr>`).join('');
  document.getElementById('mcli-reclamos-cont').innerHTML = `
    <div style="font-size:.75rem;color:var(--txt2);margin-bottom:.3rem">${d.total} reclamo(s) en Tero</div>
    <div class="tbl-wrap" style="max-height:220px;overflow:auto"><table style="width:100%;border-collapse:collapse">
      <tbody>${filas}</tbody></table></div>`;
}


/* ── Detalle del reclamo traído en vivo de Tero ── */
async function verDetalleReclamo(teroId){
  let m = document.getElementById('rec-modal');
  if(!m){
    m = document.createElement('div');
    m.id = 'rec-modal';
    m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9000;display:flex;align-items:center;justify-content:center;padding:1rem';
    m.onclick = e => { if(e.target === m) m.remove(); };
    document.body.appendChild(m);
  }
  m.innerHTML = '<div style="background:var(--card);border:1px solid var(--brd);border-radius:12px;padding:1.2rem;max-width:760px;width:100%;max-height:85vh;overflow:auto"><div style="text-align:center;color:var(--txt2)">Consultando Tero…</div></div>';
  const d = await api(`/api/reclamos/${teroId}/detalle`);
  const box = m.firstChild;
  if(!d || d.error){
    box.innerHTML = `<div style="color:#E0605F">No se pudo traer el detalle: ${escHtml(d?d.error:'sin respuesta')}</div>
      <button class="btn btn-gray btn-sm" style="margin-top:.6rem" onclick="document.getElementById('rec-modal').remove()">Cerrar</button>`;
    return;
  }
  // OJO: este texto lo escribió el cliente final en Tero (no un usuario interno).
  // Nunca insertarlo sin escapar: es la superficie de XSS más expuesta de toda la app.
  const msgs = (d.mensajes||[]).map(x=>{
    const dat = x.data || {};
    const txt = dat.text || dat.body || dat.message || (typeof dat === 'string' ? dat : JSON.stringify(dat).slice(0,300));
    const quien = dat.author || dat.from || dat.sender || '';
    return `<div style="border-left:2px solid var(--brd);padding:.35rem .6rem;margin-bottom:.4rem">
      ${quien?`<div style="font-size:.68rem;color:var(--txt2)">${escHtml(quien)}</div>`:''}
      <div style="font-size:.8rem">${escHtml(txt)}</div></div>`;
  }).join('');
  const adj = (d.adjuntos||[]).length;
  box.innerHTML = `
    <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.6rem">
      <h3 style="margin:0;flex:1">${escHtml(d.titulo||'Reclamo')} <span style="color:var(--txt2);font-size:.8rem">#${escHtml(d.tero_id)}</span></h3>
      <button class="btn btn-gray btn-xs" onclick="document.getElementById('rec-modal').remove()">✕</button>
    </div>
    <div style="font-size:.76rem;color:var(--txt2);margin-bottom:.7rem">
      ${escHtml(d.cliente)} · ${escHtml(d.categoria)} · ${escHtml(d.estado)} · ${escHtml(_nombreOperador(d.asignado))}
      ${d.creado?' · abierto '+escHtml(d.creado.slice(0,16).replace('T',' ')):''}
    </div>
    ${d.detail?`<div style="background:var(--surf2);border-radius:8px;padding:.7rem .9rem;margin-bottom:.8rem;white-space:pre-wrap;font-size:.83rem">${escHtml(d.detail)}</div>`:'<div style="color:var(--txt2);font-size:.8rem;margin-bottom:.8rem">(sin texto de detalle)</div>'}
    ${msgs?`<div style="font-size:.72rem;color:var(--txt2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.35rem">Conversación (${(d.mensajes||[]).length})</div>${msgs}`:''}
    ${adj?`<div style="font-size:.74rem;color:var(--txt2);margin-top:.5rem">📎 ${adj} adjunto(s) en Tero</div>`:''}`;
}
