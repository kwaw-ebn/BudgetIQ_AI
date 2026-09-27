/* Separate, server-enforced treasury pilot. Existing execution rows remain planning records. */
let treasuryState=null;
const treasuryPath=()=>`/projects/${projectId}/treasury`;
const treasuryMoney=v=>`${clean(treasuryState?.currency||'GHS')} ${Number(v||0).toLocaleString('en-GH',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
async function renderTreasury(){
  if(!authToken||!projectId)return;
  try{
    const id=projectId,state=await apiRequest(treasuryPath());if(id!==projectId)return;
    treasuryState=state;
    $('treasury-summary').innerHTML=metric('Budget ceiling',treasuryMoney(state.ceiling))+metric('Reserved requests',treasuryMoney(state.reserved))+metric('Available',treasuryMoney(state.available),Number(state.available)<0?'warn':'good');
    $('treasury-member-panel').hidden=state.role!=='preparer'||!!currentProjectOrganizationId;
    $('treasury-release-panel').hidden=state.role!=='preparer';
    $('treasury-request-panel').hidden=state.role!=='preparer';
    $('treasury-releases').innerHTML=state.releases.map(x=>`<div class="report-row"><span>${clean(x.source)} · Q${x.quarter}</span><b>${treasuryMoney(x.amount)}</b></div>`).join('')||'<p class="muted">No internal funding releases recorded.</p>';
    $('treasury-activity').innerHTML=state.activities.map(a=>`<option value="${clean(a.id)}">${clean(a.title)} · available ${treasuryMoney(a.available)}</option>`).join('');
    $('treasury-members').innerHTML=state.members.map(m=>`<div class="report-row"><span>${clean(m.email)}</span><b>${clean(m.role)}</b></div>`).join('')||'<p class="muted">No reviewer or approver assigned.</p>';
    const action=(r)=>{
      const possible={draft:['submit','preparer'],submitted:['review','reviewer'],reviewed:['approve','approver'],approved:['commit','preparer'],committed:['invoice','preparer'],invoiced:['record_payment','preparer'],'partially paid':['record_payment','preparer']}[r.status];
      let buttons=possible&&possible[1]===state.role?`<button class="outline" data-treasury-action="${possible[0]}" data-treasury-id="${clean(r.id)}">${{submit:'Submit',review:'Review',approve:'Approve',commit:'Record commitment',invoice:'Record invoice',record_payment:'Record payment'}[possible[0]]}</button>`:'';
      if(['submitted','reviewed'].includes(r.status)&&['reviewer','approver'].includes(state.role))buttons+=` <button class="outline" data-treasury-action="reject" data-treasury-id="${clean(r.id)}">Reject</button>`;
      return buttons||'—';
    };
    $('treasury-requests').innerHTML=state.requests.length?`<table class="data-table"><thead><tr><th>Activity</th><th>Request</th><th>Supplier</th><th>Quarter</th><th>Commitment</th><th>Status and match</th><th>Action</th></tr></thead><tbody>${state.requests.map(r=>`<tr><td>${clean(state.activities.find(a=>a.id===r.activity_id)?.title||'Activity removed')}</td><td><strong>${clean(r.description)}</strong><br><small>${clean(r.funding_source)}</small></td><td>${clean(r.supplier||'—')}</td><td>Q${r.quarter}</td><td>${treasuryMoney(r.amount)}</td><td>${clean(r.status)}<br><small>${r.invoice_amount?'Invoice '+treasuryMoney(r.invoice_amount)+' · paid '+treasuryMoney(r.paid_amount)+' · due '+treasuryMoney(r.outstanding):''}</small><br><small>${clean(r.invoice_ref||'')} ${clean(r.delivery_reference||'')} ${clean(r.payment_ref||'')}</small></td><td>${action(r)}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">No requests yet. Start with a planned activity, ceiling and funding release.</p>';
    $('treasury-events').innerHTML=state.events.map(e=>`<div class="review-event"><b>${clean(e.action)}</b> · ${clean(e.at)}<small>${clean(e.note||'No note')} · request ${clean(e.request_id.slice(0,8))}</small></div>`).join('')||'<p class="muted">Decisions and changes appear here.</p>';
  }catch(err){message(err.message,true)}
}
$('treasury-refresh').onclick=renderTreasury;
$('treasury-add-release').onclick=async()=>{
  try{
    await apiRequest(treasuryPath()+'/releases','POST',{source:$('treasury-release-source').value.trim(),quarter:Number($('treasury-release-quarter').value),amount:$('treasury-release-amount').value});
    $('treasury-release-amount').value='';message('Internal release recorded on server.');await renderTreasury()
  }catch(err){message(err.message,true)}
};
$('treasury-add-member').onclick=async()=>{
  try{
    await apiRequest(treasuryPath()+'/members','POST',{email:$('treasury-member-email').value.trim(),role:$('treasury-member-role').value});
    $('treasury-member-email').value='';message('Role assigned to existing account.');await renderTreasury()
  }catch(err){message(err.message,true)}
};
$('treasury-create').onclick=async()=>{
  try{
    await apiRequest(treasuryPath()+'/requests','POST',{activity_id:$('treasury-activity').value,description:$('treasury-description').value.trim(),amount:$('treasury-amount').value,supplier:$('treasury-supplier').value.trim(),funding_source:$('treasury-source').value.trim(),quarter:Number($('treasury-quarter').value)});
    $('treasury-description').value='';$('treasury-amount').value='';message('Draft request saved on server.');await renderTreasury()
  }catch(err){message(err.message,true)}
};
$('treasury-requests').onclick=async e=>{
  const button=e.target.closest('[data-treasury-action]');if(!button)return;
  const action=button.dataset.treasuryAction;
  const reference=['invoice','record_payment'].includes(action)?prompt(`Enter the ${action==='invoice'?'invoice':'payment'} reference:`):'';
  if(['invoice','record_payment'].includes(action)&&!reference?.trim())return;
  const delivery_reference=action==='invoice'?prompt('Enter the goods receipt or service completion reference:'):'';
  if(action==='invoice'&&!delivery_reference?.trim())return;
  const amount=['invoice','record_payment'].includes(action)?prompt(`Enter the ${action==='invoice'?'matched invoice':'payment'} amount:`):null;
  if(['invoice','record_payment'].includes(action)&&(!amount||!Number.isFinite(Number(amount))||Number(amount)<=0))return;
  const note=['reject','review','approve'].includes(action)?prompt('Decision note (required for rejection):'):'';
  if(note===null)return;
  try{
    button.disabled=true;
    await apiRequest(treasuryPath()+`/requests/${button.dataset.treasuryId}/actions`,'POST',{action,reference:reference||'',delivery_reference:delivery_reference||'',amount:amount||null,note:note||''});
    message('Treasury record updated.');await renderTreasury()
  }catch(err){button.disabled=false;message(err.message,true)}
};
