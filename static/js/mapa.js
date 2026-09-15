/* ========================================================
   mapa.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

let map=null, mapaInited=false;

let mapaLayers={clientes:null,naps:null,heat:null,ftth_pot:null,olts:null};

let mapaChips={naps:false,clientes:true,heat:false,ftth_pot:false,olts:false,zonas:false,vehiculos:false};

let mapaCliData=[], napData=[], oltData=[], stockData={instalado:[],manual:[]};

function drawHeatmapHorarios(d) {
  const wrap = document.getElementById('heatmap-horarios');
  if (!wrap) return;
  const dias = ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];
  let html = '<div class="heatmap-hours">';
  d.levels.forEach((row, di) => {
    html += `<div class="heatmap-hours-row">`;
    html += `<div class="heatmap-hours-label">${dias[di]}</div>`;
    row.forEach((lvl, hi) => {
      const cls = lvl > 0 ? `l${lvl}` : '';
      const valor = d.matrix[di][hi];
      html += `<div class="heatmap-hours-cell ${cls}" title="${dias[di]} ${hi}h: ${valor} eventos"></div>`;
    });
    html += `</div>`;
  });
  html += '</div>';
  html += '<div class="heatmap-hours-header">';
  for (let h = 0; h < 24; h += 3) html += `<span>${h}h</span>`;
  html += '</div>';
  wrap.innerHTML = html;

  const pico = document.getElementById('heatmap-pico');
  if (d.pico) {
    pico.innerHTML = `💡 Pico: <b>${d.pico.dia} ${d.pico.hora}h</b> (${d.pico.valor} eventos) · Considerar reforzar guardia en esa franja`;
  } else {
    pico.innerHTML = `Sin actividad registrada en los últimos 90 días`;
  }
}

let redesData=[];

async function loadRedes(){
  const d=await api('/api/redes');
  if(d) redesData=d;
}

function initMapa(){
  if(mapaInited) return;
  mapaInited=true;
  map=L.map('map-container').setView([-31.73,-60.53],13);
  _aplicarTilesTema();

  // Para técnicos restringidos (ej: marianoz), solo mostrar chips permitidos
  const isTecnico = currentUser.rol === 'tecnico';
  const capasPermitidas = userPermisos.mapa_capas || null;
  if(isTecnico && capasPermitidas){
    // Ocultar chips no permitidos
    document.querySelectorAll('.chips .chip').forEach(chip=>{
      const chipId = chip.id.replace('chip-','').replace('ftth-pot','ftth_pot');
      // 'zonas' (expansión) es informativo: visible para todos
      if(chipId==='zonas') return;
      if(!capasPermitidas.includes(chipId) && chipId!==''){
        chip.style.display='none';
      }
    });
    // Solo cargar capas permitidas
    if(capasPermitidas.includes('naps')){ mapaChips.naps=true; reloadMapaNaps(); }
    if(capasPermitidas.includes('clientes')){ reloadMapaClientes(); } else { mapaChips.clientes=false; }
  } else {
    reloadMapaClientes();
    reloadMapaNaps();
  }

  // El chip de reubicar sólo tiene sentido para quien puede editar NAPs.
  if(typeof puedeEditar === 'function' && !puedeEditar('naps')){
    const c = document.getElementById('chip-reubicar');
    if(c) c.style.display = 'none';
  }
}

function toggleChip(name){
  mapaChips[name]=!mapaChips[name];
  const chip=document.getElementById(`chip-${name}`);
  if(chip) chip.classList.toggle('active',mapaChips[name]);
  // Apagar la capa de NAPs con el modo reubicar activo dejaría el aviso
  // flotante sin nada que reubicar.
  if(name==='naps' && !mapaChips.naps && typeof _modoReubicarNap !== 'undefined' && _modoReubicarNap){
    toggleReubicarNaps();
    return;
  }
  if(name==='naps') mapaChips[name]?reloadMapaNaps():removeLayer('naps');
  else if(name==='clientes') mapaChips[name]?reloadMapaClientes():removeLayer('clientes');
  else if(name==='heat') mapaChips[name]?showHeatMap():removeLayer('heat');
  else if(name==='ftth_pot') mapaChips[name]?showFtthPotenciales():removeLayer('ftth_pot');
  else if(name==='olts') mapaChips[name]?showOltsOnMap():removeLayer('olts');
  else if(name==='torres') mapaChips[name]?showTorresOnMap():removeLayer('torres');
  else if(name==='zonas') mapaChips[name]?showZonasExpansion():removeLayer('zonas');
  else if(name==='vehiculos') mapaChips[name]?showVehiculos():ocultarVehiculos();
}

function removeLayer(name){
  if(mapaLayers[name]){map.removeLayer(mapaLayers[name]);mapaLayers[name]=null;}
}

let _zonasCargadas = null;
async function showZonasExpansion(){
  removeLayer('zonas');
  if(!_zonasCargadas){
    _zonasCargadas = await api('/api/ftth/zonas') || [];
  }
  const grupo = L.layerGroup();
  const colorPrioridad = {alta:'#c62828', media:'#f9a825', baja:'#2e7d32'};
  _zonasCargadas.forEach(z=>{
    if(!z.coords || !z.coords.length) return;
    const color = colorPrioridad[(z.prioridad||'').toLowerCase()] || '#1565c0';
    // coords puede ser [[lat,lng],...] (polígono) o un punto
    let capa;
    if(Array.isArray(z.coords[0])){
      capa = L.polygon(z.coords, {color, weight:2, fillColor:color, fillOpacity:.18});
    } else if(z.coords.length===2){
      capa = L.circle([z.coords[0], z.coords[1]], {radius:300, color, fillColor:color, fillOpacity:.18});
    } else return;
    const pot = z.clientes_potenciales ? `<br>👥 Potencial: ${z.clientes_potenciales} clientes` : '';
    const notas = z.notas ? `<br><small>${z.notas}</small>` : '';
    capa.bindPopup(`<b>📐 ${z.nombre||'Zona'}</b><br>Prioridad: ${z.prioridad||'—'} · Estado: ${z.estado||'—'}${pot}${notas}`);
    grupo.addLayer(capa);
  });
  grupo.addTo(map);
  mapaLayers.zonas = grupo;
}

// ── Vehículos (TransDat GPS) ──
let _vehTimer = null;

async function showVehiculos(){
  await _cargarVehiculos(true);  // intento manual: avisa si falla
  // Auto-refresh mientras la capa esté activa (fallos silenciosos, no desmarcan)
  if(_vehTimer) clearInterval(_vehTimer);
  _vehTimer = setInterval(()=>{ if(mapaChips.vehiculos) _cargarVehiculos(false); }, 60000);
}

function ocultarVehiculos(){
  removeLayer('vehiculos');
  if(_vehTimer){ clearInterval(_vehTimer); _vehTimer = null; }
}

async function _cargarVehiculos(esManual){
  const data = await api('/api/vehiculos/posiciones');
  if(!data || data.error){
    const msg = (data && data.error) ? String(data.error) : '';
    const es429 = msg.includes('429') || msg.toLowerCase().includes('too many');
    // Si TransDat nos bloqueó por exceso (429), parar el auto-refresh para no empeorar
    if(es429 && _vehTimer){ clearInterval(_vehTimer); _vehTimer = null; }
    if(esManual){
      // Primer intento (el usuario tocó el botón): avisar y desmarcar.
      if(msg) alert('GPS vehículos: ' + msg + (es429 ? '\n\nTransDat bloqueó temporalmente por exceso de consultas. Esperá unos minutos y volvé a activar la capa.' : ''));
      mapaChips.vehiculos = false;
      const ch = document.getElementById('chip-vehiculos');
      if(ch) ch.classList.remove('active');
      if(_vehTimer){ clearInterval(_vehTimer); _vehTimer = null; }
    }
    // Refresco automático fallido: NO desmarcar, NO borrar lo que se ve.
    return;
  }
  // Hubo datos OK: recién ahí borramos los marcadores viejos y dibujamos los nuevos.
  removeLayer('vehiculos');
  const grupo = L.layerGroup();
  data.forEach(v=>{
    if(!v.lat || !v.lng) return;
    const enMov = (v.velocidad||0) > 3;
    const color = enMov ? '#2e7d32' : '#757575';
    // Ícono: flecha rotada según sentido (0 = Norte, sentido horario)
    const icon = L.divIcon({
      className: '',
      html: `<div style="display:flex;flex-direction:column;align-items:center">
        <div style="transform:rotate(${v.sentido||0}deg);font-size:20px;color:${color};
             text-shadow:0 0 3px #fff,0 0 3px #fff;line-height:1">⬆</div>
        <div style="background:${color};color:#fff;font-size:.6rem;font-weight:700;
             padding:1px 4px;border-radius:4px;white-space:nowrap;margin-top:-2px">${v.patente||'?'}</div>
      </div>`,
      iconSize: [44, 38], iconAnchor: [22, 19],
    });
    const fecha = (v.fecha||'').replace('T',' ').slice(0,16);
    const m = L.marker([v.lat, v.lng], {icon}).bindPopup(
      `<b>🚐 ${v.patente||'—'}</b> ${v.descripcion?('— '+v.descripcion):''}<br>` +
      `Velocidad: <b>${v.velocidad||0} km/h</b> · Rumbo: ${v.sentido||0}°<br>` +
      `<small>Último reporte: ${fecha}</small>`);
    grupo.addLayer(m);
  });
  grupo.addTo(map);
  mapaLayers.vehiculos = grupo;
}

function showHeatMap(){
  removeLayer('heat');
  const data=mapaCliData.filter(c=>c.lat&&c.lng).map(c=>[c.lat,c.lng,1]);
  if(data.length===0) return;
  mapaLayers.heat=L.heatLayer(data,{radius:25,blur:15,maxZoom:17,
    gradient:{0.4:'blue',0.65:'lime',1:'red'}}).addTo(map);
}

let mapaSearchTimer=null;
let _mapaSearchResults={};  // id -> cliente

async function mapaSearch(){
  const q=document.getElementById('map-q').value;
  const drop=document.getElementById('map-drop');
  if(q.length<2){drop.style.display='none';return;}
  clearTimeout(mapaSearchTimer);
  mapaSearchTimer=setTimeout(async()=>{
    const data=await api(`/api/clientes/buscar?q=${encodeURIComponent(q)}`);
    if(!data||!data.length){
      drop.innerHTML='<div class="item" style="color:#888">Sin resultados</div>';
      drop.style.display='block';
      return;
    }
    _mapaSearchResults={};
    drop.innerHTML=data.map(c=>{
      _mapaSearchResults[c.id]=c;
      const nro = c.nro_cliente ? `<span class="badge b-fibra" style="font-family:monospace">#${escHtml(c.nro_cliente)}</span> ` : '';
      const sinCoord = (!c.lat || !c.lng) ? ' <span style="color:#dc3545;font-size:.75rem">(sin coordenadas)</span>' : '';
      const nombreHtml = escHtml(c.nombre);
      const dirHtml = escHtml((c.direccion||'')+' '+(c.localidad||''));
      return `<div class="item" data-id="${c.id}" style="cursor:pointer;${(!c.lat||!c.lng)?'opacity:.6':''}">
        <div class="name">${nro}${nombreHtml}${sinCoord}</div>
        <div class="sub">${dirHtml} | <span class="badge b-${c.estado}">${estadoLabel(c.estado)}</span></div>
      </div>`;
    }).join('');
    // Event delegation - una sola vez
    drop.onclick = (e)=>{
      const item = e.target.closest('.item[data-id]');
      if(!item) return;
      const id = parseInt(item.dataset.id);
      const c = _mapaSearchResults[id];
      if(!c) return;
      mapaGoToCliente(c);
    };
    drop.style.display='block';
  },300);
}

function mapaGoToCliente(c){
  document.getElementById('map-drop').style.display='none';
  document.getElementById('map-q').value=c.nombre||'';
  if(!c.lat || !c.lng){
    alert(`El cliente "${c.nombre}" no tiene coordenadas cargadas.\n\nEditá la ficha y agregá lat/lng para que aparezca en el mapa.`);
    return;
  }
  if(!map){ console.warn('map no inicializado'); return; }
  map.setView([c.lat, c.lng], 17);
  const nro = c.nro_cliente ? `<div style="font-family:monospace;color:#666;font-size:.85rem">#${c.nro_cliente}</div>` : '';
  const verBtn = `<button class="btn btn-prim btn-sm" style="margin-top:.5rem;width:100%" onclick="openModalCliente(${c.id})">📋 Ver ficha</button>`;
  L.popup({maxWidth:280}).setLatLng([c.lat, c.lng])
    .setContent(`<b>${(c.nombre||'').replace(/</g,'&lt;')}</b>${nro}${verBtn}`)
    .openOn(map);
}

// Compat: dejar mapaGoTo como wrapper por si se usa desde otro lado
function mapaGoTo(lat, lng, nombre){
  if(!lat||!lng){
    alert(`"${nombre}" no tiene coordenadas cargadas.`);
    return;
  }
  if(!map) return;
  map.setView([lat,lng],17);
  L.popup().setLatLng([lat,lng]).setContent(`<b>${nombre||''}</b>`).openOn(map);
}

document.addEventListener('click',e=>{
  const drop=document.getElementById('map-drop');
  if(drop&&!drop.contains(e.target)&&!document.getElementById('map-q').contains(e.target))
    drop.style.display='none';
});

// ── NAPs ──

async function promptNuevaRed(){
  const nombre= await pedirDato('Nombre de la nueva red (ej: NUEVARED):');
  if(!nombre || !nombre.trim()) return;
  const r=await api('/api/redes','POST',{nombre:nombre.trim().toUpperCase()});
  if(r?.ok){
    await loadRedes();
    const sel=document.getElementById('mnap-red');
    sel.innerHTML='<option value="">— Seleccionar red —</option>';
    redesData.forEach(r=>{
      const o=document.createElement('option'); o.value=r.nombre; o.textContent=r.nombre; sel.appendChild(o);
    });
    sel.value=nombre.trim().toUpperCase();
    generarNombreNap();
  } else {
    alert('Error: '+(r?.error||'No se pudo crear la red'));
  }
}

// PATCH viejo eliminado — la nueva loadDash() ya llama a loadDashMonitoreo() internamente

// ── Chip "Red Torres" eliminado en sprint v7.2: era redundante con el chip "Torres".
// Ambos llamaban a /api/torres/mapa_red y mostraban marcadores+líneas. Ahora sólo queda "Torres".

// ═══ ASIGNAR TORRES POR PROXIMIDAD (importado de v6.2) ═══
async function asignarTorresProximidad(){
  if(!await confirmar('¿Asignar la torre más cercana (máx 5km) a todos los clientes inalámbricos sin torre?\n\nEsto actualiza la base de datos.')) return;
  const r = await api('/api/clientes/asignar_torre_proximidad','POST',{max_km:5});
  if(r?.ok){
    alert(`✅ Listo:\n• ${r.asignados} clientes asignados a una torre\n• ${r.sin_torre_cercana} sin torre cercana (>5km)${r.sin_coordenadas?`\n• ${r.sin_coordenadas} sin coordenadas válidas`:''}`);
    if(typeof loadMapa==='function') loadMapa();
  } else {
    alert('No se pudo completar la asignación');
  }
}


/* ══ Fondo del mapa según el tema (claro / oscuro) ══
   Oscuro: CARTO Dark Matter (gratuito, sin clave).
   Claro:  OpenStreetMap estándar. */
let _capaBase = null;

function _temaOscuroActivo(){
  const l = document.getElementById('tema-oscuro-css');
  return !!(l && !l.disabled);
}

function _aplicarTilesTema(){
  if(!map) return;
  const oscuro = _temaOscuroActivo();
  const url = oscuro
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const attr = oscuro ? '© OSM · © CARTO' : '© OSM';
  if(_capaBase) map.removeLayer(_capaBase);
  _capaBase = L.tileLayer(url, {attribution: attr, maxZoom: 19, subdomains: 'abcd'});
  _capaBase.addTo(map);
  if(_capaBase.getContainer) _capaBase.getContainer().classList.toggle('tiles-oscuros', oscuro);
  document.body.classList.toggle('mapa-oscuro', oscuro);
}

/* Que el mapa siga el toggle de tema sin recargar la página */
document.addEventListener('DOMContentLoaded', function(){
  const link = document.getElementById('tema-oscuro-css');
  if(!link) return;
  new MutationObserver(function(){ _aplicarTilesTema(); })
    .observe(link, {attributes:true, attributeFilter:['disabled']});
});
