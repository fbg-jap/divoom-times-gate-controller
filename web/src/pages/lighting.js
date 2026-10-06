import {$,el,button,row,card,hint,toast,d,action,preview,render} from "../ui.js";
import {t} from "../i18n.js";
import {colorControl,lightingDefaults,lightingPayload,moods} from "../colors.js";
import {screen,device} from "../model.js";
const lightingDrafts=new Map();
export function lightingPage(main) {
  const deviceId=d().id;
  if(!lightingDrafts.has(deviceId))lightingDrafts.set(deviceId,{...lightingDefaults(),...d().lighting});
  const settings=lightingDrafts.get(deviceId);
  const preview=el('div',{class:'light-device','aria-label':t("ui.color_and_zone_preview_of"),role:'img'});
  const glow=el('div',{class:'light-back'}),panels=el('div',{class:'light-panels'},...[1,2,3,4,5].map(n=>el('div',{class:'light-screen'},el('span',{},String(n))))),keys=el('div',{class:'light-keys'});
  preview.append(glow,panels,keys);
  const status=el('p',{class:'hint'},t("ui.approximate_view_of_color_brightness"));
  const draw=()=>{
    preview.style.setProperty('--light',settings.color);preview.style.setProperty('--brightness',settings.on?settings.brightness/100:0);
    preview.classList.toggle('cycling',settings.cycle);preview.classList.toggle('edges',settings.zone!==2);preview.classList.toggle('backlight',settings.zone!==1);preview.classList.toggle('keys-on',settings.keys);
  };
  const color=colorControl(settings.color,t("ui.lighting_color"),value=>{settings.color=value;draw();});
  const brightness=el('input',{type:'range',min:0,max:100,step:1,value:settings.brightness,'aria-label':t("ui.rgb_brightness")}),percentage=el('output',{},settings.brightness+'%');
  brightness.oninput=()=>{settings.brightness=+brightness.value;percentage.textContent=settings.brightness+'%';draw();};
  const zones=el('div',{class:'segmented','aria-label':t("ui.lit_zone"),role:'group'});
  [t("ui.all_zones"),t("ui.edges"),t("ui.backlight")].forEach((name,index)=>{
    const b=button(name,()=>{settings.zone=index;for(const [i,item] of [...zones.children].entries())item.setAttribute('aria-pressed',String(i===index));draw();});b.setAttribute('aria-pressed',String(index===settings.zone));zones.append(b);
  });
  const switches=el('div',{class:'lighting-switches'});
  for(const [key,name] of [['on',t("ui.lighting_on")],['cycle',t("ui.multicolor_cycle")],['keys',t("ui.key_light")]]){
    const input=el('input',{type:'checkbox',checked:settings[key]});input.onchange=()=>{settings[key]=input.checked;draw();};switches.append(el('label',{class:'light-toggle'},input,el('span',{},name)));
  }
  const presets=el('div',{class:'mood-grid'});
  moods.forEach(([name,value,level,cycle])=>{
    const b=button(t(name),()=>{Object.assign(settings,{color:value,brightness:level,cycle,on:true});render();});b.prepend(el('span',{class:'mood-dot',style:`--swatch:${value}`}));presets.append(b);
  });
  const effects=el('div',{class:'effect-grid',role:'group','aria-label':t("ui.rgb_effects")});
  for(let i=0;i<12;i++){
    const b=button('',()=>{settings.effect=i;for(const [n,item] of [...effects.children].entries())item.setAttribute('aria-pressed',String(n===i));});
    b.setAttribute('aria-pressed',String(settings.effect===i));b.setAttribute('aria-label',t("ui.effect")+(i+1));
    b.append(el('span',{class:'effect-symbol','aria-hidden':'true'},'▱ ▱ ▱ ▱ ▱'),el('span',{},t("ui.effect")+(i+1)));effects.append(b);
  }
  main.append(card(t("ui.your_mood_at_a_glance"),preview,status,el('div',{class:'lighting-layout'},el('div',{},color),el('div',{},el('p',{class:'color-label'},t("ui.lit_zone")),zones,el('div',{class:'brightness-row'},el('span',{},t("ui.brightness")),brightness,percentage),switches))),
    card(t("ui.quick_moods"),hint(t("ui.choose_a_combination_of_color")),presets),
    card(t("ui.device_effects"),hint(t("ui.select_a_card_modes_keep")),effects,
      el('div',{class:'lighting-apply'},button(t("ui.apply_lighting"),async()=>{await action('command',deviceId,{payload:lightingPayload(settings)});toast(t("ui.lighting_sent_to_the_times"));},'primary'),hint(t("ui.the_preview_does_not_send")))));
  draw();
}
