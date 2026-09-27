export const palette = [
  ['Menta','#64e6ca'],['Turquesa','#00c6b7'],['Azul','#5295ff'],['Violeta','#a799ff'],
  ['Rosa','#ff70bd'],['Rojo','#ff5263'],['Naranja','#ff9952'],['Ámbar','#ffc879'],
  ['Amarillo','#ffe66b'],['Lima','#b8eb62'],['Blanco','#ffffff'],['Cálido','#ffe8c6'],
  ['Pizarra','#516078'],['Noche','#101b2b'],['Carbón','#24252b'],['Negro','#000000'],
];
export const moods = [
  ['Océano','#5295ff',45,false],['Aurora','#64e6ca',60,false],['Atardecer','#ffc879',45,false],
  ['Neón','#ff70bd',80,false],['Lectura','#ffe8c6',30,false],['Multicolor','#64e6ca',60,true],
];
export const lightingDefaults=()=>({color:'#64e6ca',brightness:50,effect:0,zone:0,on:true,cycle:false,keys:true});
export function validateLighting(value) {
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Configuración de iluminación inválida');
  const s={...lightingDefaults(),...value};
  if(!/^#[0-9a-f]{6}$/i.test(s.color))throw Error('Color RGB inválido');
  for(const [key,max] of [['brightness',100],['effect',11],['zone',2]])if(!Number.isInteger(s[key])||s[key]<0||s[key]>max)throw Error('Valor de iluminación inválido: '+key);
  for(const key of ['on','cycle','keys'])if(typeof s[key]!=='boolean')throw Error('Estado de iluminación inválido');
  return s;
}
export function lightingPayload(value) {
  const s=validateLighting(value);
  return {Command:'Channel/SetRGBInfo',Brightness:s.brightness,Color:s.color.toLowerCase(),OnOff:+s.on,KeyOnOff:+s.keys,ColorCycle:+s.cycle,SelectLightIndex:s.zone,LightList:[{SelectEffect:s.effect}]};
}
export function lightingFromPayload(p) {
  const fields=['Command','Brightness','Color','OnOff','KeyOnOff','ColorCycle','SelectLightIndex','LightList'];
  if(!p||p.Command!=='Channel/SetRGBInfo'||Object.keys(p).length!==fields.length||Object.keys(p).some(k=>!fields.includes(k)))throw Error('Comando de iluminación inválido');
  if(!Array.isArray(p.LightList)||p.LightList.length!==1||!p.LightList[0]||Object.keys(p.LightList[0]).join()!=='SelectEffect')throw Error('Selecciona un único efecto RGB');
  for(const key of ['OnOff','KeyOnOff','ColorCycle'])if(!Number.isInteger(p[key])||![0,1].includes(p[key]))throw Error('Interruptor RGB inválido');
  return validateLighting({color:p.Color,brightness:p.Brightness,effect:p.LightList[0].SelectEffect,zone:p.SelectLightIndex,on:!!p.OnOff,keys:!!p.KeyOnOff,cycle:!!p.ColorCycle});
}
export function toHsv(hex) {
  const [r,g,b]=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255),max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;
  let h=0;if(delta)h=(max===r?(g-b)/delta+(g<b?6:0):max===g?(b-r)/delta+2:(r-g)/delta+4)*60;
  return [h,max?delta/max:0,max];
}
export function fromHsv(h,s,v) {
  const f=n=>{const k=(n+h/60)%6;return Math.round(255*(v-v*s*Math.max(0,Math.min(k,4-k,1)))).toString(16).padStart(2,'0');};
  return '#'+f(5)+f(3)+f(1);
}
const nameOf=color=>palette.find(([,code])=>code===color)?.[0]||'Personalizado';
export function contrastText(color) {
  const linear=color.slice(1).match(/../g).map(c=>{
    const value=parseInt(c,16)/255;
    return value<=.04045?value/12.92:((value+.055)/1.055)**2.4;
  });
  const luminance=linear[0]*.2126+linear[1]*.7152+linear[2]*.0722;
  return luminance>.179?'#000000':'#ffffff';
}
let recent=[];
const node=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e;};
function normalizeColor(value) {
  // Canvas also resolves named colors from older desktop compositions.
  const context=document.createElement('canvas').getContext('2d');
  context.fillStyle='#64e6ca';
  if(typeof value==='string')context.fillStyle=value;
  const color=context.fillStyle;
  if(/^#[0-9a-f]{6}$/i.test(color))return color.toLowerCase();
  return '#64e6ca';
}
export function colorControl(value,label,onChange) {
  let current=normalizeColor(value);
  const root=node('div','color-control'),title=node('span','color-label',label),choose=node('button','color-choice'),sample=node('span','color-chip'),name=node('span');
  root.setAttribute('role','group');root.setAttribute('aria-label',label);choose.type='button';choose.append(sample,name);root.append(title,choose);
  const quick=node('div','color-swatches');root.append(quick);
  const paint=()=>{sample.style.background=current;name.textContent=nameOf(current);choose.setAttribute('aria-label','Elegir '+label.toLowerCase()+': '+nameOf(current));for(const b of quick.children)b.setAttribute('aria-pressed',String(b.dataset.color===current));};
  const commit=c=>{current=c;paint();onChange(c);root.dispatchEvent(new Event('input',{bubbles:true}));};
  for(const [name,color] of palette){const b=node('button','color-dot');b.type='button';b.style.setProperty('--swatch',color);b.dataset.color=color;b.title=name;b.setAttribute('aria-label',label+': '+name);b.onclick=()=>commit(color);quick.append(b);}
  choose.onclick=()=>openPicker(current,label,choose,commit);paint();root.setColor=commit;return root;
}
function openPicker(initial,label,trigger,commit) {
  let [h,s,v]=toHsv(initial),chosen=initial;
  const veil=node('div','color-overlay'),dialog=node('section','color-dialog');dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-label','Elegir '+label.toLowerCase());
  const heading=node('h2',null,'Elige un color'),hint=node('p','hint','Arrastra para elegir el tono y su intensidad.'),plane=node('div','color-plane'),cursor=node('span','color-cursor');
  plane.tabIndex=0;plane.setAttribute('role','slider');plane.setAttribute('aria-label','Saturación y luminosidad');plane.setAttribute('aria-valuemin','0');plane.setAttribute('aria-valuemax','100');plane.append(cursor);
  const hueLabel=node('label','field'),hue=node('input','hue-slider');hue.type='range';hue.min=0;hue.max=359;hue.step=1;hue.value=Math.round(h);hueLabel.append(node('span',null,'Tono'),hue);
  const result=node('div','chosen-color'),swatches=node('div','color-swatches'),history=node('div','color-swatches'),actions=node('div','row');
  const cancel=node('button',null,'Cancelar'),ok=node('button','primary','Usar color');cancel.type=ok.type='button';actions.append(cancel,ok);
  dialog.append(heading,hint,plane,hueLabel,result,node('p','hint','Paleta'),swatches);
  if(recent.length)dialog.append(node('p','hint','Colores recientes'),history);
  dialog.append(actions);veil.append(dialog);document.body.append(veil);
  const paint=()=>{chosen=fromHsv(h,s,v);plane.style.setProperty('--hue',`hsl(${h} 100% 50%)`);cursor.style.left=s*100+'%';cursor.style.top=(1-v)*100+'%';result.style.background=chosen;result.style.color=contrastText(chosen);result.textContent=nameOf(chosen);plane.setAttribute('aria-valuenow',Math.round(s*100));plane.setAttribute('aria-valuetext',`Saturación ${Math.round(s*100)}%, luminosidad ${Math.round(v*100)}%`);};
  const select=color=>{[h,s,v]=toHsv(color);hue.value=Math.round(h);paint();};
  for(const [name,color] of palette){const b=node('button','color-dot');b.type='button';b.style.setProperty('--swatch',color);b.setAttribute('aria-label',name);b.onclick=()=>select(color);swatches.append(b);}
  for(const color of recent){const b=node('button','color-dot');b.type='button';b.style.setProperty('--swatch',color);b.setAttribute('aria-label','Color reciente '+nameOf(color));b.onclick=()=>select(color);history.append(b);}
  hue.oninput=()=>{h=+hue.value;paint();};
  const pick=e=>{const r=plane.getBoundingClientRect();s=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));v=Math.max(0,Math.min(1,1-(e.clientY-r.top)/r.height));paint();};
  plane.onpointerdown=e=>{plane.focus();plane.setPointerCapture(e.pointerId);pick(e);};plane.onpointermove=e=>{if(plane.hasPointerCapture(e.pointerId))pick(e);};
  plane.onkeydown=e=>{const d={ArrowLeft:[-.02,0],ArrowRight:[.02,0],ArrowUp:[0,.02],ArrowDown:[0,-.02]}[e.key];if(d){e.preventDefault();s=Math.max(0,Math.min(1,s+d[0]));v=Math.max(0,Math.min(1,v+d[1]));paint();}};
  const close=()=>{veil.remove();if(trigger.isConnected)trigger.focus();};cancel.onclick=close;ok.onclick=()=>{recent=[chosen,...recent.filter(c=>c!==chosen)].slice(0,8);commit(chosen);close();};veil.onclick=e=>{if(e.target===veil)close();};
  dialog.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab'){const focusables=[...dialog.querySelectorAll('button,input,[tabindex="0"]')];const i=focusables.indexOf(document.activeElement);if((e.shiftKey&&i===0)||(!e.shiftKey&&i===focusables.length-1)){e.preventDefault();focusables[e.shiftKey?focusables.length-1:0].focus();}}};
  paint();plane.focus();
}
