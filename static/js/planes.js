/* ========================================================
   planes.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadPlanDatalist(){
  const plans=await api('/api/abonos');
  if(!plans) return;
  document.getElementById('plan-datalist').innerHTML=plans.map(p=>`<option value="${p.nombre}">`).join('');
}

// ── NOTIF BADGE ──

// helper: bloque de datos técnicos para la orden (IP/PPPoE/abono según tipo)
function _datosTecnicoSvc(s){
  const tipo = (s.tipo_servicio||'').toLowerCase();
  const chips = [];
  if(s.cliente_plan) chips.push(`📋 <b>Abono:</b> ${escHtml(s.cliente_plan)}`);
  if(tipo === 'inalambrico'){
    if(s.ip_asignada) chips.push(`🌐 <b>IP:</b> ${escHtml(s.ip_asignada)}`);
  } else if(tipo === 'fibra'){
    if(s.cliente_nap) chips.push(`🔵 <b>NAP:</b> ${escHtml(s.cliente_nap)}`);
    if(s.olt_nombre) chips.push(`📡 OLT: ${escHtml(s.olt_nombre)}${s.olt_puerto?'/'+escHtml(s.olt_puerto):''}`);
  }
  if(s.pppoe_usuario) chips.push(`👤 <b>PPPoE:</b> ${escHtml(s.pppoe_usuario)}`);
  if(s.pppoe_clave) chips.push(`🔑 ${escHtml(s.pppoe_clave)}`);
  if(!chips.length) return '';
  return `<div style="margin-top:.4rem;padding:.4rem .6rem;background:var(--card);border-radius:6px;font-size:.76rem;line-height:1.6;display:flex;gap:.8rem;flex-wrap:wrap">${chips.join('<span style="color:#ccc">·</span>')}</div>`;
}

async function loadServicios(){
  const estado=document.getElementById('svc-estado').value;
  const tipo=document.getElementById('svc-tipo').value;
  const tecnico=document.getElementById('svc-tecnico').value;
  const prioridad=document.getElementById('svc-prioridad').value;
  const d=await api(`/api/servicios?estado=${estado}&tipo=${tipo}&tecnico=${encodeURIComponent(tecnico)}&prioridad=${prioridad}`);
  if(!d) return;
  const list=document.getElementById('svc-list');
  if(!d.length){list.innerHTML='<div class="empty">Sin órdenes para los filtros seleccionados</div>';return;}
  list.innerHTML=d.map(s=>`<div class="svc-card" style="margin-bottom:.5rem">
    <div class="svc-header">
      <span class="badge b-${escHtml(s.prioridad)}">${escHtml((s.prioridad||'').toUpperCase())}</span>
      <span class="svc-tipo">${escHtml(tipoSvcLabel(s.tipo))}</span>
      <span class="badge b-${escHtml(s.estado)}" style="margin-left:auto">${escHtml(estadoServLabel(s.estado))}</span>
    </div>
    <div style="display:flex;gap:1rem;font-size:.8rem;flex-wrap:wrap">
      <div><b>Cliente:</b> ${escHtml(s.cliente_nombre)||'—'}</div>
      ${s.cliente_tel?`<div>📞 ${escHtml(s.cliente_tel)}</div>`:''}
      ${s.cliente_dir?`<div>📍 ${escHtml(s.cliente_dir)}, ${escHtml(s.cliente_localidad)}</div>`:''}
      ${s.tecnico?`<div>👷 ${escHtml(s.tecnico)}</div>`:''}
      ${s.tiene_costo?`<div>💵 $${escHtml(s.costo)}</div>`:''}
    </div>
    ${s.descripcion?`<div style="font-size:.78rem;color:var(--txt2);margin-top:.3rem"><b>Problema:</b> ${escHtml(s.descripcion)}</div>`:''}
    ${_datosTecnicoSvc(s)}
    <div style="margin-top:.4rem;font-size:.72rem;color:var(--txt2)">${escHtml(s.fecha_creacion?.slice(0,16))||''}</div>
    <div style="margin-top:.4rem;display:flex;gap:.3rem">
      <button class="btn btn-gray btn-xs" onclick="openModalServicio(${s.id})">✏️ Editar</button>
      ${s.estado==='pendiente'?`<button class="btn btn-am btn-xs" onclick="cambiarEstadoSvc(${s.id},'en_proceso')">▶ Iniciar</button>`:''}
      ${s.estado==='en_proceso'?`<button class="btn btn-vd btn-xs" onclick="cambiarEstadoSvc(${s.id},'cerrado')">✓ Cerrar</button>`:''}
      ${(s.estado==='pendiente'||s.estado==='en_proceso')?`<button class="btn btn-am btn-xs" onclick="cancelarServicio(${s.id})">✕ Cancelar</button>`:''}
      ${s.estado==='cancelado'&&s.motivo_cancelacion?`<span style="font-size:.7rem;color:#c62828" title="${escAttr(s.motivo_cancelacion)}">✕ ${escHtml(s.motivo_cancelacion.slice(0,30))}${s.motivo_cancelacion.length>30?'...':''}</span>`:''}
      <button class="btn btn-rj btn-xs" onclick="deleteSvc(${s.id})">🗑</button>
    </div>
  </div>`).join('');
}

async function cambiarEstadoSvc(id, estado){
  await api(`/api/servicios/${id}`,'PUT',{estado,tipo:'',subtipo:'',tecnico:'',prioridad:'normal',costo:0,tiene_costo:0});
  loadServicios();
}

// ── Cancelar instalación/servicio con motivo ──
const MOTIVOS_CANCELACION = [
  'El cliente se cansó de esperar',
  'No hay manera de llegar con cable de FTTH',
  'La topografía no permite un buen enlace inalámbrico',
  'El cliente desistió / cambió de opinión',
  'Otro (especificar)',
];

async function cancelarServicio(id){
  // Mostrar diálogo con las causas comunes
  const opciones = MOTIVOS_CANCELACION.map((m,i)=>`${i+1}. ${m}`).join('\n');
  const sel = await pedirDato(
    `Cancelar este servicio.\n\nElegí el motivo (escribí el número):\n\n${opciones}`,
    '', {titulo:'Motivo de cancelación', tipo:'number'});
  if(sel === null) return;
  const idx = parseInt(sel) - 1;
  if(isNaN(idx) || idx < 0 || idx >= MOTIVOS_CANCELACION.length){
    alert('Número de motivo inválido'); return;
  }
  let motivo = MOTIVOS_CANCELACION[idx];
  // Si es "Otro", pedir el detalle
  if(idx === MOTIVOS_CANCELACION.length - 1){
    const detalle = await pedirDato('Especificá el motivo:', '', {titulo:'Motivo'});
    if(!detalle) return;
    motivo = detalle;
  }
  const r = await api(`/api/servicios/${id}`, 'PUT', {estado:'cancelado', motivo_cancelacion:motivo,
    tipo:'',subtipo:'',tecnico:'',prioridad:'normal',costo:0,tiene_costo:0});
  if(r && r.ok){ toast('Servicio cancelado. Motivo registrado.', 'ok'); loadServicios(); }
  else alert(r?.error || 'No se pudo cancelar');
}

async function deleteSvc(id){
  if(!await confirmar('¿Eliminar esta orden?')) return;
  await api(`/api/servicios/${id}`,'DELETE');
  loadServicios();
}

let svcPreselCli=null;

function svcTipoChange(){
  const tipo=document.getElementById('msvc-tipo').value;
  document.getElementById('svc-costo-row').style.display=tipo==='service_con_costo'?'grid':'none';
}

async function saveServicio(){
  const id=document.getElementById('msvc-id').value;
  const tipo=document.getElementById('msvc-tipo').value;
  const data={
    cliente_id:document.getElementById('msvc-cli-id').value||null,
    tipo,
    subtipo:'',
    tecnico:document.getElementById('msvc-tecnico').value,
    prioridad:document.getElementById('msvc-prioridad').value,
    estado:document.getElementById('msvc-estado').value,
    costo:parseFloat(document.getElementById('msvc-costo').value)||0,
    tiene_costo:tipo==='service_con_costo'?1:0,
    descripcion:document.getElementById('msvc-desc').value,
    diagnostico:document.getElementById('msvc-diagnostico')?.value||'',
    solucion_aplicada:document.getElementById('msvc-solucion')?.value||'',
    observaciones:document.getElementById('msvc-obs').value
  };
  const r=await api(id?`/api/servicios/${id}`:'/api/servicios',id?'PUT':'POST',data);
  if(r?.ok||r?.id){closeModal('modal-servicio');loadServicios();loadTecnicos();}
  else alert('Error al guardar');
}

// ── OLTs ──

let stockInstData=[];

async function loadStock(){
  const d=await api('/api/stock');
  if(!d) return;
  stockData=d;
  stockInstData=d.instalado||[];
  renderStockInstalado(stockInstData);
  renderStockManual(d.manual||[]);
}

function filterStockInstalado(){
  const tipo=document.getElementById('stock-tipo-fil').value;
  const filtrado=tipo?stockInstData.filter(s=>s.tipo===tipo):stockInstData;
  renderStockInstalado(filtrado);
}

function renderStockInstalado(data){
  const list=document.getElementById('stock-instalado-list');
  if(!data.length){list.innerHTML='<div class="empty">Sin equipos registrados</div>';return;}
  list.innerHTML=data.map(s=>`<div class="stock-row">
    <span class="stock-icn">${s.tipo==='fibra'?'💡':'📡'}</span>
    <div class="stock-info">
      <div class="stock-modelo">${escHtml(s.modelo)}</div>
      <div class="stock-marca">${escHtml(s.marca)||'Sin marca'} | <span class="badge b-${escHtml(s.tipo)}">${escHtml(s.tipo)}</span></div>
      ${s.localidades?`<div style="font-size:.68rem;color:var(--txt2)">${escHtml(s.localidades)}</div>`:''}
    </div>
    <span class="stock-cnt">${s.cantidad}</span>
  </div>`).join('');
}

function renderStockManual(data){
  const list=document.getElementById('stock-manual-list');
  if(!data.length){list.innerHTML='<div class="empty">Sin stock cargado manualmente</div>';return;}
  list.innerHTML=data.map(s=>`<div class="stock-row">
    <span class="stock-icn">${s.tipo==='fibra'?'💡':s.tipo==='accesorio'?'🔩':'📡'}</span>
    <div class="stock-info">
      <div class="stock-modelo">${escHtml(s.modelo)}</div>
      <div class="stock-marca">${escHtml(s.marca)||'—'} | ${escHtml(s.descripcion)}</div>
    </div>
    <span class="stock-cnt">${s.cantidad}</span>
    <button class="btn btn-gray btn-xs" onclick="openModalStock(${s.id})">✏️</button>
  </div>`).join('');
}

async function saveStock(){
  const id=document.getElementById('mstock-id').value;
  const data={modelo:document.getElementById('mstock-modelo').value,
    marca:document.getElementById('mstock-marca').value,
    tipo:document.getElementById('mstock-tipo').value,
    cantidad:parseInt(document.getElementById('mstock-cant').value)||0,
    descripcion:document.getElementById('mstock-desc').value};
  if(!data.modelo.trim()){alert('El modelo es obligatorio');return;}
  const r=await api(id?`/api/stock/${id}`:'/api/stock',id?'PUT':'POST',data);
  if(r?.ok){closeModal('modal-stock');loadStock();}
  else alert('Error al guardar');
}

// ── BAJAS ──

async function loadAbonos(){
  const d=await api('/api/abonos');
  if(!d) return;
  const tbody=document.getElementById('abono-tbody');
  tbody.innerHTML=d.map(a=>`<tr>
    <td><b>${escHtml(a.nombre)}</b></td>
    <td><span class="badge b-${escHtml(a.tipo)}">${escHtml(a.tipo)}</span></td>
    <td>$${parseFloat(a.precio).toFixed(2)}</td>
    <td>${a.velocidad_bajada?escHtml(a.velocidad_bajada)+' Mbps':'—'}</td>
    <td>${a.velocidad_subida?escHtml(a.velocidad_subida)+' Mbps':'—'}</td>
    <td>${escHtml(a.descripcion)||'—'}</td>
    <td>
      <button class="btn btn-gray btn-xs" onclick="openModalAbono(${a.id})">✏️</button>
      <button class="btn btn-rj btn-xs" onclick="deleteAbono(${a.id})">🗑</button>
    </td>
  </tr>`).join('');
}

async function saveAbono(){
  const id=document.getElementById('mabo-id').value;
  const data={nombre:document.getElementById('mabo-nombre').value,
    tipo:document.getElementById('mabo-tipo').value,
    precio:parseFloat(document.getElementById('mabo-precio').value)||0,
    velocidad_bajada:parseInt(document.getElementById('mabo-bajada').value)||0,
    velocidad_subida:parseInt(document.getElementById('mabo-subida').value)||0,
    descripcion:document.getElementById('mabo-desc').value};
  if(!data.nombre.trim()){alert('El nombre es obligatorio');return;}
  const r=await api(id?`/api/abonos/${id}`:'/api/abonos',id?'PUT':'POST',data);
  if(r?.ok){closeModal('modal-abono');loadAbonos();loadPlanDatalist();}
  else alert('Error al guardar');
}

async function deleteAbono(id){
  if(!await confirmar('¿Eliminar este plan?')) return;
  await api(`/api/abonos/${id}`,'DELETE');
  loadAbonos();
}

// ── HISTORIAL ──

async function registrarSenal(){
  const nap=document.getElementById('msenal-nap').value;
  const dbm=parseFloat(document.getElementById('msenal-dbm').value);
  if(!nap||isNaN(dbm)){alert('Ingresá el nivel de señal');return;}
  const r=await api('/api/historial_senal','POST',{
    nap_nombre:nap, nivel_dbm:dbm,
    observaciones:document.getElementById('msenal-obs').value
  });
  if(r?.ok){
    document.getElementById('msenal-dbm').value='';
    document.getElementById('msenal-obs').value='';
    await cargarHistorialSenal(nap);
    loadNaps();
  }
}

function exportarHojaCorte(){
  const fecha=document.getElementById('ag-desde').value||new Date().toISOString().slice(0,10);
  const tecnico=document.getElementById('ag-tecnico').value||'';
  window.open(`/api/agenda/hoja_corte?fecha=${fecha}&tecnico=${encodeURIComponent(tecnico)}`,'_blank');
}

// Mini modal para reprogramar servicio
