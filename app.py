from flask import Flask, render_template, request, redirect, jsonify, g, send_file, Blueprint, url_for, flash, session, send_from_directory
from sqlalchemy.sql.functions import current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import sqlite3, os, requests, logging, json, re
from docx import Document

from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

DB_FILE = 'debate_portal.db'
TOURNY_UPLOAD_FOLDER = 'uploads/tournaments'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

OPENROUTER_API_KEY = "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"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

app.config['UPLOAD_FOLDER'] = TOURNY_UPLOAD_FOLDER
os.makedirs(TOURNY_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                name TEXT, age INTEGER, debate_style TEXT, speech_style TEXT)
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                completed INTEGER DEFAULT 0,
                priority TEXT,
                summary TEXT,
                tag TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id))
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS vulnerabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, title TEXT, description TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id))
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, coach_name TEXT, comment TEXT, timestamp TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id))
        ''')

        c.execute('''
        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, label TEXT, score INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id))
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                date TEXT,
                description TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id))
        ''')

        # Add tournament_files table
        c.execute('''
            CREATE TABLE IF NOT EXISTS tournament_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY(tournament_id) REFERENCES tournaments(id))
        ''')

        # Folders for Build Page
        c.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                user_summary TEXT,
                ai_summary TEXT)
        ''')

        # Files inside Folders
        c.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER,
                filename TEXT,
                filepath TEXT,
                ai_summary TEXT,
                FOREIGN KEY(folder_id) REFERENCES folders(id))
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS case_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                analysis_type TEXT,
                user_notes TEXT,
                original_text TEXT,
                ai_feedback TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id))
        ''')

        c.execute('''
                  CREATE TABLE IF NOT EXISTS past_debates (
                                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                                           user_id INTEGER,
                                           title TEXT,
                                           summary TEXT,
                                           date TEXT,
                                           side TEXT);
        ''')

        c.execute('''
          CREATE TABLE IF NOT EXISTS speeches (
                                                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                  round_id INTEGER NOT NULL,
                                                  user_id INTEGER NOT NULL,               -- <-- define user_id first
                                                  name TEXT NOT NULL,                     -- e.g., '1AC', '1NC', etc.
                                                  speaker TEXT NOT NULL,                  -- e.g., 'Aff', 'Neg', or name
                                                  content TEXT NOT NULL,                  -- full speech content
                                                  feedback_json TEXT,                     -- optional: cached JSON AI feedback
                                                  FOREIGN KEY (user_id) REFERENCES users(id)
              );
          ''')

    c.execute('''
            CREATE TABLE IF NOT EXISTS debates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                side TEXT,
                elo INTEGER,
                transcript TEXT,
                ai_responses TEXT,
                summary TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id));
        ''')

    conn.commit()

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        form = request.form
        email = form['email']
        password = form['password']
        name = form.get('name')
        age = form.get('age')
        debate_style = form.get('debate_style')
        speech_style = form.get('speech_style')

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()

            if user:
                if check_password_hash(user[2], password):
                    session['user_id'] = user[0]
                    session['name'] = user[3]
                    session['email'] = email
                    return redirect(url_for('dashboard'))
                else:
                    flash("Incorrect password.", "danger")
            else:
                if all([name, age, debate_style, speech_style]):
                    hashed_pw = generate_password_hash(password)
                    cursor.execute("""
                        INSERT INTO users (email, password, name, age, debate_style, speech_style)
                        VALUES (?, ?, ?, ?, ?, ?)""", (email, hashed_pw, name, age, debate_style, speech_style))
                    conn.commit()
                    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                    new_id = cursor.fetchone()[0]
                    session['user_id'] = new_id
                    session['name'] = name
                    session['email'] = email
                    return redirect(url_for('dashboard'))
                else:
                    flash("Please complete your profile info to register.", "warning")

    return render_template("auth.html")

@app.route('/auth/check_user', methods=['POST'])
def check_user():
    data = request.get_json()
    email = data.get('email')
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE email = ?", (email,))
        exists = cursor.fetchone() is not None
        return jsonify({'exists': exists})

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('auth'))

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()

        # TASKS
        c.execute("""
                       SELECT id, title, description, completed, priority, summary, tag
                       FROM tasks WHERE user_id = ?""", (user_id,))
        tasks = [{
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "completed": bool(row[3]),
            "priority": row[4],
            "summary": row[5],
            "tag": row[6]
        } for row in c.fetchall()]

        # TOURNAMENTS (with files)
        c.execute("SELECT id, name, date, description FROM tournaments WHERE user_id = ?", (user_id,))
        tournaments = [{
            "id": row[0],
            "name": row[1],
            "date": row[2],
            "description": row[3],
        } for row in c.fetchall()]

        for t in tournaments:
            c.execute("SELECT id, filename FROM tournament_files WHERE tournament_id = ?", (t["id"],))
            t["files"] = [{"id": f[0], "filename": f[1]} for f in c.fetchall()]

        # VULNERABILITIES
        c.execute("SELECT title, description FROM vulnerabilities WHERE user_id = ?", (user_id,))
        vulnerabilities = [{"title": row[0], "description": row[1]} for row in c.fetchall()]

        # PERFORMANCE
        c.execute("SELECT label, score FROM performance WHERE user_id = ?", (user_id,))
        perf_rows = c.fetchall()
        if not perf_rows:
            performance = {"labels": ["Round 1", "Round 2", "Round 3"], "data": [70, 80, 85]}
        else:
            labels, data = zip(*perf_rows)
            performance = {"labels": labels, "data": data}

        # FEEDBACK
        c.execute(
            "SELECT comment, timestamp FROM feedback WHERE user_id = ? ORDER BY timestamp DESC LIMIT 3",
            (user_id,))
        feedbacks = [{
            "coach_name": "Coach Taylor",
            "comment": row[0],
            "timestamp": row[1]
        } for row in c.fetchall()]

    # ALERTS & EVENTS
    today = datetime.now().date()
    alerts = [
        {"message": "Debate Team forms due in 5 days"},
        {"message": "Debate cases should be completed in 10 days"},
        {"message": "Official Debate Team banquet in 21 days"}
    ]
    events = [
        {"name": "Info Session", "date": (today + timedelta(weeks=1)).strftime("%B %d, %Y"), "countdown": "7 days left"},
        {"name": "Debate Practice", "date": (today + timedelta(weeks=2)).strftime("%B %d, %Y"), "countdown": "14 days left"},
        {"name": "Official First Debate @ Parkway West", "date": (today + timedelta(weeks=4)).strftime("%B %d, %Y"), "countdown": "28 days left"}
    ]

    return render_template(
        "dashboard.html",
        name=session.get('name'),
        email=session.get('email'),
        tasks=tasks,
        tournaments=tournaments,
        vulnerabilities=vulnerabilities,
        performance=performance,
        feedbacks=feedbacks,
        alerts=alerts,
        events=events
    )


# Helper Functions
def call_openrouter_gpt(prompt, max_tokens=800):
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
            timeout=15
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()

    except requests.exceptions.HTTPError as http_err:
        logger.exception("HTTP error: %s", http_err)
    except requests.exceptions.RequestException as req_err:
        logger.exception("Request error: %s", req_err)
    except json.JSONDecodeError as json_err:
        logger.exception("JSON decode error: %s", json_err)
    except Exception:
        logger.exception("General error in call_openrouter_gpt")

    return "Sorry, something went wrong while trying to respond. Please try again in a moment."

# --- AI Endpoints ---
@app.route("/ai/summarize_task", methods=["POST"])
def ai_summarize_task():
    data = request.get_json()
    desc = data.get("description", "").strip()

    if not desc:
        return jsonify({"summary": "", "error": "No description provided."}), 400

    prompt = (f"Summarize the following task description in one siungle concise sentence:\n\n{desc}\n\n"
              f"Only respond with the summary and one sentence.")
    summary = call_openrouter_gpt(prompt)
    return jsonify({"summary": summary})


@app.route("/ai/suggest_tag", methods=["POST"])
def ai_suggest_tag():
    data = request.get_json()
    title = data.get("title", "").strip()
    desc = data.get("description", "").strip()

    if not title and not desc:
        return jsonify({"tag": "", "error": "No input provided."}), 400

    prompt = (
        f"Given the following task information:\n\n"
        f"Title: {title}\nDescription: {desc}\n\n"
        f"Suggest ONE short, general category tag for this task. "
        f"Do not include punctuation or explanations."
    )

    tag = call_openrouter_gpt(prompt)
    return jsonify({"tag": tag})


# --- Task Operations ---
@app.route('/dashboard/add_task', methods=['POST'])
def add_task():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    title = request.form.get('title')
    description = request.form.get('description')
    priority = request.form.get('priority')
    completed = 0

    if not title:
        flash("Task title is required.", "warning")
        return redirect(url_for('dashboard'))

    try:
        summary_prompt = (
            f"Summarize the following task description in one short, clear sentence. "
            f"Return only the sentence:\n\n{description}"
        )
        tag_prompt = (
            f"Based on this task, suggest ONE short category tag that describes it best. "
            f"Do not include punctuation or explanation.\n\nTitle: {title}\nDescription: {description}"
        )
        summary = call_openrouter_gpt(summary_prompt)
        tag = call_openrouter_gpt(tag_prompt)
    except Exception as e:
        print("AI Error:", e)
        summary = "No summary available."
        tag = "General"
        print("[DEBUG] OpenRouter raw response:", result)

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO tasks (user_id, title, description, completed, priority, summary, tag)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, title, description, completed, priority, summary, tag))
        conn.commit()

    flash("Task added with AI enhancements!", "success")
    return redirect(url_for('dashboard'))


@app.route('/dashboard/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    user_id = session.get('user_id')
    if not user_id:from werkzeug.utils import secure_filename

from flask import send_from_directory

@app.route('/dashboard/tournaments/add', methods=['POST'])
def add_tournament():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    name = request.form.get('name')
    date = request.form.get('date')
    description = request.form.get('description')

    if not name:
        flash("Tournament name is required.", "warning")
        return redirect(url_for('dashboard'))

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO tournaments (user_id, name, date, description) VALUES (?, ?, ?, ?)",
                  (user_id, name, date, description))
        conn.commit()

    flash("Tournament added!", "success")
    return redirect(url_for('dashboard'))


@app.route('/dashboard/tournaments/<int:tournament_id>/upload', methods=['POST'])
def upload_tournament_file(tournament_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('dashboard'))

    file = request.files['file']

    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(url_for('dashboard'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Optionally prefix filename with tournament id or UUID for uniqueness
        filename_on_disk = f"{tournament_id}_{filename}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename_on_disk)
        file.save(save_path)

        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO tournament_files (tournament_id, filename, filepath, uploaded_at) VALUES (?, ?, ?, ?)",
                      (tournament_id, filename, filename_on_disk, datetime.now().isoformat()))
            conn.commit()

        flash("File uploaded!", "success")
    else:
        flash("File type not allowed.", "danger")

    return redirect(url_for('dashboard'))


@app.route('/dashboard/tournaments/file/<int:file_id>/download')
def download_tournament_file(file_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
                  SELECT tf.filepath, t.user_id FROM tournament_files tf
                                                         JOIN tournaments t ON tf.tournament_id = t.id
                  WHERE tf.id = ?
                  ''', (file_id,))
        row = c.fetchone()

    if not row:
        flash("File not found.", "danger")
        return redirect(url_for('dashboard'))

    filepath, owner_id = row
    if owner_id != user_id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('dashboard'))

    return send_from_directory(app.config['UPLOAD_FOLDER'], filepath, as_attachment=True)

    return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        conn.commit()

    flash("Task deleted.", "success")
    return redirect(url_for('dashboard'))

@app.route('/dashboard/tournaments/<int:tournament_id>/delete', methods=['POST'])
def delete_tournament(tournament_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # Ensure tournament belongs to user
        c.execute("SELECT user_id FROM tournaments WHERE id = ?", (tournament_id,))
        row = c.fetchone()
        if not row or row[0] != user_id:
            flash("Unauthorized", "danger")
            return redirect(url_for('dashboard'))

        # Delete all files
        c.execute("SELECT filepath FROM tournament_files WHERE tournament_id = ?", (tournament_id,))
        for (filepath,) in c.fetchall():
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filepath))
            except FileNotFoundError:
                pass

        c.execute("DELETE FROM tournament_files WHERE tournament_id = ?", (tournament_id,))
        c.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
        conn.commit()

    flash("Tournament deleted.", "success")
    return redirect(url_for('dashboard'))


@app.route('/dashboard/tournaments/file/<int:file_id>/delete', methods=['POST'])
def delete_tournament_file(file_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth'))

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
                  SELECT tf.filepath, t.user_id FROM tournament_files tf
                                                         JOIN tournaments t ON tf.tournament_id = t.id
                  WHERE tf.id = ?
                  ''', (file_id,))
        row = c.fetchone()

    if not row or row[1] != user_id:
        flash("Unauthorized", "danger")
        return redirect(url_for('dashboard'))

    filepath = row[0]
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filepath))
    except FileNotFoundError:
        pass

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM tournament_files WHERE id = ?", (file_id,))
        conn.commit()

    flash("File deleted.", "success")
    return redirect(url_for('dashboard'))

@app.route("/build")
def build():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM folders")
        folders = c.fetchall()

        folder_data = []
        for f in folders:
            folder_id, name, user_summary, ai_summary = f
            c.execute("SELECT id, filename FROM files WHERE folder_id = ?", (folder_id,))
            files = c.fetchall()
            folder_data.append({
                "id": folder_id,
                "name": name,
                "user_summary": user_summary,
                "ai_summary": ai_summary,
                "files": files
            })

    return render_template("build.html", folders=folder_data)

@app.route('/message', methods=['POST'])
def chatbot_message():
    data = request.json
    user_message = data.get("message", "").strip()
    user_case = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please enter a message so I can respond."})

    prompt = f"""
    You are a professional chatbot aimed at helping the user with their debate case or questions. 
    A user has written the following message: "{user_message}". 
    While responding, take into consideration their case so far: {user_case}.
    
    Please respond professionally with high quality. 
    Always respond in 1 - 2 paragraphs, not bullet points/lists.
    """

    bot_reply = call_openrouter_gpt(prompt, max_tokens=800)
    return jsonify({"reply": bot_reply})

# Route: Add Folder
@app.route("/add_folder", methods=["POST"])
def add_folder():
    name = request.form.get("name")
    user_summary = request.form.get("user_summary")
    ai_prompt = f"Give a very short summary for a debate folder titled '{name}' with contents described as: {user_summary}"
    ai_summary = call_openrouter_gpt(ai_prompt, max_tokens=500)

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO folders (name, user_summary, ai_summary) VALUES (?, ?, ?)", (name, user_summary, ai_summary))
        conn.commit()

    return redirect(url_for("build"))


@app.route("/upload_file/<int:folder_id>", methods=["POST"])
def upload_file(folder_id):
    file = request.files.get("file")
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], str(folder_id))
        os.makedirs(folder_path, exist_ok=True)
        filepath = os.path.join(folder_path, filename)
        file.save(filepath)

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            text = f"Unable to read content of file: {filename}"

        # Generate AI summary for this file
        ai_prompt_file = f"Give a short, strategic debate summary of the following document: {text[:2000]}"
        ai_summary_file = call_openrouter_gpt(ai_prompt_file, max_tokens=300)

        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            # Insert file record
            c.execute(
                "INSERT INTO files (folder_id, filename, filepath, ai_summary) VALUES (?, ?, ?, ?)",
                (folder_id, filename, filepath, ai_summary_file)
            )
            conn.commit()

            # Get existing user_summary of folder to include in AI prompt
            c.execute("SELECT user_summary FROM folders WHERE id = ?", (folder_id,))
            row = c.fetchone()
            user_summary = row[0] if row else ""

            # Get all file summaries for this folder
            c.execute("SELECT ai_summary FROM files WHERE folder_id = ?", (folder_id,))
            file_summaries = [row[0] for row in c.fetchall()]

            # Combine all file summaries into one string (limit length for prompt)
            combined_file_summaries = "\n".join(file_summaries)[:3000]

            # Create prompt for folder summary update
            ai_prompt_folder = (
                f"Given the folder title and user summary: '{user_summary}', "
                f"and the following file summaries: {combined_file_summaries}, "
                f"generate a very short debate summary of this folder."
            )

            # Generate new AI summary for folder
            new_folder_summary = call_openrouter_gpt(ai_prompt_folder, max_tokens=500)

            # Update folder's ai_summary in DB
            c.execute(
                "UPDATE folders SET ai_summary = ? WHERE id = ?",
                (new_folder_summary, folder_id)
            )
            conn.commit()

    return redirect(url_for("build"))


# Route: Delete File
@app.route("/delete_file/<int:file_id>", methods=["POST"])
def delete_file(file_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT filepath FROM files WHERE id = ?", (file_id,))
        row = c.fetchone()
        if row:
            filepath = row[0]
            try:
                os.remove(filepath)
            except FileNotFoundError:
                pass
        c.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.commit()
    return redirect(url_for("build"))


# Route: Download File
@app.route("/download_file/<int:file_id>")
def download_file(file_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT filepath, filename FROM files WHERE id = ?", (file_id,))
        row = c.fetchone()
        if row:
            filepath, filename = row
            return send_file(filepath, as_attachment=True, download_name=filename)
    return "File not found.", 404

@app.route("/delete_folder/<int:folder_id>", methods=["POST"])
def delete_folder(folder_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # First delete all files in this folder (and optionally their physical files)
        c.execute("SELECT filepath FROM files WHERE folder_id = ?", (folder_id,))
        filepaths = c.fetchall()
        for (filepath,) in filepaths:
            try:
                os.remove(filepath)
            except FileNotFoundError:
                pass
        c.execute("DELETE FROM files WHERE folder_id = ?", (folder_id,))

        # Now delete the folder
        c.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        conn.commit()
    return redirect(url_for("build"))

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def generate_case_prompt(case_text, user_notes, analysis_type, feedback_style):
    role_tone = {
        "coach": "You are a seasoned debate coach providing analytical and developmental feedback.",
        "judge": "You are a judge providing post-round commentary with an educational purpose."
    }[feedback_style]

    return f"""
        {role_tone}
        
        The user is submitting a {analysis_type.lower()} document. Please analyze the text in four structured sections:
        1. **General Wording Feedback** – Tone, clarity, rhetorical effectiveness, engagement.
        2. **Technical Feedback** – Strengths, weaknesses, logical structure, missing warrants, powerful counters.
        3. **Future Suggestions** – Specific actionable edits, phrasing improvements, and structure rewrites.
        4. **Flow Map** – Summarize the argumentative progression, highlighting internal clashes and flow issues.
        
        --- CASE TEXT START ---
        {case_text}
        --- CASE TEXT END ---
        
        --- USER NOTES ---
        {user_notes or "None provided."}
        """



@app.route('/analyze_case', methods=['POST'])
def analyze_case():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    file = request.files.get('file')
    analysis_type = request.form.get('analysis_type', 'Full Analysis')
    user_notes = request.form.get('user_notes', '')
    feedback_style = request.form.get('feedback_style', 'coach')

    if not file or not file.filename.endswith('.docx'):
        return jsonify({"error": "Upload a valid .docx file."}), 400

    filepath = os.path.join('uploads', secure_filename(file.filename))
    file.save(filepath)

    case_text = extract_text_from_docx(filepath)
    prompt = generate_case_prompt(case_text, user_notes, analysis_type, feedback_style)
    ai_output = call_openrouter_gpt(prompt, max_tokens=1800)

    # Save result
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
                  INSERT INTO case_analysis (user_id, analysis_type, user_notes, original_text, ai_feedback)
                  VALUES (?, ?, ?, ?, ?)
                  ''', (user_id, analysis_type, user_notes, case_text, ai_output))
        conn.commit()

    # Try to split AI output by section headers
    parsed = extract_sections(ai_output)
    return jsonify(parsed)

def extract_sections(response):
    def extract(section):
        pattern = rf"{section}[\s\-:]*\n(.*?)(?=\n[A-Z][a-zA-Z\s]+[\s\-:]*\n|\Z)"
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else "Not found."

    return {
        "wording": extract("General Wording Feedback"),
        "technical": extract("Technical Feedback"),
        "future": extract("Future Suggestions"),
        "flow": extract("Flow Map"),
    }

@app.route('/past/')
def past_debates():
    if 'user_id' not in session:
        return redirect('/login')

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM past_debates WHERE user_id = ?", (session['user_id'],))
        rows = c.fetchall()

    past_debates = [
        {
            "id": row[0],
            "user_id": row[1],
            "title": row[2],
            "summary": row[3],
            "date": row[4],
            "side": row[5]
        }
        for row in rows
    ]
    return render_template("past.html", debates=past_debates)


@app.route('/past/add_debate', methods=['POST'])
def add_debate():
    if 'user_id' not in session:
        return redirect('/login')

    title = request.form.get("title")
    summary = request.form.get("summary")
    date = request.form.get("date")
    side = request.form.get("side")

    if not all([title, summary, date, side]):
        flash("All fields are required.", "error")
        return redirect("/past/")

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO past_debates (user_id, title, summary, date, side) VALUES (?, ?, ?, ?, ?)",
            (session['user_id'], title, summary, date, side)
        )
        conn.commit()

    return redirect("/past/")


@app.route('/past/delete_debate/<int:debate_id>', methods=['POST'])
def delete_debate(debate_id):
    if 'user_id' not in session:
        return redirect('/login')

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # Optional: Add user_id condition to prevent deleting others’ data
        c.execute("DELETE FROM past_debates WHERE id = ? AND user_id = ?", (debate_id, session['user_id']))
        conn.commit()

    return redirect("/past/")

def generate_ai_analysis_for_speech(speech):
    """
    Calls OpenRouter GPT to generate full AI analysis for a single debate speech.
    Returns a dict with the expected keys for the analysis.html template per speech.
    """

    prompt = f"""
    You are an expert debate coach and AI analyst.

    Analyze the following debate speech transcript and metadata:
    Title: {speech['title']}
    Speaker: {speech['speaker']}
    Round: {speech['round']}
    Transcript excerpt: {speech.get('transcript_excerpt', 'N/A')}
    Previous speech for reference: {speech.get('previous_speech', 'N/A')}

    Provide a detailed, structured JSON response containing the following categories:

    1. Content Feedback:
      - argumentClarity: Comments on clarity of tags, warrants, impacts.
      - evidenceQuality: Comments on credibility, currency, relevance.
      - internalLinkChains: Comments on logical consistency and warranting.

    2. Strategic Execution:
      - argumentSelection: Comments on strategy given round context.
      - clash: How well responses answer opponent arguments.
      - depthVsBreadth: Comments on argument development depth.

    3. Style and Structure:
      - organization: Comments on speech structure and signposting.
      - timeAllocation: Comments on time spent on key arguments.
      - persuasiveness: Comments on rhetorical and logical persuasiveness.

    4. Technical Argument Evaluation:
      - droppedArguments: Arguments that were conceded or dropped.
      - ineffectiveResponses: Responses that fail to answer arguments.
      - overviewsWeighing: Quality of framing and weighing arguments.
      - useOfTheory: Proper use of theory, T-presses, K arguments.

    Return ONLY valid JSON in this exact format:

    {{
      "content": {{
        "argumentClarity": "...",
        "evidenceQuality": "...",
        "internalLinkChains": "..."
      }},
      "strategy": {{
        "argumentSelection": "...",
        "clash": "...",
        "depthVsBreadth": "..."
      }},
      "style": {{
        "organization": "...",
        "timeAllocation": "...",
        "persuasiveness": "..."
      }},
      "technical": {{
        "droppedArguments": "...",
        "ineffectiveResponses": "...",
        "overviewsWeighing": "...",
        "useOfTheory": "..."
      }}
    }}

    IMPORTANT:
    - Be concise but insightful.
    - Avoid explanations outside the JSON.
    """

    try:
        raw = call_openrouter_gpt(prompt, max_tokens=1200)  # Your wrapper for the API call
        analysis = json.loads(raw)
    except Exception as e:
        logger.exception("Failed to parse AI response: %s", e)
        # Fallback placeholder with neutral feedback
        analysis = {
            "content": {
                "argumentClarity": "Unable to generate feedback at this time.",
                "evidenceQuality": "Unable to generate feedback at this time.",
                "internalLinkChains": "Unable to generate feedback at this time."
            },
            "strategy": {
                "argumentSelection": "Unable to generate feedback at this time.",
                "clash": "Unable to generate feedback at this time.",
                "depthVsBreadth": "Unable to generate feedback at this time."
            },
            "style": {
                "organization": "Unable to generate feedback at this time.",
                "timeAllocation": "Unable to generate feedback at this time.",
                "persuasiveness": "Unable to generate feedback at this time."
            },
            "technical": {
                "droppedArguments": "Unable to generate feedback at this time.",
                "ineffectiveResponses": "Unable to generate feedback at this time.",
                "overviewsWeighing": "Unable to generate feedback at this time.",
                "useOfTheory": "Unable to generate feedback at this time."
            }
        }
    return analysis

def generate_full_round_analysis(speeches):
    """
    Takes a list of speech dicts, calls generate_ai_analysis_for_speech on each,
    and returns a list of dicts ready to feed your UI.
    """
    results = []
    for sp in speeches:
        feedback = generate_ai_analysis_for_speech(sp)
        results.append({
            "id": sp["id"],
            "name": sp["name"],
            "feedback": feedback
        })
    return results

analysis_bp = Blueprint('analysis', __name__)

@analysis_bp.route('/analysis/<int:round_id>')
def analysis_page(round_id):
    speeches = get_speeches_for_round(round_id)

    # If any speech has no feedback, call AI and save
    for speech in speeches:
        if not speech["feedback"]:
            feedback = generate_ai_analysis_for_speech(speech)
            speech["feedback"] = feedback
            save_feedback_for_speech(speech["id"], feedback)

    return render_template("analysis.html", speeches=speeches)



def save_feedback_for_speech(speech_id, feedback):
    """
    Saves the AI-generated feedback JSON to the database.
    """
    import json
    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute("""
                    UPDATE speeches
                    SET feedback_json = ?
                    WHERE id = ?
                    """, (json.dumps(feedback), speech_id))
        conn.commit()
    finally:
        conn.close()


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row  # so you can access columns by name
    return g.db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.route('/api/debate/ai/respond', methods=['POST'])
def ai_respond():
    data = request.json
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"error": "Missing prompt"}), 400

    response_text = call_openrouter_gpt(prompt)
    return jsonify({"response": response_text})

# Save debate data route
@app.route('/api/debate/save', methods=['POST'])
def save_debate():
    data = request.json
    user_id = data.get("user_id")  # Assuming you send this securely via auth/session
    title = data.get("title", "Untitled Debate")
    side = data.get("side", "Aff")
    elo = data.get("elo", 2000)
    transcript = data.get("transcript", "")
    ai_responses = data.get("ai_responses", "")
    summary = data.get("summary", "")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
                INSERT INTO debates (user_id, title, side, elo, transcript, ai_responses, summary, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, title, side, elo, transcript, ai_responses, summary, datetime.utcnow()))
    db.commit()
    return jsonify({"status": "success", "debate_id": cur.lastrowid})

# Fetch user debate history
@app.route('/api/debate/history', methods=['GET'])
def debate_history():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    db = get_db()
    debates = db.execute("SELECT * FROM debates WHERE user_id = ? ORDER BY timestamp DESC", (user_id,)).fetchall()
    debates_list = [dict(row) for row in debates]
    return jsonify({"debates": debates_list})

@app.route('/debate', methods=['GET'])
def practice_debate():
    return render_template("practice.html")

# Flowchart generation route (simple example)
@app.route('/api/debate/flowchart', methods=['POST'])
def generate_flowchart():
    """
    Accepts a JSON list of speeches with labels and text:
    [
        {"label": "1AC", "text": "..."},
        {"label": "1NC", "text": "..."},
        ...
    ]

    Returns structured JSON of argument nodes with simplistic "complexity" scores.
    """
    data = request.json
    speeches = data.get("speeches")
    if not speeches or not isinstance(speeches, list):
        return jsonify({"error": "Invalid or missing speeches data"}), 400

    # Dummy complexity scoring: length of speech text + random factor
    import random
    nodes = []
    for s in speeches:
        text_len = len(s.get("text", ""))
        complexity = max(1, min(20, text_len // 50 + random.randint(-3, 3)))
        nodes.append({
            "label": s.get("label"),
            "complexity_score": complexity,
            "text_snippet": s.get("text", "")[:100]  # first 100 chars
        })

    return jsonify({"flowchart": nodes})



if __name__ == "__main__":
    init_db()
    app.run(debug=True)
