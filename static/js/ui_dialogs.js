/* ════════════════════════════════════════════════════════
   ui_dialogs.js — Avisos y confirmaciones propios (no bloqueantes)
   Reemplaza alert() y confirm() nativos por diálogos HTML.
   Se carga ANTES que el resto del JS para sobreescribir los globales.
   ════════════════════════════════════════════════════════ */

(function(){
  // ── Estilos inyectados una sola vez ──
  if(!document.getElementById('ui-dialogs-css')){
    const css = document.createElement('style');
    css.id = 'ui-dialogs-css';
    css.textContent = `
      .ui-toast-wrap{position:fixed;top:14px;right:14px;z-index:99999;display:flex;flex-direction:column;gap:8px;max-width:min(380px,92vw)}
      .ui-toast{background:var(--card);border-left:4px solid #1565c0;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.18);
        padding:.7rem .9rem;font-size:.85rem;color:var(--txt);display:flex;gap:.5rem;align-items:flex-start;
        animation:uiToastIn .2s ease;cursor:pointer;word-break:break-word}
      .ui-toast.ok{border-left-color:#2e7d32}
      .ui-toast.err{border-left-color:#c62828}
      .ui-toast.warn{border-left-color:#f9a825}
      .ui-toast .ico{font-size:1.1rem;line-height:1.2;flex-shrink:0}
      @keyframes uiToastIn{from{opacity:0;transform:translateX(30px)}to{opacity:1;transform:translateX(0)}}
      .ui-modal-ov{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99998;display:flex;
        align-items:center;justify-content:center;animation:uiFadeIn .15s ease;padding:1rem}
      @keyframes uiFadeIn{from{opacity:0}to{opacity:1}}
      .ui-modal-box{background:var(--card);border-radius:12px;max-width:440px;width:100%;
        box-shadow:0 12px 40px rgba(0,0,0,.3);overflow:hidden;animation:uiBoxIn .2s ease}
      @keyframes uiBoxIn{from{transform:scale(.94);opacity:.6}to{transform:scale(1);opacity:1}}
      .ui-modal-hd{padding:1rem 1.2rem .4rem;font-weight:700;font-size:1.02rem;color:#1a3d6b;display:flex;gap:.5rem;align-items:center}
      .ui-modal-body{padding:.3rem 1.2rem 1rem;font-size:.9rem;color:var(--txt);line-height:1.5;white-space:pre-wrap}
      .ui-modal-ft{display:flex;justify-content:flex-end;gap:.5rem;padding:.7rem 1.2rem 1.1rem}
      .ui-btn{border:none;border-radius:7px;padding:.5rem 1.1rem;font-size:.88rem;font-weight:600;cursor:pointer;transition:.12s}
      .ui-btn-primary{background:#1565c0;color:#fff}
      .ui-btn-primary:hover{background:#0d47a1}
      .ui-btn-danger{background:#c62828;color:#fff}
      .ui-btn-danger:hover{background:#a01b1b}
      .ui-btn-gray{background:var(--card);color:var(--txt2)}
      .ui-btn-gray:hover{background:var(--surf2)}
    `;
    document.head.appendChild(css);
  }

  function _wrap(){
    let w = document.querySelector('.ui-toast-wrap');
    if(!w){ w = document.createElement('div'); w.className = 'ui-toast-wrap'; document.body.appendChild(w); }
    return w;
  }

  // ── TOAST (aviso no bloqueante) ──
  window.toast = function(mensaje, tipo){
    const w = _wrap();
    const t = document.createElement('div');
    const iconos = {ok:'✅', err:'⛔', warn:'⚠️', info:'ℹ️'};
    t.className = 'ui-toast ' + (tipo || 'info');
    t.innerHTML = `<span class="ico">${iconos[tipo] || iconos.info}</span><span>${String(mensaje).replace(/</g,'&lt;')}</span>`;
    const quitar = ()=>{ t.style.opacity='0'; t.style.transform='translateX(30px)'; setTimeout(()=>t.remove(), 200); };
    t.onclick = quitar;
    w.appendChild(t);
    setTimeout(quitar, tipo === 'err' ? 6000 : 4000);
  };

  // ── alert() → toast (detecta tipo por contenido) ──
  const _alertNativo = window.alert;
  window.alert = function(msg){
    const s = String(msg);
    let tipo = 'info';
    if(/✓|✅|correctamente|guardado|registrad|asignad|liberad|actualizad|éxito|exito/i.test(s)) tipo = 'ok';
    else if(/error|⛔|no se pudo|inválid|invalid|fall|no tenés|no hay|⚠/i.test(s)) tipo = 'err';
    else if(/ojo|atención|atencion|cuidado|verificá|verifica/i.test(s)) tipo = 'warn';
    window.toast(s, tipo);
  };

  // ── confirmar() → diálogo con promesa (para usar con await) ──
  window.confirmar = function(mensaje, opciones){
    opciones = opciones || {};
    return new Promise(resolve=>{
      const ov = document.createElement('div');
      ov.className = 'ui-modal-ov';
      const peligro = opciones.peligro || /elimin|borrar|dar de baja|baja|quitar/i.test(String(mensaje));
      const btnOkClass = peligro ? 'ui-btn-danger' : 'ui-btn-primary';
      const okTxt = opciones.ok || (peligro ? 'Eliminar' : 'Confirmar');
      const cancelTxt = opciones.cancel || 'Cancelar';
      const titulo = opciones.titulo || (peligro ? '¿Estás seguro?' : 'Confirmar');
      const icono = opciones.icono || (peligro ? '🗑️' : '❓');
      ov.innerHTML = `
        <div class="ui-modal-box" role="dialog">
          <div class="ui-modal-hd">${icono} ${titulo}</div>
          <div class="ui-modal-body">${String(mensaje).replace(/</g,'&lt;')}</div>
          <div class="ui-modal-ft">
            <button class="ui-btn ui-btn-gray" data-r="0">${cancelTxt}</button>
            <button class="ui-btn ${btnOkClass}" data-r="1">${okTxt}</button>
          </div>
        </div>`;
      const cerrar = (val)=>{ ov.style.opacity='0'; setTimeout(()=>ov.remove(),150); resolve(val); };
      ov.querySelector('[data-r="0"]').onclick = ()=>cerrar(false);
      ov.querySelector('[data-r="1"]').onclick = ()=>cerrar(true);
      ov.onclick = (e)=>{ if(e.target===ov) cerrar(false); };
      document.addEventListener('keydown', function esc(ev){
        if(ev.key==='Escape'){ cerrar(false); document.removeEventListener('keydown', esc); }
      });
      document.body.appendChild(ov);
      ov.querySelector('[data-r="1"]').focus();
    });
  };

  // ── confirm() nativo → versión que NO bloquea pero mantiene compatibilidad ──
  // Como no se puede hacer sincrónico sin bloquear, confirm() ahora muestra el
  // diálogo y devuelve false inmediato si se usa en la forma vieja. Por eso el
  // resto del código migra a `await confirmar(...)`. Dejamos confirm como alias
  // que advierte en consola (no debería quedar ninguno tras la migración).
  // ── pedirDato() → diálogo de entrada (reemplaza prompt) ──
  window.pedirDato = function(mensaje, valorDefault, opciones){
    opciones = opciones || {};
    return new Promise(resolve=>{
      const ov = document.createElement('div');
      ov.className = 'ui-modal-ov';
      const tipo = opciones.tipo || 'text';
      const ph = opciones.placeholder || '';
      ov.innerHTML = `
        <div class="ui-modal-box" role="dialog">
          <div class="ui-modal-hd">✏️ ${opciones.titulo || 'Ingresá un dato'}</div>
          <div class="ui-modal-body">${String(mensaje).replace(/</g,'&lt;')}
            <input id="ui-input-dato" type="${tipo}" value="${(valorDefault||'').toString().replace(/"/g,'&quot;')}"
              placeholder="${ph}" style="width:100%;margin-top:.6rem;padding:.5rem;border:1.5px solid var(--brd);border-radius:7px;font-size:.95rem">
          </div>
          <div class="ui-modal-ft">
            <button class="ui-btn ui-btn-gray" data-r="0">Cancelar</button>
            <button class="ui-btn ui-btn-primary" data-r="1">Aceptar</button>
          </div>
        </div>`;
      const inp = ov.querySelector('#ui-input-dato');
      const cerrar = (val)=>{ ov.style.opacity='0'; setTimeout(()=>ov.remove(),150); resolve(val); };
      ov.querySelector('[data-r="0"]').onclick = ()=>cerrar(null);
      ov.querySelector('[data-r="1"]').onclick = ()=>cerrar(inp.value);
      ov.onclick = (e)=>{ if(e.target===ov) cerrar(null); };
      inp.addEventListener('keydown', (ev)=>{
        if(ev.key==='Enter') cerrar(inp.value);
        if(ev.key==='Escape') cerrar(null);
      });
      document.body.appendChild(ov);
      inp.focus(); inp.select();
    });
  };

  window._confirmNativo = window.confirm;
})();
