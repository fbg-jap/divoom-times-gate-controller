import test from 'node:test';
import assert from 'node:assert/strict';
import {en,es,t,setLanguage,getLanguage,lazy} from '../src/i18n.js';
import {kinds} from '../src/model.js';
import {lightingPayload} from '../src/colors.js';

test.afterEach(()=>setLanguage('en'));

test('every English key exists in Spanish and vice versa',()=>{
  assert.deepEqual(Object.keys(es).sort(),Object.keys(en).sort());
  for(const [key,value] of Object.entries(es))assert.ok(value.trim(),key);
});
test('placeholders match between languages',()=>{
  const holes=text=>(text.match(/\{\d+\}/g)||[]).sort().join();
  for(const key of Object.keys(en))assert.equal(holes(es[key]),holes(en[key]),key);
});
test('switching language changes output and falls back to English',()=>{
  assert.equal(getLanguage(),'en');
  assert.equal(t('ui.save'),'Save');
  setLanguage('es');
  assert.equal(t('ui.save'),'Guardar');
  assert.equal(t('color.saturation_0_brightness_1',[40,60]),'Saturación 40%, luminosidad 60%');
  setLanguage('xx');
  assert.equal(getLanguage(),'en');
  assert.equal(t('no.such.key'),'no.such.key');
});
test('module-level tables are looked up lazily',()=>{
  assert.equal(kinds.clock,'Clock');
  setLanguage('es');
  assert.equal(kinds.clock,'Reloj');
  assert.equal(lazy({a:'ui.save'}).a,'Guardar');
});
test('validation messages follow the selected language',()=>{
  assert.throws(()=>lightingPayload({color:'bad'}),/Invalid RGB color/);
  setLanguage('es');
  assert.throws(()=>lightingPayload({color:'bad'}),/Color RGB inválido/);
});
