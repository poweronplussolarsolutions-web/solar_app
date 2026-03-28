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
from datetime import datetime, date
import os

DOCUMENT_STAGES = [
    {
        'name':'Customer KYC',
        'condition':'always',
        'docs':['ID Proof','Pass Book','Electricity Bill']
    },
    {
        'name':'Bank / Loan file',
         'condition':'loan',
         'docs':['GEO Tag Photo','Bank Stamp Paper','Bank File']
    },
    {
        'name':'Feasibility',
        'condition':'always',
        'docs':['Feasibility Receipt']
    },
    {
        'name':'KSEB filing',
        'condition':'always',
        'docs':['KSEB Stamp Paper','B-Class Licence','KSEB File']
    },
    {
        'name':'Inspection & connection',
        'condition':'always',
        'docs':['Inspection','CD Payment Receipt','KSEB Connection']
    },
    {
        'name':'Subsidy',
        'condition':'always',
        'docs':['Subsidy Request','Subsidy Redeem']
    },
    {
        'name':'Project closure',
        'condition':'always',
        'docs':['Payment Completion','Warranty Card','Final Invoice']
    },
]
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
    'Lead':'Created',
    'Site Visit':'Created',
    'Documentation':'InProgress',
    'Onsite Work':'InProgress',
    'Connection':'InProgress',
    'Subsidy':'InProgress',
    'Payment':'InProgress',
}
def get_expected_docs(project_type):
    """Return full list of expected document names for a project type."""
    docs = []
    for stage in DOCUMENT_STAGES:
        if stage['condition'] == 'always' or project_type == 'Loan':
            docs.extend(stage['docs'])
    return docs


def get_doc_completion(project):
    """
    Returns (done, total) based on expected docs for the project type,
    not just what has been recorded.
    """
    expected   = get_expected_docs(project.project_type)
    recorded   = {d.doc_type: d for d in project.documents}
    done_count = sum(
        1 for doc_name in expected
        if doc_name in recorded and recorded[doc_name].status in ['Received', 'Sent','Completed']
    )
    return done_count, len(expected)
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
    system_kw        = db.Column(db.Numeric(6, 2), nullable=False)
    project_type     = db.Column(db.Enum('Loan', 'Cash'), nullable=False)
    status           = db.Column(db.Enum('Lead','Created','InProgress','Completed','Delayed','Pending','Closed'), default='Lead')
    stage            = db.Column(db.String(100), default='Lead')
    total_amount     = db.Column(db.Numeric(12, 2), default=0)
    collected_amount = db.Column(db.Numeric(12, 2), default=0)
    coordinator_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    doc_staff_id     = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    coordinator = db.relationship('User', foreign_keys=[coordinator_id], backref='coordinated_projects')
    doc_staff   = db.relationship('User', foreign_keys=[doc_staff_id],   backref='doc_projects')
    payments    = db.relationship('Payment',        backref='project', lazy=True)
    documents   = db.relationship('Document',       backref='project', lazy=True)
    logs        = db.relationship('ProjectLog',     backref='project', lazy=True)
    materials   = db.relationship('Material',       backref='project', lazy=True)
    assignments = db.relationship('WorkerAssignment', backref='project', lazy=True)

    @property
    def pending_amount(self):
        return float(self.total_amount or 0) - float(self.collected_amount or 0)

    @property
    def payment_pct(self):
        t = float(self.total_amount or 0)
        if t == 0:
            return 0
        return int(float(self.collected_amount or 0) / t * 100)

    @property
    def days_open(self):
        return (datetime.utcnow().date() - self.created_at.date()).days
    
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
    payments=db.relationship('WorkerPayment',backref='assignement',lazy=True)
class WorkerPayment(db.Model):
    __tablename__ = 'worker_payments'
    id            = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('worker_assignments.id'), nullable=False)
    project_id    = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    week_start    = db.Column(db.Date, nullable=False)
    week_end      = db.Column(db.Date, nullable=False)
    days_worked   = db.Column(db.Integer, default=0)
    rate_per_day  = db.Column(db.Numeric(8, 2), default=0)
    amount        = db.Column(db.Numeric(10, 2), nullable=False)
    paid_date     = db.Column(db.Date, nullable=False)
    paid_by       = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes         = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    project       = db.relationship('Project', foreign_keys=[project_id])
    payer         = db.relationship('User', foreign_keys=[paid_by])
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
    status          = db.Column(db.Enum('NotStarted','Requested','Processing','Received'), default='NotStarted')
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
    last = Project.query.order_by(Project.id.desc()).first()
    num = (last.id + 1) if last else 1
    return f'P{num:04d}'


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
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash(f'Welcome, {user.full_name}!', 'success')
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
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

@app.route('/dashboard')
@login_required
def dashboard():
    role = current_user.role
    data = {}

    if role == 'admin':
        data['total']     = Project.query.count()
        data['inprog']    = Project.query.filter_by(status='InProgress').count()
        data['completed'] = Project.query.filter(Project.status.in_(['Completed','Closed'])).count()
        data['delayed']   = Project.query.filter_by(status='Delayed').count()
        data['projects']  = Project.query.order_by(Project.updated_at.desc()).limit(10).all()
        payments          = db.session.query(db.func.sum(Payment.amount)).scalar() or 0
        data['collected'] = float(payments)
        total_amt         = db.session.query(db.func.sum(Project.total_amount)).scalar() or 0
        data['total_amt'] = float(total_amt)

    elif role == 'coordinator':
        my_projects=Project.query.filter_by(coordinator_id=current_user.id).order_by(Project.updated_at.desc()).all()
        my_project_ids=[p.id for p in my_projects]
        total_value = sum(float(p.total_amount or 0) for p in my_projects)
        total_collected=sum(float(p.collected_amount or 0) for p in my_projects)
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
        my_projects = Project.query.filter_by(doc_staff_id=current_user.id).order_by(Project.updated_at.desc()).all()
        new_projects=[p for p in my_projects if p.status == 'InProgress' and len(p.documents)== 0]
        completed_projects=[p for p in my_projects if p.status in ['Completed','Closed']]
        projects_with_counts = []
        for p in my_projects:
            done, total = get_doc_completion(p)
            projects_with_counts.append({
            'project':   p,
            'done_docs': done,
            'total_docs': total,
            'doc_pct':   int(done / total * 100) if total > 0 else 0,
        })
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
        data['total_collected'] = float(db.session.query(db.func.sum(Payment.amount)).scalar() or 0)
        total_amt               = float(db.session.query(db.func.sum(Project.total_amount)).scalar() or 0)
        data['total_pending']   = total_amt - data['total_collected']
        data['projects']        = Project.query.filter(Project.status.notin_(['Closed'])).all()

    elif role == 'onsite':
        feasibility_project_ids=db.session.query(Document.project_id).filter(
            Document.doc_type == 'Feasibility Receipt',
            Document.status.in_(['Received', 'Completed']),
        ).subquery()
        data['projects']  = Project.query.filter(Project.status.in_(['InProgress','Delayed']),Project.id.in_(feasibility_project_ids),).all()
        data['workers']   = Worker.query.filter_by(is_active=True).all()
        data['tasks'] = Notification.query.filter_by(
            user_id = current_user.id,
            notif_type='task',
            is_read=False,
        ).order_by(Notification.created_at.desc()).all()

    elif role == 'appinstall':
        data['installs']  = AppInstallation.query.filter_by(status='Pending').all()
        data['completed'] = AppInstallation.query.filter_by(status='Completed').count()

    return render_template('dashboard.html', data=data)


# ─────────────────────────────────────────────────────────────────────────────
# PROJECTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/projects')
@login_required
def projects():
    status_filter = request.args.get('status', '')
    search        = request.args.get('q', '')
    q = Project.query.join(Customer)
    if current_user.role=='coordinator':
        q=q.filter(Project.coordinator_id==current_user.id)
    if status_filter:
        q = q.filter(Project.status == status_filter)
    if search:
        q = q.filter(Customer.name.ilike(f'%{search}%') | Project.project_code.ilike(f'%{search}%'))
    projects_list = q.order_by(Project.updated_at.desc()).all()
    return render_template('projects.html', projects=projects_list,
                           status_filter=status_filter, search=search)


@app.route('/projects/new', methods=['GET', 'POST'])
@login_required
@roles_required('coordinator')
def new_project():
    customers   = Customer.query.order_by(Customer.name).all()
    
    doc_staff   = User.query.filter_by(role='documents',    is_active=True).all()

    if request.method == 'POST':
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
            project_code   = next_project_code(),
            customer_id    = cust_id,
            system_kw      = float(request.form['system_kw']),
            project_type   = request.form['project_type'],
            status         = 'Created',
            stage          = 'Lead',
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
                message=f'You have been assigned to {proj.project_code}-{proj.customer.name}({proj.project_type},{proj.system_kw} kW).',
                notif_type='task',
            )
        db.session.commit()
        flash(f'Project {proj.project_code} created successfully!', 'success')
        return redirect(url_for('project_detail', pid=proj.id))

    return render_template('new_project.html', customers=customers,
                            doc_staff=doc_staff)


@app.route('/projects/<int:pid>')
@login_required
def project_detail(pid):
    proj     = Project.query.get_or_404(pid)
    logs     = ProjectLog.query.filter_by(project_id=pid).order_by(ProjectLog.created_at.desc()).all()
    workers  = Worker.query.filter_by(is_active=True).all()
    all_workers = Worker.query.filter_by(is_active=True).all()
    worker_rate = {str(w.id):float(w.rate_per_day or 0) for w in all_workers}
    return render_template('project_detail.html', proj=proj, logs=logs,
                           workers=workers, all_workers=all_workers,worker_rate=worker_rate)


@app.route('/projects/<int:pid>/update_status', methods=['POST'])
@login_required
def update_status(pid):
    proj       = Project.query.get_or_404(pid)
    new_status = request.form.get('status')
    new_stage  = request.form.get('stage')
    old_status = proj.status
    
    if new_stage:
        proj.stage = new_stage
        if not new_status:
            new_status=STAGE_STATUS_MAP.get(new_stage,proj.status)
    if new_status:
        proj.status = new_status
    log_action(pid, 'Status updated', old_val=old_status, new_val= proj.status)
    db.session.commit()
    flash('Project status updated.', 'success')
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
        total_docs  = sum(len(get_expected_docs(p.project_type)) for p in assigned)
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
    amount = float(request.form['amount'])

    if proj.project_type == 'Loan':
        source      = 'Bank'
        instalment  = request.form.get('instalment')
        existing    = [p.instalment for p in proj.payments if p.payment_source == 'Bank']
        if instalment in existing:
            flash(f'{instalment} bank payment already recorded for this project.', 'danger')
            return redirect(url_for('project_detail', pid=pid))
    else:
        source     = 'Customer'
        instalment = None

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
    db.session.commit()
    flash(f'Payment of ₹{amount:,.0f} recorded.', 'success')
    return redirect(url_for('project_detail', pid=pid))


@app.route('/payments')
@login_required
@roles_required('admin', 'payments')
def payments_dashboard():
    total_collected = float(db.session.query(db.func.sum(Payment.amount)).scalar() or 0)
    total_value     = float(db.session.query(db.func.sum(Project.total_amount)).scalar() or 0)
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(20).all()
    pending_projs   = Project.query.filter(Project.status.notin_(['Closed'])).all()
    return render_template('payments.html',
                           total_collected=total_collected,
                           total_pending=total_value - total_collected,
                           total_value=total_value,
                           recent_payments=recent_payments,
                           pending_projs=pending_projs)


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/projects/<int:pid>/documents', methods=['GET', 'POST'])
@login_required
def documents(pid):
    proj = Project.query.get_or_404(pid)
    if current_user.role == 'documents' and proj.doc_staff_id != current_user.id:
        flash('This project is not assigned to you.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
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

        db.session.commit()
        flash(f'{doc_type} — {status}.', 'success')

    return render_template('documents.html', proj=proj)
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
        log_action(pid, 'KSEB tasks updated')
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
    return render_template('workers.html', workers=all_workers)


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
    log_action(pid, f'Worker assigned: ID {request.form["worker_id"]}',new_val=wa.status)
    db.session.commit()
    flash('Worker assigned.', 'success')
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
@app.route('/projects/<int:pid>/worker_payment', methods=['POST'])
@login_required
@roles_required('admin', 'onsite', 'payments')
def add_worker_payment(pid):
    assignment_id = int(request.form['assignment_id'])
    wa            = WorkerAssignment.query.get_or_404(assignment_id)
    days          = int(request.form.get('days_worked') or 0)
    rate          = float(request.form.get('rate_per_day') or wa.worker.rate_per_day or 0)
    amount        = float(request.form.get('amount') or (days * rate))

    wp = WorkerPayment(
        assignment_id = assignment_id,
        project_id    = pid,
        week_start    = date.fromisoformat(request.form['week_start']),
        week_end      = date.fromisoformat(request.form['week_end']),
        days_worked   = days,
        rate_per_day  = rate,
        amount        = amount,
        paid_date     = date.fromisoformat(request.form['paid_date']),
        paid_by       = current_user.id,
        notes         = request.form.get('notes'),
    )
    db.session.add(wp)
    log_action(pid, f'Worker payment: {wa.worker.name} ₹{amount:,.0f}', new_val=str(amount))
    db.session.commit()
    flash(f'Payment of ₹{amount:,.0f} recorded for {wa.worker.name}.', 'success')
    return redirect(url_for('project_detail', pid=pid))
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

        db.session.commit()
        flash('Onsite progress updated.', 'success')

    return render_template('onsite_progress.html', proj=proj, progress=progress)
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
    sub  = proj.subsidy or Subsidy(project_id=pid)

    if request.method == 'POST':
        sub.status          = request.form.get('status', sub.status)
        sub.expected_amount = float(request.form.get('expected_amount', sub.expected_amount or 0))
        sub.received_amount = float(request.form.get('received_amount', sub.received_amount or 0))
        sub.request_date    = date.fromisoformat(request.form['request_date']) if request.form.get('request_date') else sub.request_date
        sub.notes           = request.form.get('notes')
        if not sub.id:
            db.session.add(sub)
        log_action(pid, 'Subsidy updated', new_val=sub.status)
        db.session.commit()
        flash('Subsidy record updated.', 'success')
    return render_template('subsidy.html', proj=proj, sub=sub)


# ─────────────────────────────────────────────────────────────────────────────
# APP INSTALLATION
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/installations')
@login_required
@roles_required('admin', 'appinstall', 'documents')
def installations():
    pending   = AppInstallation.query.filter_by(status='Pending').all()
    completed = AppInstallation.query.filter_by(status='Completed').all()
    return render_template('installations.html', pending=pending, completed=completed)


@app.route('/projects/<int:pid>/installation', methods=['POST'])
@login_required
@roles_required('admin', 'appinstall', 'documents')
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
    }

    total_collected = sum(float(p.amount) for p in all_pays)
    total_value     = sum(float(p.total_amount or 0) for p in all_projs)

    return render_template('admin_analytics.html',
        total_projects  = len(all_projs),
        total_collected = total_collected,
        total_value     = total_value,
        total_pending   = total_value - total_collected,
        coord_stats     = coord_stats,
        chart_data      = chart_data,
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
        user_id=current_user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify([{
        'id':         n.id,
        'message':    n.message,
        'type':       n.notif_type,
        'project_id': n.project_id,
        'code':       n.project.project_code,
        'created_at': n.created_at.strftime('%d %b %H:%M'),
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


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
