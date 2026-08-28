/* ════════════════════════════════════════════════════════
   onu_alertas.js — Panel de alertas de señal óptica:
   1) Alertas NAP/PON (infraestructura): NAPs/PONs con TODOS los clientes caídos
   2) ONU individuales con señal baja/crítica
   3) Limpieza: ONUs en la OLT de clientes dados de baja, rescindidos o
      PENDIENTES de rescisión. Se alimenta de /api/v2/pendientes-rescision.
      Es SÓLO LECTURA: Pucará no da de baja nada en la OLT.
   ════════════════════════════════════════════════════════ */

let _onuAlertasTimer = null;

async function loadOnuAlertas(){
  const cont = document.getElementById('onu-alertas-cont');
  if(!cont) return;
  // Auto-refresco mientras la sección esté a la vista: el poller actualiza
  // las señales por cron y la tabla tiene que seguirle el ritmo.
  if(_onuAlertasTimer) clearInterval(_onuAlertasTimer);
  _onuAlertasTimer = setInterval(function(){
    const pg = document.getElementById('page-onu-alertas');
    if(!pg || !pg.classList.contains('active')){ clearInterval(_onuAlertasTimer); _onuAlertasTimer=null; return; }
    loadOnuAlertas();
  }, 60000);
  cont.innerHTML = '<div style="color:var(--txt2);padding:1rem">Cargando alertas…</div>';
  const [napPon, prob, limpieza] = await Promise.all([
    api('/api/alertas/nap-pon').catch(()=>null),
    api('/api/onus/problematicas').catch(()=>null),
    api('/api/v2/pendientes-rescision').catch(()=>null),
  ]);
  cont.innerHTML =
    _seccionNapPon(napPon) +
    _seccionOnusIndividuales(prob) +
    _seccionLimpieza(limpieza);
}

// ── 1) Alertas de infraestructura NAP/PON ──
function _seccionNapPon(d){
  if(!d) return '';
  const crit = d.criticas || [], baja = d.bajas || [];
  if(!crit.length && !baja.length){
    return `<div style="border:1px solid #4FB3AA;border-radius:10px;padding:.7rem .9rem;margin-bottom:1rem;background:rgba(79,179,170,.08)">
      <b style="color:#4FB3AA">🛰 Infraestructura OK</b> <span style="color:var(--txt2);font-size:.82rem">— ningún NAP ni PON con todos los clientes caídos</span></div>`;
  }
  const bloque = (a, critica) => {
    const col = critica ? '#E0605F' : '#E08063';
    const icono = a.tipo === 'nap' ? '📦' : '🔌';
    const cls = (a.clientes||[]).map(c=>`${escHtml(c.nombre)} (#${escHtml(c.cod)})`).join(', ');
    return `<div style="border-left:3px solid ${col};background:var(--surf2);border-radius:6px;padding:.6rem .8rem;margin-bottom:.5rem">
      <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
        <span style="font-size:1.1rem">${icono}</span>
        <b style="color:${col}">${escHtml(a.titulo)}</b>
        <span style="background:${col};color:#fff;font-size:.7rem;padding:.1rem .5rem;border-radius:10px">${a.n_afectados} cliente(s)</span>
        ${critica?'<span style="font-size:.7rem;color:var(--txt2)">→ incidencia creada + Telegram</span>':''}
      </div>
      <div style="font-size:.76rem;color:var(--txt2);margin-top:.35rem">Afectados: ${cls}</div>
    </div>`;
  };
  return `<div class="card" style="margin-bottom:1rem;border:1px solid #E0605F">
    <div class="stitle" style="color:#E0605F">🛰 Alertas de infraestructura (NAP / PON)</div>
    <div style="font-size:.76rem;color:var(--txt2);margin-bottom:.6rem">Cuando <b>todos</b> los clientes activos de un NAP o de un puerto PON caen juntos — probable corte de fibra o equipo sin luz.</div>
    ${crit.map(a=>bloque(a,true)).join('')}
    ${baja.map(a=>bloque(a,false)).join('')}
  </div>`;
}

// ── 2) ONU individuales con señal baja/crítica ──
function _seccionOnusIndividuales(d){
  if(!d) return '';
  const total = (d.total_criticas||0) + (d.total_bajas||0) + (d.total_saturadas||0);
  if(total === 0){
    return `<div class="card" style="margin-bottom:1rem"><div style="color:#4FB3AA;padding:.3rem">✅ Ninguna ONU individual con señal fuera de rango.
      <span style="color:var(--txt2);font-size:.78rem">(saturada &gt; -8 · buena ≥ -23 · aceptable ≥ -26 · baja ≥ -29 · crítica &lt; -29 dBm)</span></div></div>`;
  }
  const fila = (o, critica) => {
    const rx = o.rx_power != null ? o.rx_power.toFixed(2) : '—';
    const col = critica ? '#E0605F' : '#E08063';
    const cli = o.cliente_nombre || (o.nro_cliente ? '#'+o.nro_cliente : '—');
    return `<tr style="cursor:pointer" onclick="${o.cliente_id?`openModalCliente(${o.cliente_id})`:''}">
      <td style="padding:.4rem .5rem">${critica?'🔴':'⚠'} <b>${escHtml(cli)}</b> ${o.nro_cliente?`<span style="color:var(--txt2)">#${escHtml(o.nro_cliente)}</span>`:''}</td>
      <td style="padding:.4rem .5rem;color:${col};font-weight:700;text-align:right">${rx} dBm</td>
      <td style="padding:.4rem .5rem;font-family:monospace">${escHtml(o.olt_nombre)||'?'} · PON${o.pon}/${o.onu}</td>
      <td style="padding:.4rem .5rem">${escHtml(o.direccion)} ${escHtml(o.localidad)}</td>
      <td style="padding:.4rem .5rem">${o.telefono?`<a href="tel:${encodeURIComponent(o.telefono)}" onclick="event.stopPropagation()" style="color:#5B9BD5">${escHtml(o.telefono)}</a>`:''}</td>
    </tr>`;
  };
  const tabla = (titulo, items, critica, color) => {
    if(!items.length) return '';
    return `<div style="border:1px solid ${color};border-radius:10px;margin-bottom:1rem;overflow:hidden">
      <div style="background:${color};color:#fff;padding:.55rem .9rem;font-weight:700">${escHtml(titulo)} — ${items.length} cliente(s)</div>
      <div class="tbl-wrap"><table style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead><tr style="background:var(--card)"><th style="text-align:left;padding:.4rem .5rem">Cliente</th><th style="text-align:right;padding:.4rem .5rem">RX</th><th style="text-align:left;padding:.4rem .5rem">OLT/PON</th><th style="text-align:left;padding:.4rem .5rem">Dirección</th><th style="text-align:left;padding:.4rem .5rem">Tel</th></tr></thead>
        <tbody>${items.map(o=>fila(o, critica)).join('')}</tbody></table></div></div>`;
  };
  return `<div class="card" style="margin-bottom:1rem">
    <div class="stitle">🔴 ONU individuales con señal fuera de rango</div>
    ${tabla('🟣 SATURADA — más de -8 dBm (exceso de luz, falta atenuación)',
            d.saturadas || [], true, '#9676F1')}
    ${tabla('🔴 CRÍTICA — &lt; -29 dBm', d.criticas, true, '#E0605F')}
    ${tabla('⚠ Baja — entre -26 y -29 dBm', d.bajas, false, '#E08063')}
  </div>`;
}

// ── 3) Limpieza: ONUs de clientes de baja, rescindidos o en trámite ──
// Reemplaza al viejo /api/onus/limpieza, que sólo veía 'baja' y 'rescision'.
// Ahora incluye 'pte_rescision' y ordena por antigüedad, que es el criterio
// con el que realmente se decide qué limpiar primero.

let _limpiezaItems = [];        // última respuesta, para armar la exportación

const _LIMP_ETIQUETA = {
  baja: 'BAJA', rescision: 'RESCINDIDO', pte_rescision: 'PTE. RESCISIÓN'
};

function _seccionLimpieza(d){
  if(!d) return '';
  _limpiezaItems = d.items || [];
  const r = d.resumen || {};
  if(!_limpiezaItems.length){
    return `<div class="card"><div style="color:#4FB3AA;padding:.3rem">🧹 Sin ONUs de clientes dados de baja en las OLT.</div></div>`;
  }

  const filas = _limpiezaItems.map((o, i) => {
    const est = _LIMP_ETIQUETA[o.estado_comercial] || (o.estado_comercial || '').toUpperCase();
    const colorEst = o.en_tramite ? '#E0A838' : '#E0605F';
    const dias = o.dias_desde_cambio;
    return `<tr${o.antigua ? ' style="background:rgba(224,96,95,.07)"' : ''}>
      <td style="padding:.35rem .4rem"><input type="checkbox" class="limp-chk" data-idx="${escHtml(i)}"></td>
      <td style="padding:.35rem .5rem">
        <b${o.cliente_id ? ` style="cursor:pointer;text-decoration:underline" onclick="openModalCliente(${escHtml(o.cliente_id)})"` : ''}>${escHtml(o.nombre || ('#' + (o.nro_cliente || '?')))}</b>
        ${o.nro_cliente ? `<span style="color:var(--txt2)"> #${escHtml(o.nro_cliente)}</span>` : ''}</td>
      <td style="padding:.35rem .5rem"><span style="background:${colorEst};color:#fff;font-size:.66rem;padding:.1rem .4rem;border-radius:8px;white-space:nowrap">${escHtml(est)}</span></td>
      <td style="padding:.35rem .5rem;font-family:monospace;white-space:nowrap">${escHtml(o.ubicacion)}</td>
      <td style="padding:.35rem .5rem;font-family:monospace;font-size:.72rem">${escHtml(o.serial || '—')}</td>
      <td style="padding:.35rem .5rem;white-space:nowrap">${escHtml(o.fecha_estado ? String(o.fecha_estado).slice(0,10) : '—')}</td>
      <td style="padding:.35rem .5rem;text-align:right;white-space:nowrap${o.antigua ? ';color:#E0605F;font-weight:600' : ''}">${dias != null ? escHtml(dias) + ' d' : '—'}</td>
      <td style="padding:.35rem .5rem">${o.online ? '<span style="color:#4FB3AA">activa en OLT</span>' : '<span style="color:var(--txt2)">sin señal</span>'}</td>
    </tr>`;
  }).join('');

  return `<div class="card" style="border:1px solid #E0A838">
    <div class="stitle" style="color:#E0A838">🧹 ONUs a limpiar de las OLT — ${escHtml(r.total ?? _limpiezaItems.length)}
      <span style="margin-left:auto;font-weight:400;font-size:.72rem;color:var(--txt2)">
        ${escHtml(r.confirmadas ?? 0)} confirmadas · ${escHtml(r.en_tramite ?? 0)} en trámite ·
        ${escHtml(r.antiguas ?? 0)} con más de 90 días · ${escHtml(r.online ?? 0)} todavía activas</span>
    </div>

    <div class="alert-box warn" style="margin-bottom:.6rem;font-size:.78rem">
      <b>Pucará no da de baja nada en la OLT.</b> Este listado es para revisar y planificar la limpieza:
      la baja se ejecuta a mano en la OLT. Verificá cada caso antes de tocar nada — un
      <b>Pendiente de rescisión</b> todavía puede volver atrás, y borrar su ONU deja al cliente sin servicio.
    </div>

    <div style="display:flex;gap:.4rem;align-items:center;margin-bottom:.5rem;flex-wrap:wrap">
      <button class="btn btn-gray btn-sm" onclick="limpMarcarTodo(true)">Seleccionar todo</button>
      <button class="btn btn-gray btn-sm" onclick="limpMarcarTodo(false)">Limpiar selección</button>
      <button class="btn btn-prim btn-sm" onclick="limpCopiarSeleccion()">📋 Copiar selección</button>
      <button class="btn btn-gray btn-sm" onclick="limpExportarSeleccion()">⬇ Exportar CSV</button>
      <span style="font-size:.72rem;color:var(--txt2)">Para llevar la lista a la sesión de la OLT.</span>
    </div>

    <div class="tbl-wrap" style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.8rem">
      <thead><tr style="background:var(--card)">
        <th style="padding:.35rem .4rem"></th>
        <th style="text-align:left;padding:.35rem .5rem">Cliente</th>
        <th style="text-align:left;padding:.35rem .5rem">Estado comercial</th>
        <th style="text-align:left;padding:.35rem .5rem">OLT · PON:ONU</th>
        <th style="text-align:left;padding:.35rem .5rem">Serial</th>
        <th style="text-align:left;padding:.35rem .5rem">Fecha</th>
        <th style="text-align:right;padding:.35rem .5rem">Antigüedad</th>
        <th style="text-align:left;padding:.35rem .5rem">En OLT</th>
      </tr></thead>
      <tbody>${filas}</tbody></table></div></div>`;
}

function limpMarcarTodo(valor){
  document.querySelectorAll('.limp-chk').forEach(c => { c.checked = valor; });
}

function _limpSeleccion(){
  return Array.from(document.querySelectorAll('.limp-chk:checked'))
    .map(c => _limpiezaItems[parseInt(c.dataset.idx, 10)])
    .filter(Boolean);
}

function _limpFilasTexto(sel){
  return sel.map(o => [
    o.nro_cliente || '', o.nombre || '', o.estado_comercial || '',
    o.olt_nombre || '', o.pon ?? '', o.onu ?? '', o.serial || '',
    o.fecha_estado || '', o.dias_desde_cambio ?? ''
  ]);
}

const _LIMP_CABECERA = ['nro_cliente','nombre','estado','olt','pon','onu','serial','fecha_estado','dias'];

async function limpCopiarSeleccion(){
  const sel = _limpSeleccion();
  if(!sel.length){ alert('⚠️ No seleccionaste ninguna ONU'); return; }
  const txt = sel.map(o => `${o.ubicacion}\t${o.serial || '—'}\t${o.nombre || ''}`).join('\n');
  try{
    await navigator.clipboard.writeText(txt);
    toast(`${sel.length} ONU copiadas al portapapeles`, 'ok');
  }catch(e){
    alert('No se pudo copiar automáticamente. Usá "Exportar CSV".');
  }
}

function limpExportarSeleccion(){
  const sel = _limpSeleccion();
  if(!sel.length){ alert('⚠️ No seleccionaste ninguna ONU'); return; }
  // Comillas dobles escapadas: un nombre con coma no debe partir la columna.
  const csv = [_LIMP_CABECERA].concat(_limpFilasTexto(sel))
    .map(f => f.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['﻿' + csv], {type:'text/csv;charset=utf-8'}));
  const a = document.createElement('a');
  a.href = url;
  a.download = `onus_a_limpiar_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
