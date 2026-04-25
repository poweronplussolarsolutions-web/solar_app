"""
logging_system.py — Structured logging for Power On Plus Solar Solutions
========================================================================
Integrates with app.py. Import and call `setup_logging(app)` after the
Flask app object is created but before the first request.

Features
--------
* Rotating file logs  — app.log, error.log, security.log, access.log
* Console handler      — coloured, human-readable in development
* Security audit log   — login attempts, lockouts, password changes
* HTTP access log      — every request with method, path, status, duration
* Unhandled-exception  — full traceback to error.log
* DB-query slowness    — logs SQLAlchemy queries that exceed SLOW_QUERY_MS
* Per-request context  — user_id, ip, request_id injected into every record
* JSON structured mode — set LOG_FORMAT=json env var for log aggregators
* Admin log viewer     — /admin/logs route to tail logs in the browser

Usage in app.py
---------------
    from logging_system import setup_logging, security_log, access_log
    # … create app, db, etc. …
    setup_logging(app)
"""

import logging
import logging.handlers
import os
import sys
import time
import uuid
import json
import traceback
from datetime import datetime, date
from functools import wraps
from flask import request, g, has_request_context, current_app
from flask_login import current_user


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

LOG_DIR          = os.environ.get('LOG_DIR', 'logs')
LOG_FORMAT       = os.environ.get('LOG_FORMAT', 'text')   # 'text' | 'json'
LOG_LEVEL        = os.environ.get('LOG_LEVEL', 'INFO').upper()
SLOW_QUERY_MS    = int(os.environ.get('SLOW_QUERY_MS', 200))
MAX_BYTES        = 10 * 1024 * 1024   # 10 MB per file
BACKUP_COUNT     = 10                  # keep 10 rotated files

# Named loggers — import these anywhere:
#   from logging_system import security_log, access_log, slow_log
app_logger      = logging.getLogger('solar.app')
security_logger = logging.getLogger('solar.security')
access_logger   = logging.getLogger('solar.access')
slow_logger     = logging.getLogger('solar.slow_query')
error_logger    = logging.getLogger('solar.error')


# ─────────────────────────────────────────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────────────────────────────────────────

class _ContextFilter(logging.Filter):
    """Inject request-id, user, ip into every log record."""
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, 'request_id', '-')
            record.ip         = request.remote_addr or '-'
            try:
                record.user = current_user.username if current_user.is_authenticated else 'anon'
            except Exception:
                record.user = '-'
            record.path   = request.path
            record.method = request.method
        else:
            record.request_id = '-'
            record.ip         = '-'
            record.user       = '-'
            record.path       = '-'
            record.method     = '-'
        return True


TEXT_FMT = (
    '%(asctime)s | %(levelname)-8s | %(name)-20s | '
    'req=%(request_id)s user=%(user)s ip=%(ip)s | %(message)s'
)
DATE_FMT = '%Y-%m-%d %H:%M:%S'

ACCESS_FMT = (
    '%(asctime)s | %(ip)s | %(user)s | '
    '%(method)s %(path)s → %(message)s'
)


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        self.format_exception_text(record)
        doc = {
            'ts':         self.formatTime(record, DATE_FMT),
            'level':      record.levelname,
            'logger':     record.name,
            'msg':        record.getMessage(),
            'request_id': getattr(record, 'request_id', '-'),
            'user':       getattr(record, 'user',       '-'),
            'ip':         getattr(record, 'ip',         '-'),
            'method':     getattr(record, 'method',     '-'),
            'path':       getattr(record, 'path',       '-'),
        }
        if record.exc_info:
            doc['traceback'] = self.formatException(record.exc_info)
        return json.dumps(doc, ensure_ascii=False)

    @staticmethod
    def format_exception_text(record):
        if record.exc_info and not record.exc_text:
            record.exc_text = '...'  # suppress duplicate in getMessage


class _ColourFormatter(logging.Formatter):
    """Coloured console output for development."""
    COLOURS = {
        'DEBUG':    '\033[36m',
        'INFO':     '\033[32m',
        'WARNING':  '\033[33m',
        'ERROR':    '\033[31m',
        'CRITICAL': '\033[35m',
    }
    RESET = '\033[0m'

    def format(self, record):
        colour = self.COLOURS.get(record.levelname, '')
        record.levelname = f'{colour}{record.levelname:<8}{self.RESET}'
        return super().format(record)


# ─────────────────────────────────────────────────────────────────────────────
# HANDLER FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def _make_file_handler(filename: str, formatter: logging.Formatter) -> logging.Handler:
    os.makedirs(LOG_DIR, exist_ok=True)
    path    = os.path.join(LOG_DIR, filename)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8'
    )
    handler.addFilter(_ContextFilter())
    handler.setFormatter(formatter)
    return handler


def _make_console_handler(formatter: logging.Formatter) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(formatter)
    return handler


# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(app):
    """
    Call once after `app = Flask(__name__)`.

    Registers:
      • before_request  — assign request_id, start timer
      • after_request   — write access log line
      • teardown_request — log unhandled exceptions
    """
    level = getattr(logging, LOG_LEVEL, logging.INFO)

    if LOG_FORMAT == 'json':
        main_fmt   = _JsonFormatter()
        access_fmt = _JsonFormatter()
    else:
        main_fmt   = _ColourFormatter(TEXT_FMT, datefmt=DATE_FMT) \
                     if app.debug else logging.Formatter(TEXT_FMT, datefmt=DATE_FMT)
        access_fmt = logging.Formatter(ACCESS_FMT, datefmt=DATE_FMT)

    # ── Configure named loggers ───────────────────────────────────────────────
    _configure(app_logger,      level, [
        _make_file_handler('app.log',      main_fmt),
        _make_console_handler(main_fmt),
    ])
    _configure(security_logger, level, [
        _make_file_handler('security.log', main_fmt),
        _make_console_handler(main_fmt),
    ])
    _configure(access_logger,   logging.INFO, [
        _make_file_handler('access.log',   access_fmt),
    ])
    _configure(slow_logger,     logging.WARNING, [
        _make_file_handler('slow_query.log', main_fmt),
        _make_console_handler(main_fmt),
    ])
    _configure(error_logger,    logging.ERROR, [
        _make_file_handler('error.log',    main_fmt),
        _make_console_handler(main_fmt),
    ])

    # ── Capture Werkzeug / SQLAlchemy logs ────────────────────────────────────
    logging.getLogger('werkzeug').setLevel(logging.WARNING)   # avoid double access lines
    _configure(logging.getLogger('sqlalchemy.engine'), logging.WARNING, [
        _make_file_handler('app.log', main_fmt),
    ])

    # ── Flask hooks ───────────────────────────────────────────────────────────
    @app.before_request
    def _before():
        g.request_id = uuid.uuid4().hex[:12]
        g.request_start = time.perf_counter()

    # cache user
        try:
            if current_user.is_authenticated:
                g.user = current_user
            else:
                g.user = None
        except:
            g.user = None

    @app.after_request
    def _after(response):
        try:
            if response is None:
                return response
            duration_ms = int((time.perf_counter() - getattr(g, 'request_start', time.perf_counter())) * 1000)
        # Skip noisy endpoints
            skip = {'/api/notifications', '/static'}
            if not any(request.path.startswith(p) for p in skip):
                access_logger.info(
                '%s %dms',
                response.status_code,
                duration_ms,
                extra={
                    'ip':     request.remote_addr,
                    'user':   _safe_username(),
                    'method': request.method,
                    'path':   request.path,
                    'request_id': getattr(g, 'request_id', '-'),
                },
            )
        except Exception as e:
                error_logger.error("After request logging failed: %s",e)
        return response

    @app.teardown_request
    def _teardown(exc):
        if exc is not None:
            error_logger.error(
                'Unhandled exception: %s', exc,
                exc_info=True,
            )

    app_logger.info('Logging initialised — level=%s format=%s dir=%s', LOG_LEVEL, LOG_FORMAT, LOG_DIR)
    _register_routes(app)
    _register_sqlalchemy_listener(app)


def _configure(logger, level, handlers):
    logger.setLevel(level)
    logger.propagate = False
    for h in handlers:
        h.setLevel(level)
        logger.addHandler(h)


def _safe_username():
    try:
        return g.user.username if g.get('user') else 'anon'
    except:
        return '-'


# ─────────────────────────────────────────────────────────────────────────────
# SQLALCHEMY SLOW-QUERY LISTENER
# ─────────────────────────────────────────────────────────────────────────────

def _register_sqlalchemy_listener(app):
    try:
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, 'before_cursor_execute')
        def _before_execute(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault('query_start', time.perf_counter())

        @event.listens_for(Engine, 'after_cursor_execute')
        def _after_execute(conn, cursor, statement, parameters, context, executemany):
            start = conn.info.get('query_start')
            if start:
                ms = (time.perf_counter() - start) * 1000
                if ms >= SLOW_QUERY_MS:
                    if not hasattr(conn, "_logged_slow"):
                        slow_logger.warning(
            'SLOW QUERY %.1fms: %s',
            ms,
            statement[:300].replace('\n', ' ')
        )
                        conn._logged_slow = True
    except ImportError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTIONS  (import these in app.py)
# ─────────────────────────────────────────────────────────────────────────────

def security_log(event: str, detail: str = '', level: str = 'info'):
    """Log a security-relevant event."""
    fn = getattr(security_logger, level, security_logger.info)
    fn('SECURITY [%s] %s', event, detail)


def log_login_attempt(username: str, success: bool, reason: str = ''):
    level = 'info' if success else 'warning'
    security_log(
        'LOGIN_SUCCESS' if success else 'LOGIN_FAIL',
        f'user={username} reason={reason or "-"}',
        level=level,
    )


def log_lockout(username: str, minutes: int):
    security_log('ACCOUNT_LOCKED', f'user={username} locked_for={minutes}m', level='warning')


def log_password_change(username: str, changed_by: str):
    security_log('PASSWORD_CHANGE', f'user={username} changed_by={changed_by}')


def log_admin_action(action: str, target: str = '', detail: str = ''):
    security_log('ADMIN_ACTION', f'action={action} target={target} detail={detail}')


def log_access_denied(path: str, user: str):
    security_log('ACCESS_DENIED', f'path={path} user={user}', level='warning')


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN LOG VIEWER ROUTE
# ─────────────────────────────────────────────────────────────────────────────

_LOG_FILES = {
    'app':      'app.log',
    'security': 'security.log',
    'access':   'access.log',
    'error':    'error.log',
    'slow':     'slow_query.log',
}

_VIEWER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Log Viewer — Power On Plus</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
  header {{ background: #1e293b; padding: 1rem 1.5rem; display: flex; align-items: center; gap: 1rem; border-bottom: 1px solid #334155; }}
  header h1 {{ font-size: 1.1rem; font-weight: 700; color: #f8fafc; }}
  header a {{ color: #94a3b8; font-size: .85rem; text-decoration: none; }}
  header a:hover {{ color: #f8fafc; }}
  .controls {{ background: #1e293b; padding: .75rem 1.5rem; display: flex; gap: .75rem; flex-wrap: wrap; align-items: center; border-bottom: 1px solid #334155; }}
  select, input[type=text], input[type=number] {{
    background: #0f172a; border: 1px solid #475569; border-radius: .375rem;
    color: #e2e8f0; padding: .4rem .75rem; font-size: .85rem; }}
  button {{ background: #2563eb; color: #fff; border: none; border-radius: .375rem;
    padding: .4rem 1rem; font-size: .85rem; cursor: pointer; }}
  button:hover {{ background: #1d4ed8; }}
  button.secondary {{ background: #475569; }}
  button.secondary:hover {{ background: #334155; }}
  #log-box {{ font-family: 'Courier New', monospace; font-size: .78rem; line-height: 1.6;
    padding: 1rem 1.5rem; white-space: pre-wrap; word-break: break-all; }}
  .line {{ padding: .1rem .4rem; border-radius: .2rem; }}
  .line.ERROR, .line.CRITICAL {{ background: rgba(239,68,68,.15); color: #fca5a5; }}
  .line.WARNING {{ background: rgba(245,158,11,.12); color: #fcd34d; }}
  .line.INFO  {{ color: #94a3b8; }}
  .line.DEBUG {{ color: #64748b; }}
  .badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 9999px; font-size: .7rem;
    font-weight: 700; margin-right: .3rem; }}
  .badge.err  {{ background: #ef4444; color: #fff; }}
  .badge.warn {{ background: #f59e0b; color: #000; }}
  .badge.info {{ background: #3b82f6; color: #fff; }}
  .badge.sec  {{ background: #8b5cf6; color: #fff; }}
  .stats {{ display: flex; gap: 1rem; margin-left: auto; font-size: .8rem; color: #94a3b8; }}
  .stat span {{ font-weight: 700; color: #e2e8f0; }}
  #filter-bar {{ display: flex; align-items: center; gap: .5rem; }}
  .highlight {{ background: #fef08a; color: #000 !important; border-radius: 2px; }}
</style>
</head>
<body>
<header>
  <h1>📋 Log Viewer</h1>
  <a href="/dashboard">← Dashboard</a>
  <a href="/admin/logs?file={{current_file}}&lines={{lines}}&q={{q}}" style="margin-left:auto; background:#1e40af; padding:.3rem .8rem; border-radius:.375rem; color:#fff; font-size:.8rem;">↻ Refresh</a>
</header>
<div class="controls">
  <form method="get" style="display:contents">
    <select name="file" onchange="this.form.submit()">
      {{file_options}}
    </select>
    <input type="number" name="lines" value="{{lines}}" min="10" max="5000" style="width:80px" title="Lines to show">
    <input type="text" name="q" value="{{q}}" placeholder="Filter text…" style="width:200px">
    <button type="submit">Apply</button>
    <button type="button" class="secondary" onclick="document.querySelector('[name=q]').value='';this.form.submit()">Clear</button>
    <div class="stats">
      <div>Errors <span class="badge err">{{cnt_error}}</span></div>
      <div>Warnings <span class="badge warn">{{cnt_warn}}</span></div>
      <div>Security <span class="badge sec">{{cnt_sec}}</span></div>
      <div>Total <span>{{cnt_total}}</span></div>
    </div>
  </form>
</div>
<div id="log-box">{{log_content}}</div>
<script>
  // Auto-scroll to bottom
  window.scrollTo(0, document.body.scrollHeight);
  // Keyboard shortcut: Ctrl+R to refresh
  document.addEventListener('keydown', e => {{ if (e.ctrlKey && e.key==='r') location.reload(); }});
</script>
</body>
</html>
"""

def _register_routes(app):
    from flask import request as freq, abort
    from markupsafe import Markup
    from flask_login import login_required, current_user
    from functools import wraps

    def admin_only(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != 'admin':
                abort(403)
            return f(*args, **kwargs)
        return wrapper

    @app.route('/admin/logs')
    @login_required
    @admin_only
    def admin_log_viewer():
        current_file = freq.args.get('file', 'app')
        lines        = max(10, min(5000, freq.args.get('lines', 200, type=int)))
        q            = freq.args.get('q', '').strip()

        filename = _LOG_FILES.get(current_file, 'app.log')
        filepath = os.path.join(LOG_DIR, filename)

        raw_lines = []
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                raw_lines = fh.readlines()[-lines:]

        if q:
            raw_lines = [l for l in raw_lines if q.lower() in l.lower()]

        cnt_error = sum(1 for l in raw_lines if ' | ERROR' in l or ' | CRITICAL' in l)
        cnt_warn  = sum(1 for l in raw_lines if ' | WARNING' in l)
        cnt_sec   = sum(1 for l in raw_lines if 'SECURITY' in l)
        cnt_total = len(raw_lines)

        def _classify(line):
            if ' | ERROR' in line or ' | CRITICAL' in line:
                return 'ERROR'
            if ' | WARNING' in line:
                return 'WARNING'
            if ' | DEBUG' in line:
                return 'DEBUG'
            return 'INFO'

        import html as _html
        def _render_line(line):
            cls   = _classify(line)
            safe  = _html.escape(line.rstrip())
            if q:
                safe = safe.replace(_html.escape(q), f'<mark class="highlight">{_html.escape(q)}</mark>')
            return f'<div class="line {cls}">{safe}</div>'

        log_content = '\n'.join(_render_line(l) for l in raw_lines) if raw_lines else \
                      '<div style="color:#64748b;padding:2rem">No log entries found.</div>'

        file_options = '\n'.join(
            f'<option value="{k}" {"selected" if k==current_file else ""}>{v}</option>'
            for k, v in _LOG_FILES.items()
        )

        html = _VIEWER_HTML \
    .replace('{{current_file}}', current_file) \
    .replace('{{lines}}',        str(lines)) \
    .replace('{{q}}',            _html.escape(q)) \
    .replace('{{file_options}}', file_options) \
    .replace('{{log_content}}',  log_content) \
    .replace('{{cnt_error}}',    str(cnt_error)) \
    .replace('{{cnt_warn}}',     str(cnt_warn)) \
    .replace('{{cnt_sec}}',      str(cnt_sec)) \
    .replace('{{cnt_total}}',    str(cnt_total))
        from flask import Response
        return Response(html, mimetype='text/html')

    @app.route('/admin/logs/download')
    @login_required
    @admin_only
    def download_log():
        from flask import send_file as _sf
        filename = _LOG_FILES.get(freq.args.get('file', 'app'), 'app.log')
        filepath = os.path.join(LOG_DIR, filename)
        if not os.path.exists(filepath):
            abort(404)
        log_admin_action('LOG_DOWNLOAD', detail=filename)
        return _sf(filepath, as_attachment=True, download_name=filename)

    app_logger.info('Log viewer registered at /admin/logs')