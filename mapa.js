/* ========================================================
   mapa.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

let map=null, mapaInited=false;

let mapaLayers={clientes:null,naps:null,heat:null,ftth_pot:null,olts:null};

let mapaChips={naps:false,clientes:true,heat:false,ftth_pot:false,olts:false};

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
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM',maxZoom:19}).addTo(map);

  // Para técnicos restringidos (ej: marianoz), solo mostrar chips permitidos
  const isTecnico = currentUser.rol === 'tecnico';
  const capasPermitidas = userPermisos.mapa_capas || null;
  if(isTecnico && capasPermitidas){
    // Ocultar chips no permitidos
    document.querySelectorAll('.chips .chip').forEach(chip=>{
      const chipId = chip.id.replace('chip-','').replace('ftth-pot','ftth_pot');
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
}

function toggleChip(name){
  mapaChips[name]=!mapaChips[name];
  const chip=document.getElementById(`chip-${name}`);
  if(chip) chip.classList.toggle('active',mapaChips[name]);
  if(name==='naps') mapaChips[name]?reloadMapaNaps():removeLayer('naps');
  else if(name==='clientes') mapaChips[name]?reloadMapaClientes():removeLayer('clientes');
  else if(name==='heat') mapaChips[name]?showHeatMap():removeLayer('heat');
  else if(name==='ftth_pot') mapaChips[name]?showFtthPotenciales():removeLayer('ftth_pot');
  else if(name==='olts') mapaChips[name]?showOltsOnMap():removeLayer('olts');
  else if(name==='torres') mapaChips[name]?showTorresOnMap():removeLayer('torres');
}

function removeLayer(name){
  if(mapaLayers[name]){map.removeLayer(mapaLayers[name]);mapaLayers[name]=null;}
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
      const nro = c.nro_cliente ? `<span class="badge b-fibra" style="font-family:monospace">#${c.nro_cliente}</span> ` : '';
      const sinCoord = (!c.lat || !c.lng) ? ' <span style="color:#dc3545;font-size:.75rem">(sin coordenadas)</span>' : '';
      // Escape HTML para evitar XSS y bugs de comillas
      const nombreHtml = (c.nombre||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
      const dirHtml = ((c.direccion||'')+' '+(c.localidad||'')).replace(/</g,'&lt;');
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
  const nombre=prompt('Nombre de la nueva red (ej: NUEVARED):');
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
