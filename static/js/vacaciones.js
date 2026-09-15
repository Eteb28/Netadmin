// ════════════════════════════════════════════════════════
// CALENDARIO DE VACACIONES EN DASHBOARD + solicitud
// ════════════════════════════════════════════════════════
let _dashVacMes = null;
let _miEmpleado = null;

function _vacMesISO(offset=0){
  const d = new Date(); d.setDate(1); d.setMonth(d.getMonth()+offset);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
}

async function loadDashVacaciones(){
  if(!_dashVacMes) _dashVacMes = _vacMesISO(0);
  // Saber si el usuario está vinculado a un empleado (para mostrar botón solicitar)
  if(_miEmpleado === null){
    _miEmpleado = await api('/api/mi_empleado') || {vinculado:false};
  }
  const btn = document.getElementById('dash-vac-solicitar');
  const saldo = document.getElementById('dash-vac-saldo');
  // El botón se muestra SIEMPRE: todos los empleados deben poder solicitar.
  // Si el usuario no está vinculado a un legajo, al hacer clic se le explica
  // qué falta (antes el botón simplemente no aparecía y no se entendía por qué).
  if(btn) btn.style.display = 'inline-block';
  if(_miEmpleado.vinculado){
    if(saldo && _miEmpleado.vacaciones){
      const v = _miEmpleado.vacaciones;
      saldo.textContent = `Tus días: ${v.disponibles} disponibles` +
        (v.pendientes_aprobacion ? ` · ${v.pendientes_aprobacion} pend. aprobación` : '');
    }
  } else if(saldo){
    saldo.textContent = '';
  }
  const data = await api(`/api/empleados/ausencias?mes=${_dashVacMes}`);
  if(data) renderDashVacCalendario(data);
}

function cambiarMesDashVac(delta){
  const [y,m] = (_dashVacMes||_vacMesISO(0)).split('-').map(Number);
  const d = new Date(y, m-1+delta, 1);
  _dashVacMes = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
  loadDashVacaciones();
}

function renderDashVacCalendario(data){
  const cont = document.getElementById('dash-vac-calendario');
  const lbl = document.getElementById('dash-vac-mes');
  if(!cont) return;
  const [y,m] = data.mes.split('-').map(Number);
  const meses = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
  if(lbl) lbl.textContent = `${meses[m]} ${y}`;
  const diasMes = new Date(y, m, 0).getDate();
  const primerDia = new Date(y, m-1, 1).getDay();

  // Solo vacaciones (el dashboard es de vacaciones), pero mostramos todas las ausencias suaves
  const colorEstado = (a) => {
    if(a.estado === 'pendiente') return '#f9a825';   // amarillo: pendiente de aprobar
    if(a.estado === 'rechazada') return '#bdbdbd';    // gris: rechazada
    const t = (a.tipo||'').toLowerCase();
    if(t.includes('vacacion')) return '#2e7d32';
    if(t.includes('licencia')) return '#1565c0';
    if(t.includes('ausencia')) return '#e65100';
    if(t.includes('suspen')) return '#c62828';
    return '#6a1b9a';
  };

  const porDia = {};
  for(const a of data.ausencias){
    if(a.estado === 'rechazada') continue;  // no mostrar rechazadas
    const desde = new Date(a.fecha_desde+'T00:00:00');
    const hasta = a.fecha_hasta ? new Date(a.fecha_hasta+'T00:00:00') : desde;
    for(let dia=1; dia<=diasMes; dia++){
      const f = new Date(y, m-1, dia);
      if(f>=desde && f<=hasta) (porDia[dia]=porDia[dia]||[]).push(a);
    }
  }

  const dse = ['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'];
  let celdas = dse.map(d=>`<div style="font-weight:700;font-size:.68rem;text-align:center;color:var(--txt2);padding:3px">${d}</div>`).join('');
  for(let i=0;i<primerDia;i++) celdas += '<div></div>';
  for(let dia=1; dia<=diasMes; dia++){
    const aus = porDia[dia]||[];
    const chips = aus.slice(0,3).map(a=>{
      const pend = a.estado==='pendiente' ? ' ⏳' : '';
      const per = (a.periodo && (a.tipo||'').toLowerCase().includes('vacacion')) ? ` · Período ${a.periodo}` : '';
      return `<div style="font-size:.58rem;background:${colorEstado(a)};color:#fff;border-radius:3px;padding:1px 3px;margin-top:1px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis" title="${a.empleado}: ${a.tipo} (${a.estado||'autorizada'})${per}">${a.empleado.split(' ')[0]}${pend}</div>`;
    }).join('');
    const mas = aus.length>3 ? `<div style="font-size:.52rem;color:var(--txt2)">+${aus.length-3}</div>` : '';
    celdas += `<div style="border:1px solid var(--brd);border-radius:5px;min-height:54px;padding:2px;background:${aus.length?'var(--surf2)':'var(--card)'}">
      <div style="font-size:.66rem;font-weight:600;color:var(--txt2)">${dia}</div>${chips}${mas}</div>`;
  }
  const leyenda = `<div style="display:flex;gap:.7rem;flex-wrap:wrap;margin-top:.5rem;font-size:.68rem;color:var(--txt2)">
    <span><span style="display:inline-block;width:9px;height:9px;background:#2e7d32;border-radius:2px"></span> Vacaciones</span>
    <span><span style="display:inline-block;width:9px;height:9px;background:#f9a825;border-radius:2px"></span> Pendiente ⏳</span>
    <span><span style="display:inline-block;width:9px;height:9px;background:#1565c0;border-radius:2px"></span> Licencia</span>
  </div>`;
  cont.innerHTML = `<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px">${celdas}</div>${leyenda}`;
}

// ── Solicitar vacaciones (empleado) ──
function abrirSolicitarVacaciones(){
  // Si el usuario no está vinculado a un legajo, no puede solicitar: se lo
  // explicamos en vez de esconder el botón (antes desaparecía sin motivo visible).
  if(_miEmpleado && !_miEmpleado.vinculado){
    alert('Tu usuario todavía no está vinculado a un legajo de RRHH, por eso no ' +
          'se pueden registrar tus vacaciones.\n\nPedile a RRHH que asocie tu usuario ' +
          'al legajo (campo "Usuario del sistema" en tu ficha de empleado).');
    return;
  }
  document.getElementById('solvac-desde').value='';
  document.getElementById('solvac-hasta').value='';
  document.getElementById('solvac-motivo').value='';
  document.getElementById('solvac-dias').textContent='—';
  const medio = document.getElementById('solvac-medio'); if(medio) medio.checked=false;
  toggleMedioDiaSol();
  // Período: año actual por defecto, con un par de años hacia atrás/adelante
  const sel = document.getElementById('solvac-periodo');
  if(sel){
    const y = new Date().getFullYear();
    const anios = [y+1, y, y-1, y-2];
    sel.innerHTML = anios.map(a=>`<option value="${a}" ${a===y?'selected':''}>Período ${a}</option>`).join('');
  }
  const v = _miEmpleado && _miEmpleado.vacaciones;
  if(v){
    document.getElementById('solvac-saldo').textContent = `Disponibles: ${v.disponibles} días en total`;
    // Desglose por período
    const des = document.getElementById('solvac-desglose');
    if(des){
      if(v.por_periodo && v.por_periodo.length){
        des.innerHTML = '<div style="color:var(--txt2);margin-bottom:.2rem">Por período:</div>' +
          v.por_periodo.map(p=>`<div style="display:flex;justify-content:space-between;border-bottom:1px solid var(--brd);padding:.15rem 0">
            <span>Período ${p.periodo}</span>
            <span><b>${p.disponibles}</b> disp. <span style="color:var(--txt2)">(de ${p.asignados}${p.pendientes?`, ${p.pendientes} pend.`:''})</span></span>
          </div>`).join('');
      } else {
        des.innerHTML = '<span style="color:var(--txt2)">RRHH todavía no cargó días por período; se usa el total general.</span>';
      }
    }
  }
  // Historial: últimas 4 solicitudes (pedido de RRHH, para que el empleado
  // pueda verificar y reclamar si algo no coincide)
  const hist = document.getElementById('solvac-historial');
  if(hist){
    const us = (_miEmpleado && _miEmpleado.ultimas_solicitudes) || [];
    if(!us.length){
      hist.innerHTML = '<div style="color:var(--txt2)">Sin solicitudes anteriores registradas.</div>';
    } else {
      const badge = e => e==='autorizada' ? '<span style="color:#2e7d32">✓ autorizada</span>'
                    : e==='pendiente'     ? '<span style="color:#e8a13b">⏳ pendiente</span>'
                    : e==='rechazada'     ? '<span style="color:#c62828">✕ rechazada</span>'
                    : (e||'—');
      const dias = d => d==null ? '—' : (Number(d)===0.5 ? 'medio día' : `${d} día${d>1?'s':''}`);
      const fecha = f => f ? f.split('-').reverse().join('/') : '—';
      hist.innerHTML =
        '<div style="color:var(--txt2);margin-bottom:.25rem">Tus últimas solicitudes:</div>' +
        '<table style="width:100%;border-collapse:collapse">' +
        us.map(u=>`<tr style="border-bottom:1px solid var(--brd)">
            <td style="padding:.22rem 0">${fecha(u.fecha_desde)}${u.fecha_hasta && u.fecha_hasta!==u.fecha_desde?` → ${fecha(u.fecha_hasta)}`:''}</td>
            <td style="text-align:center"><b>${dias(u.dias)}</b></td>
            <td style="text-align:center;color:var(--txt2)">${u.periodo?`Per. ${u.periodo}`:'—'}</td>
            <td style="text-align:right">${badge(u.estado)}</td>
          </tr>`).join('') +
        '</table>';
    }
  }
  document.getElementById('modal-solicitar-vac').style.display='flex';
}

function toggleMedioDiaSol(){
  const medio = document.getElementById('solvac-medio');
  const wrap = document.getElementById('solvac-hasta-wrap');
  if(wrap) wrap.style.display = (medio && medio.checked) ? 'none' : '';
  calcDiasSolVac();
}

function calcDiasSolVac(){
  const medio = document.getElementById('solvac-medio');
  const lbl = document.getElementById('solvac-dias');
  if(medio && medio.checked){ lbl.textContent = '0,5 día'; return; }
  const d = document.getElementById('solvac-desde').value;
  const h = document.getElementById('solvac-hasta').value;
  if(d && h){
    const dias = Math.round((new Date(h)-new Date(d))/86400000)+1;
    lbl.textContent = dias>0 ? `${dias} día(s)` : 'Fechas inválidas';
  } else lbl.textContent='—';
}

async function enviarSolicitudVac(){
  const desde = document.getElementById('solvac-desde').value;
  let hasta = document.getElementById('solvac-hasta').value;
  const motivo = document.getElementById('solvac-motivo').value;
  const periodo = (document.getElementById('solvac-periodo')||{}).value || null;
  const medioDia = !!(document.getElementById('solvac-medio') && document.getElementById('solvac-medio').checked);
  if(!desde){ alert('Indicá la fecha de inicio'); return; }
  if(medioDia) hasta = desde;
  const r = await api('/api/vacaciones/solicitar', 'POST', {fecha_desde:desde, fecha_hasta:hasta, motivo, periodo, medio_dia:medioDia});
  if(r && r.ok){
    alert(r.msg || 'Solicitud enviada');
    closeModal('modal-solicitar-vac');
    _miEmpleado = null;  // forzar refresco de saldo
    loadDashVacaciones();
  } else {
    alert(r?.error || 'No se pudo enviar la solicitud');
  }
}
