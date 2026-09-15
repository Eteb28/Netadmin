/* ========================================================
   tecnicos.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadTecnicos(){
  const tecs=await api('/api/tecnicos');
  if(!tecs) return;
  document.getElementById('tecnico-datalist').innerHTML=tecs.map(t=>`<option value="${t}">`).join('');
  const sel=document.getElementById('svc-tecnico');
  sel.innerHTML='<option value="">Todos los técnicos</option>'+tecs.map(t=>`<option value="${t}">${t}</option>`).join('');
}

// ════════════════════════════════════════════════════════
// PRODUCTIVIDAD POR TÉCNICO
// ════════════════════════════════════════════════════════
let _prodVisible = false;

async function toggleProductividad(){
  const cont = document.getElementById('svc-productividad');
  if(!cont) return;
  _prodVisible = !_prodVisible;
  cont.style.display = _prodVisible ? 'block' : 'none';
  if(_prodVisible) await loadProductividad();
}

async function loadProductividad(){
  const data = await api('/api/servicios/por_tecnico');
  const cont = document.getElementById('svc-productividad');
  if(!cont || !data) return;

  const tiposClave = ['instalacion','servicio_tecnico','mantenimiento','calculo_enlace','rescision_retiro'];
  const tipoLabel = {instalacion:'Instal.', servicio_tecnico:'Serv.Téc.', mantenimiento:'Mant.', calculo_enlace:'Cálculo', rescision_retiro:'Rescis.'};

  const tabla = (lista, titulo, icono) => {
    if(!lista || !lista.length) return `<div style="color:#888;padding:.5rem;font-size:.85rem">${icono} ${titulo}: sin datos</div>`;
    const filas = lista.map(t => {
      const cols = tiposClave.map(tp => `<td style="text-align:center">${t.por_tipo[tp]||0}</td>`).join('');
      return `<tr>
        <td><b>${escHtml(t.tecnico)}</b></td>
        <td style="text-align:center"><span style="color:#f9a825;font-weight:700">${t.pendientes}</span></td>
        <td style="text-align:center"><span style="color:#2e7d32;font-weight:700">${t.realizados}</span></td>
        ${cols}
        <td style="text-align:center"><b>${t.total}</b></td>
      </tr>`;
    }).join('');
    return `<div style="margin-bottom:1rem">
      <div style="font-weight:600;margin-bottom:.4rem">${icono} ${titulo} <span style="color:var(--txt2);font-weight:400;font-size:.8rem">(${lista.length})</span></div>
      <div style="overflow:auto"><table class="tbl">
        <thead><tr><th>Nombre</th><th>Pend.</th><th>Realiz.</th>${tiposClave.map(tp=>`<th>${tipoLabel[tp]}</th>`).join('')}<th>Total</th></tr></thead>
        <tbody>${filas}</tbody>
      </table></div>
    </div>`;
  };

  let aviso = '';
  if(!data.lista_configurada){
    aviso = `<div style="background:var(--tint-ambar);border:1px solid #ffc107;border-radius:6px;padding:.5rem;font-size:.8rem;margin-bottom:.7rem">
      ⚠ No hay lista de técnicos de campo configurada. Se muestran todos juntos.
      Configurala en <b>Config → Técnicos de campo</b> para separar técnicos de usuarios admin.</div>`;
  }

  cont.innerHTML = `<div class="card" style="margin-bottom:.7rem">
    <div class="stitle">📊 Productividad por técnico</div>
    <div style="font-size:.78rem;color:var(--txt2);margin-bottom:.5rem">Basado en el técnico asignado (codtecnico) de cada trabajo.</div>
    ${aviso}
    ${tabla(data.tecnicos_campo, 'Técnicos de campo', '👷')}
    ${data.usuarios_admin && data.usuarios_admin.length ? tabla(data.usuarios_admin, 'Usuarios / Administrativos', '🧑‍💼') : ''}
  </div>`;
}
