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
      <span class="badge b-${s.prioridad}">${s.prioridad.toUpperCase()}</span>
      <span class="svc-tipo">${tipoSvcLabel(s.tipo)}</span>
      <span class="badge b-${s.estado}" style="margin-left:auto">${estadoServLabel(s.estado)}</span>
    </div>
    <div style="display:flex;gap:1rem;font-size:.8rem;flex-wrap:wrap">
      <div><b>Cliente:</b> ${s.cliente_nombre||'—'}</div>
      ${s.cliente_tel?`<div>📞 ${s.cliente_tel}</div>`:''}
      ${s.cliente_dir?`<div>📍 ${s.cliente_dir}, ${s.cliente_localidad||''}</div>`:''}
      ${s.tecnico?`<div>👷 ${s.tecnico}</div>`:''}
      ${s.tiene_costo?`<div>💵 $${s.costo}</div>`:''}
    </div>
    ${s.descripcion?`<div style="font-size:.78rem;color:var(--txt2);margin-top:.3rem">${s.descripcion}</div>`:''}
    <div style="margin-top:.4rem;font-size:.72rem;color:var(--txt2)">${s.fecha_creacion?.slice(0,16)||''}</div>
    <div style="margin-top:.4rem;display:flex;gap:.3rem">
      <button class="btn btn-gray btn-xs" onclick="openModalServicio(${s.id})">✏️ Editar</button>
      ${s.estado==='pendiente'?`<button class="btn btn-am btn-xs" onclick="cambiarEstadoSvc(${s.id},'en_proceso')">▶ Iniciar</button>`:''}
      ${s.estado==='en_proceso'?`<button class="btn btn-vd btn-xs" onclick="cambiarEstadoSvc(${s.id},'cerrado')">✓ Cerrar</button>`:''}
      <button class="btn btn-rj btn-xs" onclick="deleteSvc(${s.id})">🗑</button>
    </div>
  </div>`).join('');
}

async function cambiarEstadoSvc(id, estado){
  await api(`/api/servicios/${id}`,'PUT',{estado,tipo:'',subtipo:'',tecnico:'',prioridad:'normal',costo:0,tiene_costo:0});
  loadServicios();
}

async function deleteSvc(id){
  if(!confirm('¿Eliminar esta orden?')) return;
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
      <div class="stock-modelo">${s.modelo}</div>
      <div class="stock-marca">${s.marca||'Sin marca'} | <span class="badge b-${s.tipo}">${s.tipo}</span></div>
      ${s.localidades?`<div style="font-size:.68rem;color:var(--txt2)">${s.localidades}</div>`:''}
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
      <div class="stock-modelo">${s.modelo}</div>
      <div class="stock-marca">${s.marca||'—'} | ${s.descripcion||''}</div>
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
    <td><b>${a.nombre}</b></td>
    <td><span class="badge b-${a.tipo}">${a.tipo}</span></td>
    <td>$${parseFloat(a.precio).toFixed(2)}</td>
    <td>${a.velocidad_bajada?a.velocidad_bajada+' Mbps':'—'}</td>
    <td>${a.velocidad_subida?a.velocidad_subida+' Mbps':'—'}</td>
    <td>${a.descripcion||'—'}</td>
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
  if(!confirm('¿Eliminar este plan?')) return;
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
