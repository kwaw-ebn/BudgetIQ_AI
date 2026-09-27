"""Internal procurement comparison pilot; not a tender, contract or purchase order."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from storage import Base, ProjectMember, User, db, user_from_header
from treasury import Request, cents, scope, availability, record as treasury_record

router=APIRouter(prefix='/api/projects/{project_id}/procurement',tags=['Procurement pilot'])

class Case(Base):
    __tablename__='budgetiq_procurement_cases'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_projects.id'),index=True)
    activity_id:Mapped[str]=mapped_column(String(100))
    title:Mapped[str]=mapped_column(String(250))
    method:Mapped[str]=mapped_column(String(50))
    reason:Mapped[str]=mapped_column(Text)
    funding_source:Mapped[str]=mapped_column(String(150))
    quarter:Mapped[int]=mapped_column(Integer)
    estimated_cents:Mapped[int]=mapped_column(Integer)
    external_reference:Mapped[str]=mapped_column(String(120),default='')
    status:Mapped[str]=mapped_column(String(30),default='draft')
    recommended_quote_id:Mapped[str]=mapped_column(String(36),default='')
    recommendation:Mapped[str]=mapped_column(Text,default='')
    evaluator_id:Mapped[str]=mapped_column(String(36),default='')
    created_by:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'))
    created_at:Mapped[str]=mapped_column(String(40))

class Quote(Base):
    __tablename__='budgetiq_procurement_quotes'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    case_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_procurement_cases.id'),index=True)
    supplier:Mapped[str]=mapped_column(String(200))
    reference:Mapped[str]=mapped_column(String(120))
    price_cents:Mapped[int]=mapped_column(Integer)
    responsive:Mapped[int]=mapped_column(Integer)
    technical_score:Mapped[int]=mapped_column(Integer)
    note:Mapped[str]=mapped_column(Text)
    entered_by:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'))
    created_at:Mapped[str]=mapped_column(String(40))

class ProcurementEvent(Base):
    __tablename__='budgetiq_procurement_events'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    case_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_procurement_cases.id'),index=True)
    actor_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'))
    action:Mapped[str]=mapped_column(String(35))
    note:Mapped[str]=mapped_column(String(500))
    at:Mapped[str]=mapped_column(String(40))

class Handoff(Base):
    __tablename__='budgetiq_procurement_handoffs'
    case_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_procurement_cases.id'),primary_key=True)
    request_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_treasury_requests.id'),unique=True)

class MemberInput(BaseModel):
    email:EmailStr
class CaseInput(BaseModel):
    activity_id:str=Field(min_length=1,max_length=100)
    title:str=Field(min_length=3,max_length=250)
    method:str=Field(pattern='^(Request for quotations|Open tender|Restricted tender|Direct sourcing|Other)$')
    reason:str=Field(min_length=10,max_length=1000)
    funding_source:str=Field(min_length=1,max_length=150)
    quarter:int=Field(ge=1,le=4)
    estimate:Decimal=Field(gt=0,le=100000000)
    external_reference:str=Field(default='',max_length=120)
class QuoteInput(BaseModel):
    supplier:str=Field(min_length=2,max_length=200)
    reference:str=Field(min_length=1,max_length=120)
    price:Decimal=Field(gt=0,le=100000000)
    responsive:bool
    technical_score:int=Field(ge=0,le=100)
    note:str=Field(default='',max_length=1000)
class RecommendInput(BaseModel):
    quote_id:str
    rationale:str=Field(min_length=15,max_length=1500)
    no_conflict:bool
    single_offer_reason:str=Field(default='',max_length=500)
class DecisionInput(BaseModel):
    decision:str=Field(pattern='^(approve|return)$')
    note:str=Field(min_length=5,max_length=500)

def now():return datetime.now(timezone.utc).isoformat()
def event(session,c,user,action,note=''):
    session.add(ProcurementEvent(id=str(uuid4()),case_id=c.id,actor_id=user.id,action=action,note=note[:500],at=now()))
def require_case(session,p,case_id):
    c=session.get(Case,case_id)
    if not c or c.project_id!=p.id:raise HTTPException(404,'Procurement case not found')
    return c
def view(c,quotes,handoff):
    return {'id':c.id,'activity_id':c.activity_id,'title':c.title,'method':c.method,'reason':c.reason,'funding_source':c.funding_source,'quarter':c.quarter,'estimate':str(Decimal(c.estimated_cents)/100),'external_reference':c.external_reference,'status':c.status,'recommended_quote_id':c.recommended_quote_id,'recommendation':c.recommendation,'treasury_request_id':handoff.request_id if handoff else None,'quotes':[{'id':q.id,'supplier':q.supplier,'reference':q.reference,'price':str(Decimal(q.price_cents)/100),'responsive':bool(q.responsive),'technical_score':q.technical_score,'note':q.note} for q in quotes]}

@router.get('')
def overview(project_id:str,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user)
    if role not in ('preparer','procurement','approver'):raise HTTPException(404,'Project not found')
    cases=session.scalars(select(Case).where(Case.project_id==p.id).order_by(Case.created_at.desc())).all()
    ids=[c.id for c in cases]
    quotes=session.scalars(select(Quote).where(Quote.case_id.in_(ids))).all() if ids else []
    handoffs=session.scalars(select(Handoff).where(Handoff.case_id.in_(ids))).all() if ids else []
    events=session.scalars(select(ProcurementEvent).where(ProcurementEvent.case_id.in_(ids)).order_by(ProcurementEvent.at.desc())).all() if ids else []
    _,activities,_,_=availability(session,p)
    members=session.execute(select(ProjectMember,User.email).join(User,ProjectMember.user_id==User.id).where(ProjectMember.project_id==p.id,ProjectMember.role=='procurement')).all()
    return {'role':role,'currency':json.loads(p.document).get('currency','GHS'),'activities':[{'id':a.get('id'),'title':a.get('title'),'planned':str(Decimal(activities[a['id']])/100)} for a in json.loads(p.document).get('activities',[]) if a.get('id') in activities],'cases':[view(c,[q for q in quotes if q.case_id==c.id],next((h for h in handoffs if h.case_id==c.id),None)) for c in cases],'events':[{'case_id':e.case_id,'action':e.action,'note':e.note,'at':e.at} for e in events],'procurement_members':[email for _,email in members]}

@router.post('/members')
def assign_procurement(project_id:str,body:MemberInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user)
    if p.organization_id:raise HTTPException(409,'Assign staff in organization access settings')
    if role!='preparer':raise HTTPException(403,'Only the project owner can assign procurement staff')
    target=session.scalar(select(User).where(User.email==str(body.email).lower()))
    if not target or target.status!='active':raise HTTPException(404,'Approved account not found')
    if target.id==user.id:raise HTTPException(409,'Use a separate account for procurement evaluation')
    member=session.get(ProjectMember,(p.id,target.id))
    if member:member.role='procurement'
    else:session.add(ProjectMember(project_id=p.id,user_id=target.id,role='procurement'))
    session.commit()
    return {'email':target.email,'role':'procurement'}

@router.post('/cases')
def create_case(project_id:str,body:CaseInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True)
    if role!='preparer':raise HTTPException(403,'Only the project owner can plan procurement')
    ceiling,activities,_,_=availability(session,p)
    if body.activity_id not in activities:raise HTTPException(422,'Choose a planned activity')
    estimate=cents(body.estimate)
    if not ceiling or estimate>ceiling or estimate>activities[body.activity_id]:raise HTTPException(409,'Estimate exceeds the project ceiling or activity plan')
    c=Case(id=str(uuid4()),project_id=p.id,activity_id=body.activity_id,title=body.title.strip(),method=body.method,reason=body.reason.strip(),funding_source=body.funding_source.strip(),quarter=body.quarter,estimated_cents=estimate,external_reference=body.external_reference.strip(),status='draft',recommended_quote_id='',recommendation='',evaluator_id='',created_by=user.id,created_at=now())
    session.add(c);event(session,c,user,'case created',body.method);session.commit()
    return {'id':c.id,'status':c.status}

@router.post('/cases/{case_id}/quotes')
def add_quote(project_id:str,case_id:str,body:QuoteInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True);c=require_case(session,p,case_id)
    if role!='procurement':raise HTTPException(403,'Procurement staff account required')
    if c.status not in ('draft','quotations'):raise HTTPException(409,'Comparison is closed')
    existing=session.scalars(select(Quote).where(Quote.case_id==c.id)).all()
    if any(q.supplier.casefold()==body.supplier.strip().casefold() for q in existing):raise HTTPException(409,'Supplier already entered for this case')
    if len(existing)>=30:raise HTTPException(409,'30 quote limit reached')
    q=Quote(id=str(uuid4()),case_id=c.id,supplier=body.supplier.strip(),reference=body.reference.strip(),price_cents=cents(body.price),responsive=int(body.responsive),technical_score=body.technical_score,note=body.note.strip(),entered_by=user.id,created_at=now())
    session.add(q);c.status='quotations';event(session,c,user,'quote added',q.reference);session.commit()
    return {'id':q.id,'status':c.status}

@router.post('/cases/{case_id}/recommend')
def recommend(project_id:str,case_id:str,body:RecommendInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True);c=require_case(session,p,case_id)
    if role!='procurement':raise HTTPException(403,'Procurement staff account required')
    if c.status!='quotations':raise HTTPException(409,'Add quotations before recommendation')
    if not body.no_conflict:raise HTTPException(409,'A different evaluator is required when a conflict is declared')
    quotes=session.scalars(select(Quote).where(Quote.case_id==c.id)).all()
    q=next((x for x in quotes if x.id==body.quote_id),None)
    if not q or not q.responsive:raise HTTPException(409,'Select a responsive quote in this case')
    if len(quotes)==1 and len(body.single_offer_reason.strip())<10:raise HTTPException(422,'Explain why only one offer is available')
    if q.price_cents>c.estimated_cents:raise HTTPException(409,'Selected price exceeds the procurement estimate; revise the plan first')
    c.recommended_quote_id=q.id;c.evaluator_id=user.id;c.recommendation=body.rationale.strip();c.status='recommended'
    event(session,c,user,'recommended',body.rationale.strip());session.commit()
    return {'status':c.status}

@router.post('/cases/{case_id}/decision')
def decide(project_id:str,case_id:str,body:DecisionInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True);c=require_case(session,p,case_id)
    if role!='approver':raise HTTPException(403,'Separate approver account required')
    if c.status!='recommended':raise HTTPException(409,'Case must be recommended first')
    if c.evaluator_id==user.id:raise HTTPException(403,'Evaluator cannot approve their own recommendation')
    c.status='approved' if body.decision=='approve' else 'quotations'
    if body.decision=='return':c.recommended_quote_id='';c.recommendation='';c.evaluator_id=''
    event(session,c,user,body.decision,body.note.strip());session.commit()
    return {'status':c.status}

@router.post('/cases/{case_id}/treasury-draft')
def handoff(project_id:str,case_id:str,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True);c=require_case(session,p,case_id)
    if role!='preparer':raise HTTPException(403,'Only the project owner can prepare a Treasury request')
    if c.status!='approved':raise HTTPException(409,'Internal recommendation must be approved')
    if session.get(Handoff,c.id):raise HTTPException(409,'A Treasury draft already exists')
    q=session.get(Quote,c.recommended_quote_id)
    _,activities,_,_=availability(session,p)
    if not q or c.activity_id not in activities or q.price_cents>activities[c.activity_id]:raise HTTPException(409,'Activity plan no longer covers selected quote')
    r=Request(id=str(uuid4()),project_id=p.id,creator_id=user.id,activity_id=c.activity_id,description=c.title[:300],supplier=q.supplier,funding_source=c.funding_source,quarter=c.quarter,amount_cents=q.price_cents,status='draft',invoice_ref='',payment_ref='',created_at=now())
    session.add(r);session.add(Handoff(case_id=c.id,request_id=r.id));treasury_record(session,r,user,'draft','Linked procurement comparison '+c.id)
    event(session,c,user,'treasury draft created',r.id);session.commit()
    return {'request_id':r.id,'status':'draft'}
