import {current, configured, legacyDisplay, previewStatus, units, decimal, validated} from './model.js';
import {BackendClient, internalTransport, inputDiagnosticsHTML} from './bridge-client.js';
import {previewTransport} from './preview-transport.js';

const content = document.querySelector('#content');
const dialog = document.querySelector('#dialog');
const labels = {primary: 'Primary Weapon', secondary: 'Secondary Weapon'};
let state;
let client;
let busy=false;
let pendingRequests=0;
let dialogKind='';
let diagnosticTimer;
let renderedRevision=-1;
const integrated=new URLSearchParams(location.search).get('integrated')==='1';
let filter = '';
let reticle = {mark: '+', opacity: '80', size: '70'};
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// The button/card provides the accessible name; SVG assets are local and licensed.
const operatorIcon = op => `<img class="operator-logo" src="/assets/operators/${escape(op.id)}.svg" alt="" aria-hidden="true" width="350" height="350" draggable="false">`;

function announce(text) { document.querySelector('#announcement').textContent = text; }
function showDialog(title, html) {
  dialogKind='message';
  document.querySelector('#dialog-title').textContent = title;
  document.querySelector('#dialog-body').innerHTML = html;
  if(!dialog.open)dialog.showModal();
}
function field(slot, name, label, value) {
  return `<div class="field-row"><label for="${slot}-${name}">${label}</label><div class="number-control"><button data-step="-1" data-slot="${slot}" data-field="${name}" aria-label="Diminuir ${label} da ${slot === 'primary' ? 'primária' : 'secundária'}">−</button><input id="${slot}-${name}" data-slot="${slot}" data-field="${name}" inputmode="decimal" autocomplete="off" spellcheck="false" value="${escape(value)}" aria-label="${label} da ${slot === 'primary' ? 'primária' : 'secundária'}"><button data-step="1" data-slot="${slot}" data-field="${name}" aria-label="Aumentar ${label} da ${slot === 'primary' ? 'primária' : 'secundária'}">+</button></div></div>`;
}
function weaponPanel(slot) {
  const weapon = current(state)[slot];
  const selected = state.weapon === slot;
  const warning = units(weapon.interval_seconds) === 0n ? '△ Intervalo zero · não configurada' : '△ Abaixo de 0.001 s · valor preservado';
  return `<section class="weapon-panel ${selected ? 'is-selected' : ''}" aria-label="${labels[slot]}"><div class="weapon-heading"><h2>${labels[slot]}</h2><button class="slot-button" data-weapon="${slot}" aria-pressed="${selected}" aria-label="Selecionar ${slot === 'primary' ? 'primária' : 'secundária'}">${slot === 'primary' ? '1' : '2'}</button></div><button class="weapon-toggle" data-toggle="${slot}" aria-pressed="${weapon.enabled}" aria-label="${slot === 'primary' ? 'Primária' : 'secundária'}: ${weapon.enabled ? 'ativada' : 'pausada'}"><span>${weapon.enabled ? '●' : 'Ⅱ'}</span>${weapon.enabled ? 'ATIVADO' : 'PAUSADO'}</button>${field(slot, 'x', 'Horizontal (X)', weapon.x)}${field(slot, 'y', 'Vertical (Y)', weapon.y)}${field(slot, 'interval_seconds', 'Speed · s', weapon.interval_seconds)}<div class="field-note ${configured(weapon) ? '' : 'unconfigured'}">${configured(weapon) ? 'Valores efetivos · sem conversão oculta' : warning}</div></section>`;
}
function renderWeapons() {
  const op = current(state);
  content.innerHTML = `<div class="weapons-layout"><section class="operator-card" aria-label="Operador selecionado"><div class="operator-badge" aria-hidden="true">${operatorIcon(op)}</div><div><h1>${escape(op.label)}</h1><small>OPERADOR ${String(op.legacy_index).padStart(2,'0')} / 75</small></div><button class="text-button" data-view="operators">Trocar operador ↗</button></section><div class="weapon-pair">${weaponPanel('primary')}${weaponPanel('secondary')}</div><aside class="sensitivity"><h2>Sensitivity Multiplier</h2><div class="field-row"><label for="mult-x">X</label><input id="mult-x" data-mult="x" value="${escape(state.multipliers.x)}" aria-label="Multiplicador X" inputmode="decimal"></div><div class="field-row"><label for="mult-y">Y</label><input id="mult-y" data-mult="y" value="${escape(state.multipliers.y)}" aria-label="Multiplicador Y" inputmode="decimal"></div><p>Mesmos controles, à direita.<br>Rotas antigas preservadas<br>na auditoria de conversões.</p><button id="conversions" class="text-button">Conferir conversões ↗</button></aside></div><div class="lower-layout"><section class="information"><div class="information-title"><span>${escape(op.label.toUpperCase())}</span><span>${state.weapon === 'primary' ? 'PRIMARY / 1' : 'SECONDARY / 2'}</span></div><div class="information-body"><strong>${integrated ? previewStatus(state).replace('Habilitada na prévia','Habilitada · saída simulada') : previewStatus(state)}</strong> · ${state.paused ? 'P retoma apenas a pausa geral.' : 'As pausas individuais continuam preservadas.'}<br>Botões individuais não alteram os demais operadores.</div><p class="information-note">Y e Speed mostram os valores enviados ao backend, não as escalas antigas de exibição.</p></section><section class="action-panel"><button id="global-pause" class="pause-all" aria-pressed="${state.paused}"><span>${state.paused ? 'Ⅱ PAUSA GERAL' : '▷ PAUSA GERAL LIBERADA'}</span><span>[P]</span></button><div class="nav-buttons"><button data-view="reticles">⌖ Miras</button><button data-view="files">▤ Arquivos</button></div><p class="session-note">${integrated ? 'Backend confirmado · salvamento automático.' : 'Prévia: alterações em memória, sem gravação.'}</p></section></div>`;
}
function renderOperators() {
  const matches = state.operators.filter(op => op.label.toLowerCase().includes(filter.toLowerCase()) || op.id.includes(filter.toLowerCase()));
  content.innerHTML = `<div class="gallery-layout"><section class="gallery-panel"><div class="gallery-toolbar"><h1>Operator Select ›</h1><input id="operator-search" type="search" placeholder="Buscar operador" aria-label="Buscar operador" value="${escape(filter)}"></div><div class="operator-grid">${matches.map(op => `<button data-operator="${escape(op.id)}" aria-label="Selecionar ${escape(op.label)}" aria-current="${state.selected === op.id}" title="${escape(op.label)}" class="operator-tile ${!configured(op.primary) && !configured(op.secondary) ? 'no-settings' : ''} ${filter ? 'filtered' : ''}">${operatorIcon(op)}<small>${op.legacy_index}</small></button>`).join('')}</div>${matches.length ? '' : '<p>Nenhum operador encontrado.</p>'}</section><aside class="gallery-info"><div class="eyebrow">CATÁLOGO LOCAL / 75 OPERADORES</div><h2>Escolha o operador.<br>Preserve seu perfil.</h2><p>A ordem dos operadores e os seis parâmetros de cada perfil foram conservados a partir das evidências.</p><p class="legend">Ícones locais de r6operators · licença MIT. Marco Vockner, Jose Roberto e colaboradores.</p><p class="legend">Cada operador mantém suas duas pausas individuais durante a navegação.</p><button class="text-button" data-view="weapons">Voltar para ${escape(current(state).label)} →</button></aside></div>`;
}
function renderReticles() {
  content.innerHTML = `<section class="small-page"><h1>Custom Crosshairs</h1><div class="reticle-layout"><div><div class="reticle-view" aria-label="Prévia da mira"><span class="reticle-mark" style="opacity:${Number(reticle.opacity)/100};font-size:${Number(reticle.size)}px">${reticle.mark}</span></div><div class="reticle-choices">${['+','⊕','·','⌖'].map(mark=>`<button data-mark="${mark}" aria-label="Mira ${mark}" aria-pressed="${reticle.mark===mark}">${mark}</button>`).join('')}</div></div><div class="reticle-controls"><label for="opacity">Opacity · ${reticle.opacity}%</label><input id="opacity" type="range" min="0" max="100" value="${reticle.opacity}"><label for="size">Size · ${reticle.size}%</label><input id="size" type="range" min="20" max="120" value="${reticle.size}"><p class="notice">Desenhos tipográficos próprios. Apenas a área de prévia muda; nenhuma sobreposição é criada no Windows.</p><p>O catálogo original de 200 miras permanece pendente de permissões e reconstrução.</p></div></div></section>`;
}
function renderFiles() {
  content.innerHTML = `<section class="small-page"><h1>Settings Files</h1><p>${integrated ? 'Configurações confirmadas pelo Python e salvas automaticamente em JSON versionado.' : 'Prévia sem persistência. Abra a aplicação Python para usar os arquivos.'}</p><div class="file-buttons"><button id="save-settings" ${integrated?'':'disabled'}>Salvar configurações</button><button id="import-settings" ${integrated?'':'disabled'}>Importar configurações</button><button id="export-settings" ${integrated?'':'disabled'}>Exportar JSON</button></div><p class="notice">O formato próprio preserva os 75 perfis, fatores, pausas individuais, seleção e preferências. A pausa geral sempre começa ativa. Resíduos e botões simulados não são salvos.</p><p>Importação legada: settings.txt com prefixo ^^^, 75 linhas na ordem documentada. O arquivo é validado integralmente e requer confirmação antes de substituir os parâmetros.</p><p>${(state.notices||[]).map(escape).join('<br>')}</p></section>`;
}
function render() {
  renderMode();
  document.querySelector('#back').hidden = state.view === 'operators';
  document.querySelector('#back').textContent = state.view === 'weapons' ? '← OPERADORES' : '← CONFIGURAÇÕES';
  document.querySelector('#screen-title').textContent = {weapons:'OPERATOR / CONFIGURAÇÕES',operators:'SELEÇÃO MANUAL',reticles:'MIRAS / PRÉVIA',files:'ARQUIVOS / CONFIGURAÇÕES'}[state.view];
  ({weapons:renderWeapons,operators:renderOperators,reticles:renderReticles,files:renderFiles})[state.view]();
  const status=content.querySelector('.information-body strong');
  if(status && integrated && state.mode==='real')status.textContent=previewStatus(state).replace('Habilitada na prévia','Habilitada · saída Real');
  renderedRevision=state.revision;
}
function renderMode(){
  if(!integrated)return;
  const real=state.mode==='real';
  const button=document.querySelector('#output-mode');
  button.disabled=false;
  button.textContent=real?'● REAL · '+(state.paused?'PAUSADO':'HABILITADO'):'○ SIMULAÇÃO'+(state.emergency?' · F12':'');
  if(state.diagnostics?.sink?.test_only)button.textContent+=' [TESTE]';
  button.style.color=real?'#ffb36b':'';
  document.querySelector('#emergency').hidden=false;
}
function isEditing(){return Boolean(document.activeElement?.closest('input,textarea,select,[contenteditable=true]'));}
async function pollGlobal(){
  try{
    if(!busy){
      await send('snapshot',{},false);renderMode();
      if(!isEditing() && renderedRevision!==state.revision)render();
      if(dialog.open && dialogKind==='diagnostics')document.querySelector('#diagnostic-data').innerHTML=diagnosticsHTML();
    }
  }catch(error){announce('Não foi possível atualizar o estado: '+error.message);}
  setTimeout(pollGlobal,350);
}
async function pollLiveDiagnostics(){
  try{
    if(dialog.open && dialogKind==='diagnostics'){
      await client.send('diagnostics');
      if(dialog.open && dialogKind==='diagnostics')document.querySelector('#diagnostic-data').innerHTML=diagnosticsHTML();
    }
  }catch(error){announce('Diagnóstico indisponível: '+error.message);}
  setTimeout(pollLiveDiagnostics,200);
}
function conversionDialog() {
  const op=current(state);
  showDialog('Fidelidade dos perfis', `<p>Os campos principais mostram os números efetivos. Nenhum sinal ou fator de Speed é aplicado ao valor armazenado.</p><table><thead><tr><th>Campo</th><th>Primária</th><th>Secundária</th></tr></thead><tbody><tr><td>Y armazenado</td><td>${escape(op.primary.y)}</td><td>${escape(op.secondary.y)}</td></tr><tr><td>Y exibido no legado</td><td>${legacyDisplay(op.primary,'primary').y}</td><td>${legacyDisplay(op.secondary,'secondary').y}</td></tr><tr><td>Intervalo real · s</td><td>${escape(op.primary.interval_seconds)}</td><td>${escape(op.secondary.interval_seconds)}</td></tr><tr><td>Speed exibido no legado</td><td>${legacyDisplay(op.primary,'primary').interval_seconds}</td><td>${legacyDisplay(op.secondary,'secondary').interval_seconds}</td></tr></tbody></table><p><strong>Multiplicadores:</strong> a primária não os aplicava nas rotas de tecla 1 e edição; aplicava ao entrar no operador. A secundária os aplicava nas rotas de tecla 2 e edição.</p><p>O backend simulado aplica os fatores uniformemente nas duas armas (1 = 1×), conforme a correção aprovada. O auditor mantém as rotas antigas como evidência. Nenhum fator altera os valores-base.</p><p class="notice">Os parâmetros vêm do snapshot externo identificado por hash, não de uma versão histórica autenticada pelo executável.</p>`);
}
async function send(action,payload={},redraw=true) {
  pendingRequests++;busy=true;
  try {
    const reply=await client.send(action,payload);
    state=client.state;reticle=state.reticle;
    if(redraw && pendingRequests===1)render();
    return reply;
  } catch(error) {
    if(client.state){state=client.state;reticle=state.reticle;if(redraw)render();}
    throw error;
  } finally {pendingRequests--;busy=pendingRequests>0;}
}
function report(error){showDialog('Ação não aplicada',`<p>${escape(error.message)}</p><p>O estado exibido é o último confirmado pelo backend.</p>`);}
function diagnosticsHTML() {
  const d=integrated?(client.diagnostics || state.diagnostics):state.diagnostics;
  if(!d)return '<p>Abra tools/run_app.py para conectar ao motor Python.</p>';
  const last=d.last;
  return `${d.physical_input?inputDiagnosticsHTML(d):''}<p><strong>${escape(d.operator_label??current(state).label)} / ${escape(d.selected_weapon??state.weapon)}</strong><br>
    X efetivo: ${escape(d.effective.x)} · Y efetivo: ${escape(d.effective.y)} (frações exatas)<br>
    Pausa geral: ${(d.paused??state.paused)?'SIM':'NÃO'} · Primária: ${(d.primary_enabled??current(state).primary.enabled)?'ativada':'pausada'} · Secundária: ${(d.secondary_enabled??current(state).secondary.enabled)?'ativada':'pausada'}<br>
    Modo: ${(d.mode??state.mode)==='real'?'REAL':'SIMULAÇÃO'} · Entrada do motor: ${d.input.left_pressed && d.input.right_pressed?'ativa':'solta'} · Elegível: ${d.eligible?'sim':'não'}<br>
    Listener global: ${d.input_healthy?'operacional':'indisponível'} · Saída: ${d.sink?.test_only?'MOCK · SEM MOVIMENTO':d.sink?.operational?'Windows disponível':'indisponível'} · Chamadas aceitas: ${d.sink?.calls??0}<br>
    Emergência: ${(d.emergency??state.emergency)?'acionada':'não'} · Última parada interna: ${d.last_emergency_ns==null?'—':(d.last_emergency_ns/1000000).toFixed(3)+' ms'} ${d.await_release?'· solte ambos os botões antes de continuar':''}<br>
    Intervalo solicitado (perfil atual): ${escape(d.requested_seconds)} s<br>
    Último registro: ${last?escape(last.movement.operator_id)+' / '+escape(last.movement.weapon)+' · geração '+last.movement.generation:'—'}<br>
    Intervalo observado desse registro: ${last?.timing?.observed_interval_ns==null?'—':(last.timing.observed_interval_ns/1000000).toFixed(3)+' ms'}<br>
    Resíduos atuais X/Y: ${escape(d.residuals.x)} / ${escape(d.residuals.y)}<br>
    Último dx/dy: ${last ? last.movement.dx+' / '+last.movement.dy : '—'} · Ciclos: ${d.cycles}<br>
    Totais X/Y: ${d.total_x} / ${d.total_y} · Geração: ${d.generation}</p>
    ${d.error?'<p class="error">'+escape(d.error)+'</p>':''}
    ${d.safety_error?'<p class="error">'+escape(d.safety_error)+'</p>':''}
    <table><thead><tr><th>Contexto</th><th>dx / dy</th><th>rx / ry</th><th>X sorteado</th></tr></thead><tbody>${d.recent.map(r=>`<tr><td>${escape(r.movement.operator_id)} / ${escape(r.movement.weapon)} · g${r.movement.generation}</td><td>${r.movement.dx} / ${r.movement.dy}</td><td>${escape(r.movement.residual_x)} / ${escape(r.movement.residual_y)}</td><td>${r.movement.horizontal_selected?'sim':'não'}</td></tr>`).join('')}</tbody></table>`;
}
async function pollDiagnostic(){
  if(!dialog.open || dialogKind!=='diagnostics')return;
  try{
    if(!busy){await send('snapshot',{},false);render();document.querySelector('#diagnostic-data').innerHTML=diagnosticsHTML();}
  }catch(error){report(error);}
  if(dialog.open && dialogKind==='diagnostics')diagnosticTimer=setTimeout(pollDiagnostic,350);
}
function showDiagnostics(){
  showDialog('Diagnóstico · motor compartilhado',`<p class="notice">“Simular 2 s” só funciona em Simulação e não remove pausas. Real usa L+R físicos e os atalhos globais. F12 interrompe a saída e retorna à Simulação. Perder foco encerra somente a entrada sintética.</p><div class="file-buttons"><button id="diagnostic-run">Simular 2 s</button><button id="diagnostic-stop">Parar simulação</button><button id="diagnostic-pause">Pausa geral [P]</button></div><div id="diagnostic-data">${diagnosticsHTML()}</div>`);
  dialogKind='diagnostics';if(!integrated)pollDiagnostic();
}
document.querySelector('#dialog-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{clearTimeout(diagnosticTimer);dialogKind='';if(client)send('simulate_stop',{},false).catch(()=>{});});
window.addEventListener('blur',()=>{if(client)client.send('simulate_stop').catch(()=>{});});
document.querySelector('#about').addEventListener('click',()=>showDialog('Sobre esta entrega', `<p>Fase 5: motor exato compartilhado, Simulação e Real explícito.</p><ul><li>75 logos locais de r6operators sob licença MIT. <a class="comparison-link" href="/assets/operators/LICENSE.txt" target="_blank" rel="noopener">Licença</a>.</li><li>P/1/2 globais na liberação; F12 na pressão. Campos da própria interface não disparam P/1/2.</li><li>Sem identificação do jogo, manipulação de memória ou evasão de anticheat.</li><li>Real inicia pausado; cliques, foco e edição não alteram a pausa geral. Operações de arquivo usam bloqueio temporário separado.</li><li>JSON versionado preservado; Real e pausas transitórias não são restaurados.</li></ul><p>${integrated?'Ponte interna pywebview. O Python é a autoridade do estado.':'Prévia estática independente: sem ponte e sem persistência.'}</p>`));
document.querySelector('#output-mode').addEventListener('click',()=>{
  showDialog('Modo de saída',`<p>Simulação não move o mouse. Real permite movimentos globais ao pressionar L+R com as pausas liberadas, inclusive minimizado. F12 interrompe e retorna à Simulação.</p><p>A troca inicia pausada. Solte ambos os botões e use P para liberar. Não use Real antes de autorizar seu teste físico controlado.</p><div class="file-buttons"><button id="mode-simulation" data-epoch="${state.safety_epoch}">Usar Simulação</button><button id="mode-real" data-epoch="${state.safety_epoch}">Confirmar ativação do modo Real</button></div>`);
});
document.querySelector('#emergency').addEventListener('click',()=>send('emergency').catch(report));
document.addEventListener('focusin',()=>{if(integrated && client)send('set_editing',{editing:isEditing()},false).catch(report);});
document.addEventListener('focusout',()=>{if(integrated && client)queueMicrotask(()=>send('set_editing',{editing:isEditing()},false).catch(report));});
document.querySelector('#back').addEventListener('click',()=>send('set_view',{view:state.view==='weapons'?'operators':'weapons'}).catch(report));
document.querySelector('#diagnostics').addEventListener('click',showDiagnostics);
content.addEventListener('click',async event=>{
  const button=event.target.closest('button');
  if(!button || button.disabled)return;
  try{
    if(button.dataset.toggle){
      await send('toggle_weapon',{weapon:button.dataset.toggle,operator:state.selected});
      announce('Estado individual confirmado.');
    }else if(button.dataset.weapon)await send('select_weapon',{weapon:button.dataset.weapon});
    else if(button.dataset.operator){await send('select_operator',{id:button.dataset.operator});document.querySelector('#app').focus();}
    else if(button.dataset.view){await send('set_view',{view:button.dataset.view});document.querySelector('#app').focus();}
    else if(button.dataset.step){
      const {slot,field,step}=button.dataset;
      await send('step_parameter',{operator:state.selected,weapon:slot,field,direction:Number(step)});
    }else if(button.id==='global-pause')await send(integrated?'set_pause':'toggle_pause',integrated?{paused:button.getAttribute('aria-pressed')!=='true',epoch:state.safety_epoch}:{});
    else if(button.id==='conversions')conversionDialog();
    else if(button.dataset.mark)await send('set_reticle',{field:'mark',value:button.dataset.mark});
    else if(button.id==='save-settings'){await send('save');showDialog('Configuração salva','<p>JSON validado e salvo no disco. Backup da última configuração válida mantido.</p>');}
    else if(button.id==='export-settings'){
      const reply=await send('export_file');
      if(reply.exported)showDialog('Exportação concluída','<p>Arquivo JSON versionado salvo no destino escolhido.</p>');
    }else if(button.id==='import-settings'){
      const reply=await send('import_file');
      if(reply.import_preview){
        const p=reply.import_preview;
        showDialog('Confirmar importação',`<p>75 operadores / 450 parâmetros. A aplicação ficará em pausa geral após importar.</p><p>${p.warnings.map(escape).join('<br>')}</p><button id="confirm-import" data-token="${escape(p.token)}">Aplicar importação</button>`);
      }
    }
  }catch(error){report(error);}
});
content.addEventListener('change',async event=>{
  const input=event.target;
  try{
    if(input.dataset.field){
      const value=validated(input.dataset.field,input.value);
      await send('update_parameter',{operator:state.selected,weapon:input.dataset.slot,field:input.dataset.field,value});
    }else if(input.dataset.mult){
      const number=units(input.value);if(number<=0n)throw new Error('Multiplicador deve ser positivo.');
      await send('set_multiplier',{axis:input.dataset.mult,value:decimal(number)});
    }else if(input.id==='opacity'||input.id==='size')await send('set_reticle',{field:input.id,value:input.value});
  }catch(error){render();report(error);}
});
content.addEventListener('input',event=>{
  if(event.target.id==='operator-search'){
    filter=event.target.value;renderOperators();document.querySelector('#operator-search').focus();
  }
});
dialog.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.id==='confirm-import'){await send('confirm_import',{token:button.dataset.token});dialog.close();}
    else if(button.id==='mode-real'||button.id==='mode-simulation'){
      await send('set_mode',{mode:button.id==='mode-real'?'real':'simulation',epoch:button.dataset.epoch});dialog.close();
    }
    else if(button.id==='diagnostic-run')await send('simulate_start');
    else if(button.id==='diagnostic-stop')await send('simulate_stop');
    else if(button.id==='diagnostic-pause')await send(integrated?'set_pause':'toggle_pause',integrated?{paused:!(client.diagnostics?.paused??state.paused),epoch:state.safety_epoch}:{});
    if(dialogKind==='diagnostics')document.querySelector('#diagnostic-data').innerHTML=diagnosticsHTML();
  }catch(error){report(error);}
});
document.addEventListener('keyup',event=>{
  if(integrated)return; // global listener is the sole owner: no double toggle
  if(!state || (dialog.open && dialogKind!=='diagnostics') || event.ctrlKey || event.altKey || event.metaKey || event.target.closest('input,textarea,select,[contenteditable=true]'))return;
  if(event.key==='1'||event.key==='2')send('select_weapon',{weapon:event.key==='1'?'primary':'secondary'}).catch(report);
  else if(event.key.toLowerCase()==='p')send('toggle_pause').catch(report);
});
try{
  let transport;
  if(integrated)transport=await internalTransport();
  else{
    const response=await fetch('/data/profiles.json',{cache:'no-store'});
    if(!response.ok)throw new Error(`Catálogo indisponível (${response.status}).`);
    transport=previewTransport(await response.json());
  }
  client=new BackendClient(transport);
  await send('snapshot');
  if(integrated){
    document.title='R6 Rebuild';
    document.querySelector('.brand small').textContent='CONTROLE LOCAL · 0.5';
    document.querySelector('.preview-caption').innerHTML='<span>FASE 5 · MODOS EXPLÍCITOS</span> Início seguro em Simulação. F12: emergência global.';
    setTimeout(pollGlobal,350);
    setTimeout(pollLiveDiagnostics,200);
    if(state.notices.some(n=>n.includes('inválid')||n.includes('recuperada')))showDialog('Recuperação das configurações',state.notices.map(n=>'<p>'+escape(n)+'</p>').join(''));
  }
}catch(error){content.innerHTML=`<p class="loading error">Não foi possível carregar a aplicação.<br>${escape(error.message)}</p>`;}
