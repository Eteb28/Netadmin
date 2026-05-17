/* ========================================================
   config.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

async function loadConfig(){
  const d=await api('/api/configuracion');
  if(!d) return;
  const cfg={};
  d.forEach(c=>{cfg[c.clave]=c.valor;});
  const set=(id,val)=>{const e=document.getElementById(id);if(e)e.value=val||'';};
  set('cfg-tg-token',cfg.telegram_token);
  set('cfg-tg-chatid',cfg.telegram_chat_id);
  set('cfg-mon-intervalo',cfg.monitoreo_intervalo||'60');
  set('cfg-nap-umbral',cfg.alerta_nap_umbral||'6');
  set('cfg-ping-timeout',cfg.ping_timeout||'2');
  set('cfg-uisp-url',cfg.uisp_url);
  set('cfg-uisp-token',cfg.uisp_token);
  // Empresa
  const emp=await api('/api/empresa');
  if(emp){
    set('cfg-razon',emp.razon_social);
    set('cfg-fantasia',emp.nombre_fantasia);
    set('cfg-cuit',emp.cuit);
    set('cfg-tel',emp.telefono);
    set('cfg-dir',emp.direccion);
    set('cfg-email',emp.email);
  }
}

async function saveConfig(){
  const val=(id)=>(document.getElementById(id)||{value:''}).value;
  const data={
    telegram_token:val('cfg-tg-token'),
    telegram_chat_id:val('cfg-tg-chatid'),
    monitoreo_intervalo:val('cfg-mon-intervalo'),
    alerta_nap_umbral:val('cfg-nap-umbral'),
    ping_timeout:val('cfg-ping-timeout'),
    uisp_url:val('cfg-uisp-url'),
    uisp_token:val('cfg-uisp-token')
  };
  const r=await api('/api/configuracion','PUT',data);
  if(r?.ok) alert('✅ Configuración guardada');
  else alert('Error al guardar');
}

async function saveEmpresa(){
  const val=(id)=>(document.getElementById(id)||{value:''}).value;
  const r=await api('/api/empresa','PUT',{
    razon_social:val('cfg-razon'), nombre_fantasia:val('cfg-fantasia'),
    cuit:val('cfg-cuit'), telefono:val('cfg-tel'),
    direccion:val('cfg-dir'), email:val('cfg-email')
  });
  if(r?.ok) alert('✅ Datos de empresa guardados');
}

async function testTelegram(){
  const res=document.getElementById('cfg-tg-result');
  res.innerHTML='Enviando...';
  const r=await api('/api/configuracion/test_telegram','POST');
  if(r?.ok) res.innerHTML='<span style="color:var(--vd)">✅ Mensaje enviado correctamente por Telegram</span>';
  else res.innerHTML=`<span style="color:var(--rj)">❌ ${r?.error||'Error al enviar'}</span>`;
}

function testUisp(){ alert('Funcionalidad UISP disponible — configurá URL y Token para activarla'); }
