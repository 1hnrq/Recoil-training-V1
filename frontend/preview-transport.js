// Retain the read-only standalone visual preview, never pretend it is connected.
import {createState,selectOperator,selectWeapon,toggleWeapon,updateParameter,units,decimal} from './model.js';
export function previewTransport(catalog) {
  const state=createState(catalog);
  state.reticle={mark:'+',opacity:'80',size:'70'};state.revision=0;state.saved=false;state.notices=[];
  return async(action,p={})=>{
    try {
      if(action==='select_operator')selectOperator(state,p.id);
      else if(action==='select_weapon')selectWeapon(state,p.weapon);
      else if(action==='toggle_weapon')toggleWeapon(state,p.weapon);
      else if(action==='toggle_pause')state.paused=!state.paused;
      else if(action==='update_parameter')updateParameter(state,p.weapon,p.field,p.value);
      else if(action==='step_parameter'){
        const op=state.operators.find(o=>o.id===p.operator);
        updateParameter(state,p.weapon,p.field,decimal(units(op[p.weapon][p.field])+BigInt(p.direction)*(p.field==='interval_seconds'?1000n:100000n)));
      }
      else if(action==='set_multiplier'){const v=units(p.value);if(v<=0n)throw new Error('Multiplicador deve ser positivo.');state.multipliers[p.axis]=decimal(v);}
      else if(action==='set_view')state.view=p.view;
      else if(action==='set_reticle')state.reticle[p.field]=p.value;
      else if(!['snapshot','simulate_stop'].includes(action))throw new Error('Abra a aplicação Python para usar esta função.');
      state.revision++;
      return {ok:true,state:structuredClone(state)};
    } catch(error){return {ok:false,error:error.message,state:structuredClone(state)};}
  };
}
