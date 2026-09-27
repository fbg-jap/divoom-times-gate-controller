import test from 'node:test';
import assert from 'node:assert/strict';
import {lightingDefaults,lightingPayload,lightingFromPayload,palette,toHsv,fromHsv} from '../src/colors.js';
import {MobileEngine,validateCommand} from '../src/mobile.js';
import {defaults} from '../src/model.js';

test('visual RGB selections retain the original protocol and effect indexing',()=>{
  const p=lightingPayload({color:'#ABCDEF',brightness:73,effect:11,zone:2,on:true,keys:false,cycle:true});
  assert.deepEqual(p,{Command:'Channel/SetRGBInfo',Color:'#abcdef',Brightness:73,LightList:[{SelectEffect:11}],SelectLightIndex:2,OnOff:1,KeyOnOff:0,ColorCycle:1});
  validateCommand(p);
  for(const LightList of [[],[null],[8],[{SelectEffect:12}],[{SelectEffect:0},{SelectEffect:1}]])assert.throws(()=>validateCommand({...p,LightList}));
  for(const Brightness of [-1,101,true,'50'])assert.throws(()=>validateCommand({...p,Brightness}));
});
test('opening the HSV picker does not change existing palette or boundary colors',()=>{
  for(const color of [...palette.map(([,c])=>c),'#ff0000','#00ff00','#0000ff','#808080','#abcdef'])assert.equal(fromHsv(...toHsv(color)),color);
});
test('mobile lighting is retained only after acknowledgement and leaves media running',async()=>{
  const engine=new MobileEngine(true);engine.config=defaults();
  const d=engine.config.devices[0],before=structuredClone(d),p=lightingPayload({...lightingDefaults(),effect:5,zone:2});
  let writes=0;
  engine.persist=async()=>{writes++;};
  engine.command=async()=>{throw Error('device rejected');};
  await assert.rejects(engine.operate('command',d.id,{payload:p}),/device rejected/);
  assert.deepEqual(d,before);assert.equal(writes,0);
  engine.command=async()=>({error_code:0});
  await engine.operate('command',d.id,{payload:p});
  assert.deepEqual(d.lighting,lightingFromPayload(p));assert.equal(writes,1);
  assert.deepEqual(d.screens,before.screens);assert.deepEqual(d.playlists,before.playlists);assert.equal(d.suspended,before.suspended);
});
