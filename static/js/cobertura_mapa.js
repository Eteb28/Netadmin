// ══════════ Mapa de Cobertura Teórica (Prioridad 5) — Leaflet INDEPENDIENTE ══════════
// Instancia propia (covMap), separada del mapa general (map). No comparte estado.
let covMap = null;
let covInited = false;
let covData = null;
let covCapaBase = null;
const covLayers = { sectores: null, clientes: null, torres: null };

function _covTemaOscuro(){
  return document.body.classList.contains('tema-oscuro') ||
         (typeof _temaOscuroActivo === 'function' && _temaOscuroActivo());
}

function _covTiles(){
  if(!covMap) return;
  const oscuro = _covTemaOscuro();
  const url = oscuro
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  if(covCapaBase) covMap.removeLayer(covCapaBase);
  covCapaBase = L.tileLayer(url, {attribution: oscuro?'© OSM · © CARTO':'© OSM', maxZoom: 19, subdomains: 'abcd'});
  covCapaBase.addTo(covMap);
}

function initCoberturaMapa(){
  if(covInited) return;
  covInited = true;
  covMap = L.map('cobertura-map-container').setView([-31.73, -60.53], 12);
  _covTiles();
  covLayers.sectores = L.layerGroup().addTo(covMap);
  covLayers.torres   = L.layerGroup().addTo(covMap);
  covLayers.clientes = L.layerGroup();  // apagada por defecto
}

// Llamada por navGo al entrar a la página
function abrirCoberturaMapa(){
  initCoberturaMapa();
  // El contenedor tenía tamaño 0 mientras estaba oculto → recalcular
  setTimeout(()=>{ if(covMap) covMap.invalidateSize(); }, 60);
  if(!covData) cargarCoberturaMapa();
}

async function cargarCoberturaMapa(){
  initCoberturaMapa();
  const info = document.getElementById('cov-info');
  if(info) info.textContent = 'Cargando…';
  covData = await api('/api/cobertura/sectores');
  if(!covData){ if(info) info.textContent = 'No se pudo cargar.'; return; }
  covRender();
  // Ajustar la vista a los sectores/torres si hay
  const pts = [];
  (covData.sectores||[]).forEach(s=>pts.push([s.lat, s.lng]));
  if(pts.length){ try{ covMap.fitBounds(pts, {padding:[40,40], maxZoom:14}); }catch(e){} }
  // Avisos de APs omitidos
  const om = document.getElementById('cov-omitidos');
  if(om){
    const o = covData.omitidos||[];
    om.textContent = o.length ? `⚠ ${o.length} AP(s) no se dibujan por faltarles coordenadas de torre o datos físicos (azimut/apertura/alcance).` : '';
  }
}

function _covColorEstado(estado){
  return estado==='critico'?'#c62828':estado==='advertencia'?'#e8a13b':estado==='normal'?'#2e7d32':'#9e9e9e';
}
function _covColorSenal(senal){
  return senal==='buena'?'#2e7d32':senal==='media'?'#e8a13b':senal==='pobre'?'#c62828':'#9e9e9e';
}

function covRender(){
  if(!covMap || !covData) return;
  const filtro = document.getElementById('cov-filtro-estado').value;
  covLayers.sectores.clearLayers();
  covLayers.torres.clearLayers();
  covLayers.clientes.clearLayers();

  const torresVistas = {};
  let dibujados = 0;
  (covData.sectores||[]).forEach(s=>{
    if(filtro && s.estado !== filtro) return;
    dibujados++;
    const color = s.color || _covColorEstado(s.estado);
    // El GeoJSON viene en [lng,lat]; L.geoJSON lo interpreta bien.
    if(s.geojson){
      L.geoJSON(s.geojson, {
        style: { color: color, weight: 1, fillColor: color, fillOpacity: 0.25 }
      }).bindPopup(
        `<b>${s.modelo}</b><br>${s.torre_nombre||''}<br>`+
        `Azimut ${Math.round(s.azimut)}° · ${Math.round(s.apertura)}° · ${s.alcance_m} m<br>`+
        `<b style="color:${color}">${s.estado}</b> — ${s.clientes} clientes<br>${s.motivo}`
      ).addTo(covLayers.sectores);
    }
    // marcador de la torre (una vez)
    if(s.torre_nombre && !torresVistas[s.torre_nombre]){
      torresVistas[s.torre_nombre] = true;
      L.circleMarker([s.lat, s.lng], {radius:5, color:'#333', weight:2, fillColor:'#fff', fillOpacity:1})
        .bindPopup(`🗼 <b>${s.torre_nombre}</b>`).addTo(covLayers.torres);
    }
  });

  // clientes (respetando el filtro de estado del AP al que pertenecen)
  const apsFiltrados = new Set((covData.sectores||[])
    .filter(s=>!filtro || s.estado===filtro).map(s=>s.equipo_id));
  (covData.clientes||[]).forEach(c=>{
    if(filtro && !apsFiltrados.has(c.ap_snmp_id)) return;
    const col = _covColorSenal(c.senal);
    L.circleMarker([c.lat, c.lng], {radius:3.5, color:col, weight:1, fillColor:col, fillOpacity:0.9})
      .bindPopup(`<b>${c.nombre||'Cliente'}</b><br>Señal: ${c.rssi!=null?c.rssi+' dBm':'—'} (${c.senal})`)
      .addTo(covLayers.clientes);
  });

  const info = document.getElementById('cov-info');
  if(info) info.textContent = `${dibujados} sector(es) · ${(covData.clientes||[]).length} cliente(s)`;
}

function covToggle(capa){
  if(!covMap) return;
  const on = document.getElementById('cov-chk-'+capa).checked;
  const layer = covLayers[capa];
  if(!layer) return;
  if(on) layer.addTo(covMap); else covMap.removeLayer(layer);
}
