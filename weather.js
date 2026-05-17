/* ========================================================
   weather.js — ERLAN NetAdmin v7
   Refactor etapa 2: separación de JS por dominio
   ======================================================== */

const WEATHER_CODES={
  0:'☀️ Despejado',1:'🌤 Mayormente despejado',2:'⛅ Parcialmente nublado',3:'☁️ Nublado',
  45:'🌫 Niebla',48:'🌫 Niebla con escarcha',
  51:'🌦 Llovizna leve',53:'🌦 Llovizna',55:'🌦 Llovizna densa',
  61:'🌧 Lluvia leve',63:'🌧 Lluvia',65:'🌧 Lluvia intensa',
  71:'❄️ Nieve leve',73:'❄️ Nieve',75:'❄️ Tormenta de nieve',
  80:'⛈ Chaparrones',81:'⛈ Chaparrones moderados',82:'⛈ Chaparrones intensos',
  95:'⛈ Tormenta',96:'⛈ Tormenta con granizo',99:'⛈ Tormenta severa'
};

async function loadWeatherCarousel(){
  // Coordenadas de Paraná, Entre Ríos (sede principal)
  const lat=-31.73,lng=-60.53;
  try{
    const r=await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&current_weather=true&timezone=America/Argentina/Buenos_Aires`);
    const d=await r.json();
    if(!d.current_weather) return;
    const cw=d.current_weather;
    const desc=WEATHER_CODES[cw.weathercode]||'🌡 Sin datos';
    // Insertar slide de clima en el carrusel
    carouselItems.unshift({
      icon:'🌡',
      title:'CLIMA — PARANÁ',
      text:`${desc} | ${Math.round(cw.temperature)}°C | Viento ${Math.round(cw.windspeed)} km/h`,
      badge:'',
      badgeClass:''
    });
    renderCarousel();
  }catch(e){console.log('Weather error:',e);}
}

async function openWeatherModal(){
  document.getElementById('modal-weather').style.display='flex';
  const body=document.getElementById('weather-body');
  body.innerHTML='<div class="empty">Cargando pronóstico...</div>';
  const lat=-31.73, lng=-60.53;
  try{
    const r=await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max&timezone=America/Argentina/Buenos_Aires`);
    const d=await r.json();
    if(!d.daily){body.innerHTML='<div class="empty">Error al cargar el pronóstico</div>';return;}
    const {time,weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max}=d.daily;
    const dias=['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'];
    body.innerHTML=`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:.6rem">
      ${time.map((t,i)=>{
        const fecha=new Date(t+'T12:00:00');
        const dia=dias[fecha.getDay()];
        const desc=WEATHER_CODES[weathercode[i]]||'—';
        const icn=desc.split(' ')[0];
        return `<div style="background:var(--fondo);border-radius:10px;padding:.8rem;text-align:center;border:1px solid var(--brd)">
          <div style="font-size:.75rem;color:var(--txt2);font-weight:700">${dia} ${fecha.getDate()}/${fecha.getMonth()+1}</div>
          <div style="font-size:2rem;margin:.3rem 0">${icn}</div>
          <div style="font-size:.72rem;color:var(--txt2);margin-bottom:.3rem">${desc.slice(desc.indexOf(' ')+1)}</div>
          <div style="font-size:.95rem;font-weight:700;color:var(--az2)">${Math.round(temperature_2m_max[i])}° <span style="font-size:.8rem;color:var(--txt2)">/ ${Math.round(temperature_2m_min[i])}°</span></div>
          ${precipitation_sum[i]>0?`<div style="font-size:.72rem;color:#2d5a8e;margin-top:.2rem">💧 ${precipitation_sum[i]}mm</div>`:''}
          <div style="font-size:.68rem;color:var(--txt2);margin-top:.2rem">💨 ${Math.round(windspeed_10m_max[i])} km/h</div>
        </div>`;
      }).join('')}
    </div>`;
  }catch(e){body.innerHTML='<div class="empty">Error al cargar el pronóstico</div>';}
}

// ── INIT AUTH EXTENDED ──
// (initAuth ya definida arriba con permisos — no duplicar)

// ── INPUT LISTENERS para preview PPPoE ──
['act-pppoe-user','act-pppoe-pass','act-ip'].forEach(id=>{
  const el=document.getElementById(id);
  if(el) el.addEventListener('input',actualizarPreview);
});

// Cerrar dropdown de activación al click fuera
document.addEventListener('click',e=>{
  const drop=document.getElementById('act-nap-drop');
  const input=document.getElementById('act-nap-q');
  if(drop&&input&&!drop.contains(e.target)&&!input.contains(e.target))
    drop.style.display='none';
});

// ── MONITOREO ──
