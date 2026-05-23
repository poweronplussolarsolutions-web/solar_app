# Power on Plus Solar Solutions — Office Management System

A full-stack Flask web application for managing solar installation projects,
built for Power on Plus Solar Solutions, Kerala.

---

## Tech Stack

- **Backend**: Python 3.10+ / Flask
- **Database**: MySQL (via SQLAlchemy + PyMySQL)
- **Auth**: Flask-Login with role-based access control
- **Frontend**: Jinja2 HTML templates (no JS framework needed)

---

## Project Structure

```
solar_app/
├── app.py                  # Main Flask app — models, routes, config
├── requirements.txt
├── migrations/
│   └── schema.sql          # Raw MySQL schema + seed data
└── templates/
    ├── base.html           # Layout with sidebar navigation
    ├── login.html          # Login page
    ├── dashboard.html      # Role-aware dashboard
    ├── projects.html       # Project list with filters
    ├── project_detail.html # Full project view
    ├── new_project.html    # Create project form
    ├── payments.html       # Payments dashboard
    ├── documents.html      # Document checklist
    ├── kseb.html           # KSEB tasks form
    ├── subsidy.html        # Subsidy tracking
    ├── workers.html        # Worker roster
    ├── installations.html  # App installation tracker
    ├── admin_users.html    # User management
    ├── new_user.html       # Create user form
    └── _project_table.html # Reusable table partial
```

---

## Setup Instructions

### 1. Install Python dependencies

```bash
cd solar_app
pip install -r requirements.txt
```

### 2. Create MySQL database

```bash
mysql -u root -p
```

```sql
CREATE DATABASE solar_app CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
EXIT;
```

Or run the full schema file:

```bash
mysql -u root -p solar_app < migrations/schema.sql
```

> Note: The schema.sql seed data uses placeholder password hashes.
> The app.py `seed_db()` function inserts real hashed passwords automatically on first run.

### 3. Configure database connection

Edit `app.py`, find this line and update your credentials:

```python
app.config['SQLALCHEMY_DATABASE_URI'] = (
    'mysql+pymysql://root:password@localhost/solar_app'
)
```

Or set an environment variable:

```bash
export DATABASE_URL="mysql+pymysql://myuser:mypassword@localhost/solar_app"
export SECRET_KEY="your-secret-key-here"
```

### 4. Run the application

```bash
python app.py
```

The app will:
- Create all tables automatically via `db.create_all()`
- Seed default users and workers on first run
- Start on http://localhost:5000

---



## Role Permissions

| Feature                    | Admin | Coordinator | Documents | Payments | On-site | App Install |
|----------------------------|:-----:|:-----------:|:---------:|:--------:|:-------:|:-----------:|
| View all projects           | ✓     | —           | —         | —        | —       | —           |
| Create project              | ✓     | ✓           | —         | —        | —       | —           |
| Update project status       | ✓     | ✓           | ✓         | —        | —       | —           |
| Record payments             | ✓     | —           | —         | ✓        | —       | —           |
| View payments dashboard     | ✓     | —           | —         | ✓        | —       | —           |
| Manage KSEB tasks           | ✓     | —           | ✓         | —        | —       | —           |
| Manage documents            | ✓     | —           | ✓         | —        | —       | —           |
| Assign workers              | ✓     | —           | —         | —        | ✓       | —           |
| Manage installations        | ✓     | —           | ✓         | —        | —       | ✓           |
| Manage users                | ✓     | —           | —         | —        | —       | —           |

---

## Project Workflow Stages

```
Lead → Site Visit → Project Confirmation → Documentation →
Bank/Feasibility → Structure Work → Material Delivery →
KSEB Processing → Inspection → Connection →
Subsidy → App Installation → Final Payment → Warranty Issued → Closed
```

Project status values: `Lead`, `Created`, `InProgress`, `Completed`, `Delayed`, `Pending`, `Closed`

---

## API Endpoints

| Method | URL                    | Description              | Auth    |
|--------|------------------------|--------------------------|---------|
| GET    | `/api/projects`        | All projects as JSON     | Any     |
| GET    | `/api/dashboard_stats` | Summary counts + revenue | Any     |

---

## Production Deployment (Gunicorn + Nginx)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 "app:app"
```

Nginx config (`/etc/nginx/sites-available/solar`):

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Security Checklist Before Going Live

- [ ] Change `SECRET_KEY` to a long random string
- [ ] Change all default user passwords
- [ ] Set `DEBUG = False` in production
- [ ] Use environment variables for DB credentials
- [ ] Enable HTTPS via Let's Encrypt
- [ ] Restrict MySQL user to only the `solar_app` database
