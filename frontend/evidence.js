/* Financial history is part of the authenticated, server-saved project document. */
let financialPreview=[];
let evidenceProjectId=null;
function ensureEvidence(){
  project.financialRecords ||= [];
  project.planVersions ||= [];
  project.revisionEvents ||= [];
}
function renderEvidence(){
  ensureEvidence();
  if(evidenceProjectId!==projectId){evidenceProjectId=projectId;financialPreview=[];$('financial-year').value=project.year;$('commit-financial').hidden=true;$('import-preview').textContent=''}
  const A=BudgetIQAnalytics,records=project.financialRecords,fmt=money;
  $('snapshot-list').innerHTML=project.planVersions.length?[...project.planVersions].reverse().map(v=>`<div class="review-event"><b>${clean(v.stage)}</b> · ${clean(v.year)} · ${fmt(v.planTotal)}<small>${clean(v.at)} · ${clean(v.note||'No reference')} · ${v.activities.length} activities</small></div>`).join(''):'<p class="muted">No saved plan versions yet. Capture the original budget when ready.</p>';
  $('financial-list').innerHTML=records.length?`<table class="data-table"><thead><tr><th>Year</th><th>Metric</th><th>Stage</th><th>Amount</th><th>Source</th><th>Note</th></tr></thead><tbody>${[...records].reverse().slice(0,100).map(r=>`<tr><td>${clean(r.year)}</td><td>${clean(r.metric)}</td><td>${clean(r.stage)}</td><td>${fmt(r.amount)}</td><td>${clean(r.source)}</td><td>${clean(r.note||'—')}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">No annual financial records yet.</p>';
  const rows=[];
  for(const metric of A.metrics){
    const years=[...new Set(records.filter(r=>r.metric===metric).map(r=>Number(r.year)))].sort((a,b)=>b-a);
    for(const year of years.slice(0,5)){
      const original=A.latest(records,year,metric,'Original budget'),revised=A.latest(records,year,metric,'Revised estimate'),actual=A.latest(records,year,metric,'Audited actual');
      const revision=original&&revised?A.pct(Number(revised.amount),Number(original.amount)):null;
      const execution=original&&actual?A.pct(Number(actual.amount),Number(original.amount)):null;
      rows.push(`<div class="report-row"><span>${clean(metric)} ${year}<small>Revision: ${original&&revised?`${fmt(revised.amount- original.amount)} (${revision===null?'n/a':revision.toFixed(1)+'%'})`:'awaiting original and revised figures'}<br>Execution: ${original&&actual?`${fmt(actual.amount-original.amount)} (${execution===null?'n/a':execution.toFixed(1)+'%'})`:'requires audited actual'}</small></span></div>`);
    }
  }
  $('financial-variance').innerHTML=rows.join('')||'<p class="muted">Add original, revised and audited records to compare stages.</p>';
  if(project.revisionEvents.length)$('financial-variance').innerHTML+=`<h4>Revision notes</h4>${[...project.revisionEvents].reverse().slice(0,10).map(e=>`<div class="review-event"><b>${clean(e.metric)} ${clean(e.year)}</b> · ${fmt(e.revised)}<small>${clean(e.at)} · ${clean(e.reason||'No reason supplied')}</small></div>`).join('')}`;
  const warnings=A.quality(records,project.currency);
  $('financial-quality').innerHTML=warnings.length?`<ul>${warnings.slice(0,20).map(w=>`<li>${clean(w)}</li>`).join('')}</ul>`:'<p class="muted">No issues detected in the entered annual series. Source figures still need review.</p>';
  const metric=$('forecast-metric').value,forecast=A.forecast(records,metric,project.currency);
  if(!forecast.results){$('forecast-results').innerHTML=`<p class="muted">${clean(forecast.reason)}</p>`;return}
  const best=forecast.best;
  $('forecast-results').innerHTML=`<p>Next year: <b>${forecast.year}</b> · ${forecast.trainYears} audited years · ${forecast.testYears} held-out one-year tests.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Method</th><th>Next year</th><th>MAE</th><th>RMSE</th><th>MAPE</th><th>Average bias</th></tr></thead><tbody>${forecast.results.map(r=>`<tr><td>${clean(r.name)}${r===best?' · lowest MAE':''}</td><td>${fmt(r.next)}</td><td>${fmt(r.mae)}</td><td>${fmt(r.rmse)}</td><td>${r.mape===null?'n/a':r.mape.toFixed(1)+'%'}</td><td>${fmt(r.bias)}</td></tr>`).join('')}</tbody></table></div><p class="muted">${clean(forecast.reason||'One-year reference only; recheck as new audited results arrive.')} Forecasts use nominal annual totals and do not adjust for inflation or policy changes. Compare with your full plan and price scenario before approval.</p>`;
}
function addFinancialRecord(data){
  ensureEvidence();
  if(project.financialRecords.length>=300)throw Error('300 annual record limit reached. Export a backup before adding more.');
  const A=BudgetIQAnalytics,year=Number(data.year),amount=Number(data.amount),metric=data.metric,stage=data.stage,currency=data.currency;
  if(data.amount===null||data.amount===undefined||String(data.amount).trim()==='')throw Error('Enter an amount.');
  if(!Number.isInteger(year)||year<2000||year>2200||!Number.isFinite(amount)||amount<0||!A.metrics.includes(metric)||!A.stages.includes(stage))throw Error('Check year, metric, stage and nonnegative amount.');
  if(currency!==project.currency)throw Error(`Currency ${currency} differs from this project's ${project.currency}. Convert and document the source first.`);
  if(!data.source?.trim())throw Error('Enter the source of this figure.');
  const prior=A.latest(project.financialRecords,year,metric,stage);
  if(prior&&!data.note?.trim())throw Error('A corrected entry needs an explanation. Previous entries remain in the history.');
  const original=A.latest(project.financialRecords,year,metric,'Original budget');
  const variance=original&&stage==='Revised estimate'?A.pct(amount,Number(original.amount)):null;
  if(variance!==null&&Math.abs(variance)>=10&&!data.note?.trim())throw Error('A revision of 10% or more needs an explanation.');
  const record={id:uid(),at:today(),year,metric,stage,amount,currency,source:data.source.trim().slice(0,200),note:(data.note||'').trim().slice(0,500)};
  project.financialRecords.push(record);
  if(stage==='Revised estimate')project.revisionEvents.push({id:uid(),at:record.at,year,metric,original:original?.amount??null,revised:amount,reason:record.note,recordId:record.id});
}
$('capture-snapshot').onclick=()=>{
  try{
    ensureEvidence();if(project.planVersions.length>=12)throw Error('12 plan versions reached; use a project backup before capturing more.');
    const stage=$('snapshot-stage').value,note=$('snapshot-note').value.trim();
    if(stage==='Revised estimate'&&!note)throw Error('Explain why this plan is being revised.');
    if(stage==='Original budget'&&project.planVersions.some(v=>v.stage==='Original budget'&&Number(v.year)===Number(project.year)))throw Error('The original plan for this year is already captured. Use a revised estimate.');
    project.planVersions.push({id:uid(),at:today(),stage,year:Number(project.year),note,planTotal:total(),ceiling:num(project.ceiling),activities:structuredClone(project.activities),revenues:structuredClone(project.revenues)});
    $('snapshot-note').value='';save();renderEvidence();message(`${stage} captured as a read-only version in this project.`);
  }catch(err){message(err.message,true)}
};
$('add-financial').onclick=()=>{
  try{
    addFinancialRecord({year:$('financial-year').value,metric:$('financial-metric').value,stage:$('financial-stage').value,amount:$('financial-amount').value,currency:project.currency,source:$('financial-source').value,note:$('financial-note').value});
    $('financial-amount').value='';$('financial-note').value='';save();renderEvidence();message('Annual figure and its source saved.');
  }catch(err){message(err.message,true)}
};
$('forecast-metric').onchange=renderEvidence;
$('financial-upload').onchange=async e=>{
  financialPreview=[];$('commit-financial').hidden=true;
  const file=e.target.files[0];if(!file)return;
  const form=new FormData();form.append('file',file);
  try{
    $('import-preview').textContent='Checking file…';
    const response=await fetch(`${API}/api/financial/import`,{method:'POST',headers:{Authorization:`Bearer ${authToken}`},body:form});
    const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Import failed');
    const seen=new Set(),warnings=[...result.warnings];
    financialPreview=result.records.filter(r=>{
      const key=`${r.year}|${r.metric}|${r.stage}`;
      if(r.currency!==project.currency){warnings.push(`${key}: ${r.currency} differs from project currency; skipped.`);return false}
      if(seen.has(key)||BudgetIQAnalytics.latest(project.financialRecords||[],r.year,r.metric,r.stage)){warnings.push(`${key}: already recorded; skipped.`);return false}
      seen.add(key);
      const original=BudgetIQAnalytics.latest([...project.financialRecords,...result.records.filter(x=>x.stage==='Original budget')],r.year,r.metric,'Original budget');
      const variance=original&&r.stage==='Revised estimate'?BudgetIQAnalytics.pct(r.amount,original.amount):null;
      if(variance!==null&&Math.abs(variance)>=10&&!r.note){warnings.push(`${key}: revision above 10% needs a note; skipped.`);return false}
      return true;
    });
    $('import-preview').innerHTML=`<p>${financialPreview.length} of ${result.total_rows} rows ready to save.</p>${warnings.length?`<ul>${warnings.slice(0,30).map(w=>`<li>${clean(w)}</li>`).join('')}</ul>`:'<p class="muted">No import warnings.</p>'}`;
    $('commit-financial').hidden=!financialPreview.length;
  }catch(err){$('import-preview').textContent=err.message}
};
$('commit-financial').onclick=()=>{
  try{
    if((project.financialRecords||[]).length+financialPreview.length>300)throw Error('Import would exceed the 300 record limit.');
    let count=0;for(const record of financialPreview.sort((a,b)=>BudgetIQAnalytics.stages.indexOf(a.stage)-BudgetIQAnalytics.stages.indexOf(b.stage))){addFinancialRecord(record);count++}
    financialPreview=[];$('commit-financial').hidden=true;$('import-preview').textContent=`${count} checked records added. Review them before forecasting.`;
    save();renderEvidence();message(`${count} financial records saved to your project.`);
  }catch(err){message(err.message,true)}
};
renderEvidence();
