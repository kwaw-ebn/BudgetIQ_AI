/* Internal comparison only. No tender publication, contract award or purchase order. */
let procurementState=null;
const procurementPath=()=>`/projects/${projectId}/procurement`;
const procurementMoney=value=>`${clean(procurementState?.currency||'GHS')} ${Number(value||0).toLocaleString('en-GH',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
async function renderProcurement(){
  if(!authToken||!projectId)return;
  try{
    const id=projectId,state=await apiRequest(procurementPath());if(id!==projectId)return;
    procurementState=state;
    $('proc-member-panel').hidden=state.role!=='preparer';$('proc-create-panel').hidden=state.role!=='preparer';
    $('proc-activity').innerHTML=state.activities.map(a=>`<option value="${clean(a.id)}">${clean(a.title)} · ${procurementMoney(a.planned)}</option>`).join('');
    $('proc-members').innerHTML=state.procurement_members.map(x=>`<div class="report-row"><span>${clean(x)}</span><b>Procurement</b></div>`).join('')||'<p class="muted">Assign a separate procurement evaluator.</p>';
    $('proc-cases').innerHTML=state.cases.length?state.cases.map(c=>{
      const quotes=c.quotes.map(q=>`<tr><td>${clean(q.supplier)}</td><td>${clean(q.reference)}</td><td>${procurementMoney(q.price)}</td><td>${q.responsive?'Responsive':'Not responsive'}</td><td>${q.technical_score}/100</td><td>${clean(q.note)}</td></tr>`).join('');
      const add=state.role==='procurement'&&['draft','quotations'].includes(c.status)?`<div class="evidence-form" data-proc-quote-form="${clean(c.id)}"><label>Supplier<input data-field="supplier" placeholder="Supplier name"></label><label>Quote reference<input data-field="reference" placeholder="Reference"></label><label>Quoted price<input data-field="price" type="number" min="0.01" step="0.01"></label><label>Technical score / 100<input data-field="technical_score" type="number" min="0" max="100" value="70"></label><label>Responsiveness<select data-field="responsive"><option value="true">Meets stated requirements</option><option value="false">Does not meet requirements</option></select></label><label>Evaluation note<input data-field="note" placeholder="Evidence and concerns"></label><button class="outline" data-proc-action="quote" data-case-id="${clean(c.id)}">Add offer</button></div>`:'';
      const recommend=state.role==='procurement'&&c.status==='quotations'?`<div class="evidence-form" data-proc-recommend-form="${clean(c.id)}"><label>Recommended responsive offer<select data-field="quote_id">${c.quotes.filter(q=>q.responsive).map(q=>`<option value="${clean(q.id)}">${clean(q.supplier)} · ${procurementMoney(q.price)}</option>`).join('')}</select></label><label>Evaluation rationale<input data-field="rationale" placeholder="Compare price, fit and evidence"></label><label>If only one offer, explain<input data-field="single_offer_reason" placeholder="Reason"></label><label>Conflict declaration<select data-field="no_conflict"><option value="false">Choose declaration</option><option value="true">I have no conflict of interest</option></select></label><button class="primary" data-proc-action="recommend" data-case-id="${clean(c.id)}">Submit recommendation</button></div>`:'';
      const decide=state.role==='approver'&&c.status==='recommended'?`<div class="proc-actions"><button class="primary" data-proc-action="approve" data-case-id="${clean(c.id)}">Approve internal recommendation</button><button class="outline" data-proc-action="return" data-case-id="${clean(c.id)}">Return for review</button></div>`:'';
      const handoff=state.role==='preparer'&&c.status==='approved'&&!c.treasury_request_id?`<button class="primary" data-proc-action="handoff" data-case-id="${clean(c.id)}">Create Treasury draft</button>`:'';
      return `<div class="activity proc-case"><div class="activity-head proc-case-head"><div><strong>${clean(c.title)}</strong><small>${clean(state.activities.find(a=>a.id===c.activity_id)?.title||'Activity removed')}</small></div><div><b>${clean(c.status)}</b><small>${clean(c.method)}</small></div><div><b>${procurementMoney(c.estimate)}</b><small>Estimate · Q${c.quarter}</small></div></div><div class="proc-case-body"><p class="muted">Funding: ${clean(c.funding_source)} · Method reason: ${clean(c.reason)} ${c.external_reference?'· External reference: '+clean(c.external_reference):''}</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Supplier</th><th>Quote ref</th><th>Price</th><th>Requirements</th><th>Score</th><th>Notes</th></tr></thead><tbody>${quotes||'<tr><td colspan="6">No offers recorded.</td></tr>'}</tbody></table></div>${c.recommended_quote_id?`<p><strong>Recommendation:</strong> ${clean(c.quotes.find(q=>q.id===c.recommended_quote_id)?.supplier||'Unknown')} · ${clean(c.recommendation)}</p>`:''}${c.treasury_request_id?`<p class="muted">Linked Treasury draft: ${clean(c.treasury_request_id.slice(0,8))}</p>`:''}${add}${recommend}${decide}${handoff}</div></div>`;
    }).join(''):'<p class="muted">No procurement cases. Create one from a costed activity.</p>';
    $('proc-events').innerHTML=state.events.map(e=>`<div class="review-event"><b>${clean(e.action)}</b> · ${clean(e.at)}<small>${clean(e.note)} · case ${clean(e.case_id.slice(0,8))}</small></div>`).join('')||'<p class="muted">No activity yet.</p>';
  }catch(err){message(err.message,true)}
}
$('proc-refresh').onclick=renderProcurement;
$('proc-add-member').onclick=async()=>{try{await apiRequest(procurementPath()+'/members','POST',{email:$('proc-member-email').value.trim()});$('proc-member-email').value='';message('Procurement role assigned.');await renderProcurement()}catch(err){message(err.message,true)}};
$('proc-create').onclick=async()=>{try{
  await apiRequest(procurementPath()+'/cases','POST',{activity_id:$('proc-activity').value,title:$('proc-title').value.trim(),estimate:$('proc-estimate').value,method:$('proc-method').value,reason:$('proc-reason').value.trim(),funding_source:$('proc-source').value.trim(),quarter:Number($('proc-quarter').value),external_reference:$('proc-external').value.trim()});
  $('proc-title').value='';$('proc-estimate').value='';message('Procurement case saved.');await renderProcurement()
}catch(err){message(err.message,true)}};
$('proc-cases').onclick=async e=>{
  const b=e.target.closest('[data-proc-action]');if(!b)return;
  const action=b.dataset.procAction,id=b.dataset.caseId,base=procurementPath()+`/cases/${id}`;
  try{
    b.disabled=true;
    if(action==='quote'){
      const form=b.closest('[data-proc-quote-form]'),get=k=>form.querySelector(`[data-field="${k}"]`).value;
      await apiRequest(base+'/quotes','POST',{supplier:get('supplier').trim(),reference:get('reference').trim(),price:get('price'),technical_score:Number(get('technical_score')),responsive:get('responsive')==='true',note:get('note').trim()});
    }else if(action==='recommend'){
      const form=b.closest('[data-proc-recommend-form]'),get=k=>form.querySelector(`[data-field="${k}"]`).value;
      await apiRequest(base+'/recommend','POST',{quote_id:get('quote_id'),rationale:get('rationale').trim(),single_offer_reason:get('single_offer_reason').trim(),no_conflict:get('no_conflict')==='true'});
    }else if(action==='approve'||action==='return'){
      const note=prompt('Record the reason for this decision:');if(note===null){b.disabled=false;return}
      await apiRequest(base+'/decision','POST',{decision:action,note:note.trim()});
    }else if(action==='handoff'){
      await apiRequest(base+'/treasury-draft','POST',{});
    }
    message('Procurement record updated.');await renderProcurement()
  }catch(err){b.disabled=false;message(err.message,true)}
};
