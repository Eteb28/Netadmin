// contabilidad.js — Carga de egresos e inflación para informes de rentabilidad

async function loadContabilidad(){
  // Inicializar filtro de mes al mes actual si está vacío
  const mesFiltro = document.getElementById('egr-mes-filtro');
  const infMes = document.getElementById('infl-mes');
  const egrFecha = document.getElementById('egr-fecha');
  const hoy = new Date().toISOString().slice(0,10);
  const mesActual = hoy.slice(0,7);
  if(mesFiltro && !mesFiltro.value) mesFiltro.value = mesActual;
  if(infMes && !infMes.value) infMes.value = mesActual;
  if(egrFecha && !egrFecha.value) egrFecha.value = hoy;

  // Cargar categorías en el select (una vez)
  const sel = document.getElementById('egr-categoria');
  if(sel && !sel.options.length){
    const r = await api('/api/contabilidad/egresos');
    (r?.categorias || []).forEach(c => {
      const o = document.createElement('option'); o.value = c; o.textContent = c; sel.appendChild(o);
    });
  }
  await loadEgresos();
  await loadInflacion();
  await loadContResumen();
}

function _money(n){ return '$' + (Math.round(n||0)).toLocaleString('es-AR'); }

async function loadContResumen(){
  const r = await api('/api/contabilidad/resumen');
  if(!r) return;
  const ult = r.meses[r.meses.length-1];
  const ing = (r.ingresos.find(x=>x.mes===ult)||{}).valor || 0;
  const egr = (r.egresos.find(x=>x.mes===ult)||{}).valor || 0;
  const inf = (r.inflacion.find(x=>x.mes===ult)||{}).valor;
  document.getElementById('cont-ing').textContent = _money(ing);
  document.getElementById('cont-egr').textContent = _money(egr);
  const gan = ing - egr;
  const ge = document.getElementById('cont-gan');
  ge.textContent = _money(gan);
  ge.style.color = gan >= 0 ? 'var(--vd2,#4FB88A)' : 'var(--rj2,#E08063)';
  document.getElementById('cont-infl').textContent = (inf != null) ? inf + '%' : '— sin cargar';
}

async function loadEgresos(){
  const mes = document.getElementById('egr-mes-filtro')?.value || '';
  const r = await api('/api/contabilidad/egresos?mes=' + mes);
  if(!r) return;
  const tb = document.getElementById('egr-tbody');
  if(!r.egresos.length){
    tb.innerHTML = '<tr><td colspan="5" style="color:var(--txt2);padding:.8rem">Sin egresos cargados en este mes.</td></tr>';
  } else {
    tb.innerHTML = r.egresos.map(e => `<tr>
      <td>${escHtml(e.fecha)}</td>
      <td>${escHtml(e.categoria)}</td>
      <td style="text-align:right;font-family:'IBM Plex Mono',monospace">${_money(e.monto)}</td>
      <td style="color:var(--txt2)">${escHtml(e.descripcion)||'—'}</td>
      <td><button class="btn btn-gray btn-xs" onclick="borrarEgreso(${e.id})" title="Eliminar">🗑</button></td>
    </tr>`).join('');
  }
  // Chips por categoría
  const chips = document.getElementById('egr-por-categoria');
  const cats = Object.entries(r.por_categoria || {});
  if(cats.length){
    const total = cats.reduce((a,[,v])=>a+v, 0);
    chips.innerHTML = cats.map(([c,v]) => `<span style="background:var(--card);border:1px solid var(--brd);border-radius:20px;padding:.25rem .6rem;font-size:.76rem">
      ${escHtml(c)}: <b style="font-family:'IBM Plex Mono',monospace">${_money(v)}</b></span>`).join('')
      + `<span style="background:rgba(224,168,56,.12);border:1px solid rgba(224,168,56,.3);border-radius:20px;padding:.25rem .6rem;font-size:.76rem;color:var(--am2,#E0A838)">
        Total: <b>${_money(total)}</b></span>`;
  } else { chips.innerHTML = ''; }
}

async function guardarEgreso(){
  const fecha = document.getElementById('egr-fecha').value;
  const categoria = document.getElementById('egr-categoria').value;
  const monto = parseFloat(document.getElementById('egr-monto').value);
  if(!fecha || !categoria || !monto){ alert('Completá fecha, categoría y monto.'); return; }
  const r = await api('/api/contabilidad/egresos', 'POST', {
    fecha, categoria, monto, descripcion: document.getElementById('egr-desc').value
  });
  if(r?.error){ alert('Error: ' + r.error); return; }
  document.getElementById('egr-monto').value = '';
  document.getElementById('egr-desc').value = '';
  // Alinear el filtro al mes del egreso cargado para verlo
  const filtro = document.getElementById('egr-mes-filtro');
  if(filtro) filtro.value = fecha.slice(0,7);
  await loadEgresos();
  await loadContResumen();
}

async function borrarEgreso(id){
  if(!confirm('¿Eliminar este egreso?')) return;
  const r = await api('/api/contabilidad/egresos/' + id, 'DELETE');
  if(r?.error){ alert('Error: ' + r.error); return; }
  await loadEgresos();
  await loadContResumen();
}

async function loadInflacion(){
  const r = await api('/api/contabilidad/inflacion');
  if(!r) return;
  const tb = document.getElementById('infl-tbody');
  if(!r.length){
    tb.innerHTML = '<tr><td colspan="3" style="color:var(--txt2);padding:.8rem">Sin índices cargados.</td></tr>';
    return;
  }
  tb.innerHTML = r.map(i => `<tr>
    <td>${escHtml(i.mes)}</td>
    <td style="text-align:right;font-family:'IBM Plex Mono',monospace">${i.indice_pct}%</td>
    <td style="color:var(--txt2)">${escHtml(i.creado_por)||'—'}</td>
  </tr>`).join('');
}

async function guardarInflacion(){
  const mes = document.getElementById('infl-mes').value;
  const pct = parseFloat(document.getElementById('infl-pct').value);
  if(!mes || isNaN(pct)){ alert('Completá mes e índice.'); return; }
  const r = await api('/api/contabilidad/inflacion', 'POST', {mes, indice_pct: pct});
  if(r?.error){ alert('Error: ' + r.error); return; }
  document.getElementById('infl-pct').value = '';
  await loadInflacion();
  await loadContResumen();
}
