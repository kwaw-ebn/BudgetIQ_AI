"""BudgetIQ pilot API. Estimates require human review before approval."""
from __future__ import annotations
import csv
import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, File, HTTPException, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from storage import router as storage_router, init_storage, user_from_header
from treasury import router as treasury_router

app = FastAPI(title="BudgetIQ AI API", version="0.3.0")
app.include_router(storage_router)
app.include_router(treasury_router)
app.add_event_handler("startup", init_storage)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in __import__('os').environ.get('FRONTEND_ORIGIN','http://localhost:5500').split(',')], allow_methods=['GET','POST','PUT'], allow_headers=['*'])
MAX_BYTES = 8 * 1024 * 1024
EXTENSIONS = {'.csv','.xlsx','.xlsm','.docx','.pdf'}
CATEGORIES = [('training', 'Training'), ('workshop', 'Training'), ('supervision', 'Supervision'), ('monitoring', 'Monitoring'), ('outreach', 'Outreach'), ('meeting', 'Meeting'), ('screening', 'Screening'), ('procurement', 'Procurement')]

class Line(BaseModel):
    activity: str = Field(min_length=2, max_length=250)
    category: str = 'Other'
    cost_item: str = 'Activity cost'
    frequency: Decimal = Field(default=Decimal('1'), ge=0, le=100000)
    people: Decimal = Field(default=Decimal('1'), ge=0, le=1000000)
    unit_price: Decimal = Field(default=Decimal('0'), ge=0, le=1000000000)
    source: str = 'Estimate'
    note: str = ''

class Budget(BaseModel):
    organization: str = Field(default='New organization', max_length=200)
    year: int = Field(default=2027, ge=2000, le=2200)
    currency: str = Field(default='GHS', max_length=10)
    lines: list[Line] = Field(max_length=2000)
    ceiling: Decimal = Field(default=Decimal('0'), ge=0)
    status: str = 'Draft'
    objectives: list[dict] = Field(default_factory=list, max_length=500)
    programmes: list[dict] = Field(default_factory=list, max_length=500)
    activities: list[dict] = Field(default_factory=list, max_length=2000)
    revenues: list[dict] = Field(default_factory=list, max_length=2000)
    expenses: list[dict] = Field(default_factory=list, max_length=5000)
    reviews: list[dict] = Field(default_factory=list, max_length=2000)

async def read_upload(upload: UploadFile) -> tuple[bytes,str]:
    ext = Path(upload.filename or '').suffix.lower()
    if ext not in EXTENSIONS:
        raise HTTPException(400, f'Unsupported file type: {ext or "unknown"}')
    data = await upload.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES: raise HTTPException(413, 'Maximum file size is 8 MB')
    return data, ext

def extract(data: bytes, ext: str) -> list[str]:
    try:
        if ext == '.csv':
            return [' | '.join(row) for row in csv.reader(io.StringIO(data.decode('utf-8-sig'))) if any(row)]
        if ext in ('.xlsx','.xlsm'):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            result=[]
            for sheet in wb:
                for row in sheet.iter_rows(max_row=4000, max_col=25, values_only=True):
                    values=[str(v).strip() for v in row if v is not None and str(v).strip()]
                    if values:result.append(' | '.join(values[:10]))
                if len(result)>8000:break
            wb.close()
            return result
        if ext == '.docx':
            from docx import Document
            d=Document(io.BytesIO(data))
            return [p.text.strip() for p in d.paragraphs if p.text.strip()] + [' | '.join(c.text.strip() for c in row.cells) for table in d.tables for row in table.rows]
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data))
        if len(reader.pages)>100: raise HTTPException(400,'PDF exceeds 100 pages')
        return [line.strip() for page in reader.pages for line in (page.extract_text() or '').splitlines() if line.strip()]
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, f'Could not read document: {type(exc).__name__}') from exc

def candidates(rows:list[str]) -> list[dict]:
    seen=set(); out=[]
    for raw in rows:
        clean=re.sub(r'\s+',' ',raw).strip(' |\t')
        if len(clean)<8 or len(clean)>320:continue
        low=clean.lower()
        if low in seen:continue
        match=next((label for term,label in CATEGORIES if re.search(r'\b'+term+r'\b',low)),None)
        if not match:continue
        if any(word in low for word in ('total','unit price','prior year','revenue section','activity type','budget year')):continue
        seen.add(low)
        if len(out)>=100:break
        out.append({'activity':clean[:250], 'category':match,'cost_item':'Activity cost','frequency':1,'people':1,'unit_price':0,'source':'Action plan','note':'Quantity and price require review'})
    return out

FINANCIAL_STAGES = {'Original budget', 'Revised estimate', 'Provisional result', 'Audited actual'}
FINANCIAL_METRICS = {'Revenue', 'Expenditure'}

@app.post('/api/financial/import')
async def import_financial_series(file: UploadFile=File(...), _user=Depends(user_from_header)):
    """Validate a tidy annual financial series before a user chooses to save it."""
    data, ext = await read_upload(file)
    if ext not in {'.csv', '.xlsx', '.xlsm'}:
        raise HTTPException(400, 'Financial series must be CSV or Excel')
    try:
        if ext == '.csv':
            rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        else:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            rows = list(wb.active.iter_rows(max_row=2002, max_col=12, values_only=True))
            wb.close()
    except Exception as exc:
        raise HTTPException(422, f'Could not read financial series: {type(exc).__name__}') from exc
    if not rows or len(rows)>2002:
        raise HTTPException(422, 'File must contain a header and at most 2,000 observations')
    headers=[str(v or '').strip().lower().replace(' ','_') for v in rows[0]]
    required={'year','metric','stage','amount','currency','source'}
    if not required.issubset(headers):
        raise HTTPException(422, 'Required columns: year, metric, stage, amount, currency, source; optional: note')
    positions={name:headers.index(name) for name in required | ({'note'} if 'note' in headers else set())}
    accepted=[]; warnings=[]; seen=set(); currencies=set()
    for index,row in enumerate(rows[1:],start=2):
        if not any(v is not None and str(v).strip() for v in row):continue
        def cell(name):
            pos=positions.get(name)
            return str(row[pos] if pos is not None and pos<len(row) and row[pos] is not None else '').strip()
        try:
            year=int(cell('year'))
            amount=Decimal(cell('amount').replace(',',''))
            if not 2000<=year<=2200 or not amount.is_finite() or amount<0:raise ValueError()
        except (ValueError,InvalidOperation):
            warnings.append(f'Row {index}: invalid year or amount; skipped')
            continue
        metric,stage,currency,source=cell('metric'),cell('stage'),cell('currency').upper(),cell('source')
        if metric not in FINANCIAL_METRICS or stage not in FINANCIAL_STAGES or not re.fullmatch(r'[A-Z]{3}',currency) or not source:
            warnings.append(f'Row {index}: invalid metric, stage, currency or source; skipped')
            continue
        key=(year,metric,stage)
        if key in seen:
            warnings.append(f'Row {index}: duplicate {year} {metric} {stage}; skipped')
            continue
        seen.add(key);currencies.add(currency)
        accepted.append({'year':year,'metric':metric,'stage':stage,'amount':float(amount),'currency':currency,'source':source[:200],'note':cell('note')[:500]})
    if len(currencies)>1:warnings.append('Multiple currencies found. Import only rows matching this project currency.')
    for metric in FINANCIAL_METRICS:
        actual_years=sorted(r['year'] for r in accepted if r['metric']==metric and r['stage']=='Audited actual')
        if len(actual_years)>1:
            missing=sorted(set(range(actual_years[0],actual_years[-1]+1))-set(actual_years))
            if missing:warnings.append(f'{metric}: missing audited years {", ".join(map(str,missing))}')
    return {'records':accepted,'warnings':warnings[:100],'total_rows':len(rows)-1}

@app.get('/health')
def health():return {'status':'ok'}

@app.post('/api/plan/import')
async def import_plan(file: UploadFile=File(...)):
    data, ext=await read_upload(file)
    rows=extract(data,ext)
    items=candidates(rows)
    return {'lines':items,'message':f'Found {len(items)} possible activities. Review each one and enter verified prices.','extracted_rows':len(rows),'limitations':'Rules-based extraction; scanned PDFs require OCR and are not supported.'}

@app.post('/api/history/import')
async def import_history(file: UploadFile=File(...)):
    data,ext=await read_upload(file)
    rows=extract(data,ext)
    # Only explicit activity-like rows. Prior spending is context, never silently used as a current rate.
    return {'references':candidates(rows),'extracted_rows':len(rows),'message':'Historical items are reference only. Validate current quantities and prices.'}

def total(line:Line)->Decimal:return line.frequency*line.people*line.unit_price

def safe_cell(value: str) -> str:
    """Prevent spreadsheet programs from interpreting uploaded text as formulas."""
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value

def amount(value) -> Decimal:
    try: return max(Decimal('0'), Decimal(str(value or 0)))
    except (InvalidOperation, ValueError): return Decimal('0')

def display(value) -> str:
    return safe_cell(str(value if value is not None else ''))[:500]

@app.post('/api/budget/export/{format}')
def export_budget(format:Literal['xlsx','pdf','csv'], budget:Budget):
    if format=='csv':
        output=io.StringIO();writer=csv.writer(output)
        writer.writerow(['Activity','Category','Cost item','Frequency','People/units','Unit price','Total','Source','Review note'])
        for x in budget.lines:writer.writerow([safe_cell(x.activity),safe_cell(x.category),safe_cell(x.cost_item),str(x.frequency),str(x.people),str(x.unit_price),str(total(x)),safe_cell(x.source),safe_cell(x.note)])
        writer.writerow(['TOTAL','','','','','',str(sum(map(total,budget.lines),Decimal(0))),'',''])
        return StreamingResponse(iter([output.getvalue().encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="budgetiq-draft.csv"'})
    if format=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb=Workbook(); ws=wb.active;ws.title='Draft budget'
        ws.append(['BudgetIQ AI — Draft budget']);ws.append([safe_cell(budget.organization),budget.year,safe_cell(budget.currency)]);ws.append(['Activity','Category','Cost item','Frequency','People/units','Unit price','Total','Source','Review note'])
        for i,x in enumerate(budget.lines,4):
            ws.append([safe_cell(x.activity),safe_cell(x.category),safe_cell(x.cost_item),float(x.frequency),float(x.people),float(x.unit_price),f'=D{i}*E{i}*F{i}',safe_cell(x.source),safe_cell(x.note)])
        end=3+len(budget.lines);ws.append(['TOTAL',None,None,None,None,None,f'=SUM(G4:G{end})'])
        ws.append(['DRAFT: Confirm rates, quantities, funding sources and approvals before use.'])
        for cell in ws[3]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='172554')
        for col,width in {'A':65,'B':18,'C':22,'D':15,'E':18,'F':18,'G':20,'H':20,'I':48}.items():ws.column_dimensions[col].width=width
        for row in ws.iter_rows(min_row=4,max_row=end,min_col=6,max_col=7):
            for cell in row:cell.number_format='#,##0.00'
        ws.freeze_panes='A4'; b=io.BytesIO();wb.save(b);b.seek(0)
        if budget.activities or budget.revenues or budget.expenses:
            def sheet(name, headers, records):
                tab=wb.create_sheet(name);tab.append(headers)
                for record in records:tab.append([display(v) if isinstance(v,str) else v for v in record])
                for cell in tab[1]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='172554')
                tab.freeze_panes='A2';tab.auto_filter.ref=tab.dimensions
                for col in 'ABCDEFGHIJ':tab.column_dimensions[col].width=23
                tab.column_dimensions['A'].width=42
                return tab
            obj={o.get('id'):o for o in budget.objectives};prog={p.get('id'):p for p in budget.programmes}
            sheet('Objectives',['Objective','Result measure'],[(o.get('title',''),o.get('target','')) for o in budget.objectives])
            sheet('Programmes',['Programme','Objective'],[(p.get('title',''),obj.get(p.get('objectiveId'),{}).get('title','')) for p in budget.programmes])
            details=[]
            for a in budget.activities:
                p=prog.get(a.get('programmeId'),{});o=obj.get(p.get('objectiveId'),{})
                for c in a.get('costs',[]):
                    f=amount(c.get('frequency'));q=amount(c.get('quantity'));price=amount(c.get('unitPrice'))
                    details.append([o.get('title',''),p.get('title',''),a.get('title',''),c.get('category',''),c.get('item',''),float(f),float(q),float(price),float(f*q*price),c.get('fundingSource',''),c.get('evidence',''),a.get('quarter',1)])
            sheet('Detailed costing',['Objective','Programme','Activity','Category','Cost item','Frequency','Quantity','Unit price','Total','Funding source','Rate evidence','Quarter'],details)
            sheet('Funding',['Source','Type','Projected','Received','Quarter'],[(r.get('name',''),r.get('type',''),float(amount(r.get('projected'))),float(amount(r.get('received'))),r.get('quarter',1)) for r in budget.revenues])
            activity_names={a.get('id'):a.get('title','') for a in budget.activities}
            sheet('Execution',['Activity','Description','Quarter','Committed','Paid'],[(activity_names.get(e.get('activityId'),''),e.get('description',''),e.get('quarter',1),float(amount(e.get('committed'))),float(amount(e.get('paid')))) for e in budget.expenses])
            sheet('Results',['Objective','Programme','Activity','Expected','Delivered','Note'],[(obj.get(prog.get(a.get('programmeId'),{}).get('objectiveId'),{}).get('title',''),prog.get(a.get('programmeId'),{}).get('title',''),a.get('title',''),a.get('expectedResult',''),a.get('actualResult',''),a.get('resultNote','')) for a in budget.activities])
            sheet('Review log',['Date','Name (self reported)','Role','Decision','Comment','Plan total'],[(r.get('at',''),r.get('name',''),r.get('role',''),r.get('decision',''),r.get('comment',''),float(amount(r.get('planTotal')))) for r in budget.reviews])
            planned=sum(map(total,budget.lines),Decimal(0));paid=sum((amount(e.get('paid')) for e in budget.expenses),Decimal(0))
            sheet('Summary',['Metric','Value'],[['Organization',budget.organization],['Year',budget.year],['Status (self reported)',budget.status],['Currency',budget.currency],['Full plan',float(planned)],['Ceiling',float(budget.ceiling)],['Funding gap',float(max(Decimal(0),planned-budget.ceiling))],['Projected revenue',float(sum((amount(r.get('projected')) for r in budget.revenues),Decimal(0)))],['Received revenue',float(sum((amount(r.get('received')) for r in budget.revenues),Decimal(0)))],['Paid',float(paid)],['Remaining against plan',float(planned-paid)]])
            b=io.BytesIO();wb.save(b);b.seek(0)
        return StreamingResponse(b,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="budgetiq-draft.xlsx"'})
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
    from xml.sax.saxutils import escape
    b=io.BytesIO();doc=SimpleDocTemplate(b,pagesize=landscape(A4),leftMargin=28,rightMargin=28)
    s=getSampleStyleSheet();content=[Paragraph('BudgetIQ AI — Draft budget',s['Title']),Paragraph(f'{escape(budget.organization)} | {budget.year} | {escape(budget.currency)}',s['Normal']),Spacer(1,12)]
    rows=[['Activity','Category','Cost item','Frequency','People','Unit price','Total']]
    for x in budget.lines:rows.append([Paragraph(escape(x.activity),s['BodyText']),x.category,Paragraph(escape(x.cost_item),s['BodyText']),str(x.frequency),str(x.people),str(x.unit_price),str(total(x))])
    rows.append(['TOTAL','','','','','',str(sum(map(total,budget.lines),Decimal(0)))])
    t=Table(rows,colWidths=[235,90,95,65,60,70,70],repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#172554')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.3,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    planned=sum(map(total,budget.lines),Decimal(0));paid=sum((amount(e.get('paid')) for e in budget.expenses),Decimal(0))
    content.extend([t,Spacer(1,12),Paragraph(f'Ceiling: {budget.currency} {budget.ceiling} | Funding gap: {budget.currency} {max(Decimal(0),planned-budget.ceiling)} | Paid: {budget.currency} {paid}',s['Normal']),Spacer(1,8),Paragraph('DRAFT: Confirm rates, quantities, funding sources and approvals before use. Review decisions in the browser are self reported.',s['Normal'])]);doc.build(content);b.seek(0)
    return StreamingResponse(b,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="budgetiq-draft.pdf"'})
