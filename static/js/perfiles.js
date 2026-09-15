// ══════════ Perfiles de Radio (capacidad por modelo) — Prioridad 1 ══════════
let _perfilesData = [];

async function cargarPerfiles(){
  const cont = document.getElementById('perfiles-lista');
  cont.innerHTML = '<div style="color:var(--txt2)">Cargando…</div>';
  _perfilesData = await api('/api/perfiles_radio') || [];
  if(!_perfilesData.length){
    cont.innerHTML = '<div style="color:var(--txt2);padding:1rem">No hay perfiles cargados. Creá uno con “Nuevo perfil”.</div>';
    return;
  }
  const nd = v => (v===null||v===undefined||v==='')?'<span style="color:var(--txt2)">—</span>':escHtml(v);
  cont.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.82rem">
    <thead><tr style="text-align:left;border-bottom:2px solid var(--brd)">
      <th style="padding:.4rem">Fabricante / Modelo</th><th>Tipo</th><th>Apertura H</th>
      <th>Ganancia</th><th>Alcance</th><th>Cli. rec.</th><th>Cli. máx</th>
      <th>Umbral ⚠/🔴</th><th>Fuente</th><th></th>
    </tr></thead><tbody>
    ${_perfilesData.map(p=>`<tr style="border-bottom:1px solid var(--brd)">
      <td style="padding:.4rem"><b>${escHtml(p.fabricante)} ${escHtml(p.modelo)}</b></td>
      <td>${nd(p.tipo_equipo)}</td>
      <td>${p.apertura_horizontal!=null?p.apertura_horizontal+'°':nd(null)}</td>
      <td>${p.ganancia_dbi!=null?p.ganancia_dbi+' dBi':nd(null)}</td>
      <td>${p.alcance_teorico_m!=null?p.alcance_teorico_m+' m':nd(null)}</td>
      <td>${nd(p.clientes_recomendados)}</td>
      <td>${nd(p.clientes_max_operativo)}</td>
      <td>${p.umbral_advertencia!=null?p.umbral_advertencia+'%':nd(null)} / ${p.umbral_critico!=null?p.umbral_critico+'%':nd(null)}</td>
      <td><span style="font-size:.72rem;color:var(--txt2)">${nd(p.fuente)}</span></td>
      <td><button class="btn btn-gray btn-xs" onclick="editarPerfil(${p.id})">✏️</button></td>
    </tr>`).join('')}
    </tbody></table></div>`;
}

function _perfSet(id,val){ const el=document.getElementById(id); if(el) el.value = (val==null?'':val); }

function abrirModalPerfil(){
  document.getElementById('mperf-title').textContent = 'Nuevo perfil';
  ['mperf-id','mperf-fabricante','mperf-modelo','mperf-apertura-h','mperf-apertura-v',
   'mperf-ganancia','mperf-frec-min','mperf-frec-max','mperf-alcance','mperf-cli-rec',
   'mperf-cli-max','mperf-throughput','mperf-umbral-adv','mperf-umbral-crit','mperf-obs'].forEach(id=>_perfSet(id,''));
  document.getElementById('mperf-tipo').value = '';
  document.getElementById('mperf-fuente').value = 'manual';
  document.getElementById('mperf-del').style.display = 'none';
  abrirModal('modal-perfil');
}

function editarPerfil(id){
  const p = _perfilesData.find(x=>x.id===id);
  if(!p) return;
  document.getElementById('mperf-title').textContent = `Editar: ${p.fabricante} ${p.modelo}`;
  _perfSet('mperf-id',p.id); _perfSet('mperf-fabricante',p.fabricante); _perfSet('mperf-modelo',p.modelo);
  document.getElementById('mperf-tipo').value = p.tipo_equipo||'';
  _perfSet('mperf-apertura-h',p.apertura_horizontal); _perfSet('mperf-apertura-v',p.apertura_vertical);
  _perfSet('mperf-ganancia',p.ganancia_dbi); _perfSet('mperf-frec-min',p.frecuencia_min);
  _perfSet('mperf-frec-max',p.frecuencia_max); _perfSet('mperf-alcance',p.alcance_teorico_m);
  _perfSet('mperf-cli-rec',p.clientes_recomendados); _perfSet('mperf-cli-max',p.clientes_max_operativo);
  _perfSet('mperf-throughput',p.throughput_recomendado_mbps); _perfSet('mperf-umbral-adv',p.umbral_advertencia);
  _perfSet('mperf-umbral-crit',p.umbral_critico); _perfSet('mperf-obs',p.observaciones);
  document.getElementById('mperf-fuente').value = p.fuente||'manual';
  document.getElementById('mperf-del').style.display = '';
  abrirModal('modal-perfil');
}

function _perfPayload(){
  const num=id=>{const v=parseFloat(document.getElementById(id).value);return isNaN(v)?null:v;};
  const int=id=>{const v=parseInt(document.getElementById(id).value);return isNaN(v)?null:v;};
  const txt=id=>{const v=document.getElementById(id).value.trim();return v||null;};
  return {
    fabricante: txt('mperf-fabricante'), modelo: txt('mperf-modelo'),
    tipo_equipo: document.getElementById('mperf-tipo').value||null,
    apertura_horizontal: num('mperf-apertura-h'), apertura_vertical: num('mperf-apertura-v'),
    ganancia_dbi: num('mperf-ganancia'), frecuencia_min: num('mperf-frec-min'),
    frecuencia_max: num('mperf-frec-max'), alcance_teorico_m: num('mperf-alcance'),
    clientes_recomendados: int('mperf-cli-rec'), clientes_max_operativo: int('mperf-cli-max'),
    throughput_recomendado_mbps: num('mperf-throughput'),
    umbral_advertencia: num('mperf-umbral-adv'), umbral_critico: num('mperf-umbral-crit'),
    fuente: document.getElementById('mperf-fuente').value, observaciones: txt('mperf-obs')
  };
}

async function guardarPerfil(){
  const id = document.getElementById('mperf-id').value;
  const p = _perfPayload();
  if(!p.fabricante || !p.modelo){ alert('Fabricante y modelo son obligatorios'); return; }
  const r = id ? await api(`/api/perfiles_radio/${id}`,'PUT',p) : await api('/api/perfiles_radio','POST',p);
  if(r && (r.ok||r.id)){ closeModal('modal-perfil'); cargarPerfiles(); }
  else alert('Error: '+(r&&r.error?r.error:'no se pudo guardar'));
}

async function borrarPerfil(){
  const id = document.getElementById('mperf-id').value;
  if(!id || !confirm('¿Eliminar este perfil?')) return;
  const r = await api(`/api/perfiles_radio/${id}`,'DELETE');
  if(r && r.ok){ closeModal('modal-perfil'); cargarPerfiles(); }
  else alert('Error: '+(r&&r.error?r.error:'no se pudo eliminar'));
}
