"""
Power on Plus Solar Solutions — Flask Web Application
=====================================================
Run:  python app.py
Deps: pip install flask flask-sqlalchemy flask-login flask-migrate pymysql
"""

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date,timezone
from decimal import Decimal
import os

from flask import send_file
import tempfile,calendar 

DCR_SUBSIDY_AMOUNT=78000
# DOCUMENT_STAGES = [
#     {
#         'name':'Customer KYC',
#         'condition':'always',
#         'docs':['ID Proof','Pass Book','Electricity Bill']
#     },
#     {
#         'name':'Bank / Loan file',
#          'condition':'loan',
#          'docs':['GEO Tag Photo','Bank Stamp Paper','Bank File']
#     },
#     {
#         'name':'Feasibility',
#         'condition':'always',
#         'docs':['Feasibility Receipt']
#     },
#     {
#         'name':'KSEB filing',
#         'condition':'always',
#         'docs':['KSEB Stamp Paper','B-Class Licence','KSEB File']
#     },
#     {
#         'name':'Inspection & connection',
#         'condition':'always',
#         'docs':['Inspection','CD Payment Receipt','KSEB Connection']
#     },
#     {
#         'name':'Subsidy',
#         'condition':'always',
#         'docs':['Subsidy Request','Subsidy Redeem']
#     },
#     {
#         'name':'Project closure',
#         'condition':'always',
#         'docs':['Payment Completion','Warranty Card','App Installation']
#     },
# ]
PROJECT_STAGES=[
    'Lead',
    'Site Visit',
    'Documentation',
    'Onsite Work',
    'Connection',
    'Subsidy',
    'Payment',
]
STAGE_STATUS_MAP={
    'Lead':'Lead',
    'Site Visit':'InProgress',
    'Documentation':'InProgress',
    'Onsite Work':'InProgress',
    'Connection':'InProgress',
    'Subsidy':'InProgress',
    'Payment':'InProgress',
}
def get_document_stages():
    """Return active document stages ordered by sort_order."""
    return DocumentStage.query.filter_by(is_active=True).order_by(DocumentStage.sort_order).all()

def get_expected_docs(project_type, project_subtype=None,loan_subtype=None):
    """Return full list of expected document names for a project."""
    docs = []
    for stage in get_document_stages():
        if stage.condition == 'always':
            docs.extend(stage.doc_list)
        elif stage.condition == 'loan' and project_type == 'Loan':
            docs.extend(stage.doc_list)
        elif stage.condition == 'loan_self' and project_type == 'Loan' and loan_subtype !='Assisted':
            docs.extend(stage.doc_list)
        elif stage.condition == 'dcr' and project_subtype == 'DCR':
            docs.extend(stage.doc_list)
    return docs

def get_doc_completion(project):
    expected   = get_expected_docs(project.project_type, project.project_subtype,project.loan_subtype)
    recorded   = {d.doc_type: d for d in project.documents}
    done_count = sum(
        1 for doc_name in expected
        if doc_name in recorded and recorded[doc_name].status in ['Received', 'Sent', 'Completed']
    )
    return done_count, len(expected)
# def get_expected_docs(project_type):
#     """Return full list of expected document names for a project type."""
#     docs = []
#     for stage in DOCUMENT_STAGES:
#         if stage['condition'] == 'always' or project_type == 'Loan':
#             docs.extend(stage['docs'])
#     return docs


# def get_doc_completion(project):
#     """
#     Returns (done, total) based on expected docs for the project type,
#     not just what has been recorded.
#     """
#     expected   = get_expected_docs(project.project_type)
#     recorded   = {d.doc_type: d for d in project.documents}
#     done_count = sum(
#         1 for doc_name in expected
#         if doc_name in recorded and recorded[doc_name].status in ['Received', 'Sent','Completed']
#     )
#     return done_count, len(expected)
# ─────────────────────────────────────────────────────────────────────────────
# APP CONFIG
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'solar-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:Panattayil%4012345@localhost/solar_app'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# ─────────────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(80),  unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(255), nullable=False)
    full_name  = db.Column(db.String(120), nullable=False)
    role       = db.Column(db.Enum('admin','coordinator','documents','payments','onsite','appinstall'), nullable=False)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status=db.Column(db.String(20),nullable=False,default='active')

    def set_password(self, raw):
        self.password = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password, raw)


class Customer(db.Model):
    __tablename__ = 'customers'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    phone      = db.Column(db.String(20))
    email      = db.Column(db.String(120))
    address    = db.Column(db.Text)
    district   = db.Column(db.String(80))
    pincode    = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    projects   = db.relationship('Project', backref='customer', lazy=True)


class Project(db.Model):
    __tablename__ = 'projects'
    id               = db.Column(db.Integer, primary_key=True)
    project_code     = db.Column(db.String(20), unique=True, nullable=False)
    customer_id      = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    inverter_capacity_kw = db.Column(db.Numeric(6, 2), nullable=False)
    panel_capacity_kw = db.Column(db.Numeric(6, 2), nullable=False)
    project_type     = db.Column(db.Enum('Loan', 'Cash'), nullable=False)
    status           = db.Column(db.Enum('Lead','Created','InProgress','Completed','Delayed','Pending','Closed','OnHold','Cancelled'), default='Lead')
    stage            = db.Column(db.String(100), default='Lead')
    total_amount     = db.Column(db.Numeric(12, 2), default=0)
    collected_amount = db.Column(db.Numeric(12, 2), default=0)
    coordinator_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    doc_staff_id     = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    staged_changed_at = db.Column(db.DateTime,default=datetime.utcnow)
    project_subtype=db.Column(db.Enum('DCR','Non-DCR'),nullable=True)
    coordinator = db.relationship('User', foreign_keys=[coordinator_id], backref='coordinated_projects')
    doc_staff   = db.relationship('User', foreign_keys=[doc_staff_id],   backref='doc_projects')
    payments    = db.relationship('Payment',        backref='project', lazy=True)
    documents   = db.relationship('Document',       backref='project', lazy=True)
    logs        = db.relationship('ProjectLog',     backref='project', lazy=True)
    materials   = db.relationship('Material',       backref='project', lazy=True)
    assignments = db.relationship('WorkerAssignment', backref='project', lazy=True)
    loan_subtype=db.Column(db.Enum('Assisted','Self'),nullable=True)


    @property
    def contract_amount(self):
        """The base contract amount entered at project creation."""
        return float(self.total_amount or 0)

    @property
    def company_paid_expenses(self):
        """Expenses paid by company that need to be recovered from customer."""
        return [e for e in self.expenses if e.paid_by == 'Company' ]

    @property
    def company_expense_total(self):
        return sum(float(e.amount) for e in self.company_paid_expenses)

    @property
    def total_receivable(self):
        """Contract amount + any company-paid expenses to be recovered."""
        return self.contract_amount + self.company_expense_total
    @property
    def recovered_expense_total(self):
        """Company-paid expenses that have been recovered from customer."""
        return sum(float(e.amount) for e in self.company_paid_expenses if e.recovered)

    
    @property
    def pending_amount(self):
        sub_customer_share = 0
        if self.subsidy and self.subsidy.customer_share and self.subsidy.status == 'Received':
            sub_customer_share = float(self.subsidy.customer_share)
        return max(0, self.total_receivable - self.effective_collected - sub_customer_share)
    @property
    def effective_collected(self):
        """Cash collected from customer + recovered company expenses."""
        company_share = 0
        if self.subsidy and self.subsidy.company_share and self.subsidy.status == 'Received':
            company_share = float(self.subsidy.company_share)
        return float(self.collected_amount or 0) + self.recovered_expense_total + company_share
    @property
    def payment_pct(self):
        t = self.total_receivable
        if t == 0:
            return 0
        return min(100, int(self.effective_collected / t * 100))

    @property
    def days_open(self):
        if self.status in ('Closed', 'Completed', 'Cancelled'):
            end = (self.updated_at or datetime.utcnow()).date()
        else:
            end = datetime.utcnow().date()
        return (end - self.created_at.date()).days
    @property
    def days_in_stage(self):
        if self.status in ('Closed', 'Completed', 'Cancelled'):
            end = (self.updated_at or datetime.utcnow()).replace(tzinfo=None)
        else:
            end = datetime.now(timezone.utc).replace(tzinfo=None)
        ref = self.staged_changed_at or self.updated_at or self.created_at
        if ref is None:
            return 0
        return (end - ref).days
    # @property
    # def net_amount(self):
    #     sub_received = float(self.subsidy.received_amount) if self.subsidy and self.subsidy.received_amount else 0
    #     return float(self.total_amount or 0)-sub_received
    # @property
    # def net_pending(self):
    #     return max(0, self.net_amount - float(self.collected_amount or 0))
    
    @property
    def bank_instalments(self):
        """Returns dict of which bank installments are recorded for loan projects"""
        pays=[p for p in self.payments if p.payment_source == 'Bank']
        return {p.instalment:p for p in pays}
    
    @property
    def next_bank_instalment(self):
        done=self.bank_instalments
        if 'First' not in done:
            return 'First'
        if 'Second' not in done:
            return 'Second'
        return None


class Document(db.Model):
    __tablename__ = 'documents'
    id            = db.Column(db.Integer, primary_key=True)
    project_id    = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    doc_type      = db.Column(db.String(80), nullable=False)
    status        = db.Column(db.Enum('Pending','Received','Sent','Completed'), default='Pending')
    received_date = db.Column(db.Date)
    notes         = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    __tablename__ = 'payments'
    id           = db.Column(db.Integer, primary_key=True)
    project_id   = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    amount       = db.Column(db.Numeric(12, 2), nullable=False)
    payment_type = db.Column(db.Enum('Cash','Bank','Cheque','Online'), nullable=False)
    payment_source=db.Column(db.Enum('Customer','Bank'),nullable=False,default='Customer')
    instalment=db.Column(db.Enum('Full','First','Second'),nullable=True)
    payment_date = db.Column(db.Date, nullable=False)
    reference_no = db.Column(db.String(80))
    received_by  = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes        = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)


class Worker(db.Model):
    __tablename__ = 'workers'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    phone        = db.Column(db.String(20))
    skill        = db.Column(db.String(80))
    rate_per_day = db.Column(db.Numeric(8, 2), default=0)
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    assignments  = db.relationship('WorkerAssignment', backref='worker', lazy=True)
    weekly_payments=db.relationship('WorkerWeeklyPayment',back_populates='worker',order_by='WorkerWeeklyPayment.week_start.desc()')

weekly_pay_project=db.Table(
        'weekly_pay_project',
        db.Column('payment_id',db.Integer,db.ForeignKey('worker_weekly_payment.id'),primary_key=True),
        db.Column('project_id',db.Integer,db.ForeignKey('projects.id'),primary_key=True),
    )
class WorkerAssignment(db.Model):
    __tablename__ = 'worker_assignments'
    id          = db.Column(db.Integer, primary_key=True)
    project_id  = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    worker_id   = db.Column(db.Integer, db.ForeignKey('workers.id'),  nullable=False)
    start_date  = db.Column(db.Date)
    end_date    = db.Column(db.Date)
    days_worked = db.Column(db.Integer, default=0)
    work_phase=db.Column(db.Enum('Structure','Installation','Electrical'),default='Structure')
    status      = db.Column(db.Enum('Assigned','Active','Completed','Paid'), default='Assigned')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    
# class WorkerPayment(db.Model):
#     __tablename__ = 'worker_payments'
#     id            = db.Column(db.Integer, primary_key=True)
#     assignment_id = db.Column(db.Integer, db.ForeignKey('worker_assignments.id'), nullable=False)
#     project_id    = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
#     week_start    = db.Column(db.Date, nullable=False)
#     week_end      = db.Column(db.Date, nullable=False)
#     days_worked   = db.Column(db.Integer, default=0)
#     rate_per_day  = db.Column(db.Numeric(8, 2), default=0)
#     amount        = db.Column(db.Numeric(10, 2), nullable=False)
#     paid_date     = db.Column(db.Date, nullable=False)
#     paid_by       = db.Column(db.Integer, db.ForeignKey('users.id'))
#     notes         = db.Column(db.Text)
#     created_at    = db.Column(db.DateTime, default=datetime.utcnow)
#     project       = db.relationship('Project', foreign_keys=[project_id])
#     payer         = db.relationship('User', foreign_keys=[paid_by])

class WorkerWeeklyPayment(db.Model):
    __tablename__='worker_weekly_payment'
    __table_args__ = (
        db.UniqueConstraint('worker_id','week_start',name='uq_worker_week'),
    )
    id = db.Column(db.Integer, primary_key=True)
    worker_id    = db.Column(db.Integer, db.ForeignKey('workers.id'), nullable=False)
    week_start   = db.Column(db.Date, nullable=False)
    week_end     = db.Column(db.Date, nullable=False)
    days_worked  = db.Column(db.Numeric(4, 1), nullable=False)
    rate_per_day = db.Column(db.Numeric(10, 2), nullable=False)
    amount       = db.Column(db.Numeric(10, 2), nullable=False)
    paid_date    = db.Column(db.Date, nullable=False)
    payer_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes        = db.Column(db.String(300), nullable=True)

    projects=db.relationship('Project',secondary='weekly_pay_project',lazy='select')
    worker=db.relationship('Worker',back_populates='weekly_payments')
    payer=db.relationship('User',foreign_keys=[payer_id])
    
class KSEBTask(db.Model):
    __tablename__ = 'kseb_tasks'
    id              = db.Column(db.Integer, primary_key=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('projects.id'), unique=True, nullable=False)
    stamp_paper     = db.Column(db.Enum('Pending','Requested','Received'), default='Pending')
    b_class_licence = db.Column(db.Enum('Pending','Requested','Received'), default='Pending')
    file_sent       = db.Column(db.Boolean, default=False)
    file_sent_date  = db.Column(db.Date)
    inspection_date = db.Column(db.Date)
    inspection_done = db.Column(db.Boolean, default=False)
    cd_payment_done = db.Column(db.Boolean, default=False)
    cd_payment_date = db.Column(db.Date)
    connection_date = db.Column(db.Date)
    connection_done = db.Column(db.Boolean, default=False)
    meter_available = db.Column(db.Boolean, default=True)
    ae_completed    = db.Column(db.Boolean, default=False)
    notes           = db.Column(db.Text)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    project         = db.relationship('Project', backref=db.backref('kseb_task', uselist=False))


class Subsidy(db.Model):
    __tablename__ = 'subsidy'
    id              = db.Column(db.Integer, primary_key=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('projects.id'), unique=True, nullable=False)
    request_date    = db.Column(db.Date)
    expected_amount = db.Column(db.Numeric(10, 2), default=0)
    received_amount = db.Column(db.Numeric(10, 2), default=0)
    customer_share = db.Column(db.Numeric(10, 2), default=0)
    company_share = db.Column(db.Numeric(10, 2), default=0)
    status          = db.Column(db.Enum('NotStarted','Processing','Commissioned','Redeemed','Received'), default='NotStarted')
    notes           = db.Column(db.Text)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    project         = db.relationship('Project', backref=db.backref('subsidy', uselist=False))


class AppInstallation(db.Model):
    __tablename__ = 'app_installations'
    id             = db.Column(db.Integer, primary_key=True)
    project_id     = db.Column(db.Integer, db.ForeignKey('projects.id'), unique=True, nullable=False)
    scheduled_date = db.Column(db.Date)
    completed_date = db.Column(db.Date)
    installed_by   = db.Column(db.Integer, db.ForeignKey('users.id'))
    status         = db.Column(db.Enum('Pending','Scheduled','Completed'), default='Pending')
    notes          = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    project        = db.relationship('Project', backref=db.backref('app_install', uselist=False))


class SiteVisit(db.Model):
    __tablename__ = 'site_visits'
    id             = db.Column(db.Integer, primary_key=True)
    project_id     = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    scheduled_date = db.Column(db.Date)
    visited_date   = db.Column(db.Date)
    conducted_by   = db.Column(db.Integer, db.ForeignKey('users.id'))
    observations   = db.Column(db.Text)
    status         = db.Column(db.Enum('Scheduled','Completed','Cancelled'), default='Scheduled')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    project        = db.relationship('Project', backref='site_visits')


class ProjectLog(db.Model):
    __tablename__ = 'project_logs'
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    action     = db.Column(db.String(200), nullable=False)
    old_value  = db.Column(db.String(100))
    new_value  = db.Column(db.String(100))
    done_by    = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship('User', foreign_keys=[done_by])


class Material(db.Model):
    __tablename__ = 'materials'
    id              = db.Column(db.Integer, primary_key=True)
    project_id      = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    item_name       = db.Column(db.String(100), nullable=False)
    quantity        = db.Column(db.Numeric(8, 2))
    unit            = db.Column(db.String(20))
    dispatch_status = db.Column(db.Enum('Pending','Dispatched','Delivered'), default='Pending')
    dispatch_date   = db.Column(db.Date)
    received_date   = db.Column(db.Date)
    notes           = db.Column(db.Text)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    message    = db.Column(db.String(255), nullable=False)
    notif_type = db.Column(db.String(80), default='info')   # 'task', 'info', 'warning'
    is_read    = db.Column(db.Boolean, default=False)
    action_url = db.Column(db.String(255),nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship('User', foreign_keys=[user_id])
    project    = db.relationship('Project', foreign_keys=[project_id])

class OnsiteProgress(db.Model):
    __tablename__ = 'onsite_progress'
    id                    = db.Column(db.Integer, primary_key=True)
    project_id            = db.Column(db.Integer, db.ForeignKey('projects.id'), unique=True, nullable=False)
    structure_work_status = db.Column(db.Enum('NotStarted','InProgress','Completed'), default='NotStarted')
    structure_start_date  = db.Column(db.Date)
    structure_end_date    = db.Column(db.Date)
    structure_notes       = db.Column(db.Text)
    installation_status   = db.Column(db.Enum('NotStarted','InProgress','Completed'), default='NotStarted')
    installation_start_date=db.Column(db.Date)
    installation_end_date=db.Column(db.Date)
    installation_notes    = db.Column(db.Text)
    electrical_status=db.Column(db.Enum('NotStarted','InProgress','Completed'),default='NotStarted')
    electrical_start_date=db.Column(db.Date)
    electrical_end_date=db.Column(db.Date)
    electrical_notes=db.Column(db.Text)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by            = db.Column(db.Integer, db.ForeignKey('users.id'))
    project               = db.relationship('Project', backref=db.backref('onsite_progress', uselist=False))
class OnsiteLog(db.Model):
    __tablename__ = 'onsite_logs'
    id         = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    log_date   = db.Column(db.Date, nullable=False, default=date.today)
    work_phase = db.Column(db.Enum('Structure','Installation','Electrical'), nullable=False)
    note       = db.Column(db.String(500), nullable=False)
    logged_by  = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    project    = db.relationship('Project', backref='onsite_logs')
    logger     = db.relationship('User', foreign_keys=[logged_by])
class JobCard(db.Model):
    __tablename__ = 'job_cards'
    id           = db.Column(db.Integer, primary_key=True)
    project_id   = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    worker_id    = db.Column(db.Integer, db.ForeignKey('workers.id'),  nullable=False)
    work_phase   = db.Column(db.Enum('Structure','Installation','Electrical'), nullable=False)
    description  = db.Column(db.String(300))

    # Financials — agreed upfront or computed at close
    agreed_amount   = db.Column(db.Numeric(10,2), nullable=True)  # lump sum, or null = rate×days
    actual_days     = db.Column(db.Numeric(4,1),  nullable=True)
    rate_per_day    = db.Column(db.Numeric(10,2), nullable=True)
    final_amount    = db.Column(db.Numeric(10,2), nullable=True)  # set on approval

    status       = db.Column(
        db.Enum('Open','PendingApproval','Approved','Paid','Voided'),
        default='Open'
    )

    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at    = db.Column(db.DateTime, nullable=True)    # when onsite marks done
    approved_at  = db.Column(db.DateTime, nullable=True)    # when admin/payments approves
    approved_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    closed_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    project      = db.relationship('Project', backref='job_cards')
    worker       = db.relationship('Worker',  backref='job_cards')
    approver     = db.relationship('User', foreign_keys=[approved_by])
    closer       = db.relationship('User', foreign_keys=[closed_by])


class WorkerAdvance(db.Model):
    __tablename__ = 'worker_advances'
    id                = db.Column(db.Integer, primary_key=True)
    worker_id         = db.Column(db.Integer, db.ForeignKey('workers.id'), nullable=False)
    project_id        = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True)
    amount            = db.Column(db.Numeric(10,2), nullable=False)
    given_date        = db.Column(db.Date, nullable=False)
    given_by          = db.Column(db.Integer, db.ForeignKey('users.id'))
    recovered_amount  = db.Column(db.Numeric(10,2), default=0)
    status            = db.Column(
        db.Enum('Outstanding','PartiallyRecovered','Cleared'),
        default='Outstanding'
    )
    notes             = db.Column(db.String(300))
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    worker  = db.relationship('Worker',  backref='advances')
    giver   = db.relationship('User',    foreign_keys=[given_by])
    project = db.relationship('Project', backref='worker_advances')


class WorkerLedger(db.Model):
    __tablename__ = 'worker_ledger'
    id             = db.Column(db.Integer, primary_key=True)
    worker_id      = db.Column(db.Integer, db.ForeignKey('workers.id'), nullable=False)
    entry_date     = db.Column(db.Date, nullable=False)
    entry_type     = db.Column(
        db.Enum('Earning','Advance','Deduction','Settlement','Bonus'),
        nullable=False
    )
    amount         = db.Column(db.Numeric(10,2), nullable=False)  # always positive
    direction      = db.Column(db.Enum('Credit','Debit'), nullable=False)
    # Credit = owed to worker (Earning, Bonus)
    # Debit  = reduces balance  (Advance, Deduction, Settlement)
    reference_type = db.Column(db.String(40))   # 'JobCard', 'Advance', 'Manual'
    reference_id   = db.Column(db.Integer)
    notes          = db.Column(db.String(300))
    balance_after  = db.Column(db.Numeric(10,2))  # running balance
    recorded_by    = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    worker    = db.relationship('Worker', backref='ledger_entries')
    recorder  = db.relationship('User',   foreign_keys=[recorded_by])

class ProjectExpense(db.Model):
    __tablename__ = 'project_expenses'
    id           = db.Column(db.Integer, primary_key=True)
    project_id   = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    expense_type = db.Column(db.Enum('CD Payment', 'Net Meter'), nullable=False)
    amount       = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    paid_by      = db.Column(db.Enum('Customer', 'Company'), nullable=False, default='Customer')
    paid_date    = db.Column(db.Date, nullable=True)
    recovered    = db.Column(db.Boolean, default=False)
    recovered_date = db.Column(db.Date, nullable=True)
    notes        = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    recorded_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    project  = db.relationship('Project', backref='expenses')
    recorder = db.relationship('User', foreign_keys=[recorded_by])
class DocumentStage(db.Model):
    __tablename__ = 'document_stages'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    condition  = db.Column(db.Enum('always', 'loan','loan_self', 'dcr'), nullable=False, default='always')
    docs       = db.Column(db.Text, nullable=False)   # comma-separated doc names
    sort_order = db.Column(db.Integer, default=0)
    is_active  = db.Column(db.Boolean, default=True)

    @property
    def doc_list(self):
        return [d.strip() for d in self.docs.split(',') if d.strip()]
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def roles_required(*roles):
    """Decorator: restrict route to specific roles."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def log_action(project_id, action, old_val=None, new_val=None):
    from datetime import timedelta
    cutoff=datetime.utcnow() - timedelta(seconds=5)
    duplicate = ProjectLog.query.filter_by(
        project_id=project_id,
        action=action,
        old_value=str(old_val) if old_val else None,
        new_value=str(new_val) if new_val else None,
        done_by=current_user.id,
    ).filter(ProjectLog.created_at>=cutoff).first()
    if duplicate:
        return
    entry = ProjectLog(
        project_id=project_id,
        action=action,
        old_value=str(old_val) if old_val else None,
        new_value=str(new_val) if new_val else None,
        done_by=current_user.id
    )
    db.session.add(entry)


def auto_advance_stage(proj):
    """
    Advance stage + status based on current project data.
    Fires notifications to the next responsible team on each transition.
    """
    if proj.status in ('Cancelled', 'OnHold', 'Completed', 'Closed'):
        return
 
    db.session.expire(proj, ['documents', 'site_visits', 'onsite_progress',
                              'app_install', 'subsidy', 'assignments'])
 
    old_stage  = proj.stage
    old_status = proj.status
 
    doc_map = {d.doc_type: d for d in proj.documents}
 
    def doc_done(*names):
        return all(
            doc_map.get(n) and doc_map[n].status in ('Received', 'Sent', 'Completed')
            for n in names
        )
 
    if proj.stage == 'Lead':
        if proj.site_visits:
            proj.stage  = 'Site Visit'
            proj.status = 'InProgress'
        else:
            proj.status = 'Lead'
 
    elif proj.stage == 'Site Visit':
        completed_visits = [v for v in proj.site_visits if v.status == 'Completed']
        if completed_visits:
            proj.stage  = 'Documentation'
            proj.status = 'InProgress'
 
    elif proj.stage == 'Documentation':
        if doc_done('Feasibility Receipt'):
            proj.stage  = 'Onsite Work'
            proj.status = 'InProgress'
 
    elif proj.stage == 'Onsite Work':
        op = proj.onsite_progress
        if op and op.electrical_status == 'Completed':
            proj.stage  = 'Connection'
            proj.status = 'InProgress'
 
    elif proj.stage == 'Connection':
        if doc_done('KSEB Connection'):
            proj.stage  = 'Payment'
            proj.status = 'InProgress'

    elif proj.stage == 'Payment':
        sub = proj.subsidy
        if proj.project_subtype == 'DCR':
        # For DCR: payment must be collected AND subsidy redeemed before closing
            fully_paid = (
            proj.total_amount and float(proj.total_amount) > 0
            and float(proj.collected_amount or 0) >= float(proj.total_amount)
        )
            app_done = proj.app_install and proj.app_install.status == 'Completed'
            if fully_paid and app_done:
                proj.stage  = 'Subsidy'
                proj.status = 'InProgress'
        else:
        # Non-DCR: just payment + app install
            fully_paid = (
            proj.total_amount and float(proj.total_amount) > 0
            and float(proj.collected_amount or 0) >= float(proj.total_amount)
        )
        app_done = proj.app_install and proj.app_install.status == 'Completed'
        if fully_paid and app_done:
            proj.status = 'Completed'

    elif proj.stage == 'Subsidy':
    # Only DCR projects reach here
        sub = proj.subsidy
        if sub and sub.status == 'Redeemed':
            proj.status = 'Completed'
 
    if proj.stage != old_stage or proj.status != old_status:
        # Update stage timestamp
        proj.stage_changed_at = datetime.utcnow()
 
        log_action(
            proj.id,
            f'Auto-advanced: {old_stage} → {proj.stage}',
            old_val=old_status,
            new_val=proj.status,
        )
 
        # ── Notify next responsible team ──────────────────────────────────
        _notify_stage_transition(proj, old_stage, proj.stage)
 
 
def _notify_stage_transition(proj, from_stage, to_stage):
    """Send notifications to the team responsible for the new stage."""
    code = f'{proj.project_code} — {proj.customer.name}'
 
    if to_stage == 'Site Visit':
        pass
        # Notify coordinator
        # if proj.coordinator_id:
        #     create_notification(
        #         proj.coordinator_id, proj.id,
        #         f'{code}: Site visit scheduled. Please confirm the visit date.',
        #         'task'
        #     )
 
    elif to_stage == 'Documentation':
        # Notify doc staff
        if proj.doc_staff_id:
            create_notification(
                proj.doc_staff_id, proj.id,
                f'{code}: Site visit completed. Documentation work can now begin.',
                'task'
            )
 
    elif to_stage == 'Onsite Work':
        # Notify onsite team
        # notify_onsite_team(
        #     proj.id,
        #     f'{code}: Documentation ready. Feasibility approved — onsite work can begin.',
        #     'task'
        # )
        # Also notify coordinator
        if proj.coordinator_id:
            create_notification(
                proj.coordinator_id, proj.id,
                f'{code} moved to Onsite Work stage.',
                'info'
            )
 
    elif to_stage == 'Connection':
        # Notify coordinator and doc staff about KSEB connection needed
        if proj.coordinator_id:
            create_notification(
                proj.coordinator_id, proj.id,
                f'{code}: Onsite work complete. KSEB connection step now active.',
                'info'
            )
        if proj.doc_staff_id:
            create_notification(
                proj.doc_staff_id, proj.id,
                f'{code}: Electrical work done. Please update KSEB Connection document.',
                'task'
            )
 
    
 
    elif to_stage == 'Payment':
        # Notify coordinator and payments
        if proj.coordinator_id:
            create_notification(
                proj.coordinator_id, proj.id,
                f'{code}: KSEB connection done. Ready for final payment collection.',
                'info'
            )
        payments_users = User.query.filter_by(role='payments', is_active=True).all()
        
        for u in payments_users:
            create_notification(
                u.id, proj.id,
                f'{code}:KSEB connection completed.Entered Payment stage. Collect remaining balance of '
                f'₹{float(proj.total_amount or 0) - float(proj.collected_amount or 0):,.0f}.',
                'task'
            )
        if proj.doc_staff_id:
            create_notification(
            proj.doc_staff_id, proj.id,
            f'{code}: Project in final payment stage. Please ensure Payment Completion, Warranty Card and App Installation documents are updated.',
            'task'
        )
        
    elif to_stage == 'Subsidy':
        # Notify payments team
        payments_users = User.query.filter_by(role='payments', is_active=True).all()
        for u in payments_users:
            create_notification(
                u.id, proj.id,
                f'{code}: Payment collected. Please initiate subsidy redemption process. '
                'task'
            )
        if proj.coordinator_id:
            create_notification(
            proj.coordinator_id, proj.id,
            f'{code}: Payment complete. Subsidy redemption now in progress.',
            'info'
        )
        if proj.doc_staff_id:
            create_notification(
            proj.doc_staff_id, proj.id,
            f'{code}: Payment collected. Please update Subsidy Request and Subsidy Redeem documents.',
            'task'
        )
def create_notification(user_id,project_id,message,notif_type='info'):
    notif=Notification(
        user_id = user_id,
        project_id=project_id,
        message=message,
        notif_type=notif_type,
    )
    db.session.add(notif)
def notify_onsite_team(project_id,message,notif_type='task'):
    onsite_users=User.query.filter_by(role='onsite',is_active=True).all()
    for user in onsite_users:
        create_notification(user.id,project_id,message,notif_type)
def next_project_code():
    from sqlalchemy import func
    all_codes=db.session.query(Project.project_code).all()
    numeric=[]
    for(code,) in all_codes:
        try:
            numeric.append(int(code))
        except (ValueError,TypeError):
            pass
    return str(max(numeric)+1)if numeric else None


# ─────────────────────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if not u or not u.check_password(request.form['password']):
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('login'))

        if u.status != 'active':
            flash('Your account is not active. Contact admin.', 'danger')
            return redirect(url_for('login'))

        login_user(u)
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/admin/document_stages')
@login_required
@roles_required('admin')
def manage_document_stages():
    stages = DocumentStage.query.order_by(DocumentStage.sort_order).all()
    return render_template('admin_document_stages.html', stages=stages)


@app.route('/admin/document_stages/new', methods=['POST'])
@login_required
@roles_required('admin')
def new_document_stage():
    last = DocumentStage.query.order_by(DocumentStage.sort_order.desc()).first()
    stage = DocumentStage(
        name       = request.form['name'].strip(),
        condition  = request.form.get('condition', 'always'),
        docs       = request.form['docs'].strip(),
        sort_order = (last.sort_order + 1) if last else 0,
        is_active  = True,
    )
    db.session.add(stage)
    db.session.commit()
    flash(f'Stage "{stage.name}" created.', 'success')
    return redirect(url_for('manage_document_stages'))


@app.route('/admin/document_stages/<int:sid>/edit', methods=['POST'])
@login_required
@roles_required('admin')
def edit_document_stage(sid):
    stage = DocumentStage.query.get_or_404(sid)
    stage.name      = request.form['name'].strip()
    stage.condition = request.form.get('condition', stage.condition)
    stage.docs      = request.form['docs'].strip()
    stage.is_active = 'is_active' in request.form
    db.session.commit()
    flash(f'Stage "{stage.name}" updated.', 'success')
    return redirect(url_for('manage_document_stages'))


@app.route('/admin/document_stages/<int:sid>/delete', methods=['POST'])
@login_required
@roles_required('admin')
def delete_document_stage(sid):
    stage = DocumentStage.query.get_or_404(sid)
    stage.is_active = False   # soft delete
    db.session.commit()
    flash(f'Stage "{stage.name}" deactivated.', 'warning')
    return redirect(url_for('manage_document_stages'))


@app.route('/admin/document_stages/reorder', methods=['POST'])
@login_required
@roles_required('admin')
def reorder_document_stages():
    order = request.form.getlist('order')   # list of stage IDs in new order
    for i, sid in enumerate(order):
        stage = DocumentStage.query.get(int(sid))
        if stage:
            stage.sort_order = i
    db.session.commit()
    return jsonify({'ok': True})
@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    stale  = Project.query.filter(
        Project.status == 'InProgress',
        Project.created_at <= cutoff,
    ).all()
    if stale:
        for proj in stale:
            proj.status = 'Delayed'
        db.session.commit()
    role = current_user.role
    data = {}

    if role == 'admin':
        data['total']     = Project.query.count()
        data['inprog']    = Project.query.filter_by(status='InProgress').count()
        data['completed'] = Project.query.filter(Project.status.in_(['Completed','Closed'])).count()
        data['onhold']  = Project.query.filter_by(status='OnHold').count()
        data['cancelled'] = Project.query.filter_by(status='Cancelled').count()
        data['delayed']   = Project.query.filter_by(status='Delayed').count()
        data['projects']  = Project.query.order_by(Project.updated_at.desc()).paginate(page=request.args.get('page',1,type=int),per_page=15,error_out=False)
        active_project_ids = db.session.query(Project.id).filter(
            Project.status.notin_(['Cancelled', 'OnHold'])
        ).subquery()
        payments          = db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.project_id.in_(active_project_ids)
        ).scalar() or 0
        data['collected'] = float(payments)
        total_amt         = db.session.query(db.func.sum(Project.total_amount)).filter(
            Project.status.notin_(['Cancelled', 'OnHold'])
        ).scalar() or 0
        data['total_amt'] = float(total_amt)

    elif role == 'coordinator':
        my_projects=Project.query.filter_by(coordinator_id=current_user.id).order_by(Project.updated_at.desc()).all()
        my_project_ids=[p.id for p in my_projects]
        total_value = sum(float(p.total_amount or 0) for p in my_projects if p.status not in ['Cancelled','OnHold'])
        total_collected=sum(float(p.collected_amount or 0) for p in my_projects if p.status not in ['Cancelled','OnHold'])
        total_pending = total_value - total_collected
        subsidy_list=Subsidy.query.filter(Subsidy.project_id.in_(my_project_ids)).all() if my_project_ids else []
        subsidy_pending = sum(float(s.expected_amount or 0) - float(s.received_amount or 0) for s in subsidy_list)
        subsidy_received=sum(float(s.received_amount or 0) for s in subsidy_list)
        data['projects']  = Project.query.filter_by(coordinator_id=current_user.id).order_by(Project.updated_at.desc()).all()
        data['pending']   = Project.query.filter(Project.status.in_(['Lead','Created'])).count()
        data['site_visits'] = SiteVisit.query.filter_by(status='Scheduled').all()
        data['delayed']   = Project.query.filter_by(status='Delayed').count()
        data['total_value'] = total_value
        data['total_collected']=total_collected
        data['total_pending']=total_pending
        data['subsidy_pending']=subsidy_pending
        data['subsidy_received']=subsidy_received
        data['subsidy_list']=subsidy_list

    elif role == 'documents':
        all_my_projects = Project.query.filter_by(doc_staff_id=current_user.id).order_by(Project.updated_at.desc()).all()
        my_projects = [p for p in all_my_projects if p.status not in ['Cancelled', 'OnHold']]
        new_projects = [p for p in my_projects if p.status == 'InProgress' and len(p.documents) == 0]
        completed_projects = [p for p in my_projects if p.status in ['Completed', 'Closed']]
        projects_with_counts = []
        for p in my_projects:
            done, total = get_doc_completion(p)
            projects_with_counts.append({
            'project':   p,
            'done_docs': done,
            'total_docs': total,
            'doc_pct':   int(done / total * 100) if total > 0 else 0,
        })
        page=request.args.get('page',1,type=int)
        per_page=20
        total=len(projects_with_counts)
        start=(page -1)*per_page
        end=start+per_page
        from flask_sqlalchemy import pagination
        data['pagination']=None
        data['page']=page
        data['per_page']=per_page
        data['total_projects']=total
        data['projects_with_counts']=projects_with_counts[start:end]
        data['total_pages']=(total+per_page -1) // per_page
        notifications = Notification.query.filter_by(
        user_id  = current_user.id,
        is_read  = False,
    ).order_by(Notification.created_at.desc()).all()
        data['projects']  = my_projects
        data['projects_with_counts']=projects_with_counts
        data['queue']     = len(data['projects'])
        data['new_projects'] = new_projects
        data['new_count']=len(new_projects)
        data['completed_projects']=completed_projects
        data['completed_count']=len(completed_projects)
        data['notifications']=notifications

    elif role == 'payments':
        active_project_ids = db.session.query(Project.id).filter(
            Project.status.notin_(['Cancelled', 'OnHold'])
        ).subquery()
        data['total_collected'] = float(db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.project_id.in_(active_project_ids)
        ).scalar() or 0)
        total_amt               = float(db.session.query(db.func.sum(Project.total_amount)).filter(
            Project.status.notin_(['Cancelled', 'OnHold'])
        ).scalar() or 0)
        data['total_pending']   = total_amt - data['total_collected']
        data['projects']        = Project.query.filter(Project.status.notin_(['Closed', 'Cancelled', 'OnHold'])).paginate(page=request.args.get('page',1,type=int),per_page=20,error_out=False)

    elif role == 'onsite':
        feasibility_project_ids=db.session.query(Document.project_id).filter(
            Document.doc_type == 'Feasibility Receipt',
            Document.status.in_(['Received', 'Completed']),
        ).subquery()
        completed_onsite_ids=db.session.query(OnsiteProgress.project_id).filter(
            OnsiteProgress.electrical_status == 'Completed'
        ).subquery()
        data['projects']  = Project.query.filter(Project.status.in_(['InProgress','Delayed']),Project.id.in_(feasibility_project_ids),Project.id.notin_(completed_onsite_ids),).all()
        data['workers']   = Worker.query.filter_by(is_active=True).all()
        data['tasks'] = Notification.query.filter_by(
            user_id = current_user.id,
            notif_type='task',
            is_read=False,
        ).order_by(Notification.created_at.desc()).all()

    elif role == 'appinstall':
        pending=AppInstallation.query.filter_by(status='Pending').all()
        scheduled=AppInstallation.query.filter_by(status='Scheduled').all()
        completed_count=AppInstallation.query.filter_by(status='Completed').count()
        data['installs']  = pending
        data['scheduled']=scheduled
        data['pending_count']=len(pending)
        data['scheduled_count']=len(scheduled)
        data['completed'] = completed_count

    return render_template('dashboard.html', data=data)


# ─────────────────────────────────────────────────────────────────────────────
# PROJECTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/projects')
@login_required
def projects():
    status_filter = request.args.get('status', '')
    search        = request.args.get('q', '')
    page=request.args.get('page',1,type=int)
    per_page = 15
    q = Project.query.join(Customer)
    if current_user.role=='coordinator':
        q=q.filter(Project.coordinator_id==current_user.id)
    if status_filter:
        q = q.filter(Project.status == status_filter)
    if search:
        q = q.filter(Customer.name.ilike(f'%{search}%') | Project.project_code.ilike(f'%{search}%'))
    pagination = q.order_by(Project.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    projects_list = pagination.items
    return render_template('projects.html', projects=projects_list,pagination=pagination,
                           status_filter=status_filter, search=search)


@app.route('/projects/new', methods=['GET', 'POST'])
@login_required
@roles_required('coordinator')
def new_project():
    customers   = Customer.query.order_by(Customer.name).all()
    
    doc_staff   = User.query.filter_by(role='documents',    is_active=True).all()
    suggested_code=next_project_code()

    if request.method == 'POST':
        code=request.form['project_code'].strip()
        if Project.query.filter_by(project_code=code).first():
            flash(f'MNRE number {code} is already registered.','danger')
            return render_template('new_project.html',customers=customers,doc_staff=doc_staff,suggested_code=suggested_code)
        # Check or create customer
        cust_id = request.form.get('customer_id')
        if not cust_id:
            cust = Customer(
                name     = request.form['customer_name'],
                phone    = request.form.get('phone'),
                email    = request.form.get('email'),
                address  = request.form.get('address'),
                district = request.form.get('district'),
                pincode  = request.form.get('pincode'),
            )
            db.session.add(cust)
            db.session.flush()
            cust_id = cust.id

        proj = Project(
            project_code   = code,
            customer_id    = cust_id,
            inverter_capacity_kw = float(request.form['inverter_capacity_kw']),
            panel_capacity_kw = float(request.form['panel_capacity_kw']),
            project_type   = request.form['project_type'],
            status         = 'Lead',
            stage          = 'Lead',
            project_subtype=request.form.get('project_subtype') or None,
            loan_subtype = request.form.get('loan_subtype') or None,
            total_amount   = float(request.form.get('total_amount', 0)),
            coordinator_id = current_user.id,
            doc_staff_id   = request.form.get('doc_staff_id') or None,
            notes          = request.form.get('notes'),
        )
        db.session.add(proj)
        db.session.flush()
        log_action(proj.id, 'Project created', new_val='Created')
        if proj.doc_staff_id:
            create_notification(
                user_id= proj.doc_staff_id,
                project_id=proj.id,
                message=f'You have been assigned to {proj.project_code}-{proj.customer.name}({proj.project_type},{proj.inverter_capacity_kw} kW).',
                notif_type='task',
            )
        db.session.commit()
        flash(f'Project {proj.project_code} created successfully!', 'success')
        return redirect(url_for('project_detail', pid=proj.id))

    return render_template('new_project.html', customers=customers,
                            doc_staff=doc_staff,suggested_code=suggested_code)
@app.route('/projects/<int:pid>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'coordinator', 'documents')
def edit_project(pid):
    proj = Project.query.get_or_404(pid)

    if current_user.role == 'coordinator' and proj.coordinator_id != current_user.id:
        flash('You can only edit your own projects.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    if current_user.role == 'documents' and proj.doc_staff_id != current_user.id:
        flash('You can only edit projects assigned to you.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    if proj.status in ('Cancelled', 'Closed') and current_user.role != 'admin':
        flash('Cancelled or closed projects cannot be edited.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    doc_staff    = User.query.filter_by(role='documents',    is_active=True).all()
    coordinators = User.query.filter_by(role='coordinator',  is_active=True).all()

    if request.method == 'POST':
        old_type     = proj.project_type
        old_subtype  = proj.project_subtype
        old_loan_sub = proj.loan_subtype
        old_amount   = float(proj.total_amount or 0)

        new_type     = request.form['project_type']
        new_subtype  = request.form.get('project_subtype') or None
        new_loan_sub = request.form.get('loan_subtype') or None
        new_amount   = float(request.form.get('total_amount') or 0)

        proj.inverter_capacity_kw = float(request.form['inverter_capacity_kw'])
        proj.panel_capacity_kw    = float(request.form['panel_capacity_kw'])
        proj.project_type         = new_type
        proj.project_subtype      = new_subtype
        proj.loan_subtype         = new_loan_sub
        proj.total_amount         = new_amount
        proj.notes                = request.form.get('notes', '').strip()

        changes = []

        # ── Admin-only fields ────────────────────────────────────────────────
        if current_user.role == 'admin':
            # MNRE number
            new_code = request.form.get('project_code', '').strip()
            if new_code and new_code != proj.project_code:
                if Project.query.filter(
                    Project.project_code == new_code, Project.id != pid
                ).first():
                    flash('That MNRE number is already in use.', 'danger')
                    return redirect(url_for('edit_project', pid=pid))
                changes.append(f'MNRE: {proj.project_code} → {new_code}')
                proj.project_code = new_code

            # Customer fields
            proj.customer.name     = request.form.get('customer_name',     proj.customer.name).strip()
            proj.customer.phone    = request.form.get('customer_phone',    proj.customer.phone or '').strip() or None
            proj.customer.email    = request.form.get('customer_email',    proj.customer.email or '').strip() or None
            proj.customer.district = request.form.get('customer_district', proj.customer.district or '').strip() or None
            proj.customer.pincode  = request.form.get('customer_pincode',  proj.customer.pincode or '').strip() or None
            proj.customer.address  = request.form.get('customer_address',  proj.customer.address or '').strip() or None

            # Stage and status override
            new_stage  = request.form.get('stage')
            new_status = request.form.get('status')
            if new_stage and new_stage != proj.stage:
                changes.append(f'Stage: {proj.stage} → {new_stage}')
                proj.stage = new_stage
                proj.staged_changed_at = datetime.utcnow()
            if new_status and new_status != proj.status:
                changes.append(f'Status: {proj.status} → {new_status}')
                proj.status = new_status

            # Coordinator reassignment
            new_coord_id = request.form.get('coordinator_id') or None
            if new_coord_id:
                new_coord_id = int(new_coord_id)
                if proj.coordinator_id != new_coord_id:
                    old_coord = proj.coordinator
                    new_coord = User.query.get(new_coord_id)
                    if old_coord:
                        create_notification(
                            old_coord.id, pid,
                            f'You have been unassigned as coordinator from '
                            f'{proj.project_code} — {proj.customer.name}.',
                            'info'
                        )
                    if new_coord:
                        create_notification(
                            new_coord_id, pid,
                            f'You have been assigned as coordinator for '
                            f'{proj.project_code} — {proj.customer.name}.',
                            'task'
                        )
                    changes.append(
                        f'Coordinator: {old_coord.full_name if old_coord else "None"} → '
                        f'{new_coord.full_name if new_coord else "None"}'
                    )
                    proj.coordinator_id = new_coord_id
            else:
                proj.coordinator_id = None

        # ── Re-open payment if amount increased ──────────────────────────────
        if new_amount > float(proj.collected_amount or 0):
            if proj.status == 'Completed' and proj.stage == 'Payment':
                proj.status = 'InProgress'

        # ── Doc staff reassignment ───────────────────────────────────────────
        new_staff_id = request.form.get('doc_staff_id') or None
        if new_staff_id:
            new_staff_id = int(new_staff_id)
            old_staff    = proj.doc_staff
            if old_staff and old_staff.id != new_staff_id:
                create_notification(
                    old_staff.id, pid,
                    f'You have been unassigned from {proj.project_code} — {proj.customer.name}.',
                    'info'
                )
            if proj.doc_staff_id != new_staff_id:
                new_staff = User.query.get(new_staff_id)
                create_notification(
                    new_staff_id, pid,
                    f'You have been assigned to {proj.project_code} — {proj.customer.name} '
                    f'({proj.project_type}, {proj.inverter_capacity_kw} kW).',
                    'task'
                )
            proj.doc_staff_id = new_staff_id
        else:
            proj.doc_staff_id = None

        # ── Build change log ─────────────────────────────────────────────────
        if old_type != new_type:
            changes.append(f'Type: {old_type} → {new_type}')
        if old_subtype != new_subtype:
            changes.append(f'Subtype: {old_subtype or "None"} → {new_subtype or "None"}')
        if old_loan_sub != new_loan_sub:
            changes.append(f'Loan type: {old_loan_sub or "None"} → {new_loan_sub or "None"}')
        if abs(old_amount - new_amount) > 0.01:
            changes.append(f'Amount: ₹{old_amount:,.0f} → ₹{new_amount:,.0f}')

        # ── Notify docs staff if coordinator/admin made changes ──────────────
        if current_user.role in ('coordinator', 'admin') and changes and proj.doc_staff_id:
            create_notification(
                proj.doc_staff_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Project details edited '
                f'by {current_user.full_name}. Changes: {", ".join(changes)}.',
                'info'
            )

        # ── Notify coordinator if documents staff made changes ───────────────
        if current_user.role == 'documents' and changes and proj.coordinator_id:
            create_notification(
                proj.coordinator_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Project details edited '
                f'by {current_user.full_name} (docs). Changes: {", ".join(changes)}.',
                'info'
            )

        # ── Notify payments on amount change ─────────────────────────────────
        if abs(old_amount - new_amount) > 0.01:
            pending        = new_amount - float(proj.collected_amount or 0)
            collected      = float(proj.collected_amount or 0)
            payments_users = User.query.filter_by(role='payments', is_active=True).all()
            for u in payments_users:
                if pending > 0:
                    create_notification(
                        u.id, pid,
                        f'{proj.project_code} — {proj.customer.name}: Contract amount revised '
                        f'from ₹{old_amount:,.0f} to ₹{new_amount:,.0f} '
                        f'by {current_user.full_name}. Outstanding: ₹{pending:,.0f}.',
                        'task'
                    )
                else:
                    create_notification(
                        u.id, pid,
                        f'{proj.project_code} — {proj.customer.name}: Contract amount revised '
                        f'from ₹{old_amount:,.0f} to ₹{new_amount:,.0f} '
                        f'by {current_user.full_name}. '
                        f'Already collected ₹{collected:,.0f}.',
                        'info'
                    )

        log_action(pid, 'Project edited: ' + (', '.join(changes) if changes else 'details updated'))
        db.session.commit()

        pending = new_amount - float(proj.collected_amount or 0)
        if pending > 0:
            flash(f'Project updated. Outstanding balance: ₹{pending:,.0f}.', 'success')
        else:
            flash('Project details updated successfully.', 'success')
        return redirect(url_for('project_detail', pid=pid))

    return render_template('edit_project.html', proj=proj,
                           doc_staff=doc_staff, coordinators=coordinators)
@app.route('/projects/<int:pid>/site_visit', methods=['POST'])
@login_required
@roles_required('admin', 'coordinator')
def add_site_visit(pid):
    proj = Project.query.get_or_404(pid)
    if proj.status in ('Cancelled', 'OnHold'):
        flash('Cannot schedule a site visit for this project.', 'danger')
        return redirect(url_for('project_detail', pid=pid))
    if proj.site_visits:
        flash('A site vist has already been scheduled for this project.','warning')
        return redirect(url_for('project_detail',pid=pid))
    visit = SiteVisit(
        project_id     = pid,
        scheduled_date = date.fromisoformat(request.form['scheduled_date']) if request.form.get('scheduled_date') else date.today(),
        conducted_by   = current_user.id,
        status         = 'Scheduled',
    )
    db.session.add(visit)
    db.session.flush()
    log_action(pid, 'Site visit scheduled', new_val='Scheduled')
    auto_advance_stage(proj)   # Lead → Site Visit fires here
    db.session.commit()
    flash('Site visit scheduled.', 'success')
    return redirect(url_for('project_detail', pid=pid))


@app.route('/projects/<int:pid>/site_visit/<int:vid>/complete', methods=['POST'])
@login_required
@roles_required('admin', 'coordinator')
def complete_site_visit(vid, pid):
    visit = SiteVisit.query.get_or_404(vid)
    proj  = Project.query.get_or_404(pid)
    visit.status       = 'Completed'
    visit.visited_date = date.fromisoformat(request.form['visited_date']) if request.form.get('visited_date') else date.today()
    visit.observations = request.form.get('observations', '')
    log_action(pid, 'Site visit completed', new_val='Completed')
    db.session.flush()
    auto_advance_stage(proj)   # Site Visit → Documentation fires here
    db.session.commit()
    flash('Site visit marked complete.', 'success')
    return redirect(url_for('project_detail', pid=pid))

@app.route('/projects/<int:pid>')
@login_required
def project_detail(pid):
    proj     = Project.query.get_or_404(pid)
    stages=get_document_stages()
    logs     = ProjectLog.query.filter_by(project_id=pid).order_by(ProjectLog.created_at.desc()).all()
    workers  = Worker.query.filter_by(is_active=True).all()
    all_workers = Worker.query.filter_by(is_active=True).all()
    worker_rate = {str(w.id):float(w.rate_per_day or 0) for w in all_workers}
    return render_template('project_detail.html', proj=proj, logs=logs,
                           workers=workers, all_workers=all_workers,worker_rate=worker_rate,today=date.today())
@app.route('/projects/<int:pid>/expenses', methods=['POST'])
@login_required
@roles_required('admin', 'documents')
def update_expense(pid):
    proj         = Project.query.get_or_404(pid)
    expense_type = request.form['expense_type']   # 'CD Payment' or 'Net Meter'
    amount       = float(request.form.get('amount') or 0)
    paid_by      = request.form.get('paid_by', 'Customer')
    paid_date    = request.form.get('paid_date')
    notes        = request.form.get('notes', '').strip()

    existing = ProjectExpense.query.filter_by(
        project_id=pid, expense_type=expense_type
    ).first()

    if existing:
        existing.amount    = amount
        existing.paid_by   = paid_by
        existing.paid_date = date.fromisoformat(paid_date) if paid_date else existing.paid_date
        existing.notes     = notes
        existing.recorded_by = current_user.id
    else:
        expense = ProjectExpense(
            project_id   = pid,
            expense_type = expense_type,
            amount       = amount,
            paid_by      = paid_by,
            paid_date    = date.fromisoformat(paid_date) if paid_date else None,
            notes        = notes,
            recorded_by  = current_user.id,
        )
        db.session.add(expense)

    log_action(pid, f'{expense_type} recorded: paid by {paid_by}, ₹{amount:,.0f}', new_val=paid_by)

    # If company paid, notify payments team to track recovery
    if paid_by == 'Company':
        payments_users = User.query.filter_by(role='payments', is_active=True).all()
        for u in payments_users:
            create_notification(
                u.id, pid,
                f'{proj.project_code} — {proj.customer.name}: {expense_type} of '
                f'₹{amount:,.0f} paid by company. To be recovered from customer.',
                'task'
            )

    db.session.commit()
    flash(f'{expense_type} updated.', 'success')
    return redirect(url_for('documents', pid=pid))


@app.route('/projects/<int:pid>/expenses/<int:eid>/mark_recovered', methods=['POST'])
@login_required
@roles_required('admin', 'payments')
def mark_expense_recovered(pid, eid):
    expense = ProjectExpense.query.get_or_404(eid)
    expense.recovered      = True
    expense.recovered_date = date.today()
    log_action(pid, f'{expense.expense_type} marked as recovered from customer')
    db.session.commit()
    flash(f'{expense.expense_type} marked as recovered.', 'success')
    return redirect(url_for('project_detail', pid=pid))

@app.route('/projects/<int:pid>/update_status', methods=['POST'])
@login_required
def update_status(pid):
    proj       = Project.query.get_or_404(pid)
    new_status = request.form.get('status')
    new_stage  = request.form.get('stage')
    old_status = proj.status
    if proj.status in ('Cancelled', 'OnHold'):
        flash('Cannot update status of a Cancelled or On Hold project.', 'danger')
        return redirect(url_for('project_detail', pid=pid))
    if new_stage:
        proj.stage = new_stage
        if not new_status:
            new_status=STAGE_STATUS_MAP.get(new_stage,proj.status)
    if new_status:
        proj.status = new_status
    if proj.status == 'Completed':
        if not proj.app_install or proj.app_install.status != 'Completed':
            if current_user.role != 'admin':
                flash('Project cannot be marked Completed until App Installation is done.', 'danger')
                proj.status = old_status
    log_action(pid, 'Status updated', old_val=old_status, new_val= proj.status)
    db.session.commit()
    flash('Project status updated.', 'success')
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/cancel', methods=['POST'])
@login_required
@roles_required('admin', 'coordinator','documents')
def cancel_project(pid):
    proj = Project.query.get_or_404(pid)

    # Coordinators can only cancel their own projects
    if current_user.role == 'coordinator' and proj.coordinator_id != current_user.id:
        flash('You can only cancel your own projects.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    if proj.status == 'Cancelled':
        flash('Project is already cancelled.', 'warning')
        return redirect(url_for('project_detail', pid=pid))

    if proj.status == 'Closed':
        flash('Closed projects cannot be cancelled.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    old_status  = proj.status
    proj.status = 'Cancelled'
    reason      = request.form.get('reason', '').strip()
    log_action(pid, f'Project cancelled. Reason: {reason or "No reason provided"}',
               old_val=old_status, new_val='Cancelled')

    # Notify doc staff if assigned
    if proj.doc_staff_id:
        create_notification(
            user_id    = proj.doc_staff_id,
            project_id = pid,
            message    = f'Project {proj.project_code} — {proj.customer.name} has been cancelled.',
            notif_type = 'warning',
        )
    if proj.coordinator_id and proj.coordinator_id != current_user.id:
        create_notification(
            user_id    = proj.coordinator_id,
            project_id = pid,
            message    = f'Project {proj.project_code} — {proj.customer.name} has been cancelled by {current_user.full_name}.',
            notif_type = 'warning',
        )

    db.session.commit()
    flash(f'Project {proj.project_code} has been cancelled.', 'success')
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/uncancel', methods=['POST'])
@login_required
@roles_required('admin')
def uncancel_project(pid):
    proj = Project.query.get_or_404(pid)

    if proj.status != 'Cancelled':
        flash('Project is not cancelled.', 'warning')
        return redirect(url_for('project_detail', pid=pid))

    reason = request.form.get('reason', '').strip()
    proj.status = 'InProgress' if proj.stage != 'Lead' else 'Lead'

    log_action(pid, f'Project uncancelled. Reason: {reason or "No reason provided"}',
               old_val='Cancelled', new_val=proj.status)

    if proj.coordinator_id:
        create_notification(
            user_id    = proj.coordinator_id,
            project_id = pid,
            message    = f'Project {proj.project_code} — {proj.customer.name} has been reinstated by {current_user.full_name}.',
            notif_type = 'info',
        )
    if proj.doc_staff_id:
        create_notification(
            user_id    = proj.doc_staff_id,
            project_id = pid,
            message    = f'Project {proj.project_code} — {proj.customer.name} has been reinstated.',
            notif_type = 'info',
        )

    db.session.commit()
    flash(f'Project {proj.project_code} has been reinstated.', 'success')
    return redirect(url_for('project_detail', pid=pid))

@app.route('/projects/<int:pid>/hold', methods=['POST'])
@login_required
@roles_required('admin', 'coordinator', 'documents')
def hold_project(pid):
    proj = Project.query.get_or_404(pid)

    # Documents staff can only hold their assigned projects
    if current_user.role == 'documents' and proj.doc_staff_id != current_user.id:
        flash('You can only put your assigned projects on hold.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    if proj.status in ('Cancelled', 'Closed', 'Completed'):
        flash(f'Cannot put a {proj.status} project on hold.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    old_status  = proj.status
    reason      = request.form.get('reason', '').strip()

    if proj.status == 'OnHold':
        # Toggle: Resume the project
        proj.status = 'InProgress'
        log_action(pid, 'Project resumed from On Hold', old_val='OnHold', new_val='InProgress')
        # Notify coordinator
        if proj.coordinator_id:
            create_notification(
                user_id    = proj.coordinator_id,
                project_id = pid,
                message    = f'Project {proj.project_code} — {proj.customer.name} has been resumed.',
                notif_type = 'info',
            )
        flash(f'Project {proj.project_code} resumed.', 'success')
    else:
        proj.status = 'OnHold'
        log_action(pid, f'Project put on hold. Reason: {reason or "No reason provided"}',
                   old_val=old_status, new_val='OnHold')
        # Notify coordinator
        if proj.coordinator_id:
            create_notification(
                user_id    = proj.coordinator_id,
                project_id = pid,
                message    = (
                    f'Project {proj.project_code} — {proj.customer.name} has been put On Hold'
                    + (f': {reason}' if reason else '.') 
                ),
                notif_type = 'warning',
            )
        flash(f'Project {proj.project_code} is now On Hold.', 'warning')

    db.session.commit()
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/assign_doc_staff', methods=['POST'])
@login_required
@roles_required('coordinator')
def assign_doc_staff(pid):
    proj         = Project.query.get_or_404(pid)
    new_staff_id = request.form.get('doc_staff_id')

    if not new_staff_id:
        flash('Please select a staff member.', 'danger')
        return redirect(url_for('project_detail', pid=pid))

    new_staff_id = int(new_staff_id)
    old_staff    = proj.doc_staff

    # Notify old staff if being replaced
    if old_staff and old_staff.id != new_staff_id:
        create_notification(
            user_id    = old_staff.id,
            project_id = pid,
            message    = f'You have been unassigned from {proj.project_code} — {proj.customer.name}.',
            notif_type = 'info',
        )

    proj.doc_staff_id = new_staff_id
    new_staff = User.query.get(new_staff_id)

    create_notification(
        user_id    = new_staff_id,
        project_id = pid,
        message    = f'You have been assigned to {proj.project_code} — {proj.customer.name} ({proj.project_type}, {proj.system_kw} kW).',
        notif_type = 'task',
    )

    log_action(pid, 'Doc staff assigned',
               old_val = old_staff.full_name if old_staff else None,
               new_val = new_staff.full_name if new_staff else None)
    db.session.commit()
    flash(f'{new_staff.full_name} assigned and notified.', 'success')
    return redirect(url_for('project_detail', pid=pid))

@app.route('/coordinator/analytics')
@login_required
@roles_required('coordinator')
def coordinator_analytics():
    from collections import Counter
    from datetime import timedelta
    import calendar as cal_module

    today          = date.today()
    my_projects    = Project.query.filter_by(coordinator_id=current_user.id).all()
    my_project_ids = [p.id for p in my_projects]

    # Projects created this calendar month
    this_month_count = sum(
        1 for p in my_projects
        if p.created_at.year == today.year and p.created_at.month == today.month
    )

    # Doc-staff analytics
    doc_staff_users = User.query.filter_by(role='documents', is_active=True).all()
    doc_analytics   = []
    for staff in doc_staff_users:
        assigned    = [p for p in my_projects if p.doc_staff_id == staff.id]
        completed   = [p for p in assigned if p.status in ['Completed', 'Closed']]
        inprog      = [p for p in assigned if p.status == 'InProgress']
        not_started = [p for p in assigned if p.status == 'InProgress' and len(p.documents) == 0]
        total_docs  = sum(len(get_expected_docs(p.project_type,p.project_subtype,p.loan_subtype)) for p in assigned)
        done_docs   = sum(get_doc_completion(p)[0] for p in assigned)
        doc_analytics.append({
            'staff':       staff,
            'assigned':    len(assigned),
            'completed':   len(completed),
            'inprog':      len(inprog),
            'not_started': len(not_started),
            'total_docs':  total_docs,
            'done_docs':   done_docs,
            'doc_pct':     int(done_docs / total_docs * 100) if total_docs > 0 else 0,
        })

    unassigned_projects = [p for p in my_projects if not p.doc_staff_id]

    # Stage distribution
    stage_order = [
        'Lead', 'Site Visit', 'Documentation',
        'Onsite Work','Connection','Subsidy','Payment'
    ]
    stage_counts_raw = Counter(p.stage for p in my_projects)
    stage_data       = [{'stage': s, 'count': stage_counts_raw.get(s, 0)} for s in stage_order]

    # All payments for my projects
    payments_all = Payment.query.filter(
        Payment.project_id.in_(my_project_ids)
    ).all() if my_project_ids else []

    # Weekly data — last 12 weeks
    week_labels        = []
    week_projects_data = []
    week_payments_k    = []
    for i in range(11, -1, -1):
        wstart = today - timedelta(weeks=i + 1) + timedelta(days=1)
        wend   = today - timedelta(weeks=i)
        week_labels.append(wstart.strftime('%d %b'))
        week_projects_data.append(sum(
            1 for p in my_projects
            if wstart <= p.created_at.date() <= wend
        ))
        week_payments_k.append(round(sum(
            float(p.amount) for p in payments_all
            if wstart <= p.payment_date <= wend
        ) / 1000, 1))

    # Daily activity — current month
    days_in_month     = cal_module.monthrange(today.year, today.month)[1]
    month_day_labels  = [str(d) for d in range(1, days_in_month + 1)]
    month_day_projects = [
        sum(1 for p in my_projects if p.created_at.date() == date(today.year, today.month, d))
        for d in range(1, days_in_month + 1)
    ]

    # Payments per month — last 6 months
    pay_month_labels = []
    pay_month_values = []
    for i in range(5, -1, -1):
        month_date = today.replace(day=1)
        for _ in range(i):
            month_date = (month_date - timedelta(days=1)).replace(day=1)
        pay_month_labels.append(month_date.strftime('%b %Y'))
        pay_month_values.append(round(sum(
            float(p.amount) for p in payments_all
            if p.payment_date.year == month_date.year
            and p.payment_date.month == month_date.month
        ) / 1000, 1))

    # Status cumulative trend — weekly
    trend_inprog    = []
    trend_completed = []
    trend_delayed   = []
    for i in range(11, -1, -1):
        snap = today - timedelta(weeks=i)
        trend_inprog.append(sum(
            1 for p in my_projects
            if p.status == 'InProgress' and p.created_at.date() <= snap
        ))
        trend_completed.append(sum(
            1 for p in my_projects
            if p.status in ['Completed', 'Closed'] and p.created_at.date() <= snap
        ))
        trend_delayed.append(sum(
            1 for p in my_projects
            if p.status == 'Delayed' and p.created_at.date() <= snap
        ))

    chart_data = {
        'week_labels':         week_labels,
        'week_projects':       week_projects_data,
        'week_payments_k':     week_payments_k,
        'month_day_labels':    month_day_labels,
        'month_day_projects':  month_day_projects,
        'pay_month_labels':    pay_month_labels,
        'pay_month_values':    pay_month_values,
        'staff_names':         [a['staff'].full_name.split()[0] for a in doc_analytics],
        'staff_done':          [a['done_docs']                   for a in doc_analytics],
        'staff_pending':       [a['total_docs'] - a['done_docs'] for a in doc_analytics],
        'trend_inprog':        trend_inprog,
        'trend_completed':     trend_completed,
        'trend_delayed':       trend_delayed,
        'stage_labels':        [s['stage'] for s in stage_data if s['count'] > 0],
        'stage_counts':        [s['count'] for s in stage_data if s['count'] > 0],
    }

    return render_template('coordinator_analytics.html',
        my_projects         = my_projects,
        doc_analytics       = doc_analytics,
        unassigned_projects = unassigned_projects,
        stage_data          = stage_data,
        this_month_count    = this_month_count,
        chart_data          = chart_data,
    )

# ─────────────────────────────────────────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────────────────────────────────────────


@app.route('/projects/<int:pid>/add_payment', methods=['POST'])
@login_required
@roles_required('admin', 'payments')
def add_payment(pid):
    proj   = Project.query.get_or_404(pid)
    if proj.stage == 'Lead':
        flash('Payments cannot be recorded while the project is still in Lead stage.','danger')
        return redirect(url_for('project_detail',pid=pid))
    amount = float(request.form['amount'])
    source=request.form.get('payment_source','Customer')

    if proj.total_amount and proj.total_amount > 0:
        if float(proj.collected_amount or 0) >= float(proj.total_amount):
            flash('This project is fully paid. No further payments can be recorded.', 'danger')
            return redirect(url_for('project_detail', pid=pid))

    if proj.total_amount and proj.total_amount > 0:
        remaining = float(proj.total_amount) - float(proj.collected_amount or 0)
        if amount > remaining + 0.01:          
            flash(
                f'Payment of ₹{amount:,.0f} exceeds the remaining balance of ₹{remaining:,.0f}. '
                f'Please enter a correct amount.',
                'danger'
            )
            return redirect(url_for('project_detail', pid=pid))

    instalment=None
    if source == 'Bank':
        instalment  = request.form.get('instalment')
        existing    = [p.instalment for p in proj.payments if p.payment_source == 'Bank']
        if instalment in existing:
            flash(f'{instalment} bank payment already recorded for this project.', 'danger')
            return redirect(url_for('project_detail', pid=pid))
    

    pay = Payment(
        project_id     = pid,
        amount         = amount,
        payment_type   = request.form['payment_type'],
        payment_source = source,
        instalment     = instalment,
        payment_date   = date.fromisoformat(request.form['payment_date']),
        reference_no   = request.form.get('reference_no'),
        received_by    = current_user.id,
        notes          = request.form.get('notes'),
    )
    db.session.add(pay)
    proj.collected_amount = float(proj.collected_amount or 0) + amount
    label = f'{instalment} bank payment' if instalment else 'Customer payment'
    log_action(pid, f'{label} recorded: ₹{amount:,.0f}', new_val=str(amount))
    auto_advance_stage(proj)
    db.session.commit()
    flash(f'Payment of ₹{amount:,.0f} recorded.', 'success')
    return redirect(url_for('project_detail', pid=pid))


@app.route('/payments')
@login_required
@roles_required('admin', 'payments')
def payments_dashboard():
    page=request.args.get('page',1,type=int)
    pay_page=request.args.get('pay_page',1,type=int)
    per_page=15
    active_project_ids = db.session.query(Project.id).filter(
        Project.status.notin_(['Cancelled', 'OnHold'])
    ).subquery()
    total_collected = float(db.session.query(db.func.sum(Payment.amount)).filter(
        Payment.project_id.in_(active_project_ids)
    ).scalar() or 0)
    total_value     = float(db.session.query(db.func.sum(Project.total_amount)).filter(
        Project.status.notin_(['Cancelled', 'OnHold'])
    ).scalar() or 0)
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).paginate(page=pay_page,per_page=per_page,error_out=False)
    pending_projs   = Project.query.filter(Project.status.notin_(['Closed', 'Cancelled', 'OnHold'])).order_by(Project.updated_at.desc()).paginate(page=page,per_page=per_page,error_out=False)
    return render_template('payments.html',
                           total_collected=total_collected,
                           total_pending=total_value - total_collected,
                           total_value=total_value,
                           recent_payments=recent_payments,
                           pending_projs=pending_projs,
                           page=page,
                           pay_page=pay_page)
@app.route('/payments/pending_approvals')
@login_required
@roles_required('admin', 'onsite')
def pending_approvals():
    cards = JobCard.query.filter_by(status='PendingApproval')\
                .order_by(JobCard.closed_at.desc()).all()
    return render_template('pending_approvals.html', cards=cards)
# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/projects/<int:pid>/documents', methods=['GET', 'POST'])
@login_required
def documents(pid):
    proj = Project.query.get_or_404(pid)
    stages=get_document_stages()
    if current_user.role == 'documents' and proj.doc_staff_id != current_user.id:
        flash('This project is not assigned to you.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        if proj.stage in ('Lead', 'Site Visit'):
            flash('Documents cannot be updated until the site visit is completed.', 'danger')
            return redirect(url_for('documents', pid=pid))
        done_before,expected=get_doc_completion(proj)
        was_complete=(expected >0 and done_before == expected)
        if current_user.role != 'admin' and was_complete:
            flash('All documents are completed and locked.','danger')
            return redirect(url_for('documents',pid=pid))
        doc_type = request.form['doc_type']
        status   = request.form.get('status', 'Pending')

        existing = Document.query.filter_by(project_id=pid, doc_type=doc_type).first()
        if existing:
            existing.status = status
            if status != 'Pending':
                existing.received_date = date.today()
            log_action(pid, f'Document updated: {doc_type}', new_val=status)
        else:
            doc = Document(
                project_id    = pid,
                doc_type      = doc_type,
                status        = status,
                received_date = date.today() if status != 'Pending' else None,
                notes         = request.form.get('notes'),
            )
            db.session.add(doc)
            log_action(pid, f'Document received: {doc_type}', new_val=status)

        # ── Feasibility trigger ──────────────────────────────────────────────
        if doc_type == 'Feasibility Receipt' and status in ('Received', 'Completed'):
            already_notified = Notification.query.filter_by(
                project_id = pid,
                notif_type = 'task',
            ).filter(Notification.message.like('%Structure work%')).first()
            if not already_notified:
                notify_onsite_team(
                    project_id = pid,
                    message    = f'Feasibility done for {proj.project_code} — {proj.customer.name}. Start structure work.',
                    notif_type = 'task',
                )
                log_action(pid, 'Onsite team notified: structure work', new_val='Notified')
        # ────────────────────────────────────────────────────────────────────
        if doc_type == 'KSEB Connection' and status in ('Received','Completed'):
            existing_install=AppInstallation.query.filter_by(project_id=pid).first()
            if not existing_install:
                install=AppInstallation(project_id=pid, status='Pending',scheduled_date=date.today())
                db.session.add(install)
                log_action(pid,'KSEB connection complete → App Installation queued',new_val='Pending')
                app_users=User.query.filter_by(role='appinstall',is_active=True).all()
                for u in app_users:
                    create_notification(
                        user_id=u.id,
                        project_id=pid,
                        message=(
                            f'KSEB connection done for {proj.project_code} — '
                            f'{proj.customer.name} ({proj.system_kw} kW). '
                            f'Schedule app installation.'
                        ),
                        notif_type='task',
                    )
        if current_user.role == 'admin' and was_complete and proj.doc_staff_id:
            create_notification(
                proj.doc_staff_id,pid,
                f'{proj.project_code} - {proj.customer.name}:Admin({current_user.full_name})'
                f'edited document "{doc_type}" -> {status} after completion.',
                'info'
            )
        db.session.flush()
        auto_advance_stage(proj)
        db.session.commit()
        flash(f'{doc_type} — {status}.', 'success')

    return render_template('documents.html', proj=proj,stages=stages)
@app.route('/projects/<int:pid>/documents/batch', methods=['POST'])
@login_required
def batch_documents(pid):
    proj = Project.query.get_or_404(pid)
    if current_user.role == 'documents' and proj.doc_staff_id != current_user.id:
        flash('This project is not assigned to you.', 'danger')
        return redirect(url_for('dashboard'))
    if proj.stage in ('Lead', 'Site Visit'):
        flash('Documents cannot be updated until the site visit is completed.', 'danger')
        return redirect(url_for('documents', pid=pid))
 
    doc_types = request.form.getlist('doc_types')
    status    = request.form.get('status', 'Received')
 
    for doc_type in doc_types:
        existing = Document.query.filter_by(project_id=pid, doc_type=doc_type).first()
        if existing:
            existing.status = status
            if status != 'Pending':
                existing.received_date = date.today()
        else:
            db.session.add(Document(
                project_id    = pid,
                doc_type      = doc_type,
                status        = status,
                received_date = date.today() if status != 'Pending' else None,
            ))
        log_action(pid, f'Batch document update: {doc_type}', new_val=status)
 
    db.session.flush()
    auto_advance_stage(proj)
    db.session.commit()
    flash(f'{len(doc_types)} documents marked {status}.', 'success')
    return redirect(url_for('documents', pid=pid))
# ─────────────────────────────────────────────────────────────────────────────
# KSEB
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/projects/<int:pid>/kseb', methods=['GET', 'POST'])
@login_required
def kseb(pid):
    proj = Project.query.get_or_404(pid)
    task = proj.kseb_task or KSEBTask(project_id=pid)

    if request.method == 'POST':
        task.stamp_paper     = request.form.get('stamp_paper', task.stamp_paper)
        task.b_class_licence = request.form.get('b_class_licence', task.b_class_licence)
        task.file_sent       = 'file_sent' in request.form
        task.inspection_done = 'inspection_done' in request.form
        task.cd_payment_done = 'cd_payment_done' in request.form
        task.connection_done = 'connection_done' in request.form
        task.meter_available = 'meter_available' in request.form
        task.ae_completed    = 'ae_completed' in request.form
        task.notes           = request.form.get('notes')
        if not task.id:
            db.session.add(task)
            db.session.flush()
        log_action(pid, 'KSEB tasks updated')
        existing_install=AppInstallation.query.filter_by(project_id=pid).first()
        if task.connection_done and not existing_install:
            install=AppInstallation(
                project_id=pid,
                status='Pending',
                scheduled_date=date.today()
            )
            db.session.add(install)
            log_action(pid,'KSEB connection complete → App Installation queued',new_val='Pending')
            app_users = User.query.filter_by(role='appinstall', is_active=True).all()
            for u in app_users:
                create_notification(
                    user_id    = u.id,
                    project_id = pid,
                    message    = (
                        f'KSEB connection done for {proj.project_code} — '
                        f'{proj.customer.name} ({proj.system_kw} kW). '
                        f'Schedule app installation.'
                    ),
                    notif_type = 'task',
                )
        db.session.flush()
        auto_advance_stage(proj)
        db.session.commit()
        flash('KSEB tasks updated.', 'success')
    return render_template('kseb.html', proj=proj, task=task)


# ─────────────────────────────────────────────────────────────────────────────
# WORKERS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/workers')
@login_required
@roles_required('admin', 'onsite', 'payments')
def workers():
    all_workers = Worker.query.filter_by(is_active=True).all()
    return render_template('workers.html', workers=all_workers,today=date.today())


@app.route('/projects/<int:pid>/assign_worker', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def assign_worker(pid):
    if current_user.role=='onsite':
        feasibility=Document.query.filter_by(
            project_id=pid,
            doc_type='Feasibility Receipt',
        ).filter(Document.status.in_(['Received','Completed'])).first()
        if not feasibility:
            flash('Worker assignment is not allowed until the Feasibility Receipt is received','danger')
            return redirect(url_for('project_detail',pid=pid))
    start=request.form.get('start_date')
    end=request.form.get('end_date')
    days=0
    if start and end:     
        d1 = date.fromisoformat(start)
        d2 = date.fromisoformat(end)
        days = max((d2 - d1).days + 1,0)
    work_phase=request.form.get('work_phase','Structure')
    progress = Project.query.get_or_404(pid).onsite_progress
    if work_phase == 'Installation':
        
        if not progress or progress.structure_work_status!='Completed':
            flash('Panel installation workers cannot be assigned until structure work is marked completed.','danger')
            return redirect(url_for('project_detail',pid=pid))
    if work_phase == 'Electrical':
        if not progress or progress.structure_work_status !='Completed':
            flash('Electrical workers cannot be assigned until structure work is marked Completed.','danger')
            return redirect(url_for('project_detail',pid=pid))
    if work_phase == 'Installation':
        # Also require at least one material dispatched
        dispatched = [m for m in Project.query.get_or_404(pid).materials
                      if m.dispatch_status in ('Dispatched', 'Delivered')]
        if not dispatched:
            flash('At least one material must be Dispatched before assigning Installation workers.', 'danger')
            return redirect(url_for('project_detail', pid=pid))    
    wa = WorkerAssignment(
        project_id = pid,
        worker_id  = request.form['worker_id'],
        start_date = date.fromisoformat(start) if start else None,
        end_date = date.fromisoformat(end) if end else None,
        days_worked=days,
        work_phase=work_phase,
        status     = 'Assigned',
    )
    db.session.add(wa)
    assigned_worker = Worker.query.get(int(request.form['worker_id']))
    card = JobCard(
        project_id   = pid,
        worker_id    = int(request.form['worker_id']),
        work_phase   = work_phase,
        rate_per_day = assigned_worker.rate_per_day,
        status       = 'Open',
    )
    db.session.add(card)
    
    log_action(pid, f'Worker assigned: ID {request.form["worker_id"]}',new_val=wa.status)
    db.session.commit()
    flash('Worker assigned.', 'success')
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/unassign_worker/<int:aid>', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def unassign_worker(pid, aid):
    wa = WorkerAssignment.query.get_or_404(aid)
    
    if wa.status == 'Paid':
        flash('Cannot unassign a worker who has already been paid.', 'danger')
        return redirect(url_for('project_detail', pid=pid))
    
    # Void any open/pending job cards for this worker+phase on this project
    related_cards = JobCard.query.filter_by(
        project_id=pid,
        worker_id=wa.worker_id,
        work_phase=wa.work_phase,
    ).filter(JobCard.status.in_(['Open', 'PendingApproval'])).all()
    
    for card in related_cards:
        card.status = 'Voided'
    
    worker_name = wa.worker.name
    phase = wa.work_phase
    log_action(pid, f'Worker unassigned: {worker_name} — {phase}', old_val=wa.status)
    db.session.delete(wa)
    db.session.commit()
    flash(f'{worker_name} unassigned from {phase} phase.', 'success')
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/update_assignment/<int:aid>', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def update_assignment(pid, aid):
    if current_user.role == 'onsite':
        feasibility = Document.query.filter_by(
            project_id=pid,
            doc_type='Feasibility Receipt',
        ).filter(Document.status.in_(['Received', 'Completed'])).first()
        if not feasibility:
            flash('Worker assignment is not allowed until the Feasibility Receipt is received', 'danger')
            return redirect(url_for('project_detail', pid=pid))

    wa = WorkerAssignment.query.get_or_404(aid)

    new_worker_id = request.form.get('worker_id')
    if new_worker_id:
        wa.worker_id = int(new_worker_id)

    new_phase = request.form.get('work_phase', wa.work_phase)
    if new_phase == 'Installation' or new_phase == 'Electrical':
        progress = Project.query.get_or_404(pid).onsite_progress
        if not progress or progress.structure_work_status != 'Completed':
            flash('Installation and Electrical phases require structure work to be Completed.', 'danger')
            return redirect(url_for('project_detail', pid=pid))
    wa.work_phase = new_phase

    new_status = request.form.get('status', wa.status)
    if new_status == 'Paid' and wa.status != 'Completed':
        flash('Worker must be marked Completed before payment can be recorded.', 'danger')
        return redirect(url_for('project_detail', pid=pid))
    wa.status = new_status

    log_action(pid, f'Worker assignment updated: {wa.worker.name}', new_val=wa.status)
    db.session.commit()
    flash(f'Assignment updated.', 'success')
    return redirect(url_for('project_detail', pid=pid))
# @app.route('/worker/<int:worker_id>/weekly_payment', methods=['POST'])
# @login_required
# @roles_required('admin', 'onsite', 'payments')
# def add_worker_payment(worker_id):
#     worker      = Worker.query.get_or_404(worker_id)
#     week_start  = datetime.strptime(request.form['week_start'],  '%Y-%m-%d').date()
#     week_end    = datetime.strptime(request.form['week_end'],    '%Y-%m-%d').date()
#     paid_date   = datetime.strptime(request.form['paid_date'],   '%Y-%m-%d').date()
#     days_worked = Decimal(request.form['days_worked'])
#     rate_per_day = Decimal(request.form['rate_per_day'])
#     project_ids = request.form.getlist('project_ids')

#     # ── Guard: duplicate week ────────────────────────────────────────────────
#     duplicate = WorkerWeeklyPayment.query.filter_by(
#         worker_id  = worker.id,
#         week_start = week_start,
#     ).first()
#     if duplicate:
#         flash(f'A payment for {worker.name} covering the week starting '
#               f'{week_start} already exists.', 'danger')
#         return redirect(url_for('workers'))

#     # ── Guard: days sanity ───────────────────────────────────────────────────
#     if days_worked <= 0 or days_worked > 7:
#         flash('Days worked must be between 0.5 and 7.', 'danger')
#         return redirect(url_for('workers'))

#     # ── Always recompute amount server-side ──────────────────────────────────
#     amount = (days_worked * rate_per_day).quantize(Decimal('0.01'))

#     pay = WorkerWeeklyPayment(
#         worker_id    = worker.id,
#         week_start   = week_start,
#         week_end     = week_end,
#         days_worked  = days_worked,
#         rate_per_day = rate_per_day,
#         amount       = amount,
#         paid_date    = paid_date,
#         payer_id     = current_user.id,
#         notes        = request.form.get('notes') or None,
#     )
#     if project_ids:
#         pay.projects = Project.query.filter(Project.id.in_(project_ids)).all()

#     db.session.add(pay)
#     db.session.flush()

#     # ── Auto-mark linked assignments as Paid + log against each project ──────
#     for proj in pay.projects:
#         for wa in proj.assignments:
#             if wa.worker_id == worker.id and wa.status == 'Completed':
#                 wa.status = 'Paid'
#         log_action(
#             proj.id,
#             f'Worker paid: {worker.name} — {days_worked} days @ ₹{rate_per_day}/day',
#             new_val=str(amount),
#         )

#     db.session.commit()
#     flash(f'Payment of ₹{amount:,.0f} recorded for {worker.name}.', 'success')
#     return redirect(url_for('workers'))
@app.route('/worker/payment/<int:pay_id>/delete', methods=['POST'])
@login_required
@roles_required('admin')
def delete_worker_payment(pay_id):
    pay    = WorkerWeeklyPayment.query.get_or_404(pay_id)
    worker = pay.worker
    reason = request.form.get('reason', '').strip()

    # Revert assignment statuses on linked projects
    for proj in pay.projects:
        for wa in proj.assignments:
            if wa.worker_id == worker.id and wa.status == 'Paid':
                wa.status = 'Completed'
        log_action(
            proj.id,
            f'Worker payment voided: {worker.name} — week {pay.week_start}. '
            f'Reason: {reason or "Not provided"}',
            old_val=str(pay.amount),
        )

    db.session.delete(pay)
    db.session.commit()
    flash(f'Payment for {worker.name} (week {pay.week_start}) voided.', 'warning')
    return redirect(url_for('workers'))
@app.route('/projects/<int:pid>/onsite_progress', methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'onsite')
def onsite_progress(pid):
    proj     = Project.query.get_or_404(pid)
    progress = proj.onsite_progress or OnsiteProgress(project_id=pid)

    if request.method == 'POST':
        new_structure_status  = request.form.get('structure_work_status', progress.structure_work_status)
        new_install_status    = request.form.get('installation_status', '')
        new_electrical_status = request.form.get('electrical_status', '')

        # ── Worker guards ────────────────────────────────────────────────────
        structure_workers = [
            a for a in proj.assignments
            if a.work_phase == 'Structure' and a.status != 'Paid'
        ]
        installation_workers = [
            a for a in proj.assignments
            if a.work_phase == 'Installation' and a.status != 'Paid'
        ]
        electrical_workers = [
            a for a in proj.assignments
            if a.work_phase == 'Electrical' and a.status != 'Paid'
        ]

        if new_structure_status in ('InProgress', 'Completed') and not structure_workers:
            flash('Assign at least one Structure worker before updating structure work status.', 'danger')
            return redirect(url_for('onsite_progress', pid=pid))
        if new_install_status in ('InProgress', 'Completed') and not installation_workers:
            flash('Assign at least one Installation worker before updating panel installation status.', 'danger')
            return redirect(url_for('onsite_progress', pid=pid))
        if new_electrical_status in ('InProgress', 'Completed') and not electrical_workers:
            flash('Assign at least one Electrical worker before updating electrical work status.', 'danger')
            return redirect(url_for('onsite_progress', pid=pid))

        # ── Capture old values before updating ───────────────────────────────
        old_structure  = progress.structure_work_status
        old_install    = progress.installation_status or 'NotStarted'
        old_electrical = progress.electrical_status   or 'NotStarted'

        # ── Apply updates ────────────────────────────────────────────────────
        progress.structure_work_status = new_structure_status
        progress.structure_notes       = request.form.get('structure_notes', progress.structure_notes)

        if new_install_status and new_install_status != 'None':
            progress.installation_status = new_install_status
        elif not progress.installation_status or progress.installation_status == 'None':
            progress.installation_status = 'NotStarted'
        progress.installation_notes = request.form.get('installation_notes', progress.installation_notes)

        if new_electrical_status and new_electrical_status != 'None':
            progress.electrical_status = new_electrical_status
        elif not progress.electrical_status or progress.electrical_status == 'None':
            progress.electrical_status = 'NotStarted'
        progress.electrical_notes = request.form.get('electrical_notes', progress.electrical_notes)

        progress.updated_by = current_user.id

        for field, col in [
            ('structure_start_date',    'structure_start_date'),
            ('structure_end_date',      'structure_end_date'),
            ('installation_start_date', 'installation_start_date'),
            ('installation_end_date',   'installation_end_date'),
            ('electrical_start_date',   'electrical_start_date'),
            ('electrical_end_date',     'electrical_end_date'),
        ]:
            val = request.form.get(field)
            if val:
                setattr(progress, col, date.fromisoformat(val))

        if not progress.id:
            db.session.add(progress)

        # ── Build meaningful log message ─────────────────────────────────────
        changes = []
        if old_structure != progress.structure_work_status:
            changes.append(f'Structure: {old_structure} → {progress.structure_work_status}')
        if old_install != progress.installation_status:
            changes.append(f'Installation: {old_install} → {progress.installation_status}')
        if old_electrical != progress.electrical_status:
            changes.append(f'Electrical: {old_electrical} → {progress.electrical_status}')

        if changes:
            log_action(pid, 'Onsite: ' + ', '.join(changes))
        else:
            log_action(pid, 'Onsite dates/notes updated')
        db.session.flush()
        auto_advance_stage(proj)
        db.session.commit()
        flash('Onsite progress updated.', 'success')

    return render_template('onsite_progress.html', proj=proj, progress=progress)
@app.route('/projects/<int:pid>/onsite_log', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def add_onsite_log(pid):
    proj = Project.query.get_or_404(pid)
    note = request.form.get('note', '').strip()
    phase = request.form.get('work_phase', 'Structure')
    if not note:
        flash('Note cannot be empty.', 'danger')
        return redirect(url_for('onsite_progress', pid=pid))
    entry = OnsiteLog(
        project_id = pid,
        log_date   = date.today(),
        work_phase = phase,
        note       = note,
        logged_by  = current_user.id,
    )
    db.session.add(entry)
    log_action(pid, f'Onsite log added: {phase}', new_val=note[:60])
    db.session.commit()
    flash('Log entry added.', 'success')
    return redirect(url_for('onsite_progress', pid=pid))
@app.route('/job_card/<int:card_id>/close', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def close_job_card(card_id):
    card = JobCard.query.get_or_404(card_id)
 
    if card.status != 'Open':
        flash('This job card is not open.', 'danger')
        return redirect(url_for('workers'))
 
    actual_days  = Decimal(request.form['actual_days'])
    final_amount = Decimal(request.form['final_amount'])
    description  = request.form.get('description', '').strip() or None
 
    card.actual_days  = actual_days
    card.final_amount = final_amount
    card.description  = description
    card.status       = 'PendingApproval'
    card.closed_at    = datetime.utcnow()
    card.closed_by    = current_user.id
 
    log_action(
        card.project_id,
        f'Job card closed: {card.worker.name} — {card.work_phase} ({actual_days} days)',
        new_val=str(final_amount),
    )
    db.session.commit()
    flash(f'Job card submitted for approval — ₹{final_amount:,.0f} for {card.worker.name}.', 'success')
    return redirect(url_for('workers'))
@app.route('/job_card/<int:card_id>/approve', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def approve_job_card(card_id):
    card = JobCard.query.get_or_404(card_id)
 
    if card.status != 'PendingApproval':
        flash('Card is not pending approval.', 'danger')
        return redirect(url_for('workers'))
 
    card.status      = 'Approved'
    card.approved_at = datetime.utcnow()
    card.approved_by = current_user.id
 
    # ── Create ledger entry (Credit) ─────────────────────────────────────────
    last = WorkerLedger.query.filter_by(worker_id=card.worker_id) \
               .order_by(WorkerLedger.id.desc()).first()
    prev_balance = float(last.balance_after) if last else 0.0
    new_balance  = prev_balance + float(card.final_amount)
 
    entry = WorkerLedger(
        worker_id      = card.worker_id,
        entry_date     = date.today(),
        entry_type     = 'Earning',
        direction      = 'Credit',
        amount         = card.final_amount,
        reference_type = 'JobCard',
        reference_id   = card.id,
        balance_after  = new_balance,
        recorded_by    = current_user.id,
        notes          = f'{card.work_phase} — {card.project.project_code}',
    )
    db.session.add(entry)
 
    log_action(
        card.project_id,
        f'Job card approved: {card.worker.name} — {card.work_phase}',
        new_val=str(card.final_amount),
    )
    db.session.commit()
    flash(
        f'Job card approved. ₹{card.final_amount:,.0f} added to {card.worker.name}\'s balance.',
        'success',
    )
    return redirect(url_for('workers'))
@app.route('/job_card/<int:card_id>/void', methods=['POST'])
@login_required
@roles_required('admin','onsite')
def void_job_card(card_id):
    card = JobCard.query.get_or_404(card_id)
 
    if card.status == 'Paid':
        flash('Paid job cards cannot be voided.', 'danger')
        return redirect(url_for('workers'))
 
    old_status  = card.status
    card.status = 'Voided'
    log_action(
        card.project_id,
        f'Job card voided: {card.worker.name} — {card.work_phase}',
        old_val=old_status, new_val='Voided',
    )
    db.session.commit()
    flash(f'Job card for {card.worker.name} voided.', 'warning')
    return redirect(url_for('workers'))
@app.route('/worker/<int:worker_id>/advance', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def give_advance(worker_id):
    worker = Worker.query.get_or_404(worker_id)
    amount = Decimal(request.form['amount'])
 
    if amount <= 0:
        flash('Amount must be greater than 0.', 'danger')
        return redirect(url_for('workers'))
 
    given_date = datetime.strptime(request.form['given_date'], '%Y-%m-%d').date()
    notes      = request.form.get('notes', '').strip() or None
 
    advance = WorkerAdvance(
        worker_id  = worker_id,
        amount     = amount,
        given_date = given_date,
        given_by   = current_user.id,
        notes      = notes,
        status     = 'Outstanding',
    )
    db.session.add(advance)
    db.session.flush()
    last = WorkerLedger.query.filter_by(worker_id=worker_id) \
               .order_by(WorkerLedger.id.desc()).first()
    prev_balance = float(last.balance_after) if last else 0.0
    new_balance  = prev_balance - float(amount)  # advance reduces what we owe
 
    entry = WorkerLedger(
        worker_id      = worker_id,
        entry_date     = given_date,
        entry_type     = 'Advance',
        direction      = 'Debit',
        amount         = amount,
        reference_type = 'Advance',
        reference_id   = advance.id,
        balance_after  = new_balance,
        recorded_by    = current_user.id,
        notes          = notes or f'Advance given on {given_date}',
    )
    db.session.add(entry)
    db.session.commit()
    flash(f'Advance of ₹{amount:,.0f} recorded for {worker.name}.', 'success')
    return redirect(url_for('workers'))
@app.route('/worker/<int:worker_id>/settle', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def settle_worker(worker_id):
    worker = Worker.query.get_or_404(worker_id)
 
    # Current balance from ledger
    last = WorkerLedger.query.filter_by(worker_id=worker_id) \
               .order_by(WorkerLedger.id.desc()).first()
    current_balance = float(last.balance_after) if last else 0.0
 
    if current_balance <= 0:
        flash('No balance to settle.', 'warning')
        return redirect(url_for('workers'))
 
    amount_paid  = Decimal(request.form['amount'])
    notes        = request.form.get('notes', '').strip() or None
    new_balance  = current_balance - float(amount_paid)
 
    # ── Settlement ledger entry ──────────────────────────────────────────────
    entry = WorkerLedger(
        worker_id      = worker_id,
        entry_date     = date.today(),
        entry_type     = 'Settlement',
        direction      = 'Debit',
        amount         = amount_paid,
        reference_type = 'Manual',
        balance_after  = new_balance,
        recorded_by    = current_user.id,
        notes          = notes,
    )
    db.session.add(entry)
 
    # ── Auto-recover outstanding advances ────────────────────────────────────
    for advance in WorkerAdvance.query.filter_by(
        worker_id=worker_id,
    ).filter(WorkerAdvance.status.in_(['Outstanding', 'PartiallyRecovered'])).all():
        still_owed = float(advance.amount) - float(advance.recovered_amount)
        if still_owed <= 0:
            continue
        recover = min(still_owed, float(amount_paid))
        advance.recovered_amount = float(advance.recovered_amount) + recover
        if float(advance.recovered_amount) >= float(advance.amount):
            advance.status = 'Cleared'
        else:
            advance.status = 'PartiallyRecovered'
 
    # ── Mark all approved job cards as Paid ──────────────────────────────────
    approved_cards = JobCard.query.filter_by(worker_id=worker_id, status='Approved').all()
    for jc in approved_cards:
        jc.status = 'Paid'
        log_action(
            jc.project_id,
            f'Worker paid (settlement): {worker.name} — {jc.work_phase}',
            new_val=str(jc.final_amount),
        )
 
    db.session.commit()
    flash(
        f'Settlement of ₹{amount_paid:,.0f} recorded for {worker.name}. '
        f'Remaining balance: ₹{new_balance:,.0f}.',
        'success',
    )
    return redirect(url_for('workers'))
@app.route('/ledger/<int:entry_id>/void', methods=['POST'])
@login_required
@roles_required('admin')
def void_ledger_entry(entry_id):
    """
    Soft-delete a ledger entry by recalculating all balances after it.
    Simpler approach: add a reversal entry so the audit trail stays intact.
    """
    entry  = WorkerLedger.query.get_or_404(entry_id)
    worker = entry.worker
 
    # Add reversal entry (opposite direction, same amount)
    last = WorkerLedger.query.filter_by(worker_id=worker.id) \
               .order_by(WorkerLedger.id.desc()).first()
    prev_balance   = float(last.balance_after) if last else 0.0
    reverse_dir    = 'Debit' if entry.direction == 'Credit' else 'Credit'
    new_balance    = prev_balance - float(entry.amount) if entry.direction == 'Credit' \
                     else prev_balance + float(entry.amount)
 
    reversal = WorkerLedger(
        worker_id      = worker.id,
        entry_date     = date.today(),
        entry_type     = entry.entry_type,
        direction      = reverse_dir,
        amount         = entry.amount,
        reference_type = 'Reversal',
        reference_id   = entry.id,
        balance_after  = new_balance,
        recorded_by    = current_user.id,
        notes          = f'Reversal of entry #{entry.id}',
    )
    db.session.add(reversal)
    db.session.commit()
    flash(f'Ledger entry #{entry.id} reversed. Balance updated to ₹{new_balance:,.0f}.', 'warning')
    return redirect(url_for('workers'))
@app.route('/advance/<int:advance_id>/recover', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def recover_advance(advance_id):
    advance = WorkerAdvance.query.get_or_404(advance_id)
    still_owed = float(advance.amount) - float(advance.recovered_amount)
 
    recover_amount = float(request.form.get('recover_amount', still_owed))
    recover_amount = min(recover_amount, still_owed)  # cap at what's owed
 
    advance.recovered_amount = float(advance.recovered_amount) + recover_amount
    if float(advance.recovered_amount) >= float(advance.amount):
        advance.status = 'Cleared'
    else:
        advance.status = 'PartiallyRecovered'
 
    db.session.commit()
    flash(f'₹{recover_amount:,.0f} marked as recovered from advance.', 'success')
    return redirect(url_for('workers'))
@app.route('/projects/<int:pid>/materials/dispatch/<int:mid>', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def dispatch_material(pid, mid):
    proj     = Project.query.get_or_404(pid)
    material = Material.query.get_or_404(mid)
    progress = proj.onsite_progress

    # ── Hard lock ────────────────────────────────────────────────────────────
    if not progress or progress.structure_work_status != 'Completed':
        flash(
            'Materials cannot be dispatched until structure work is marked Completed.',
            'danger'
        )
        return redirect(url_for('project_detail', pid=pid))
    # ─────────────────────────────────────────────────────────────────────────

    material.dispatch_status = 'Dispatched'
    material.dispatch_date   = date.today()
    log_action(pid, f'Material dispatched: {material.item_name}', new_val='Dispatched')
    db.session.commit()
    flash(f'{material.item_name} marked as dispatched.', 'success')
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/materials/update/<int:mid>', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def update_material(pid, mid):
    proj = Project.query.get_or_404(pid)
    material = Material.query.get_or_404(mid)

    material.item_name = request.form.get('item_name', material.item_name)
    material.quantity  = float(request.form.get('quantity') or material.quantity or 0)

    if request.form.get('dispatch_date'):
        material.dispatch_date = date.fromisoformat(request.form['dispatch_date'])

    # preserve status — passed as hidden field, no change in logic
    material.dispatch_status = request.form.get('dispatch_status', material.dispatch_status)
    if material.dispatch_status == 'Delivered' and not material.received_date:
        material.received_date = date.today()

    material.notes = request.form.get('notes', material.notes)
    log_action(pid, f'Material updated: {material.item_name}', new_val=material.dispatch_status)
    db.session.commit()
    flash(f'{material.item_name} updated.', 'success')
    return redirect(url_for('onsite_progress', pid=pid))
@app.route('/projects/<int:pid>/materials/bulk_update', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def bulk_update_materials(pid):
    proj     = Project.query.get_or_404(pid)
    progress = proj.onsite_progress
    if not progress or progress.structure_work_status != 'Completed':
        flash('Materials cannot be updated until structure work is Completed.', 'danger')
        return redirect(url_for('onsite_progress', pid=pid))

    dispatch_status = request.form.get('dispatch_status')
    dispatch_date   = request.form.get('dispatch_date')

    for m in proj.materials:
        m.dispatch_status = dispatch_status
        if dispatch_date:
            m.dispatch_date = date.fromisoformat(dispatch_date)
        if dispatch_status == 'Delivered' and not m.received_date:
            m.received_date = date.today()

    log_action(pid, f'All materials bulk updated to {dispatch_status}')
    db.session.commit()
    flash(f'All materials marked as {dispatch_status}.', 'success')
    return redirect(url_for('onsite_progress', pid=pid))

@app.route('/projects/<int:pid>/materials/add', methods=['POST'])
@login_required
@roles_required('admin', 'onsite')
def add_material(pid):
    proj     = Project.query.get_or_404(pid)
    progress = proj.onsite_progress
    if not progress or progress.structure_work_status != 'Completed':
        flash('Materials cannot be added until structure work is marked Completed.', 'danger')
        return redirect(url_for('onsite_progress', pid=pid))
    material = Material(
        project_id      = pid,
        item_name       = request.form['item_name'],
        quantity        = float(request.form.get('quantity') or 0),
        dispatch_status = 'Pending',
        notes           = request.form.get('notes'),
    )
    db.session.add(material)
    log_action(pid, f'Material added: {material.item_name}', new_val='Pending')
    all_delivered=(
        len(proj.materials)>0 and all(m.dispatch_status == 'Delivered' for m in proj.materials)
    )
    if all_delivered:
        flash('All materials are already delivered. No new materials can be added.','danger')
        return redirect(url_for('onsite_progress',pid=pid))
    db.session.commit()
    flash(f'{material.item_name} added.', 'success')
    return redirect(url_for('onsite_progress', pid=pid))
# ─────────────────────────────────────────────────────────────────────────────
# SUBSIDY
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/projects/<int:pid>/subsidy', methods=['GET', 'POST'])
@login_required
def subsidy(pid):
    proj = Project.query.get_or_404(pid)
    sub  = proj.subsidy

    if request.method == 'POST':
        if current_user.role not in ['admin', 'payments','documents']:
            flash('Subsidy can be updated only by payments team', 'danger')
            return redirect(url_for('subsidy', pid=pid))

        if sub is None:
            sub = Subsidy(project_id=pid)
            db.session.add(sub)
            db.session.flush()

        exp = float(request.form.get('expected_amount') or sub.expected_amount or 78000)
        
        new_status=request.form.get('status',sub.status)
        if new_status == 'Received':
            rec=exp
        else:
            rec=float(request.form.get('received_amount') or sub.received_amount or 0)
        if rec>exp:
            flash(f'Received amount (₹{rec:,.0f}) cannot exceed expected amount (₹{exp:,.0f}).', 'danger')
            return redirect(url_for('subsidy',pid=pid))

        sub.status          = new_status
        sub.expected_amount = exp
        sub.received_amount = rec
        sub.notes           = request.form.get('notes')
        if request.form.get('request_date'):
            sub.request_date = date.fromisoformat(request.form['request_date'])

        customer_share = float(sub.customer_share or 0) if sub.customer_share else 0
        company_share  = float(sub.company_share  or 0) if sub.company_share  else 0
        if new_status == 'Received':
            customer_share = float(request.form.get('customer_share') or 0)
            company_share = float(request.form.get('company_share') or 0)
            if abs((customer_share + company_share) - rec)>0.01:
                flash(f'Customer share (₹{customer_share:,.0f}) + Company share (₹{company_share:,.0f})'
                      f'must equal received amount (₹{rec:,.0f}).', 'danger')
                return redirect(url_for('subsidy', pid=pid))
        sub.customer_share = customer_share
        sub.company_share  = company_share
        

        if sub.status == 'Processing':
            if proj.coordinator_id:
                create_notification(proj.coordinator_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Subsidy processing started by docs team.',
                'info')
            log_action(pid, 'Subsidy updated: Processing', new_val=sub.status)
        elif sub.status == 'Commissioned':
            payments_users = User.query.filter_by(role='payments', is_active=True).all()
            for u in payments_users:
                create_notification(u.id, pid,
                f'{proj.project_code} — {proj.customer.name}: Project commissioned. Please redeem the subsidy.',
                'task')
            if proj.coordinator_id:
                create_notification(proj.coordinator_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Project commissioned. Subsidy redemption pending.',
                'info')
            log_action(pid, 'Subsidy update: Project commissioned', new_val=sub.status)

        elif sub.status == 'Redeemed':
            if proj.doc_staff_id:
                create_notification(proj.doc_staff_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Subsidy redeemed by payments team. Please update Subsidy Redeem document.',
                'task')
            if proj.coordinator_id:
                create_notification(proj.coordinator_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Subsidy redeemed.',
                'info')
            log_action(pid, 'Subsidy updated: Redeemed', new_val=sub.status)

        elif sub.status == 'Received':
            if proj.coordinator_id:
                create_notification(proj.coordinator_id, pid,
                f'{proj.project_code} — {proj.customer.name}: Subsidy amount received.',
                'info')
            log_action(pid, 'Subsidy updated: Received', new_val=sub.status)
        db.session.flush()
        auto_advance_stage(proj)
        db.session.commit()
        flash('Subsidy record updated.', 'success')

    return render_template('subsidy.html', proj=proj, sub=sub)


# ─────────────────────────────────────────────────────────────────────────────
# APP INSTALLATION
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/installations')
@login_required
@roles_required('admin', 'appinstall','documents')
def installations():
    pending   = AppInstallation.query.filter_by(status='Pending').all()
    completed = AppInstallation.query.filter_by(status='Completed').all()
    return render_template('installations.html', pending=pending, completed=completed,today=date.today())


@app.route('/projects/<int:pid>/installation', methods=['POST'])
@login_required
@roles_required('admin', 'appinstall')
def update_installation(pid):
    proj    = Project.query.get_or_404(pid)
    install = proj.app_install or AppInstallation(project_id=pid)
    install.status         = request.form.get('status', install.status)
    install.scheduled_date = date.fromisoformat(request.form['scheduled_date']) if request.form.get('scheduled_date') else install.scheduled_date
    install.completed_date = date.fromisoformat(request.form['completed_date']) if request.form.get('completed_date') else install.completed_date
    install.installed_by   = current_user.id
    install.notes          = request.form.get('notes')
    if install.status == 'Completed':
        proj.status = 'Completed'
        proj.stage  = 'App Installation'
        log_action(pid, 'App installation completed', new_val='Completed')
    if not install.id:
        db.session.add(install)
    db.session.flush()
    auto_advance_stage(proj)
    db.session.commit()
    flash('Installation record updated.', 'success')
    return redirect(url_for('project_detail', pid=pid))


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — USER MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/admin/users')
@login_required
@roles_required('admin')
def manage_users():
    users = User.query.order_by(User.role, User.full_name).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/new', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def new_user():
    if request.method == 'POST':
        u = User(
            username  = request.form['username'],
            email     = request.form['email'],
            full_name = request.form['full_name'],
            role      = request.form['role'],
        )
        u.set_password(request.form['password'])
        db.session.add(u)
        db.session.commit()
        flash(f'User {u.username} created.', 'success')
        return redirect(url_for('manage_users'))
    return render_template('new_user.html')

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def edit_user(user_id):
    u = User.query.get_or_404(user_id)
    if request.method == 'POST':
        u.username  = request.form['username']
        u.email     = request.form['email']
        u.full_name = request.form['full_name']
        u.role      = request.form['role']
        if request.form.get('password'):        # only update if provided
            u.set_password(request.form['password'])
        db.session.commit()
        flash(f'User {u.username} updated.', 'success')
        return redirect(url_for('manage_users'))
    return render_template('edit_user.html', user=u)


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@roles_required('admin')
def delete_user(user_id):
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('manage_users'))
    db.session.delete(u)
    db.session.commit()
    flash(f'User {u.username} deleted.', 'success')
    return redirect(url_for('manage_users'))
@app.route('/admin/users/<int:user_id>/status', methods=['POST'])
@login_required
@roles_required('admin')
def change_user_status(user_id):
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash('You cannot change your own status.', 'danger')
        return redirect(url_for('manage_users'))

    new_status = request.form.get('status')
    if new_status not in ('active', 'inactive'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('manage_users'))

    u.status = new_status
    db.session.commit()
    flash(f'{u.username} marked as {new_status}.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/admin/analytics')
@login_required
@roles_required('admin')
def admin_analytics():
    from collections import defaultdict, Counter
    from datetime import timedelta
    import calendar

    today     = date.today()
    all_projs = Project.query.all()
    all_pays  = Payment.query.all()

    # ── Weekly (last 8 weeks) ──
    weekly_projects = defaultdict(int)
    weekly_payments = defaultdict(float)
    for i in range(7, -1, -1):
        week_start = today - timedelta(weeks=i)
        week_end   = today - timedelta(weeks=i - 1)
        label      = week_start.strftime('%d %b')
        weekly_projects[label] = sum(
            1 for p in all_projs
            if week_start <= p.created_at.date() < week_end
        )
        weekly_payments[label] = sum(
            float(p.amount) for p in all_pays
            if week_start <= p.payment_date < week_end
        )

    # ── Monthly (last 12 months) ──
    monthly_projects = defaultdict(int)
    monthly_payments = defaultdict(float)
    for i in range(11, -1, -1):
        ref_month = today.replace(day=1)
        for _ in range(i):
            ref_month = (ref_month - timedelta(days=1)).replace(day=1)
        label = ref_month.strftime('%b %Y')
        monthly_projects[label] = sum(
            1 for p in all_projs
            if p.created_at.year == ref_month.year
            and p.created_at.month == ref_month.month
        )
        monthly_payments[label] = sum(
            float(p.amount) for p in all_pays
            if p.payment_date.year == ref_month.year
            and p.payment_date.month == ref_month.month
        )

    # ── Yearly (last 5 years) ──
    yearly_projects = defaultdict(int)
    yearly_payments = defaultdict(float)
    for i in range(4, -1, -1):
        yr = today.year - i
        yearly_projects[str(yr)] = sum(
            1 for p in all_projs if p.created_at.year == yr
        )
        yearly_payments[str(yr)] = sum(
            float(p.amount) for p in all_pays if p.payment_date.year == yr
        )

    # ── Status & type breakdown ──
    status_counts = Counter(p.status for p in all_projs)
    type_counts   = Counter(p.project_type for p in all_projs)
    # ── Docs staff stats ──
    doc_staff_users = User.query.filter_by(role='documents', is_active=True).all()
    doc_staff_stats = []
    for staff in doc_staff_users:
        assigned    = [p for p in all_projs if p.doc_staff_id == staff.id]
        completed   = [p for p in assigned if p.status in ['Completed', 'Closed']]
        inprog      = [p for p in assigned if p.status == 'InProgress']
        not_started = [p for p in assigned if p.status == 'InProgress' and len(p.documents) == 0]
        total_docs  = sum(len(get_expected_docs(p.project_type,p.project_subtype,p.loan_subtype)) for p in assigned)
        done_docs   = sum(get_doc_completion(p)[0] for p in assigned)
        doc_staff_stats.append({
        'name':        staff.full_name,
        'assigned':    len(assigned),
        'completed':   len(completed),
        'inprog':      len(inprog),
        'not_started': len(not_started),
        'total_docs':  total_docs,
        'done_docs':   done_docs,
        'doc_pct':     int(done_docs / total_docs * 100) if total_docs > 0 else 0,
    })
    # ── Coordinator stats ──
    coordinators = User.query.filter_by(role='coordinator', is_active=True).all()
    coord_stats  = []
    for c in coordinators:
        cp = [p for p in all_projs if p.coordinator_id == c.id]
        coord_stats.append({
            'name':      c.full_name.split()[0],
            'total':     len(cp),
            'completed': sum(1 for p in cp if p.status in ['Completed', 'Closed']),
            'delayed':   sum(1 for p in cp if p.status == 'Delayed'),
            'collected': sum(float(p.collected_amount or 0) for p in cp),
        })

    # ── chart_data must be OUTSIDE the coordinator loop ──
    chart_data = {
        'weekly_labels':    list(weekly_projects.keys()),
        'weekly_projects':  list(weekly_projects.values()),
        'weekly_payments':  list(weekly_payments.values()),
        'monthly_labels':   list(monthly_projects.keys()),
        'monthly_projects': list(monthly_projects.values()),
        'monthly_payments': list(monthly_payments.values()),
        'yearly_labels':    list(yearly_projects.keys()),
        'yearly_projects':  list(yearly_projects.values()),
        'yearly_payments':  list(yearly_payments.values()),
        'status_labels':    list(status_counts.keys()),
        'status_counts':    list(status_counts.values()),
        'type_labels':      list(type_counts.keys()),
        'type_counts':      list(type_counts.values()),
        'coord_names':      [c['name']      for c in coord_stats],
        'coord_total':      [c['total']     for c in coord_stats],
        'coord_completed':  [c['completed'] for c in coord_stats],
        'coord_delayed':    [c['delayed']   for c in coord_stats],
        'coord_collected':  [c['collected'] for c in coord_stats],
        'staff_names':     [s['name'].split()[0]                          for s in doc_staff_stats],
        'staff_completed': [s['completed']                                for s in doc_staff_stats],
        'staff_inprog':    [s['inprog'] - s['not_started']                for s in doc_staff_stats],
        'staff_notstarted':[s['not_started']                              for s in doc_staff_stats],
        'staff_pending':   [s['assigned'] - s['completed']                for s in doc_staff_stats],
    }

    total_collected = sum(
        float(p.amount) for p in all_pays
        if p.project.status not in ['Cancelled', 'OnHold']
    )
    total_value     = sum(
        float(p.total_amount or 0) for p in all_projs
        if p.status not in ['Cancelled', 'OnHold']
    )
    
    return render_template('admin_analytics.html',
        total_projects  = len(all_projs),
        total_collected = total_collected,
        total_value     = total_value,
        total_pending   = total_value - total_collected,
        coord_stats     = coord_stats,
        chart_data      = chart_data,
        doc_staff_stats=doc_staff_stats,
    )
# ─────────────────────────────────────────────────────────────────────────────
# API — JSON ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/projects')
@login_required
def api_projects():
    projects_list = Project.query.join(Customer).all()
    return jsonify([{
        'id':           p.id,
        'code':         p.project_code,
        'customer':     p.customer.name,
        'status':       p.status,
        'stage':        p.stage,
        'kw':           float(p.system_kw),
        'type':         p.project_type,
        'collected':    float(p.collected_amount or 0),
        'total':        float(p.total_amount or 0),
        'payment_pct':  p.payment_pct,
        'days_open':    p.days_open,
    } for p in projects_list])


@app.route('/api/dashboard_stats')
@login_required
def api_dashboard_stats():
    return jsonify({
        'total':     Project.query.count(),
        'inprog':    Project.query.filter_by(status='InProgress').count(),
        'completed': Project.query.filter(Project.status.in_(['Completed','Closed'])).count(),
        'delayed':   Project.query.filter_by(status='Delayed').count(),
        'collected': float(db.session.query(db.func.sum(Payment.amount)).scalar() or 0),
    })
@app.route('/api/notifications')
@login_required
def api_notifications():
    notifs = Notification.query.filter_by(
        user_id=current_user.id,
    ).order_by(Notification.created_at.desc()).limit(40).all()
    return jsonify([{
        'id':         n.id,
        'message':    n.message,
        'type':       n.notif_type,
        'project_id': n.project_id,
        'code':       n.project.project_code,
        'created_at': n.created_at.strftime('%d %b %H:%M'),
        'is_read':    n.is_read,
        'action_url':n.action_url or f'/projects/{n.project_id}'
    } for n in notifs])


@app.route('/api/notifications/read/<int:nid>', methods=['POST'])
@login_required
def mark_notification_read(nid):
    n = Notification.query.get_or_404(nid)
    if n.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    n.is_read = True
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/notifications/read_all', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE FILTERS
# ─────────────────────────────────────────────────────────────────────────────

@app.template_filter('inr')
def inr_filter(value):
    try:
        return f'₹{float(value):,.0f}'
    except:
        return '₹0'

@app.template_filter('date_fmt')
def date_fmt(value):
    if not value:
        return '—'
    if isinstance(value, datetime):
        return value.strftime('%d %b %Y')
    return str(value)

"""
Standalone generator — called from Flask route.
Usage:
    from gen_coord_report import build_coordinator_monthly_report
    path = build_coordinator_monthly_report(coordinator, projects, year, month)
"""

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from openpyxl.utils import get_column_letter




# ── Palette ──────────────────────────────────────────────────────────────────
C_HEADER_BG   = '1A3C5E'   # dark navy
C_HEADER_FG   = 'FFFFFF'
C_SUBHDR_BG   = '2E6DA4'   # mid blue
C_SUBHDR_FG   = 'FFFFFF'
C_ACCENT_BG   = 'D6E4F0'   # light blue band
C_ALT_BG      = 'F2F7FB'   # alternating row
C_TOTAL_BG    = 'FFF3CD'   # amber total row
C_TOTAL_FG    = '856404'
C_BORDER      = 'BFCBD6'
C_GREEN_BG    = 'D4EDDA'
C_GREEN_FG    = '155724'
C_RED_BG      = 'F8D7DA'
C_RED_FG      = '721C24'
C_AMBER_BG    = 'FFF3CD'
C_AMBER_FG    = '856404'

STATUS_COLORS = {
    'Completed': (C_GREEN_BG, C_GREEN_FG),
    'Closed':    (C_GREEN_BG, C_GREEN_FG),
    'InProgress':('D1ECF1', '0C5460'),
    'Delayed':   (C_RED_BG,  C_RED_FG),
    'OnHold':    (C_AMBER_BG, C_AMBER_FG),
    'Cancelled': ('E2E3E5', '383D41'),
    'Lead':      ('E2E3E5', '383D41'),
}

def _fill(hex_color):
    return PatternFill('solid', start_color=hex_color, fgColor=hex_color)

def _font(bold=False, color='000000', size=10, italic=False):
    return Font(name='Arial', bold=bold, color=color, size=size, italic=italic)

def _border():
    side = Side(style='thin', color=C_BORDER)
    return Border(left=side, right=side, top=side, bottom=side)

def _center():
    return Alignment(horizontal='center', vertical='center', wrap_text=True)

def _left():
    return Alignment(horizontal='left', vertical='center', wrap_text=True)

def _right():
    return Alignment(horizontal='right', vertical='center')

def _inr(value):
    try:
        return float(value or 0)
    except:
        return 0.0

def _fmt_inr(ws, cell):
    cell.number_format = '₹#,##0;(₹#,##0);"-"'

def _style_header_cell(cell, text, bg=C_HEADER_BG, fg=C_HEADER_FG, size=10, center=True):
    cell.value = text
    cell.font  = _font(bold=True, color=fg, size=size)
    cell.fill  = _fill(bg)
    cell.border = _border()
    cell.alignment = _center() if center else _left()

def _style_data_cell(cell, value, bg='FFFFFF', fg='000000', bold=False,
                     align='left', number_fmt=None):
    cell.value = value
    cell.font  = _font(bold=bold, color=fg)
    cell.fill  = _fill(bg)
    cell.border = _border()
    cell.alignment = _center() if align == 'center' else (
                     _right()  if align == 'right'  else _left())
    if number_fmt:
        cell.number_format = number_fmt


# ─────────────────────────────────────────────────────────────────────────────
def build_coordinator_monthly_report(coordinator, all_projects, year, month,
                                     output_dir='/tmp'):
    """
    coordinator  : User ORM object
    all_projects : list of Project ORM objects for this coordinator
    year, month  : int
    Returns path to the generated .xlsx file.
    """
    month_name  = calendar.month_name[month]
    month_start = date(year, month, 1)
    month_end   = date(year, month, calendar.monthrange(year, month)[1])

    # Filter projects active/created this month
    month_projects = [
        p for p in all_projects
        if p.created_at.date() <= month_end
        and p.status not in ('Cancelled',)
    ]
    created_this_month = [
        p for p in all_projects
        if p.created_at.year == year and p.created_at.month == month
    ]

    wb = Workbook()

    # ── Sheet 1: Summary ─────────────────────────────────────────────────────
    ws = wb.active
    ws.title = 'Summary'
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = 'A6'
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize   = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage   = True
    ws.page_setup.fitToWidth  = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.horizontalCentered = True
    # Title block
    ws.merge_cells('A1:H1')
    c = ws['A1']
    c.value = 'Power On Plus Solar Solutions'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=14)
    c.fill  = _fill(C_HEADER_BG)
    c.alignment = _center()

    ws.merge_cells('A2:H2')
    c = ws['A2']
    c.value = f'Monthly Work Report — {month_name} {year}'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=11)
    c.fill  = _fill(C_SUBHDR_BG)
    c.alignment = _center()

    ws.merge_cells('A3:H3')
    c = ws['A3']
    c.value = f'Coordinator: {coordinator.full_name}'
    c.font  = _font(bold=False, color='333333', size=10, italic=True)
    c.fill  = _fill(C_ALT_BG)
    c.alignment = _center()

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 8  # spacer

    # ── KPI cards row ────────────────────────────────────────────────────────
    ws.row_dimensions[5].height = 20

    kpi_headers = [
        'New This Month', 'Active Projects', 'Completed',
        'Delayed', 'Total Value (₹)', 'Collected (₹)', 'Pending (₹)', 'Collection %'
    ]
    for col, h in enumerate(kpi_headers, 1):
        _style_header_cell(ws.cell(5, col), h, bg=C_SUBHDR_BG)

    active    = [p for p in month_projects if p.status in ('InProgress','Delayed','Lead','OnHold')]
    completed = [p for p in month_projects if p.status in ('Completed','Closed')]
    delayed   = [p for p in month_projects if p.status == 'Delayed']
    total_val = sum(_inr(p.total_amount) for p in month_projects)
    collected = sum(_inr(p.collected_amount) for p in month_projects)
    pending   = total_val - collected
    pct       = (collected / total_val * 100) if total_val else 0

    kpi_vals = [
        len(created_this_month), len(active), len(completed),
        len(delayed), total_val, collected, pending, pct / 100
    ]
    kpi_fmts = [
        None, None, None, None,
        '₹#,##0', '₹#,##0', '₹#,##0', '0.0%'
    ]
    kpi_bgs = [
        'FFFFFF','FFFFFF','FFFFFF','FFFFFF',
        'FFFFFF','FFFFFF','FFFFFF','FFFFFF'
    ]
    ws.row_dimensions[6].height = 20
    for col, (val, fmt) in enumerate(zip(kpi_vals, kpi_fmts), 1):
        cell = ws.cell(6, col)
        _style_data_cell(cell, val, align='center',
                         bold=True, number_fmt=fmt)

    # ── Project detail table ─────────────────────────────────────────────────
    ws.row_dimensions[7].height = 8   # spacer
    ws.row_dimensions[8].height = 20

    detail_headers = [
        'MNRE No.', 'Customer', 'Type', 'Subtype',
        'Stage', 'Status', 'Contract (₹)', 'Collected (₹)',
        'Pending (₹)', 'Doc Staff', 'Days Open', 'Created'
    ]
    # Extend merge for detail table (12 cols, need to widen)
    for col, h in enumerate(detail_headers, 1):
        _style_header_cell(ws.cell(8, col), h)

    row = 9
    for i, p in enumerate(sorted(month_projects, key=lambda x: x.created_at, reverse=True)):
        bg     = C_ALT_BG if i % 2 == 0 else 'FFFFFF'
        s_bg, s_fg = STATUS_COLORS.get(p.status, ('FFFFFF', '000000'))
        pend_val = _inr(p.total_amount) - _inr(p.collected_amount)

        ws.row_dimensions[row].height = 18
        vals = [
            p.project_code,
            p.customer.name,
            p.project_type,
            p.project_subtype or '—',
            p.stage,
            p.status,
            _inr(p.total_amount),
            _inr(p.collected_amount),
            pend_val,
            p.doc_staff.full_name if p.doc_staff else '—',
            p.days_open,
            p.created_at.strftime('%d %b %Y'),
        ]
        fmts = [None,None,None,None,None,None,
                '₹#,##0','₹#,##0','₹#,##0',
                None,None,None]
        aligns = ['center','left','center','center','center','center',
                  'right','right','right','left','center','center']

        for col, (val, fmt, aln) in enumerate(zip(vals, fmts, aligns), 1):
            cell = ws.cell(row, col)
            cell_bg = s_bg if col == 6 else bg
            cell_fg = s_fg if col == 6 else '000000'
            _style_data_cell(cell, val, bg=cell_bg, fg=cell_fg,
                             align=aln, number_fmt=fmt)
        row += 1

    # Totals row
    ws.row_dimensions[row].height = 20
    total_row_data = [
        'TOTAL', f'{len(month_projects)} projects', '', '', '', '',
        total_val, collected, pending, '', '', ''
    ]
    total_fmts = [None,None,None,None,None,None,
                  '₹#,##0','₹#,##0','₹#,##0',None,None,None]
    total_aligns = ['center','left','','','','',
                    'right','right','right','','','']
    for col, (val, fmt, aln) in enumerate(
            zip(total_row_data, total_fmts, total_aligns), 1):
        if val == '':
            cell = ws.cell(row, col)
            cell.fill   = _fill(C_TOTAL_BG)
            cell.border = _border()
            continue
        cell = ws.cell(row, col)
        _style_data_cell(cell, val, bg=C_TOTAL_BG, fg=C_TOTAL_FG,
                         bold=True, align=aln or 'center', number_fmt=fmt)

    # Column widths for summary sheet
    col_widths = [12, 24, 8, 10, 16, 12, 14, 14, 14, 18, 10, 13]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Sheet 2: Projects Created This Month ─────────────────────────────────
    ws2 = wb.create_sheet('New This Month')
    ws2.sheet_view.showGridLines = False
    ws2.page_setup.orientation = 'landscape'
    ws2.page_setup.paperSize   = ws2.PAPERSIZE_A4
    ws2.page_setup.fitToPage   = True
    ws2.page_setup.fitToWidth  = 1
    ws2.page_setup.fitToHeight = 0
    ws2.print_options.horizontalCentered = True
    _build_project_sheet(ws2, created_this_month,
                         f'New Projects — {month_name} {year}',
                         coordinator.full_name)

    # ── Sheet 3: Stage Breakdown ──────────────────────────────────────────────
    ws3 = wb.create_sheet('By Stage')
    ws3.sheet_view.showGridLines = False
    ws2.page_setup.orientation = 'landscape'
    ws2.page_setup.paperSize   = ws2.PAPERSIZE_A4
    ws2.page_setup.fitToPage   = True
    ws2.page_setup.fitToWidth  = 1
    ws2.page_setup.fitToHeight = 0
    ws2.print_options.horizontalCentered = True
    _build_stage_sheet(ws3, month_projects, month_name, year, coordinator.full_name)

    # ── Sheet 4: Payments This Month ─────────────────────────────────────────
    ws4 = wb.create_sheet('Payments')
    ws4.sheet_view.showGridLines = False
    ws2.page_setup.orientation = 'landscape'
    ws2.page_setup.paperSize   = ws2.PAPERSIZE_A4
    ws2.page_setup.fitToPage   = True
    ws2.page_setup.fitToWidth  = 1
    ws2.page_setup.fitToHeight = 0
    ws2.print_options.horizontalCentered = True
    _build_payments_sheet(ws4, month_projects, month_name, year,
                          coordinator.full_name, month_start, month_end)

    fname = (f'Report_{coordinator.username}_{year}_{month:02d}.xlsx'
             .replace(' ', '_'))
    path  = os.path.join(output_dir, fname)
    wb.save(path)
    return path


# ─────────────────────────────────────────────────────────────────────────────
def _build_project_sheet(ws, projects, title, coord_name):
    ws.merge_cells('A1:J1')
    c = ws['A1']
    c.value = title
    c.font  = _font(bold=True, color=C_HEADER_FG, size=12)
    c.fill  = _fill(C_HEADER_BG)
    c.alignment = _center()

    ws.merge_cells('A2:J2')
    c = ws['A2']
    c.value = f'Coordinator: {coord_name}'
    c.font  = _font(italic=True, color='444444')
    c.fill  = _fill(C_ALT_BG)
    c.alignment = _center()

    ws.row_dimensions[3].height = 8

    headers = ['MNRE No.','Customer','Type','Subtype','Stage','Status',
               'Contract (₹)','Collected (₹)','Pending (₹)','Doc Staff']
    for col, h in enumerate(headers, 1):
        _style_header_cell(ws.cell(4, col), h)

    for i, p in enumerate(projects, 0):
        row = i + 5
        bg  = C_ALT_BG if i % 2 == 0 else 'FFFFFF'
        s_bg, s_fg = STATUS_COLORS.get(p.status, ('FFFFFF','000000'))
        pend = _inr(p.total_amount) - _inr(p.collected_amount)
        data = [
            p.project_code, p.customer.name,
            p.project_type, p.project_subtype or '—',
            p.stage, p.status,
            _inr(p.total_amount), _inr(p.collected_amount), pend,
            p.doc_staff.full_name if p.doc_staff else '—',
        ]
        fmts   = [None,None,None,None,None,None,'₹#,##0','₹#,##0','₹#,##0',None]
        aligns = ['center','left','center','center','center','center',
                  'right','right','right','left']
        for col, (val, fmt, aln) in enumerate(zip(data, fmts, aligns), 1):
            cell   = ws.cell(row, col)
            c_bg   = s_bg if col == 6 else bg
            c_fg   = s_fg if col == 6 else '000000'
            _style_data_cell(cell, val, bg=c_bg, fg=c_fg, align=aln, number_fmt=fmt)
        ws.row_dimensions[row].height = 17

    col_widths = [12, 24, 8, 10, 16, 12, 14, 14, 14, 18]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _build_stage_sheet(ws, projects, month_name, year, coord_name):
    stages = ['Lead','Site Visit','Documentation','Onsite Work',
              'Connection','Subsidy','Payment']

    ws.merge_cells('A1:D1')
    c = ws['A1']
    c.value = f'Stage Breakdown — {month_name} {year}'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=12)
    c.fill  = _fill(C_HEADER_BG)
    c.alignment = _center()

    ws.merge_cells('A2:D2')
    c = ws['A2']
    c.value = f'Coordinator: {coord_name}'
    c.font  = _font(italic=True, color='444444')
    c.fill  = _fill(C_ALT_BG)
    c.alignment = _center()

    ws.row_dimensions[3].height = 8

    for col, h in enumerate(['Stage','Count','Total Value (₹)','Collected (₹)'], 1):
        _style_header_cell(ws.cell(4, col), h)

    row = 5
    for i, stage in enumerate(stages):
        sp = [p for p in projects if p.stage == stage]
        bg = C_ALT_BG if i % 2 == 0 else 'FFFFFF'
        data = [
            stage, len(sp),
            sum(_inr(p.total_amount) for p in sp),
            sum(_inr(p.collected_amount) for p in sp),
        ]
        fmts   = [None, None, '₹#,##0', '₹#,##0']
        aligns = ['left','center','right','right']
        for col, (val, fmt, aln) in enumerate(zip(data, fmts, aligns), 1):
            _style_data_cell(ws.cell(row, col), val, bg=bg,
                             align=aln, number_fmt=fmt)
        ws.row_dimensions[row].height = 17
        row += 1

    # Grand total
    for col, (val, fmt, aln) in enumerate(zip(
        ['TOTAL', len(projects),
         sum(_inr(p.total_amount) for p in projects),
         sum(_inr(p.collected_amount) for p in projects)],
        [None, None, '₹#,##0', '₹#,##0'],
        ['center','center','right','right']
    ), 1):
        _style_data_cell(ws.cell(row, col), val, bg=C_TOTAL_BG, fg=C_TOTAL_FG,
                         bold=True, align=aln, number_fmt=fmt)
    ws.row_dimensions[row].height = 20

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 10
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 18


def _build_payments_sheet(ws, projects, month_name, year, coord_name,
                          month_start, month_end):
    from datetime import date as d_

    ws.merge_cells('A1:G1')
    c = ws['A1']
    c.value = f'Payments — {month_name} {year}'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=12)
    c.fill  = _fill(C_HEADER_BG)
    c.alignment = _center()

    ws.merge_cells('A2:G2')
    c = ws['A2']
    c.value = f'Coordinator: {coord_name}'
    c.font  = _font(italic=True, color='444444')
    c.fill  = _fill(C_ALT_BG)
    c.alignment = _center()

    ws.row_dimensions[3].height = 8

    for col, h in enumerate(['MNRE No.','Customer','Date','Amount (₹)',
                              'Type','Source','Reference'], 1):
        _style_header_cell(ws.cell(4, col), h)

    all_pays = []
    for p in projects:
        for pay in p.payments:
            if month_start <= pay.payment_date <= month_end:
                all_pays.append((p, pay))

    all_pays.sort(key=lambda x: x[1].payment_date, reverse=True)

    for i, (p, pay) in enumerate(all_pays):
        row = i + 5
        bg  = C_ALT_BG if i % 2 == 0 else 'FFFFFF'
        data = [
            p.project_code,
            p.customer.name,
            pay.payment_date.strftime('%d %b %Y'),
            _inr(pay.amount),
            pay.payment_type,
            pay.payment_source,
            pay.reference_no or '—',
        ]
        fmts   = [None,None,None,'₹#,##0',None,None,None]
        aligns = ['center','left','center','right','center','center','center']
        for col, (val, fmt, aln) in enumerate(zip(data, fmts, aligns), 1):
            _style_data_cell(ws.cell(row, col), val, bg=bg,
                             align=aln, number_fmt=fmt)
        ws.row_dimensions[row].height = 17
        row += 1

    if all_pays:
        total_row = len(all_pays) + 5
        total_amt = sum(_inr(pay.amount) for _, pay in all_pays)
        for col in range(1, 8):
            cell = ws.cell(total_row, col)
            if col == 2:
                _style_data_cell(cell, f'{len(all_pays)} payments',
                                 bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True)
            elif col == 4:
                _style_data_cell(cell, total_amt, bg=C_TOTAL_BG, fg=C_TOTAL_FG,
                                 bold=True, align='right', number_fmt='₹#,##0')
            elif col == 1:
                _style_data_cell(cell, 'TOTAL', bg=C_TOTAL_BG, fg=C_TOTAL_FG,
                                 bold=True, align='center')
            else:
                cell.fill   = _fill(C_TOTAL_BG)
                cell.border = _border()
        ws.row_dimensions[total_row].height = 20

    col_widths = [12, 24, 14, 16, 12, 12, 18]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

def build_docstaff_monthly_report(staff, all_projects, year, month, output_dir='/tmp'):
    """
    staff        : User ORM object (role='documents')
    all_projects : list of Project ORM objects assigned to this staff
    year, month  : int
    Returns path to the generated .xlsx file.
    """
    month_name  = calendar.month_name[month]
    month_start = date(year, month, 1)
    month_end   = date(year, month, calendar.monthrange(year, month)[1])

    month_projects = [
        p for p in all_projects
        if p.created_at.date() <= month_end
        and p.status not in ('Cancelled',)
    ]
    created_this_month = [
        p for p in all_projects
        if p.created_at.year == year and p.created_at.month == month
    ]

    wb = Workbook()

    # ── Sheet 1: Summary ─────────────────────────────────────────────────────
    ws = wb.active
    ws.title = 'Summary'
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = 'A6'
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize   = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage   = True
    ws.page_setup.fitToWidth  = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.horizontalCentered = True

    ws.merge_cells('A1:H1')
    c = ws['A1']
    c.value = 'Power On Plus Solar Solutions'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=14)
    c.fill  = _fill(C_HEADER_BG)
    c.alignment = _center()

    ws.merge_cells('A2:H2')
    c = ws['A2']
    c.value = f'Documents Staff Monthly Report — {month_name} {year}'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=11)
    c.fill  = _fill(C_SUBHDR_BG)
    c.alignment = _center()

    ws.merge_cells('A3:H3')
    c = ws['A3']
    c.value = f'Staff: {staff.full_name}'
    c.font  = _font(bold=False, color='333333', size=10, italic=True)
    c.fill  = _fill(C_ALT_BG)
    c.alignment = _center()

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 8

    # ── KPI row ──────────────────────────────────────────────────────────────
    ws.row_dimensions[5].height = 20
    kpi_headers = [
        'Total Assigned', 'New This Month', 'Completed',
        'In Progress', 'Feasibility Done', 'Connection Done', 'Payment Done', 'Delayed'
    ]
    for col, h in enumerate(kpi_headers, 1):
        _style_header_cell(ws.cell(5, col), h, bg=C_SUBHDR_BG)

    completed_projs  = [p for p in month_projects if p.status in ('Completed', 'Closed')]
    inprog_projs     = [p for p in month_projects if p.status == 'InProgress']
    delayed_projs    = [p for p in month_projects if p.status == 'Delayed']

    def _doc_done(project, doc_name):
        doc_map = {d.doc_type: d for d in project.documents}
        return doc_map.get(doc_name) and doc_map[doc_name].status in ('Received', 'Sent', 'Completed')

    feasibility_done = sum(1 for p in month_projects if _doc_done(p, 'Feasibility Receipt'))
    connection_done  = sum(1 for p in month_projects if _doc_done(p, 'KSEB Connection'))
    payment_done     = sum(1 for p in month_projects if _doc_done(p, 'Payment Completion'))

    kpi_vals = [
        len(month_projects), len(created_this_month), len(completed_projs),
        len(inprog_projs), feasibility_done, connection_done, payment_done, len(delayed_projs)
    ]
    kpi_fmts = [None, None, None, None, None, None, None, None]

    ws.row_dimensions[6].height = 20
    for col, (val, fmt) in enumerate(zip(kpi_vals, kpi_fmts), 1):
        cell = ws.cell(6, col)
        _style_data_cell(cell, val, align='center', bold=True, number_fmt=fmt)

    # ── Project detail table ──────────────────────────────────────────────────
    ws.row_dimensions[7].height = 8
    ws.row_dimensions[8].height = 20

    detail_headers = [
        'MNRE No.', 'Customer', 'Type', 'Subtype', 'Stage', 'Status','MNRE',
        'Feasibility', 'Connection', 'Payment Compl.', 'Coordinator', 'Days Open', 'Created'
    ]
    for col, h in enumerate(detail_headers, 1):
        _style_header_cell(ws.cell(8, col), h)

    row = 9
    for i, p in enumerate(sorted(month_projects, key=lambda x: x.created_at, reverse=True)):
        bg = C_ALT_BG if i % 2 == 0 else 'FFFFFF'
        s_bg, s_fg = STATUS_COLORS.get(p.status, ('FFFFFF', '000000'))

        def _tick(project, doc_name):
            doc_map = {d.doc_type: d for d in project.documents}
            return '✓' if (doc_map.get(doc_name) and doc_map[doc_name].status in ('Received', 'Sent', 'Completed')) else '✗'

        f_done = _tick(p, 'Feasibility Receipt')
        c_done = _tick(p, 'KSEB Connection')
        pay_done = _tick(p, 'Payment Completion')
        mnre_done=_tick(p,'MNRE')

        ws.row_dimensions[row].height = 18
        vals = [
            p.project_code,
            p.customer.name,
            p.project_type,
            p.project_subtype or '—',
            p.stage,
            p.status,
            mnre_done,
            f_done,
            c_done,
            pay_done,
            p.coordinator.full_name if p.coordinator else '—',
            p.days_open,
            p.created_at.strftime('%d %b %Y'),
        ]
        fmts = [None, None, None, None, None, None, None, None, None, None, None, None, None]
        aligns = ['center', 'left', 'center', 'center', 'center', 'center',
                  'center', 'center', 'center', 'center', 'left', 'center', 'center']

        for col, (val, fmt, aln) in enumerate(zip(vals, fmts, aligns), 1):
            cell    = ws.cell(row, col)
            cell_bg = s_bg if col == 6 else bg
            cell_fg = s_fg if col == 6 else '000000'
            # Green/red tick coloring
            if col in (7, 8, 9,10):
                cell_bg = C_GREEN_BG if val == '✓' else C_RED_BG
                cell_fg = C_GREEN_FG if val == '✓' else C_RED_FG
            _style_data_cell(cell, val, bg=cell_bg, fg=cell_fg, align=aln, number_fmt=fmt)
        row += 1
    # Totals row
    ws.row_dimensions[row].height = 20
    for col in range(1, 13):
        cell = ws.cell(row, col)
        if col == 1:
            _style_data_cell(cell, 'TOTAL', bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True, align='center')
        elif col == 2:
            _style_data_cell(cell, f'{len(month_projects)} projects', bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True)
        elif col == 7:
            _style_data_cell(cell, sum(1 for p in month_projects if _doc_done(p, 'MNRE')),
                             bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True, align='center')
        elif col == 8:
            _style_data_cell(cell, feasibility_done, bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True, align='center')
        elif col == 9:
            _style_data_cell(cell, connection_done, bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True, align='center')
        elif col == 10:
            _style_data_cell(cell, payment_done, bg=C_TOTAL_BG, fg=C_TOTAL_FG, bold=True, align='center')
        else:
            cell.fill   = _fill(C_TOTAL_BG)
            cell.border = _border()

    col_widths = [12, 24, 8, 10, 16, 12, 8, 10, 10, 8, 20, 10, 13]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Sheet 2: Document Status Detail ──────────────────────────────────────
    ws2 = wb.create_sheet('Document Status')
    ws2.sheet_view.showGridLines = False
    ws2.page_setup.orientation = 'landscape'
    ws2.page_setup.paperSize   = ws2.PAPERSIZE_A4
    ws2.page_setup.fitToPage   = True
    ws2.page_setup.fitToWidth  = 1
    ws2.page_setup.fitToHeight = 0
    ws2.print_options.horizontalCentered = True

    ws2.merge_cells('A1:F1')
    c = ws2['A1']
    c.value = f'Document Status Detail — {month_name} {year}'
    c.font  = _font(bold=True, color=C_HEADER_FG, size=12)
    c.fill  = _fill(C_HEADER_BG)
    c.alignment = _center()

    ws2.merge_cells('A2:F2')
    c = ws2['A2']
    c.value = f'Staff: {staff.full_name}'
    c.font  = _font(italic=True, color='444444')
    c.fill  = _fill(C_ALT_BG)
    c.alignment = _center()

    ws2.row_dimensions[3].height = 8

    for col, h in enumerate(['MNRE No.', 'Customer', 'Document', 'Status', 'Received Date', 'Stage'], 1):
        _style_header_cell(ws2.cell(4, col), h)

    doc_row = 5
    for i, p in enumerate(sorted(month_projects, key=lambda x: x.created_at, reverse=True)):
        expected_docs = get_expected_docs(p.project_type, p.project_subtype, p.loan_subtype)
        doc_map       = {d.doc_type: d for d in p.documents}
        bg = C_ALT_BG if i % 2 == 0 else 'FFFFFF'

        for doc_name in expected_docs:
            doc_rec = doc_map.get(doc_name)
            status  = doc_rec.status if doc_rec else 'Pending'
            rec_date = doc_rec.received_date.strftime('%d %b %Y') if doc_rec and doc_rec.received_date else '—'

            if status in ('Received', 'Completed', 'Sent'):
                d_bg, d_fg = C_GREEN_BG, C_GREEN_FG
            else:
                d_bg, d_fg = C_RED_BG, C_RED_FG

            data   = [p.project_code, p.customer.name, doc_name, status, rec_date, p.stage]
            aligns = ['center', 'left', 'left', 'center', 'center', 'center']

            for col, (val, aln) in enumerate(zip(data, aligns), 1):
                cell    = ws2.cell(doc_row, col)
                cell_bg = d_bg if col == 4 else bg
                cell_fg = d_fg if col == 4 else '000000'
                _style_data_cell(cell, val, bg=cell_bg, fg=cell_fg, align=aln)
            ws2.row_dimensions[doc_row].height = 16
            doc_row += 1

    ws2.column_dimensions['A'].width = 12
    ws2.column_dimensions['B'].width = 24
    ws2.column_dimensions['C'].width = 28
    ws2.column_dimensions['D'].width = 12
    ws2.column_dimensions['E'].width = 14
    ws2.column_dimensions['F'].width = 16

    # ── Sheet 3: Stage Breakdown ──────────────────────────────────────────────
    ws3 = wb.create_sheet('By Stage')
    ws3.sheet_view.showGridLines = False
    ws3.page_setup.orientation = 'landscape'
    ws3.page_setup.paperSize   = ws3.PAPERSIZE_A4
    ws3.page_setup.fitToPage   = True
    ws3.page_setup.fitToWidth  = 1
    ws3.page_setup.fitToHeight = 0
    ws3.print_options.horizontalCentered = True
    _build_stage_sheet(ws3, month_projects, month_name, year, staff.full_name)

    # ── Sheet 4: New This Month ───────────────────────────────────────────────
    ws4 = wb.create_sheet('New This Month')
    ws4.sheet_view.showGridLines = False
    ws4.page_setup.orientation = 'landscape'
    ws4.page_setup.paperSize   = ws4.PAPERSIZE_A4
    ws4.page_setup.fitToPage   = True
    ws4.page_setup.fitToWidth  = 1
    ws4.page_setup.fitToHeight = 0
    ws4.print_options.horizontalCentered = True
    _build_project_sheet(ws4, created_this_month,
                         f'New Projects — {month_name} {year}',
                         staff.full_name)

    fname = f'DocsReport_{staff.username}_{year}_{month:02d}.xlsx'.replace(' ', '_')
    path  = os.path.join(output_dir, fname)
    wb.save(path)
    return path
@app.route('/admin/coordinator_reports')
@login_required
@roles_required('admin')
def coordinator_reports():
    coordinators = User.query.filter_by(role='coordinator', is_active=True).all()
    from datetime import date
    today = date.today()
    return render_template('coordinator_reports.html',
                           coordinators=coordinators,
                           current_year=today.year,
                           current_month=today.month)
 
 
@app.route('/admin/coordinator_reports/download')
@login_required
@roles_required('admin')
def download_coordinator_report():
    
 
    coord_id = request.args.get('coordinator_id', type=int)
    year     = request.args.get('year',  type=int)
    month    = request.args.get('month', type=int)
 
    if not all([coord_id, year, month]) or not (1 <= month <= 12):
        flash('Invalid report parameters.', 'danger')
        return redirect(url_for('coordinator_reports'))
 
    coordinator = User.query.get_or_404(coord_id)
    if coordinator.role != 'coordinator':
        flash('Selected user is not a coordinator.', 'danger')
        return redirect(url_for('coordinator_reports'))
 
    projects = Project.query.filter_by(coordinator_id=coord_id).all()
 
    path = build_coordinator_monthly_report(
        coordinator=coordinator,
        all_projects=projects,
        year=year,
        month=month,
        output_dir=tempfile.gettempdir(),
    )
 
    month_name = calendar.month_name[month]
    filename   = f'Report_{coordinator.username}_{month_name}_{year}.xlsx'
 
    return send_file(
        path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
@app.route('/admin/docstaff_reports')
@login_required
@roles_required('admin')
def docstaff_reports():
    staff_list = User.query.filter_by(role='documents', is_active=True).all()
    today = date.today()
    return render_template('docstaff_reports.html',
                           staff_list=staff_list,
                           current_year=today.year,
                           current_month=today.month)


@app.route('/admin/docstaff_reports/download')
@login_required
@roles_required('admin')
def download_docstaff_report():
    staff_id = request.args.get('staff_id', type=int)
    year     = request.args.get('year',     type=int)
    month    = request.args.get('month',    type=int)

    if not all([staff_id, year, month]) or not (1 <= month <= 12):
        flash('Invalid report parameters.', 'danger')
        return redirect(url_for('docstaff_reports'))

    staff = User.query.get_or_404(staff_id)
    if staff.role != 'documents':
        flash('Selected user is not a documents staff member.', 'danger')
        return redirect(url_for('docstaff_reports'))

    projects = Project.query.filter_by(doc_staff_id=staff_id).all()

    path = build_docstaff_monthly_report(
        staff        = staff,
        all_projects = projects,
        year         = year,
        month        = month,
        output_dir   = tempfile.gettempdir(),
    )

    month_name = calendar.month_name[month]
    filename   = f'DocsReport_{staff.username}_{month_name}_{year}.xlsx'

    return send_file(
        path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
# ─────────────────────────────────────────────────────────────────────────────
# DB INIT & SEED
# ─────────────────────────────────────────────────────────────────────────────

def seed_db():
    """Create default admin + sample users if DB is empty."""
    if User.query.count() == 0:
        roles_data = [
            ('admin',     'admin@poweronplus.in',    'Admin User',      'admin',       'admin123'),
            ('anita',     'anita@poweronplus.in',    'Anita Nair',      'coordinator', 'coord123'),
            ('vinod',     'vinod@poweronplus.in',    'Vinod Menon',     'coordinator', 'coord123'),
            ('sreeja',    'sreeja@poweronplus.in',   'Sreeja K',        'documents',   'docs123'),
            ('priya',     'priya@poweronplus.in',    'Priya Das',       'documents',   'docs123'),
            ('rajan',     'pay@poweronplus.in',      'Rajan P',         'payments',    'pay123'),
            ('suresh',    'onsite@poweronplus.in',   'Suresh K',        'onsite',      'site123'),
            ('appteam',   'app@poweronplus.in',      'App Team Lead',   'appinstall',  'app123'),
        ]
        for uname, email, fname, role, pwd in roles_data:
            u = User(username=uname, email=email, full_name=fname, role=role)
            u.set_password(pwd)
            db.session.add(u)

        workers_data = [
            ('Arun K', '9845001111', 'Panel Installation', 1200),
            ('Biju M', '9845002222', 'Electrical Work',    1200),
            ('Cijo P', '9845003333', 'Structural Work',    1200),
        ]
        for name, phone, skill, rate in workers_data:
            db.session.add(Worker(name=name, phone=phone, skill=skill, rate_per_day=rate))

        db.session.commit()
        print('✓ Database seeded with default users and workers.')
    if DocumentStage.query.count() == 0:
        seed_stages = [
            ('Customer KYC',         'always', 'ID Proof,Pass Book,Electricity Bill',              0),
            ('Bank / Loan file',     'loan_self','GEO Tag Photo,Bank Stamp Paper,Bank File',         1),
            ('Feasibility',          'always', 'Feasibility Receipt',                              2),
            ('KSEB filing',          'always', 'KSEB Stamp Paper,B-Class Licence,KSEB File',       3),
            ('Inspection & conn.',   'always', 'Inspection,CD Payment Receipt,KSEB Connection',    4),
            ('Subsidy',              'dcr',    'Subsidy Request,Subsidy Redeem',                   5),
            ('Project closure',      'always', 'Payment Completion,Warranty Card,App Installation',6),
        ]
        for name, cond, docs, order in seed_stages:
            db.session.add(DocumentStage(
                name=name, condition=cond, docs=docs, sort_order=order
            ))
        db.session.commit()
        print('Document stages seeded.')


@app.cli.command('mark_delayed')
def mark_delayed():
    """Mark InProgress projects as Delayed if older than 30 days."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    stale  = Project.query.filter(
        Project.status == 'InProgress',
        Project.created_at <= cutoff,
    ).all()
    count = 0
    for proj in stale:
        proj.status = 'Delayed'
        count += 1
    db.session.commit()
    print(f'✓ Marked {count} project(s) as Delayed.')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_db()
    app.run(debug=True, port=5000)
