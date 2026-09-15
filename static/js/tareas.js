// tareas.js — Pizarrón personal de tareas (post-its) por usuario.
// Las notas admiten imágenes pegadas desde el portapapeles (Ctrl+V), soltadas
// con el mouse o elegidas con el botón 📎. Se guardan por /api/v2 y sólo las ve
// su dueño.

// Colores de post-it: fondo claro + texto oscuro (se ven bien en ambos temas)
const TAREA_COLORES = {
  amarillo: {bg:'#FDE68A', txt:'#4A3410', borde:'#E9C86A'},
  rosa:     {bg:'#FBCFE8', txt:'#500724', borde:'#E9A9CE'},
  azul:     {bg:'#BFDBFE', txt:'#1E3A5F', borde:'#93BEE9'},
  verde:    {bg:'#BBF7D0', txt:'#14532D', borde:'#8CD9A8'},
  naranja:  {bg:'#FED7AA', txt:'#7C2D12', borde:'#EBB483'},
};
let _tareaColorSel = 'amarillo';
let _tareaAdjuntos = {};      // {tarea_id: [adjunto, ...]}
let _pendientes = [];         // imágenes pegadas antes de crear la nota

const TAREA_MAX_MB = 5;
const TAREA_MAX_IMGS = 6;

function _initColorPicker(){
  const cont = document.getElementById('tarea-colores');
  if(!cont || cont._init) return;
  cont._init = true;
  Object.entries(TAREA_COLORES).forEach(([nombre, c]) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.title = nombre;
    b.style.cssText = `width:24px;height:24px;border-radius:50%;background:${c.bg};cursor:pointer;border:2px solid ${nombre===_tareaColorSel?'var(--txt)':'transparent'};padding:0`;
    b.onclick = () => { _tareaColorSel = nombre; _refreshColorPicker(); };
    b.dataset.color = nombre;
    cont.appendChild(b);
  });
}
function _refreshColorPicker(){
  document.querySelectorAll('#tarea-colores button').forEach(b => {
    b.style.border = `2px solid ${b.dataset.color===_tareaColorSel?'var(--txt)':'transparent'}`;
  });
}

async function loadTareas(){
  _initColorPicker();
  _initPegado();
  const board = document.getElementById('tarea-board');
  const tareas = await api('/api/tareas');
  if(!tareas){ board.innerHTML = '<div style="color:var(--txt2);padding:1rem">Error al cargar.</div>'; return; }

  // Los adjuntos de todas las notas en una sola petición, no una por post-it.
  _tareaAdjuntos = {};
  if(tareas.length){
    const r = await api('/api/v2/adjuntos/consulta', 'POST', {ids: tareas.map(t => t.id)});
    if(r && !r.error) _tareaAdjuntos = r;
  }

  const pendientes = tareas.filter(t => !t.completada);
  const hechas = tareas.filter(t => t.completada);

  if(!tareas.length){
    board.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--txt2);padding:3rem 1rem">
      <div style="font-size:2.5rem;margin-bottom:.5rem">📋</div>
      No tenés tareas todavía. Escribí una arriba y presioná Enter.
      <div style="font-size:.78rem;margin-top:.4rem">Después podés pegarle capturas de pantalla con Ctrl+V.</div>
    </div>`;
    return;
  }

  let html = pendientes.map(_postitHTML).join('');
  if(hechas.length){
    html += `<div style="grid-column:1/-1;margin:.6rem 0 .2rem;font-size:.8rem;color:var(--txt2);border-top:1px solid var(--brd);padding-top:.7rem">
      ✓ Completadas (${hechas.length})</div>`;
    html += hechas.map(_postitHTML).join('');
  }
  board.innerHTML = html;
}

function _postitHTML(t){
  const c = TAREA_COLORES[t.color] || TAREA_COLORES.amarillo;
  const rot = ((t.id * 37) % 5) - 2;  // rotación -2..2 grados, estable por id
  const done = t.completada;
  const imgs = _tareaAdjuntos[t.id] || _tareaAdjuntos[String(t.id)] || [];
  return `<div class="tarea-postit" data-tarea="${t.id}" tabindex="0"
       ondragover="tareaDragOver(event,this)" ondragleave="tareaDragLeave(this)" ondrop="tareaDrop(event,${t.id},this)"
       style="background:${c.bg};color:${c.txt};border-bottom:3px solid ${c.borde};transform:rotate(${done?0:rot}deg);${done?'opacity:.55':''}">
    <div class="tarea-texto" style="${done?'text-decoration:line-through':''}">${_escapeHtml(t.texto)}</div>
    ${_galeriaHTML(t.id, imgs, c)}
    <div class="tarea-acciones">
      <label class="tarea-check" title="${done?'Reabrir':'Completar'}">
        <input type="checkbox" ${done?'checked':''} onchange="toggleTarea(${t.id}, this.checked)">
        <span>${done?'Hecha':'Marcar'}</span>
      </label>
      <button class="tarea-adj" onclick="tareaElegirArchivo(${t.id})"
              title="Agregar imagen (o pegá una captura con Ctrl+V sobre esta nota)">📎</button>
      <button class="tarea-del" onclick="borrarTarea(${t.id})" title="Eliminar">🗑</button>
    </div>
  </div>`;
}

function _galeriaHTML(tareaId, imgs, c){
  if(!imgs.length) return '';
  return `<div class="tarea-galeria">${imgs.map(a => `
    <div class="tarea-miniatura">
      <img src="/api/v2/adjuntos/${a.id}" alt="${_escapeHtml(a.nombre_original || 'Imagen adjunta')}"
           loading="lazy" onclick="tareaVerImagen(${a.id}, '${_escapeJs(a.nombre_original || '')}')">
      <button class="tarea-mini-del" title="Quitar imagen"
              onclick="event.stopPropagation();tareaBorrarAdjunto(${a.id})">×</button>
    </div>`).join('')}</div>`;
}

function _escapeHtml(s){
  const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML;
}
// Para texto que va dentro de un atributo onclick='...': primero se escapa
// para JavaScript y después para HTML, porque el navegador decodifica las
// entidades ANTES de ejecutar el atributo.
function _escapeJs(s){
  return _escapeHtml(String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

/* ── Pegado y arrastre de imágenes ──────────────────────────────── */

function _initPegado(){
  if(document._tareaPegadoInit) return;
  document._tareaPegadoInit = true;

  document.addEventListener('paste', ev => {
    const pg = document.getElementById('page-tareas');
    if(!pg || !pg.classList.contains('active')) return;    // sólo en esta pantalla

    const imgs = Array.from(ev.clipboardData?.items || [])
      .filter(i => i.kind === 'file' && i.type.startsWith('image/'))
      .map(i => i.getAsFile())
      .filter(Boolean);
    if(!imgs.length) return;                                // era texto: pegado normal
    ev.preventDefault();

    // Si el foco está sobre un post-it, la imagen va a esa nota; si no, queda
    // en espera para la nota que se esté escribiendo arriba.
    const postit = ev.target.closest?.('.tarea-postit');
    if(postit) tareaSubirImagenes(parseInt(postit.dataset.tarea, 10), imgs);
    else _encolarPendientes(imgs);
  });
}

function tareaDragOver(ev, el){
  if(!Array.from(ev.dataTransfer.types || []).includes('Files')) return;
  ev.preventDefault();
  el.classList.add('tarea-drop');
}
function tareaDragLeave(el){ el.classList.remove('tarea-drop'); }
function tareaDrop(ev, tareaId, el){
  ev.preventDefault();
  el.classList.remove('tarea-drop');
  const imgs = Array.from(ev.dataTransfer.files || []).filter(f => f.type.startsWith('image/'));
  if(imgs.length) tareaSubirImagenes(tareaId, imgs);
}

function tareaElegirArchivo(tareaId){
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = 'image/png,image/jpeg,image/gif,image/webp';
  inp.multiple = true;
  inp.onchange = () => {
    const fs = Array.from(inp.files || []);
    if(fs.length) tareaSubirImagenes(tareaId, fs);
  };
  inp.click();
}

/* Subida real. Devuelve cuántas entraron. */
async function tareaSubirImagenes(tareaId, archivos){
  let ok = 0, errores = [];
  for(const f of archivos){
    if(f.size > TAREA_MAX_MB * 1024 * 1024){
      errores.push(`${f.name || 'imagen'}: pesa más de ${TAREA_MAX_MB} MB`);
      continue;
    }
    const fd = new FormData();
    fd.append('imagen', f, f.name || 'captura.png');
    try{
      const r = await fetch(`/api/v2/tareas/${tareaId}/adjuntos`,
                            {method:'POST', body: fd, credentials:'same-origin'});
      if(r.ok){ ok++; continue; }
      const d = await r.json().catch(() => ({}));
      errores.push(d.error || `no se pudo subir (${r.status})`);
    }catch(e){
      errores.push('fallo de red al subir la imagen');
    }
  }
  if(ok) toast(ok === 1 ? 'Imagen agregada' : `${ok} imágenes agregadas`, 'ok');
  if(errores.length) alert('⚠️ ' + errores.join('\n'));
  if(ok) await loadTareas();
  return ok;
}

async function tareaBorrarAdjunto(adjuntoId){
  const ok = await confirmar('¿Quitar esta imagen de la nota?',
                             {titulo:'Quitar imagen', ok:'Quitar', peligro:true});
  if(!ok) return;
  const r = await api('/api/v2/adjuntos/' + adjuntoId, 'DELETE');
  if(!r || r.error){ alert('❌ ' + ((r && r.error) || 'No se pudo quitar')); return; }
  await loadTareas();
}

/* Imágenes pegadas antes de que la nota exista: se muestran como pendientes y
   se suben apenas se crea, para no obligar a guardar primero y pegar después. */
function _encolarPendientes(archivos){
  const libres = TAREA_MAX_IMGS - _pendientes.length;
  if(libres <= 0){ alert(`⚠️ Una nota admite hasta ${TAREA_MAX_IMGS} imágenes`); return; }
  _pendientes.push(...archivos.slice(0, libres));
  _pintarPendientes();
  document.getElementById('tarea-input')?.focus();
}

function _pintarPendientes(){
  const cont = document.getElementById('tarea-pendientes');
  if(!cont) return;
  if(!_pendientes.length){ cont.innerHTML = ''; cont.style.display = 'none'; return; }
  cont.style.display = 'flex';
  cont.innerHTML = `<span style="font-size:.74rem;color:var(--txt2);align-self:center">
      ${_pendientes.length} ${_pendientes.length === 1 ? 'imagen lista' : 'imágenes listas'} para adjuntar:</span>` +
    _pendientes.map((f, i) => `<div class="tarea-miniatura tarea-mini-pend">
      <img src="${URL.createObjectURL(f)}" alt="Imagen pendiente ${i+1}">
      <button class="tarea-mini-del" title="Descartar" onclick="_quitarPendiente(${i})">×</button>
    </div>`).join('');
}

function _quitarPendiente(i){
  _pendientes.splice(i, 1);
  _pintarPendientes();
}

async function agregarTarea(){
  const inp = document.getElementById('tarea-input');
  const texto = inp.value.trim();
  // Se puede crear una nota que sea sólo una captura: en ese caso se le pone
  // un texto por defecto, porque el backend exige texto.
  if(!texto && !_pendientes.length) return;
  const r = await api('/api/tareas', 'POST',
                      {texto: texto || '📎 Captura', color: _tareaColorSel});
  if(r?.error){ alert(r.error); return; }
  inp.value = '';
  if(_pendientes.length && r?.id){
    const aSubir = _pendientes.slice();
    _pendientes = [];
    _pintarPendientes();
    await tareaSubirImagenes(r.id, aSubir);
  }
  inp.focus();
  await loadTareas();
}

async function toggleTarea(id, completada){
  await api('/api/tareas/' + id, 'PUT', {completada});
  await loadTareas();
}

async function borrarTarea(id){
  const imgs = (_tareaAdjuntos[id] || _tareaAdjuntos[String(id)] || []).length;
  if(imgs){
    const ok = await confirmar(
      `Esta nota tiene ${imgs} ${imgs === 1 ? 'imagen' : 'imágenes'}. Se eliminan junto con la nota.`,
      {titulo:'Eliminar nota', ok:'Eliminar', peligro:true});
    if(!ok) return;
  }
  const r = await api('/api/tareas/' + id, 'DELETE');
  if(r?.error){ alert(r.error); return; }
  await loadTareas();
}

/* Visor a pantalla completa. */
function tareaVerImagen(adjuntoId, nombre){
  const ov = document.createElement('div');
  ov.className = 'tarea-visor';
  ov.innerHTML = `<div class="tarea-visor-barra">
      <span>${_escapeHtml(nombre || 'Imagen adjunta')}</span>
      <a href="/api/v2/adjuntos/${adjuntoId}" target="_blank" rel="noopener">Abrir en pestaña</a>
      <button title="Cerrar">×</button>
    </div>
    <img src="/api/v2/adjuntos/${adjuntoId}" alt="${_escapeHtml(nombre || 'Imagen adjunta')}">`;
  const cerrar = () => { ov.remove(); document.removeEventListener('keydown', esc); };
  const esc = ev => { if(ev.key === 'Escape') cerrar(); };
  ov.onclick = ev => { if(ev.target === ov || ev.target.tagName === 'BUTTON') cerrar(); };
  document.addEventListener('keydown', esc);
  document.body.appendChild(ov);
}
