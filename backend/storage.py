"""Authenticated, organization-scoped project storage. Requires DATABASE_URL and AUTH_SECRET."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, String, Integer, ForeignKey, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

router=APIRouter(prefix='/api')
DB_URL=os.getenv('DATABASE_URL','')
AUTH_SECRET=os.getenv('AUTH_SECRET','')
engine=None
if DB_URL:
    url=DB_URL.replace('postgres://','postgresql+psycopg://',1).replace('postgresql://','postgresql+psycopg://',1)
    engine=create_engine(url,pool_pre_ping=True,pool_size=3,max_overflow=2)

class Base(DeclarativeBase):pass
class User(Base):
    __tablename__='budgetiq_users'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    email:Mapped[str]=mapped_column(String(255),unique=True,index=True)
    password_hash:Mapped[str]=mapped_column(String(300))
class Project(Base):
    __tablename__='budgetiq_projects'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    owner_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'),index=True)
    name:Mapped[str]=mapped_column(String(200))
    year:Mapped[int]=mapped_column(Integer)
    version:Mapped[int]=mapped_column(Integer,default=1)
    document:Mapped[str]=mapped_column(Text)
    updated_at:Mapped[str]=mapped_column(String(40))
class ProjectMember(Base):
    __tablename__='budgetiq_project_members'
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_projects.id'),primary_key=True)
    user_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'),primary_key=True)
    role:Mapped[str]=mapped_column(String(20))

def project_role(session:Session,p:Project,user:User):
    if p.owner_id==user.id:return 'preparer'
    member=session.get(ProjectMember,(p.id,user.id))
    return member.role if member else None

class Credentials(BaseModel):
    email:EmailStr
    password:str=Field(min_length=12,max_length=128)
class ProjectWrite(BaseModel):
    name:str=Field(min_length=1,max_length=200)
    year:int=Field(ge=2000,le=2200)
    document:dict
    version:int|None=None

def db():
    if engine is None or not AUTH_SECRET:raise HTTPException(503,'Server storage is not configured')
    with Session(engine) as session:yield session

def token(user:User):return URLSafeTimedSerializer(AUTH_SECRET,salt='budgetiq-auth-v1').dumps(user.id)
def user_from_header(authorization:str=Header(default=''),session:Session=Depends(db)):
    if not authorization.startswith('Bearer '):raise HTTPException(401,'Sign in required')
    try:user_id=URLSafeTimedSerializer(AUTH_SECRET,salt='budgetiq-auth-v1').loads(authorization[7:],max_age=60*60*24)
    except (BadSignature,SignatureExpired):raise HTTPException(401,'Session expired')
    user=session.get(User,user_id)
    if not user:raise HTTPException(401,'Sign in required')
    return user

def hash_password(password:str,salt:bytes|None=None):
    salt=salt or secrets.token_bytes(16)
    return salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,390000).hex()
def check_password(password:str,stored:str):
    try:salt,digest=stored.split(':');return hmac.compare_digest(hash_password(password,bytes.fromhex(salt)).split(':')[1],digest)
    except (ValueError,TypeError):return False

def validate_document(document:dict):
    if len(json.dumps(document))>1_000_000:raise HTTPException(413,'Project exceeds 1 MB')
    if document.get('schema')!=2 or not all(isinstance(document.get(k),list) for k in ('objectives','programmes','activities','revenues','expenses','reviews')):raise HTTPException(422,'Invalid project document')
    return json.dumps(document,separators=(',',':'))

def serialize(p:Project,include_doc=False):
    result={'id':p.id,'name':p.name,'year':p.year,'version':p.version,'updated_at':p.updated_at}
    if include_doc:result['document']=json.loads(p.document)
    return result

@router.post('/auth/register')
def register(body:Credentials,session:Session=Depends(db)):
    email=str(body.email).lower()
    if session.scalar(select(User).where(User.email==email)):raise HTTPException(409,'Account already exists')
    user=User(id=str(uuid4()),email=email,password_hash=hash_password(body.password))
    session.add(user);session.commit();return {'token':token(user),'email':email}
@router.post('/auth/login')
def login(body:Credentials,session:Session=Depends(db)):
    user=session.scalar(select(User).where(User.email==str(body.email).lower()))
    if not user or not check_password(body.password,user.password_hash):raise HTTPException(401,'Invalid credentials')
    return {'token':token(user),'email':user.email}
@router.get('/auth/me')
def me(user:User=Depends(user_from_header)):return {'email':user.email}
@router.get('/projects')
def list_projects(user:User=Depends(user_from_header),session:Session=Depends(db)):
    shared=select(ProjectMember.project_id).where(ProjectMember.user_id==user.id)
    return [dict(serialize(p),role=project_role(session,p,user)) for p in session.scalars(select(Project).where((Project.owner_id==user.id)|(Project.id.in_(shared))).order_by(Project.updated_at.desc())).all()]
@router.post('/projects')
def create_project(body:ProjectWrite,user:User=Depends(user_from_header),session:Session=Depends(db)):
    if len(session.scalars(select(Project).where(Project.owner_id==user.id)).all())>=50:raise HTTPException(400,'50 project limit reached')
    p=Project(id=str(uuid4()),owner_id=user.id,name=body.name,year=body.year,version=1,document=validate_document(body.document),updated_at=datetime.now(timezone.utc).isoformat())
    session.add(p);session.commit();return serialize(p,True)
@router.get('/projects/{project_id}')
def get_project(project_id:str,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p=session.get(Project,project_id)
    if not p or not project_role(session,p,user):raise HTTPException(404,'Project not found')
    return dict(serialize(p,True),role=project_role(session,p,user))
@router.put('/projects/{project_id}')
def update_project(project_id:str,body:ProjectWrite,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p=session.get(Project,project_id)
    if not p or p.owner_id!=user.id:raise HTTPException(404,'Project not found')
    if body.version!=p.version:raise HTTPException(409,'Project changed elsewhere. Reload before saving.')
    from treasury import validate_plan_change
    validate_plan_change(session,p,body.document)
    p.name=body.name;p.year=body.year;p.document=validate_document(body.document);p.version+=1;p.updated_at=datetime.now(timezone.utc).isoformat()
    session.commit();return serialize(p,True)

def init_storage():
    if engine and AUTH_SECRET:Base.metadata.create_all(engine)
