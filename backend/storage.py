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
from sqlalchemy import create_engine, String, Integer, ForeignKey, Text, select, text, inspect
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
    status:Mapped[str]=mapped_column(String(20),default='pending',server_default='pending')
class Organization(Base):
    __tablename__='budgetiq_organizations'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    name:Mapped[str]=mapped_column(String(200))
class OrganizationMember(Base):
    __tablename__='budgetiq_organization_members'
    organization_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_organizations.id'),primary_key=True)
    user_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'),primary_key=True)
    role:Mapped[str]=mapped_column(String(20))
class Project(Base):
    __tablename__='budgetiq_projects'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    owner_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'),index=True)
    name:Mapped[str]=mapped_column(String(200))
    year:Mapped[int]=mapped_column(Integer)
    version:Mapped[int]=mapped_column(Integer,default=1)
    document:Mapped[str]=mapped_column(Text)
    updated_at:Mapped[str]=mapped_column(String(40))
    organization_id:Mapped[str|None]=mapped_column(String(36),ForeignKey('budgetiq_organizations.id'),nullable=True,index=True)
class ProjectMember(Base):
    __tablename__='budgetiq_project_members'
    project_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_projects.id'),primary_key=True)
    user_id:Mapped[str]=mapped_column(String(36),ForeignKey('budgetiq_users.id'),primary_key=True)
    role:Mapped[str]=mapped_column(String(20))

def project_role(session:Session,p:Project,user:User):
    if p.organization_id:
        membership=session.get(OrganizationMember,(p.organization_id,user.id))
        if not membership:return None
        return 'preparer' if membership.role=='admin' else membership.role
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
    organization_id:str|None=None

ADMIN_EMAIL=os.getenv('BUDGETIQ_ADMIN_EMAIL','').strip().lower()
ROLES={'preparer','reviewer','approver','procurement'}
class OrganizationInput(BaseModel):
    name:str=Field(min_length=2,max_length=200)
class MemberInput(BaseModel):
    email:EmailStr
    role:str
class StatusInput(BaseModel):
    status:str

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
    if user.status!='active':raise HTTPException(403,'Account is awaiting approval or has been suspended')
    return user

def require_admin(user:User=Depends(user_from_header)):
    if not ADMIN_EMAIL or user.email!=ADMIN_EMAIL:raise HTTPException(403,'Platform administrator required')
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
    result={'id':p.id,'name':p.name,'year':p.year,'version':p.version,'updated_at':p.updated_at,'organization_id':p.organization_id}
    if include_doc:result['document']=json.loads(p.document)
    return result

@router.post('/auth/register')
def register(body:Credentials,session:Session=Depends(db)):
    email=str(body.email).lower()
    if email==ADMIN_EMAIL:raise HTTPException(403,'Administrator account must already exist before configuration')
    if session.scalar(select(User).where(User.email==email)):raise HTTPException(409,'Account already exists')
    user=User(id=str(uuid4()),email=email,password_hash=hash_password(body.password),status='pending')
    session.add(user);session.commit();return {'status':'pending','message':'Request received. An administrator must approve your account.'}
@router.post('/auth/login')
def login(body:Credentials,session:Session=Depends(db)):
    user=session.scalar(select(User).where(User.email==str(body.email).lower()))
    if not user or not check_password(body.password,user.password_hash):raise HTTPException(401,'Invalid credentials')
    if user.status!='active':raise HTTPException(403,'Account is awaiting approval or has been suspended')
    return {'token':token(user),'email':user.email,'admin':user.email==ADMIN_EMAIL}
@router.get('/auth/me')
def me(user:User=Depends(user_from_header)):return {'email':user.email,'admin':user.email==ADMIN_EMAIL}

@router.get('/admin/users')
def admin_users(admin:User=Depends(require_admin),session:Session=Depends(db)):
    return [{'id':u.id,'email':u.email,'status':u.status} for u in session.scalars(select(User).order_by(User.email)).all()]

@router.put('/admin/users/{user_id}')
def set_user_status(user_id:str,body:StatusInput,admin:User=Depends(require_admin),session:Session=Depends(db)):
    if body.status not in ('active','suspended'):raise HTTPException(422,'Invalid status')
    target=session.get(User,user_id)
    if not target:raise HTTPException(404,'User not found')
    if target.id==admin.id and body.status!='active':raise HTTPException(400,'Cannot suspend your administrator account')
    target.status=body.status;session.commit();return {'id':target.id,'status':target.status}

@router.post('/organizations')
def create_organization(body:OrganizationInput,admin:User=Depends(require_admin),session:Session=Depends(db)):
    org=Organization(id=str(uuid4()),name=body.name.strip())
    session.add(org);session.add(OrganizationMember(organization_id=org.id,user_id=admin.id,role='admin'));session.commit()
    return {'id':org.id,'name':org.name}

@router.get('/organizations')
def organizations(user:User=Depends(user_from_header),session:Session=Depends(db)):
    members=session.scalars(select(OrganizationMember).where(OrganizationMember.user_id==user.id)).all()
    return [{'id':m.organization_id,'name':session.get(Organization,m.organization_id).name,'role':m.role} for m in members]

@router.get('/organizations/{organization_id}/members')
def organization_members(organization_id:str,user:User=Depends(user_from_header),session:Session=Depends(db)):
    m=session.get(OrganizationMember,(organization_id,user.id))
    if not m or m.role!='admin':raise HTTPException(403,'Organization administrator required')
    return [{'email':session.get(User,x.user_id).email,'role':x.role} for x in session.scalars(select(OrganizationMember).where(OrganizationMember.organization_id==organization_id)).all()]

@router.put('/organizations/{organization_id}/members')
def assign_member(organization_id:str,body:MemberInput,user:User=Depends(user_from_header),session:Session=Depends(db)):
    actor=session.get(OrganizationMember,(organization_id,user.id))
    if not actor or actor.role!='admin':raise HTTPException(403,'Organization administrator required')
    if body.role not in ROLES or body.role=='admin':raise HTTPException(422,'Choose a staff role')
    target=session.scalar(select(User).where(User.email==str(body.email).lower()))
    if not target or target.status!='active':raise HTTPException(404,'Approved account not found')
    member=session.get(OrganizationMember,(organization_id,target.id))
    if member:
        if member.role=='admin':raise HTTPException(403,'Administrator role cannot be replaced here')
        member.role=body.role
    else:session.add(OrganizationMember(organization_id=organization_id,user_id=target.id,role=body.role))
    session.commit();return {'email':target.email,'role':body.role}
@router.get('/projects')
def list_projects(user:User=Depends(user_from_header),session:Session=Depends(db)):
    shared=select(ProjectMember.project_id).where(ProjectMember.user_id==user.id)
    orgs=select(OrganizationMember.organization_id).where(OrganizationMember.user_id==user.id)
    return [dict(serialize(p),role=project_role(session,p,user)) for p in session.scalars(select(Project).where((Project.organization_id.in_(orgs))|((Project.organization_id.is_(None))&((Project.owner_id==user.id)|(Project.id.in_(shared))))).order_by(Project.updated_at.desc())).all() if project_role(session,p,user)]
@router.post('/projects')
def create_project(body:ProjectWrite,user:User=Depends(user_from_header),session:Session=Depends(db)):
    if not body.organization_id:raise HTTPException(422,'Choose an organization before creating a budget')
    m=session.get(OrganizationMember,(body.organization_id,user.id))
    if not m or m.role not in ('admin','preparer'):raise HTTPException(403,'Organization preparer role required')
    if len(session.scalars(select(Project).where(Project.organization_id==body.organization_id)).all())>=50:raise HTTPException(400,'50 project limit reached')
    p=Project(id=str(uuid4()),owner_id=user.id,organization_id=body.organization_id,name=body.name,year=body.year,version=1,document=validate_document(body.document),updated_at=datetime.now(timezone.utc).isoformat())
    session.add(p);session.commit();return serialize(p,True)
@router.get('/projects/{project_id}')
def get_project(project_id:str,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p=session.get(Project,project_id)
    role=project_role(session,p,user) if p else None
    if not role:raise HTTPException(404,'Project not found')
    result=dict(serialize(p,True),role=role)
    if role!='preparer':
        original=result['document']
        result['document']={'schema':2,'organization':original.get('organization','Organization'),'year':p.year,'currency':original.get('currency','GHS'),'ceiling':0,'uplift':0,'status':'Restricted view','objectives':[],'programmes':[],'activities':[],'revenues':[],'expenses':[],'reviews':[],'financialRecords':[],'planVersions':[],'revisionEvents':[]}
    return result
@router.put('/projects/{project_id}')
def update_project(project_id:str,body:ProjectWrite,user:User=Depends(user_from_header),session:Session=Depends(db)):
    p=session.get(Project,project_id)
    if not p or project_role(session,p,user)!='preparer':raise HTTPException(404,'Project not found')
    if body.version!=p.version:raise HTTPException(409,'Project changed elsewhere. Reload before saving.')
    from treasury import validate_plan_change
    validate_plan_change(session,p,body.document)
    p.name=body.name;p.year=body.year;p.document=validate_document(body.document);p.version+=1;p.updated_at=datetime.now(timezone.utc).isoformat()
    session.commit();return serialize(p,True)

def init_storage():
    if engine and AUTH_SECRET:
        with engine.begin() as connection:
            # Existing accounts remain active; all new registrations are pending.
            inspector=inspect(connection)
            if inspector.has_table('budgetiq_users') and 'status' not in {c['name'] for c in inspector.get_columns('budgetiq_users')}:
                connection.execute(text("ALTER TABLE budgetiq_users ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
            if inspector.has_table('budgetiq_projects') and 'organization_id' not in {c['name'] for c in inspector.get_columns('budgetiq_projects')}:
                connection.execute(text("ALTER TABLE budgetiq_projects ADD COLUMN organization_id VARCHAR(36)"))
        Base.metadata.create_all(engine)
