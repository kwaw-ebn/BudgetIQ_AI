"""BudgetIQ pilot API. Estimates require human review before approval."""
from __future__ import annotations
import csv
import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(title="BudgetIQ AI API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in __import__('os').environ.get('FRONTEND_ORIGIN','http://localhost:5500').split(',')], allow_methods=['GET','POST'], allow_headers=['*'])
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
    content.extend([t,Spacer(1,12),Paragraph('DRAFT: Confirm rates, quantities, funding sources and approvals before use.',s['Normal'])]);doc.build(content);b.seek(0)
    return StreamingResponse(b,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="budgetiq-draft.pdf"'})
