"""BudgetIQ treasury-style pilot. No connection to government payment rails."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from storage import Base, Project, ProjectMember, User, db, project_role, user_from_header

router=APIRouter(prefix='/api/projects/{project_id}/treasury',tags=['Treasury pilot'])

class Request(Base):
    __tablename__='budgetiq_treasury_requests'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_projects.id'),index=True)
    creator_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'))
    activity_id:Mapped[str]=mapped_column(String(100))
    description:Mapped[str]=mapped_column(String(300))
    supplier:Mapped[str]=mapped_column(String(200))
    funding_source:Mapped[str]=mapped_column(String(150))
    quarter:Mapped[int]=mapped_column(Integer)
    amount_cents:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(String(30),default='draft')
    invoice_ref:Mapped[str]=mapped_column(String(100),default='')
    payment_ref:Mapped[str]=mapped_column(String(100),default='')
    created_at:Mapped[str]=mapped_column(String(40))

class Event(Base):
    __tablename__='budgetiq_treasury_events'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    request_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_treasury_requests.id'),index=True)
    actor_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'))
    action:Mapped[str]=mapped_column(String(30))
    note:Mapped[str]=mapped_column(String(500))
    at:Mapped[str]=mapped_column(String(40))

class FundingRelease(Base):
    __tablename__='budgetiq_treasury_releases'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_projects.id'),index=True)
    source:Mapped[str]=mapped_column(String(150))
    quarter:Mapped[int]=mapped_column(Integer)
    amount_cents:Mapped[int]=mapped_column(Integer)
    created_by:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'))
    created_at:Mapped[str]=mapped_column(String(40))

class InvoiceMatch(Base):
    __tablename__='budgetiq_treasury_invoice_matches'
    request_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_treasury_requests.id'),primary_key=True)
    invoice_ref:Mapped[str]=mapped_column(String(100))
    delivery_ref:Mapped[str]=mapped_column(String(100))
    amount_cents:Mapped[int]=mapped_column(Integer)

class PaymentRecord(Base):
    __tablename__='budgetiq_treasury_payment_records'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    request_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_treasury_requests.id'),index=True)
    reference:Mapped[str]=mapped_column(String(100))
    amount_cents:Mapped[int]=mapped_column(Integer)
    recorded_at:Mapped[str]=mapped_column(String(40))

class MemberInput(BaseModel):
    email:EmailStr
    role:str=Field(pattern='^(reviewer|approver)$')

class RequestInput(BaseModel):
    activity_id:str=Field(min_length=1,max_length=100)
    description:str=Field(min_length=3,max_length=300)
    supplier:str=Field(default='',max_length=200)
    funding_source:str=Field(min_length=1,max_length=150)
    quarter:int=Field(ge=1,le=4)
    amount:Decimal=Field(gt=0,le=100000000)

class ActionInput(BaseModel):
    action:str=Field(pattern='^(submit|review|approve|reject|commit|invoice|record_payment)$')
    note:str=Field(default='',max_length=500)
    reference:str=Field(default='',max_length=100)
    delivery_reference:str=Field(default='',max_length=100)
    amount:Decimal|None=Field(default=None,gt=0,le=100000000)

class ReleaseInput(BaseModel):
    source:str=Field(min_length=1,max_length=150)
    quarter:int=Field(ge=1,le=4)
    amount:Decimal=Field(gt=0,le=100000000)

def cents(v):
    d=Decimal(str(v))
    if not d.is_finite() or d<=0 or d!=d.quantize(Decimal('.01')):raise HTTPException(422,'Use a positive amount with at most two decimals')
    return int(d*100)

def scope(session,project_id,user,lock=False):
    stmt=select(Project).where(Project.id==project_id)
    p=session.scalar(stmt.with_for_update() if lock else stmt)
    role=project_role(session,p,user) if p else None
    if not role:raise HTTPException(404,'Project not found')
    return p,role

def record(session,r,user,action,note=''):
    session.add(Event(id=str(uuid4()),request_id=r.id,actor_id=user.id,action=action,note=note,at=datetime.now(timezone.utc).isoformat()))

def availability(session,p,exclude=None):
    doc=json.loads(p.document)
    ceiling=cents(doc.get('ceiling',0)) if Decimal(str(doc.get('ceiling',0)))>0 else 0
    activities={a['id']:int(sum(Decimal(str(l.get('frequency',0)))*Decimal(str(l.get('quantity',0)))*Decimal(str(l.get('unitPrice',0))) for l in a.get('costs',[]))*100) for a in doc.get('activities',[])}
    rows=session.scalars(select(Request).where(Request.project_id==p.id)).all()
    reserved=sum(r.amount_cents for r in rows if r.id!=exclude and r.status not in ('draft','rejected'))
    by_activity={key:sum(r.amount_cents for r in rows if r.activity_id==key and r.id!=exclude and r.status not in ('draft','rejected')) for key in activities}
    return ceiling,activities,reserved,by_activity

def check_envelope(session,p,r):
    ceiling,activities,reserved,by_activity=availability(session,p,r.id)
    if not ceiling:raise HTTPException(409,'Set an approved ceiling before submitting a request')
    if r.activity_id not in activities:raise HTTPException(409,'Activity is no longer in the plan')
    if r.amount_cents+reserved>ceiling:raise HTTPException(409,'Request exceeds the remaining budget ceiling')
    if r.amount_cents+by_activity[r.activity_id]>activities[r.activity_id]:raise HTTPException(409,'Request exceeds this activity’s planned cost')
    releases=session.scalars(select(FundingRelease).where(FundingRelease.project_id==p.id,FundingRelease.source==r.funding_source,FundingRelease.quarter==r.quarter)).all()
    released=sum(x.amount_cents for x in releases)
    others=session.scalars(select(Request).where(Request.project_id==p.id,Request.funding_source==r.funding_source,Request.quarter==r.quarter)).all()
    source_reserved=sum(x.amount_cents for x in others if x.id!=r.id and x.status not in ('draft','rejected'))
    if r.amount_cents+source_reserved>released:raise HTTPException(409,'Request exceeds the internal funding release for this source and quarter')

def validate_plan_change(session,p,new_document):
    """Do not let edits erase capacity or references already reserved by requests."""
    rows=session.scalars(select(Request).where(Request.project_id==p.id)).all()
    active=[r for r in rows if r.status not in ('draft','rejected')]
    releases=session.scalars(select(FundingRelease).where(FundingRelease.project_id==p.id)).all()
    if Decimal(str(new_document.get('ceiling',0)))*100<sum(x.amount_cents for x in releases):
        raise HTTPException(409,'Budget ceiling cannot fall below recorded internal funding releases')
    if not active:return
    old=json.loads(p.document)
    if new_document.get('currency')!=old.get('currency') or new_document.get('year')!=old.get('year'):
        raise HTTPException(409,'Currency and year cannot change after a request is submitted')
    ceiling=Decimal(str(new_document.get('ceiling',0)))*100
    if ceiling<sum(r.amount_cents for r in active):raise HTTPException(409,'Budget ceiling cannot fall below reserved requests')
    activities={a.get('id'):a for a in new_document.get('activities',[])}
    for activity_id in {r.activity_id for r in active}:
        if activity_id not in activities:raise HTTPException(409,'An activity with a submitted request cannot be removed')
        planned=sum(Decimal(str(l.get('frequency',0)))*Decimal(str(l.get('quantity',0)))*Decimal(str(l.get('unitPrice',0))) for l in activities[activity_id].get('costs',[]))*100
        if planned<sum(r.amount_cents for r in active if r.activity_id==activity_id):
            raise HTTPException(409,'Activity budget cannot fall below reserved requests')

def view(r):
    return {k:getattr(r,k) for k in ('id','activity_id','description','supplier','funding_source','quarter','status','invoice_ref','payment_ref','created_at')}|{'amount':str(Decimal(r.amount_cents)/100),'creator_id':r.creator_id}

@router.post('/releases')
def add_release(project_id:str,body:ReleaseInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True)
    if role!='preparer':raise HTTPException(403,'Only the project owner can record a funding release')
    source=body.source.strip()
    if not source:raise HTTPException(422,'Enter a funding source')
    ceiling,_,_,_=availability(session,p)
    amount=cents(body.amount)
    existing=session.scalars(select(FundingRelease).where(FundingRelease.project_id==p.id)).all()
    if sum(x.amount_cents for x in existing)+amount>ceiling:raise HTTPException(409,'Total internal releases cannot exceed the project ceiling')
    release=FundingRelease(id=str(uuid4()),project_id=p.id,source=source,quarter=body.quarter,amount_cents=amount,created_by=user.id,created_at=datetime.now(timezone.utc).isoformat())
    session.add(release);session.commit()
    return {'id':release.id,'source':source,'quarter':release.quarter,'amount':str(Decimal(amount)/100)}

@router.get('')
def overview(project_id:str,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user)
    rows=session.scalars(select(Request).where(Request.project_id==p.id).order_by(Request.created_at.desc())).all()
    ceiling,activities,reserved,by_activity=availability(session,p)
    events=session.scalars(select(Event).where(Event.request_id.in_([r.id for r in rows])).order_by(Event.at.desc())).all() if rows else []
    members=session.execute(select(ProjectMember,User.email).join(User,ProjectMember.user_id==User.id).where(ProjectMember.project_id==p.id)).all()
    releases=session.scalars(select(FundingRelease).where(FundingRelease.project_id==p.id).order_by(FundingRelease.created_at.desc())).all()
    matches={m.request_id:m for m in session.scalars(select(InvoiceMatch).where(InvoiceMatch.request_id.in_([r.id for r in rows]))).all()} if rows else {}
    payments=session.scalars(select(PaymentRecord).where(PaymentRecord.request_id.in_([r.id for r in rows]))).all() if rows else []
    payment_by_request={r.id:sum(x.amount_cents for x in payments if x.request_id==r.id) for r in rows}
    requests=[dict(view(r),invoice_amount=str(Decimal(matches[r.id].amount_cents)/100) if r.id in matches else None,delivery_reference=matches[r.id].delivery_ref if r.id in matches else '',paid_amount=str(Decimal(payment_by_request[r.id])/100),outstanding=str(Decimal(matches[r.id].amount_cents-payment_by_request[r.id])/100) if r.id in matches else None) for r in rows]
    return {'role':role,'year':p.year,'currency':json.loads(p.document).get('currency','GHS'),'ceiling':str(Decimal(ceiling)/100),'reserved':str(Decimal(reserved)/100),'available':str(Decimal(ceiling-reserved)/100),'activities':[{'id':a.get('id'),'title':a.get('title'),'planned':str(Decimal(activities[a['id']])/100),'available':str(Decimal(activities[a['id']]-by_activity[a['id']])/100)} for a in json.loads(p.document).get('activities',[]) if a.get('id') in activities],'requests':requests,'events':[{'request_id':e.request_id,'actor_id':e.actor_id,'action':e.action,'note':e.note,'at':e.at} for e in events],'members':[{'email':email,'role':m.role} for m,email in members],'releases':[{'id':x.id,'source':x.source,'quarter':x.quarter,'amount':str(Decimal(x.amount_cents)/100),'at':x.created_at} for x in releases]}

@router.post('/members')
def add_member(project_id:str,body:MemberInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user)
    if p.owner_id!=user.id:raise HTTPException(403,'Only the project owner can assign roles')
    target=session.scalar(select(User).where(User.email==str(body.email).lower()))
    if not target:raise HTTPException(404,'That person must create a BudgetIQ account first')
    if target.id==user.id:raise HTTPException(409,'A separate account is required for review or approval')
    member=session.get(ProjectMember,(p.id,target.id))
    if member:member.role=body.role
    else:session.add(ProjectMember(project_id=p.id,user_id=target.id,role=body.role))
    session.commit()
    return {'email':target.email,'role':body.role}

@router.post('/requests')
def create_request(project_id:str,body:RequestInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True)
    if role!='preparer':raise HTTPException(403,'Only the preparer can create a request')
    _,activities,_,_=availability(session,p)
    if body.activity_id not in activities:raise HTTPException(422,'Choose an activity in the plan')
    r=Request(id=str(uuid4()),project_id=p.id,creator_id=user.id,activity_id=body.activity_id,description=body.description,supplier=body.supplier,funding_source=body.funding_source,quarter=body.quarter,amount_cents=cents(body.amount),status='draft',created_at=datetime.now(timezone.utc).isoformat(),invoice_ref='',payment_ref='')
    session.add(r);record(session,r,user,'draft');session.commit()
    return view(r)

@router.post('/requests/{request_id}/actions')
def transition(project_id:str,request_id:str,body:ActionInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p,role=scope(session,project_id,user,lock=True)
    r=session.get(Request,request_id)
    if not r or r.project_id!=p.id:raise HTTPException(404,'Request not found')
    flow={'submit':('draft','submitted','preparer'),'review':('submitted','reviewed','reviewer'),'approve':('reviewed','approved','approver'),'commit':('approved','committed','preparer'),'invoice':('committed','invoiced','preparer'),'record_payment':('invoiced','payment recorded','preparer')}
    if body.action=='reject':
        if r.status not in ('submitted','reviewed') or role not in ('reviewer','approver'):raise HTTPException(409,'Only a reviewer or approver can reject a submitted request')
        if not body.note.strip():raise HTTPException(422,'Give a reason for rejection')
        next_status='rejected'
    else:
        before,next_status,required=flow[body.action]
        if r.status!=before and not (body.action=='record_payment' and r.status=='partially paid'):raise HTTPException(409,f'Request must be {before} first')
        if role!=required:raise HTTPException(403,f'{required.title()} account required')
    if body.action in ('review','approve','reject') and r.creator_id==user.id:raise HTTPException(403,'The preparer cannot review or approve their own request')
    if body.action=='approve' and session.scalar(select(Event).where(Event.request_id==r.id,Event.action=='review',Event.actor_id==user.id)):
        raise HTTPException(403,'A separate approver must approve the reviewed request')
    if body.action in ('submit','review','approve','commit'):check_envelope(session,p,r)
    if body.action in ('invoice','record_payment'):
        if not body.reference.strip():raise HTTPException(422,'Enter the invoice or payment reference')
        if body.amount is None:raise HTTPException(422,'Enter the invoice or payment amount')
    if body.action=='invoice':
        if not body.delivery_reference.strip():raise HTTPException(422,'Enter a goods receipt or service completion reference')
        value=cents(body.amount)
        if value>r.amount_cents:raise HTTPException(409,'Invoice cannot exceed the recorded commitment')
        if session.scalar(select(InvoiceMatch).where(InvoiceMatch.request_id==r.id)):raise HTTPException(409,'Invoice already matched')
        session.add(InvoiceMatch(request_id=r.id,invoice_ref=body.reference.strip(),delivery_ref=body.delivery_reference.strip(),amount_cents=value))
        r.invoice_ref=body.reference.strip()
    if body.action=='record_payment':
        match=session.get(InvoiceMatch,r.id)
        if not match:raise HTTPException(409,'Record and match an invoice first')
        value=cents(body.amount)
        payments=session.scalars(select(PaymentRecord).where(PaymentRecord.request_id==r.id)).all()
        if sum(x.amount_cents for x in payments)+value>match.amount_cents:raise HTTPException(409,'Payments cannot exceed the matched invoice')
        if session.scalar(select(PaymentRecord).join(Request,PaymentRecord.request_id==Request.id).where(Request.project_id==p.id,PaymentRecord.reference==body.reference.strip())):
            raise HTTPException(409,'Payment reference already used in this project')
        session.add(PaymentRecord(id=str(uuid4()),request_id=r.id,reference=body.reference.strip(),amount_cents=value,recorded_at=datetime.now(timezone.utc).isoformat()))
        if sum(x.amount_cents for x in payments)+value<match.amount_cents:next_status='partially paid'
        r.payment_ref=body.reference.strip()
    r.status=next_status;record(session,r,user,body.action,body.note.strip());session.commit()
    return view(r)
