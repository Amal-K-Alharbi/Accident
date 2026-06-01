# Standard library and framework imports stay grouped at the top so runtime dependencies remain explicit during deployment and review.
import os
import cv2
import time
import uuid
import base64
import sqlite3
import hashlib
import threading
import numpy as np
from datetime import datetime
from flask import (
    Flask, render_template, request, Response,
    jsonify, session, redirect, url_for, send_from_directory
)
from ultralytics import YOLO
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# The application object centralizes configuration, routing, and request handling for the entire system.
app = Flask(__name__)
# Session signing depends on a stable secret so authenticated state cannot be tampered with by the client.
app.secret_key = 'accivision_secret_key_26'
# Uploaded media stays inside the project workspace to keep evidence and operator input under managed storage.
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
# A hard upload limit protects the service from oversized requests that could degrade responsiveness.
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB max
# File type allowlisting narrows ingestion to formats the video pipeline is expected to handle.
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'webm'}

# Project-relative paths keep the application portable across local and hosted environments.
BASE_DIR = os.path.dirname(__file__)
ACCIDENTS_DIR = os.path.join(BASE_DIR, 'static', 'accidents')
DB_PATH = os.path.join(BASE_DIR, 'accivision.db')

# Required storage folders are ensured at startup so capture and upload flows do not fail on first use.
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(ACCIDENTS_DIR, exist_ok=True)


# The detector is loaded once at startup to avoid repeated initialization costs during live monitoring.
model = YOLO(os.path.join(BASE_DIR, "best.pt"))

# Label metadata is read once so detection classes can be translated into operator-facing states throughout the session.
with open(os.path.join(BASE_DIR, "coco.txt"), 'r') as f:
    class_list = [line.strip() for line in f.read().strip().split('\n')]

# Shared runtime flags coordinate long-lived streaming loops and browser polling across multiple request handlers.
camera_active = False
current_video_path = None
current_video_filename = None
video_active = False
accident_flag = False          # polled by browser for sound
accident_flag_lock = threading.Lock()
camera_inventory_cache = {'count': 0, 'checked_at': 0.0}
camera_inventory_lock = threading.Lock()

# Snapshot throttling prevents one sustained incident from generating excessive duplicate evidence.
last_snapshot_time = 0

# Encoding settings are fixed up front to keep frame streaming predictable under repeated load.
ENCODE_PARAM = [int(cv2.IMWRITE_JPEG_QUALITY), 60]

CAMERA_DISCOVERY_MAX_INDEX = 4
CAMERA_DISCOVERY_CACHE_SECONDS = 15



# Database connections are centralized so every code path gets the same SQLite configuration and row access behavior.
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Startup schema management preserves compatibility with existing databases while enabling new workflow metadata.
def init_db():
    conn = get_db()
    # User storage is created defensively so authentication works even on a brand-new deployment.
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'admin',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Accident storage persists evidence and lifecycle state so dashboards survive refreshes and restarts.
    conn.execute('''CREATE TABLE IF NOT EXISTS accidents (
        id TEXT PRIMARY KEY,
        image TEXT NOT NULL,
        timestamp REAL NOT NULL,
        notified INTEGER DEFAULT 0,
        responded INTEGER DEFAULT 0,
        closed INTEGER DEFAULT 0,
        reported_at REAL,
        responded_at REAL
    )''')
    # Schema inspection supports additive migrations without destructive table rebuilds.
    user_columns = [row['name'] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if 'role' not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")

    # Accident schema inspection protects historical data while newer alert workflow fields are introduced.
    accident_columns = [row['name'] for row in conn.execute("PRAGMA table_info(accidents)").fetchall()]
    if 'responded' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN responded INTEGER DEFAULT 0")
    if 'closed' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN closed INTEGER DEFAULT 0")
    if 'status' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN status TEXT")
    if 'sent_at' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN sent_at REAL")
    if 'reported_at' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN reported_at REAL")
    if 'responded_at' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN responded_at REAL")
    if 'closed_at' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN closed_at REAL")
    if 'detection_time_seconds' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN detection_time_seconds REAL")
    if 'response_status' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN response_status TEXT DEFAULT 'pending'")
    if 'assigned_responder' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN assigned_responder TEXT")
    if 'confidence' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN confidence REAL DEFAULT 0")
    if 'source_video' not in accident_columns:
        conn.execute("ALTER TABLE accidents ADD COLUMN source_video TEXT")

    conn.execute(
        '''
        UPDATE accidents
        SET sent_at = COALESCE(sent_at, reported_at)
        WHERE reported_at IS NOT NULL
        '''
    )
    conn.execute(
        '''
        UPDATE accidents
        SET status = CASE
            WHEN closed = 1 THEN 'closed'
            WHEN responded = 1 THEN 'responded'
            WHEN notified = 1 THEN 'sent_to_responder'
            ELSE 'new'
        END
        WHERE status IS NULL OR TRIM(status) = ''
        '''
    )
    conn.execute(
        '''
        UPDATE accidents
        SET response_status = CASE
            WHEN status = 'closed' THEN 'resolved'
            WHEN status = 'responded' THEN 'acknowledged'
            WHEN status = 'sent_to_responder' THEN COALESCE(response_status, 'pending')
            ELSE COALESCE(response_status, 'pending')
        END
        WHERE response_status IS NULL OR TRIM(response_status) = ''
        '''
    )

    conn.commit()
    conn.close()


# Database preparation runs before any request handling so later routes can assume a ready schema.
init_db()


# Password hashing keeps stored credentials irreversible and supports safe upgrades from older hashes.
def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_password, entered_password):
    # 1. Password Verification and Legacy Upgrade Check
    if not stored_password or not entered_password:
        return False, False

    try:
        if check_password_hash(stored_password, entered_password):
            return True, False
    except (ValueError, TypeError):
        pass

    legacy_sha = hashlib.sha256(entered_password.encode()).hexdigest()
    if stored_password == legacy_sha:
        return True, True

    if stored_password == entered_password:
        return True, True

    return False, False


# Role lookup is isolated because authorization decisions should rely on one trusted access path.
def get_user_role(email):
    conn = get_db()
    row = conn.execute('SELECT role FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    return row['role'] if row and row['role'] in {'admin', 'responder'} else 'admin'


# Session role access is wrapped to keep permission checks consistent across routes and templates.
def get_current_role():
    return session.get('user_role', 'admin')


# Shared alert counters drive badges and summaries so every page reports the same operational totals.
def get_alert_counts(conn=None):
    should_close = conn is None
    if conn is None:
        conn = get_db()

    # Counting in SQL avoids loading the full accident history into memory just to update dashboard badges.
    counts = conn.execute(
        '''
        SELECT
            SUM(
                CASE
                    WHEN status NOT IN ('closed', 'false_alarm')
                    THEN 1
                    ELSE 0
                END
            ) AS active_alerts_count,
            SUM(
                CASE
                    WHEN closed = 0 AND (
                        status = 'responded'
                        OR (status IS NULL AND responded = 1)
                    ) THEN 1
                    ELSE 0
                END
            ) AS responded_cases_count
        FROM accidents
        '''
    ).fetchone()

    if should_close:
        conn.close()

    return {
        'active_alerts_count': counts['active_alerts_count'] or 0,
        'responded_cases_count': counts['responded_cases_count'] or 0,
    }


# Detection-time metrics reflect model inference speed, not upload, notification, or responder timing.
def get_average_response_time(conn=None):
    should_close = conn is None
    if conn is None:
        conn = get_db()

    # Only captured detections with measured inference duration contribute to the performance summary.
    stats = conn.execute(
        '''
        SELECT
            COUNT(*) AS detected_total,
            AVG(detection_time_seconds) AS average_response_seconds
        FROM accidents
        WHERE detection_time_seconds IS NOT NULL
          AND detection_time_seconds >= 0
        '''
    ).fetchone()

    if should_close:
        conn.close()

    average_seconds = stats['average_response_seconds']
    if average_seconds is None:
        return {
            'avg_response_seconds': None,
            'avg_response_time_label': 'No data'
        }

    return {
        'avg_response_seconds': average_seconds,
        'avg_response_time_label': format_model_detection_time(average_seconds)
    }


def get_active_alerts_count(conn=None):
    return get_alert_counts(conn)['active_alerts_count']


def get_responded_cases_count(conn=None):
    return get_alert_counts(conn)['responded_cases_count']


def get_response_status_counts(conn=None):
    # 1. Responder Status Counts
    should_close = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        '''
        SELECT response_status, COUNT(*) AS total
        FROM accidents
        WHERE status IN ('sent_to_responder', 'responded', 'closed')
           OR notified = 1
        GROUP BY response_status
        '''
    ).fetchall()

    if should_close:
        conn.close()

    counts = {status: 0 for status in ['pending', 'acknowledged', 'en_route', 'on_scene', 'resolved']}
    for row in rows:
        status = row['response_status'] if row['response_status'] in counts else 'pending'
        counts[status] += row['total'] or 0
    return counts


# Recent event shaping converts raw records into dashboard-friendly summaries without leaking storage details into templates.
def build_recent_events(conn=None, limit=6):
    should_close = conn is None
    if conn is None:
        conn = get_db()

    rows = conn.execute(
        '''
        SELECT id, timestamp, notified, responded, closed, status, response_status
        FROM accidents
        ORDER BY timestamp DESC
        LIMIT ?
        ''',
        (limit,)
    ).fetchall()

    recent_events = []
    for index, row in enumerate(rows, start=1):
        normalized_status = get_alert_status(row)
        response_label = build_response_status_label(get_response_status(row))
        status = response_label if normalized_status in {'sent_to_responder', 'responded', 'closed'} else build_incident_status(normalized_status)
        recent_events.append({
            'event_id': f"EVT-{datetime.fromtimestamp(row['timestamp']).strftime('%Y%m%d')}-{index:03d}",
            'location': f"Monitored Zone {((index - 1) % 4) + 1}",
            'severity': 'Critical' if normalized_status == 'sent_to_responder' else 'High' if normalized_status == 'responded' else 'Medium' if normalized_status == 'closed' else 'Low',
            'status': status,
            'time': get_elapsed_time(row['timestamp']),
        })

    if should_close:
        conn.close()

    if recent_events:
        return recent_events

    return [
        {'event_id': 'EVT-DEMO-001', 'location': 'North Corridor Camera 04', 'severity': 'Critical', 'status': 'Active', 'time': '2 min ago'},
        {'event_id': 'EVT-DEMO-002', 'location': 'Main St & 4th Ave', 'severity': 'High', 'status': 'Responded', 'time': '14 min ago'},
        {'event_id': 'EVT-DEMO-003', 'location': 'Downtown Sector 2', 'severity': 'Medium', 'status': 'Closed', 'time': '38 min ago'},
    ]


# =========================
# 5. Alert Status Update Logic
# =========================

# Status normalization bridges legacy boolean fields and the newer workflow column so the UI can reason about one canonical state.
def get_alert_status(row):
    raw_status = row['status'] if 'status' in row.keys() else None
    if raw_status in {'new', 'sent_to_responder', 'responded', 'closed', 'false_alarm'}:
        return raw_status

    if row['closed']:
        return 'closed'
    if row['responded']:
        return 'responded'
    if row['notified']:
        return 'sent_to_responder'
    return 'new'


# Responder status labels are kept separate from admin lifecycle labels.
def get_response_status(row):
    raw_status = row['response_status'] if 'response_status' in row.keys() else None
    if raw_status in {'pending', 'acknowledged', 'en_route', 'on_scene', 'resolved'}:
        return raw_status
    if get_alert_status(row) == 'closed':
        return 'resolved'
    if get_alert_status(row) == 'responded':
        return 'acknowledged'
    return 'pending'


def build_response_status_label(status):
    labels = {
        'pending': 'Pending',
        'acknowledged': 'Acknowledged',
        'en_route': 'En Route',
        'on_scene': 'On Scene',
        'resolved': 'Resolved',
    }
    return labels.get(status, 'Pending')


def build_fake_location(alert_id):
    # 1. Stable Fake Location
    locations = [
        'King Fahd Road - Northbound',
        'Olaya Street & Makkah Road',
        'Airport Road Camera 04',
        'Downtown Sector 2',
        'Main St & 4th Ave',
    ]
    index = sum(ord(char) for char in str(alert_id)) % len(locations)
    return locations[index]


def format_confidence(value):
    # 2. Confidence Formatting
    try:
        return f"{float(value or 0) * 100:.0f}%"
    except (TypeError, ValueError):
        return "0%"


# Human-readable labels are derived in one place to keep wording stable across admin and responder views.
def build_incident_status(status):
    if status == 'closed':
        return 'Closed'
    if status == 'responded':
        return 'Responded'
    if status == 'sent_to_responder':
        return 'Active'
    if status == 'false_alarm':
        return 'False Alarm'
    return 'New'


# Serialization prepares database rows for rendering by attaching computed timings and display-oriented fields.
def serialize_accident(row):
    status = get_alert_status(row)
    response_status = get_response_status(row)
    notified = bool(row['notified']) or status in {'sent_to_responder', 'responded', 'closed'}
    responded = bool(row['responded']) or status in {'responded', 'closed'}
    closed = bool(row['closed']) or status == 'closed'
    sent_at = row['sent_at'] if 'sent_at' in row.keys() else None
    reported_at = row['reported_at'] if 'reported_at' in row.keys() else None
    responded_at = row['responded_at'] if 'responded_at' in row.keys() else None
    closed_at = row['closed_at'] if 'closed_at' in row.keys() else None
    effective_sent_at = sent_at or reported_at
    return {
        'id': row['id'],
        'image': row['image'],
        'confidence': row['confidence'] if 'confidence' in row.keys() else 0,
        'confidence_label': format_confidence(row['confidence'] if 'confidence' in row.keys() else 0),
        'source_video': row['source_video'] if 'source_video' in row.keys() else None,
        'elapsed': get_elapsed_time(row['timestamp']),
        'date': datetime.fromtimestamp(row['timestamp']).strftime('%Y-%m-%d %H:%M:%S'),
        'created_at': row['timestamp'],
        'location': build_fake_location(row['id']),
        'assigned_responder': row['assigned_responder'] if 'assigned_responder' in row.keys() and row['assigned_responder'] else 'Responder Team',
        'response_status': response_status,
        'response_status_label': build_response_status_label(response_status),
        'sent_at': effective_sent_at,
        'responded_at': responded_at,
        'closed_at': closed_at,
        'time_to_respond': format_duration(responded_at - effective_sent_at) if effective_sent_at and responded_at and responded_at >= effective_sent_at else None,
        'time_to_close': format_duration(closed_at - responded_at) if responded_at and closed_at and closed_at >= responded_at else None,
        'notified': notified,
        'responded': responded,
        'closed': closed,
        'internal_status': status,
        'status': build_incident_status(status)
    }


# =========================
# 1. Shared Page Context
# =========================

# Shared dashboard context keeps navigation badges, summary metrics, and user identity aligned across templates.
def build_dashboard_context():
    role = get_current_role()
    conn = get_db()
    alert_counts = get_alert_counts(conn)
    response_metrics = get_average_response_time(conn)
    recent_events = build_recent_events(conn)
    response_status_counts = get_response_status_counts(conn)
    working_camera_count = get_working_camera_count()
    events_today_count = conn.execute(
        '''
        SELECT COUNT(*) AS total
        FROM accidents
        WHERE status NOT IN ('false_alarm')
          AND timestamp >= (strftime('%s', 'now') - 86400)
        '''
    ).fetchone()['total'] or 0
    conn.close()

    user_email = session.get('user_email', '')
    user_name = user_email.split('@', 1)[0].replace('.', ' ').title() if user_email else role.title()
    return {
        **alert_counts,
        **response_metrics,
        'cameras_online_count': working_camera_count,
        'cameras_total_count': working_camera_count,
        'events_today_count': events_today_count,
        'recent_events': recent_events,
        'response_status_counts': response_status_counts,
        'current_role': role,
        'dashboard_title': 'Dashboard',
        'user_name': user_name,
        'user_role_label': role.title(),
        'alerts_url': url_for('responder_alerts') if role == 'responder' else url_for('alerts_page'),
        'dashboard_url': url_for('responder_dashboard') if role == 'responder' else url_for('admin_home_file'),
        'alerts_label': 'Responder Alerts' if role == 'responder' else 'Alerts',
    }


# Rendering is wrapped so dashboard entry points reuse the same context assembly path.
def render_dashboard_page():
    return render_template('home.html', **build_dashboard_context())


# =========================
# 2. Authentication Logic
# =========================

# Post-login routing is role-aware so each operator lands in the workflow most relevant to their responsibility.
def get_post_login_endpoint():
    return 'responder_dashboard' if get_current_role() == 'responder' else 'dashboard'


def get_post_login_url():
    return url_for('responder_dashboard') if get_current_role() == 'responder' else url_for('admin_home_file')


# Authentication enforcement is abstracted into a decorator to avoid repeating redirect logic on protected routes.
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# Global response hardening prevents browsers from caching authenticated pages with time-sensitive operational data.
@app.after_request
# Cache headers are applied after each request because dashboard state and session context should not persist in browser history.
def add_no_cache_headers(response):
    if 'user_id' in session and request.endpoint != 'static':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# =========================
# 3. Role-Based Access Control
# =========================

# Responder-only authorization separates operational case handling from administrative controls.
def responder_required(f):
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if get_current_role() != 'responder':
            return redirect(url_for('admin_home_file'))
        return f(*args, **kwargs)
    return decorated


# Admin-only authorization protects ingestion, escalation, and monitoring actions from non-admin accounts.
def admin_required(f):
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if get_current_role() != 'admin':
            return redirect(url_for('responder_dashboard'))
        return f(*args, **kwargs)
    return decorated



# Upload validation is isolated because several request paths rely on the same acceptance policy.
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Relative time formatting favors quick situational awareness over raw epoch values in the UI.
def get_elapsed_time(timestamp):
    diff = time.time() - timestamp
    if diff < 60:
        return f"{int(diff)} seconds ago"
    elif diff < 3600:
        mins = int(diff // 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    elif diff < 86400:
        hours = int(diff // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = int(diff // 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"


# Shared duration formatting keeps timing metrics readable and consistent across the product.
def format_duration(seconds):
    total_seconds = max(int(round(seconds)), 0)
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours} hr {remaining_minutes} min"
    if minutes > 0:
        return f"{minutes} min {remaining_seconds} sec"
    return f"{remaining_seconds} sec"


def format_model_detection_time(seconds):
    # 1. Model Timing Display
    if seconds is None:
        return 'No data'

    seconds = max(float(seconds), 0.0)
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    label = f"{seconds:.2f}".rstrip('0').rstrip('.')
    return f"{label}s"


# Camera probing is isolated so dashboard device counts and live capture can share the same platform-aware opening strategy.
def open_camera_capture(index):
    if os.name == 'nt':
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)


# Dashboard device metrics are cached briefly to avoid repeated hardware probing on every render.
def get_working_camera_count():
    now = time.time()
    with camera_inventory_lock:
        if now - camera_inventory_cache['checked_at'] < CAMERA_DISCOVERY_CACHE_SECONDS:
            return camera_inventory_cache['count']

    available_count = 0
    for camera_index in range(CAMERA_DISCOVERY_MAX_INDEX):
        cap = open_camera_capture(camera_index)
        try:
            if not cap.isOpened():
                continue
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, _ = cap.read()
            if ok:
                available_count += 1
        finally:
            cap.release()

    with camera_inventory_lock:
        camera_inventory_cache['count'] = available_count
        camera_inventory_cache['checked_at'] = now

    return available_count


# Single-record retrieval is centralized because most alert transitions start from the same lookup step.
def fetch_accident_row(conn, accident_id):
    return conn.execute('SELECT * FROM accidents WHERE id = ?', (accident_id,)).fetchone()


# Admin visibility rules keep the live review queue focused while still retaining dismissed or completed records in storage.
def accident_visible_to_admin(row):
    return get_alert_status(row) != 'false_alarm'


# Responder visibility is intentionally narrower so only dispatched incidents enter the active response queue.
def accident_visible_to_responder(row):
    return get_alert_status(row) in {'sent_to_responder', 'responded', 'closed'}


# Action responses share one serializer so asynchronous UI updates remain consistent after any alert transition.
def build_alert_action_response(conn, accident_id, message):
    row = fetch_accident_row(conn, accident_id)
    accident = serialize_accident(row)
    alert_counts = get_alert_counts(conn)
    return {
        'success': True,
        'id': accident_id,
        'status': accident['status'],
        'internal_status': accident['internal_status'],
        'response_status': accident['response_status'],
        'response_status_label': accident['response_status_label'],
        'assigned_responder': accident['assigned_responder'],
        'confidence_label': accident['confidence_label'],
        'notified': accident['notified'],
        'responded': accident['responded'],
        'closed': accident['closed'],
        'sent_at': accident['sent_at'],
        'responded_at': accident['responded_at'],
        'closed_at': accident['closed_at'],
        'time_to_respond': accident['time_to_respond'],
        'time_to_close': accident['time_to_close'],
        **alert_counts,
        'message': message,
    }


# Dispatch transitions are isolated here to keep responder handoff rules consistent across old and new endpoints.
def report_alert_by_id(accident_id):
    conn = get_db()
    row = fetch_accident_row(conn, accident_id)
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Accident not found'}), 404

    status = get_alert_status(row)
    if status == 'closed':
        response = build_alert_action_response(conn, accident_id, 'Alert already closed.')
        conn.close()
        return jsonify(response)

    if status in {'sent_to_responder', 'responded'}:
        response = build_alert_action_response(conn, accident_id, 'Alert already sent to responder.')
        conn.close()
        return jsonify(response)

    sent_at = row['sent_at'] or row['reported_at'] or time.time()
    conn.execute(
        '''
        UPDATE accidents
        SET notified = 1,
            status = 'sent_to_responder',
            response_status = COALESCE(response_status, 'pending'),
            assigned_responder = COALESCE(assigned_responder, 'Responder Team'),
            sent_at = ?,
            reported_at = COALESCE(reported_at, ?)
        WHERE id = ?
        ''',
        (sent_at, sent_at, accident_id)
    )
    conn.commit()
    response = build_alert_action_response(conn, accident_id, 'Alert sent to responder dashboard.')
    conn.close()
    return jsonify(response)


# False-alarm handling preserves evidence for auditability while removing non-actionable items from live operations.
def false_alarm_by_id(accident_id):
    conn = get_db()
    row = fetch_accident_row(conn, accident_id)
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Accident not found'}), 404

    status = get_alert_status(row)
    if status == 'closed':
        conn.close()
        return jsonify({'success': False, 'error': 'Closed alerts cannot be marked as false alarms.'}), 400

    if status in {'responded', 'sent_to_responder'}:
        conn.close()
        return jsonify({'success': False, 'error': 'This alert has already been sent to the responder dashboard.'}), 400

    conn.execute(
        '''
        UPDATE accidents
        SET status = 'false_alarm',
            notified = 0,
            responded = 0,
            closed = 0
        WHERE id = ?
        ''',
        (accident_id,)
    )
    conn.commit()
    response = build_alert_action_response(conn, accident_id, 'Alert marked as false alarm and kept in the database.')
    conn.close()
    return jsonify(response)


# Acknowledgement is stored separately from closure so the system can measure reaction time before full resolution time.
def respond_alert_by_id(accident_id):
    return update_responder_status_by_id(accident_id, 'acknowledged')


# Final closure is separated from acknowledgement to preserve a complete and measurable incident lifecycle.
def close_alert_by_id(accident_id):
    return update_responder_status_by_id(accident_id, 'resolved')


def update_responder_status_by_id(accident_id, response_status):
    # 1. Validate the requested responder state before touching the incident record.
    if response_status not in {'acknowledged', 'en_route', 'on_scene', 'resolved'}:
        return jsonify({'success': False, 'error': 'Invalid responder status.'}), 400

    conn = get_db()
    row = fetch_accident_row(conn, accident_id)
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Accident not found'}), 404

    status = get_alert_status(row)
    if status not in {'sent_to_responder', 'responded', 'closed'} and not row['notified']:
        conn.close()
        return jsonify({'success': False, 'error': 'This alert has not been sent to responders yet'}), 400

    if status == 'closed' and response_status != 'resolved':
        response = build_alert_action_response(conn, accident_id, 'Alert already closed.')
        conn.close()
        return jsonify(response)

    # 2. Preserve first-response timing while allowing status progress to continue.
    now = time.time()
    assigned_responder = session.get('user_email') or row['assigned_responder'] or 'Responder Team'
    if response_status == 'resolved':
        conn.execute(
            '''
            UPDATE accidents
            SET responded = 1,
                notified = 1,
                closed = 1,
                status = 'closed',
                response_status = 'resolved',
                assigned_responder = ?,
                responded_at = COALESCE(responded_at, ?),
                closed_at = COALESCE(closed_at, ?)
            WHERE id = ?
            ''',
            (assigned_responder, now, now, accident_id)
        )
    else:
        conn.execute(
            '''
            UPDATE accidents
            SET responded = 1,
                notified = 1,
                closed = 0,
                status = 'responded',
                response_status = ?,
                assigned_responder = ?,
                responded_at = COALESCE(responded_at, ?)
            WHERE id = ?
            ''',
            (response_status, assigned_responder, now, accident_id)
        )
    conn.commit()

    # 3. Return the updated state so both dashboards can refresh immediately.
    message = f"Responder status updated to {build_response_status_label(response_status)}."
    response = build_alert_action_response(conn, accident_id, message)
    conn.close()
    return jsonify(response)


# Snapshot persistence runs off the streaming path because evidence capture should not block live detection output.
def save_snapshot_background(frame_copy):
    # 1. Save Evidence Snapshot
    accident_id = str(uuid.uuid4())[:8]
    filename = f"accident_{accident_id}.jpg"
    filepath = os.path.join(ACCIDENTS_DIR, filename)
    captured_at = time.time()

    cv2.imwrite(filepath, frame_copy, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

    conn = get_db()
    conn.execute(
        '''
        INSERT INTO accidents (id, image, timestamp, notified)
        VALUES (?, ?, ?, ?)
        ''',
        (
            accident_id,
            filename,
            captured_at,
            0,
        )
    )
    conn.commit()
    conn.close()


# Frame processing owns inference, visual overlays, and alert signaling because those concerns must stay synchronized per image.
ACCIDENT_TRIGGER_CONFIDENCE = 0.68
ACCIDENT_CONFIRM_FRAMES = 2
ACCIDENT_ALERT_DELAY_SECONDS = 0.6
ACCIDENT_RESET_SECONDS = 1.5

accident_confirm_count = 0
accident_first_seen_time = None
accident_alert_sent = False
last_accident_seen_time = 0


def process_frame(frame):
    global accident_flag
    global accident_confirm_count
    global accident_first_seen_time
    global accident_alert_sent
    global last_accident_seen_time

    frame = cv2.resize(frame, (768, 432))
    results = model.predict(frame, imgsz=512, conf=0.45, verbose=False)

    accident_detected = False

    boxes = results[0].boxes
    if boxes is not None and boxes.data is not None:
        for row in boxes.data:
            x1, y1, x2, y2 = row[0:4]
            conf = row[4]
            cls_id = int(row[5])

            label = class_list[cls_id] if cls_id < len(class_list) else "Unknown"
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            confidence = float(conf)

            if label == "accident" and confidence >= ACCIDENT_TRIGGER_CONFIDENCE:
                accident_detected = True

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 4)
                cv2.putText(
                    frame,
                    f"ACCIDENT {confidence:.0%}",
                    (x1, y1 - 12),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA
                )
            else:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    f"{label} {confidence:.0%}",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA
                )

    now = time.time()

    if accident_detected:
        accident_confirm_count += 1
        last_accident_seen_time = now

        if accident_first_seen_time is None:
            accident_first_seen_time = now
    else:
        if now - last_accident_seen_time > ACCIDENT_RESET_SECONDS:
            accident_confirm_count = 0
            accident_first_seen_time = None
            accident_alert_sent = False

    confirmed_accident = (
        accident_confirm_count >= ACCIDENT_CONFIRM_FRAMES
        and accident_first_seen_time is not None
        and now - accident_first_seen_time >= ACCIDENT_ALERT_DELAY_SECONDS
    )

    if confirmed_accident:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        cv2.rectangle(overlay, (0, 0), (w, 65), (0, 0, 180), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        text = "!!! ACCIDENT DETECTED !!!"
        font = cv2.FONT_HERSHEY_DUPLEX
        (tw, th), _ = cv2.getTextSize(text, font, 1.1, 2)
        cx = (w - tw) // 2

        cv2.putText(frame, text, (cx + 2, 44), font, 1.1, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, (cx, 42), font, 1.1, (0, 255, 255), 2, cv2.LINE_AA)

        if int(time.time() * 3) % 2 == 0:
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 5)

        if not accident_alert_sent:
            with accident_flag_lock:
                accident_flag = True
            accident_alert_sent = True

    return frame, confirmed_accident

# Snapshot gating balances evidence retention against storage noise during sustained detections.
def try_save_snapshot(frame):
    global last_snapshot_time
    now = time.time()
    if now - last_snapshot_time >= 30:
        last_snapshot_time = now
        snapshot = frame.copy()
        threading.Thread(
            target=save_snapshot_background,
            args=(snapshot,),
            daemon=True
        ).start()


# Uploaded footage shares the same detection pipeline as live input so operator expectations stay consistent across sources.
def generate_video_frames():
    global current_video_path, current_video_filename, video_active

    if not current_video_path or not os.path.exists(current_video_path):
        return

    video_path = current_video_path
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print("Error opening video")
        return

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    video_active = True

    try:
        while video_active:
            ret, frame = cap.read()

            if not ret:
                break

            processed, detected = process_frame(frame)

            if detected:
                try_save_snapshot(processed)

            _, buffer = cv2.imencode('.jpg', processed, ENCODE_PARAM)

            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n'
                + buffer.tobytes()
                + b'\r\n'
            )

    finally:
        cap.release()
        video_active = False

        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
                print("Uploaded video deleted after analysis.")
            except Exception as e:
                print("Error deleting uploaded video:", e)

        if current_video_path == video_path:
            current_video_path = None
            current_video_filename = None
# Camera streaming is separated from uploaded playback because device access and lifecycle rules differ.
def generate_camera_frames():
    # 1. Live Camera Streaming
    global camera_active

    cap = open_camera_capture(0)
    if not cap.isOpened():
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    camera_active = True

    while camera_active:
        ret, frame = cap.read()
        if not ret:
            break

        processed, detected = process_frame(frame)

        if detected:
            try_save_snapshot(processed)

        _, buffer = cv2.imencode('.jpg', processed, ENCODE_PARAM)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    cap.release()
    camera_active = False




# =========================
# 1. Route Configuration
# =========================

# Authentication routes combine sign-in and sign-up because this deployment keeps onboarding lightweight and local.
@app.route('/login.html', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
# Login coordinates account creation, credential verification, and role-aware redirection into protected workflows.
def login():
    if 'user_id' in session:
        return redirect(get_post_login_url())

    error = None
    success = None
    selected_role = request.args.get('role') or session.get('pending_registration_role')
    selected_role = selected_role if selected_role in {'admin', 'responder'} else 'admin'
    role_locked = 'pending_registration_role' in session
    show_signup = request.args.get('mode') == 'signup'

    if request.args.get('registered') == '1':
        success = 'Account created successfully! Please sign in.'

    if request.method == 'POST':
        form_type = request.form.get('form_type')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if form_type == 'signup':
            show_signup = True
            confirm = request.form.get('confirm_password', '')
            role = session.get('pending_registration_role')
            conn = get_db()

            if role not in {'admin', 'responder'}:
                conn.close()
                return redirect(url_for('select_role'))
            if not email or not password:
                error = 'Please fill in all fields.'
            elif '@' not in email or '.' not in email:
                error = 'Please enter a valid email address.'
            elif len(password) < 4:
                error = 'Password must be at least 4 characters.'
            elif password != confirm:
                error = 'Passwords do not match.'
            elif role not in {'admin', 'responder'}:
                error = 'Please select a valid role.'
            else:
                existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
                if existing:
                    error = 'An account with this email already exists.'
                else:
                    conn.execute(
                        'INSERT INTO users (email, password, role) VALUES (?, ?, ?)',
                        (email, hash_password(password), role)
                    )
                    conn.commit()
                    session.pop('pending_registration_role', None)
                    conn.close()
                    return redirect(url_for('login', registered=1))
            conn.close()

        elif form_type == 'login':
            conn = get_db()
            user = conn.execute(
                'SELECT * FROM users WHERE email = ?',
                (email,)
            ).fetchone()

            password_ok, needs_password_upgrade = verify_password(user['password'], password) if user else (False, False)
            if user and password_ok:
                if needs_password_upgrade:
                    conn.execute(
                        'UPDATE users SET password = ? WHERE id = ?',
                        (hash_password(password), user['id'])
                    )
                    conn.commit()
                conn.close()
                session['user_id'] = user['id']
                session['user_email'] = email
                session['user_role'] = user['role'] if user['role'] in {'admin', 'responder'} else 'admin'
                return redirect(get_post_login_url())
            else:
                conn.close()
                error = 'Invalid email or password.'

    return render_template(
        'login.html',
        error=error,
        success=success,
        show_signup=show_signup,
        selected_role=selected_role,
        role_locked=role_locked
    )


@app.route('/select_role.html', methods=['GET', 'POST'])
@app.route('/select-role', methods=['GET', 'POST'], endpoint='select_role')
# Role selection is the single entry point into role-specific registration.
def select_role():
    if request.method == 'POST':
        role = request.form.get('role', '').strip().lower()
        if role == 'admin':
            return redirect(url_for('register_admin'))
        if role == 'responder':
            return redirect(url_for('register_responder'))
    return render_template('select_role.html')


@app.route('/register/admin')
# 1. Admin selection opens the existing registration form with the Admin role locked.
def register_admin():
    session['pending_registration_role'] = 'admin'
    return redirect(url_for('login', mode='signup', role='admin'))


@app.route('/register/responder')
# 2. Responder selection opens the existing registration form with the Responder role locked.
def register_responder():
    session['pending_registration_role'] = 'responder'
    return redirect(url_for('login', mode='signup', role='responder'))


# Explicit logout exists because shared operator machines require a clear and immediate session reset path.
@app.route('/logout')
# Logout reinforces cache controls so previously viewed protected pages are not resurfaced by the browser.
def logout():
    session.clear()
    response = redirect(url_for('intro'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# The public landing page stays separate from the dashboard to support unauthenticated discovery of the system.
@app.route('/intro.html')
@app.route('/')
# The introduction page presents product context before an operator signs in.
def intro():
    return render_template('intro.html')


# A role-aware home redirect preserves older navigation paths without duplicating dashboard selection logic.
@app.route('/home', endpoint='home')
@login_required
# Home resolves through one redirect point so role-specific landing behavior remains centralized.
def home():
    return redirect(get_post_login_url())


# =========================
# 4. Admin Routes
# =========================

# The dashboard route exposes the shared operational overview used after authentication.
@app.route('/dashboard', endpoint='dashboard')
@admin_required
# Dashboard rendering stays thin so metrics and navigation composition continue to come from shared helpers.
def dashboard():
    return render_dashboard_page()


@app.route('/home.html', endpoint='admin_home_file')
@admin_required
# The home.html alias keeps the requested admin dashboard filename available.
def admin_home_file():
    return render_dashboard_page()


# Detection controls are admin-only because they can create new evidence and trigger downstream alerts.
@app.route('/detect.html')
@app.route('/detect')
@admin_required
# The detect page hosts ingestion controls for uploaded footage and live camera monitoring.
def detect():
    return render_template('detect.html', **build_dashboard_context())


# Admin alerts are kept separate from responder work queues so each role has a clear page boundary.
@app.route('/alerts.html')
@app.route('/alerts')
@admin_required
# Alert listing applies role-scoped visibility before rendering so each audience sees only relevant work.
def alerts_page():
    conn = get_db()
    rows = conn.execute('SELECT * FROM accidents ORDER BY timestamp DESC').fetchall()
    alert_counts = get_alert_counts(conn)
    conn.close()

    accidents = [serialize_accident(row) for row in rows if accident_visible_to_admin(row)]

    context = build_dashboard_context()
    context.update(alert_counts)

    return render_template('alerts.html', accidents=accidents, **context)


# =========================
# 5. Responder Routes
# =========================

@app.route('/responder', endpoint='responder_dashboard')
# The responder dashboard shows only dispatched active incidents.
@responder_required
def responder_dashboard():
    return render_responder_queue()


def render_responder_queue():
    conn = get_db()
    rows = conn.execute('SELECT * FROM accidents ORDER BY timestamp DESC').fetchall()
    alert_counts = get_alert_counts(conn)
    conn.close()

    accidents = [serialize_accident(row) for row in rows if accident_visible_to_responder(row)]
    responder_stats = {
        'assigned_alerts_count': len(accidents),
        'pending_alerts_count': sum(1 for accident in accidents if accident['response_status'] == 'pending'),
        'acknowledged_alerts_count': sum(1 for accident in accidents if accident['response_status'] in {'acknowledged', 'en_route', 'on_scene'}),
        'resolved_alerts_count': sum(1 for accident in accidents if accident['response_status'] == 'resolved'),
        'response_status_chart': [
            {'key': 'pending', 'label': 'Pending', 'count': sum(1 for accident in accidents if accident['response_status'] == 'pending')},
            {'key': 'acknowledged', 'label': 'Acknowledged', 'count': sum(1 for accident in accidents if accident['response_status'] == 'acknowledged')},
            {'key': 'en_route', 'label': 'En Route', 'count': sum(1 for accident in accidents if accident['response_status'] == 'en_route')},
            {'key': 'on_scene', 'label': 'On Scene', 'count': sum(1 for accident in accidents if accident['response_status'] == 'on_scene')},
            {'key': 'resolved', 'label': 'Resolved', 'count': sum(1 for accident in accidents if accident['response_status'] == 'resolved')},
        ],
    }
    context = build_dashboard_context()
    context.update(alert_counts)
    context.update(responder_stats)
    return render_template('respond.html', accidents=accidents, **context)


@app.route('/responder_alert.html')
@app.route('/responder/alerts', endpoint='responder_alerts')
# Responder alert navigation opens the first assigned alert in the update workspace.
@responder_required
def responder_alerts():
    conn = get_db()
    rows = conn.execute('SELECT * FROM accidents ORDER BY timestamp DESC').fetchall()
    conn.close()

    accidents = [serialize_accident(row) for row in rows if accident_visible_to_responder(row)]
    return render_responder_alert_page(None, accidents)


@app.route('/responder/alert/<accident_id>', endpoint='responder_alert_detail')
# A responder-only detail page is available for direct incident review.
@responder_required
def responder_alert_detail(accident_id):
    conn = get_db()
    row = fetch_accident_row(conn, accident_id)

    if not row or not accident_visible_to_responder(row):
        conn.close()
        return redirect(url_for('responder_dashboard'))

    accidents = [serialize_accident(item) for item in conn.execute('SELECT * FROM accidents ORDER BY timestamp DESC').fetchall() if accident_visible_to_responder(item)]
    conn.close()
    return render_responder_alert_page(serialize_accident(row), accidents)


def render_responder_alert_page(accident, accidents=None):
    return render_template(
        'responder_alert.html',
        acc=accident,
        accidents=accidents or [],
        me=session.get('user_email', 'Responder'),
        **build_dashboard_context()
    )


# Dedicated action endpoints make alert transitions explicit, auditable, and easier to secure.
@app.route('/report_alert/<accident_id>', methods=['POST'])
@admin_required
# Reporting delegates to shared transition logic so compatibility and new UI flows stay aligned.
def report_alert(accident_id):
    return report_alert_by_id(accident_id)


@app.route('/false_alarm/<accident_id>', methods=['POST'])
@admin_required
# Administrative dismissal is exposed separately from responder closure because the two actions represent different intent.
def false_alarm(accident_id):
    return false_alarm_by_id(accident_id)


@app.route('/respond_alert/<accident_id>', methods=['POST'])
@responder_required
# A dedicated acknowledgement endpoint supports the responder's two-step workflow.
def respond_alert(accident_id):
    return respond_alert_by_id(accident_id)


@app.route('/close_alert/<accident_id>', methods=['POST'])
@responder_required
# A dedicated closure endpoint preserves the distinction between acknowledging and fully resolving an incident.
def close_alert(accident_id):
    return close_alert_by_id(accident_id)


@app.route('/responder/update-status', methods=['POST'], endpoint='responder_update_status')
# Status updates from the responder detail page map onto the supported incident lifecycle.
@responder_required
def responder_update_status():
    data = request.get_json() or {}
    accident_id = data.get('id')
    status = data.get('status')

    if status in {'acknowledged', 'en_route', 'on_scene'}:
        return update_responder_status_by_id(accident_id, status)
    if status == 'resolved':
        return update_responder_status_by_id(accident_id, status)
    return jsonify({'success': False, 'error': 'Invalid responder status.'}), 400


# The legacy dispatch endpoint remains for compatibility with older front-end interactions.
@app.route('/contact_authority', methods=['POST'])
@login_required
# This compatibility wrapper forwards old admin actions into the current reporting lifecycle.
def contact_authority():
    if get_current_role() != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    accident_id = data.get('id')
    return report_alert_by_id(accident_id)


# The legacy responder endpoint remains available so older clients continue to function during workflow evolution.
@app.route('/mark_responded', methods=['POST'])
@login_required
# This wrapper maps the historical single-button responder flow onto the newer respond-then-close model.
def mark_responded():
    if get_current_role() != 'responder':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json() or {}
    accident_id = data.get('id')
    conn = get_db()
    row = fetch_accident_row(conn, accident_id)
    conn.close()
    if not row:
        return jsonify({'success': False, 'error': 'Accident not found'}), 404

    if get_alert_status(row) == 'responded' or row['responded']:
        return close_alert_by_id(accident_id)
    return respond_alert_by_id(accident_id)




# Upload handling is kept separate from streaming endpoints because file validation and playback control have different concerns.
@app.route('/upload', methods=['POST'])
@admin_required
# Upload processing resets previous playback state so only one uploaded source drives detection at a time.
def upload_video():
    global current_video_path, current_video_filename, video_active

    video_active = False
    time.sleep(0.3)

    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400

    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: mp4, avi, mov, mkv, wmv, webm'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    current_video_path = filepath
    current_video_filename = filename

    return jsonify({'success': True, 'filename': filename})


# Multipart streaming routes keep the browser preview simple without introducing websocket infrastructure.
@app.route('/video_feed')
@admin_required
# Uploaded video frames are served incrementally so processed output appears in near real time.
def video_feed():
    return Response(generate_video_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/uploads/<path:filename>', endpoint='uploaded_file')
@login_required
# Uploaded evidence is served only to authenticated operators for preview and review.
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# Live camera streaming has its own route because device-backed capture has distinct lifecycle and failure behavior.
@app.route('/camera_feed')
@admin_required
# Camera streaming mirrors the uploaded-feed contract to simplify front-end integration.
def camera_feed():
    return Response(generate_camera_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# Snapshot-based camera processing supports browsers that submit individual frames instead of consuming a continuous stream.
@app.route('/process_camera_frame', methods=['POST'])
@admin_required
# This endpoint decodes incoming image payloads, runs inference, and returns an annotated preview frame.
def process_camera_frame():
    try:
        frame = None

        if 'frame' in request.files:
            image_bytes = request.files['frame'].read()
        else:
            data = request.get_json(silent=True) or {}
            frame_data = data.get('frame') or data.get('image')

            if not frame_data:
                return jsonify({'success': False, 'error': 'No frame provided'}), 400

            if ',' in frame_data:
                frame_data = frame_data.split(',', 1)[1]

            image_bytes = base64.b64decode(frame_data)

        np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid frame data'}), 400

    if frame is None:
        return jsonify({'success': False, 'error': 'Unable to decode frame'}), 400

    try:
        processed, detected = process_frame(frame)

        if detected:
            try_save_snapshot(processed)

        ok, buffer = cv2.imencode('.jpg', processed, ENCODE_PARAM)
        if not ok:
            return jsonify({'success': False, 'error': 'Unable to encode frame'}), 500

        encoded = base64.b64encode(buffer.tobytes()).decode('ascii')
        return jsonify({
            'success': True,
            'detected': detected,
            'image': f'data:image/jpeg;base64,{encoded}'
        })
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Camera processing failed: {exc}'}), 500


# Explicit stop routes let the UI terminate long-running stream generators without restarting the app.
@app.route('/stop_video', methods=['POST'])
@admin_required
def stop_video():
    global video_active, current_video_path, current_video_filename

    video_active = False

    if current_video_path and os.path.exists(current_video_path):
        try:
            os.remove(current_video_path)
            print("Video deleted successfully.")
        except Exception as e:
            print("Error deleting video:", e)

    current_video_path = None
    current_video_filename = None

    return jsonify({'success': True})

@app.route('/stop_camera', methods=['POST'])
@admin_required
# Camera shutdown exists to release the device promptly when operators leave live mode.
def stop_camera():
    global camera_active
    camera_active = False
    return jsonify({'success': True})


# Polling-based alert signaling keeps browser audio warnings decoupled from frame transport.
@app.route('/accident_status')
@admin_required
# Sound-trigger polling resets after each read so one detection does not repeat indefinitely in the client.
def accident_status():
    """Polled by browser to trigger sound — returns True once then resets."""
    global accident_flag
    with accident_flag_lock:
        status = accident_flag
        accident_flag = False
    return jsonify({'accident': status})



# Direct execution support keeps local development straightforward without affecting production deployment patterns.
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000,
            use_reloader=False, threaded=True)



