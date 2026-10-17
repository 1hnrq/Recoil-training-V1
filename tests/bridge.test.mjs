import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdtempSync,rmSync,readFileSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {BackendClient,internalTransport,inputDiagnosticsHTML,synchronizationDiagnosticsHTML} from '../frontend/bridge-client.js';
import {previewTransport} from '../frontend/preview-transport.js';

const root=resolve(import.meta.dirname,'..');
test('sincronização distingue ocorrência congelada, estado atual e erro de saída',()=>{
  const html=synchronizationDiagnosticsHTML({heartbeat:{age_ns:1000000,timeout_ns:250000000},
    listener_progress:{progress:{phase:'pump',heartbeat_sequence:42}},
    sink:{queued:0,last_api_call:{duration_ns:300000000,return_value:0,winerror:5,error:'<erro>'}},
    last_transition:{code:'heartbeat_timeout',detail:'<timeout>',observed_ns:123,
      heartbeat:{age_ns:251000000,timeout_ns:250000000,last_delivery:{healthy:false,delay_ns:2000000}},
      listener:{progress:{phase:'publish'},operational:true},output:{in_flight:{id:1}},
      lock_wait:{input:{last_ns:2000000,max_ns:3000000}}}});
  for(const text of ['idade 1.000 ms','limite 250.000 ms','publicação #42','fila de movimentos: 0',
    'retorno 0 · erro Windows 5','&lt;erro&gt;','registro congelado','heartbeat vencido · &lt;timeout&gt;',
    'heartbeat 251.000 ms / limite 250.000 ms','Listener na ocorrência: publish',
    'Saída na ocorrência: em andamento','input: 2.000 ms / máx. 3.000 ms',
    'saúde recebido na ocorrência: false · atraso 2.000 ms'])assert.ok(html.includes(text),text);
  assert.ok(!html.includes('<timeout>'));
});
test('sincronização sem amostras não inventa dados de Windows ou listener',()=>{
  const html=synchronizationDiagnosticsHTML({});
  for(const text of ['idade —','Fase atual do listener: desconhecida','nenhuma chamada registrada',
    'registro congelado): nenhuma'])assert.ok(html.includes(text),text);
  assert.ok(!html.includes('undefined'));assert.ok(!html.includes('NaN'));
});
test('diagnóstico ultrapassa fila e não substitui estado nem aceita amostra antiga',async()=>{
  let release;
  let observed=20;
  const c=new BackendClient(action=>action==='diagnostics'?Promise.resolve({ok:true,diagnostics:{observed_ns:observed,holding:true}}):new Promise(r=>release=r));
  const pending=c.send('export_file');await Promise.resolve();
  await c.send('diagnostics');assert.equal(c.diagnostics.holding,true);assert.equal(c.state,null);
  observed=10;await c.send('diagnostics');assert.equal(c.diagnostics.observed_ns,20);
  release({ok:true,state:{revision:1,diagnostics:{observed_ns:5,holding:false}}});await pending;
  assert.equal(c.diagnostics.holding,true);
});
test('painel identifica reconciliado sem alegar leitura física, holding e motivo',()=>{
  const html=inputDiagnosticsHTML({physical_input:{left:true,right:false},input:{left_pressed:false,right_pressed:false},
    holding:false,worker_active:false,worker_running:true,weapon_enabled:false,eligible:false,
    blockers:['weapon_pause','left_released'],listener_events:{down:{left:3,right:1},up:{left:2,right:1}},
    last_stop:{reason:'<falha>',observed_ns:100},observed_ns:200,mode:'simulation'});
  for(const text of ['Reconciliado L/R: pressionado / solto','Windows L/R (última consulta): desconhecido / desconhecido','Holding (L + R): NÃO','arma pausada',
    'DOWN 3 / 1','UP 2 / 1','Worker: inativo','&lt;falha&gt;','somente entrada sintética'])assert.ok(html.includes(text),text);
});
test('painel distingue hook, Windows, motor, sequências, idades e validação',()=>{
  const html=inputDiagnosticsHTML({observed_ns:100000000,mode:'real',reconciled_input:{left:false,right:true},
    input:{left_pressed:false,right_pressed:true},holding:false,blockers:['input_revalidation'],
    input_received:{sequence:4,observed_ns:90000000,buttons:{left:false,right:true}},
    listener_events:{hook_buttons:{left:true,right:true},hook_sequences:{left:1,right:2},published_ns:95000000,
      last_event:{button:'right',down:true,sequence:2,observed_ns:80000000},
      async_sample:{left:true,right:true,sequence:7,started_ns:91000000,observed_ns:92000000,valid:{left:true,right:true},hook_sequences:{left:1,right:2}},
      pending:{left:{reason:'async_negative',press:1,since_ns:90000000,positive:1,negative:0}},
      last_release:{button:'left',reason:'<negative>',confirmed:false,observed_ns:90000000,event_sequence:2,sample_sequence:6}}});
  for(const text of ['Hook L/R (últimos eventos): pressionado / pressionado','Windows L/R (última consulta): pressionado / pressionado',
    'Reconciliado L/R: solto / pressionado','Motor L/R: solto / pressionado','validando divergência L/R',
    '#7 · início 9.0 ms atrás · fim 8.0 ms atrás · duração 1.000 ms','right DOWN · #2 · 20.0 ms atrás',
    'DOWN #1','votos +1/−0','#4 · 10.0 ms atrás','&lt;negative&gt; · preventiva'])assert.ok(html.includes(text),text);
  assert.ok(!html.includes('L físico:'));
});
const python=process.env.R6_TEST_PYTHON || (existsSync(join(root,'.venv/Scripts/python.exe'))?join(root,'.venv/Scripts/python.exe'):'python');

function host(dir){
  const proc=spawn(python,['-B','-u',join(root,'tests/fixtures/bridge_host.py'),dir],{cwd:root,stdio:['pipe','pipe','pipe']});
  const pending=[];let stderr='';proc.stderr.on('data',d=>stderr+=d);
  const lines=createInterface({input:proc.stdout});
  lines.on('line',line=>{const p=pending.shift();if(p){clearTimeout(p.timer);p.resolve(JSON.parse(line));}});
  proc.on('exit',code=>{for(const p of pending.splice(0)){clearTimeout(p.timer);p.reject(new Error(`Python ${code}: ${stderr}`));}});
  const invoke=(action,payload)=>new Promise((resolve,reject)=>{
    const p={resolve,reject,timer:setTimeout(()=>reject(new Error('Ponte de teste excedeu 10 s')),10000)};
    pending.push(p);proc.stdin.write(JSON.stringify({action,payload})+'\n');
  });
  return {client:new BackendClient(invoke),close:()=>new Promise((resolve,reject)=>{
    proc.once('exit',code=>code===0?resolve():reject(new Error(stderr)));proc.stdin.end();
  })};
}

test('cliente não altera estado antes da confirmação e serializa comandos',async()=>{
  const calls=[];let resolveFirst;
  const c=new BackendClient((action)=>{calls.push(action);return calls.length===1?new Promise(r=>resolveFirst=r):Promise.resolve({ok:true,state:{revision:2,selected:'ash'}});});
  const one=c.send('first');const two=c.send('second');await Promise.resolve();
  assert.equal(c.state,null);assert.deepEqual(calls,['first']);
  resolveFirst({ok:true,state:{revision:1,selected:'jager'}});await Promise.all([one,two]);
  assert.deepEqual(calls,['first','second']);assert.equal(c.state.selected,'ash');
});
test('erro e resposta antiga não substituem estado confirmado mais recente',async()=>{
  const replies=[{ok:true,state:{revision:3,x:'1'}},{ok:false,error:'inválido',state:{revision:3,x:'1'}},{ok:true,state:{revision:2,x:'999'}}];
  const c=new BackendClient(async()=>replies.shift());await c.send('a');await assert.rejects(c.send('b'),/inválido/);await c.send('c');assert.equal(c.state.x,'1');
});
test('adaptador interno encaminha somente à API pywebview real',async()=>{
  const calls=[];const invoke=await internalTransport({pywebview:{api:{invoke:(...args)=>{calls.push(args);return {ok:true};}}}});
  await invoke('select_weapon',{weapon:'secondary'});assert.deepEqual(calls,[['select_weapon',{weapon:'secondary'}]]);
});
test('emergência ultrapassa comando bloqueado e resposta antiga não restaura Real',async()=>{
  let release;
  const c=new BackendClient(action=>action==='emergency'?Promise.resolve({ok:true,state:{revision:9,mode:'simulation',paused:true}}):new Promise(r=>release=r));
  const pending=c.send('export_file');await Promise.resolve();
  await c.send('emergency');assert.equal(c.state.mode,'simulation');
  release({ok:true,state:{revision:8,mode:'real',paused:false}});await pending;
  assert.equal(c.state.mode,'simulation');assert.equal(c.state.paused,true);
});
test('prévia estática continua identificada como não persistente',async()=>{
  const catalog=JSON.parse(readFileSync(join(root,'data/profiles.json'),'utf8'));
  const invoke=previewTransport(catalog);assert.equal((await invoke('snapshot')).state.saved,false);
  assert.equal((await invoke('export_file')).ok,false);
});
test('JS ↔ Python: seleção, valores, pausas, multiplicadores e erro confirmado',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'r6-bridge-test-'));let h=host(dir);
  try{
    const c=h.client;await c.send('snapshot');assert.equal(c.state.operators.length,75);assert.equal(c.state.paused,true);
    await c.send('toggle_weapon',{operator:'jager',weapon:'secondary'});
    await c.send('update_parameter',{operator:'jager',weapon:'primary',field:'x',value:'-0.400000'});
    await c.send('set_multiplier',{axis:'x',value:'1.25'});assert.equal(c.state.diagnostics.effective.x,'-1/2');
    await Promise.all([c.send('step_parameter',{operator:'jager',weapon:'primary',field:'x',direction:1}),
                       c.send('step_parameter',{operator:'jager',weapon:'primary',field:'x',direction:1})]);
    assert.equal(c.state.operators.find(p=>p.id==='jager').primary.x,'-0.2');
    await c.send('update_parameter',{operator:'jager',weapon:'primary',field:'x',value:'-0.400000'});
    await c.send('select_operator',{id:'ash'});await c.send('select_weapon',{weapon:'secondary'});
    assert.equal(c.state.paused,true);await c.send('select_operator',{id:'jager'});
    assert.equal(c.state.operators.find(p=>p.id==='jager').secondary.enabled,false);
    await assert.rejects(c.send('set_multiplier',{axis:'x',value:'NaN'}));assert.equal(c.state.multipliers.x,'1.25');
    const doc=JSON.parse(readFileSync(join(dir,'settings.json'),'utf8'));assert.equal(doc.operators[33].primary.parameters.x,'-0.400000');
    await c.send('toggle_pause');await c.send('select_weapon',{weapon:'secondary'});
    await h.close();h=host(dir);await h.client.send('snapshot');
    assert.equal(h.client.state.paused,true);assert.equal(h.client.state.weapon,'secondary');assert.equal(h.client.state.multipliers.x,'1.25');
    assert.equal(h.client.state.diagnostics.input.left_pressed,false);
  }finally{await h.close();rmSync(dir,{recursive:true});}
});
test('JS ↔ motor: saída inteira, resíduos e temporização observada no diagnóstico',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'r6-motor-test-'));const h=host(dir);
  try{
    const c=h.client;await c.send('snapshot');
    for(const [field,value] of [['x','-0.4'],['y','0.4'],['interval_seconds','0.005']])await c.send('update_parameter',{operator:'jager',weapon:'primary',field,value});
    await c.send('toggle_pause');await c.send('simulate_start');
    await new Promise(r=>setTimeout(r,120));await c.send('snapshot');
    assert.ok(c.state.diagnostics.cycles>=5);assert.ok(c.state.diagnostics.total_y>=2);
    assert.equal(c.state.diagnostics.requested_seconds,'0.005');assert.ok(c.state.diagnostics.last.timing.observed_interval_ns>=5000000);
    for(const row of c.state.diagnostics.recent){assert.ok(Number.isInteger(row.movement.dx));assert.ok(Number.isInteger(row.movement.dy));}
    await c.send('toggle_pause');assert.equal(c.state.paused,true);assert.deepEqual(c.state.diagnostics.residuals,{x:'0',y:'0'});
  }finally{await h.close();rmSync(dir,{recursive:true});}
});

test('handlers reais da UI: diagnóstico atualiza com comando pendente; foco/blur/fechar não pausam',async t=>{
  const catalog=JSON.parse(readFileSync(join(root,'data/profiles.json'),'utf8'));
  const snapshot=(await previewTransport(catalog)('snapshot')).state;
  Object.assign(snapshot,{revision:1,mode:'real',paused:false,notices:[],safety_epoch:'mock:0'});
  snapshot.diagnostics={observed_ns:10,mode:'real',paused:false,physical_input:{left:true,right:true},
    input:{left_pressed:true,right_pressed:true},holding:true,eligible:true,blockers:[],
    worker_active:true,worker_running:true,weapon_enabled:true,sink:{test_only:true,calls:0},
    effective:{x:'0',y:'1'},residuals:{x:'0',y:'0'},recent:[],cycles:0,total_x:0,total_y:0,generation:0};
  class Element {
    constructor(){this.events={};this.style={};this.innerHTML='';this.open=false;}
    addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
    async fire(name,event={}){for(const fn of this.events[name]||[])await fn(event);}
    querySelector(){return null;}
    closest(){return null;}
    showModal(){this.open=true;}
    close(){this.open=false;void this.fire('close');}
    focus(){}
  }
  const elements=new Map();const doc=new Element();
  doc.querySelector=name=>{if(!elements.has(name))elements.set(name,new Element());return elements.get(name);};
  const calls=[];const timers=[];const win=new Element();let releaseEdit;
  win.pywebview={api:{invoke:async(action,payload)=>{
    calls.push([action,payload]);
    if(action==='set_editing')return new Promise(resolve=>{releaseEdit=()=>resolve({ok:true,state:structuredClone(snapshot)});});
    if(action==='diagnostics')return {ok:true,diagnostics:{...snapshot.diagnostics,observed_ns:20}};
    return {ok:true,state:structuredClone(snapshot)};
  }}};
  for(const [name,value] of Object.entries({document:doc,window:win,location:{search:'?integrated=1'}})){
    const old=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{configurable:true,value});
    t.after(()=>{if(old)Object.defineProperty(globalThis,name,old);else delete globalThis[name];});
  }
  t.mock.method(globalThis,'setTimeout',(fn,delay)=>{timers.push({fn,delay});return 1;});
  await import('../frontend/app.js?phase5-ui-regression');
  assert.ok(!doc.querySelector('#content').innerHTML.includes('Não foi possível carregar'));
  await doc.querySelector('#diagnostics').fire('click');
  assert.equal(doc.querySelector('#dialog').open,true);
  await doc.fire('focusin');await new Promise(resolve=>setImmediate(resolve));
  assert.ok(releaseEdit); // a real UI mutation remains unresolved in the client queue
  await timers.find(timer=>timer.delay===200).fn();
  assert.ok(doc.querySelector('#diagnostic-data').innerHTML.includes('Holding (L + R): SIM'));
  assert.ok(calls.some(([action])=>action==='diagnostics'));
  await win.fire('blur'); // minimize/focus loss has this same frontend route
  doc.querySelector('#dialog').close();
  releaseEdit();await new Promise(resolve=>setImmediate(resolve));
  assert.ok(calls.some(([action])=>action==='simulate_stop'));
  assert.ok(!calls.some(([action])=>['set_pause','toggle_pause','emergency'].includes(action)));
  await doc.fire('keyup',{key:'p'}); // global listener owns integrated keyboard, no double toggle
  assert.ok(!calls.some(([action])=>action==='toggle_pause'));
});
