-- ============================================================
-- Power on Plus Solar Solutions — MySQL Database Schema
-- ============================================================

CREATE DATABASE IF NOT EXISTS solar_app CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE solar_app;

-- ─────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(80)  NOT NULL UNIQUE,
    email       VARCHAR(120) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,
    full_name   VARCHAR(120) NOT NULL,
    role        ENUM('admin','coordinator','documents','payments','onsite','appinstall') NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- CUSTOMERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    phone        VARCHAR(20),
    email        VARCHAR(120),
    address      TEXT,
    district     VARCHAR(80),
    pincode      VARCHAR(10),
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- PROJECTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    project_code        VARCHAR(20) NOT NULL UNIQUE,
    customer_id         INT NOT NULL,
    system_kw           DECIMAL(6,2) NOT NULL,
    project_type        ENUM('Loan','Cash') NOT NULL,
    status              ENUM('Lead','Created','InProgress','Completed','Delayed','Pending','Closed') DEFAULT 'Lead',
    stage               VARCHAR(100) DEFAULT 'Lead',
    total_amount        DECIMAL(12,2) DEFAULT 0,
    collected_amount    DECIMAL(12,2) DEFAULT 0,
    coordinator_id      INT,
    doc_staff_id        INT,
    notes               TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id)   REFERENCES customers(id),
    FOREIGN KEY (coordinator_id) REFERENCES users(id),
    FOREIGN KEY (doc_staff_id)   REFERENCES users(id)
);

-- ─────────────────────────────────────────────
-- SITE VISITS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS site_visits (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    scheduled_date  DATE,
    visited_date    DATE,
    conducted_by    INT,
    observations    TEXT,
    status          ENUM('Scheduled','Completed','Cancelled') DEFAULT 'Scheduled',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id)    REFERENCES projects(id),
    FOREIGN KEY (conducted_by)  REFERENCES users(id)
);

-- ─────────────────────────────────────────────
-- DOCUMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    doc_type        VARCHAR(80) NOT NULL,
    status          ENUM('Pending','Received','Verified','Sent') DEFAULT 'Pending',
    received_date   DATE,
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- ─────────────────────────────────────────────
-- PAYMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS payments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    amount          DECIMAL(12,2) NOT NULL,
    payment_type    ENUM('Cash','Bank','Cheque','Online') NOT NULL,
    payment_date    DATE NOT NULL,
    reference_no    VARCHAR(80),
    received_by     INT,
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id)  REFERENCES projects(id),
    FOREIGN KEY (received_by) REFERENCES users(id)
);

-- ─────────────────────────────────────────────
-- WORKERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workers (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    phone       VARCHAR(20),
    skill       VARCHAR(80),
    rate_per_day DECIMAL(8,2) DEFAULT 0,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- WORKER ASSIGNMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worker_assignments (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    project_id  INT NOT NULL,
    worker_id   INT NOT NULL,
    start_date  DATE,
    end_date    DATE,
    days_worked INT DEFAULT 0,
    amount_paid DECIMAL(10,2) DEFAULT 0,
    status      ENUM('Assigned','Active','Completed','Paid') DEFAULT 'Assigned',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (worker_id)  REFERENCES workers(id)
);

-- ─────────────────────────────────────────────
-- KSEB TASKS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kseb_tasks (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL UNIQUE,
    stamp_paper     ENUM('Pending','Requested','Received') DEFAULT 'Pending',
    b_class_licence ENUM('Pending','Requested','Received') DEFAULT 'Pending',
    file_sent       BOOLEAN DEFAULT FALSE,
    file_sent_date  DATE,
    inspection_date DATE,
    inspection_done BOOLEAN DEFAULT FALSE,
    cd_payment_done BOOLEAN DEFAULT FALSE,
    cd_payment_date DATE,
    connection_date DATE,
    connection_done BOOLEAN DEFAULT FALSE,
    meter_available BOOLEAN DEFAULT TRUE,
    ae_completed    BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- ─────────────────────────────────────────────
-- SUBSIDY
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subsidy (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL UNIQUE,
    request_date    DATE,
    expected_amount DECIMAL(10,2) DEFAULT 0,
    received_amount DECIMAL(10,2) DEFAULT 0,
    status          ENUM('NotStarted','Requested','Processing','Received') DEFAULT 'NotStarted',
    notes           TEXT,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- ─────────────────────────────────────────────
-- APP INSTALLATIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS app_installations (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    project_id          INT NOT NULL UNIQUE,
    scheduled_date      DATE,
    completed_date      DATE,
    installed_by        INT,
    status              ENUM('Pending','Scheduled','Completed') DEFAULT 'Pending',
    notes               TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id)   REFERENCES projects(id),
    FOREIGN KEY (installed_by) REFERENCES users(id)
);

-- ─────────────────────────────────────────────
-- PROJECT TIMELINE LOG
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS project_logs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    project_id  INT NOT NULL,
    action      VARCHAR(200) NOT NULL,
    old_value   VARCHAR(100),
    new_value   VARCHAR(100),
    done_by     INT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (done_by)    REFERENCES users(id)
);

-- ─────────────────────────────────────────────
-- MATERIALS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS materials (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    item_name       VARCHAR(100) NOT NULL,
    quantity        DECIMAL(8,2),
    unit            VARCHAR(20),
    dispatch_status ENUM('Pending','Dispatched','Delivered') DEFAULT 'Pending',
    dispatch_date   DATE,
    received_date   DATE,
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- ─────────────────────────────────────────────
-- SEED DATA
-- ─────────────────────────────────────────────

-- Default users (passwords hashed for 'password123')
INSERT INTO users (username, email, password, full_name, role) VALUES
('admin',      'admin@poweronplus.in',    'pbkdf2:sha256:260000$placeholder_hash_admin',    'Admin User',       'admin'),
('anita',      'anita@poweronplus.in',    'pbkdf2:sha256:260000$placeholder_hash_anita',    'Anita Nair',       'coordinator'),
('vinod',      'vinod@poweronplus.in',    'pbkdf2:sha256:260000$placeholder_hash_vinod',    'Vinod Menon',      'coordinator'),
('sreeja',     'sreeja@poweronplus.in',   'pbkdf2:sha256:260000$placeholder_hash_sreeja',   'Sreeja K',         'documents'),
('priya',      'priya@poweronplus.in',    'pbkdf2:sha256:260000$placeholder_hash_priya',    'Priya Das',        'documents'),
('payments1',  'pay1@poweronplus.in',     'pbkdf2:sha256:260000$placeholder_hash_pay1',     'Rajan P',          'payments'),
('onsite1',    'onsite@poweronplus.in',   'pbkdf2:sha256:260000$placeholder_hash_onsite',   'Suresh K',         'onsite'),
('appteam1',   'app@poweronplus.in',      'pbkdf2:sha256:260000$placeholder_hash_app',      'Dev Team Lead',    'appinstall');

-- Sample customers
INSERT INTO customers (name, phone, email, address, district, pincode) VALUES
('Rajesh Kumar',  '9876543210', 'rajesh@email.com',  '12, MG Road, Thrissur',    'Thrissur',  '680001'),
('Meera Nair',    '9876543211', 'meera@email.com',   '45, Station Rd, Palakkad', 'Palakkad',  '678001'),
('George Thomas', '9876543212', 'george@email.com',  '7, Church St, Ernakulam',  'Ernakulam', '682001'),
('Sunitha Pillai','9876543213', 'sunitha@email.com', '22, Beach Rd, Kozhikode',  'Kozhikode', '673001'),
('Anil Menon',    '9876543214', 'anil@email.com',    '9, Garden Ave, Thrissur',  'Thrissur',  '680002'),
('Leela Varma',   '9876543215', 'leela@email.com',   '3, Lake View, Alappuzha',  'Alappuzha', '688001');

-- Sample workers
INSERT INTO workers (name, phone, skill, rate_per_day) VALUES
('Arun K',  '9845001111', 'Panel Installation', 1200.00),
('Biju M',  '9845002222', 'Electrical Work',    1200.00),
('Cijo P',  '9845003333', 'Structural Work',    1200.00);
