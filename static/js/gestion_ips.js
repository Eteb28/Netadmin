/* ════════════════════════════════════════════════════════
   gestion_ips.js — Grilla de IPs por rango
   Torre (1-50): equipos editables | Clientes (51-254): asignación
   ════════════════════════════════════════════════════════ */
let _ipBloque = 'clientes';
let _ipSubred = null;

async function loadGestionIPs(){
  // Cargar el selector de subredes desde los rangos cargados
  const rangos = await api('/api/ip_rangos') || [];
  const sel = document.getElementById('ip-subred-sel');
  if(!sel) return;
  if(!rangos.length){
    sel.innerHTML = '<option value="">No hay rangos cargados</option>';
    document.getElementById('ip-grilla-cont').innerHTML =
      '<div style="color:#999;padding:1rem">Primero cargá los rangos de IP (script gestionar_ips_pucara.py --cargar-rangos).</div>';
    return;
  }
  sel.innerHTML = rangos.map(r =>
    `<option value="${r.subred}">169.254.${r.subred}.0/24 ${r.localidades?'· '+r.localidades:'· '+(r.origen||'')}</option>`
  ).join('');
  _ipSubred = rangos[0].subred;
  loadGrillaIP();
}

function setBloqueIP(b){
  _ipBloque = b;
  document.getElementById('ipbloque-torre').classList.toggle('btn-prim', b==='torre');
  document.getElementById('ipbloque-clientes').classList.toggle('btn-prim', b==='clientes');
  loadGrillaIP();
}

async function loadGrillaIP(){
  const sel = document.getElementById('ip-subred-sel');
  _ipSubred = parseInt(sel.value);
  if(isNaN(_ipSubred)) return;
  const d = await api(`/api/ip_grilla?subred=${_ipSubred}&bloque=${_ipBloque}`);
  const cont = document.getElementById('ip-grilla-cont');
  const resumen = document.getElementById('ip-resumen');
  if(!d || !d.grilla){ cont.innerHTML = '<div style="color:#c62828">Error al cargar la grilla</div>'; return; }
  resumen.innerHTML = `<b>${d.libres}</b> libres · <b>${d.ocupadas}</b> usadas de ${d.total}`;
  cont.innerHTML = d.grilla.map(g => _celdaIP(g)).join('');
}

function _celdaIP(g){
  const libre = !g.ocupada;
  const bg = libre ? 'var(--card)' : (_ipBloque==='torre' ? 'var(--tint-ambar)' : 'var(--tint-azul)');
  const bd = libre ? '#aed581' : (_ipBloque==='torre' ? '#ffb74d' : '#64b5f6');
  const punto = libre ? '🟢' : '🔴';
  let detalle, onclick;
  if(_ipBloque === 'torre'){
    detalle = libre ? '<i style="color:#888">libre</i>'
      : `<div style="font-weight:600;font-size:.74rem;line-height:1.2">${escHtml(g.nombre)||'(sin nombre)'}</div>` +
        (g.mac?`<div style="font-size:.66rem;color:#777">${escHtml(g.mac)}</div>`:'');
    onclick = `editarEquipoTorre(${_ipSubred},${g.host})`;
  } else {
    detalle = libre ? '<i style="color:#888">libre</i>'
      : `<div style="font-weight:600;font-size:.72rem;line-height:1.2">${escHtml((g.nombre||'').slice(0,28))}</div>` +
        `<div style="font-size:.66rem;color:#777">#${escHtml(g.nro_cliente)||'s/n'} ${escHtml(g.tipo_servicio)}</div>`;
    onclick = libre ? `asignarIPCliente('${escJs(g.ip)}')` : `g.cliente_id?openModalCliente(${g.cliente_id}):null`;
    if(!libre && g.cliente_id) onclick = `openModalCliente(${g.cliente_id})`;
  }
  return `<div onclick="${onclick}" style="background:${bg};border:1px solid ${bd};border-radius:6px;padding:.35rem .45rem;cursor:pointer;min-height:48px" title="${escAttr(g.ip)}">
    <div style="display:flex;justify-content:space-between;font-size:.7rem;color:var(--txt2)">
      <span>.${g.host}</span><span>${punto}</span>
    </div>
    ${detalle}
  </div>`;
}

// ── Editar equipo de torre (1-50) ──
async function editarEquipoTorre(subred, host){
  const ip = `169.254.${subred}.${host}`;
  // Traer el dato actual de la grilla ya cargada (relectura simple)
  const d = await api(`/api/ip_grilla?subred=${subred}&bloque=torre`);
  const cel = d.grilla.find(g => g.host === host) || {};
  const nombre = await pedirDato(`Equipo en ${ip}\n\nNombre del equipo (vacío = liberar):`, cel.nombre || '');
  if(nombre === null) return; // canceló
  const mac = await pedirDato(`MAC (opcional):`, cel.mac || '') || '';
  const r = await api('/api/ip_equipos_torre', 'POST', {subred, host, nombre, mac});
  if(r && r.ok) loadGrillaIP();
  else alert(r?.error || 'No se pudo guardar');
}

// ── Asignar IP libre a un cliente (51-254) ──
async function asignarIPCliente(ip){
  const nro = await pedirDato(`Asignar la IP ${ip} a un cliente.\n\nIngresá el N° de cliente:`);
  if(!nro) return;
  // Buscar el cliente por número
  const res = await api(`/api/clientes/buscar?q=${encodeURIComponent(nro)}`);
  if(!res || !res.length){ alert('No se encontró ese cliente'); return; }
  // Si hay varios, tomar match exacto por nro_cliente
  let cli = res.find(c => String(c.nro_cliente) === String(nro)) || res[0];
  if(!await confirmar(`¿Asignar ${ip} a:\n\n${cli.nombre} (#${cli.nro_cliente})?\n\nOjo: si es FTTH no necesita IP. Confirmá solo si pasó a inalámbrico.`)) return;
  const r = await api('/api/ip_asignar_manual', 'POST', {cliente_id: cli.id, ip});
  if(r && r.ok){ alert(`✓ IP ${ip} asignada a ${cli.nombre}`); loadGrillaIP(); }
  else alert(r?.error || 'No se pudo asignar');
}
