from urllib import response
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import os
import uuid
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3

from openai import OpenAI
from dotenv import load_dotenv

# Get the API key in .env file
# dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv()
client = OpenAI()

app = Flask(__name__)


# SQLite foreign key enforcement
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)


def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))

            if role and session.get('role') != role:
                flash('Access denied', 'error')
                return redirect(url_for('index'))

            return f(*args, **kwargs)
        return wrapped
    return decorator

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'student' or 'instructor'

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(150), nullable=False)
    instructor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    section = db.Column(db.String(50))
    room = db.Column(db.String(50))

    is_archived = db.Column(db.Boolean, default=False)
    
    instructor = db.relationship('User', backref='courses_taught')

class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=True)
    posted_on = db.Column(db.DateTime, default=db.func.current_timestamp())

    course = db.relationship('Course', backref='lessons')

class Scenario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='Draft')  # Draft / Published
    type = db.Column(db.String(50))  # e.g., 'restaurant', 'bank'

    course = db.relationship('Course', backref='scenarios')

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(50))
    character = db.Column(db.String(50))
    background = db.Column(db.String(50), default='chat-bg1.png')
    created_on = db.Column(db.DateTime, default=db.func.current_timestamp())

    student = db.relationship('User', backref='chats')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    sender = db.Column(db.String(20), nullable=False)  # 'user' or 'ai'
    content = db.Column(db.Text, nullable=False)
    created_on = db.Column(db.DateTime, default=db.func.current_timestamp())

    chat = db.relationship('Chat', backref='messages')

class StudentClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)

    student = db.relationship('User', backref='enrollments')
    course = db.relationship('Course', backref='enrollments')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'course_id', name='unique_enrollment'),
    )


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user'] = user.name
            session['email'] = user.email
            session['user_id'] = user.id
            session['role'] = user.role
            if user.role == 'student':
                return redirect(url_for('student_home'))
            else:
                return redirect(url_for('instructor_home'))
        else:
            flash('Invalid email or password', 'error')

    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('fullname')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role') 

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
        else:
            new_user = User(
                name=name,
                email=email,
                password=generate_password_hash(password),
                role = request.form.get('role').lower()
            )
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully', 'success')
            return redirect(url_for('login'))
        
        if role not in ['student', 'instructor']:
            flash('Invalid role selected', 'error')
            return redirect(url_for('register'))

    return render_template('auth/register.html')

# Student Routes


@app.route('/student/home')
@login_required(role='student')
def student_home():
    courses = (
        db.session.query(Course)
        .join(StudentClass)
        .filter(StudentClass.student_id == session['user_id'])
        .filter(Course.is_archived == False)
        .all()
    )

    classes = [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "subject": c.subject,
            "instructor": c.instructor.name,
            "image": "/static/img/Korean Words.jpg"
        }
        for c in courses
    ]

    return render_template(
        'student/student-home.html',
        classes=classes
    )

@app.route("/student/join-class", methods=["POST"])
@login_required(role="student")
def join_class():
    class_code = request.form.get("class_code").strip()

    course = Course.query.filter_by(code=class_code).first()

    if not course:
        flash("Invalid class code.", "danger")
        return redirect(url_for("student_home"))

    # Prevent duplicate enrollment
    existing = StudentClass.query.filter_by(
        student_id=session["user_id"],
        course_id=course.id
    ).first()

    if existing:
        flash("You are already enrolled in this class.", "info")
        return redirect(url_for("student_class", class_code=course.code))

    enrollment = StudentClass(
        student_id=session["user_id"],
        course_id=course.id
    )

    db.session.add(enrollment)
    db.session.commit()

    flash("Successfully joined the class!", "success")
    return redirect(url_for("student_class", class_code=course.code))


@app.route("/student/class/<class_code>")
@login_required(role="student")
def student_class(class_code):
    course = Course.query.filter_by(code=class_code).first_or_404()

    enrollment = StudentClass.query.filter_by(
        student_id=session["user_id"],
        course_id=course.id
    ).first()

    if not enrollment:
        flash("You are not enrolled in this class.", "danger")
        return redirect(url_for("student_home"))

    # FETCH ALL STUDENTS ENROLLED IN THIS CLASS
    students = (
        db.session.query(User)
        .join(StudentClass, StudentClass.student_id == User.id)
        .filter(StudentClass.course_id == course.id)
        .all()
    )

    return render_template(
        "student/student-class.html",
        course=course,
        instructor=course.instructor,
        students=students
    )



@app.route("/student/lessons")
@login_required(role='student')
def student_lessons():
    enrolled_courses = (
        db.session.query(Course)
        .join(StudentClass)
        .filter(StudentClass.student_id == session['user_id'])
        .all()
    )

    active_courses = [c for c in enrolled_courses if not c.is_archived]
    archived_courses = [c for c in enrolled_courses if c.is_archived]

    courses = [
        {
            "title": course.name,
            "lessons": [lesson.title for lesson in course.lessons]
        }
        for course in active_courses
    ]

    classes = [
        {
            "code": course.code,
            "name": course.name,
            "subject": course.subject,
            "instructor": course.instructor.name
        }
        for course in active_courses
    ]

    archived_classes = [
        {
            "code": course.code,
            "name": course.name,
            "subject": course.subject,
            "instructor": course.instructor.name
        }
        for course in archived_courses
    ]

    return render_template(
        "student/student-lessons.html",
        courses=courses,
        classes=classes,
        archived_classes=archived_classes
    )


@app.route("/student/class/<class_code>/unenroll", methods=["POST"])
@login_required(role="student")
def unenroll_class(class_code):
    course = Course.query.filter_by(code=class_code).first_or_404()

    enrollment = StudentClass.query.filter_by(
        student_id=session["user_id"],
        course_id=course.id
    ).first()

    if enrollment:
        db.session.delete(enrollment)
        db.session.commit()

    flash("You have been unenrolled from the class.", "success")
    return redirect(url_for("student_home"))



@app.route('/student/exercises')
@login_required(role='student')
def student_exercises():
    return render_template('student/student-exercises.html')

@app.route('/student/practice')
@login_required(role='student')
def student_practice():
    # Fetch all chats for the logged-in student
    chats = Chat.query.filter_by(student_id=session['user_id']).order_by(Chat.created_on.desc()).all()

    return render_template(
        'student/student-practice.html',
        chats=chats
    )

@app.route("/student/chat/<chat_type>/<int:chat_id>")
@login_required(role='student')
def student_chat(chat_type, chat_id):
    chat = Chat.query.filter_by(
        id=chat_id,
        student_id=session['user_id']
    ).first_or_404()

    return render_template(
        "student/student-chat.html",
        chat=chat,
        chat_type=chat_type,
        chat_id=chat.id
    )

@app.route('/student/chat/new', methods=['POST'])
@login_required(role='student')
def create_new_chat():
    data = request.get_json()
    title = data.get('title')
    description = data.get('prompt')  # match your modal's prompt field
    difficulty = data.get('difficulty')
    character = data.get('character')

    if not title or not description or not difficulty or not character:
        return {"error": "All fields are required"}, 400

    # Make sure you have a Chat model
    new_chat = Chat(
        title=title,
        description=description,
        difficulty=difficulty,
        character=character,
        student_id=session['user_id']
    )

    db.session.add(new_chat)
    db.session.commit()

    return {'chat_id': new_chat.id}, 200

@app.route("/student/chat/new/<int:chat_id>")
@login_required(role='student')
def student_chat_new(chat_id):
    chat = Chat.query.filter_by(
        id=chat_id,
        student_id=session['user_id']
    ).first_or_404()

    return render_template(
        "student/student-chat.html",
        chat=chat,
        chat_id=chat.id,
        chat_type="new"
    )

@app.route("/student/chat/<int:chat_id>/set-background", methods=['POST'])
@login_required(role='student')
def set_chat_background(chat_id):
    chat = Chat.query.filter_by(id=chat_id, student_id=session['user_id']).first_or_404()
    data = request.get_json()
    chat.background = data.get('background', 'chat-bg1.png')
    db.session.commit()
    return jsonify({"success": True})

@app.route("/student/chat/<int:chat_id>/send", methods=["POST"])
@login_required(role="student")
def send_message(chat_id):
    chat = Chat.query.filter_by(
        id=chat_id,
        student_id=session["user_id"]
    ).first_or_404()

    data = request.get_json()
    content = data.get("message")

    if not content:
        return jsonify({"success": False}), 400

    msg = Message(
        chat_id=chat.id,
        sender="user",
        content=content
    )

    db.session.add(msg)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": {
            "sender": "user",
            "content": msg.content
        }
    })

@app.route("/api/chat", methods=["POST"])
@login_required(role="student")
def api_chat():
    data = request.get_json()

    user_message = data.get("message")
    chat_id = data.get("chat_id")

    if not user_message or not chat_id:
        return jsonify({"error": "Missing message or chat_id"}), 400

    chat = Chat.query.filter_by(
        id=chat_id,
        student_id=session["user_id"]
    ).first_or_404()

    # Save user message
    user_msg = Message(
        chat_id=chat.id,
        sender="user",
        content=user_message
    )
    db.session.add(user_msg)
    db.session.commit()

    try:
        # Build conversation history
        history = Message.query.filter_by(chat_id=chat.id).order_by(Message.created_on).all()

        messages_for_ai = []
        for m in history:
            role = "assistant" if m.sender == "ai" else "user"
            messages_for_ai.append({
                "role": role,
                "content": m.content
            })

        # Call OpenAI
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=messages_for_ai
        )

        ai_reply = response.output_text

        # Save AI reply
        ai_msg = Message(
            chat_id=chat.id,
            sender="ai",
            content=ai_reply
        )
        db.session.add(ai_msg)
        db.session.commit()

        return jsonify({"reply": ai_reply})

    except Exception as e:
        print("AI ERROR:", e)
        return jsonify({"reply": "AI error occurred."}), 500

@app.route("/student/chat/<int:chat_id>/delete", methods=["POST"])
@login_required(role="student")
def delete_chat(chat_id):
    chat = Chat.query.filter_by(
        id=chat_id,
        student_id=session['user_id']
    ).first_or_404()

    # delete messages first (foreign key safety)
    Message.query.filter_by(chat_id=chat.id).delete()

    db.session.delete(chat)
    db.session.commit()

    return jsonify({"success": True})

@app.route("/api/speech", methods=["POST"])
@login_required(role="student")
def speech_to_text():
    audio = request.files["audio"]

    with open("temp.webm", "wb") as f:
        f.write(audio.read())

    transcription = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=open("temp.webm", "rb")
    )

    return jsonify({"text": transcription.text})


@app.route("/student/profile")
@login_required(role='student')
def student_profile():
    student = {
        "name": "Student Name",
        "email": "student@email.com",
        "student_id": "2024-00123",
        "role": "Student",
        "enrolled_since": "2024",
        "courses": 4,
        "completed": 23,
        "progress": 68,
        "last_active": "2 hrs ago"
    }
    return render_template("student/student-profile.html", student=student)

@app.route("/student/settings")
@login_required(role='student')
def student_settings():
    return render_template("student/student-settings.html")





# Instructor Routes

@app.route('/instructor/home')
@login_required(role='instructor')
def instructor_home():
    courses = Course.query.filter_by(
        instructor_id=session['user_id'],
        is_archived=False
    ).all()

    classes = [
        {
            "code": c.code,
            "name": c.name,
            "subject": c.subject,
            "instructor": c.instructor.name,
            "image": "/static/img/Korean Words.jpg"
        }
        for c in courses
    ]

    return render_template('instructor/instructor-home.html', classes=classes)

@app.route('/instructor/teaching')
@login_required(role='instructor')
def instructor_teaching():
    classes = Course.query.filter_by(
        instructor_id=session['user_id'],
        is_archived=False
    ).all()

    return render_template('instructor/instructor-teaching.html', classes=classes)


@app.route('/instructor/create-class', methods=['POST'])
@login_required(role='instructor')
def create_class():
    name = request.form.get('name')
    subject = request.form.get('subject')
    section = request.form.get('section')
    room = request.form.get('room')

    if not name or not subject:
        flash('Class name and subject are required', 'error')
        return redirect(url_for('instructor_teaching'))

    # Generate a simple class code
    code = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"

    new_course = Course(
    code=code,
    name=name,
    subject=subject,
    section=section,
    room=room,
    instructor_id=session['user_id']
    ) 


    db.session.add(new_course)
    db.session.commit()

    flash('Class created successfully!', 'success')
    return redirect(url_for('instructor_teaching'))

@app.route("/instructor/class/<class_code>")
@login_required(role='instructor')
def instructor_class(class_code):
    course = Course.query.filter_by(
        code=class_code,
        instructor_id=session['user_id']
    ).first_or_404()

    lessons = [{"title": l.title, "posted": l.posted_on.strftime("%b %d, %Y")} for l in course.lessons]
    
    students = [
        {"name": e.student.name, "id": e.student.id, "status": "Active"}  # you can calculate progress/score later
        for e in course.enrollments
    ]
    
    scenarios = [
        {"id": s.id, "title": s.title, "description": s.description, "status": s.status, "type": s.type}
        for s in course.scenarios
    ]
    
    class_data = {"code": course.code, "name": course.name, "subject": course.subject, "instructor": course.instructor.name, "is_archived": course.is_archived}
    
    return render_template("instructor/instructor-class.html",
                           class_data=class_data,
                           lessons=lessons,
                           students=students,
                           teachers=[{"name": session.get("user"), "avatar": "/static/img/profile.jpg"}],
                           scenarios=scenarios)

@app.route('/instructor/students')
@login_required(role='instructor')
def instructor_students():
    students = [
        {
            "name": "Kim Ji-hoon",
            "id": "2023-00124",
            "score": 87,
            "progress": 75,
            "status": "Active",
            "last_active": "2 hours ago"
        },
        {
            "name": "Lee Min-seo",
            "id": "2023-00156",
            "score": 92,
            "progress": 90,
            "status": "Excellent",
            "last_active": "Yesterday"
        },
        {
            "name": "Park Soo-jin",
            "id": "2023-00189",
            "score": 63,
            "progress": 45,
            "status": "Needs Attention",
            "last_active": "3 days ago"
        }
    ]

    return render_template(
        'instructor/instructor-students.html',
        students=students
    )

@app.route("/instructor/archive")
@login_required(role='instructor')
def instructor_archive():
    classes = Course.query.filter_by(
        instructor_id=session['user_id'],
        is_archived=True
    ).all()

    return render_template(
        "instructor/instructor-archive.html",
        classes=classes
    )

@app.route('/instructor/class/<class_code>/archive', methods=['POST'])
@login_required(role='instructor')
def archive_class(class_code):
    course = Course.query.filter_by(
        code=class_code,
        instructor_id=session['user_id']
    ).first_or_404()

    course.is_archived = True
    db.session.commit()

    flash("Class archived successfully.", "success")
    return redirect(url_for('instructor_teaching'))

@app.route('/instructor/class/<class_code>/update', methods=['POST'])
@login_required(role='instructor')
def update_class(class_code):
    course = Course.query.filter_by(code=class_code, instructor_id=session['user_id']).first_or_404()

    # Update fields
    course.name = request.form.get('name')
    course.subject = request.form.get('subject')
    db.session.commit()

    flash("Class updated successfully.", "success")
    return redirect(url_for('instructor_class', class_code=class_code))

@app.route('/instructor/class/<class_code>/restore', methods=['POST'])
@login_required(role='instructor')
def restore_class(class_code):
    course = Course.query.filter_by(
        code=class_code,
        instructor_id=session['user_id']
    ).first_or_404()

    course.is_archived = False
    db.session.commit()

    flash("Class restored successfully.", "success")
    return redirect(url_for('instructor_archive'))

@app.route('/instructor/class/<class_code>/create-scenario', methods=['POST'])
@login_required(role='instructor')
def create_scenario(class_code):
    course = Course.query.filter_by(
        code=class_code,
        instructor_id=session['user_id']
    ).first_or_404()

    data = request.get_json()
    title = data.get('title')
    description = data.get('description')
    scenario_type = data.get('type')
    status = 'Draft'

    if not title or not scenario_type:
        return {"success": False, "message": "Title and type are required"}, 400

    new_scenario = Scenario(
        course_id=course.id,
        title=title,
        description=description,
        type=scenario_type,
        status=status
    )

    db.session.add(new_scenario)
    db.session.commit()

    return {
        "success": True,
        "scenario": {
            "title": new_scenario.title,
            "description": new_scenario.description,
            "status": new_scenario.status,
            "type": new_scenario.type
        }
    }

@app.route('/instructor/scenario/<int:scenario_id>/delete', methods=['POST'])
@login_required(role='instructor')
def delete_scenario(scenario_id):
    scenario = Scenario.query.get(scenario_id)

    if not scenario:
        return jsonify({
            "success": False,
            "message": "Scenario not found"
        }), 404

    db.session.delete(scenario)
    db.session.commit()

    return jsonify({
        "success": True
    })

@app.route('/instructor/profile')
@login_required(role='instructor')
def instructor_profile():
    return render_template('instructor/instructor-profile.html')

@app.route('/instructor/settings')
@login_required(role='instructor')
def instructor_settings():
    return render_template('instructor/instructor-settings.html')

@app.route('/logout')
def logout():
    session.clear()  # removes all session data
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))  # redirect to login page

# TEMP: test student page without logging in
@app.route('/test/student')
def test_student():
    student = User.query.filter_by(role='student').first()
    if not student:
        return "No student exists in DB", 500

    session['user'] = student.name
    session['email'] = student.email
    session['role'] = 'student'
    session['user_id'] = student.id

    return redirect(url_for('student_home'))

# TEMP: test instructor page without logging in
@app.route('/test/instructor')
def test_instructor():
    instructor = User.query.filter_by(role='instructor').first()
    if not instructor:
        return "No instructor exists in DB", 500

    session['user'] = instructor.name
    session['email'] = instructor.email
    session['role'] = 'instructor'
    session['user_id'] = instructor.id

    return redirect(url_for('instructor_home'))




if __name__ == '__main__':
    app.run(debug=True)
