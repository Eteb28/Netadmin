// ════════════════════════════════════════════════════════
// TÉCNICOS INTERIOR (tercerizados)
// ════════════════════════════════════════════════════════

function cambiarTabServicios(tab){
  document.getElementById('svc-pane-ordenes').style.display = tab==='ordenes' ? 'block' : 'none';
  document.getElementById('svc-pane-interior').style.display = tab==='interior' ? 'block' : 'none';
  const paneStats = document.getElementById('svc-pane-stats');
  if(paneStats) paneStats.style.display = tab==='stats' ? 'block' : 'none';
  document.getElementById('svctab-ordenes').classList.toggle('active', tab==='ordenes');
  document.getElementById('svctab-interior').classList.toggle('active', tab==='interior');
  const tabStats = document.getElementById('svctab-stats');
  if(tabStats) tabStats.classList.toggle('active', tab==='stats');
  document.getElementById('svctab-ordenes').style.borderBottomColor = tab==='ordenes' ? 'var(--prim)' : 'transparent';
  document.getElementById('svctab-interior').style.borderBottomColor = tab==='interior' ? 'var(--prim)' : 'transparent';
  if(tabStats) tabStats.style.borderBottomColor = tab==='stats' ? 'var(--prim)' : 'transparent';
  if(tab==='interior'){ loadTITecnicosSelect(); loadTITrabajos(); }
  if(tab==='stats'){ loadStatsServicios(); }
}

// ── Cargar técnicos en el filtro y en el modal ──
let _tiTecnicos = [];
let _tiTarifas = [];
async function loadTITecnicosSelect(){
  const data = await api('/api/tecnico_interior/personal');
  _tiTecnicos = data || [];
  const sel = document.getElementById('ti-filtro-tecnico');
  if(sel){
    const valorActual = sel.value;  // preservar la selección del usuario
    sel.innerHTML = '<option value="">Todos los técnicos</option>' +
      _tiTecnicos.map(t=>`<option value="${t.nombre}">${t.nombre}</option>`).join('');
    sel.value = valorActual;  // restaurar el filtro elegido
  }
}

// ── Listado de trabajos ──
async function loadTITrabajos(){
  const tec = document.getElementById('ti-filtro-tecnico')?.value || '';
  const mes = document.getElementById('ti-filtro-mes')?.value || '';
  const pago = document.getElementById('ti-filtro-pago')?.value || '';
  const params = new URLSearchParams();
  if(tec) params.set('tecnico', tec);
  if(mes) params.set('mes', mes);
  if(pago!=='') params.set('pagado', pago);
  const data = await api('/api/tecnico_interior/trabajos?'+params.toString());
  const cont = document.getElementById('ti-trabajos-list');
  if(!data || !data.length){
    cont.innerHTML = '<div style="color:#888;padding:1rem;text-align:center">Sin trabajos registrados con estos filtros</div>';
    return;
  }
  const fmt = n => '$'+(n||0).toLocaleString('es-AR');
  cont.innerHTML = `<table class="tbl"><thead><tr>
    <th>Fecha</th><th>Técnico</th><th>Tipo</th><th>Cliente</th><th>Monto</th><th>Realizado</th><th>Pago</th><th></th>
    </tr></thead><tbody>${data.map(t=>`
    <tr ${t.pagado?'style="opacity:.6"':''}>
      <td>${escHtml(t.fecha_trabajo)}</td>
      <td><b>${escHtml(t.tecnico)}</b></td>
      <td>${escHtml(t.tipo_trabajo)}${t.metros>0?`<br><small style="color:#1565c0">${escHtml(t.metros)} m de FO</small>`:''}</td>
      <td>${escHtml(t.cliente)||'—'}</td>
      <td>${fmt(t.monto)}</td>
      <td style="text-align:center">
        <input type="checkbox" ${t.realizado?'checked':''} ${t.pagado?'disabled':''}
          onchange="toggleRealizadoTI(${t.id})" title="${escAttr(t.realizado?('Verificado'+(t.realizado_por?' por '+t.realizado_por:'')):'Marcar como realizado')}"
          style="width:18px;height:18px;cursor:pointer">
      </td>
      <td>${t.pagado
        ? `<span class="badge b-activo" style="cursor:pointer" title="Clic para marcar pendiente" onclick="togglePagoTI(${t.id})">✓ Pagado</span>`
        : (t.realizado
            ? `<span class="badge b-pendiente" style="cursor:pointer" title="Clic para marcar pagado" onclick="togglePagoTI(${t.id})">Pagable</span>`
            : `<span class="badge" style="background:var(--surf2);color:#888" title="Falta verificar que esté realizado">Sin verificar</span>`)}</td>
      <td><button class="btn btn-gray btn-xs" onclick="editarTITrabajo(${t.id})">✏️</button></td>
    </tr>`).join('')}</tbody></table>`;
  _tiTrabajosData = data;
}
let _tiTrabajosData = [];

async function toggleRealizadoTI(id){
  const r = await api(`/api/tecnico_interior/trabajos/${id}/toggle_realizado`, 'POST');
  if(r && r.ok) loadTITrabajos();
  else { alert(r?.error || 'No se pudo cambiar'); loadTITrabajos(); }
}

async function togglePagoTI(id){
  const r = await api(`/api/tecnico_interior/trabajos/${id}/toggle_pago`, 'POST');
  if(r && r.ok) loadTITrabajos();
  else alert(r?.error || 'No se pudo cambiar el pago');
}

// ── Modal cargar/editar trabajo ──
async function openModalTITrabajo(){
  await loadTITecnicosSelect();
  if(_tiTarifas.length===0){ const t = await api('/api/tecnico_interior/tarifas'); _tiTarifas = t||[]; }
  document.getElementById('ti-trabajo-id').value = '';
  document.getElementById('tit-modal-title').textContent = 'Cargar trabajo';
  document.getElementById('tit-del').style.display = 'none';
  // Poblar selects
  document.getElementById('tit-tecnico').innerHTML = _tiTecnicos.map(t=>`<option value="${t.nombre}">${t.nombre}</option>`).join('') || '<option value="">— Cargá técnicos primero —</option>';
  document.getElementById('tit-tipo').innerHTML = _tiTarifas.map(t=>`<option value="${t.tipo_trabajo}" data-monto="${t.monto}" data-por-metro="${t.por_metro?1:0}">${t.tipo_trabajo} ${t.por_metro?'($'+(t.monto||0).toLocaleString('es-AR')+'/metro)':'($'+(t.monto||0).toLocaleString('es-AR')+')'}</option>`).join('');
  document.getElementById('tit-fecha').value = new Date().toISOString().slice(0,10);
  document.getElementById('tit-cliente').value = '';
  document.getElementById('tit-cliente-id').value = '';
  document.getElementById('tit-localidad').value = '';
  document.getElementById('tit-desc').value = '';
  actualizarMontoTI();
  document.getElementById('modal-ti-trabajo').style.display = 'flex';
}

// ── Búsqueda de cliente para vincular el trabajo ──
let _titClienteTimer = null;
function buscarClienteTI(q){
  document.getElementById('tit-cliente-id').value = ''; // resetea el vínculo al tipear
  clearTimeout(_titClienteTimer);
  const drop = document.getElementById('tit-cliente-drop');
  if(!q || q.length < 2){ drop.style.display='none'; return; }
  _titClienteTimer = setTimeout(async ()=>{
    const res = await api(`/api/clientes/buscar?q=${encodeURIComponent(q)}`);
    if(!res || !res.length){ drop.innerHTML='<div style="padding:.5rem;color:#999;font-size:.8rem">Sin resultados</div>'; drop.style.display='block'; return; }
    drop.innerHTML = res.map(c=>`
      <div onclick="seleccionarClienteTI(${c.id},'${escJs(c.nombre)}','${escJs(c.nro_cliente)}')"
           style="padding:.45rem .6rem;border-bottom:1px solid var(--brd);cursor:pointer;font-size:.82rem">
        <b style="color:#1565c0;font-family:monospace">#${escHtml(c.nro_cliente)||'s/n'}</b> ${escHtml(c.nombre)}
        <div style="font-size:.72rem;color:#888">${escHtml(c.localidad)} · ${escHtml(c.estado)}</div>
      </div>`).join('');
    drop.style.display='block';
  }, 300);
}

function seleccionarClienteTI(id, nombre, nro){
  document.getElementById('tit-cliente').value = `#${nro} ${nombre}`;
  document.getElementById('tit-cliente-id').value = id;
  document.getElementById('tit-cliente-drop').style.display = 'none';
}

function actualizarMontoTI(){
  const sel = document.getElementById('tit-tipo');
  const opt = sel.options[sel.selectedIndex];
  const tarifa = opt ? parseFloat(opt.getAttribute('data-monto')) || 0 : 0;
  const porMetro = opt && opt.getAttribute('data-por-metro') === '1';
  const wrapMetros = document.getElementById('tit-metros-wrap');
  const inputMonto = document.getElementById('tit-monto');
  const inputMetros = document.getElementById('tit-metros');
  if(porMetro){
    // Mostrar metros, calcular monto = metros × tarifa, monto en solo lectura
    wrapMetros.style.display = '';
    const metros = parseFloat(inputMetros.value) || 0;
    inputMonto.value = (metros * tarifa).toFixed(2);
    inputMonto.readOnly = true;
    inputMonto.style.background = 'var(--card)';
    inputMonto.title = `${metros} m × $${tarifa}/m`;
  } else {
    // Trabajo de monto fijo
    wrapMetros.style.display = 'none';
    inputMetros.value = '';
    inputMonto.value = tarifa || 0;
    inputMonto.readOnly = false;
    inputMonto.style.background = '';
    inputMonto.title = '';
  }
}

function editarTITrabajo(id){
  const t = _tiTrabajosData.find(x=>x.id===id);
  if(!t) return;
  openModalTITrabajo().then(()=>{
    document.getElementById('ti-trabajo-id').value = t.id;
    document.getElementById('tit-modal-title').textContent = 'Editar trabajo';
    document.getElementById('tit-tecnico').value = t.tecnico;
    document.getElementById('tit-tipo').value = t.tipo_trabajo;
    document.getElementById('tit-fecha').value = t.fecha_trabajo;
    document.getElementById('tit-cliente').value = t.cliente||'';
    document.getElementById('tit-cliente-id').value = t.cliente_id||'';
    document.getElementById('tit-localidad').value = t.localidad||'';
    document.getElementById('tit-desc').value = t.descripcion||'';
    document.getElementById('tit-monto').value = t.monto||0;
    document.getElementById('tit-metros').value = t.metros||'';
    actualizarMontoTI();  // refresca visibilidad de metros y cálculo
    document.getElementById('tit-del').style.display = 'block';
  });
}

async function guardarTITrabajo(){
  const id = document.getElementById('ti-trabajo-id').value;
  const data = {
    tecnico: document.getElementById('tit-tecnico').value,
    tipo_trabajo: document.getElementById('tit-tipo').value,
    monto: parseFloat(document.getElementById('tit-monto').value)||0,
    metros: parseFloat(document.getElementById('tit-metros').value)||0,
    cliente_id: document.getElementById('tit-cliente-id').value || null,
    fecha_trabajo: document.getElementById('tit-fecha').value,
    cliente: document.getElementById('tit-cliente').value,
    localidad: document.getElementById('tit-localidad').value,
    descripcion: document.getElementById('tit-desc').value,
  };
  if(!data.tecnico){ alert('Seleccioná un técnico'); return; }
  if(!data.fecha_trabajo){ alert('Indicá la fecha'); return; }
  const r = id
    ? await api(`/api/tecnico_interior/trabajos/${id}`, 'PUT', data)
    : await api('/api/tecnico_interior/trabajos', 'POST', data);
  if(r && r.ok){ closeModal('modal-ti-trabajo'); loadTITrabajos(); }
  else alert(r?.error || 'No se pudo guardar');
}

async function eliminarTITrabajo(){
  const id = document.getElementById('ti-trabajo-id').value;
  if(!id || !await confirmar('¿Eliminar este trabajo?')) return;
  const r = await api(`/api/tecnico_interior/trabajos/${id}`, 'DELETE');
  if(r && r.ok){ closeModal('modal-ti-trabajo'); loadTITrabajos(); }
}

// ── Reporte de pago ──
async function verReporteTI(){
  const mes = document.getElementById('ti-filtro-mes')?.value || '';
  const cont = document.getElementById('ti-reporte');
  const params = new URLSearchParams();
  if(mes) params.set('mes', mes);
  const data = await api('/api/tecnico_interior/reporte?'+params.toString());
  if(cont.style.display==='block'){ cont.style.display='none'; return; }
  const fmt = n => '$'+(n||0).toLocaleString('es-AR');
  if(!data || !data.length){
    cont.innerHTML = '<div style="color:#888;padding:1rem">Sin datos para el reporte</div>';
  } else {
    cont.innerHTML = `<div class="card" style="background:var(--card)">
      <b>📋 Reporte de pago ${mes||'(todos los meses)'}</b>
      <table class="tbl" style="margin-top:.5rem"><thead><tr>
        <th>Técnico</th><th>Trabajos</th><th>Total</th><th>Pagable (verificado)</th><th>Sin verificar</th><th></th>
      </tr></thead><tbody>${data.map(r=>`
        <tr>
          <td><b>${escHtml(r.tecnico)}</b></td>
          <td>${r.trabajos}</td>
          <td>${fmt(r.total)}</td>
          <td style="color:${r.pagable>0?'#2e7d32':'#888'};font-weight:700">${fmt(r.pagable)}</td>
          <td style="color:${r.sin_verificar>0?'#e65100':'#888'}">${fmt(r.sin_verificar)}</td>
          <td>${r.pagable>0?`<button class="btn btn-vd btn-xs" onclick="marcarPagadoTI('${escJs(r.tecnico)}')">✓ Pagar verificados</button>`:''}</td>
        </tr>`).join('')}</tbody></table>
      <div style="font-size:.7rem;color:#888;margin-top:.4rem">Solo se puede pagar lo verificado como realizado. "Sin verificar" no se paga hasta tildar el trabajo.</div>
    </div>`;
  }
  cont.style.display = 'block';
}

async function marcarPagadoTI(tecnico){
  const mes = document.getElementById('ti-filtro-mes')?.value || '';
  // Pedir fecha de pago y observaciones
  const hoy = new Date().toISOString().slice(0,10);
  const fecha = await pedirDato(`Fecha del pago a ${tecnico} (YYYY-MM-DD):`, hoy);
  if(!fecha) return;
  const obs = await pedirDato('Observaciones del pago (opcional):', '') || '';
  const r = await api('/api/tecnico_interior/pagar', 'POST', {tecnico, mes, fecha_pago:fecha, observaciones:obs});
  if(r && r.ok){
    if(await confirmar(`✓ Pago registrado: ${r.cantidad} trabajo(s), total $${(r.monto_total||0).toLocaleString('es-AR')}.\n\n¿Descargar el comprobante en PDF?`)){
      window.open(`/api/tecnico_interior/pagos/${r.pago_id}/pdf`, '_blank');
    }
    document.getElementById('ti-reporte').style.display='none';
    verReporteTI();
    loadTITrabajos();
  } else {
    alert(r?.error || 'No se pudo registrar el pago');
  }
}

// ── Historial de pagos ──
async function verHistorialPagos(){
  const cont = document.getElementById('ti-historial');
  if(cont.style.display==='block'){ cont.style.display='none'; return; }
  const tec = document.getElementById('ti-filtro-tecnico')?.value || '';
  const fecha = document.getElementById('ti-hist-fecha')?.value || '';
  const params = new URLSearchParams();
  if(tec) params.set('tecnico', tec);
  if(fecha) params.set('fecha', fecha);
  const data = await api('/api/tecnico_interior/pagos?'+params.toString());
  const fmt = n => '$'+(n||0).toLocaleString('es-AR');
  if(!data || !data.length){
    cont.innerHTML = '<div style="color:#888;padding:1rem">Sin pagos registrados con estos filtros</div>';
  } else {
    cont.innerHTML = `<div class="card" style="background:var(--card)">
      <b>💰 Historial de pagos</b>
      <table class="tbl" style="margin-top:.5rem"><thead><tr>
        <th>Fecha pago</th><th>Técnico</th><th>Período</th><th>Trabajos</th><th>Monto</th><th>Comprobante</th>
      </tr></thead><tbody>${data.map(p=>`
        <tr>
          <td><b>${p.fecha_pago||'—'}</b></td>
          <td>${p.tecnico}</td>
          <td style="font-size:.78rem">${p.periodo_desde||'—'} a ${p.periodo_hasta||'—'}</td>
          <td>${p.cantidad_trabajos}</td>
          <td style="font-weight:700">${fmt(p.monto_total)}</td>
          <td><button class="btn btn-gray btn-xs" onclick="window.open('/api/tecnico_interior/pagos/${p.id}/pdf','_blank')">📄 PDF</button></td>
        </tr>`).join('')}</tbody></table>
    </div>`;
  }
  cont.style.display = 'block';
}

// ── Gestión de técnicos (personal) ──
async function openTIPersonal(){
  const data = await api('/api/tecnico_interior/personal');
  const cont = document.getElementById('ti-personal-list');
  cont.innerHTML = (data||[]).map(t=>`
    <div style="display:flex;align-items:center;gap:.5rem;padding:.4rem 0;border-bottom:1px solid var(--brd)">
      <div style="flex:1"><b>${t.nombre}</b> ${t.localidad?`<small style="color:#888">— ${t.localidad}</small>`:''} ${t.telefono?`<small>📞 ${t.telefono}</small>`:''}</div>
      <button class="btn btn-rj btn-xs" onclick="eliminarTIPersonal(${t.id})">🗑</button>
    </div>`).join('') || '<small style="color:#888">Sin técnicos cargados</small>';
  document.getElementById('modal-ti-personal').style.display = 'flex';
}

async function agregarTIPersonal(){
  const nombre = document.getElementById('tip-nombre').value.trim();
  if(!nombre){ alert('Ingresá el nombre'); return; }
  const r = await api('/api/tecnico_interior/personal', 'POST', {
    nombre,
    telefono: document.getElementById('tip-tel').value.trim(),
    localidad: document.getElementById('tip-loc').value.trim(),
  });
  if(r && r.ok){
    document.getElementById('tip-nombre').value='';
    document.getElementById('tip-tel').value='';
    document.getElementById('tip-loc').value='';
    openTIPersonal();
    loadTITecnicosSelect();
  }
}

async function eliminarTIPersonal(id){
  if(!await confirmar('¿Eliminar este técnico de la lista?')) return;
  const r = await api(`/api/tecnico_interior/personal/${id}`, 'DELETE');
  if(r && r.ok){ openTIPersonal(); loadTITecnicosSelect(); }
}

// ── Gestión de tarifas ──
async function openTITarifas(){
  const data = await api('/api/tecnico_interior/tarifas');
  _tiTarifas = data || [];
  const cont = document.getElementById('ti-tarifas-list');
  cont.innerHTML = (data||[]).map(t=>`
    <div style="display:flex;align-items:center;gap:.5rem;padding:.4rem 0;border-bottom:1px solid var(--brd)">
      <div style="flex:1">${t.tipo_trabajo}${t.por_metro?' <span style="font-size:.7rem;background:var(--tint-azul);color:#1565c0;padding:1px 6px;border-radius:8px">por metro</span>':''}</div>
      <input type="number" id="tar-${t.id}" value="${t.monto||0}" style="width:110px;padding:.3rem;border:1px solid var(--brd);border-radius:5px" min="0">
      <span style="font-size:.75rem;color:#888;width:42px">${t.por_metro?'$/m':'$'}</span>
      <button class="btn btn-prim btn-xs" onclick="guardarTITarifa(${t.id})">Guardar</button>
    </div>`).join('');
  document.getElementById('modal-ti-tarifas').style.display = 'flex';
}

async function guardarTITarifa(id){
  const t = _tiTarifas.find(x=>x.id===id);
  const monto = parseFloat(document.getElementById('tar-'+id).value)||0;
  const r = await api(`/api/tecnico_interior/tarifas/${id}`, 'PUT', {tipo_trabajo:t.tipo_trabajo, monto, por_metro:t.por_metro?1:0});
  if(r && r.ok){ const el=document.getElementById('tar-'+id); el.style.background='var(--tint-verde)'; setTimeout(()=>el.style.background='',800); }
}

async function agregarTITarifa(){
  const tipo = document.getElementById('nueva-tarifa-tipo').value.trim();
  const monto = parseFloat(document.getElementById('nueva-tarifa-monto').value)||0;
  const porMetro = document.getElementById('nueva-tarifa-pormetro')?.checked ? 1 : 0;
  if(!tipo){ alert('Ingresá el tipo de trabajo'); return; }
  const r = await api('/api/tecnico_interior/tarifas', 'POST', {tipo_trabajo:tipo, monto, por_metro:porMetro});
  if(r && r.ok){
    document.getElementById('nueva-tarifa-tipo').value='';
    document.getElementById('nueva-tarifa-monto').value='';
    const chk=document.getElementById('nueva-tarifa-pormetro'); if(chk) chk.checked=false;
    openTITarifas();
  }
}

// ════════════════════════════════════════════════════════
// ESTADÍSTICAS por diagnóstico y solución
// ════════════════════════════════════════════════════════
async function loadStatsServicios(){
  const periodo = document.getElementById('stats-periodo')?.value || '12';
  const d = await api(`/api/estadisticas/problemas_recurrentes?periodo=${periodo}`);
  if(!d) return;
  const cob = document.getElementById('stats-cobertura');
  const totalClasif = (d.diagnosticos||[]).reduce((a,x)=>a+x.cantidad,0);
  if(cob){
    cob.innerHTML = d.sin_diagnostico
      ? `${totalClasif} servicios clasificados · <span style="color:#e65100">${d.sin_diagnostico} sin diagnóstico cargado</span>`
      : `${totalClasif} servicios clasificados`;
  }
  renderStatsBarras('stats-diagnosticos', d.diagnosticos, '#1565c0');
  renderStatsBarras('stats-soluciones', d.soluciones, '#2e7d32');
}

function renderStatsBarras(contId, items, color){
  const cont = document.getElementById(contId);
  if(!cont) return;
  if(!items || !items.length){
    cont.innerHTML = '<div style="color:#999;padding:.5rem;font-size:.82rem">Sin datos en este período</div>';
    return;
  }
  const max = Math.max(...items.map(x=>x.cantidad));
  cont.innerHTML = items.map(x=>{
    const pct = Math.round(x.cantidad/max*100);
    return `<div style="margin-bottom:.4rem">
      <div style="display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:.15rem">
        <span>${x.nombre}</span><b>${x.cantidad}</b>
      </div>
      <div style="background:var(--card);border-radius:4px;height:8px;overflow:hidden">
        <div style="background:${color};height:100%;width:${pct}%"></div>
      </div>
    </div>`;
  }).join('');
}

// ════════════════════════════════════════════════════════
// PRE-PAGO (conciliación antes de registrar el pago)
// ════════════════════════════════════════════════════════
async function verPrePago(){
  const tec = document.getElementById('ti-filtro-tecnico')?.value || '';
  const desde = document.getElementById('ti-prepago-desde')?.value || '';
  const hasta = document.getElementById('ti-prepago-hasta')?.value || '';
  if(!tec){ alert('Seleccioná un técnico en el filtro de arriba para generar el pre-pago'); return; }
  const params = new URLSearchParams({tecnico: tec});
  if(desde) params.set('desde', desde);
  if(hasta) params.set('hasta', hasta);
  const d = await api('/api/tecnico_interior/prepago?'+params.toString());
  const cont = document.getElementById('ti-prepago-resultado');
  if(!d || !d.trabajos || !d.trabajos.length){
    cont.innerHTML = '<div class="card" style="background:var(--tint-ambar)">No hay trabajos verificados (realizados y sin pagar) para ese técnico en ese rango.</div>';
    cont.style.display = 'block';
    return;
  }
  const fmt = n => '$'+(n||0).toLocaleString('es-AR');
  cont.innerHTML = `<div class="card" style="background:var(--card);border:1px dashed #f9a825">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem">
      <b>🧾 Pre-pago de ${escHtml(tec)} ${desde||hasta?`(${escHtml(desde||'inicio')} a ${escHtml(hasta||'hoy')})`:''}</b>
      <div style="display:flex;gap:.4rem">
        <button class="btn btn-gray btn-sm" onclick="window.open('/api/tecnico_interior/prepago/pdf?${params.toString()}','_blank')">📄 Descargar PDF</button>
        <button class="btn btn-vd btn-sm" onclick="confirmarPagoDesdePrepago('${escJs(tec)}','${desde}','${hasta}')">✓ Confirmar y pagar</button>
      </div>
    </div>
    <table class="tbl"><thead><tr><th>Fecha</th><th>Tipo</th><th>Cliente</th><th>Monto</th></tr></thead>
    <tbody>${d.trabajos.map(t=>`<tr><td>${t.fecha_trabajo||'—'}</td><td>${t.tipo_trabajo||''}</td><td>${t.cliente||'—'}</td><td>${fmt(t.monto)}</td></tr>`).join('')}
    <tr style="font-weight:700;background:var(--card)"><td colspan="3">TOTAL (${d.trabajos.length} trabajos)</td><td>${fmt(d.total)}</td></tr>
    </tbody></table>
    <div style="font-size:.74rem;color:var(--txt2);margin-top:.4rem">⚠ Esto es un pre-pago: todavía NO se registró. El técnico concilia con sus registros y, cuando da el OK, tocás "Confirmar y pagar".</div>
  </div>`;
  cont.style.display = 'block';
}

async function confirmarPagoDesdePrepago(tecnico, desde, hasta){
  if(!await confirmar(`¿Confirmás el pago a ${tecnico}? Esto registra el pago y genera el comprobante definitivo.`)) return;
  const hoy = new Date().toISOString().slice(0,10);
  const fecha = await pedirDato('Fecha del pago (YYYY-MM-DD):', hoy);
  if(!fecha) return;
  const obs = await pedirDato('Observaciones (opcional):', '') || '';
  const r = await api('/api/tecnico_interior/pagar', 'POST', {tecnico, desde, hasta, fecha_pago:fecha, observaciones:obs});
  if(r && r.ok){
    if(await confirmar(`✓ Pago registrado: ${r.cantidad} trabajo(s), total $${(r.monto_total||0).toLocaleString('es-AR')}.\n\n¿Descargar el comprobante definitivo?`)){
      window.open(`/api/tecnico_interior/pagos/${r.pago_id}/pdf`, '_blank');
    }
    document.getElementById('ti-prepago-resultado').style.display='none';
    loadTITrabajos();
  } else {
    alert(r?.error || 'No se pudo registrar el pago');
  }
}
