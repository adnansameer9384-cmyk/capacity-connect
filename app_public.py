from flask import (
    Flask, request, redirect, url_for, render_template_string,
    session, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import sqlite3
import os
import datetime
import uuid

# ============================================================
# CAPACITY CONNECT
# Professional SIH Prototype
# ============================================================

app = Flask(__name__)

app.secret_key = "capacity-connect-sih-secret-key-change-this"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "capacity_connect.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "pdf", "ppt", "pptx", "doc", "docx",
    "txt", "mp4", "webm", "png", "jpg", "jpeg"
}


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():

    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'trainee',
        approved INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS trainee_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        qualifications TEXT,
        experience TEXT,
        interests TEXT,
        skills TEXT,
        certificates TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS trainer_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        specialization TEXT,
        experience TEXT,
        skills TEXT,
        bio TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        category TEXT,
        trainer_id INTEGER NOT NULL,
        duration TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trainer_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainee_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        enrolled_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(trainee_id, course_id),
        FOREIGN KEY(trainee_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        trainer_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        resource_type TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
        FOREIGN KEY(trainer_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        trainer_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,
        correct_answer TEXT NOT NULL,
        deadline TEXT,
        FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
        FOREIGN KEY(trainer_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainee_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        attempted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trainee_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainee_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trainee_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    """)

    # Create default admin
    admin = cur.execute(
        "SELECT id FROM users WHERE email = ?",
        ("admin@capacityconnect.com",)
    ).fetchone()

    if not admin:
        cur.execute("""
            INSERT INTO users
            (name, email, password, role, approved)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "System Administrator",
            "admin@capacityconnect.com",
            generate_password_hash("Admin@123"),
            "admin",
            1
        ))

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def allowed_file(filename):
    return (
        "." in filename and
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def current_user():
    if "user_id" not in session:
        return None

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return user


def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            flash("Please login to continue.", "warning")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


def role_required(role):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            user = current_user()

            if not user:
                return redirect(url_for("login"))

            if user["role"] != role:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("dashboard"))

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================
# TEMPLATE
# ============================================================

BASE_TEMPLATE = """

<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>{{ title }} | CAPACITY CONNECT</title>

<link rel="preconnect" href="https://fonts.googleapis.com">

<link rel="preconnect"
href="https://fonts.gstatic.com"
crossorigin>

<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
rel="stylesheet">

<style>

:root {
    --primary: #2563eb;
    --primary-dark: #1d4ed8;
    --secondary: #0f172a;
    --bg: #f8fafc;
    --card: #ffffff;
    --text: #0f172a;
    --muted: #64748b;
    --border: #e2e8f0;
    --success: #16a34a;
    --warning: #d97706;
    --danger: #dc2626;
    --purple: #7c3aed;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: "Inter", sans-serif;
    background: var(--bg);
    color: var(--text);
}

a {
    text-decoration: none;
    color: inherit;
}

button,
input,
textarea,
select {
    font-family: inherit;
}

.navbar {
    height: 72px;
    background: #ffffff;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 6%;
    position: sticky;
    top: 0;
    z-index: 100;
}

.logo {
    display: flex;
    align-items: center;
    gap: 12px;
    font-weight: 800;
    font-size: 19px;
}

.logo-icon {
    width: 40px;
    height: 40px;
    border-radius: 11px;
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 800;
}

.nav-links {
    display: flex;
    align-items: center;
    gap: 25px;
}

.nav-links a {
    color: #475569;
    font-size: 14px;
    font-weight: 600;
}

.nav-links a:hover {
    color: var(--primary);
}

.user-pill {
    padding: 9px 14px;
    background: #eff6ff;
    color: var(--primary);
    border-radius: 30px;
    font-size: 13px;
    font-weight: 700;
}

.container {
    width: 88%;
    max-width: 1250px;
    margin: auto;
}

.hero {
    padding: 90px 0;
    background:
        radial-gradient(circle at 85% 20%, #dbeafe 0, transparent 30%),
        radial-gradient(circle at 15% 80%, #ede9fe 0, transparent 28%),
        #ffffff;
}

.hero-grid {
    display: grid;
    grid-template-columns: 1.1fr .9fr;
    gap: 60px;
    align-items: center;
}

.hero h1 {
    font-size: clamp(40px, 5vw, 68px);
    line-height: 1.02;
    margin: 0 0 25px;
    letter-spacing: -2.5px;
}

.gradient-text {
    background: linear-gradient(90deg, #2563eb, #7c3aed);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.hero p {
    color: var(--muted);
    font-size: 18px;
    line-height: 1.8;
    max-width: 650px;
}

.hero-buttons {
    margin-top: 30px;
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
}

.btn {
    border: none;
    cursor: pointer;
    padding: 12px 20px;
    border-radius: 10px;
    font-weight: 700;
    font-size: 14px;
    display: inline-block;
    transition: .2s;
}

.btn:hover {
    transform: translateY(-1px);
}

.btn-primary {
    background: var(--primary);
    color: white;
}

.btn-primary:hover {
    background: var(--primary-dark);
}

.btn-dark {
    background: var(--secondary);
    color: white;
}

.btn-light {
    background: white;
    border: 1px solid var(--border);
    color: var(--text);
}

.btn-success {
    background: var(--success);
    color: white;
}

.btn-danger {
    background: var(--danger);
    color: white;
}

.btn-warning {
    background: var(--warning);
    color: white;
}

.hero-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 25px;
    padding: 30px;
    box-shadow: 0 25px 70px rgba(15, 23, 42, .10);
}

.hero-card-top {
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    color: white;
    padding: 28px;
    border-radius: 18px;
    margin-bottom: 20px;
}

.hero-card-top h3 {
    margin: 0 0 8px;
}

.mini-stat {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 17px 0;
    border-bottom: 1px solid var(--border);
}

.mini-stat:last-child {
    border-bottom: none;
}

.section {
    padding: 70px 0;
}

.section-title {
    text-align: center;
    margin-bottom: 45px;
}

.section-title h2 {
    font-size: 34px;
    margin: 0 0 12px;
}

.section-title p {
    color: var(--muted);
}

.features {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
}

.feature-card {
    background: white;
    border: 1px solid var(--border);
    padding: 28px;
    border-radius: 18px;
}

.feature-icon {
    width: 48px;
    height: 48px;
    border-radius: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #eff6ff;
    color: var(--primary);
    font-size: 22px;
    margin-bottom: 18px;
}

.feature-card h3 {
    margin: 0 0 10px;
}

.feature-card p {
    color: var(--muted);
    line-height: 1.7;
    font-size: 14px;
}

.footer {
    background: #0f172a;
    color: white;
    padding: 45px 0;
    margin-top: 60px;
}

.footer p {
    color: #94a3b8;
}

.auth-wrapper {
    min-height: calc(100vh - 72px);
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 50px 20px;
}

.auth-card {
    background: white;
    width: 100%;
    max-width: 480px;
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 35px;
    box-shadow: 0 20px 60px rgba(15,23,42,.08);
}

.auth-card h2 {
    margin-top: 0;
    font-size: 28px;
}

.auth-card p {
    color: var(--muted);
}

.form-group {
    margin-bottom: 17px;
}

.form-group label {
    display: block;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 7px;
}

.form-control {
    width: 100%;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: 9px;
    outline: none;
    background: white;
}

.form-control:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(37,99,235,.10);
}

textarea.form-control {
    min-height: 110px;
    resize: vertical;
}

.dashboard {
    padding: 40px 0 80px;
}

.page-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 20px;
    margin-bottom: 30px;
}

.page-heading h1 {
    margin: 0;
    font-size: 32px;
}

.page-heading p {
    color: var(--muted);
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 18px;
    margin-bottom: 30px;
}

.stat-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 17px;
    padding: 22px;
}

.stat-icon {
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #eff6ff;
    color: var(--primary);
    border-radius: 11px;
    margin-bottom: 14px;
}

.stat-number {
    font-size: 28px;
    font-weight: 800;
}

.stat-label {
    color: var(--muted);
    font-size: 13px;
    margin-top: 5px;
}

.grid-2 {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 22px;
}

.grid-3 {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
}

.card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 17px;
    padding: 24px;
    margin-bottom: 20px;
}

.card h2,
.card h3 {
    margin-top: 0;
}

.course-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: 17px;
    overflow: hidden;
}

.course-top {
    height: 125px;
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    padding: 23px;
    color: white;
}

.course-body {
    padding: 22px;
}

.course-body p {
    color: var(--muted);
    line-height: 1.6;
    font-size: 14px;
}

.course-meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin: 15px 0;
}

.badge {
    display: inline-block;
    padding: 6px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    background: #eff6ff;
    color: var(--primary);
}

.badge-success {
    background: #dcfce7;
    color: #15803d;
}

.badge-warning {
    background: #fef3c7;
    color: #92400e;
}

.badge-danger {
    background: #fee2e2;
    color: #b91c1c;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th,
td {
    padding: 14px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
}

th {
    background: #f8fafc;
    font-weight: 800;
}

.alert {
    padding: 13px 17px;
    border-radius: 10px;
    margin: 15px 0;
    font-size: 14px;
}

.alert-success {
    background: #dcfce7;
    color: #166534;
}

.alert-danger {
    background: #fee2e2;
    color: #991b1b;
}

.alert-warning {
    background: #fef3c7;
    color: #92400e;
}

.announcement {
    border-left: 4px solid var(--primary);
    background: white;
    border: 1px solid var(--border);
    padding: 20px;
    border-radius: 12px;
    margin-bottom: 14px;
}

.announcement h3 {
    margin: 0 0 7px;
}

.announcement p {
    margin: 0;
    color: var(--muted);
    line-height: 1.6;
}

.profile-grid {
    display: grid;
    grid-template-columns: 260px 1fr;
    gap: 22px;
}

.profile-side {
    background: linear-gradient(145deg, #0f172a, #1e293b);
    color: white;
    border-radius: 18px;
    padding: 25px;
}

.avatar {
    width: 75px;
    height: 75px;
    background: linear-gradient(135deg, #2563eb, #7c3aed);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 25px;
    font-weight: 800;
    margin-bottom: 17px;
}

.profile-side p {
    color: #cbd5e1;
    font-size: 13px;
}

.empty {
    text-align: center;
    padding: 45px;
    color: var(--muted);
}

.resource {
    display: flex;
    justify-content: space-between;
    gap: 15px;
    align-items: center;
    padding: 17px;
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 10px;
}

.resource strong {
    font-size: 14px;
}

.small {
    font-size: 12px;
    color: var(--muted);
}

.question {
    background: #f8fafc;
    padding: 20px;
    border-radius: 12px;
    margin-bottom: 17px;
    border: 1px solid var(--border);
}

.question h4 {
    margin-top: 0;
}

.option {
    display: block;
    background: white;
    padding: 11px;
    border: 1px solid var(--border);
    border-radius: 8px;
    margin: 7px 0;
    cursor: pointer;
}

.option:hover {
    border-color: var(--primary);
}

.progress {
    height: 9px;
    background: #e2e8f0;
    border-radius: 20px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #2563eb, #7c3aed);
}

.competency {
    border: 1px solid var(--border);
    padding: 18px;
    border-radius: 13px;
    margin-bottom: 12px;
}

.score {
    font-size: 35px;
    font-weight: 800;
    color: var(--primary);
}

@media(max-width: 900px) {

    .hero-grid,
    .grid-2,
    .profile-grid {
        grid-template-columns: 1fr;
    }

    .features,
    .grid-3 {
        grid-template-columns: repeat(2, 1fr);
    }

    .stats-grid {
        grid-template-columns: repeat(2, 1fr);
    }

    .nav-links {
        gap: 10px;
    }
}

@media(max-width: 600px) {

    .navbar {
        padding: 0 4%;
    }

    .nav-links a:not(.user-pill) {
        display: none;
    }

    .container {
        width: 92%;
    }

    .features,
    .grid-3,
    .stats-grid {
        grid-template-columns: 1fr;
    }

    .hero {
        padding: 55px 0;
    }

    .hero h1 {
        font-size: 42px;
    }

    .page-heading {
        flex-direction: column;
        align-items: flex-start;
    }
}

</style>

</head>

<body>

<nav class="navbar">

<a href="{{ url_for('home') }}" class="logo">
    <div class="logo-icon">CC</div>
    <span>CAPACITY CONNECT</span>
</a>

<div class="nav-links">

{% if session.get("user_id") %}

<a href="{{ url_for('dashboard') }}">Dashboard</a>

{% if session.get("role") == "trainee" %}
<a href="{{ url_for('courses') }}">Courses</a>
<a href="{{ url_for('trainee_profile') }}">Profile</a>
{% endif %}

{% if session.get("role") == "trainer" %}
<a href="{{ url_for('trainer_courses') }}">My Courses</a>
<a href="{{ url_for('trainer_profile') }}">Profile</a>
{% endif %}

{% if session.get("role") == "admin" %}
<a href="{{ url_for('admin_users') }}">Users</a>
<a href="{{ url_for('admin_announcements') }}">Announcements</a>
{% endif %}

<span class="user-pill">
{{ session.get("name") }}
</span>

<a href="{{ url_for('logout') }}">Logout</a>

{% else %}

<a href="{{ url_for('home') }}">Home</a>
<a href="{{ url_for('login') }}">Login</a>
<a class="btn btn-primary" href="{{ url_for('register') }}">
Get Started
</a>

{% endif %}

</div>

</nav>

{% with messages = get_flashed_messages(with_categories=true) %}

{% if messages %}

<div class="container">

{% for category, message in messages %}

<div class="alert alert-{{ category }}">
{{ message }}
</div>

{% endfor %}

</div>

{% endif %}

{% endwith %}

{{ content|safe }}

<footer class="footer">

<div class="container">

<h3>CAPACITY CONNECT</h3>

<p>
Digital Capacity Building & Learning Management Portal
</p>

<p class="small">
Empowering organizations through structured learning,
competency development and knowledge sharing.
</p>

</div>

</footer>

</body>
</html>
"""


def render_page(title, body, **context):

    template = BASE_TEMPLATE.replace(
        "{{ content|safe }}",
        body
    )

    return render_template_string(
        template,
        title=title,
        **context
    )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    conn = get_db()

    announcements = conn.execute("""
        SELECT * FROM announcements
        ORDER BY id DESC
        LIMIT 5
    """).fetchall()

    course_count = conn.execute(
        "SELECT COUNT(*) AS c FROM courses"
    ).fetchone()["c"]

    trainee_count = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role='trainee'"
    ).fetchone()["c"]

    trainer_count = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role='trainer'"
    ).fetchone()["c"]

    conn.close()

    body = """

<section class="hero">

<div class="container hero-grid">

<div>

<div class="badge">
DIGITAL CAPACITY BUILDING PLATFORM
</div>

<h1>
Learn. Develop.
<span class="gradient-text">Connect.</span>
</h1>

<p>
CAPACITY CONNECT is a centralized learning and competency
management platform designed to connect trainees, trainers
and administrators in one intelligent digital ecosystem.
</p>

<div class="hero-buttons">

<a class="btn btn-primary"
href="{{ url_for('register') }}">
Start Learning
</a>

<a class="btn btn-light"
href="{{ url_for('login') }}">
Explore Portal
</a>

</div>

</div>

<div class="hero-card">

<div class="hero-card-top">

<h3>Learning at a glance</h3>

<p>
One platform. Multiple capabilities.
</p>

</div>

<div class="mini-stat">
<span>Active Courses</span>
<strong>{{ course_count }}</strong>
</div>

<div class="mini-stat">
<span>Trainees</span>
<strong>{{ trainee_count }}</strong>
</div>

<div class="mini-stat">
<span>Expert Trainers</span>
<strong>{{ trainer_count }}</strong>
</div>

<div class="mini-stat">
<span>Role-based Access</span>
<strong>✓</strong>
</div>

</div>

</div>

</section>


<section class="section">

<div class="container">

<div class="section-title">

<h2>Everything you need to build capability</h2>

<p>
A complete digital ecosystem for organizational learning.
</p>

</div>

<div class="features">

<div class="feature-card">

<div class="feature-icon">🎓</div>

<h3>Smart Learning</h3>

<p>
Enroll in structured courses, access resources,
watch recorded lectures and build professional skills.
</p>

</div>

<div class="feature-card">

<div class="feature-icon">📊</div>

<h3>Performance Analytics</h3>

<p>
Track assessments, participation, progress and
learning performance through intuitive dashboards.
</p>

</div>

<div class="feature-card">

<div class="feature-icon">👨‍🏫</div>

<h3>Trainer Management</h3>

<p>
Empower trainers with course creation, resource
management, assessments and trainee monitoring.
</p>

</div>

<div class="feature-card">

<div class="feature-icon">🧠</div>

<h3>Competency Mapping</h3>

<p>
Identify trainers whose expertise matches the
required subject competencies.
</p>

</div>

<div class="feature-card">

<div class="feature-icon">📝</div>

<h3>Digital Assessments</h3>

<p>
Conduct subject-wise MCQ assessments with deadlines
and automatic score calculation.
</p>

</div>

<div class="feature-card">

<div class="feature-icon">📢</div>

<h3>Centralized Communication</h3>

<p>
Publish announcements, achievements and newly added
learning content from one administration portal.
</p>

</div>

</div>

</div>

</section>


<section class="section">

<div class="container">

<div class="section-title">

<h2>Latest Announcements</h2>

</div>

{% if announcements %}

{% for a in announcements %}

<div class="announcement">

<h3>{{ a["title"] }}</h3>

<p>{{ a["message"] }}</p>

<div class="small" style="margin-top:10px">
{{ a["created_at"] }}
</div>

</div>

{% endfor %}

{% else %}

<div class="card empty">
No announcements published yet.
</div>

{% endif %}

</div>

</section>

"""

    return render_page(
        "Home",
        body,
        announcements=announcements,
        course_count=course_count,
        trainee_count=trainee_count,
        trainer_count=trainer_count
    )


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]

        if role not in ["trainee", "trainer"]:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("register"))

        if not name or not email or not password:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("register"))

        conn = get_db()

        existing = conn.execute(
            "SELECT id FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if existing:

            conn.close()

            flash("An account with this email already exists.", "danger")

            return redirect(url_for("register"))

        cur = conn.execute("""
            INSERT INTO users
            (name, email, password, role, approved)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            email,
            generate_password_hash(password),
            role,
            1 if role == "trainee" else 0
        ))

        user_id = cur.lastrowid

        if role == "trainee":

            conn.execute("""
                INSERT INTO trainee_profiles
                (user_id, qualifications, experience,
                 interests, skills, certificates)
                VALUES (?, '', '', '', '', '')
            """, (user_id,))

        else:

            conn.execute("""
                INSERT INTO trainer_profiles
                (user_id, specialization, experience,
                 skills, bio)
                VALUES (?, '', '', '', '')
            """, (user_id,))

        conn.commit()
        conn.close()

        if role == "trainer":

            flash(
                "Registration successful. Your trainer account "
                "must be approved by an administrator.",
                "warning"
            )

        else:

            flash(
                "Registration successful. You can now login.",
                "success"
            )

        return redirect(url_for("login"))

    body = """

<div class="auth-wrapper">

<div class="auth-card">

<h2>Create your account</h2>

<p>
Join CAPACITY CONNECT and start your learning journey.
</p>

<form method="POST">

<div class="form-group">

<label>Full Name</label>

<input
class="form-control"
name="name"
required
placeholder="Enter your full name">

</div>


<div class="form-group">

<label>Email Address</label>

<input
class="form-control"
type="email"
name="email"
required
placeholder="you@example.com">

</div>


<div class="form-group">

<label>Password</label>

<input
class="form-control"
type="password"
name="password"
required
placeholder="Create a secure password">

</div>


<div class="form-group">

<label>Account Type</label>

<select class="form-control" name="role" required>

<option value="trainee">Trainee</option>

<option value="trainer">Trainer</option>

</select>

</div>


<button class="btn btn-primary"
style="width:100%">

Create Account

</button>

</form>

<p style="text-align:center;margin-top:20px">

Already have an account?

<a href="{{ url_for('login') }}"
style="color:#2563eb;font-weight:700">

Login

</a>

</p>

</div>

</div>

"""

    return render_page("Register", body)


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        conn.close()

        if not user or not check_password_hash(
            user["password"],
            password
        ):

            flash("Invalid email or password.", "danger")

            return redirect(url_for("login"))

        if not user["approved"]:

            flash(
                "Your account is waiting for administrator approval.",
                "warning"
            )

            return redirect(url_for("login"))

        session.clear()

        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["role"] = user["role"]

        flash(
            f"Welcome back, {user['name']}!",
            "success"
        )

        return redirect(url_for("dashboard"))

    body = """

<div class="auth-wrapper">

<div class="auth-card">

<h2>Welcome back</h2>

<p>
Login to access your CAPACITY CONNECT dashboard.
</p>

<form method="POST">

<div class="form-group">

<label>Email Address</label>

<input
class="form-control"
type="email"
name="email"
required
placeholder="you@example.com">

</div>


<div class="form-group">

<label>Password</label>

<input
class="form-control"
type="password"
name="password"
required
placeholder="Enter your password">

</div>


<button class="btn btn-primary"
style="width:100%">

Login to Portal

</button>

</form>


<div class="card"
style="margin-top:25px;background:#f8fafc">

<strong>Demo Administrator</strong>

<p class="small">

Email:
admin@capacityconnect.com

<br>

Password:
Admin@123

</p>

</div>


<p style="text-align:center">

New here?

<a href="{{ url_for('register') }}"
style="color:#2563eb;font-weight:700">

Create account

</a>

</p>

</div>

</div>

"""

    return render_page("Login", body)


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out.", "success")

    return redirect(url_for("home"))


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    if user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))

    if user["role"] == "trainer":
        return redirect(url_for("trainer_dashboard"))

    return redirect(url_for("trainee_dashboard"))


# ============================================================
# TRAINEE DASHBOARD
# ============================================================

@app.route("/trainee/dashboard")
@role_required("trainee")
def trainee_dashboard():

    user = current_user()

    conn = get_db()

    enrolled = conn.execute("""
        SELECT COUNT(*) AS c
        FROM enrollments
        WHERE trainee_id=?
    """, (user["id"],)).fetchone()["c"]

    attempts = conn.execute("""
        SELECT COUNT(*) AS c
        FROM attempts
        WHERE trainee_id=?
    """, (user["id"],)).fetchone()["c"]

    avg_score = conn.execute("""
        SELECT AVG(
            CASE
            WHEN total > 0
            THEN score * 100.0 / total
            ELSE 0
            END
        ) AS avg
        FROM attempts
        WHERE trainee_id=?
    """, (user["id"],)).fetchone()["avg"]

    certificates = conn.execute("""
        SELECT certificates
        FROM trainee_profiles
        WHERE user_id=?
    """, (user["id"],)).fetchone()

    recent_courses = conn.execute("""
        SELECT
            courses.*,
            users.name AS trainer_name
        FROM enrollments
        JOIN courses
            ON courses.id = enrollments.course_id
        JOIN users
            ON users.id = courses.trainer_id
        WHERE enrollments.trainee_id=?
        ORDER BY enrollments.id DESC
        LIMIT 5
    """, (user["id"],)).fetchall()

    conn.close()

    avg_score = round(avg_score or 0, 1)

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Welcome, {{ user["name"] }}</h1>

<p>Your personalized learning dashboard.</p>

</div>

<a class="btn btn-primary"
href="{{ url_for('courses') }}">
Explore Courses
</a>

</div>


<div class="stats-grid">

<div class="stat-card">

<div class="stat-icon">🎓</div>

<div class="stat-number">{{ enrolled }}</div>

<div class="stat-label">Enrolled Courses</div>

</div>


<div class="stat-card">

<div class="stat-icon">📝</div>

<div class="stat-number">{{ attempts }}</div>

<div class="stat-label">Assessments Attempted</div>

</div>


<div class="stat-card">

<div class="stat-icon">📈</div>

<div class="stat-number">{{ avg_score }}%</div>

<div class="stat-label">Average Score</div>

</div>


<div class="stat-card">

<div class="stat-icon">🏆</div>

<div class="stat-number">
{{ 1 if certificates and certificates["certificates"] else 0 }}
</div>

<div class="stat-label">Certificate Profiles</div>

</div>

</div>


<div class="grid-2">

<div class="card">

<h3>My Learning</h3>

{% if recent_courses %}

{% for course in recent_courses %}

<div class="resource">

<div>

<strong>{{ course["title"] }}</strong>

<div class="small">
Trainer: {{ course["trainer_name"] }}
</div>

</div>

<a class="btn btn-light"
href="{{ url_for('course_detail', course_id=course['id']) }}">
Open
</a>

</div>

{% endfor %}

{% else %}

<div class="empty">
You haven't enrolled in any courses yet.
</div>

{% endif %}

</div>


<div class="card">

<h3>Learning Progress</h3>

<p class="small">
Average assessment performance
</p>

<div class="score">
{{ avg_score }}%
</div>

<div class="progress">

<div class="progress-bar"
style="width:{{ avg_score }}%">
</div>

</div>

<p class="small" style="margin-top:15px">

Complete more assessments to improve your
performance profile.

</p>

</div>

</div>


</div>

</div>

"""

    return render_page(
        "Trainee Dashboard",
        body,
        user=user,
        enrolled=enrolled,
        attempts=attempts,
        avg_score=avg_score,
        certificates=certificates,
        recent_courses=recent_courses
    )


# ============================================================
# TRAINEE PROFILE
# ============================================================

@app.route("/trainee/profile", methods=["GET", "POST"])
@role_required("trainee")
def trainee_profile():

    user = current_user()

    conn = get_db()

    if request.method == "POST":

        conn.execute("""
            UPDATE trainee_profiles
            SET qualifications=?,
                experience=?,
                interests=?,
                skills=?,
                certificates=?
            WHERE user_id=?
        """, (
            request.form.get("qualifications", ""),
            request.form.get("experience", ""),
            request.form.get("interests", ""),
            request.form.get("skills", ""),
            request.form.get("certificates", ""),
            user["id"]
        ))

        conn.commit()

        flash(
            "Professional profile updated successfully.",
            "success"
        )

    profile = conn.execute("""
        SELECT *
        FROM trainee_profiles
        WHERE user_id=?
    """, (user["id"],)).fetchone()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Professional Profile</h1>

<p>Build your competency and professional identity.</p>

</div>

</div>


<div class="profile-grid">

<div class="profile-side">

<div class="avatar">

{{ user["name"][0]|upper }}

</div>

<h2>{{ user["name"] }}</h2>

<p>{{ user["email"] }}</p>

<span class="badge">
TRAINEE
</span>

</div>


<div class="card">

<form method="POST">

<div class="grid-2">

<div class="form-group">

<label>Qualifications</label>

<textarea
class="form-control"
name="qualifications"
placeholder="B.Tech, MBA, MSc, etc.">{{ profile["qualifications"] }}</textarea>

</div>


<div class="form-group">

<label>Work Experience</label>

<textarea
class="form-control"
name="experience"
placeholder="Describe your experience">{{ profile["experience"] }}</textarea>

</div>


<div class="form-group">

<label>Interests</label>

<textarea
class="form-control"
name="interests"
placeholder="Your professional interests">{{ profile["interests"] }}</textarea>

</div>


<div class="form-group">

<label>Skills</label>

<textarea
class="form-control"
name="skills"
placeholder="Python, Communication, Leadership...">{{ profile["skills"] }}</textarea>

</div>

</div>


<div class="form-group">

<label>Certificates</label>

<textarea
class="form-control"
name="certificates"
placeholder="Certifications and achievements">{{ profile["certificates"] }}</textarea>

</div>


<button class="btn btn-primary">
Save Professional Profile
</button>

</form>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Trainee Profile",
        body,
        user=user,
        profile=profile
    )


# ============================================================
# COURSES
# ============================================================

@app.route("/courses")
@role_required("trainee")
def courses():

    search = request.args.get("search", "").strip()

    conn = get_db()

    if search:

        course_list = conn.execute("""
            SELECT
                courses.*,
                users.name AS trainer_name
            FROM courses
            JOIN users
                ON users.id = courses.trainer_id
            WHERE
                courses.title LIKE ?
                OR courses.category LIKE ?
                OR courses.description LIKE ?
            ORDER BY courses.id DESC
        """, (
            f"%{search}%",
            f"%{search}%",
            f"%{search}%"
        )).fetchall()

    else:

        course_list = conn.execute("""
            SELECT
                courses.*,
                users.name AS trainer_name
            FROM courses
            JOIN users
                ON users.id = courses.trainer_id
            ORDER BY courses.id DESC
        """).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Learning Catalog</h1>

<p>Discover courses and develop your competencies.</p>

</div>

</div>


<div class="card">

<form method="GET"
style="display:flex;gap:10px">

<input
class="form-control"
name="search"
value="{{ search }}"
placeholder="Search courses, categories or topics">

<button class="btn btn-primary">
Search
</button>

</form>

</div>


<div class="grid-3">

{% for course in course_list %}

<div class="course-card">

<div class="course-top">

<span class="badge"
style="background:rgba(255,255,255,.18);color:white">

{{ course["category"] or "Professional Development" }}

</span>

<h3>
{{ course["title"] }}
</h3>

</div>

<div class="course-body">

<p>
{{ course["description"][:130] }}
{% if course["description"]|length > 130 %}...{% endif %}
</p>

<div class="course-meta">

<span class="badge">
👨‍🏫 {{ course["trainer_name"] }}
</span>

<span class="badge">
⏱ {{ course["duration"] or "Self paced" }}
</span>

</div>

<a class="btn btn-primary"
href="{{ url_for('course_detail', course_id=course['id']) }}">
View Course
</a>

</div>

</div>

{% else %}

<div class="card empty"
style="grid-column:1/-1">

No courses found.

</div>

{% endfor %}

</div>

</div>

</div>

"""

    return render_page(
        "Courses",
        body,
        course_list=course_list,
        search=search
    )


# ============================================================
# COURSE DETAIL
# ============================================================

@app.route("/course/<int:course_id>")
@login_required
def course_detail(course_id):

    user = current_user()

    conn = get_db()

    course = conn.execute("""
        SELECT
            courses.*,
            users.name AS trainer_name
        FROM courses
        JOIN users
            ON users.id = courses.trainer_id
        WHERE courses.id=?
    """, (course_id,)).fetchone()

    if not course:

        conn.close()

        flash("Course not found.", "danger")

        return redirect(url_for("courses"))

    resources = conn.execute("""
        SELECT *
        FROM resources
        WHERE course_id=?
        ORDER BY id DESC
    """, (course_id,)).fetchall()

    question_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM questions
        WHERE course_id=?
    """, (course_id,)).fetchone()["c"]

    enrolled = False

    if user["role"] == "trainee":

        enrolled = bool(conn.execute("""
            SELECT id
            FROM enrollments
            WHERE trainee_id=?
            AND course_id=?
        """, (
            user["id"],
            course_id
        )).fetchone())

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="card">

<div style="
background:linear-gradient(135deg,#2563eb,#7c3aed);
color:white;
padding:30px;
border-radius:15px;
">

<span class="badge"
style="background:rgba(255,255,255,.2);color:white">

{{ course["category"] or "Professional Development" }}

</span>

<h1>{{ course["title"] }}</h1>

<p style="color:#e0e7ff">

{{ course["description"] }}

</p>

</div>


<div style="padding-top:25px">

<div class="course-meta">

<span class="badge">
👨‍🏫 {{ course["trainer_name"] }}
</span>

<span class="badge">
⏱ {{ course["duration"] or "Self paced" }}
</span>

<span class="badge">
📝 {{ question_count }} Questions
</span>

</div>


{% if user["role"] == "trainee" and not enrolled %}

<a class="btn btn-primary"
href="{{ url_for('enroll', course_id=course['id']) }}">

Enroll in Course

</a>

{% elif user["role"] == "trainee" %}

<span class="badge badge-success">
✓ You are enrolled
</span>

<a class="btn btn-primary"
href="{{ url_for('assessment', course_id=course['id']) }}"
style="margin-left:10px">

Take Assessment

</a>

{% endif %}

</div>

</div>


<div class="grid-2">

<div class="card">

<h2>Learning Resources</h2>

{% if resources %}

{% for resource in resources %}

<div class="resource">

<div>

<strong>{{ resource["title"] }}</strong>

<div class="small">
{{ resource["resource_type"] or "Learning Resource" }}
</div>

</div>

<a class="btn btn-light"
href="{{ url_for('download_resource', filename=resource['filename']) }}">

Open

</a>

</div>

{% endfor %}

{% else %}

<div class="empty">
No learning resources uploaded yet.
</div>

{% endif %}

</div>


{% if user["role"] == "trainee" and enrolled %}

<div class="card">

<h2>Course Feedback</h2>

<form method="POST"
action="{{ url_for('submit_feedback', course_id=course_id) }}">

<div class="form-group">

<label>Rating</label>

<select class="form-control"
name="rating"
required>

<option value="">Select rating</option>

<option value="5">★★★★★ Excellent</option>

<option value="4">★★★★ Very Good</option>

<option value="3">★★★ Good</option>

<option value="2">★★ Needs Improvement</option>

<option value="1">★ Poor</option>

</select>

</div>

<div class="form-group">

<label>Your Feedback</label>

<textarea
class="form-control"
name="comment"
placeholder="Share your experience..."></textarea>

</div>

<button class="btn btn-primary">
Submit Feedback
</button>

</form>

</div>

{% endif %}

</div>

</div>

</div>

"""

    return render_page(
        "Course Details",
        body,
        course=course,
        resources=resources,
        question_count=question_count,
        enrolled=enrolled,
        user=user,
        course_id=course_id
    )


# ============================================================
# ENROLL
# ============================================================

@app.route("/enroll/<int:course_id>")
@role_required("trainee")
def enroll(course_id):

    user = current_user()

    conn = get_db()

    try:

        conn.execute("""
            INSERT INTO enrollments
            (trainee_id, course_id)
            VALUES (?, ?)
        """, (
            user["id"],
            course_id
        ))

        conn.commit()

        flash(
            "Successfully enrolled in the course.",
            "success"
        )

    except sqlite3.IntegrityError:

        flash(
            "You are already enrolled in this course.",
            "warning"
        )

    conn.close()

    return redirect(
        url_for(
            "course_detail",
            course_id=course_id
        )
    )


# ============================================================
# FEEDBACK
# ============================================================

@app.route("/feedback/<int:course_id>", methods=["POST"])
@role_required("trainee")
def submit_feedback(course_id):

    user = current_user()

    rating = int(request.form["rating"])
    comment = request.form.get("comment", "")

    if rating < 1 or rating > 5:

        flash("Invalid rating.", "danger")

        return redirect(
            url_for(
                "course_detail",
                course_id=course_id
            )
        )

    conn = get_db()

    conn.execute("""
        INSERT INTO feedback
        (trainee_id, course_id, rating, comment)
        VALUES (?, ?, ?, ?)
    """, (
        user["id"],
        course_id,
        rating,
        comment
    ))

    conn.commit()
    conn.close()

    flash(
        "Thank you. Your feedback has been submitted.",
        "success"
    )

    return redirect(
        url_for(
            "course_detail",
            course_id=course_id
        )
    )


# ============================================================
# ASSESSMENT
# ============================================================

@app.route("/assessment/<int:course_id>", methods=["GET", "POST"])
@role_required("trainee")
def assessment(course_id):

    user = current_user()

    conn = get_db()

    enrollment = conn.execute("""
        SELECT id
        FROM enrollments
        WHERE trainee_id=?
        AND course_id=?
    """, (
        user["id"],
        course_id
    )).fetchone()

    if not enrollment:

        conn.close()

        flash(
            "Please enroll in the course first.",
            "warning"
        )

        return redirect(
            url_for(
                "course_detail",
                course_id=course_id
            )
        )

    questions = conn.execute("""
        SELECT *
        FROM questions
        WHERE course_id=?
        ORDER BY id
    """, (course_id,)).fetchall()

    course = conn.execute("""
        SELECT *
        FROM courses
        WHERE id=?
    """, (course_id,)).fetchone()

    conn.close()

    if request.method == "POST":

        score = 0

        for question in questions:

            answer = request.form.get(
                f"question_{question['id']}"
            )

            if answer == question["correct_answer"]:
                score += 1

        conn = get_db()

        conn.execute("""
            INSERT INTO attempts
            (trainee_id, course_id, score, total)
            VALUES (?, ?, ?, ?)
        """, (
            user["id"],
            course_id,
            score,
            len(questions)
        ))

        conn.commit()
        conn.close()

        percentage = (
            round(score * 100 / len(questions), 1)
            if questions else 0
        )

        body = """

<div class="dashboard">

<div class="container">

<div class="card"
style="text-align:center;padding:55px">

<div class="feature-icon"
style="margin:0 auto 20px">

✓

</div>

<h1>Assessment Completed</h1>

<p>Your responses have been evaluated.</p>

<div class="score">
{{ score }}/{{ total }}
</div>

<h2>{{ percentage }}%</h2>

{% if percentage >= 70 %}

<span class="badge badge-success">
Excellent Performance
</span>

{% else %}

<span class="badge badge-warning">
Keep Learning & Try Again
</span>

{% endif %}

<br><br>

<a class="btn btn-primary"
href="{{ url_for('course_detail', course_id=course_id) }}">

Back to Course

</a>

</div>

</div>

</div>

"""

        return render_page(
            "Assessment Result",
            body,
            score=score,
            total=len(questions),
            percentage=percentage,
            course_id=course_id
        )

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>{{ course["title"] }} Assessment</h1>

<p>
Test your understanding of the course.
</p>

</div>

<span class="badge">
{{ questions|length }} Questions
</span>

</div>


{% if questions %}

<form method="POST">

{% for q in questions %}

<div class="question">

<h4>
{{ loop.index }}. {{ q["question"] }}
</h4>


<label class="option">

<input
type="radio"
name="question_{{ q['id'] }}"
value="A"
required>

A. {{ q["option_a"] }}

</label>


<label class="option">

<input
type="radio"
name="question_{{ q['id'] }}"
value="B">

B. {{ q["option_b"] }}

</label>


<label class="option">

<input
type="radio"
name="question_{{ q['id'] }}"
value="C">

C. {{ q["option_c"] }}

</label>


<label class="option">

<input
type="radio"
name="question_{{ q['id'] }}"
value="D">

D. {{ q["option_d"] }}

</label>

</div>

{% endfor %}

<button class="btn btn-primary">
Submit Assessment
</button>

</form>

{% else %}

<div class="card empty">

No assessment has been created for this course yet.

</div>

{% endif %}

</div>

</div>

"""

    return render_page(
        "Assessment",
        body,
        questions=questions,
        course=course,
        course_id=course_id
    )


# ============================================================
# TRAINER DASHBOARD
# ============================================================

@app.route("/trainer/dashboard")
@role_required("trainer")
def trainer_dashboard():

    user = current_user()

    conn = get_db()

    courses_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM courses
        WHERE trainer_id=?
    """, (user["id"],)).fetchone()["c"]

    resources_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM resources
        WHERE trainer_id=?
    """, (user["id"],)).fetchone()["c"]

    questions_count = conn.execute("""
        SELECT COUNT(*) AS c
        FROM questions
        WHERE trainer_id=?
    """, (user["id"],)).fetchone()["c"]

    participants = conn.execute("""
        SELECT COUNT(DISTINCT trainee_id) AS c
        FROM enrollments e
        JOIN courses c
            ON c.id=e.course_id
        WHERE c.trainer_id=?
    """, (user["id"],)).fetchone()["c"]

    my_courses = conn.execute("""
        SELECT *
        FROM courses
        WHERE trainer_id=?
        ORDER BY id DESC
        LIMIT 6
    """, (user["id"],)).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Trainer Dashboard</h1>

<p>
Manage your courses, resources and trainee performance.
</p>

</div>

<a class="btn btn-primary"
href="{{ url_for('create_course') }}">
+ Create Course
</a>

</div>


<div class="stats-grid">

<div class="stat-card">

<div class="stat-icon">🎓</div>

<div class="stat-number">{{ courses_count }}</div>

<div class="stat-label">My Courses</div>

</div>


<div class="stat-card">

<div class="stat-icon">📚</div>

<div class="stat-number">{{ resources_count }}</div>

<div class="stat-label">Learning Resources</div>

</div>


<div class="stat-card">

<div class="stat-icon">📝</div>

<div class="stat-number">{{ questions_count }}</div>

<div class="stat-label">Assessment Questions</div>

</div>


<div class="stat-card">

<div class="stat-icon">👥</div>

<div class="stat-number">{{ participants }}</div>

<div class="stat-label">Unique Participants</div>

</div>

</div>


<div class="card">

<div style="
display:flex;
justify-content:space-between;
align-items:center;
margin-bottom:20px;
">

<h2>My Courses</h2>

<a class="btn btn-light"
href="{{ url_for('trainer_courses') }}">
Manage All
</a>

</div>


<div class="grid-3">

{% for course in my_courses %}

<div class="course-card">

<div class="course-top">

<span class="badge"
style="background:rgba(255,255,255,.18);color:white">

{{ course["category"] }}

</span>

<h3>{{ course["title"] }}</h3>

</div>

<div class="course-body">

<p>
{{ course["description"][:100] }}
</p>

<a class="btn btn-primary"
href="{{ url_for('trainer_course', course_id=course['id']) }}">

Manage

</a>

</div>

</div>

{% else %}

<div class="empty"
style="grid-column:1/-1">

You haven't created a course yet.

</div>

{% endfor %}

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Trainer Dashboard",
        body,
        courses_count=courses_count,
        resources_count=resources_count,
        questions_count=questions_count,
        participants=participants,
        my_courses=my_courses
    )


# ============================================================
# TRAINER PROFILE
# ============================================================

@app.route("/trainer/profile", methods=["GET", "POST"])
@role_required("trainer")
def trainer_profile():

    user = current_user()

    conn = get_db()

    if request.method == "POST":

        conn.execute("""
            UPDATE trainer_profiles
            SET specialization=?,
                experience=?,
                skills=?,
                bio=?
            WHERE user_id=?
        """, (
            request.form.get("specialization", ""),
            request.form.get("experience", ""),
            request.form.get("skills", ""),
            request.form.get("bio", ""),
            user["id"]
        ))

        conn.commit()

        flash(
            "Trainer profile updated.",
            "success"
        )

    profile = conn.execute("""
        SELECT *
        FROM trainer_profiles
        WHERE user_id=?
    """, (user["id"],)).fetchone()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="profile-grid">

<div class="profile-side">

<div class="avatar">
{{ user["name"][0]|upper }}
</div>

<h2>{{ user["name"] }}</h2>

<p>{{ user["email"] }}</p>

<span class="badge">
TRAINER
</span>

</div>


<div class="card">

<h2>Trainer Profile</h2>

<form method="POST">

<div class="form-group">

<label>Specialization</label>

<input
class="form-control"
name="specialization"
value="{{ profile['specialization'] }}"
placeholder="e.g. Data Science, Leadership">

</div>


<div class="form-group">

<label>Professional Experience</label>

<textarea
class="form-control"
name="experience">{{ profile["experience"] }}</textarea>

</div>


<div class="form-group">

<label>Skills & Expertise</label>

<textarea
class="form-control"
name="skills">{{ profile["skills"] }}</textarea>

</div>


<div class="form-group">

<label>Professional Bio</label>

<textarea
class="form-control"
name="bio">{{ profile["bio"] }}</textarea>

</div>


<button class="btn btn-primary">
Save Trainer Profile
</button>

</form>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Trainer Profile",
        body,
        user=user,
        profile=profile
    )


# ============================================================
# TRAINER COURSES
# ============================================================

@app.route("/trainer/courses")
@role_required("trainer")
def trainer_courses():

    user = current_user()

    conn = get_db()

    courses_list = conn.execute("""
        SELECT
            courses.*,
            COUNT(DISTINCT enrollments.trainee_id) AS participants
        FROM courses
        LEFT JOIN enrollments
            ON enrollments.course_id = courses.id
        WHERE courses.trainer_id=?
        GROUP BY courses.id
        ORDER BY courses.id DESC
    """, (user["id"],)).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>My Courses</h1>

<p>Manage your training programs.</p>

</div>

<a class="btn btn-primary"
href="{{ url_for('create_course') }}">

+ Create Course

</a>

</div>


<div class="card">

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Course</th>
<th>Category</th>
<th>Duration</th>
<th>Participants</th>
<th>Action</th>

</tr>

</thead>

<tbody>

{% for course in courses_list %}

<tr>

<td>
<strong>{{ course["title"] }}</strong>
</td>

<td>
<span class="badge">
{{ course["category"] }}
</span>
</td>

<td>
{{ course["duration"] }}
</td>

<td>
{{ course["participants"] }}
</td>

<td>

<a class="btn btn-light"
href="{{ url_for('trainer_course', course_id=course['id']) }}">

Manage

</a>

</td>

</tr>

{% else %}

<tr>

<td colspan="5"
style="text-align:center">

No courses created.

</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "My Courses",
        body,
        courses_list=courses_list
    )


# ============================================================
# CREATE COURSE
# ============================================================

@app.route("/trainer/create-course", methods=["GET", "POST"])
@role_required("trainer")
def create_course():

    user = current_user()

    if request.method == "POST":

        title = request.form["title"]
        description = request.form["description"]
        category = request.form["category"]
        duration = request.form["duration"]

        conn = get_db()

        conn.execute("""
            INSERT INTO courses
            (title, description, category, trainer_id, duration)
            VALUES (?, ?, ?, ?, ?)
        """, (
            title,
            description,
            category,
            user["id"],
            duration
        ))

        conn.commit()
        conn.close()

        flash(
            "Course created successfully.",
            "success"
        )

        return redirect(url_for("trainer_courses"))

    body = """

<div class="dashboard">

<div class="container">

<div class="card">

<h1>Create New Course</h1>

<p>
Design a structured learning experience for trainees.
</p>

<form method="POST">

<div class="grid-2">

<div class="form-group">

<label>Course Title</label>

<input
class="form-control"
name="title"
required
placeholder="e.g. Introduction to Data Analytics">

</div>


<div class="form-group">

<label>Category</label>

<input
class="form-control"
name="category"
required
placeholder="e.g. Technology">

</div>


<div class="form-group">

<label>Duration</label>

<input
class="form-control"
name="duration"
placeholder="e.g. 6 Weeks">

</div>

</div>


<div class="form-group">

<label>Course Description</label>

<textarea
class="form-control"
name="description"
required
placeholder="Describe the course objectives, learning outcomes and topics..."></textarea>

</div>


<button class="btn btn-primary">
Create Course
</button>

<a class="btn btn-light"
href="{{ url_for('trainer_courses') }}">
Cancel
</a>

</form>

</div>

</div>

</div>

"""

    return render_page(
        "Create Course",
        body
    )


# ============================================================
# TRAINER COURSE MANAGEMENT
# ============================================================

@app.route("/trainer/course/<int:course_id>")
@role_required("trainer")
def trainer_course(course_id):

    user = current_user()

    conn = get_db()

    course = conn.execute("""
        SELECT *
        FROM courses
        WHERE id=?
        AND trainer_id=?
    """, (
        course_id,
        user["id"]
    )).fetchone()

    if not course:

        conn.close()

        flash("Course not found.", "danger")

        return redirect(url_for("trainer_courses"))

    resources = conn.execute("""
        SELECT *
        FROM resources
        WHERE course_id=?
        ORDER BY id DESC
    """, (course_id,)).fetchall()

    questions = conn.execute("""
        SELECT *
        FROM questions
        WHERE course_id=?
        ORDER BY id DESC
    """, (course_id,)).fetchall()

    participants = conn.execute("""
        SELECT
            users.name,
            users.email,
            enrollments.enrolled_at
        FROM enrollments
        JOIN users
            ON users.id=enrollments.trainee_id
        WHERE enrollments.course_id=?
        ORDER BY enrollments.id DESC
    """, (course_id,)).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>{{ course["title"] }}</h1>

<p>Course management workspace.</p>

</div>

</div>


<div class="grid-2">

<div class="card">

<h2>Course Overview</h2>

<p>{{ course["description"] }}</p>

<div class="course-meta">

<span class="badge">
{{ course["category"] }}
</span>

<span class="badge">
{{ course["duration"] }}
</span>

</div>

</div>


<div class="card">

<h2>Upload Learning Resource</h2>

<form method="POST"
action="{{ url_for('upload_resource', course_id=course_id) }}"
enctype="multipart/form-data">

<div class="form-group">

<label>Resource Title</label>

<input
class="form-control"
name="title"
required
placeholder="Lecture 1 - Introduction">

</div>


<div class="form-group">

<label>Resource Type</label>

<select
class="form-control"
name="resource_type">

<option>Recorded Lecture</option>

<option>Presentation</option>

<option>Study Material</option>

<option>Reference Document</option>

</select>

</div>


<div class="form-group">

<label>Select File</label>

<input
class="form-control"
type="file"
name="file"
required>

</div>


<button class="btn btn-primary">
Upload Resource
</button>

</form>

</div>

</div>


<div class="card">

<h2>Learning Library</h2>

{% for resource in resources %}

<div class="resource">

<div>

<strong>{{ resource["title"] }}</strong>

<div class="small">
{{ resource["resource_type"] }}
</div>

</div>

<a class="btn btn-light"
href="{{ url_for('download_resource', filename=resource['filename']) }}">

View

</a>

</div>

{% else %}

<div class="empty">
No resources uploaded.
</div>

{% endfor %}

</div>


<div class="card">

<div style="
display:flex;
justify-content:space-between;
align-items:center;
">

<h2>Assessment Questions</h2>

<a class="btn btn-primary"
href="{{ url_for('create_question', course_id=course_id) }}">

+ Add Question

</a>

</div>


<div class="table-wrap">

<table>

<thead>

<tr>

<th>Question</th>
<th>Deadline</th>

</tr>

</thead>

<tbody>

{% for q in questions %}

<tr>

<td>{{ q["question"] }}</td>

<td>{{ q["deadline"] or "No deadline" }}</td>

</tr>

{% else %}

<tr>

<td colspan="2">
No questions created yet.
</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>


<div class="card">

<h2>Trainee Participation</h2>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Name</th>
<th>Email</th>
<th>Enrolled</th>

</tr>

</thead>

<tbody>

{% for participant in participants %}

<tr>

<td>{{ participant["name"] }}</td>

<td>{{ participant["email"] }}</td>

<td>{{ participant["enrolled_at"] }}</td>

</tr>

{% else %}

<tr>

<td colspan="3">
No trainees enrolled yet.
</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Manage Course",
        body,
        course=course,
        resources=resources,
        questions=questions,
        participants=participants,
        course_id=course_id
    )


# ============================================================
# UPLOAD RESOURCE
# ============================================================

@app.route("/trainer/course/<int:course_id>/upload",
           methods=["POST"])
@role_required("trainer")
def upload_resource(course_id):

    user = current_user()

    title = request.form.get("title", "").strip()
    resource_type = request.form.get(
        "resource_type",
        "Learning Resource"
    )

    file = request.files.get("file")

    if not title or not file or not file.filename:

        flash(
            "Please provide a title and file.",
            "danger"
        )

        return redirect(
            url_for(
                "trainer_course",
                course_id=course_id
            )
        )

    if not allowed_file(file.filename):

        flash(
            "This file type is not supported.",
            "danger"
        )

        return redirect(
            url_for(
                "trainer_course",
                course_id=course_id
            )
        )

    unique_name = (
        str(uuid.uuid4()) + "_" +
        secure_filename(file.filename)
    )

    file.save(
        os.path.join(
            app.config["UPLOAD_FOLDER"],
            unique_name
        )
    )

    conn = get_db()

    course = conn.execute("""
        SELECT id
        FROM courses
        WHERE id=?
        AND trainer_id=?
    """, (
        course_id,
        user["id"]
    )).fetchone()

    if not course:

        conn.close()

        flash("Course not found.", "danger")

        return redirect(url_for("trainer_courses"))

    conn.execute("""
        INSERT INTO resources
        (course_id, trainer_id, title,
         filename, resource_type)
        VALUES (?, ?, ?, ?, ?)
    """, (
        course_id,
        user["id"],
        title,
        unique_name,
        resource_type
    ))

    conn.commit()
    conn.close()

    flash(
        "Learning resource uploaded successfully.",
        "success"
    )

    return redirect(
        url_for(
            "trainer_course",
            course_id=course_id
        )
    )


# ============================================================
# DOWNLOAD RESOURCE
# ============================================================

@app.route("/uploads/<filename>")
@login_required
def download_resource(filename):

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# ============================================================
# CREATE QUESTION
# ============================================================

@app.route("/trainer/course/<int:course_id>/question",
           methods=["GET", "POST"])
@role_required("trainer")
def create_question(course_id):

    user = current_user()

    conn = get_db()

    course = conn.execute("""
        SELECT *
        FROM courses
        WHERE id=?
        AND trainer_id=?
    """, (
        course_id,
        user["id"]
    )).fetchone()

    conn.close()

    if not course:

        flash("Course not found.", "danger")

        return redirect(url_for("trainer_courses"))

    if request.method == "POST":

        conn = get_db()

        conn.execute("""
            INSERT INTO questions
            (
                course_id,
                trainer_id,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_answer,
                deadline
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            course_id,
            user["id"],
            request.form["question"],
            request.form["option_a"],
            request.form["option_b"],
            request.form["option_c"],
            request.form["option_d"],
            request.form["correct_answer"],
            request.form.get("deadline", "")
        ))

        conn.commit()
        conn.close()

        flash(
            "Assessment question added.",
            "success"
        )

        return redirect(
            url_for(
                "trainer_course",
                course_id=course_id
            )
        )

    body = """

<div class="dashboard">

<div class="container">

<div class="card">

<h1>Create Assessment Question</h1>

<p>
Course: <strong>{{ course["title"] }}</strong>
</p>

<form method="POST">

<div class="form-group">

<label>Question</label>

<textarea
class="form-control"
name="question"
required></textarea>

</div>


<div class="grid-2">

<div class="form-group">

<label>Option A</label>

<input
class="form-control"
name="option_a"
required>

</div>


<div class="form-group">

<label>Option B</label>

<input
class="form-control"
name="option_b"
required>

</div>


<div class="form-group">

<label>Option C</label>

<input
class="form-control"
name="option_c"
required>

</div>


<div class="form-group">

<label>Option D</label>

<input
class="form-control"
name="option_d"
required>

</div>

</div>


<div class="grid-2">

<div class="form-group">

<label>Correct Answer</label>

<select
class="form-control"
name="correct_answer"
required>

<option value="A">Option A</option>
<option value="B">Option B</option>
<option value="C">Option C</option>
<option value="D">Option D</option>

</select>

</div>


<div class="form-group">

<label>Deadline</label>

<input
class="form-control"
type="datetime-local"
name="deadline">

</div>

</div>


<button class="btn btn-primary">
Add Question
</button>

</form>

</div>

</div>

</div>

"""

    return render_page(
        "Create Question",
        body,
        course=course
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():

    conn = get_db()

    users = conn.execute("""
        SELECT COUNT(*) AS c
        FROM users
    """).fetchone()["c"]

    trainees = conn.execute("""
        SELECT COUNT(*) AS c
        FROM users
        WHERE role='trainee'
    """).fetchone()["c"]

    trainers = conn.execute("""
        SELECT COUNT(*) AS c
        FROM users
        WHERE role='trainer'
    """).fetchone()["c"]

    courses = conn.execute("""
        SELECT COUNT(*) AS c
        FROM courses
    """).fetchone()["c"]

    enrollments = conn.execute("""
        SELECT COUNT(*) AS c
        FROM enrollments
    """).fetchone()["c"]

    attempts = conn.execute("""
        SELECT COUNT(*) AS c
        FROM attempts
    """).fetchone()["c"]

    pending = conn.execute("""
        SELECT COUNT(*) AS c
        FROM users
        WHERE approved=0
    """).fetchone()["c"]

    recent_users = conn.execute("""
        SELECT *
        FROM users
        ORDER BY id DESC
        LIMIT 8
    """).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Admin Control Center</h1>

<p>
Monitor and manage the entire CAPACITY CONNECT ecosystem.
</p>

</div>

<a class="btn btn-primary"
href="{{ url_for('admin_announcements') }}">

Publish Announcement

</a>

</div>


<div class="stats-grid">

<div class="stat-card">

<div class="stat-icon">👥</div>

<div class="stat-number">{{ users }}</div>

<div class="stat-label">Total Users</div>

</div>


<div class="stat-card">

<div class="stat-icon">🎓</div>

<div class="stat-number">{{ trainees }}</div>

<div class="stat-label">Trainees</div>

</div>


<div class="stat-card">

<div class="stat-icon">👨‍🏫</div>

<div class="stat-number">{{ trainers }}</div>

<div class="stat-label">Trainers</div>

</div>


<div class="stat-card">

<div class="stat-icon">📚</div>

<div class="stat-number">{{ courses }}</div>

<div class="stat-label">Courses</div>

</div>


<div class="stat-card">

<div class="stat-icon">🧾</div>

<div class="stat-number">{{ enrollments }}</div>

<div class="stat-label">Enrollments</div>

</div>


<div class="stat-card">

<div class="stat-icon">📝</div>

<div class="stat-number">{{ attempts }}</div>

<div class="stat-label">Assessment Attempts</div>

</div>


<div class="stat-card">

<div class="stat-icon">⏳</div>

<div class="stat-number">{{ pending }}</div>

<div class="stat-label">Pending Approvals</div>

</div>

</div>


<div class="grid-2">

<div class="card">

<h2>System Overview</h2>

<p>
CAPACITY CONNECT provides a centralized platform for
organizational training, competency development,
assessments and knowledge sharing.
</p>

<div class="course-meta">

<span class="badge badge-success">
Secure Authentication
</span>

<span class="badge">
Role Based Access
</span>

<span class="badge">
Competency Mapping
</span>

<span class="badge">
Digital Assessments
</span>

</div>

</div>


<div class="card">

<h2>Quick Actions</h2>

<div style="display:flex;gap:10px;flex-wrap:wrap">

<a class="btn btn-primary"
href="{{ url_for('admin_users') }}">

Manage Users

</a>

<a class="btn btn-light"
href="{{ url_for('admin_competency') }}">

Competency Mapping

</a>

<a class="btn btn-light"
href="{{ url_for('admin_announcements') }}">

Announcements

</a>

</div>

</div>

</div>


<div class="card">

<h2>Recent Users</h2>

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Name</th>
<th>Email</th>
<th>Role</th>
<th>Status</th>
<th>Joined</th>

</tr>

</thead>

<tbody>

{% for user in recent_users %}

<tr>

<td>{{ user["name"] }}</td>

<td>{{ user["email"] }}</td>

<td>
<span class="badge">
{{ user["role"]|upper }}
</span>
</td>

<td>

{% if user["approved"] %}

<span class="badge badge-success">
Approved
</span>

{% else %}

<span class="badge badge-warning">
Pending
</span>

{% endif %}

</td>

<td>{{ user["created_at"] }}</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Admin Dashboard",
        body,
        users=users,
        trainees=trainees,
        trainers=trainers,
        courses=courses,
        enrollments=enrollments,
        attempts=attempts,
        pending=pending,
        recent_users=recent_users
    )


# ============================================================
# ADMIN USERS
# ============================================================

@app.route("/admin/users")
@role_required("admin")
def admin_users():

    conn = get_db()

    users = conn.execute("""
        SELECT *
        FROM users
        ORDER BY approved ASC, id DESC
    """).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>User Management</h1>

<p>Approve users and manage platform roles.</p>

</div>

</div>


<div class="card">

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Name</th>
<th>Email</th>
<th>Role</th>
<th>Status</th>
<th>Action</th>

</tr>

</thead>

<tbody>

{% for user in users %}

<tr>

<td>
<strong>{{ user["name"] }}</strong>
</td>

<td>{{ user["email"] }}</td>

<td>

<span class="badge">
{{ user["role"]|upper }}
</span>

</td>

<td>

{% if user["approved"] %}

<span class="badge badge-success">
Approved
</span>

{% else %}

<span class="badge badge-warning">
Pending
</span>

{% endif %}

</td>

<td>

{% if not user["approved"] %}

<a class="btn btn-success"
href="{{ url_for('approve_user', user_id=user['id']) }}">

Approve

</a>

{% else %}

<span class="small">
Active
</span>

{% endif %}

</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "User Management",
        body,
        users=users
    )


# ============================================================
# APPROVE USER
# ============================================================

@app.route("/admin/users/<int:user_id>/approve")
@role_required("admin")
def approve_user(user_id):

    conn = get_db()

    conn.execute("""
        UPDATE users
        SET approved=1
        WHERE id=?
    """, (user_id,))

    conn.commit()
    conn.close()

    flash(
        "User approved successfully.",
        "success"
    )

    return redirect(url_for("admin_users"))


# ============================================================
# ADMIN ANNOUNCEMENTS
# ============================================================

@app.route("/admin/announcements", methods=["GET", "POST"])
@role_required("admin")
def admin_announcements():

    conn = get_db()

    if request.method == "POST":

        title = request.form["title"]
        message = request.form["message"]

        conn.execute("""
            INSERT INTO announcements
            (title, message)
            VALUES (?, ?)
        """, (
            title,
            message
        ))

        conn.commit()

        flash(
            "Announcement published successfully.",
            "success"
        )

    announcements = conn.execute("""
        SELECT *
        FROM announcements
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="grid-2">

<div class="card">

<h2>Publish Announcement</h2>

<p class="small">
Share important updates with all platform users.
</p>

<form method="POST">

<div class="form-group">

<label>Announcement Title</label>

<input
class="form-control"
name="title"
required
placeholder="New Learning Program">

</div>


<div class="form-group">

<label>Message</label>

<textarea
class="form-control"
name="message"
required
placeholder="Write your announcement..."></textarea>

</div>


<button class="btn btn-primary">
Publish Announcement
</button>

</form>

</div>


<div class="card">

<h2>Published Announcements</h2>

{% for a in announcements %}

<div class="announcement">

<h3>{{ a["title"] }}</h3>

<p>{{ a["message"] }}</p>

<div class="small"
style="margin-top:10px">

{{ a["created_at"] }}

</div>

</div>

{% else %}

<div class="empty">
No announcements published.
</div>

{% endfor %}

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Announcements",
        body,
        announcements=announcements
    )


# ============================================================
# COMPETENCY MAPPING
# ============================================================

@app.route("/admin/competency")
@role_required("admin")
def admin_competency():

    subject = request.args.get(
        "subject",
        ""
    ).strip()

    conn = get_db()

    trainers = conn.execute("""
        SELECT
            users.id,
            users.name,
            users.email,
            trainer_profiles.specialization,
            trainer_profiles.experience,
            trainer_profiles.skills,
            trainer_profiles.bio
        FROM users
        LEFT JOIN trainer_profiles
            ON trainer_profiles.user_id=users.id
        WHERE users.role='trainer'
        AND users.approved=1
    """).fetchall()

    conn.close()

    results = []

    if subject:

        keywords = [
            word.lower()
            for word in subject.split()
            if len(word) > 2
        ]

        for trainer in trainers:

            text = " ".join([
                trainer["specialization"] or "",
                trainer["experience"] or "",
                trainer["skills"] or "",
                trainer["bio"] or ""
            ]).lower()

            matches = sum(
                1
                for keyword in keywords
                if keyword in text
            )

            score = (
                round(
                    matches / len(keywords) * 100
                )
                if keywords else 0
            )

            results.append({
                "trainer": trainer,
                "score": score
            })

        results.sort(
            key=lambda x: x["score"],
            reverse=True
        )

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Competency Mapping</h1>

<p>
Find trainers whose expertise matches a required subject.
</p>

</div>

</div>


<div class="card">

<form method="GET">

<div class="form-group">

<label>Required Competency / Subject</label>

<input
class="form-control"
name="subject"
value="{{ subject }}"
placeholder="e.g. Python Data Science Leadership">

</div>

<button class="btn btn-primary">
Find Suitable Trainers
</button>

</form>

</div>


{% if subject %}

<h2>
Trainer Matches for "{{ subject }}"
</h2>


{% for item in results %}

<div class="competency">

<div style="
display:flex;
justify-content:space-between;
align-items:center;
gap:20px;
">

<div>

<h3>
{{ item["trainer"]["name"] }}
</h3>

<p class="small">
{{ item["trainer"]["specialization"] or
"No specialization provided" }}
</p>

</div>

<div style="text-align:right">

<div class="score"
style="font-size:25px">

{{ item["score"] }}%

</div>

<div class="small">
Competency Match
</div>

</div>

</div>


<div class="progress"
style="margin-top:15px">

<div class="progress-bar"
style="width:{{ item['score'] }}%">

</div>

</div>


<p class="small"
style="margin-top:12px">

<strong>Skills:</strong>
{{ item["trainer"]["skills"] or "Not provided" }}

</p>

</div>

{% else %}

<div class="card empty">

No suitable trainers found.

</div>

{% endfor %}

{% endif %}

</div>

</div>

"""

    return render_page(
        "Competency Mapping",
        body,
        subject=subject,
        results=results
    )


# ============================================================
# ADMIN PERFORMANCE
# ============================================================

@app.route("/admin/performance")
@role_required("admin")
def admin_performance():

    conn = get_db()

    performance = conn.execute("""
        SELECT
            users.name,
            courses.title,
            attempts.score,
            attempts.total,
            attempts.attempted_at
        FROM attempts
        JOIN users
            ON users.id=attempts.trainee_id
        JOIN courses
            ON courses.id=attempts.course_id
        ORDER BY attempts.id DESC
        LIMIT 100
    """).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Performance Monitoring</h1>

<p>
Monitor assessment results across the organization.
</p>

</div>

</div>


<div class="card">

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Trainee</th>
<th>Course</th>
<th>Score</th>
<th>Percentage</th>
<th>Date</th>

</tr>

</thead>

<tbody>

{% for row in performance %}

<tr>

<td>{{ row["name"] }}</td>

<td>{{ row["title"] }}</td>

<td>
{{ row["score"] }}/{{ row["total"] }}
</td>

<td>

{% if row["total"] %}

{{ ((row["score"] / row["total"]) * 100)|round(1) }}%

{% else %}

0%

{% endif %}

</td>

<td>{{ row["attempted_at"] }}</td>

</tr>

{% else %}

<tr>

<td colspan="5"
style="text-align:center">

No assessment data available.

</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Performance Monitoring",
        body,
        performance=performance
    )


# ============================================================
# ADMIN COURSES
# ============================================================

@app.route("/admin/courses")
@role_required("admin")
def admin_courses():

    conn = get_db()

    courses_list = conn.execute("""
        SELECT
            courses.*,
            users.name AS trainer_name,
            COUNT(DISTINCT enrollments.trainee_id) AS participants
        FROM courses
        JOIN users
            ON users.id=courses.trainer_id
        LEFT JOIN enrollments
            ON enrollments.course_id=courses.id
        GROUP BY courses.id
        ORDER BY courses.id DESC
    """).fetchall()

    conn.close()

    body = """

<div class="dashboard">

<div class="container">

<div class="page-heading">

<div>

<h1>Course Monitoring</h1>

<p>
Monitor courses and participation across the platform.
</p>

</div>

</div>


<div class="card">

<div class="table-wrap">

<table>

<thead>

<tr>

<th>Course</th>
<th>Trainer</th>
<th>Category</th>
<th>Participants</th>

</tr>

</thead>

<tbody>

{% for course in courses_list %}

<tr>

<td>
<strong>{{ course["title"] }}</strong>
</td>

<td>{{ course["trainer_name"] }}</td>

<td>
<span class="badge">
{{ course["category"] }}
</span>
</td>

<td>{{ course["participants"] }}</td>

</tr>

{% else %}

<tr>

<td colspan="4">
No courses available.
</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</div>

</div>

</div>

"""

    return render_page(
        "Course Monitoring",
        body,
        courses_list=courses_list
    )


# ============================================================
# 404
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    body = """

<div class="auth-wrapper">

<div class="card"
style="text-align:center;max-width:600px">

<div class="score">
404
</div>

<h1>Page Not Found</h1>

<p>
The page you are looking for doesn't exist.
</p>

<a class="btn btn-primary"
href="{{ url_for('home') }}">

Return Home

</a>

</div>

</div>

"""

    return render_page(
        "Page Not Found",
        body
    ), 404


# ============================================================
# 413 FILE TOO LARGE
# ============================================================

@app.errorhandler(413)
def file_too_large(error):

    flash(
        "File is too large. Maximum allowed size is 25 MB.",
        "danger"
    )

    return redirect(
        request.referrer or url_for("home")
    )


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    initialize_database()

    print()
    print("=" * 60)
    print("             CAPACITY CONNECT")
    print("     Digital Capacity Building Portal")
    print("=" * 60)
    print()
    print("Local Website:")
    print("http://127.0.0.1:5000")
    print()
    print("Network Website:")
    print("http://YOUR-PC-IP:5000")
    print()
    print("ADMIN LOGIN")
    print("Email    : admin@capacityconnect.com")
    print("Password : Admin@123")
    print()
    print("=" * 60)
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )