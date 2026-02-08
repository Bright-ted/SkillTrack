from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import json
import csv
from io import StringIO
import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = "skilltrack_secret_key"  # Needed for flash messages

# ==========================================
# CUSTOM JINJA2 FILTERS
# ==========================================

@app.template_filter('datetime')
def format_datetime(value, format='%b %d, %Y %I:%M %p'):
    """Format a datetime string or object."""
    if not value:
        return ""
    
    # If it's already a datetime object
    if isinstance(value, datetime.datetime):
        return value.strftime(format)
    
    # If it's a string, try to parse it
    if isinstance(value, str):
        try:
            # Try different datetime formats
            for fmt in ['%Y-%m-%dT%H:%M:%S.%f%z', 
                       '%Y-%m-%dT%H:%M:%S%z',
                       '%Y-%m-%d %H:%M:%S',
                       '%Y-%m-%d']:
                try:
                    dt = datetime.datetime.strptime(value, fmt)
                    return dt.strftime(format)
                except ValueError:
                    continue
        except Exception:
            pass
    
    # If all else fails, return the original value
    return str(value)

@app.template_filter('shortdate')
def format_shortdate(value):
    """Format date as short string."""
    return format_datetime(value, '%b %d')

@app.template_filter('timeago')
def time_ago(value):
    """Return how long ago something happened."""
    if not value:
        return ""
    
    # Parse the datetime
    if isinstance(value, str):
        try:
            dt = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except:
            return value
    elif isinstance(value, datetime.datetime):
        dt = value
    else:
        return str(value)
    
    now = datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo:
        dt = dt.astimezone(datetime.timezone.utc)
    
    diff = now - dt
    
    if diff.days > 365:
        years = diff.days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
    elif diff.days > 30:
        months = diff.days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    elif diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "just now"

# ==========================================
# SUPABASE SETUP
# ==========================================
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# ==========================================
# AUTHENTICATION & LANDING
# ==========================================

@app.route('/')
def role_select():
    return render_template('role_select.html')

@app.route('/portal/<role>')
def portal_choice(role):
    if role not in ['student', 'instructor', 'admin']:
        return redirect(url_for('role_select'))
    return render_template('auth_choice.html', role=role)

@app.route('/auth/register/<role>', methods=['GET', 'POST'])
def register(role):
    if request.method == 'GET':
        return render_template('register.html', role=role)

    try:
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        department = request.form.get('department')
        
        # 1. Create Auth User
        auth_response = supabase.auth.sign_up({"email": email, "password": password})
        if not auth_response.user: raise Exception("Registration failed.")
        user_id = auth_response.user.id

        # 2. Insert into 'users'
        supabase.table("users").insert({
            "id": user_id, "email": email, "full_name": full_name, "role": role
        }).execute()

        # 3. Insert into Profile
        if role == 'student':
            supabase.table("student_profiles").insert({
                "user_id": user_id, 
                "student_id": request.form.get('student_id'), 
                "department": department
            }).execute()
        elif role == 'instructor':
            supabase.table("instructor_profiles").insert({
                "user_id": user_id, 
                "lecturer_id": request.form.get('lecturer_id'), 
                "department": department
            }).execute()
            
        flash("Account created successfully! Please login.", "success")
        return redirect(url_for('login', role=role))

    except Exception as e:
        if "User already registered" in str(e):
             flash("You already have an account! Please login.", "warning")
             return redirect(url_for('login', role=role))
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('register', role=role))

@app.route('/auth/login/<role>', methods=['GET', 'POST'])
def login(role):
    if request.method == 'GET':
        return render_template('login.html', role=role)
    
    email = request.form.get('email')
    password = request.form.get('password')
    
    try:
        # Auth and Check Role
        auth_response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user_id = auth_response.user.id
        
        user_data = supabase.table("users").select("role, full_name").eq("id", user_id).single().execute()
        
        if user_data.data['role'] != role:
            flash(f"Wrong portal! You are a {user_data.data['role']}.", "error")
            return redirect(url_for('role_select'))
            
        session['user_id'] = user_id
        session['role'] = role
        session['full_name'] = user_data.data['full_name']
        
        if role == 'instructor':
            return redirect(url_for('instructor_dashboard')) 
        elif role == 'student':
            return redirect(url_for('student_dashboard'))

    except Exception as e:
        flash("Invalid Credentials", "error")
        return redirect(url_for('login', role=role))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('role_select'))

# ==========================================
# SHARED / DASHBOARD ROUTING
# ==========================================

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('role_select'))
    if session['role'] == 'instructor': return redirect(url_for('instructor_dashboard'))
    if session['role'] == 'student': return redirect(url_for('student_dashboard'))
    return redirect(url_for('role_select'))

# ==========================================
# INSTRUCTOR MODULES
# ==========================================

@app.route('/instructor/dashboard')
def instructor_dashboard():
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    user_id = session['user_id']

    try:
        profile = supabase.table("instructor_profiles").select("*").eq("user_id", user_id).single().execute()
        
        # Stats
        courses_query = supabase.table("courses").select("*", count="exact").eq("instructor_id", user_id).execute()
        student_query = supabase.table("student_profiles").select("*", count="exact").execute()
        
        # Calc Avg Score
        scores_data = supabase.table("exam_results").select("score").execute()
        scores = [row['score'] for row in scores_data.data]
        avg_score = round(sum(scores) / len(scores)) if len(scores) > 0 else 0

        # Recent Activity
        recent_activity = supabase.table("exam_results").select("*, users(full_name), courses(title)")\
            .order("submitted_at", desc=True).limit(3).execute()

        return render_template('instructor_dashboard.html', 
                               user=session, 
                               profile=profile.data,
                               stats={ "courses": courses_query.count, "students": student_query.count, "avg_score": avg_score, "reviews": 0 },
                               activity=recent_activity.data)
    except Exception as e:
        return f"Error loading dashboard: {e}"

@app.route('/instructor/courses')
def instructor_courses():
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    user_id = session['user_id']
    
    courses = supabase.table("courses").select("*").eq("instructor_id", user_id).order("created_at", desc=True).execute()
    profile = supabase.table("instructor_profiles").select("*").eq("user_id", user_id).single().execute()
    
    return render_template('instructor_courses.html', user=session, profile=profile.data, courses=courses.data)

@app.route('/instructor/create_course', methods=['POST'])
def create_course():
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    try:
        supabase.table("courses").insert({
            "instructor_id": session['user_id'],
            "title": request.form.get('title'),
            "description": request.form.get('description'),
            "category": request.form.get('category')
        }).execute()
        flash("Course created successfully!", "success")
    except Exception as e:
        flash(f"Error creating course: {str(e)}", "error")
    return redirect(url_for('instructor_courses'))

@app.route('/instructor/course/<course_id>')
def course_detail(course_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    course = supabase.table("courses").select("*").eq("id", course_id).single().execute()
    quizzes = supabase.table("quizzes").select("*").eq("course_id", course_id).order("created_at", desc=True).execute()
    
    return render_template('course_detail.html', user=session, course=course.data, quizzes=quizzes.data)

# --- QUIZ MANAGEMENT ---

@app.route('/instructor/create_quiz/<course_id>', methods=['POST'])
def create_quiz(course_id):
    try:
        # UPDATE: Added max_attempts to insert
        supabase.table("quizzes").insert({
            "course_id": course_id,
            "title": request.form.get('title'),
            "duration_minutes": request.form.get('duration'),
            "max_attempts": request.form.get('max_attempts', 1) 
        }).execute()
        flash("Quiz created successfully!", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
    return redirect(url_for('course_detail', course_id=course_id))

@app.route('/instructor/quiz/<quiz_id>')
def quiz_editor(quiz_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    quiz = supabase.table("quizzes").select("*, courses(title, id)").eq("id", quiz_id).single().execute()
    questions = supabase.table("questions").select("*").eq("quiz_id", quiz_id).order("id", desc=False).execute()
    return render_template('quiz_editor.html', user=session, quiz=quiz.data, questions=questions.data)

@app.route('/instructor/add_question/<quiz_id>', methods=['POST'])
def add_question(quiz_id):
    try:
        q_type = request.form.get('question_type')
        data = { "quiz_id": quiz_id, "question_text": request.form.get('question_text'), "question_type": q_type }

        if q_type == 'MCQ':
            data.update({
                "option_a": request.form.get('option_a'), "option_b": request.form.get('option_b'),
                "option_c": request.form.get('option_c'), "option_d": request.form.get('option_d'),
                "correct_option": request.form.get('correct_option')
            })
        elif q_type == 'FILL_BLANK':
            data.update({ "correct_option": request.form.get('correct_text') })
        elif q_type == 'THEORY':
            data.update({ "keywords": request.form.get('keywords') })
        
        supabase.table("questions").insert(data).execute()
        flash("Question added successfully!", "success")
    except Exception as e:
        flash(f"Error adding question: {str(e)}", "error")
    return redirect(url_for('quiz_editor', quiz_id=quiz_id))

@app.route('/instructor/edit_question/<question_id>', methods=['POST'])
def edit_question(question_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    try:
        quiz_id = request.form.get('quiz_id')
        q_type = request.form.get('question_type')
        data = { "question_text": request.form.get('question_text') }

        if q_type == 'MCQ':
            data.update({
                "option_a": request.form.get('option_a'), "option_b": request.form.get('option_b'),
                "option_c": request.form.get('option_c'), "option_d": request.form.get('option_d'),
                "correct_option": request.form.get('correct_option')
            })
        elif q_type == 'FILL_BLANK':
            data.update({ "correct_option": request.form.get('correct_text') })
        elif q_type == 'THEORY':
            data.update({ "keywords": request.form.get('keywords') })

        supabase.table("questions").update(data).eq("id", question_id).execute()
        flash("Question updated successfully!", "success")
        return redirect(url_for('quiz_editor', quiz_id=quiz_id))
    except Exception as e:
        flash(f"Error updating question: {str(e)}", "error")
        return redirect(url_for('instructor_courses'))

@app.route('/instructor/delete_question/<question_id>')
def delete_question(question_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    try:
        q_data = supabase.table("questions").select("quiz_id").eq("id", question_id).single().execute()
        quiz_id = q_data.data['quiz_id']
        supabase.table("questions").delete().eq("id", question_id).execute()
        flash("Question deleted successfully.", "success")
        return redirect(url_for('quiz_editor', quiz_id=quiz_id))
    except Exception as e:
        flash(f"Error deleting question: {str(e)}", "error")
        return redirect(url_for('instructor_courses'))

@app.route('/instructor/edit_quiz/<quiz_id>', methods=['POST'])
def edit_quiz(quiz_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    try:
        is_active = True if request.form.get('is_active') else False 
        # UPDATE: Added max_attempts to update
        supabase.table("quizzes").update({
            "title": request.form.get('title'),
            "duration_minutes": request.form.get('duration'),
            "max_attempts": request.form.get('max_attempts', 1),
            "is_active": is_active
        }).eq("id", quiz_id).execute()
        flash("Quiz settings updated!", "success")
    except Exception as e:
        flash(f"Error updating quiz: {str(e)}", "error")
    return redirect(url_for('course_detail', course_id=request.form.get('course_id')))

@app.route('/instructor/delete_quiz/<quiz_id>')
def delete_quiz(quiz_id):
    if 'user_id' not in session or session['role'] != 'instructor': 
        return redirect(url_for('role_select'))
    
    try:
        # 1. Get course_id for redirect
        data = supabase.table("quizzes").select("course_id").eq("id", quiz_id).single().execute()
        course_id = data.data['course_id']
        
    
        # Delete exam_results for this quiz
        supabase.table("exam_results").delete().eq("quiz_id", quiz_id).execute()
        
        # Delete questions for this quiz
        supabase.table("questions").delete().eq("quiz_id", quiz_id).execute()
        
        # Now delete the quiz
        supabase.table("quizzes").delete().eq("id", quiz_id).execute()
        
        flash("Quiz deleted successfully.", "success")
        return redirect(url_for('course_detail', course_id=course_id))
        
    except Exception as e:
        flash(f"Error deleting quiz: {str(e)}", "error")
        return redirect(url_for('instructor_courses'))

# ==========================================
# TRACKING & REPORTING (UPDATED)
# ==========================================

# 1. STUDENT TRACKER LIST
# --- INSTRUCTOR: STUDENT TRACKER ---

# 1. SHOW COURSE TILES (The Entry Point)
@app.route('/instructor/students')
def instructor_students():
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    # Fetch courses taught by this instructor
    courses = supabase.table("courses").select("*").eq("instructor_id", session['user_id']).execute().data
    
    return render_template('instructor_students.html', courses=courses)

# 2. SHOW STUDENTS FOR A SPECIFIC COURSE (The Detail View)
@app.route('/instructor/students/<course_id>')
def instructor_course_students(course_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    # Fetch Course Info
    course = supabase.table("courses").select("title").eq("id", course_id).single().execute().data

    # Fetch Enrollments for THIS course
    data = supabase.table("enrollments")\
        .select("student_id, users(full_name, email)")\
        .eq("course_id", course_id)\
        .execute().data
    
    # Fetch Student IDs manually
    student_uuids = [row['student_id'] for row in data]
    profiles = {}
    if student_uuids:
        p_data = supabase.table("student_profiles").select("user_id, student_id").in_("user_id", student_uuids).execute().data
        for p in p_data:
            profiles[p['user_id']] = p['student_id']

    final_list = []
    for row in data:
        row['school_id'] = profiles.get(row['student_id'], "N/A")
        final_list.append(row)
        
    return render_template('instructor_course_students.html', course=course, students=final_list)

# 2. GRADEBOOK TILES (Select Course)
@app.route('/instructor/gradebook')
def instructor_gradebook_select():
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    # Fetch courses taught by this instructor
    courses = supabase.table("courses").select("*").eq("instructor_id", session['user_id']).execute().data
    
    return render_template('instructor_gradebook_select.html', courses=courses)

# 3. CLASS LEADERBOARD (Ranked View)
@app.route('/instructor/gradebook/<course_id>')
def instructor_course_analytics(course_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))

    # Fetch Course Details
    course = supabase.table("courses").select("*").eq("id", course_id).single().execute().data

    # Fetch all results - FIXED: Added quizzes!inner(course_id)
    results = supabase.table("exam_results").select("student_id, score, passed, quizzes!inner(course_id)")\
        .eq("quizzes.course_id", course_id).execute().data
    
    # Fetch Students in this course
    enrollments = supabase.table("enrollments").select("student_id, users(full_name, email)").eq("course_id", course_id).execute().data

    # Fetch School IDs
    student_uuids = [e['student_id'] for e in enrollments]
    profiles = {}
    if student_uuids:
        p_data = supabase.table("student_profiles").select("user_id, student_id").in_("user_id", student_uuids).execute().data
        for p in p_data:
            profiles[p['user_id']] = p['student_id']

    # Calculate Ranking
    leaderboard = []
    for student in enrollments:
        uid = student['student_id']
        # Filter results for this student
        student_results = [r for r in results if r['student_id'] == uid]
        
        total_score = sum(r['score'] for r in student_results)
        count = len(student_results)
        avg_score = round(total_score / count) if count > 0 else 0
        
        leaderboard.append({
            "name": student['users']['full_name'],
            "email": student['users']['email'],
            "school_id": profiles.get(uid, "N/A"),
            "quizzes_taken": count,
            "average": avg_score,
            "total_points": total_score
        })

    # Sort by Average Score
    leaderboard.sort(key=lambda x: x['average'], reverse=True)

    return render_template('instructor_course_analytics.html', course=course, students=leaderboard)

# 4. CSV EXPORT (Matrix Gradebook)
@app.route('/instructor/export_csv/<course_id>')
def export_csv(course_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('login'))
    
    target_ca = int(request.args.get('ca', 40))

    quizzes = supabase.table("quizzes").select("id, title").eq("course_id", course_id).order("created_at").execute().data
    students = supabase.table("enrollments").select("student_id, users(full_name)").eq("course_id", course_id).execute().data
    
    # FIXED: Added quizzes!inner(course_id) here to allow filtering
    results = supabase.table("exam_results").select("student_id, quiz_id, score, quizzes!inner(course_id)").eq("quizzes.course_id", course_id).execute().data
    
    student_uuids = [s['student_id'] for s in students]
    profiles = {}
    if student_uuids:
        p_data = supabase.table("student_profiles").select("user_id, student_id").in_("user_id", student_uuids).execute().data
        for p in p_data: profiles[p['user_id']] = p['student_id']

    gradebook = {}
    for s in students:
        uid = s['student_id']
        gradebook[uid] = { 'name': s['users']['full_name'], 'id': profiles.get(uid, "N/A"), 'scores': {} }

    for r in results:
        if r['student_id'] in gradebook:
            gradebook[r['student_id']]['scores'][r['quiz_id']] = r['score']

    si = StringIO()
    cw = csv.writer(si)
    
    quiz_headers = [q['title'] for q in quizzes]
    cw.writerow(['Student Name', 'ID'] + quiz_headers + ['Average %', f'Final CA (/{target_ca})'])

    for uid, data in gradebook.items():
        row = [data['name'], data['id']]
        total = 0
        for q in quizzes:
            s = data['scores'].get(q['id'], 0)
            row.append(s)
            total += s
        
        avg = round(total / len(quizzes)) if len(quizzes) > 0 else 0
        final_ca = round((avg / 100) * target_ca)
        row.append(f"{avg}%")
        row.append(final_ca)
        cw.writerow(row)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=grades_{course_id}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# 5. FIXED REPORTS (General View)
@app.route('/instructor/reports')
def instructor_reports():
    if 'user_id' not in session or session['role'] != 'instructor': 
        return redirect(url_for('role_select'))
    
    user_id = session['user_id']
    
    try:
        # SIMPLER QUERY: Get all results for courses taught by this instructor
        # First, get all course IDs taught by this instructor
        courses = supabase.table("courses").select("id").eq("instructor_id", user_id).execute()
        course_ids = [course['id'] for course in courses.data]
        
        # If no courses, return empty
        if not course_ids:
            return render_template('instructor_reports.html', reports=[])
        
        # Get all quizzes in these courses
        quizzes = supabase.table("quizzes").select("id, title, course_id").in_("course_id", course_ids).execute()
        quiz_ids = [quiz['id'] for quiz in quizzes.data]
        
        if not quiz_ids:
            return render_template('instructor_reports.html', reports=[])
        
        # Get all exam results for these quizzes
        results = supabase.table("exam_results")\
            .select("*, users(full_name), quizzes(title)")\
            .in_("quiz_id", quiz_ids)\
            .order("submitted_at", desc=True)\
            .execute()
        
        # Format the data for the template
        reports = []
        for r in results.data:
            reports.append({
                'student_name': r['users']['full_name'] if r.get('users') else 'Unknown',
                'quiz_title': r['quizzes']['title'] if r.get('quizzes') else 'Unknown Quiz',
                'date': r['submitted_at'][:10] if r.get('submitted_at') else '',
                'score': r.get('score', 0),
                'violation_count': r.get('violation_count', 0),
                'passed': r.get('score', 0) >= 50
            })
        
        return render_template('instructor_reports.html', reports=reports)
        
    except Exception as e:
        # For debugging, you can return the error
        return f"Error loading reports: {str(e)}"

@app.route('/instructor/quiz_results/<quiz_id>')
def instructor_quiz_results(quiz_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    quiz = supabase.table("quizzes").select("title, course_id, courses(title)").eq("id", quiz_id).single().execute()
    results = supabase.table("exam_results").select("*, users(full_name, email)").eq("quiz_id", quiz_id).order("submitted_at", desc=True).execute().data
    
    grouped = {}
    for r in results:
        s_id = r['student_id']
        if s_id not in grouped:
            grouped[s_id] = {
                'student_id': s_id, 'name': r['users']['full_name'], 'email': r['users']['email'],
                'attempts': [], 'best_score': 0, 'latest_submission': r['submitted_at']
            }
        grouped[s_id]['attempts'].append(r)
        if r['score'] > grouped[s_id]['best_score']:
            grouped[s_id]['best_score'] = r['score']
            
    return render_template('instructor_quiz_results.html', quiz=quiz.data, students=grouped)

@app.route('/instructor/grade_attempt/<result_id>', methods=['GET', 'POST'])
def grade_attempt(result_id):
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))

    if request.method == 'POST':
        supabase.table("exam_results").update({
            "score": request.form.get('manual_score'),
            "feedback": request.form.get('feedback')
        }).eq("id", result_id).execute()
        flash("Grade updated successfully!", "success")
        return redirect(url_for('grade_attempt', result_id=result_id))

    data = supabase.table("exam_results").select("*, quizzes(id, title), users(full_name)").eq("id", result_id).single().execute()
    result = data.data
    q_response = supabase.table("questions").select("*").eq("quiz_id", result['quizzes']['id']).execute()
    
    review_data = []
    saved_answers = result.get('answers', {}) or {}
    
    for q in q_response.data:
        review_data.append({
            "question": q.get('question_text'),
            "user_answer": saved_answers.get(str(q['id']), ""),
            "correct_answer": q.get('correct_option'),
            "type": q['question_type']
        })
        
    return render_template('instructor_grade_attempt.html', result=result, review=review_data)

# ==========================================
# STUDENT MODULES
# ==========================================

@app.route('/student/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['role'] != 'student': 
        return redirect(url_for('role_select'))
    
    user_id = session['user_id']
    search_query = request.args.get('q', '')

    # 1. Get user stats with level and badge
    user_data = supabase.table("users").select("points, current_badge, level").eq("id", user_id).single().execute()
    stats = user_data.data if user_data.data else {
        "points": 0, 
        "current_badge": "Novice", 
        "level": 1
    }

    # 2. Calculate rank (students with more XP)
    rank_query = supabase.table("users")\
        .select("id", count="exact")\
        .gt("points", stats['points'])\
        .eq("role", "student")\
        .execute()
    
    rank = rank_query.count + 1 if rank_query.count else 1
    total_students = supabase.table("users").select("id", count="exact").eq("role", "student").execute().count
    rank_progress = int(((total_students - rank + 1) / total_students) * 100) if total_students > 0 else 0
    students_ahead = rank - 1

    # 3. Get level progression
    current_level = stats.get('level', 1)
    next_level = current_level + 1
    
    current_level_data = supabase.table("levels")\
        .select("xp_required")\
        .eq("level", current_level)\
        .single().execute().data
    
    next_level_data = supabase.table("levels")\
        .select("xp_required")\
        .eq("level", next_level)\
        .single().execute().data if next_level <= 10 else None
    
    current_xp_required = current_level_data.get('xp_required', 0)
    next_xp_required = next_level_data.get('xp_required', 0) if next_level_data else 0
    
    xp_in_current_level = stats['points'] - current_xp_required
    xp_needed_for_next = next_xp_required - current_xp_required if next_xp_required > 0 else 0
    level_progress = int((xp_in_current_level / xp_needed_for_next) * 100) if xp_needed_for_next > 0 else 100
    xp_to_next_level = xp_needed_for_next - xp_in_current_level if xp_needed_for_next > 0 else 0

    # 4. Get XP progress visualization
    all_levels = supabase.table("levels").select("*").order("level", desc=False).execute().data
    
    # 5. Get recent XP earnings
    recent_xp = supabase.table("xp_transactions")\
        .select("xp_earned, reason, created_at")\
        .eq("student_id", user_id)\
        .order("created_at", desc=True)\
        .limit(5)\
        .execute().data
    
    # 6. Calculate XP earned this week
    import datetime
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    xp_this_week_query = supabase.table("xp_transactions")\
        .select("xp_earned")\
        .eq("student_id", user_id)\
        .gte("created_at", week_ago)\
        .execute()
    
    xp_this_week = sum(item['xp_earned'] for item in xp_this_week_query.data) if xp_this_week_query.data else 0
    
    # 7. Total XP progress (toward max level)
    max_level_xp = all_levels[-1]['xp_required'] if all_levels else 4500
    total_xp_progress = int((stats['points'] / max_level_xp) * 100)

    # 8. Get enrolled courses
    my_courses_resp = supabase.table("enrollments")\
        .select("course_id, courses(title, category, description, id)")\
        .eq("student_id", user_id)\
        .execute()
    my_courses = my_courses_resp.data
    enrolled_ids = [item['course_id'] for item in my_courses]

    # 9. Get available courses
    query = supabase.table("courses").select("*")
    if search_query: 
        query = query.ilike("title", f"%{search_query}%")
    if enrolled_ids: 
        query = query.not_.in_("id", enrolled_ids)
    all_courses = query.execute().data
    
    return render_template('student_dashboard.html', 
                         user=session, 
                         stats=stats,
                         rank=rank,
                         rank_progress=rank_progress,
                         students_ahead=students_ahead,
                         level_progress=level_progress,
                         xp_to_next_level=xp_to_next_level,
                         levels=all_levels,
                         recent_xp=recent_xp,
                         xp_this_week=xp_this_week,
                         total_xp_progress=total_xp_progress,
                         my_courses=my_courses, 
                         all_courses=all_courses, 
                         search_query=search_query)

@app.route('/student/join_course/<course_id>')
def join_course(course_id):
    if 'user_id' not in session: return redirect(url_for('role_select'))
    try:
        supabase.table("enrollments").insert({ "student_id": session['user_id'], "course_id": course_id }).execute()
        flash("Successfully joined the class!", "success")
    except:
        flash("You are already enrolled.", "info")
    return redirect(url_for('student_dashboard'))

@app.route('/student/drop_course/<course_id>')
def drop_course(course_id):
    if 'user_id' not in session: return redirect(url_for('role_select'))
    try:
        supabase.table("enrollments").delete().eq("student_id", session['user_id']).eq("course_id", course_id).execute()
        flash("You have dropped the class.", "info")
    except Exception as e:
        flash(f"Error dropping course: {str(e)}", "error")
    return redirect(url_for('student_dashboard'))

@app.route('/student/grades')
def student_grades():
    if 'user_id' not in session: return redirect(url_for('role_select'))
    results = supabase.table("exam_results").select("*, quizzes(title)").eq("student_id", session['user_id']).order("submitted_at", desc=True).execute()    
    return render_template('student_grades.html', results=results.data)

@app.route('/student/course/<course_id>')
def student_course_detail(course_id):
    if 'user_id' not in session or session['role'] != 'student': return redirect(url_for('role_select'))
    course = supabase.table("courses").select("*").eq("id", course_id).single().execute()
    quizzes = supabase.table("quizzes").select("*").eq("course_id", course_id).eq("is_active", True).execute()
    return render_template('student_course_detail.html', user=session, course=course.data, quizzes=quizzes.data)

@app.route('/student/quiz_start/<quiz_id>')
def quiz_start(quiz_id):
    if 'user_id' not in session: return redirect(url_for('role_select'))
    
    quiz = supabase.table("quizzes").select("*").eq("id", quiz_id).single().execute().data
    
    # Check previous attempts
    past_results = supabase.table("exam_results").select("violation_count").eq("student_id", session['user_id']).eq("quiz_id", quiz_id).execute().data
    
    attempts_used = len(past_results)
    max_attempts = quiz.get('max_attempts', 1)
    
    # Check for cheating history
    has_cheated = any(r['violation_count'] > 0 for r in past_results)

    can_take = True
    message = ""

    if has_cheated:
        can_take = False
        message = "You are blocked from retaking this quiz due to suspicious activity in a previous attempt."
    elif attempts_used >= max_attempts:
        can_take = False
        message = f"You have used all {max_attempts} attempts allowed for this quiz."

    return render_template('student_quiz_start.html', quiz=quiz, can_take=can_take, message=message, attempts_used=attempts_used)


@app.route('/student/take_quiz/<quiz_id>')
def student_take_quiz(quiz_id):
    if 'user_id' not in session: return redirect(url_for('role_select'))
    user_id = session['user_id']

    # 1. Fetch Quiz
    try:
        quiz = supabase.table("quizzes").select("*").eq("id", quiz_id).single().execute().data
    except:
        return redirect(url_for('student_dashboard'))

    # 2. Check Attempts (Security)
    try:
        attempts = supabase.table('exam_results').select('*', count='exact').eq('quiz_id', quiz_id).eq('student_id', user_id).execute()
        if attempts.count >= int(quiz.get('max_attempts', 1)):
            flash("Max attempts reached.", "error")
            return redirect(url_for('student_dashboard'))
    except:
        pass

    # 3. Fetch Questions
    raw_questions = supabase.table("questions").select("*").eq("quiz_id", quiz_id).order("id").execute().data

    # 4. DATA FORMATTING - FIXED: Use question_text column
    formatted_questions = []
    for q in raw_questions:
        q_text = q.get('question_text', 'Question text not found')
        
        formatted_q = {
            'id': str(q['id']),  # Convert to string for JavaScript
            'text': q_text,
            'question_type': q.get('question_type', 'MCQ'),
            'options': []
        }
        
        if formatted_q['question_type'] == 'MCQ':
            formatted_q['options'] = [
                {'code': 'A', 'text': q.get('option_a', 'Option A')},
                {'code': 'B', 'text': q.get('option_b', 'Option B')},
                {'code': 'C', 'text': q.get('option_c', 'Option C')},
                {'code': 'D', 'text': q.get('option_d', 'Option D')}
            ]
        
        formatted_questions.append(formatted_q)

    return render_template('take_quiz.html', quiz=quiz, questions=formatted_questions)

@app.route('/api/save_progress', methods=['POST'])
def save_progress():
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    try:
        for q_id, val in data.get('answers', {}).items():
            supabase.table("student_answers").upsert({
                "student_id": session['user_id'], "quiz_id": data.get('quiz_id'),
                "question_id": q_id, "selected_answer": val, "updated_at": "now()"
            }, on_conflict="student_id, question_id").execute()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/student/submit_quiz/<quiz_id>', methods=['POST'])
def submit_quiz(quiz_id):
    if 'user_id' not in session: 
        return redirect(url_for('role_select'))
    
    user_id = session['user_id']

    # 1. Get violation count from form
    violation_count = int(request.form.get('violation_count', 0))
    
    # 2. Get Answers from Form
    raw_answers = request.form.get('final_answers', '{}')
    try:
        answers = json.loads(raw_answers)
    except:
        answers = {}

    # 3. Grade the Quiz
    questions = supabase.table("questions").select("*").eq("quiz_id", quiz_id).execute().data
    correct_count = 0
    total_questions = len(questions)

    for q in questions:
        q_id = str(q['id'])
        user_ans = answers.get(q_id)
        
        # Get correct answer based on question type
        correct_ans = q.get('correct_option', '')
        
        if q.get('question_type') == 'MCQ':
            if user_ans and str(user_ans).strip().upper() == str(correct_ans).strip().upper():
                correct_count += 1
                
        elif q.get('question_type') == 'FILL_BLANK':
            if user_ans and str(user_ans).strip().lower() == str(correct_ans).strip().lower():
                correct_count += 1
                
        elif q.get('question_type') == 'THEORY':
            keywords = [k.strip().lower() for k in q.get('keywords', '').split(',') if k.strip()]
            user_text = str(user_ans).lower() if user_ans else ''
            if any(keyword in user_text for keyword in keywords):
                correct_count += 1

    # Calculate percentage score
    final_score_percent = int((correct_count / total_questions * 100)) if total_questions > 0 else 0

    # 4. Save to Database
    data = {
        "student_id": user_id,
        "quiz_id": quiz_id,
        "score": final_score_percent,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "violation_count": violation_count,
        "answers": json.dumps(answers),
        "passed": final_score_percent >= 50,
        "submitted_at": "now()"
    }
    
    try:
        result = supabase.table("exam_results").insert(data).execute()
        new_result_id = result.data[0]['id']
        
        # 5. AWARD XP BASED ON PERFORMANCE
        award_student_xp(user_id, final_score_percent, quiz_id)
        
        return redirect(url_for('student_quiz_result', result_id=new_result_id))
        
    except Exception as e:
        flash(f"Error submitting quiz: {str(e)}", "error")
        return redirect(url_for('student_dashboard'))


def award_student_xp(user_id, score, quiz_id):
    """Award XP to student based on quiz performance"""
    try:
        # Get quiz difficulty (could be based on number of questions or course level)
        quiz_data = supabase.table("quizzes").select("course_id").eq("id", quiz_id).single().execute()
        course_data = supabase.table("courses").select("category").eq("id", quiz_data.data['course_id']).single().execute()
        
        # Determine difficulty multiplier
        difficulty_map = {
            "Advanced": 3,
            "Intermediate": 2,
            "Computer Science": 2,
            "Mathematics": 2,
            "Engineering": 2,
            "Business": 1,
            "General": 1
        }
        
        difficulty = difficulty_map.get(course_data.data.get('category', 'General'), 1)
        
        # Calculate XP earned
        base_xp = score  # 1 XP per percentage point
        
        # Bonus for high scores
        if score >= 90:
            bonus = 50
        elif score >= 80:
            bonus = 30
        elif score >= 70:
            bonus = 20
        elif score >= 60:
            bonus = 10
        else:
            bonus = 5
        
        total_xp = (base_xp * difficulty) + bonus
        
        # Get current XP
        user_data = supabase.table("users").select("points, level, current_badge").eq("id", user_id).single().execute()
        current_xp = user_data.data.get('points', 0)
        new_xp = current_xp + total_xp
        
        # Determine new level and badge
        level_data = supabase.table("levels").select("*").lte("xp_required", new_xp).order("level", desc=True).limit(1).single().execute()
        
        # Update user XP, level, and badge
        supabase.table("users").update({
            "points": new_xp,
            "level": level_data.data['level'],
            "current_badge": level_data.data['badge_name']
        }).eq("id", user_id).execute()
        
        # Log XP transaction (optional)
        supabase.table("xp_transactions").insert({
            "student_id": user_id,
            "quiz_id": quiz_id,
            "xp_earned": total_xp,
            "reason": f"Quiz completed: Score {score}%",
            "created_at": "now()"
        }).execute()
        
    except Exception as e:
        print(f"Error awarding XP: {str(e)}")

@app.route('/student/quiz_result/<result_id>')
def student_quiz_result(result_id):
    if 'user_id' not in session: 
        return redirect(url_for('role_select'))
    
    try:
        # Fetch result with quiz and course info
        result_data = supabase.table('exam_results')\
            .select('*, quizzes!inner(title, course_id, courses!inner(title))')\
            .eq('id', result_id)\
            .single()\
            .execute()
        result = result_data.data
        
        # Parse answers JSON
        answers_json = result.get('answers', '{}')
        if isinstance(answers_json, str):
            try:
                answers = json.loads(answers_json)
            except:
                answers = {}
        else:
            answers = answers_json
        
        # Fetch all questions for this quiz
        questions = supabase.table('questions')\
            .select('*')\
            .eq('quiz_id', result['quiz_id'])\
            .execute()\
            .data
        
        # Build report
        report = []
        for q in questions:
            q_id = str(q['id'])
            user_answer = answers.get(q_id, 'Not Answered')
            
            # Determine correctness
            is_correct = False
            correct_answer = ''
            
            if q['question_type'] == 'MCQ':
                option_map = {
                    'A': q.get('option_a'),
                    'B': q.get('option_b'),
                    'C': q.get('option_c'),
                    'D': q.get('option_d')
                }
                correct_code = q.get('correct_option', '').upper()
                correct_answer = option_map.get(correct_code, 'Unknown')
                is_correct = (user_answer.upper() == correct_code)
                
            elif q['question_type'] == 'FILL_BLANK':
                correct_answer = q.get('correct_option', '')
                is_correct = (str(user_answer).strip().lower() == str(correct_answer).strip().lower())
                
            elif q['question_type'] == 'THEORY':
                keywords = [k.strip().lower() for k in q.get('keywords', '').split(',') if k.strip()]
                user_text = str(user_answer).lower()
                correct_answer = f"Keywords: {q.get('keywords', 'None')}"
                is_correct = any(keyword in user_text for keyword in keywords) if keywords else False
            
            report.append({
                'question': q.get('question_text', 'Question not found'),
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'is_correct': is_correct
            })
        
        return render_template('quiz_result.html', result=result, report=report)
        
    except Exception as e:
        flash(f"Error loading results: {str(e)}", "error")
        return redirect(url_for('student_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)