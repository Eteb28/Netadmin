/* ========================================================
   logs.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadHistorial(){
  const d=await api('/api/historial');
  if(!d) return;
  const tbody=document.getElementById('hist-tbody');
  tbody.innerHTML=d.map(h=>`<tr>
    <td style="white-space:nowrap;font-size:.75rem">${h.fecha?.slice(0,16)||'—'}</td>
    <td>${h.usuario||'—'}</td>
    <td><span class="badge b-activo">${h.tipo||''}</span></td>
    <td>${h.titulo||''}</td>
    <td style="font-size:.75rem;color:var(--txt2)">${h.detalle||''}</td>
  </tr>`).join('');
}

// ── USUARIOS ──

async function cargarHistorialSenal(nap){
  const d=await api(`/api/historial_senal?nap=${encodeURIComponent(nap)}&limit=20`);
  const div=document.getElementById('msenal-history');
  if(!d||!d.length){div.innerHTML='<div class="empty">Sin mediciones registradas</div>';return;}
  div.innerHTML=`<div class="tbl-wrap"><table>
    <thead><tr><th>Fecha</th><th>Nivel</th><th>Observaciones</th><th>Usuario</th></tr></thead>
    <tbody>${d.map(h=>`<tr>
      <td style="font-size:.77rem">${h.fecha?.slice(0,16)||'—'}</td>
      <td style="font-family:monospace;font-weight:700;color:${(h.nivel_dbm||0)>-20?'var(--vd)':(h.nivel_dbm||0)>-25?'var(--am)':'var(--rj)'}">${h.nivel_dbm} dBm</td>
      <td style="font-size:.77rem">${h.observaciones||'—'}</td>
      <td style="font-size:.75rem">${h.registrado_por||'—'}</td>
    </tr>`).join('')}</tbody>
  </table></div>`;
}
