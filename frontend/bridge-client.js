// Serialized commands; only confirmed backend snapshots become visible state.
export class BackendClient {
  constructor(invoke) { this.invoke=invoke; this.state=null; this.tail=Promise.resolve(); this.diagnostics=null; }
  send(action,payload={}) {
    const run=async()=>{
      const reply=await this.invoke(action,payload);
      const diagnostic=reply.diagnostics || reply.state?.diagnostics;
      if(diagnostic && (!this.diagnostics || diagnostic.observed_ns>=this.diagnostics.observed_ns))this.diagnostics=diagnostic;
      if(reply.state && (!this.state || reply.state.revision>=this.state.revision)) this.state=reply.state;
      if(!reply.ok) throw new Error(reply.error || 'Comando rejeitado pelo backend.');
      return reply;
    };
    // Emergency bypasses pending file dialogs and normal command serialization.
    if(action==='diagnostics' || action==='emergency' || (action==='set_pause' && payload.paused===true))return run();
    const operation=this.tail.then(run);
    this.tail=operation.catch(()=>{});
    return operation;
  }
}

// Pure diagnostic view, independently testable without a browser or input API.
export function inputDiagnosticsHTML(d) {
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const reasons={worker_inactive:'worker encerrado/não iniciado',worker_error:'falha do worker',
    operation_block:'operação interna em andamento',global_pause:'pausa geral ativa',weapon_pause:'arma pausada',
    unconfigured_profile:'intervalo não configurado ou abaixo de 0.001 s',await_release:'aguardando soltar L e R',
    listener_unavailable:'listener indisponível',heartbeat_stale:'heartbeat vencido',input_revalidation:'validando divergência L/R (saída suspensa)',
    output_unavailable:'saída indisponível',output_blocked:'barreira da saída bloqueada',
    left_released:'L do motor solto',right_released:'R do motor solto'};
  const e=d.listener_events;
  const pair=v=>v?`${v.left} / ${v.right}`:'sem amostra';
  const change=d.last_input_change;
  const age=stamp=>Number.isFinite(stamp)?Math.max(0,(d.observed_ns-stamp)/1e6).toFixed(1)+' ms atrás':'sem horário';
  const state=value=>value===true?'pressionado':value===false?'solto':'desconhecido';
  const states=v=>`${state(v?.left)} / ${state(v?.right)}`;
  const sample=e?.async_sample, hook=e?.last_event, release=e?.last_release, received=d.input_received;
  const reconciled=d.reconciled_input||d.physical_input;
  const pending=['left','right'].map((name,i)=>{
    const p=e?.pending?.[name];
    return `${i?'R':'L'}: ${p?`${escape(p.reason)} · DOWN #${p.press} · ${age(p.since_ns)} · votos +${p.positive}/−${p.negative}`:'nenhuma'}`;
  }).join('; ');
  return `<p>Hook L/R (últimos eventos): ${states(e?.hook_buttons)}<br>
    Windows L/R (última consulta): ${states(sample)}<br>
    Reconciliado L/R: ${states(reconciled)} · Holding (L + R): ${d.holding?'SIM':'NÃO'}<br>
    Motor L/R: ${d.input.left_pressed?'pressionado':'solto'} / ${d.input.right_pressed?'pressionado':'solto'}<br>
    Worker: ${d.worker_active?'ativo':'inativo'} · Thread: ${d.worker_running?'em execução/aguardando':'parada'} · Arma selecionada: ${d.weapon_enabled?'ativada':'pausada'}<br>
    Elegível: ${d.eligible?'SIM':'NÃO'} · Motivos: ${d.blockers?.length?d.blockers.map(r=>escape(reasons[r]||r)).join('; '):'nenhum'}<br>
    Bloqueios operacionais: ${escape((d.operation_blocks||[]).join(', ')||'nenhum')}<br>
    Eventos não injetados recebidos (L / R): DOWN ${pair(e?.down)} · UP ${pair(e?.up)}<br>
    Suspensões preventivas por reconciliação (L / R): ${pair(e?.reconciled_releases)} · Liberações confirmadas por validação: ${pair(e?.confirmed_releases)} · Recuperações: ${pair(e?.recoveries)}<br>
    Duplicados do hook: ${e?.duplicates??0} · Injetados ignorados: ${e?.injected_ignored??0} · Consultas obsoletas descartadas: ${e?.discarded_samples??0} · Entregas rejeitadas pelo motor: ${d.input_rejected??0}<br>
    Último evento do hook: ${hook?`${escape(hook.button)} ${hook.down?'DOWN':'UP'} · #${hook.sequence} · ${age(hook.observed_ns)}`:'—'}<br>
    Sequência do hook L/R: ${pair(e?.hook_sequences)} · Publicação do listener: ${age(e?.published_ns)}<br>
    Consulta Windows: ${sample?`#${sample.sequence} · início ${age(sample.started_ns)} · fim ${age(sample.observed_ns)} · duração ${((sample.observed_ns-sample.started_ns)/1e6).toFixed(3)} ms · válida L/R: ${pair(sample.valid)} · hook na aquisição: ${pair(sample.hook_sequences)}`:'—'}<br>
    Validação pendente: ${pending}<br>
    Última entrega aceita pelo motor: ${received?`#${received.sequence} · ${age(received.observed_ns)} · L/R ${states(received.buttons)}`:'—'}<br>
    Última liberação/suspensão: ${release?`${escape(release.button)} · ${escape(release.reason)} · ${release.confirmed?'definitiva':'preventiva'} · ${age(release.observed_ns)} · evento #${release.event_sequence} / consulta #${release.sample_sequence}`:'—'}<br>
    Última alteração de entrada: ${change?escape(change.source)+' · '+age(change.observed_ns):'—'}<br>
    Última interrupção do motor: ${d.last_stop?escape(d.last_stop.reason)+' · '+age(d.last_stop.observed_ns):'nenhuma registrada'}<br>
    Holding refere-se ao estado reconciliado; não significa elegibilidade. Estados do hook, Windows e motor têm horários distintos. Uma consulta positiva isolada não cria um DOWN.<br>
    Geração conta reinicializações dos resíduos, não eventos nem movimentos.
    ${d.mode==='simulation'?'Em Simulação, cliques físicos são observados, mas somente entrada sintética alimenta o motor.':''}</p>${synchronizationDiagnosticsHTML(d)}`;
}

export function synchronizationDiagnosticsHTML(d) {
  const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ms=v=>Number.isFinite(v)?(v/1e6).toFixed(3)+' ms':'—';
  const h=d.heartbeat, output=d.sink, api=output?.last_api_call, fault=d.last_transition;
  const codes={heartbeat_timeout:'heartbeat vencido',listener_unavailable:'listener indisponível',
    output_failure:'falha de saída',output_unavailable:'saída indisponível',critical_failure:'falha crítica',critical_worker_failure:'falha crítica do worker',
    emergency:'F12/controle',manual_mode:'troca manual',shutdown:'encerramento',dispatch_rejected:'emissão descartada'};
  const locks=v=>Object.entries(v||{}).map(([name,metric])=>`${esc(name)}: ${ms(metric.last_ns)} / máx. ${ms(metric.max_ns)}`).join('; ')||'—';
  const apiInfo=v=>v?`duração ${ms(v.duration_ns)} · retorno ${esc(v.return_value??'—')} · erro Windows ${esc(v.winerror??'não disponível')} · ${esc(v.error||'sem exceção')}`:'nenhuma chamada registrada';
  return `<p><strong>Sincronização e segurança</strong><br>
    Heartbeat: idade ${ms(h?.age_ns)} · limite ${ms(h?.timeout_ns)} · intervalo entre publicações ${ms(h?.publication_gap_ns)} · atraso até recebimento ${ms(h?.delivery_delay_ns)}<br>
    Horários monotônicos do heartbeat: produzido ${esc(h?.produced_ns??'—')} ns · recebido ${esc(h?.received_ns??'—')} ns<br>
    Fase atual do listener: ${esc(d.listener_progress?.progress?.phase??'desconhecida')} · publicação #${d.listener_progress?.progress?.heartbeat_sequence??'—'}<br>
    Saída em andamento: ${output?.in_flight?'SIM':'NÃO'} · fila de movimentos: ${output?.queued??0} · preparações descartadas: ${d.discarded_preparations??0} · conclusões de geração antiga: ${d.stale_completions??0}<br>
    SendInput (última chamada): ${apiInfo(api)}<br>
    Espera pelo lock do motor: ${locks(d.lock_wait)}<br>
    Espera pelo controle da saída: ${ms(output?.lock_wait?.last_ns)} / máx. ${ms(output?.lock_wait?.max_ns)}<br>
    Última transição REAL → SIMULAÇÃO (registro congelado): ${fault?`${esc(codes[fault.code]||fault.code)} · ${esc(fault.detail)} · ${esc(fault.observed_ns)} ns<br>
    No instante da ocorrência: heartbeat ${ms(fault.heartbeat?.age_ns)} / limite ${ms(fault.heartbeat?.timeout_ns)} · atraso de entrega ${ms(fault.heartbeat?.delivery_delay_ns)} · intervalo de publicação ${ms(fault.heartbeat?.publication_gap_ns)}<br>
    Listener na ocorrência: ${esc(fault.listener?.progress?.phase??'desconhecido')} · operacional ${esc(fault.listener?.operational??'desconhecido')} · erro ${esc(fault.listener?.error??fault.listener?.diagnostic_error??'nenhum registrado')}<br>
    Último evento de saúde recebido na ocorrência: ${esc(fault.heartbeat?.last_delivery?.healthy??'desconhecido')} · atraso ${ms(fault.heartbeat?.last_delivery?.delay_ns)} · intervalo de publicação ${ms(fault.heartbeat?.last_delivery?.publication_gap_ns)}<br>
    Saída na ocorrência: ${fault.output?.in_flight?'em andamento':'sem chamada em andamento'} · ${apiInfo(fault.output?.last_api_call)}<br>
    Esperas de locks na ocorrência: ${locks(fault.lock_wait)}`:'nenhuma'}<br>
    Bloqueio impede novas emissões. Não cancela retroativamente a chamada já admitida pelo adaptador; seu retorno pode ocorrer depois da parada. Não há fila nem reenvio.</p>`;
}

export async function internalTransport(win=window) {
  if(!win.pywebview?.api) await new Promise((resolve,reject)=>{
    const ready=()=>{clearTimeout(timer);resolve();};
    const timer=setTimeout(()=>{win.removeEventListener('pywebviewready',ready);reject(new Error('Ponte Python indisponível. Abra com tools/run_app.py.'));},10000);
    win.addEventListener('pywebviewready',ready,{once:true});
  });
  if(typeof win.pywebview?.api?.invoke!=='function') throw new Error('Ponte Python inválida.');
  return (action,payload)=>win.pywebview.api.invoke(action,payload);
}
