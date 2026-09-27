/* Transparent annual reference forecasts. Only audited actuals enter validation. */
const BudgetIQAnalytics=(()=>{
  const stages=['Original budget','Revised estimate','Provisional result','Audited actual'];
  const metrics=['Revenue','Expenditure'];
  const latest=(records,year,metric,stage)=>[...records].reverse().find(r=>Number(r.year)===Number(year)&&r.metric===metric&&r.stage===stage);
  const pct=(a,b)=>b===0?null:100*(a-b)/b;
  function quality(records,currency){
    const warnings=[],keys=new Set();
    for(const r of records){
      const key=`${r.year}|${r.metric}|${r.stage}`;
      if(keys.has(key))warnings.push(`Repeated ${r.year} ${r.metric} ${r.stage}; latest entry is used.`);
      keys.add(key);
      if(r.currency!==currency)warnings.push(`${r.year} ${r.metric}: ${r.currency} differs from project currency ${currency}.`);
      if(!Number.isFinite(Number(r.amount))||Number(r.amount)<0)warnings.push(`${r.year} ${r.metric}: invalid amount.`);
    }
    for(const metric of metrics){
      const years=[...new Set(records.filter(r=>r.metric===metric&&r.stage==='Audited actual'&&r.currency===currency).map(r=>Number(r.year)))].sort((a,b)=>a-b);
      if(years.length>1)for(let y=years[0]+1;y<years.at(-1);y++)if(!years.includes(y))warnings.push(`${metric}: audited actual missing for ${y}; forecasting paused.`);
    }
    return [...new Set(warnings)];
  }
  function predict(method,values){
    const n=values.length;
    if(method==='Last actual')return values[n-1];
    if(method==='Linear trend'){
      const xm=(n-1)/2,ym=values.reduce((a,b)=>a+b,0)/n;
      const slope=values.reduce((s,y,x)=>s+(x-xm)*(y-ym),0)/values.reduce((s,_,x)=>s+(x-xm)**2,0);
      return ym+slope*(n-xm);
    }
    if(method==='Exponential smoothing'){
      let level=values[0];for(let i=1;i<n;i++)level=.5*values[i]+.5*level;return level;
    }
    let level=values[0],trend=values[1]-values[0];
    for(let i=1;i<n;i++){const old=level;level=.5*values[i]+.5*(level+trend);trend=.3*(level-old)+.7*trend}
    return level+trend;
  }
  function forecast(records,metric,currency){
    const all=records.filter(r=>r.metric===metric&&r.stage==='Audited actual'&&r.currency===currency);
    const years=[...new Set(all.map(r=>Number(r.year)))].sort((a,b)=>a-b);
    if(years.length<4)return {reason:`At least four annual audited ${metric.toLowerCase()} results are needed for a provisional comparison.`};
    if(years.some((y,i)=>i&&y!==years[i-1]+1))return {reason:'Audited years have gaps. Fill them before forecasting.'};
    const values=years.map(y=>Number(latest(all,y,metric,'Audited actual').amount));
    if(values.some(v=>!Number.isFinite(v)||v<0))return {reason:'Invalid audited amount. Review the financial records.'};
    const methods=['Last actual','Linear trend','Exponential smoothing','Holt trend'];
    const results=methods.map(name=>{
      const errors=[];for(let i=3;i<values.length;i++)errors.push(predict(name,values.slice(0,i))-values[i]);
      return {name,mae:errors.reduce((s,e)=>s+Math.abs(e),0)/errors.length,
        rmse:Math.sqrt(errors.reduce((s,e)=>s+e*e,0)/errors.length),
        mape:errors.every((_,j)=>values[j+3]!==0)?errors.reduce((s,e,j)=>s+100*Math.abs(e)/values[j+3],0)/errors.length:null,
        bias:errors.reduce((s,e)=>s+e,0)/errors.length,
        next:Math.max(0,predict(name,values))};
    }).sort((a,b)=>a.mae-b.mae);
    return {year:years.at(-1)+1,trainYears:years.length,testYears:values.length-3,results,best:results[0],
      reason:values.length<6?'Preliminary: few held-out years. Review assumptions before allocating funds.':''};
  }
  return {stages,metrics,latest,pct,quality,forecast};
})();
if(typeof module!=='undefined')module.exports=BudgetIQAnalytics;
