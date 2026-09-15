/* ════════════════════════════════════════════════════════
   reclamos_tecnicos.js — Pestaña "Reclamos" del modal del cliente
   y administración de los catálogos (fases 2 y 3).

   Consume /api/v2/reclamos. NO tiene nada que ver con reclamos.js,
   que muestra los tickets espejados de Tero: aquél registra el
   contacto del cliente; éste registra qué falló y qué se hizo, que
   es lo que alimenta la analítica.
   ════════════════════════════════════════════════════════ */

let _rtCatalogos = null;      // {causas:[], resoluciones:[]} — se cachea por sesión

async function _rtCargarCatalogos(forzar){
  if(_rtCatalogos && !forzar) return _rtCatalogos;
  _rtCatalogos = await api('/api/v2/reclamos/catalogos') || {causas:[], resoluciones:[]};
  return _rtCatalogos;
}

function _rtOpciones(items, vacio){
  return `<option value="">${escHtml(vacio)}</option>` +
    (items || []).map(i => `<option value="${escHtml(i.id)}">${escHtml(i.nombre)}</option>`).join('');
}

/* ── Pestaña del modal del cliente ────────────────────────────── */

async function cargarReclamosCliente(){
  const cont = document.getElementById('mcli-rec-cont');
  const id = document.getElementById('mcli-id').value;
  if(!cont || !id) return;
  cont.innerHTML = '<div style="color:var(--txt2);padding:.5rem">Cargando…</div>';

  const [cat, stats, historial] = await Promise.all([
    _rtCargarCatalogos(),
    api(`/api/v2/reclamos/cliente/${id}/estadisticas`),
    api(`/api/v2/reclamos/cliente/${id}`)
  ]);
  if(!stats){ cont.innerHTML = '<div class="alert-box warn">No se pudo leer el historial de reclamos.</div>'; return; }

  cont.innerHTML =
    _rtFormAlta(cat) +
    _rtKpis(stats) +
    `<div class="grid-2" style="gap:.8rem;align-items:start;margin:.8rem 0">
       <div>${v2Seccion('🏷 Por causa', v2Barras(stats.por_causa, {vacio:'Todavía sin causas registradas'}))}</div>
       <div>${v2Seccion('🛠 Por resolución', v2Barras(stats.por_resolucion, {vacio:'Todavía sin resoluciones registradas'}))}</div>
     </div>` +
    _rtHistorial(historial || [], cat);
}

function _rtKpis(s){
  return v2KpiGrid([
    v2Kpi(s.total, 'Reclamos', '#5B9BD5'),
    v2Kpi(s.abiertos, 'Abiertos', s.abiertos ? '#E0A838' : '#4FB3AA'),
    v2Kpi(v2Duracion(s.mttr_minutos), 'Tiempo medio de resolución', '#9676F1',
          'MTTR: promedio entre el alta y el cierre de los reclamos cerrados'),
    v2Kpi(s.mtbf_dias != null ? s.mtbf_dias + ' d' : '—', 'Tiempo medio entre reclamos', '#E08063',
          'MTBF: promedio entre un reclamo y el siguiente. Con un solo reclamo no hay intervalo que medir.'),
    v2Kpi(s.dias_desde_ultimo != null ? s.dias_desde_ultimo + ' d' : '—', 'Desde el último', '#566B84')
  ]);
}

function _rtFormAlta(cat){
  return `<div style="background:var(--surf2);border:1px solid var(--brd);border-radius:8px;padding:.7rem;margin-bottom:.8rem">
    <div style="font-weight:600;font-size:.85rem;margin-bottom:.5rem">➕ Registrar un reclamo</div>
    <div class="form-row">
      <div><label>Causa</label><select id="rt-causa">${_rtOpciones(cat.causas, '— Sin tipificar —')}</select></div>
      <div><label>Técnico asignado</label><input id="rt-tecnico" placeholder="Nombre del técnico"></div>
    </div>
    <div style="margin-top:.4rem"><label>Observaciones</label>
      <textarea id="rt-obs" rows="2" placeholder="Qué reportó el cliente…"></textarea></div>
    <div style="margin-top:.5rem;display:flex;align-items:center;gap:.5rem">
      <button class="btn btn-prim btn-sm" onclick="rtRegistrar()">Registrar</button>
      <span style="font-size:.72rem;color:var(--txt2)">Se guarda el AP, la OLT y el PON que el cliente tiene ahora.</span>
    </div>
  </div>`;
}

/* El contexto de red se copia al reclamo: si mañana el cliente se muda de AP,
   este reclamo tiene que seguir contando contra el AP que falló hoy. */
function _rtContextoRed(){
  const val = id => (document.getElementById(id)?.value || '').trim();
  const oltNombre = val('mcli-olt-nombre');
  const olt = (typeof oltData !== 'undefined' && Array.isArray(oltData))
    ? oltData.find(o => (o.nombre || '').toLowerCase() === oltNombre.toLowerCase())
    : null;
  const pon = parseInt(val('mcli-olt-puerto'), 10);
  return {
    ap_nombre: val('mcli-ap') || null,
    ap_id: parseInt(val('mcli-torre'), 10) || null,
    olt_id: olt ? olt.id : null,
    pon: isNaN(pon) ? null : pon,
    tipo_servicio: val('mcli-tipo') || null
  };
}

async function rtRegistrar(){
  const id = document.getElementById('mcli-id').value;
  if(!id) return;
  const r = await api('/api/v2/reclamos', 'POST', {
    cliente_id: parseInt(id, 10),
    causa_id: parseInt(document.getElementById('rt-causa').value, 10) || null,
    tecnico: document.getElementById('rt-tecnico').value.trim() || null,
    observaciones: document.getElementById('rt-obs').value.trim() || null,
    contexto_red: _rtContextoRed()
  });
  if(!r || r.error){ alert('❌ ' + ((r && r.error) || 'No se pudo registrar el reclamo')); return; }
  toast('Reclamo registrado', 'ok');
  cargarReclamosCliente();
}

function _rtHistorial(lista, cat){
  const filas = lista.map(r => {
    const abierto = r.estado !== 'cerrado' && r.estado !== 'anulado';
    const color = abierto ? '#E0A838' : '#4FB3AA';
    const acciones = abierto
      ? `<button class="btn btn-gray btn-sm" onclick="rtAbrirCierre(${escHtml(r.id)})">Cerrar</button>`
      : escHtml(r.resolucion || '—');
    return `<tr style="border-top:1px solid var(--brd)">
      <td style="padding:.35rem;white-space:nowrap">${escHtml(v2Fecha(r.fecha_alta))}</td>
      <td style="padding:.35rem">${escHtml(r.causa || '—')}</td>
      <td style="padding:.35rem"><span style="color:${color};font-weight:600">${escHtml(r.estado)}</span></td>
      <td style="padding:.35rem">${escHtml(r.tecnico || '—')}</td>
      <td style="padding:.35rem;text-align:right;white-space:nowrap">${escHtml(v2Duracion(r.minutos_resolucion))}</td>
      <td style="padding:.35rem">${escHtml(r.usuario_alta)}</td>
      <td style="padding:.35rem">${acciones}</td>
    </tr>` +
    (r.observaciones ? `<tr><td colspan="7" style="padding:0 .35rem .4rem;font-size:.74rem;color:var(--txt2);white-space:pre-wrap">${escHtml(r.observaciones)}</td></tr>` : '');
  }).join('');

  // El desplegable de resolución vive fuera de la tabla: se rellena al cerrar.
  return v2Seccion('📜 Historial', v2Tabla(
    ['Fecha', 'Causa', 'Estado', 'Técnico', {txt:'Resolución', derecha:true}, 'Registró', ''],
    filas, 'Este cliente no tiene reclamos registrados.'
  )) + `<div id="rt-cierre-slot" data-resoluciones='${escHtml(JSON.stringify((cat.resoluciones||[]).map(x=>({id:x.id,nombre:x.nombre}))))}'></div>`;
}

function rtAbrirCierre(reclamoId){
  const slot = document.getElementById('rt-cierre-slot');
  let resoluciones = [];
  try{ resoluciones = JSON.parse(slot.dataset.resoluciones || '[]'); }catch(e){}
  slot.innerHTML = `<div style="background:var(--surf2);border:1px solid var(--brd);border-radius:8px;padding:.7rem;margin-top:.5rem">
    <div style="font-weight:600;font-size:.85rem;margin-bottom:.5rem">Cerrar reclamo #${escHtml(reclamoId)}</div>
    <div class="form-row">
      <div><label>Resolución</label><select id="rt-resol">${_rtOpciones(resoluciones, '— Sin especificar —')}</select></div>
      <div><label>Nota de cierre</label><input id="rt-cierre-obs" placeholder="Qué se hizo"></div>
    </div>
    <div style="margin-top:.5rem;display:flex;gap:.4rem">
      <button class="btn btn-prim btn-sm" onclick="rtCerrar(${escHtml(reclamoId)})">Confirmar cierre</button>
      <button class="btn btn-gray btn-sm" onclick="document.getElementById('rt-cierre-slot').innerHTML=''">Cancelar</button>
    </div>
  </div>`;
  slot.scrollIntoView({behavior:'smooth', block:'nearest'});
}

async function rtCerrar(reclamoId){
  const r = await api(`/api/v2/reclamos/${reclamoId}/cerrar`, 'POST', {
    resolucion_id: parseInt(document.getElementById('rt-resol').value, 10) || null,
    observaciones: document.getElementById('rt-cierre-obs').value.trim() || null
  });
  if(!r || r.error){ alert('❌ ' + ((r && r.error) || 'No se pudo cerrar')); return; }
  toast('Reclamo cerrado', 'ok');
  cargarReclamosCliente();
}

/* ── Motor de análisis (sección Reclamos) ─────────────────────── */

async function loadAnaliticaReclamos(){
  const cont = document.getElementById('rta-cont');
  if(!cont) return;
  const dias = document.getElementById('rta-dias')?.value ?? '90';
  cont.innerHTML = '<div style="color:var(--txt2);padding:.5rem">Calculando…</div>';

  const d = await api('/api/v2/reclamos/analitica' + (dias ? `?dias=${encodeURIComponent(dias)}` : '?dias=0'));
  if(!d){ cont.innerHTML = '<div class="alert-box warn">No se pudo calcular la analítica.</div>'; return; }

  const totalCausas = (d.por_causa || []).reduce((a, c) => a + (c[1] || 0), 0);
  if(!totalCausas && !(d.top_clientes || []).length){
    cont.innerHTML = '<div class="alert-box info">Todavía no hay reclamos técnicos cargados en el período. Se cargan desde la pestaña <b>Reclamos</b> de la ficha del cliente.</div>';
    return;
  }

  cont.innerHTML =
    v2KpiGrid([
      v2Kpi(totalCausas, 'Reclamos tipificados', '#5B9BD5'),
      v2Kpi(v2Duracion(d.mttr_minutos), 'MTTR global', '#9676F1',
            'Tiempo medio de resolución de los reclamos cerrados en el período'),
      v2Kpi((d.tecnicos || []).length, 'Técnicos con carga', '#4FB3AA')
    ]) +
    `<div class="grid-2" style="gap:.9rem;align-items:start;margin-top:.9rem">
      <div>${v2Seccion('🏷 Por causa', v2Barras(d.por_causa))}</div>
      <div>${v2Seccion('🛠 Por resolución', v2Barras(d.por_resolucion))}</div>
      <div>${v2Seccion('👥 Clientes con más reclamos', _rtaRanking(d.top_clientes, 'openModalCliente'))}</div>
      <div>${v2Seccion('📡 APs con más reclamos', v2Barras(_rtaPares(d.top_aps), {color:'#E08063'}))}</div>
      <div>${v2Seccion('💡 PON con más incidencias', v2Barras(_rtaPares(d.top_pon), {color:'#E0A838', anchoEtiqueta:160}))}</div>
      <div>${v2Seccion('🖥 OLT con más incidencias', v2Barras(_rtaPares(d.top_olt), {color:'#5B9BD5'}))}</div>
     </div>` +
    v2Seccion('🧰 Tasa de resolución por técnico', _rtaTecnicos(d.tecnicos));
}

function _rtaPares(items){
  return (items || []).map(i => [i.nombre, i.total]);
}

/* Igual que v2Barras pero con la fila enlazada a la ficha del cliente. */
function _rtaRanking(items, fnAbrir){
  items = items || [];
  if(!items.length) return '<div style="color:var(--txt2);font-size:.8rem">Sin datos</div>';
  const max = Math.max(...items.map(i => i.total), 1);
  return items.slice(0, 12).map(i => {
    const clic = i.id ? ` style="cursor:pointer" onclick="${escJs(fnAbrir)}(${escHtml(i.id)})"` : '';
    return `<div${clic} style="display:flex;align-items:center;gap:.5rem;margin-bottom:.3rem;font-size:.78rem${i.id ? ';cursor:pointer' : ''}">
      <span style="min-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(i.nombre)}">${escHtml(i.nombre)}</span>
      <div style="flex:1;background:var(--card);border-radius:3px;height:13px"><div style="background:#C56B8E;height:100%;border-radius:3px;width:${Math.round(i.total/max*100)}%"></div></div>
      <b style="min-width:32px;text-align:right">${escHtml(i.total)}</b>
    </div>`;
  }).join('');
}

function _rtaTecnicos(items){
  const filas = (items || []).map(t => {
    const pct = t.extra ?? 0;
    const color = pct >= 90 ? '#4FB3AA' : pct >= 70 ? '#E0A838' : '#E0605F';
    return `<tr style="border-top:1px solid var(--brd)">
      <td style="padding:.35rem .5rem"><b>${escHtml(t.nombre)}</b></td>
      <td style="padding:.35rem .5rem;text-align:right">${escHtml(t.total)}</td>
      <td style="padding:.35rem .5rem;text-align:right;color:${color};font-weight:600">${escHtml(pct)} %</td>
      <td style="padding:.35rem .5rem;width:110px">
        <div style="background:var(--card);border-radius:3px;height:10px">
          <div style="background:${color};height:100%;border-radius:3px;width:${Math.max(0, Math.min(100, pct))}%"></div></div></td>
    </tr>`;
  }).join('');
  return v2Tabla(
    ['Técnico', {txt:'Asignados', derecha:true}, {txt:'Resueltos', derecha:true}, ''],
    filas, 'Ningún reclamo tiene técnico asignado todavía.'
  );
}

/* ── Administración de catálogos (Configuración) ──────────────── */

async function loadCatalogosReclamos(){
  const cont = document.getElementById('cfg-catalogos');
  if(!cont) return;
  const cat = await _rtCargarCatalogos(true);
  const incluirInactivos = document.getElementById('cfg-cat-inactivos')?.checked;
  const datos = incluirInactivos
    ? (await api('/api/v2/reclamos/catalogos?incluir_inactivos=1') || cat)
    : cat;

  cont.innerHTML = `<div class="grid-2" style="gap:.8rem;align-items:start">
    ${_rtPanelCatalogo('causas', '🏷 Causas del reclamo', datos.causas)}
    ${_rtPanelCatalogo('resoluciones', '🛠 Resoluciones', datos.resoluciones)}
  </div>`;
}

function _rtPanelCatalogo(tipo, titulo, items){
  const filas = (items || []).map(i => `<tr style="border-top:1px solid var(--brd);${i.activo ? '' : 'opacity:.45'}">
    <td style="padding:.3rem">${escHtml(i.nombre)}${i.activo ? '' : ' <span style="font-size:.68rem">(inactiva)</span>'}</td>
    <td style="padding:.3rem;text-align:right">${
      i.activo ? `<button class="btn btn-gray btn-sm" onclick="rtDesactivarCatalogo('${escJs(tipo)}',${escHtml(i.id)},'${escJs(i.nombre)}')">Desactivar</button>` : ''
    }</td></tr>`).join('');

  return `<div>
    <div style="font-weight:600;font-size:.86rem;margin-bottom:.45rem">${escHtml(titulo)}</div>
    <div style="display:flex;gap:.4rem;margin-bottom:.5rem">
      <input id="rt-nuevo-${escHtml(tipo)}" placeholder="Nueva opción…" style="flex:1">
      <button class="btn btn-prim btn-sm" onclick="rtCrearCatalogo('${escJs(tipo)}')">Agregar</button>
    </div>
    ${v2Tabla(['Opción', ''], filas, 'Catálogo vacío')}
  </div>`;
}

async function rtCrearCatalogo(tipo){
  const inp = document.getElementById('rt-nuevo-' + tipo);
  const nombre = (inp?.value || '').trim();
  if(!nombre){ alert('⚠️ Escribí un nombre'); return; }
  const r = await api(`/api/v2/reclamos/catalogos/${tipo}`, 'POST', {nombre});
  if(!r || r.error){ alert('❌ ' + ((r && r.error) || 'No se pudo agregar')); return; }
  inp.value = '';
  toast('Opción agregada', 'ok');
  loadCatalogosReclamos();
}

async function rtDesactivarCatalogo(tipo, id, nombre){
  const ok = await confirmar(
    `¿Desactivar "${nombre}"?\n\nNo se borra: los reclamos históricos la siguen mostrando. Sólo deja de ofrecerse al cargar reclamos nuevos.`,
    {titulo:'Desactivar opción', ok:'Desactivar', icono:'🚫', peligro:false}
  );
  if(!ok) return;
  const r = await api(`/api/v2/reclamos/catalogos/${tipo}/${id}`, 'DELETE');
  if(!r || r.error){ alert('❌ ' + ((r && r.error) || 'No se pudo desactivar')); return; }
  toast('Opción desactivada', 'ok');
  loadCatalogosReclamos();
}
