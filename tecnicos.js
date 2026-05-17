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
