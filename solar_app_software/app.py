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
    amount_paid = db.Column(db.Numeric(10, 2), default=0)
    status      = db.Column(db.Enum('Assigned','Active','Completed','Paid'), default='Assigned')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


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
    entry = ProjectLog(
        project_id=project_id,
        action=action,
        old_value=str(old_val) if old_val else None,
        new_value=str(new_val) if new_val else None,
        done_by=current_user.id
    )
    db.session.add(entry)


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
        data['projects']  = my_projects
        data['projects_with_counts']=projects_with_counts
        data['queue']     = len(data['projects'])
        data['new_projects'] = new_projects
        data['new_count']=len(new_projects)
        data['completed_projects']=completed_projects
        data['completed_count']=len(completed_projects)

    elif role == 'payments':
        data['total_collected'] = float(db.session.query(db.func.sum(Payment.amount)).scalar() or 0)
        total_amt               = float(db.session.query(db.func.sum(Project.total_amount)).scalar() or 0)
        data['total_pending']   = total_amt - data['total_collected']
        data['projects']        = Project.query.filter(Project.status.notin_(['Closed'])).all()

    elif role == 'onsite':
        data['projects']  = Project.query.filter(Project.status.in_(['InProgress','Delayed'])).all()
        data['workers']   = Worker.query.filter_by(is_active=True).all()

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
            stage          = 'Site Visit Done',
            total_amount   = float(request.form.get('total_amount', 0)),
            coordinator_id = current_user.id,
            doc_staff_id   = request.form.get('doc_staff_id') or None,
            notes          = request.form.get('notes'),
        )
        db.session.add(proj)
        db.session.flush()
        log_action(proj.id, 'Project created', new_val='Created')
        db.session.commit()
        flash(f'Project {proj.project_code} created successfully!', 'success')
        return redirect(url_for('project_detail', pid=proj.id))

    return render_template('new_project.html', customers=customers,
                            doc_staff=doc_staff)


@app.route('/projects/<int:pid>')
@login_required
def project_detail(pid):
    proj     = Project.query.get_or_404(pid)
    logs     = ProjectLog.query.filter_by(project_id=pid).order_by(ProjectLog.created_at.desc()).distinct(ProjectLog.id).all()
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
    if new_status:
        proj.status = new_status
    if new_stage:
        proj.stage = new_stage
    log_action(pid, 'Status updated', old_val=old_status, new_val=new_status or proj.status)
    db.session.commit()
    flash('Project status updated.', 'success')
    return redirect(url_for('project_detail', pid=pid))

@app.route('/coordinator/analytics')
@login_required
@roles_required('coordinator')
def coordinator_analytics():
    from collections import Counter
    import json
    my_projects     = Project.query.filter_by(coordinator_id=current_user.id).all()
    my_project_ids  = [p.id for p in my_projects]

    doc_staff_users = User.query.filter_by(role='documents', is_active=True).all()
    doc_analytics   = []
    for staff in doc_staff_users:
        assigned    = [p for p in my_projects if p.doc_staff_id == staff.id]
        completed   = [p for p in assigned if p.status in ['Completed', 'Closed']]
        inprog      = [p for p in assigned if p.status == 'InProgress']
        not_started = [p for p in assigned if p.status == 'InProgress' and len(p.documents) == 0]
        total_docs  = sum(len(get_expected_docs(p.project_type)) for p in assigned)
        done_docs   = sum(get_doc_completion(p)[0] for p in assigned)

        # ── Build per-project details ──
        project_details = []
        for p in assigned:
            done, total = get_doc_completion(p)
            project_details.append({
                'project':    p,
                'done_docs':  done,
                'total_docs': total,
                'doc_pct':    int(done / total * 100) if total > 0 else 0,
            })

        doc_analytics.append({
            'staff':           staff,
            'assigned':        len(assigned),
            'completed':       len(completed),
            'inprog':          len(inprog),
            'not_started':     len(not_started),
            'total_docs':      total_docs,
            'done_docs':       done_docs,
            'doc_pct':         int(done_docs / total_docs * 100) if total_docs > 0 else 0,
            'project_details': project_details,
        })

    unassigned_projects = [p for p in my_projects if not p.doc_staff_id]

    stage_order  = [
        'Lead', 'Site Visit', 'Project Confirmation', 'Documentation',
        'Bank/Feasibility', 'Structure Work', 'Material Delivery',
        'KSEB Processing', 'Inspection', 'Connection',
        'Subsidy', 'App Installation', 'Final Payment', 'Warranty Issued'
    ]
    stage_counts = Counter(p.stage for p in my_projects)
    stage_data   = [{'stage': s, 'count': stage_counts.get(s, 0)} for s in stage_order]

    total_value     = sum(float(p.total_amount or 0) for p in my_projects)
    total_collected = sum(float(p.collected_amount or 0) for p in my_projects)
    subsidy_list    = Subsidy.query.filter(Subsidy.project_id.in_(my_project_ids)).all() if my_project_ids else []

    chart_data = {
        'staff_names':  [a['staff'].full_name.split()[0] for a in doc_analytics],
        'done_docs':    [a['done_docs']                   for a in doc_analytics],
        'pending_docs': [a['total_docs'] - a['done_docs'] for a in doc_analytics],
        'completed':    [a['completed']                   for a in doc_analytics],
        'inprog':       [a['inprog']                      for a in doc_analytics],
        'not_started':  [a['not_started']                 for a in doc_analytics],
        'stage_labels': [s['stage'] for s in stage_data if s['count'] > 0],
        'stage_counts': [s['count'] for s in stage_data if s['count'] > 0],
    }

    return render_template('coordinator_analytics.html',
        my_projects         = my_projects,
        doc_analytics       = doc_analytics,
        unassigned_projects = unassigned_projects,
        stage_data          = stage_data,
        total_value         = total_value,
        total_collected     = total_collected,
        subsidy_list        = subsidy_list,
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
        flash('This project is not assigned to you.','danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        doc_type = request.form['doc_type']
        status   = request.form.get('status', 'Pending')

        # Update existing or create new
        existing = Document.query.filter_by(
            project_id=pid, doc_type=doc_type
        ).first()

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
    
    start=request.form.get('start_date')
    end=request.form.get('end_date')
    days=0
    if start and end:
        
        d1 = date.fromisoformat(start)
        d2 = date.fromisoformat(end)
        days = max((d2 - d1).days + 1,0)
    wa = WorkerAssignment(
        project_id = pid,
        worker_id  = request.form['worker_id'],
        start_date = date.fromisoformat(start) if start else None,
        end_date = date.fromisoformat(end) if end else None,
        days_worked=days,
        status     = 'Completed' if (end and end <= str(date.today())) else 'Active' if start else 'Assigned',
    )
    db.session.add(wa)
    log_action(pid, f'Worker assigned: ID {request.form["worker_id"]}',new_val=wa.status)
    db.session.commit()
    flash('Worker assigned.', 'success')
    return redirect(url_for('project_detail', pid=pid))
@app.route('/projects/<int:pid>/update_assignment/<int:aid>',methods=['POST'])
@login_required
@roles_required('admin','onsite')
def update_assignment(pid,aid):
    wa = WorkerAssignment.query.get_or_404(aid)
    start = request.form.get('start_date')
    end = request.form.get('end_date')

    if start:
        wa.start_date=date.fromisoformat(start)
    if end:
        wa.end_date=date.fromisoformat(end)
    if start and end:
        wa.days_worked=max((date.fromisoformat(end) - date.fromisoformat(start)).days + 1,0)
    wa.status = request.form.get('status',wa.status)
    wa.amount_paid=float(request.form.get('amount_paid',wa.amount_paid or 0))
    log_action(pid, f'Worker assignment updated: {wa.worker.name}', new_val=wa.status)
    db.session.commit()
    flash(f'Assignment for {wa.worker.name} updated.', 'success')
    return redirect(url_for('project_detail', pid=pid))


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
