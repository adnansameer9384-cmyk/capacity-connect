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
import re
import secrets
import random
from urllib import request as urllib_request
from urllib import error as urllib_error
import json
from html import escape

# ============================================================
# CAPACITY CONNECT
# Professional SIH Prototype
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "capacity-connect-sih-local-secret-key")

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
        expert_language TEXT,
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

    CREATE TABLE IF NOT EXISTS trainer_assessment_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainer_id INTEGER NOT NULL,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        percentage REAL NOT NULL,
        status TEXT NOT NULL,
        expert_language TEXT,
        attempted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trainer_id) REFERENCES users(id) ON DELETE CASCADE
    );

    """)

    # Safe migrations for databases created by older versions.
    trainer_columns = [row[1] for row in cur.execute("PRAGMA table_info(trainer_profiles)").fetchall()]
    if "expert_language" not in trainer_columns:
        cur.execute("ALTER TABLE trainer_profiles ADD COLUMN expert_language TEXT")

    attempt_columns = [row[1] for row in cur.execute("PRAGMA table_info(trainer_assessment_attempts)").fetchall()]
    if "expert_language" not in attempt_columns:
        cur.execute("ALTER TABLE trainer_assessment_attempts ADD COLUMN expert_language TEXT")

    # Create/update administrator from environment variables only.
    # No demo administrator credentials are hard-coded.
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")

    # Remove the old demo administrator account.
    cur.execute(
        "DELETE FROM users WHERE email = ?",
        ("admin@capacityconnect.com",)
    )

    if admin_email and admin_password:
        admin = cur.execute(
            "SELECT id FROM users WHERE email = ?",
            (admin_email,)
        ).fetchone()

        if not admin:
            cur.execute("""
                INSERT INTO users
                (name, email, password, role, approved)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "System Administrator",
                admin_email,
                generate_password_hash(admin_password),
                "admin",
                1
            ))
        else:
            cur.execute("""
                UPDATE users
                SET password=?, role='admin', approved=1
                WHERE email=?
            """, (
                generate_password_hash(admin_password),
                admin_email
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

            if role != "admin" and not user["approved"]:
                if role == "trainer":
                    return redirect(url_for("trainer_assessment"))
                flash("Your account is waiting for administrator approval.", "warning")
                return redirect(url_for("login"))

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
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")

        if role not in ["trainee", "trainer"]:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("register"))

        if not name or not email or not password:
            flash("Please fill all required fields.", "danger")
            return redirect(url_for("register"))

        if not re.fullmatch(r"[A-Za-z0-9._%+-]+@gmail\.com", email):
            flash("Please enter a valid Gmail address ending with @gmail.com.", "danger")
            return redirect(url_for("register"))

        conn = get_db()

        existing = conn.execute(
            "SELECT id FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if existing:
            conn.close()
            flash("An account with this email already exists.", "danger")
            return redirect(url_for("login"))

        cur = conn.execute(
            """
            INSERT INTO users
            (name, email, password, role, approved)
            VALUES (?, ?, ?, ?, 0)
            """,
            (name, email, generate_password_hash(password), role)
        )

        user_id = cur.lastrowid

        if role == "trainee":
            conn.execute(
                """
                INSERT INTO trainee_profiles
                (user_id, qualifications, experience, interests, skills, certificates)
                VALUES (?, '', '', '', '', '')
                """,
                (user_id,)
            )
        else:
            conn.execute(
                """
                INSERT INTO trainer_profiles
                (user_id, specialization, experience, skills, bio, expert_language)
                VALUES (?, '', '', '', '', NULL)
                """,
                (user_id,)
            )

        conn.commit()
        conn.close()

        flash(
            "Registration successful! Your account is waiting for administrator approval.",
            "success"
        )
        return redirect(url_for("login"))

    body = """
    <div class="auth-wrapper">
        <div class="auth-card">
            <h2>Create your account</h2>
            <p>Join CAPACITY CONNECT and create your account.</p>

            <form method="POST">
                <div class="form-group">
                    <label>Full Name</label>
                    <input class="form-control" name="name" required
                           placeholder="Enter your full name">
                </div>

                <div class="form-group">
                    <label>Gmail Address</label>
                    <input class="form-control" type="email" name="email" required
                           placeholder="you@gmail.com"
                           pattern="[A-Za-z0-9._%+-]+@gmail[.]com">
                </div>

                <div class="form-group">
                    <label>Password</label>
                    <input class="form-control" type="password" name="password" required
                           placeholder="Create a secure password" minlength="6">
                </div>

                <div class="form-group">
                    <label>Account Type</label>
                    <select class="form-control" name="role" required>
                        <option value="trainee">Trainee</option>
                        <option value="trainer">Trainer</option>
                    </select>
                </div>

                <button class="btn btn-primary" style="width:100%" type="submit">
                    Create Account
                </button>
            </form>

            <p style="text-align:center;margin-top:20px">
                Already have an account?
                <a href="{{ url_for('login') }}"
                   style="color:#2563eb;font-weight:700">Login</a>
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

        if not user["approved"] and user["role"] != "trainer":
            flash(
                "Your account is waiting for administrator approval.",
                "warning"
            )
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user["id"]
        session["name"] = user["name"]
        session["role"] = user["role"]

        # Trainers must select their expert programming language before
        # entering the trainer assessment.
        if user["role"] == "trainer" and not user["approved"]:
            return redirect(url_for("trainer_language"))

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
# TRAINER MCQ ASSESSMENT
# ============================================================


# ============================================================
# TRAINER PROGRAMMING LANGUAGE SELECTION
# ============================================================

SUPPORTED_TRAINER_LANGUAGES = [
    "C",
    "C++",
    "Java",
    "Python",
    "JavaScript",
    "HTML/CSS"
]


LANGUAGE_QUESTION_BANK = {
    'C': [
        ('What is the behavior of `int x=1; printf("%d %d", x++, ++x);` in C?', 'The behavior is undefined', ['It always prints 1 3', 'It always prints 1 2', 'It is implementation-defined']),
        ('If `int a[5];` is declared, what is the type of the expression `a` in most expression contexts?', 'Pointer to the first element, after array-to-pointer conversion', ['An array of five integers', 'Pointer to the whole array', 'Integer address value']),
        ('What does `sizeof(char)` return in C?', '1', ['The number of bits in a char', '2', 'Implementation-dependent bytes']),
        ('Which statement about `malloc` is correct?', 'It returns suitably aligned uninitialized storage or NULL on failure', ['It initializes allocated bytes to zero', 'It returns a typed pointer', 'It automatically frees memory at scope exit']),
        ('What does `calloc(n, size)` additionally guarantee compared with `malloc`?', 'The allocated bytes are initialized to zero', ['The pointer cannot be NULL', 'The memory is automatically resized', 'The memory is allocated on the stack']),
        ('What is the purpose of `free(p)` when `p` was returned by `malloc`?', 'Releases the dynamically allocated storage', ['Sets p to NULL automatically', 'Deletes the pointer variable', 'Copies the allocation to the stack']),
        ('What does the `static` keyword on a local variable primarily change?', 'Its storage duration becomes the entire program execution', ['Its value becomes compile-time constant', 'Its scope becomes global', 'It makes access thread-safe']),
        ('What does `static` on a file-scope function usually provide?', 'Internal linkage', ['Dynamic dispatch', 'External linkage', 'Automatic storage duration']),
        ('What is the main effect of `const int *p`?', 'The pointed-to int cannot be modified through p', ['p cannot point elsewhere', 'Both p and the int are constant', 'The pointer is volatile']),
        ('What does `int *const p` mean?', 'p cannot point to another int, but the int may be modified', ['The int cannot be modified', 'Both p and the int are constant', 'p is a pointer to a constant pointer']),
        ('Which operator has higher precedence in `*p++`?', 'Postfix ++', ['Unary *', 'Both have equal precedence', 'Assignment']),
        ('What does `p + 1` mean when p is an `int *`?', 'It points to the next int object', ['It increases the address by one byte', 'It points to the next pointer object', 'It converts p to an integer']),
        ('Which expression correctly allocates space for 10 ints?', '`malloc(10 * sizeof *p)` when p is int*', ['`malloc(10)` always', '`malloc(sizeof(10))`', '`malloc(10 * sizeof(int*))`']),
        ('What is a dangling pointer?', 'A pointer referring to an object whose lifetime has ended', ['A NULL pointer', 'A pointer to static storage', 'A pointer that has not been initialized']),
        ('What is a memory leak?', 'Allocated storage becomes unreachable without being freed', ['Reading a NULL pointer', 'Writing within an allocated object', 'Freeing memory twice']),
        ('What is the result of `5 & 3` using C bitwise AND?', '1', ['7', '6', '2']),
        ('What is the result of `5 ^ 3` using C bitwise XOR?', '6', ['1', '7', '2']),
        ('What is the result of `5 << 1` for a suitable signed positive int?', '10', ['6', '2', '20']),
        ('Which header declares `memcpy`?', 'string.h', ['stdlib.h', 'stdio.h', 'memory.h is required by the C standard']),
        ('Which statement about `memcpy` is correct?', 'The source and destination objects must not overlap', ['It safely handles any overlap', 'It always appends a null terminator', 'It allocates destination storage']),
        ('Which function should be used for overlapping memory regions?', 'memmove', ['memcpy', 'memset', 'memcmp']),
        ('What does `strcmp(a,b)` return when strings are equal?', '0', ['1', '-1', 'The string length']),
        ('Why is `gets` unsafe and removed from modern C standards?', 'It cannot limit the number of characters read', ['It cannot read spaces', 'It only works with integers', 'It always causes a memory leak']),
        ('What does `volatile` primarily tell the compiler?', 'The object may change for reasons outside ordinary program flow', ['The object is automatically atomic', 'The object is stored only in RAM', 'The object cannot be cached by the CPU']),
        ('Does `volatile` by itself make a shared variable thread-safe?', 'No', ['Yes, always', 'Only for pointers', 'Only on x86']),
        ('What does the `restrict` qualifier communicate?', 'A pointer is intended to be the exclusive access path to an object for that block', ['The pointer cannot be NULL', 'The pointer is constant', 'The pointed object is read-only']),
        ('What is the type of a string literal such as `"abc"` in C?', 'An array of char', ['A pointer to char', 'An array of const char', 'A struct containing characters']),
        ('What happens if a program attempts to modify a string literal through a pointer?', 'The behavior is undefined', ['The literal is copied automatically', 'Only the first character changes', 'A compile-time conversion occurs']),
        ('What does `extern int x;` usually declare?', 'An object defined elsewhere with external linkage', ['A new local integer', 'A constant integer', 'A thread-local integer']),
        ('Which storage duration applies to an ordinary local variable without static?', 'Automatic', ['Static', 'Allocated', 'Thread']),
        ('What does a function pointer store?', 'The address of a function', ['The return value of a function', 'The address of the stack frame only', 'A function name as text']),
        ('Which declaration declares a pointer to a function taking an int and returning int?', '`int (*fp)(int);`', ['`int *fp(int);`', '`int fp(*int);`', '`(*int) fp(int);`']),
        ('What is the purpose of a `typedef`?', 'Creates an alias for a type name', ['Allocates a new type at runtime', 'Creates a variable', 'Defines a macro with arguments']),
        ('Which statement about a C `union` is correct?', 'Its members share the same storage', ['All members have separate storage', 'Its size is always the sum of members', 'Only the first member can be declared']),
        ('What does structure padding affect?', 'The size and layout of a struct', ['The values of all members', 'The function call convention only', 'The lexical scope of fields']),
        ('Which operator accesses a struct member through a pointer?', '->', ['.', '::', '&']),
        ('What does `.` do with a struct object?', 'Accesses a member of the object', ['Dereferences a pointer', 'Accesses a global symbol', 'Performs floating-point multiplication']),
        ('Which preprocessor directive creates a macro?', '#define', ['#macro', '#const', '#include']),
        ('What does `#include <file.h>` primarily do?', 'Includes the header contents during preprocessing', ['Links a library at runtime', 'Executes the header', 'Allocates header memory']),
        ('What is the purpose of include guards?', 'Prevent repeated inclusion of the same header contents', ['Improve CPU cache locality', 'Encrypt declarations', 'Force dynamic linking']),
        ('What does the C conditional operator `cond ? a : b` return?', 'a if cond is nonzero, otherwise b', ['Always a', 'Always b', 'The condition itself']),
        ('Which statement about integer division is correct for positive operands?', 'The fractional part is discarded', ['It always rounds up', 'It always returns double', 'It causes a floating-point exception']),
        ('What happens when an unsigned integer arithmetic operation exceeds its range?', 'It wraps modulo one more than the maximum value', ['The behavior is always undefined', 'It automatically becomes signed', 'A runtime exception is guaranteed']),
        ('Which conversion is performed by integer promotion?', 'Certain smaller integer types are promoted to int or unsigned int', ['All integers become long long', 'All integers become float', 'Only unsigned types become pointers']),
        ('What does `sizeof` evaluate to for a variable-length array at runtime?', 'Its actual size is determined at runtime', ['Always zero', 'Always a compile-time constant', 'The pointer size']),
        ('Can a C function return an array directly?', 'No, but it can return a pointer to an array or first element', ['Yes, arrays are first-class return values', 'Only if the array is static', 'Only for char arrays']),
        ('What is the main danger of returning the address of a local automatic variable?', 'The object lifetime ends when the function returns', ['The pointer becomes NULL automatically', 'The variable becomes global', 'The stack is copied to the heap']),
        ('What does `fgets` provide that makes it safer than `gets`?', 'It accepts a maximum input size', ['It removes all newline characters automatically', 'It reads only integers', 'It never stores a terminator']),
        ('What does `EOF` represent in standard C input functions?', 'A negative int value used to indicate end-of-file or input failure', ['A character stored in every file', 'The null byte', 'A successful read']),
        ('Which statement about `printf` format mismatches is correct?', 'Passing an argument with an incompatible expected type can cause undefined behavior', ['The compiler always converts every argument safely', 'Only strings are affected', 'The result is always implementation-defined']),
    ],
    'C++': [
        ('What is RAII in C++ primarily used for?', 'Binding resource lifetime to object lifetime', ['Running code only at compile time', 'Replacing templates', 'Managing only heap memory']),
        ('Which smart pointer uniquely owns an object?', 'std::unique_ptr', ['std::shared_ptr', 'std::weak_ptr', 'std::observer_ptr is standard']),
        ('Why is `std::weak_ptr` useful with shared ownership?', 'It can observe a shared object without contributing to its reference count', ['It deletes objects immediately', 'It transfers unique ownership', 'It prevents all aliasing']),
        ('What happens when the last `std::shared_ptr` owning an object is destroyed?', 'The managed object is destroyed', ['Only the pointer object is destroyed', 'The object becomes a unique_ptr', 'The object is copied to the stack']),
        ('What does `std::move(x)` actually do?', 'It casts x to an rvalue reference enabling move operations', ['It physically moves bytes immediately', 'It destroys x', 'It guarantees a move constructor call']),
        ('After moving from a standard library object, what is generally guaranteed?', 'It remains valid but its value is generally unspecified', ['It becomes invalid and cannot be used', 'It is always empty', 'It is always identical to its old value']),
        ('What is object slicing?', 'Copying a derived object into a base object by value, losing the derived part', ['Deleting through a base pointer', 'Converting a pointer to void*', 'Removing virtual functions']),
        ('Why should a polymorphic base class often have a virtual destructor?', 'So deleting a derived object through a base pointer is well-defined', ['To make constructors virtual', 'To reduce object size', 'To enable templates']),
        ('What does a pure virtual function make a class?', 'Abstract if the class has at least one pure virtual function', ['Final automatically', 'A namespace', 'A template specialization']),
        ('What is the purpose of `override`?', 'It asks the compiler to verify that a virtual function overrides a base member', ['It makes a function virtual', 'It prevents overriding', 'It makes a function static']),
        ('What does `final` on a virtual function mean?', 'Further overriding is prohibited', ['The function is inlined', 'The function is pure virtual', 'The function becomes static']),
        ('Which container provides contiguous storage and amortized constant-time push_back?', 'std::vector', ['std::list', 'std::map', 'std::set']),
        ('What commonly invalidates iterators when a vector reallocates?', 'All iterators and references to its elements', ['Only the first iterator', 'Only end()', 'None']),
        ('What does `emplace_back` generally allow?', 'Constructing an element directly in the container', ['Sorting the container', 'Deleting the last element', 'Moving the container to disk']),
        ('What is a lambda capture `[&]`?', 'Capture used local variables by reference', ['Capture all variables by value', 'Capture only globals', 'Capture the return value']),
        ('What does `[=]` in a lambda generally mean?', 'Capture odr-used automatic variables by value', ['Capture all variables by reference', 'Capture only this', 'Capture globals by pointer']),
        ('What is a dangling reference?', 'A reference referring to an object whose lifetime has ended', ['A reference initialized to zero', 'A const reference', 'A reference to a temporary that is always safe']),
        ('What is perfect forwarding intended to preserve?', 'The value category and cv/ref qualifiers of an argument', ['Only the argument type name', 'The memory address', 'The object identity across processes']),
        ('What is the purpose of `std::forward<T>(x)`?', 'Conditionally casts x to preserve forwarding category', ['Moves every argument unconditionally', 'Copies x', 'Allocates x on the heap']),
        ('What is template specialization?', 'Providing a customized implementation for particular template arguments', ['Instantiating every possible type', 'Replacing inheritance', 'Creating a namespace alias']),
        ('What does `constexpr` primarily permit?', 'An expression or function to participate in constant evaluation when requirements are met', ['Forcing runtime evaluation', 'Making data thread-safe', 'Making a variable mutable']),
        ('What does `consteval` mean for a function?', 'It must be evaluated at compile time when called', ['It is always evaluated at runtime', 'It is deprecated', 'It is equivalent to const']),
        ('What does `noexcept` communicate?', 'The function is not expected to throw exceptions', ['The function cannot fail', 'The compiler guarantees no UB', 'The function is always constexpr']),
        ('What is the main purpose of move constructors?', 'Efficiently transfer resources from a source object', ['Prevent copying of integers', 'Allocate stack memory', 'Perform polymorphic dispatch']),
        ('What is copy elision?', 'Omitting certain copy/move operations when permitted by the language', ['Deleting copy constructors', 'Converting copies to references', 'Copying only metadata']),
        ('Which cast is intended for checked downcasts in a polymorphic hierarchy?', 'dynamic_cast', ['static_cast', 'reinterpret_cast', 'const_cast']),
        ('Which cast can remove constness?', 'const_cast', ['dynamic_cast', 'static_cast only', 'reinterpret_cast only']),
        ('Which cast is generally the most low-level and potentially dangerous?', 'reinterpret_cast', ['dynamic_cast', 'const_cast', 'implicit_cast']),
        ('What does `std::optional<T>` represent?', 'A value that may or may not be present', ['A thread-safe variable', 'A polymorphic base class', 'A container with unlimited values']),
        ('What does `std::variant` provide?', 'A type-safe discriminated union', ['A dynamic array only', 'A reference-counted pointer', 'A compile-time namespace']),
        ('What does `std::visit` commonly do?', 'Invokes a visitor based on the active alternative of a variant', ['Iterates a vector', 'Visits base classes', 'Calls destructors']),
        ('Why is `std::enable_shared_from_this` used?', 'To safely create a shared_ptr to an existing object already owned by shared_ptr', ['To make unique_ptr copyable', 'To prevent destruction', 'To create weak references only']),
        ('What is a deadlock?', 'Two or more threads wait indefinitely for resources held by each other', ['A data race only', 'A compiler error', 'A failed allocation']),
        ('Does `std::mutex` itself prevent all data races?', 'No; the program must use the same synchronization discipline for shared data', ['Yes automatically', 'Only for atomic variables', 'Only on Linux']),
        ('What does `std::atomic` provide?', 'Atomic operations and synchronization primitives for supported types', ['A replacement for every mutex', 'Automatic memory allocation', 'Guaranteed lock-free behavior for all types']),
        ('What is a data race in the C++ memory model?', 'Conflicting unsynchronized accesses to the same memory location involving at least one write', ['Any two reads', 'Any use of threads', 'A race between compilers']),
        ('What is the purpose of `std::scoped_lock`?', 'Conveniently lock one or more mutexes with RAII', ['Create a scope at runtime', 'Disable exceptions', 'Allocate a mutex']),
        ('What is function template overload resolution affected by?', 'Template argument deduction and viable overload ranking', ['Only return type', 'Only source-file order', 'Only function names']),
        ('Can functions be overloaded solely by return type?', 'No', ['Yes always', 'Only for templates', 'Only inside classes']),
        ('What is name hiding in derived classes?', 'A derived declaration can hide base overloads with the same name', ['Deleting the base function', 'Virtual dispatch failure', 'Removing a namespace']),
        ('What does `using Base::f;` in a derived class commonly accomplish?', 'Brings base overloads of f into the derived scope', ['Calls f immediately', 'Makes f private', 'Deletes derived f']),
        ('What is the Rule of Five concerned with?', 'Special member functions related to resource-owning types', ['Five inheritance levels', 'Five template parameters', 'Five namespaces']),
        ('What is the Rule of Zero?', 'Prefer types whose resource management needs no custom special member functions', ['Always define five constructors', 'Avoid RAII', 'Use zero classes']),
        ('What does `std::string_view` provide?', 'A non-owning view of character data', ['An owning immutable string', 'A reference-counted string', 'A mutable C buffer']),
        ('What is a key lifetime risk with `std::string_view`?', 'It can outlive the referenced character storage', ['It always allocates', 'It cannot refer to strings', 'It cannot be copied']),
        ('What does `std::move` on a const object often result in?', 'A const rvalue, which may prevent use of typical non-const move operations', ['Guaranteed efficient move', 'Destruction of the object', 'Conversion to void']),
        ('What is SFINAE?', 'Substitution failure in certain template contexts removes a candidate instead of causing a hard error', ['A runtime exception mechanism', 'A memory allocator', 'A virtual dispatch rule']),
        ('What are C++20 concepts primarily for?', 'Constraining templates with readable compile-time requirements', ['Replacing all classes', 'Runtime type checking', 'Garbage collection']),
        ('What does `std::ranges` primarily provide?', 'Composable range-based algorithms and views', ['A garbage collector', 'A thread scheduler', 'A GUI framework']),
        ('What does `std::exchange` do?', 'Replaces an object value and returns its previous value', ['Only swaps two containers', 'Moves an object without returning anything', 'Creates a shared_ptr']),
    ],
    'Java': [
        ('Why is `String` immutable in Java significant?', 'Its value cannot change after construction, enabling safe sharing and stable hashing', ['It can never be garbage-collected', 'It is stored only on the stack', 'It is always interned']),
        ('What is the contract between `equals` and `hashCode`?', 'Equal objects must return the same hash code', ['Unequal objects must have different hashes', 'hashCode must be unique', 'equals may ignore object state']),
        ('What happens if a class overrides equals but not hashCode?', 'Hash-based collections can behave incorrectly for logically equal objects', ['The code always fails compilation', 'The JVM disables hashing', 'equals becomes final']),
        ('What is method overloading?', 'Same method name with different parameter lists', ['Replacing a superclass method with same signature', 'Changing only return type', 'Changing only access modifier']),
        ('What is method overriding?', 'A subclass provides a compatible implementation of an inherited instance method', ['Two methods differ only by return type', 'A static method changes behavior dynamically', 'A constructor replaces a method']),
        ('Can a static method be overridden polymorphically?', 'No, static methods are hidden rather than overridden', ['Yes always', 'Only if final', 'Only in interfaces']),
        ('What does `final` on a class prevent?', 'Subclassing', ['Object creation', 'Method calls', 'Garbage collection']),
        ('What does `final` on a reference variable prevent?', 'Reassigning the reference', ['Mutating the referenced object', 'Garbage collection', 'Calling methods']),
        ('What is type erasure in Java generics?', 'Generic type information is largely removed or translated at runtime for ordinary generic types', ['Generics are compiled into machine code only', 'Generic classes cannot run', 'All type checks disappear at compile time']),
        ('Why can you not normally write `new T()` inside a generic class?', 'The runtime type information for T is not available in that form', ['Constructors are forbidden in generics', 'T is always primitive', 'new works only with interfaces']),
        ('Which collection preserves insertion order and allows duplicates?', 'List', ['Set', 'Map', 'Queue only']),
        ('Which collection maps keys to values?', 'Map', ['Set', 'List', 'Deque']),
        ('What is the usual complexity of HashMap average-case lookup?', 'O(1) expected, subject to hashing and implementation details', ['O(log n) guaranteed', 'O(n log n) guaranteed', 'O(n^2) guaranteed']),
        ('What does `ConcurrentHashMap` aim to provide?', 'Thread-safe concurrent access with scalable synchronization characteristics', ['A sorted map only', 'A map that forbids updates', 'A persistent database']),
        ('What is a checked exception?', 'An exception the compiler requires code to catch or declare, subject to the language rules', ['Any RuntimeException', 'An exception caught automatically', 'An exception thrown only by the JVM']),
        ('Which class is the superclass of most runtime exceptions?', 'RuntimeException', ['Error', 'Throwable only', 'Exception only']),
        ('What does try-with-resources rely on?', 'AutoCloseable/Closeable resources and automatic closing', ['A garbage collector callback', 'finalize only', 'A background thread']),
        ('What happens if both try-with-resources body and close throw exceptions?', 'The close exception can be suppressed while the primary exception is propagated', ['Both are always lost', 'The JVM crashes', 'Only the close exception can be thrown']),
        ('What does `volatile` provide in Java?', 'Visibility and ordering guarantees for the variable, but not compound-operation atomicity', ['Atomic increment for every type', 'Mutual exclusion', 'Transaction rollback']),
        ('Why is `count++` not made atomic merely by declaring count volatile?', 'It is a read-modify-write operation requiring multiple steps', ['volatile disables reads', '++ is not legal on volatile', 'The JVM converts it to a lock']),
        ('What does `synchronized` on an instance method lock?', 'The monitor associated with that instance', ['The class loader', 'Every object in the JVM', 'Only the method code']),
        ('What does `synchronized` on a static method lock?', 'The Class object for that class', ['The current thread', 'The package', 'The heap']),
        ('What is the purpose of `ExecutorService`?', 'Manage and execute asynchronous tasks using a thread-pool style abstraction', ['Compile source code', 'Manage database schemas', 'Create JVMs']),
        ('What does `Future.get()` generally do?', 'Waits for and returns the result of a submitted computation, possibly throwing exceptions', ['Starts a task twice', 'Cancels every task', 'Creates a new thread automatically']),
        ('What is a Java Stream?', 'A pipeline abstraction for processing data from a source', ['A collection that stores elements permanently', 'A network socket only', 'A thread']),
        ('Are Java streams themselves collections?', 'No', ['Yes always', 'Only parallel streams', 'Only IntStream']),
        ('What does an intermediate stream operation usually do?', 'Builds another lazy stage of the pipeline', ['Immediately consumes the stream', 'Closes the JVM', 'Creates a thread']),
        ('Which is a terminal stream operation?', 'collect', ['map', 'filter', 'sorted']),
        ('What is `Optional<T>` intended to represent?', 'A value that may be present or absent', ['A thread-safe mutable box', 'A replacement for every exception', 'A collection of exactly two values']),
        ('What does a record primarily provide?', 'A concise syntax for data-carrier classes with generated members', ['A mutable database table', 'A thread primitive', 'A GUI component']),
        ('What is a sealed class used for?', 'Restricting which classes may extend or implement a type', ['Preventing object creation', 'Making all fields mutable', 'Enabling reflection only']),
        ('What is class initialization order broadly based on?', 'Superclass initialization followed by class initialization, with static initialization before instance construction', ['Random order', 'Instance initialization before static initialization always', 'Subclass static code before superclass static code']),
        ('When are static initializers of a class executed?', 'When the class is initialized by the JVM', ['Every time an instance method runs', 'Only at compilation', 'After every object is destroyed']),
        ('What is the difference between `==` and `equals` for objects?', '== compares references; equals can compare logical state if overridden', ['Both always compare content', '== invokes equals', 'equals compares memory addresses only']),
        ('What does String.intern() relate to?', 'The JVM string pool and canonical string representations', ['File system storage', 'Thread-local strings', 'Character encoding conversion only']),
        ('Why can excessive string concatenation in a loop be inefficient?', 'Repeated immutable String creation can cause unnecessary allocations', ['Strings are mutable', 'The compiler forbids concatenation', 'Loops cannot concatenate strings']),
        ('What does garbage collection reclaim?', 'Objects that are no longer reachable according to the JVM reachability model', ['Every object after one method call', 'All stack frames', 'All static fields']),
        ('Can Java code explicitly force garbage collection?', 'It can request GC with System.gc(), but execution is not guaranteed', ['Yes, System.gc() guarantees immediate collection', 'No request is possible', 'Only Runtime.free() guarantees it']),
        ('What is a daemon thread?', 'A thread that does not by itself prevent JVM shutdown', ['A thread with higher priority', 'A thread immune to interruption', 'A thread that owns every lock']),
        ('What does `CompletableFuture` provide?', 'Composable asynchronous computations', ['A database transaction manager', 'A replacement for arrays', 'A GUI event loop only']),
        ('What is a functional interface?', 'An interface with exactly one abstract method', ['An interface with no methods', 'An interface with only static methods', 'An interface that cannot be implemented']),
        ('What does a lambda expression implement in Java?', 'A compatible functional interface target type', ['Any class automatically', 'A primitive type', 'A package']),
        ('What is method reference syntax used for?', 'A concise reference to an existing method or constructor', ['Calling methods without objects only', 'Reflection without types', 'Replacing inheritance']),
        ('What does `super` in a constructor commonly do?', 'Invokes a superclass constructor', ['Creates a new superclass', 'Calls an interface default method only', 'Makes the object immutable']),
        ('Can constructors be inherited?', 'No', ['Yes always', 'Only public constructors', 'Only record constructors']),
        ('What is covariance in Java arrays?', 'A subtype array can be assigned to a supertype array reference', ['Generic types are covariant by default', 'Primitive arrays become objects', 'Arrays cannot be assigned']),
        ('What runtime exception can result from storing the wrong subtype in a covariant array?', 'ArrayStoreException', ['ClassNotFoundException', 'IOException', 'IllegalAccessError']),
        ('Why are generics generally invariant in Java?', '`List<Dog>` is not a subtype of `List<Animal>` because allowing it could violate type safety', ['The JVM cannot allocate lists', 'Generics are primitive only', 'Inheritance is disabled for generics']),
        ('What does `? extends T` usually mean for a generic collection?', 'It can produce values as T but is not generally safe for adding arbitrary T values', ['It accepts any supertype only', 'It always allows adding T', 'It means exactly T']),
        ('What does `? super T` usually allow?', 'Adding T values safely while reads are available only as Object without further knowledge', ['Reading as T safely in all cases', 'Only exact T collections', 'No insertion at all']),
    ],
    'Python': [
        ('Why is a mutable default argument such as `def f(x=[]):` risky?', 'The same list object is reused across calls', ['Python recreates it on every call', 'Lists cannot be defaults', 'It causes a syntax error']),
        ('What is late binding in Python closures?', 'A closure looks up a free variable when the inner function executes', ['Variables are copied at function definition automatically', 'Closures cannot access outer variables', 'Only globals are late-bound']),
        ('How can a loop-created lambda capture the current loop value reliably?', 'Bind it as a default argument such as `lambda x=i: x`', ['Use `global i`', 'Use `del i`', 'Use `yield i` only']),
        ('What does `is` test in Python?', 'Object identity', ['Value equality only', 'Hash equality', 'Type equality only']),
        ('What does `==` normally test?', 'Equality according to the objects’ comparison protocol', ['Identity only', 'Memory address only', 'Hash codes only']),
        ('What is the key difference between list and tuple?', 'Lists are mutable; tuples are immutable', ['Tuples are always faster for every operation', 'Lists cannot contain objects', 'Tuples cannot be nested']),
        ('What does a generator function return when called?', 'A generator iterator object', ['A list containing all results', 'A coroutine always', 'A string']),
        ('What happens when `next()` is called on an exhausted generator?', 'StopIteration is raised', ['None is always returned', 'The generator restarts', 'ValueError is raised']),
        ('What is a generator expression useful for?', 'Lazy iteration without creating the whole result collection immediately', ['Creating classes', 'Compiling bytecode', 'Making values immutable']),
        ('What does `yield` do inside a generator?', 'Produces a value and suspends execution until resumed', ['Returns permanently like return', 'Raises StopIteration immediately', 'Creates a new thread']),
        ('What is the purpose of a decorator?', 'Wrap or transform a function/class while preserving a reusable transformation pattern', ['Only document a function', 'Allocate memory', 'Create a module']),
        ('Why is `functools.wraps` commonly used in decorators?', 'It copies useful metadata from the wrapped function to the wrapper', ['It makes functions asynchronous', 'It caches every call', 'It disables closures']),
        ('What does a context manager support through `with`?', 'Setup and cleanup around a block, commonly via __enter__ and __exit__', ['Only exception handling', 'Only file reading', 'Thread scheduling']),
        ('What does `__enter__` return to the `as` target in a with statement?', 'Whatever object __enter__ returns', ['Always self', 'Always None', 'The exception object']),
        ('What does `__exit__` returning True generally do?', 'Suppresses the exception from propagating out of the with block', ['Raises the exception again', 'Restarts the block', 'Closes Python']),
        ('What is MRO in Python?', 'Method Resolution Order used to search classes for attributes/methods', ['Memory Register Output', 'Module Runtime Object', 'Method Return Optimization']),
        ('What algorithm is used for Python class MRO in modern Python?', 'C3 linearization', ['Depth-first search without constraints', 'Breadth-first search only', 'Topological sorting of modules']),
        ('What does `super()` primarily provide?', 'A proxy for accessing the next class in the MRO', ['Direct access to object memory', 'A parent-only method call ignoring MRO', 'A new superclass']),
        ('What is a descriptor?', 'An object defining methods such as __get__, __set__, or __delete__ that control attribute access', ['A type annotation only', 'A module loader', 'A garbage collector hook']),
        ('Why is a property useful?', 'It exposes method-backed attribute access while keeping a property-like interface', ['It creates a global variable', 'It disables methods', 'It forces immutability']),
        ('What is the purpose of `__slots__`?', 'Restrict instance attributes and can reduce per-instance memory overhead', ['It creates database slots', 'It makes every attribute static', 'It disables inheritance always']),
        ('What is the relationship between `__eq__` and `__hash__`?', 'Changing equality semantics can require corresponding hash semantics for hashable objects', ['They are unrelated', '__hash__ always ignores __eq__', 'Defining __eq__ always makes objects hashable']),
        ('What commonly happens when a class defines `__eq__` but no `__hash__`?', 'Instances are generally made unhashable', ['A hash is automatically derived from id forever', 'Equality is disabled', 'The class becomes immutable']),
        ('What is shallow copying?', 'Copying the outer container while nested referenced objects remain shared', ['Recursively copying every object', 'Copying only immutable values', 'Copying class definitions']),
        ('What does `copy.deepcopy` attempt to do?', 'Recursively copy objects while respecting its copy protocol and memoization', ['Only copy the outer object', 'Serialize to JSON', 'Clone the Python interpreter']),
        ('What does the GIL in standard CPython historically affect?', 'Execution of Python bytecode by multiple threads at the same time', ['All I/O concurrency', 'All multiprocessing', 'All Python implementations equally']),
        ('Does the GIL prevent all concurrency in Python?', 'No; I/O concurrency and multiprocessing can still provide concurrency, and implementations differ', ['Yes, no concurrency is possible', 'Only async code can run', 'Threads cannot exist']),
        ('What does `async def` define?', 'A coroutine function', ['A generator only', 'A thread function', 'A normal synchronous function with no special behavior']),
        ('What does `await` do in an async function?', 'Suspends the coroutine until an awaitable completes, allowing the event loop to run other work', ['Creates a new OS process', 'Blocks every thread in Python', 'Returns immediately with the final value']),
        ('What is a Python `asyncio` event loop?', 'A scheduler that drives asynchronous tasks and callbacks', ['A CPU thread pool only', 'A database connection', 'A compiler phase']),
        ('What does dictionary insertion order mean in modern Python?', 'Dictionaries preserve insertion order as a language guarantee', ['Keys are always sorted', 'Order is random', 'Only integer keys preserve order']),
        ('What is the average-case lookup complexity of a Python dict?', 'O(1) expected', ['O(log n) guaranteed', 'O(n log n) expected', 'O(n^2) expected']),
        ('What happens if you modify a dictionary while directly iterating over its keys?', 'It can raise RuntimeError because the dictionary size changed', ['It always silently works', 'The dictionary becomes sorted', 'The loop restarts']),
        ('What is tuple unpacking?', 'Assigning iterable elements to multiple targets', ['Converting tuples to strings', 'Sorting tuple elements', 'Copying a tuple recursively']),
        ('What does extended unpacking such as `a, *mid, b = seq` do?', 'Assigns the middle remaining elements to a list named mid', ['Creates a tuple named mid', 'Requires exactly three elements', 'Discards the middle values']),
        ('What is a list comprehension primarily?', 'A concise expression for constructing a list from an iterable with optional filtering', ['A lazy generator by definition', 'A class definition', 'A dictionary-only syntax']),
        ('Which comprehension is lazy by default?', 'Generator expression', ['List comprehension', 'Set comprehension', 'Dict comprehension']),
        ('What is the walrus operator `:=` used for?', 'Assignment expressions inside expressions', ['Type casting', 'Pattern matching only', 'Bitwise assignment']),
        ('What does structural pattern matching with `match` support?', 'Matching values and structures against patterns', ['Only regular expressions', 'Only strings', 'Only class inheritance']),
        ('What is the purpose of a dataclass?', 'Reduce boilerplate for data-oriented classes by generating methods such as __init__', ['Create database tables automatically', 'Make every field private', 'Replace dictionaries']),
        ('What does `@dataclass(frozen=True)` generally provide?', 'Dataclass instances whose fields cannot normally be assigned after initialization', ['Deep immutability of all referenced objects', 'Automatic thread safety', 'Mandatory slots in every Python version']),
        ('What is an exception hierarchy used for?', 'Organizing exceptions so specific or general handlers can catch appropriate types', ['Controlling variable scope', 'Scheduling tasks', 'Managing imports']),
        ('Why is `except Exception:` different from bare `except:`?', 'Bare except also catches BaseException subclasses such as KeyboardInterrupt', ['They are identical', 'Exception catches SystemExit automatically', 'Bare except catches only ValueError']),
        ('What does `raise` without an expression do inside an exception handler?', 'Re-raises the currently handled exception', ['Raises None', 'Raises the last syntax error', 'Stops Python without an exception']),
        ('What does `finally` generally guarantee?', 'Its block is attempted whether or not an exception occurs, subject to control-flow termination cases', ['It runs only on success', 'It runs only on exceptions', 'It never runs after return']),
        ('What is `__name__ == "__main__"` commonly used for?', 'Detecting when a module is executed as the main script rather than imported', ['Checking whether a class is private', 'Testing the Python version', 'Detecting a virtual environment']),
        ('What is a virtual environment mainly for?', 'Isolating Python package installations and interpreter environments', ['Encrypting source code', 'Running Python without an interpreter', 'Compiling C extensions only']),
        ('What is a metaclass?', 'A class whose instances are classes', ['A module-level variable', 'A decorator that must be callable', 'A parent object for every instance only']),
        ('What does `type(obj)` normally return?', 'The object’s class/type object', ['The object’s memory address', 'A string representation', 'Its MRO list']),
        ('What does `__getattribute__` control?', 'Attribute access on an object', ['Only method calls', 'Object destruction only', 'Import resolution']),
    ],
    'JavaScript': [
        ('What is the Temporal Dead Zone associated with?', 'let, const, and class bindings before their initialization', ['var after declaration', 'Function declarations only', 'Object properties']),
        ('What happens when a `let` variable is accessed before initialization?', 'A ReferenceError is thrown', ['undefined is returned', 'null is returned', 'The variable becomes global']),
        ('What is hoisting of `var` commonly observed as?', 'The declaration is processed so the binding exists with value undefined before assignment', ['The value is copied to the top', 'The variable becomes constant', 'The declaration is ignored']),
        ('How does `===` differ from `==`?', 'Strict equality avoids most implicit type coercion', ['They are identical', '=== always compares object contents', '== never coerces types']),
        ('What does `Object.is(NaN, NaN)` return?', 'true', ['false', 'undefined', 'throws TypeError']),
        ('What is special about `Object.is(0, -0)`?', 'It returns false', ['It returns true', 'It throws', 'It converts both to NaN']),
        ('What does an arrow function do with `this`?', 'It lexically captures this from its surrounding scope', ['It creates its own dynamic this', 'It always binds this to window', 'It sets this to null']),
        ('What does a closure retain?', 'Access to variables from its lexical environment', ['A copy of the entire program', 'Only global variables', 'The browser DOM only']),
        ('What is the prototype chain used for?', 'Property and method lookup through linked prototype objects', ['Garbage collection only', 'Module loading only', 'Promise scheduling']),
        ('What does `class` syntax in JavaScript primarily build on?', 'The prototype-based object model', ['Classical C++ vtables', 'Java bytecode', 'WebAssembly only']),
        ('What is the difference between `null` and `undefined`?', 'They are distinct values with different meanings and behavior', ['They are strictly identical', 'null is an undeclared variable', 'undefined is always an object']),
        ('What does `typeof null` return due to a historical language quirk?', '"object"', ['"null"', '"undefined"', 'It throws']),
        ('What is the result of `NaN === NaN`?', 'false', ['true', 'undefined', 'TypeError']),
        ('Which method checks whether an array contains a value using SameValueZero semantics?', 'includes()', ['indexOf()', 'hasValue()', 'contains()']),
        ('Why can `indexOf(NaN)` fail to find NaN?', 'NaN is not equal to itself under strict equality', ['indexOf ignores numbers', 'NaN is converted to null', 'Arrays cannot contain NaN']),
        ('What is the JavaScript event loop responsible for?', 'Coordinating execution of queued tasks and asynchronous callbacks around the call stack', ['Compiling JavaScript to machine code only', 'Managing CSS layout', 'Allocating every object']),
        ('Which usually runs before a timer callback after the current task completes?', 'Promise microtasks', ['A new macrotask from setTimeout', 'A CSS animation frame always', 'A network request always']),
        ('What does `Promise.all` do when one input promise rejects?', 'The returned promise rejects with that rejection, without waiting for remaining results to fulfill for the result', ['It converts the rejection to undefined', 'It retries automatically', 'It resolves with successful values only']),
        ('What does `Promise.allSettled` provide?', 'Results describing fulfillment or rejection for every input', ['Only the first result', 'Only successful results', 'Automatic retries']),
        ('What does `async function` return?', 'A Promise', ['A generator', 'A thread', 'A synchronous value directly']),
        ('What does `await` do inside an async function?', 'Pauses that async function until the awaited promise/thenable settles while other event-loop work may continue', ['Blocks the entire browser thread until completion', 'Creates a worker', 'Cancels the promise']),
        ('What is destructuring assignment?', 'Extracting values from arrays or properties from objects into bindings', ['Converting JSON to classes', 'Deleting object properties', 'Cloning objects deeply']),
        ('What is the spread syntax `...` used for?', 'Expanding iterable elements or object properties in supported contexts', ['Deep cloning every nested object', 'Calling a function only', 'Converting strings to numbers']),
        ('What does the rest parameter `...args` collect?', 'Remaining arguments into an array', ['All object properties into a string', 'Only the first argument', 'Arguments into a Set automatically']),
        ('What is an iterator protocol based on?', 'An object with a next() method returning iteration results', ['A class named Iterator only', 'A callback named iterate', 'A DOM interface']),
        ('What does a generator function declared with `function*` produce when called?', 'A generator object implementing the iterator protocol', ['A Promise', 'An array', 'A thread']),
        ('What does `yield` do in a generator?', 'Produces a value and suspends generator execution', ['Ends the generator permanently like return', 'Creates a Promise', 'Throws automatically']),
        ('What is a Symbol mainly used for?', 'Creating unique primitive property keys and symbolic values', ['Creating strings faster', 'Creating threads', 'Representing JSON']),
        ('What is a WeakMap useful for?', 'Associating values with object keys without preventing those keys from being garbage-collected', ['Storing primitive keys only', 'Sorting objects', 'Creating deep copies']),
        ('What is a Proxy?', 'An object that can intercept operations on a target through traps', ['A network proxy server built into JS', 'A Promise subclass', 'A browser cookie']),
        ('What does `Reflect` provide?', 'A set of methods for performing and reflecting language-level object operations', ['A reflection of the DOM only', 'A debugger API only', 'A JSON parser']),
        ('What is event bubbling?', 'An event propagates from a target upward through ancestors after target handling', ['Events move only downward', 'Events are duplicated by the browser', 'Events become promises']),
        ('What is event capturing?', 'An event phase where propagation moves from ancestors toward the target', ['The target-to-parent phase', 'A way to store events', 'A CSS feature']),
        ('What does `stopPropagation()` do?', 'Stops further propagation of the current event through the event path', ['Prevents the default browser action only', 'Removes the event listener permanently', 'Cancels all future events']),
        ('What does `preventDefault()` do?', 'Prevents the browser’s default action for a cancelable event', ['Stops event propagation automatically', 'Deletes the event', 'Stops JavaScript execution']),
        ('What is event delegation?', 'Handling events on an ancestor rather than attaching a separate listener to every child', ['Using only capture phase', 'Disabling bubbling', 'Delegating to a web worker']),
        ('What is a JavaScript module’s default export?', 'A module can have at most one default export', ['Every module must have exactly one', 'Default exports cannot be imported', 'Default export is always a function']),
        ('What does `import` generally do in an ES module?', 'Creates bindings to exported module values', ['Copies source text into the file', 'Loads only JSON', 'Runs code in a separate process']),
        ('What is the purpose of strict mode?', 'It enables stricter parsing and runtime semantics that catch certain problematic behavior', ['It makes all code faster', 'It disables exceptions', 'It enables TypeScript']),
        ('What does `Object.freeze` do?', 'Prevents adding/removing/changing own properties at the object level', ['Deeply freezes every nested object automatically', 'Converts the object to JSON', 'Makes methods private']),
        ('Is `Object.freeze` deeply recursive by default?', 'No', ['Yes', 'Only for arrays', 'Only for functions']),
        ('What does `Map` offer compared with plain object property keys?', 'Keys can be values of any type and insertion order is maintained', ['Only string keys are allowed', 'Keys are always sorted', 'Map cannot be iterated']),
        ('What is a Set designed to store?', 'Unique values according to its equality semantics', ['Key-value pairs', 'Only strings', 'Sorted numbers only']),
        ('What is debouncing commonly used for?', 'Delaying execution until activity stops for a specified period', ['Running a callback every fixed interval', 'Parallelizing CPU work', 'Caching HTTP responses']),
        ('What is throttling commonly used for?', 'Limiting how frequently a function can execute', ['Waiting until all promises resolve', 'Deep cloning objects', 'Blocking the event loop']),
        ('What does `structuredClone` provide in modern environments?', 'Structured cloning of supported data types without sharing ordinary object references', ['JSON serialization only', 'A shallow copy only', 'A string conversion']),
        ('What is a Web Worker primarily for?', 'Running JavaScript in a separate worker context to keep main-thread work responsive', ['Direct DOM manipulation from any thread', 'Replacing CSS', 'Sharing the same call stack']),
        ('What is `localStorage` persistence like?', 'Data persists across page reloads for the same origin until removed or storage is cleared', ['Data disappears on every reload', 'It is shared across all origins', 'It stores only objects']),
        ('What is same-origin policy primarily about?', 'Restricting how documents/scripts from one origin interact with resources from another origin', ['Blocking all network requests', 'Encrypting JavaScript', 'Preventing cookies from being stored']),
        ('What is CORS?', 'A browser mechanism allowing servers to declare permitted cross-origin requests', ['A JavaScript data structure', 'A CSS rule', 'A replacement for HTTPS']),
    ],
    'HTML/CSS': [
        ('Which element is the most appropriate semantic container for the primary content of a page?', 'main', ['div', 'content', 'body-main']),
        ('What is the main purpose of the `label` element for a form control?', 'Associate descriptive text with the control and improve usability/accessibility', ['Submit the form automatically', 'Validate every field', 'Style the input']),
        ('Why is a `<button type="submit">` different from a generic `<div>` used as a button?', 'It has native button semantics and keyboard/form behavior', ['div is always inaccessible', 'button cannot receive focus', 'div automatically submits forms']),
        ('What does the `alt` attribute on an informative image provide?', 'A text alternative for users who cannot perceive the image', ['A tooltip guaranteed to display', 'A CSS class', 'A loading priority']),
        ('When is an empty `alt=""` appropriate?', 'When an image is purely decorative and conveys no information', ['For every image', 'Only for logos', 'Only when the image fails to load']),
        ('What does `aria-label` provide?', 'An accessible name when appropriate native labeling is unavailable or insufficient', ['A visual label displayed automatically', 'A CSS selector', 'Form validation']),
        ('Why should native semantic HTML generally be preferred over unnecessary ARIA roles?', 'Native elements provide built-in semantics and behavior that ARIA does not fully replace', ['ARIA never works', 'Semantic HTML cannot be styled', 'ARIA is only for images']),
        ('What does `<script defer>` generally do?', 'Downloads without blocking HTML parsing and executes after parsing, preserving document order among deferred scripts', ['Executes before downloading', 'Runs immediately during parsing', 'Runs only after window unload']),
        ('What is a key difference with `<script async>`?', 'It can execute as soon as it downloads, potentially out of document order', ['It always waits for DOMContentLoaded', 'It blocks downloads', 'It executes only after defer scripts']),
        ('What is `srcset` used for on images?', 'Providing multiple image resources for responsive selection', ['Setting image CSS', 'Adding alternative text', 'Embedding SVG code only']),
        ('What does the `<picture>` element help with?', 'Art direction and responsive image source selection', ['Creating CSS grids', 'Audio playback', 'Form validation']),
        ('What does `autocomplete` on forms help browsers do?', 'Provide or disable appropriate autofill behavior for recognized fields', ['Validate HTML syntax', 'Encrypt passwords', 'Prevent submission']),
        ('What is the purpose of `novalidate` on a form?', 'Disable the browser’s built-in constraint validation for that form', ['Disable submission', 'Disable CSS', 'Make all inputs required']),
        ('Which input type provides built-in email-format constraint validation?', 'email', ['mailbox', 'text-email', 'address']),
        ('What does the `required` attribute do for a form control?', 'Makes the control subject to required-value constraint validation', ['Prevents typing', 'Makes it read-only', 'Encrypts the value']),
        ('What is CSS specificity used for?', 'Determining which competing declarations have higher selector precedence within the cascade', ['Determining page load order', 'Calculating element width only', 'Choosing font files']),
        ('Which generally has greater specificity?', 'An ID selector such as #app', ['A class selector such as .app', 'An element selector such as div', 'The universal selector *']),
        ('What is special about `:where()` in CSS specificity?', 'Its arguments contribute zero specificity', ['It always has ID specificity', 'It disables the selector', 'It only matches forms']),
        ('What is special about `:is()`?', 'Its specificity is based on the most specific selector in its argument list', ['It always has zero specificity', 'It can only contain one selector', 'It disables inheritance']),
        ('What does `:has()` enable?', 'Selecting an element based on a relative selector relationship involving its descendants or related elements', ['Selecting only the parent HTML element', 'Animating pseudo-elements', 'Matching only IDs']),
        ('What is the CSS cascade layer feature `@layer` for?', 'Controlling precedence between groups of author styles in the cascade', ['Creating JavaScript modules', 'Defining media queries only', 'Loading fonts']),
        ('What does CSS inheritance mean?', 'Some properties can take computed values from an ancestor when not otherwise specified', ['Every property inherits', 'Only layout properties inherit', 'Inheritance copies the DOM node']),
        ('What does `box-sizing: border-box` change?', 'The declared width/height include padding and border for the box', ['Padding is removed', 'Margin becomes part of width', 'Borders become transparent']),
        ('What is the default `box-sizing` value for most elements?', 'content-box', ['border-box', 'padding-box', 'inherit']),
        ('What does `position: absolute` position an element relative to?', 'Its containing block, commonly established by the nearest positioned ancestor', ['Always the viewport', 'Always the body', 'Only the previous sibling']),
        ('What does `position: fixed` generally use as its containing reference?', 'The viewport, subject to containing-block effects such as transforms', ['The nearest flex item', 'The parent grid cell only', 'The document title']),
        ('What can create a new stacking context?', 'Properties such as positioned elements with z-index, opacity below 1, and transforms in relevant conditions', ['Every div', 'Every margin', 'Every text node']),
        ('Why can a high `z-index` still appear behind another element?', 'Stacking contexts constrain z-index comparisons across contexts', ['z-index never works', 'The element must be flex', 'z-index only applies to images']),
        ('What does Flexbox primarily solve?', 'One-dimensional layout along a main axis with cross-axis alignment', ['Two-dimensional page layout only', 'Database layout', 'Text parsing']),
        ('What does `flex: 1` commonly expand to conceptually?', 'A combination of flex-grow, flex-shrink, and flex-basis values according to the shorthand', ['Only flex-grow:1', 'Only width:1px', 'display:flex and gap:1']),
        ('What does CSS Grid excel at?', 'Two-dimensional row-and-column layout', ['Only vertical centering', 'Only typography', 'Event handling']),
        ('What does `minmax(200px, 1fr)` mean in Grid?', 'A track with a minimum of 200px and a flexible maximum of 1fr', ['A fixed 200px track', 'A maximum of 200px only', 'A 1px minimum']),
        ('What does `auto-fit` with `repeat()` commonly enable?', 'Responsive tracks that can collapse empty tracks as available space changes', ['Fixed-width columns only', 'Disabling wrapping', 'Vertical scrolling']),
        ('What is the purpose of `gap` in Flexbox/Grid?', 'Defines spacing between flex/grid items without needing margins on each item', ['Adds outer page margin', 'Changes item width only', 'Sets line-height']),
        ('What does `overflow: hidden` generally do?', 'Clips overflowing content and can establish a scroll/containment behavior depending on context', ['Always creates a scrollbar', 'Makes content invisible to assistive technology', 'Deletes overflowing DOM nodes']),
        ('What is the difference between `visibility: hidden` and `display: none`?', 'Hidden elements generally retain layout space, while display:none removes them from layout', ['They are identical', 'display:none retains layout but visibility does not', 'visibility hidden deletes the element']),
        ('What does `opacity: 0` do?', 'Makes the element fully transparent while it generally remains in layout and can still receive interaction', ['Removes it from the DOM', 'Always makes it inaccessible', 'Sets display:none']),
        ('What is a CSS custom property?', 'A variable-like property such as --brand-color that can be used with var()', ['A JavaScript variable', 'A browser extension', 'An HTML attribute']),
        ('What does `var(--x, red)` mean?', 'Use --x if available, otherwise use red as the fallback', ['Always use red', 'Set --x to red', 'Remove --x']),
        ('What are logical properties such as `margin-inline` useful for?', 'Writing-mode and direction-aware layout', ['JavaScript event handling', 'Only print styles', 'Image compression']),
        ('What does a media query do?', 'Applies CSS conditionally based on media or environment features', ['Queries a database', 'Selects DOM nodes by ID', 'Loads JavaScript modules']),
        ('What does `@supports` do?', 'Conditionally applies CSS when the browser supports a specified feature', ['Checks server support', 'Tests JavaScript variables', 'Creates a shadow DOM']),
        ('What is a pseudo-element such as `::before`?', 'A generated styling hook representing a conceptual part of an element', ['A real HTML child node', 'A JavaScript object', 'A new document']),
        ('What is a pseudo-class such as `:hover`?', 'A selector representing an element state or structural condition', ['A generated child element', 'A CSS variable', 'An HTML attribute']),
        ('What does `transform: translateX(...)` generally do to layout?', 'Visually transforms the element without changing normal-flow layout dimensions', ['Changes document flow size like margin', 'Deletes the element', 'Changes its HTML content']),
        ('What is a containing block important for?', 'It establishes the reference rectangle used by certain positioned or sized descendants', ['It stores CSS variables only', 'It defines HTML validity', 'It controls JavaScript scope']),
        ('What is `clamp(min, preferred, max)` useful for?', 'Constraining a responsive value between a minimum and maximum', ['Clamping JavaScript exceptions', 'Limiting HTML form input', 'Disabling media queries']),
        ('What does `aspect-ratio` help control?', 'The preferred width-to-height ratio of a box', ['Font weight', 'Grid line numbering', 'Text encoding']),
        ('What does `object-fit: cover` commonly do for replaced content such as images?', 'Scales content to cover its box, potentially cropping it', ['Stretches it without preserving ratio', 'Hides the image', 'Adds a border']),
        ('What is `loading="lazy"` commonly used for?', 'Hinting that offscreen images/iframes may be deferred until needed', ['Forcing immediate loading', 'Disabling caching', 'Compressing images']),
    ],
}


def build_language_questions(language):
    """Return 50 unique MCQs for the selected programming language."""
    if language not in LANGUAGE_QUESTION_BANK:
        raise ValueError("Unsupported trainer language")

    questions = []
    for question, correct, wrongs in LANGUAGE_QUESTION_BANK[language]:
        options = [correct] + list(wrongs)
        questions.append({"question": question, "correct": correct, "wrong": list(wrongs)})

    # Shuffle question order and option order for every attempt.
    random.shuffle(questions)
    return questions

@app.route("/trainer/language", methods=["GET", "POST"])
@login_required
def trainer_language():
    user = current_user()
    if not user or user["role"] != "trainer":
        flash("This page is only for trainers.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        language = request.form.get("expert_language", "").strip()
        if language not in SUPPORTED_TRAINER_LANGUAGES:
            flash("Please select a valid programming language.", "danger")
            return redirect(url_for("trainer_language"))

        conn = get_db()
        conn.execute(
            "UPDATE trainer_profiles SET expert_language=? WHERE user_id=?",
            (language, user["id"])
        )
        conn.commit()
        conn.close()

        session.pop("assessment_answer_key", None)
        return redirect(url_for("trainer_assessment"))

    conn = get_db()
    profile = conn.execute(
        "SELECT expert_language FROM trainer_profiles WHERE user_id=?",
        (user["id"],)
    ).fetchone()
    conn.close()

    current_language = profile["expert_language"] if profile else ""
    body = """
    <div class="auth-wrapper">
      <div class="auth-card">
        <h2>Choose Your Expert Programming Language</h2>
        <p>Select the programming language in which you are expert. Your 50-question trainer assessment will be based on this selection.</p>
        <form method="POST">
          <div class="form-group">
            <label>Expert Programming Language</label>
            <select class="form-control" name="expert_language" required>
              <option value="">Select a language</option>
              {% for language in languages %}
              <option value="{{ language }}" {% if language == current_language %}selected{% endif %}>{{ language }}</option>
              {% endfor %}
            </select>
          </div>
          <button class="btn btn-primary" style="width:100%" type="submit">Continue to Assessment</button>
        </form>
        <p class="small" style="margin-top:18px">You will answer 50 MCQs. The choices will be randomly arranged for every attempt.</p>
      </div>
    </div>
    """
    return render_page("Trainer Language Selection", body,
                       languages=SUPPORTED_TRAINER_LANGUAGES,
                       current_language=current_language)


# ============================================================
# TRAINER MCQ ASSESSMENT
# ============================================================

@app.route("/trainer/assessment", methods=["GET", "POST"])
@login_required
def trainer_assessment():
    user = current_user()
    if not user or user["role"] != "trainer":
        flash("This assessment is only for trainers.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db()
    profile = conn.execute(
        "SELECT expert_language FROM trainer_profiles WHERE user_id=?",
        (user["id"],)
    ).fetchone()
    conn.close()

    language = profile["expert_language"] if profile else None
    if language not in SUPPORTED_TRAINER_LANGUAGES:
        return redirect(url_for("trainer_language"))

    questions = build_language_questions(language)

    if request.method == "POST":
        answer_key = session.get("assessment_answer_key", {})
        score = 0
        for index in range(len(questions)):
            if request.form.get(f"q_{index}", "") == answer_key.get(str(index)):
                score += 1

        total = len(questions)
        percentage = round((score / total) * 100, 1) if total else 0

        if percentage >= 80:
            status = "Passed - Approved"
            approved = 1
            message = "Congratulations! You scored 80% or above. Your trainer account has been approved automatically."
        elif percentage >= 50:
            status = "Re-test Required"
            approved = 0
            message = "You scored between 50% and 79%. A re-test is required. Your trainer account remains pending approval."
        else:
            status = "Failed - Re-test Required"
            approved = 0
            message = "You scored below 50%. Your trainer account remains pending approval and you must take the assessment again."

        conn = get_db()
        conn.execute("""
            INSERT INTO trainer_assessment_attempts
            (trainer_id, score, total, percentage, status, expert_language)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user["id"], score, total, percentage, status, language))
        conn.execute(
            "UPDATE users SET approved=? WHERE id=? AND role='trainer'",
            (approved, user["id"])
        )
        conn.commit()
        conn.close()
        session.pop("assessment_answer_key", None)

        return render_page(
            "Trainer Assessment Result",
            f"""
            <div class="dashboard"><div class="container">
            <div class="card" style="max-width:760px;margin:50px auto;text-align:center">
                <div style="font-size:55px">{'🎉' if approved else '📝'}</div>
                <h1>Trainer Assessment Result</h1>
                <p class="small">Programming Language: <strong>{escape(language)}</strong></p>
                <p class="small">Course Name: <strong>Trainer MCQ Based Test</strong></p>
                <div class="score" style="font-size:52px;margin:25px 0">{score}/{total}</div>
                <h2>{percentage}%</h2>
                <p><strong>{escape(status)}</strong></p>
                <p>{escape(message)}</p>
                {'<a class="btn btn-primary" href="' + url_for('trainer_dashboard') + '">Go to Trainer Dashboard</a>' if approved else '<a class="btn btn-primary" href="' + url_for('trainer_language') + '">Choose Language & Re-test</a>'}
                <a class="btn btn-light" style="margin-left:8px" href="/logout">Logout</a>
            </div></div></div>
            """
        )

    # Build a fresh randomized option order for this attempt.
    prepared = []
    answer_key = {}
    for index, item in enumerate(questions):
        options = [item["correct"]] + item["wrong"]
        random.shuffle(options)
        labels = ["A", "B", "C", "D"]
        correct_letter = labels[options.index(item["correct"])]
        answer_key[str(index)] = correct_letter
        prepared.append({
            "number": index + 1,
            "question": item["question"],
            "options": list(zip(labels, options)),
        })

    session["assessment_answer_key"] = answer_key

    body = """
    <div class="dashboard">
    <div class="container">
        <div class="page-heading">
            <div>
                <h1>Trainer MCQ Assessment</h1>
                <p>Expert Programming Language: <strong>{{ language }}</strong></p>
                <p>Course Name: <strong>Trainer MCQ Based Test</strong></p>
            </div>
            <span class="badge">50 QUESTIONS • 50 MARKS</span>
        </div>

        <div class="card" style="margin-bottom:25px">
            <h3>Assessment Rules</h3>
            <p class="small">50 programming MCQs • 1 mark each • Options are randomly arranged.</p>
            <p class="small"><strong>80–100%:</strong> Passed and automatically approved.</p>
            <p class="small"><strong>50–79%:</strong> Re-test required; account remains pending.</p>
            <p class="small"><strong>Below 50%:</strong> Failed; account remains pending.</p>
        </div>

        <form method="POST">
        {% for q in questions %}
        <div class="card" style="margin-bottom:18px">
            <h3>{{ q.number }}. {{ q.question }}</h3>
            {% for label, option in q.options %}
            <label style="display:block;padding:10px 12px;margin:8px 0;border:1px solid var(--border);border-radius:10px;cursor:pointer">
                <input type="radio" name="q_{{ q.number - 1 }}" value="{{ label }}" required>
                <strong>{{ label }}.</strong> {{ option }}
            </label>
            {% endfor %}
        </div>
        {% endfor %}
        <button class="btn btn-primary" type="submit" style="width:100%;margin-bottom:40px">Submit Assessment</button>
        </form>
    </div>
    </div>
    """

    return render_page("Trainer Assessment", body,
                       questions=prepared, language=language)


@app.route("/admin/trainer-assessments")
@role_required("admin")
def admin_trainer_assessments():
    conn = get_db()
    results = conn.execute("""
        SELECT
            trainer_assessment_attempts.*,
            users.name,
            users.email,
            users.approved,
            trainer_assessment_attempts.expert_language
        FROM trainer_assessment_attempts
        JOIN users ON users.id=trainer_assessment_attempts.trainer_id
        ORDER BY trainer_assessment_attempts.id DESC
        LIMIT 200
    """).fetchall()
    conn.close()

    body = """
    <div class="dashboard"><div class="container">
        <div class="page-heading">
            <div><h1>Trainer Assessment Results</h1><p>Review trainer MCQ assessment attempts and approval status.</p></div>
            <a class="btn btn-light" href="{{ url_for('admin_dashboard') }}">Back to Admin</a>
        </div>
        <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>Trainer</th><th>Email</th><th>Language</th><th>Score</th><th>Percentage</th><th>Status</th><th>Account</th><th>Date</th></tr></thead>
        <tbody>
        {% for row in results %}
        <tr>
            <td>{{ row["name"] }}</td>
            <td>{{ row["email"] }}</td>
            <td>{{ row["expert_language"] or "-" }}</td>
            <td>{{ row["score"] }}/{{ row["total"] }}</td>
            <td>{{ row["percentage"] }}%</td>
            <td>{{ row["status"] }}</td>
            <td>{% if row["approved"] %}Approved{% else %}Pending{% endif %}</td>
            <td>{{ row["attempted_at"] }}</td>
        </tr>
        {% else %}
        <tr><td colspan="8" style="text-align:center">No trainer assessment attempts yet.</td></tr>
        {% endfor %}
        </tbody></table></div></div>
    </div></div>
    """
    return render_page("Trainer Assessment Results", body, results=results)


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

<div style="display:flex;gap:10px;flex-wrap:wrap">
<a class="btn btn-light" href="{{ url_for('trainer_assessment') }}">Trainer Assessment</a>
<a class="btn btn-primary" href="{{ url_for('create_course') }}">
+ Create Course
</a>
</div>

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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

<div style="display:flex;gap:10px;flex-wrap:wrap">
<a class="btn btn-light" href="{{ url_for('admin_trainer_assessments') }}">Trainer Assessments</a>
<a class="btn btn-primary" href="{{ url_for('admin_announcements') }}">
Publish Announcement
</a>
</div>

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

# Initialize the database when the module is imported too.
# This is required when Render starts the app with Gunicorn
# (gunicorn app_public:app), because __main__ is not executed.
initialize_database()

if __name__ == "__main__":

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
    print("Email    :", os.environ.get("ADMIN_EMAIL", "").strip())
    print("Password : use ADMIN_PASSWORD environment variable")
    print()
    print("=" * 60)
    print()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False
    )