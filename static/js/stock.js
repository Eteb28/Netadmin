/* ========================================================
   stock.js — ERLAN NetAdmin
   Módulo de Stock: equipos individuales, movimientos, alertas
   ======================================================== */

let _stockResumen = null;
let _stockItems = [];

async function loadStockAvanzado(){
  const [resumen, items] = await Promise.all([
    api('/api/stock/resumen'),
    api('/api/stock/items?estado=deposito'),
  ]);
  _stockResumen = resumen;
  _stockItems = items || [];
  renderStockDashboard(resumen);
  renderStockItems(items);
}

function renderStockDashboard(r){
  const el = document.getElementById('stock-dashboard');
  if(!el || !r) return;
  const estados = r.por_estado || {};
  el.innerHTML = `
    <div class="fin-grid" style="margin-bottom:.8rem">
      <div class="fin-card green">
        <div class="fin-val">${estados.deposito||0}</div>
        <div class="fin-lbl">En depósito</div>
      </div>
      <div class="fin-card blue">
        <div class="fin-val">${estados.instalado||0}</div>
        <div class="fin-lbl">Instalados</div>
        <div class="fin-sub">${r.instalados_total} en clientes (${r.instalados_trackeados} trackeados)</div>
      </div>
      <div class="fin-card orange">
        <div class="fin-val">${r.pendientes_retiro}</div>
        <div class="fin-lbl">Pte. retiro</div>
        <div class="fin-sub">Rescindidos con equipo</div>
      </div>
      <div class="fin-card red">
        <div class="fin-val">${estados.baja||0}</div>
        <div class="fin-lbl">Dados de baja</div>
      </div>
    </div>
    ${r.stock_bajo?.length ? `
    <div style="background:var(--tint-ambar);border:1px solid #ff9800;border-radius:8px;padding:.5rem .8rem;margin-bottom:.6rem;font-size:.82rem">
      <b>⚠ Stock bajo:</b> ${r.stock_bajo.map(s=>`${escHtml(s.marca)} ${escHtml(s.modelo)} (${s.en_deposito} uds)`).join(' · ')}
    </div>` : ''}
    <div style="display:flex;gap:.8rem;flex-wrap:wrap;margin-bottom:.6rem">
      ${r.por_marca?.length ? `<div style="flex:1;min-width:200px">
        <b style="font-size:.8rem">Por marca (depósito):</b>
        ${r.por_marca.map(m=>`<div style="display:flex;justify-content:space-between;font-size:.78rem;padding:.15rem 0;border-bottom:1px solid var(--brd)"><span>${escHtml(m.marca)||'Sin marca'}</span><b>${m.cantidad}</b></div>`).join('')}
      </div>` : ''}
      ${r.por_tipo?.length ? `<div style="flex:1;min-width:200px">
        <b style="font-size:.8rem">Por tipo (depósito):</b>
        ${r.por_tipo.map(t=>`<div style="display:flex;justify-content:space-between;font-size:.78rem;padding:.15rem 0;border-bottom:1px solid var(--brd)"><span>${escHtml(t.tipo)||'Sin tipo'}</span><b>${t.cantidad}</b></div>`).join('')}
      </div>` : ''}
    </div>`;
}

function renderStockItems(items){
  const el = document.getElementById('stock-items-list');
  if(!el) return;
  if(!items || !items.length){
    el.innerHTML = '<div class="empty">Sin equipos en esta categoría</div>';
    return;
  }
  el.innerHTML = `<table class="fin-table">
    <thead><tr><th>Serie</th><th>Marca/Modelo</th><th>Tipo</th><th>Estado</th><th>Cliente</th><th>Acciones</th></tr></thead>
    <tbody>${items.map(i=>{
      const estadoColors = {deposito:'#2e7d32',instalado:'#1565c0',pend_retiro:'#e65100',baja:'#9e9e9e'};
      const color = estadoColors[i.estado] || '#666';
      return `<tr>
        <td style="font-family:monospace;font-size:.78rem">${escHtml(i.serie)||'—'}</td>
        <td><b>${escHtml(i.marca)}</b> ${escHtml(i.modelo)}<br><small style="color:#888">${escHtml(i.mac)}</small></td>
        <td>${escHtml(i.tipo)||'—'}</td>
        <td><span style="color:${color};font-weight:600;font-size:.78rem">${escHtml((i.estado||'').toUpperCase())}</span></td>
        <td>${i.cliente_nombre ? `${escHtml(i.cliente_nombre)}<br><small>${escHtml(i.nro_cliente)}</small>` : '—'}</td>
        <td style="white-space:nowrap">
          ${i.estado==='deposito' ? `<button class="btn btn-prim btn-xs" onclick="asignarItem(${i.id})">📦 Asignar</button>` : ''}
          ${i.estado==='instalado' ? `<button class="btn btn-am btn-xs" onclick="retirarItem(${i.id})">🔙 Retirar</button>` : ''}
          ${i.estado!=='baja' ? `<button class="btn btn-gray btn-xs" onclick="bajaItem(${i.id})">🗑</button>` : ''}
        </td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

async function filtrarStockItems(){
  const estado = document.getElementById('stock-fil-estado')?.value || '';
  const q = document.getElementById('stock-fil-q')?.value || '';
  const items = await api(`/api/stock/items?estado=${estado}&q=${encodeURIComponent(q)}`);
  renderStockItems(items);
}

// ── Acciones ──
async function asignarItem(id){
  const cli_id = await pedirDato('ID del cliente a asignar:');
  if(!cli_id) return;
  const r = await api(`/api/stock/items/${id}/asignar`, 'POST', {cliente_id: parseInt(cli_id)});
  if(r?.ok){ alert('✅ Equipo asignado'); loadStockAvanzado(); }
  else alert('Error: ' + (r?.error || 'No se pudo asignar'));
}

async function retirarItem(id){
  const motivo = await pedirDato('Motivo del retiro (opcional):') || '';
  const r = await api(`/api/stock/items/${id}/retirar`, 'POST', {motivo});
  if(r?.ok){ alert('✅ Equipo retirado al depósito'); loadStockAvanzado(); }
  else alert('Error: ' + (r?.error || ''));
}

async function bajaItem(id){
  const motivo = await pedirDato('Motivo de la baja:');
  if(!motivo) return;
  if(!await confirmar(`¿Dar de baja este equipo? Motivo: ${motivo}`)) return;
  const r = await api(`/api/stock/items/${id}/baja`, 'POST', {motivo});
  if(r?.ok){ alert('✅ Equipo dado de baja'); loadStockAvanzado(); }
}

// ── Modal nuevo equipo ──
function openModalNuevoEquipo(){
  document.getElementById('modal-stock-nuevo').style.display = 'flex';
  ['msi-serie','msi-mac','msi-modelo','msi-marca','msi-obs'].forEach(id=>{
    const e = document.getElementById(id); if(e) e.value = '';
  });
  document.getElementById('msi-tipo').value = 'fibra';
}

async function saveNuevoEquipo(){
  const data = {
    serie: document.getElementById('msi-serie').value.trim(),
    mac: document.getElementById('msi-mac').value.trim(),
    modelo: document.getElementById('msi-modelo').value.trim(),
    marca: document.getElementById('msi-marca').value.trim(),
    tipo: document.getElementById('msi-tipo').value,
    observaciones: document.getElementById('msi-obs').value.trim(),
  };
  if(!data.serie && !data.modelo){ alert('Serie o modelo requerido'); return; }
  const r = await api('/api/stock/items', 'POST', data);
  if(r?.ok){
    closeModal('modal-stock-nuevo');
    loadStockAvanzado();
  } else alert('Error: ' + (r?.error || ''));
}

// ── Pendientes retiro ──
async function loadPendientesRetiro(){
  const data = await api('/api/stock/pendientes_retiro');
  const el = document.getElementById('stock-pend-retiro');
  if(!el || !data) return;
  el.innerHTML = `<div class="fin-section" style="margin-top:.8rem">
    <h3>🔙 Equipos pendientes de retiro (${data.length})</h3>
    ${data.length ? `<table class="fin-table">
      <thead><tr><th>Cliente</th><th>Equipo</th><th>Localidad</th><th>Estado</th><th></th></tr></thead>
      <tbody>${data.map(d=>`<tr>
        <td><b>${escHtml(d.nombre)}</b><br><small>${escHtml(d.nro_cliente)}</small></td>
        <td>${escHtml(d.equipo_marca)} ${escHtml(d.equipo_modelo)}<br><small style="font-family:monospace">${escHtml(d.equipo_serie)}</small></td>
        <td>${escHtml(d.localidad)||'—'}</td>
        <td>${escHtml(estadoLabel(d.estado))}</td>
        <td>${d.lat&&d.lng?`<a href="https://www.google.com/maps/dir/?api=1&destination=${d.lat},${d.lng}" target="_blank" class="btn btn-gray btn-xs">🗺️</a>`:''}</td>
      </tr>`).join('')}</tbody>
    </table>` : '<div class="empty">Sin equipos pendientes de retiro</div>'}
  </div>`;
}

// ── Historial movimientos ──
async function loadMovimientos(){
  const data = await api('/api/stock/movimientos?limit=30');
  const el = document.getElementById('stock-movimientos');
  if(!el || !data) return;
  const tipoIcons = {ingreso:'📥',asignacion:'📦',retiro:'🔙',baja:'🗑'};
  el.innerHTML = `<div class="fin-section" style="margin-top:.8rem">
    <h3>📜 Últimos movimientos</h3>
    <table class="fin-table">
      <thead><tr><th></th><th>Equipo</th><th>Descripción</th><th>Usuario</th><th>Fecha</th></tr></thead>
      <tbody>${data.map(m=>`<tr>
        <td>${tipoIcons[m.tipo]||'•'}</td>
        <td style="font-size:.78rem">${escHtml(m.marca)} ${escHtml(m.modelo)}<br><small style="font-family:monospace">${escHtml(m.serie)}</small></td>
        <td style="font-size:.78rem">${escHtml(m.descripcion)}</td>
        <td style="font-size:.75rem;color:#888">${escHtml(m.usuario)}</td>
        <td style="font-size:.72rem;color:#888;white-space:nowrap">${(m.fecha||'').replace('T',' ').slice(0,16)}</td>
      </tr>`).join('')}</tbody>
    </table>
  </div>`;
}

// ── Importar desde clientes (una vez) ──
async function importarDesdeClientes(){
  if(!await confirmar('Esto importará todos los equipos de clientes actuales al stock. ¿Continuar?')) return;
  const r = await api('/api/stock/importar_desde_clientes', 'POST');
  if(r?.ok){
    alert(`✅ Importados: ${r.importados} equipos (${r.saltados} ya existían)`);
    loadStockAvanzado();
  } else alert('Error: ' + (r?.error || ''));
}

// ════════════════════════════════════════════════════════
// PANEL DE INVENTARIO POR CANTIDAD (vista simple, 3 columnas)
// ════════════════════════════════════════════════════════
let _invData = null;

async function toggleInventario(){
  const panel = document.getElementById('stock-inventario-panel');
  if(panel.style.display === 'block'){ panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  await loadInventario();
}

async function loadInventario(){
  const data = await api('/api/stock/inventario');
  if(!data) return;
  _invData = data;
  renderInventario(data);
}

const _CAT_LABEL = {inalambrico:'📡 Inalámbrico', fibra:'🔵 Fibra', varios:'🔧 Varios'};

function renderInventario(data){
  const panel = document.getElementById('stock-inventario-panel');
  const cols = ['inalambrico','fibra','varios'];
  let html = `<div class="card" style="margin-bottom:.6rem">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.6rem">
      <b>📋 Inventario por cantidad</b>
      <button class="btn btn-prim btn-xs" onclick="openModalInvItem()">+ Agregar ítem</button>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem">`;

  for(const cat of cols){
    const items = data[cat] || [];
    html += `<div>
      <div style="background:var(--tint-azul);color:#1a3d6b;font-weight:700;padding:.4rem .6rem;border-radius:6px 6px 0 0;display:flex;justify-content:space-between">
        <span>${_CAT_LABEL[cat]||cat}</span><span>Cantidad</span>
      </div>
      <div style="border:1px solid var(--brd);border-top:none;border-radius:0 0 6px 6px">`;
    if(!items.length){
      html += `<div style="padding:.6rem;color:#999;font-size:.8rem;text-align:center">Sin ítems</div>`;
    } else {
      items.forEach((it,i)=>{
        const bg = i%2 ? 'var(--card)' : 'var(--card)';
        const autoTag = it.origen==='auto' ? '<span title="Contado automáticamente del stock por serie" style="font-size:.6rem;color:#1565c0;margin-left:.2rem">⚙</span>' : '';
        html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:.35rem .6rem;background:${bg};font-size:.84rem">
          <span style="cursor:pointer" onclick="editarInvItem(${it.id})">${it.nombre}${autoTag}</span>
          <b style="color:${it.cantidad>0?'#1a3d6b':'#c62828'}">${it.cantidad}${it.unidad&&it.unidad!=='u'?' '+it.unidad:''}</b>
        </div>`;
      });
    }
    html += `</div></div>`;
  }
  html += `</div>
    <div style="font-size:.7rem;color:#888;margin-top:.5rem">⚙ = cantidad contada automáticamente del stock por número de serie. El resto se carga a mano (clic en el nombre para editar).</div>
  </div>`;
  panel.innerHTML = html;
}

// ── Modal agregar/editar ítem ──
function openModalInvItem(){
  document.getElementById('inv-id').value = '';
  document.getElementById('inv-modal-title').textContent = 'Agregar ítem';
  document.getElementById('inv-nombre').value = '';
  document.getElementById('inv-categoria').value = 'fibra';
  document.getElementById('inv-cantidad').value = 0;
  document.getElementById('inv-unidad').value = 'u';
  document.getElementById('inv-origen').value = 'manual';
  document.getElementById('inv-del').style.display = 'none';
  toggleInvOrigen();
  document.getElementById('modal-inv-item').style.display = 'flex';
}

function editarInvItem(id){
  let item = null;
  for(const cat in _invData){ const f = _invData[cat].find(x=>x.id===id); if(f){ item=f; break; } }
  if(!item) return;
  document.getElementById('inv-id').value = item.id;
  document.getElementById('inv-modal-title').textContent = 'Editar ítem';
  document.getElementById('inv-nombre').value = item.nombre;
  document.getElementById('inv-categoria').value = item.categoria;
  document.getElementById('inv-cantidad').value = item.cantidad;
  document.getElementById('inv-unidad').value = item.unidad||'u';
  document.getElementById('inv-origen').value = item.origen;
  document.getElementById('inv-serie-marca').value = item.serie_marca||'';
  document.getElementById('inv-serie-tipo').value = item.serie_tipo||'';
  document.getElementById('inv-del').style.display = 'block';
  toggleInvOrigen();
  document.getElementById('modal-inv-item').style.display = 'flex';
}

function toggleInvOrigen(){
  const origen = document.getElementById('inv-origen').value;
  document.getElementById('inv-auto-fields').style.display = origen==='auto' ? 'block' : 'none';
  document.getElementById('inv-cantidad').disabled = origen==='auto';
}

async function guardarInvItem(){
  const id = document.getElementById('inv-id').value;
  const data = {
    nombre: document.getElementById('inv-nombre').value.trim(),
    categoria: document.getElementById('inv-categoria').value,
    cantidad: parseInt(document.getElementById('inv-cantidad').value)||0,
    unidad: document.getElementById('inv-unidad').value.trim()||'u',
    origen: document.getElementById('inv-origen').value,
    serie_marca: document.getElementById('inv-serie-marca').value.trim(),
    serie_tipo: document.getElementById('inv-serie-tipo').value.trim(),
  };
  if(!data.nombre){ alert('Ingresá el nombre'); return; }
  const r = id
    ? await api(`/api/stock/inventario/${id}`, 'PUT', data)
    : await api('/api/stock/inventario', 'POST', data);
  if(r && r.ok){ closeModal('modal-inv-item'); loadInventario(); }
  else alert('No se pudo guardar');
}

async function eliminarInvItem(){
  const id = document.getElementById('inv-id').value;
  if(!id || !await confirmar('¿Eliminar este ítem del inventario?')) return;
  const r = await api(`/api/stock/inventario/${id}`, 'DELETE');
  if(r && r.ok){ closeModal('modal-inv-item'); loadInventario(); }
}
