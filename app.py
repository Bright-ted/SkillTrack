from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
import os
from dotenv import load_dotenv
from supabase import create_client, Client
import json
import csv
from io import StringIO

load_dotenv()

app = Flask(__name__)
app.secret_key = "skilltrack_secret_key" # Needed for flash messages

# --- SUPABASE SETUP ---
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
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    try:
        data = supabase.table("quizzes").select("course_id").eq("id", quiz_id).single().execute()
        course_id = data.data['course_id']
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
    if 'user_id' not in session or session['role'] != 'instructor': return redirect(url_for('role_select'))
    
    # UPDATE: Added violation_count and users(full_name) to select
    results = supabase.table("exam_results")\
        .select("score, passed, violation_count, users(full_name), quizzes!inner(title, courses!inner(title, instructor_id))")\
        .eq("quizzes.courses.instructor_id", session['user_id'])\
        .order("submitted_at", desc=True)\
        .execute()
        
    return render_template('instructor_reports.html', results=results.data)

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
    if 'user_id' not in session or session['role'] != 'student': return redirect(url_for('role_select'))
    user_id = session['user_id']
    search_query = request.args.get('q', '')

    user_data = supabase.table("users").select("points, current_badge").eq("id", user_id).single().execute()
    stats = user_data.data if user_data.data else {"points": 0, "current_badge": "Novice"}

    better_players = supabase.table("users").select("id", count="exact").gt("points", stats['points']).execute()
    rank = better_players.count + 1

    my_courses_resp = supabase.table("enrollments").select("course_id, courses(title, category, description, id)").eq("student_id", user_id).execute()
    my_courses = my_courses_resp.data
    enrolled_ids = [item['course_id'] for item in my_courses]

    query = supabase.table("courses").select("*")
    if search_query: query = query.ilike("title", f"%{search_query}%")
    if enrolled_ids: query = query.not_.in_("id", enrolled_ids)
    all_courses = query.execute().data
    
    return render_template('student_dashboard.html', user=session, stats=stats, rank=rank, my_courses=my_courses, all_courses=all_courses, search_query=search_query)

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

@app.route('/student/attempt_quiz/<quiz_id>')
def attempt_quiz(quiz_id):
    if 'user_id' not in session: return redirect(url_for('role_select'))
    
    # Optional: Re-verify eligibility here for security if desired

    quiz = supabase.table("quizzes").select("*").eq("id", quiz_id).single().execute()
    questions = supabase.table("questions").select("*").eq("quiz_id", quiz_id).order("id").execute().data
    
    for q in questions:
        if q.get('question_type') == 'MCQ':
            q['content'] = q['question_text']
            q['options'] = [
                {'id': 'A', 'content': q['option_a']}, {'id': 'B', 'content': q['option_b']},
                {'id': 'C', 'content': q['option_c']}, {'id': 'D', 'content': q['option_d']}
            ]
        else:
            q['content'] = q['question_text']
            q['options'] = []
    return render_template('take_quiz.html', quiz=quiz.data, questions=questions)

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
    if 'user_id' not in session: return redirect(url_for('role_select'))
    user_id = session['user_id']
    
    raw_answers = request.form.get('final_answers')
    violation_count = request.form.get('violation_count', 0) # <--- CAPTURE VIOLATIONS
    
    if not raw_answers: return redirect(url_for('student_dashboard'))
    student_answers = json.loads(raw_answers)

    questions = supabase.table("questions").select("*").eq("quiz_id", quiz_id).execute().data
    score, correct_count = 0, 0

    for q in questions:
        ans = student_answers.get(str(q['id']), "").strip()
        is_correct = False
        if q['question_type'] == 'MCQ' and ans == q['correct_option']: is_correct = True
        elif q['question_type'] == 'FILL_BLANK' and ans.lower() == q['correct_option'].lower(): is_correct = True
        elif q['question_type'] == 'THEORY':
             keywords = q.get('keywords', '').split(',')
             if any(k.strip().lower() in ans.lower() for k in keywords if k): is_correct = True
        
        if is_correct:
            score += 1
            correct_count += 1

    total_questions = len(questions)
    final_score = round((score / total_questions) * 100) if total_questions > 0 else 0
    is_passed = True if final_score >= 50 else False

    result = supabase.table("exam_results").insert({
        "student_id": user_id, 
        "quiz_id": quiz_id, 
        "score": final_score,         
        "total_score": total_questions, 
        "correct_count": correct_count, 
        "answers": student_answers,
        "passed": is_passed,
        "violation_count": violation_count # <--- SAVE TO DATABASE
    }).execute()
    
    curr = supabase.table("users").select("points").eq("id", user_id).single().execute().data
    points_earned = final_score + (10 if is_passed else 0)
    supabase.table("users").update({"points": (curr.get('points',0) + points_earned)}).eq("id", user_id).execute()

    return redirect(url_for('quiz_result', result_id=result.data[0]['id']))

@app.route('/student/quiz_result/<result_id>')
def quiz_result(result_id):
    if 'user_id' not in session: return redirect(url_for('role_select'))
    
    res = supabase.table("exam_results").select("*, quizzes(id, title, courses(title))").eq("id", result_id).single().execute()
    result = res.data
    questions = supabase.table("questions").select("*").eq("quiz_id", result['quizzes']['id']).execute().data
    
    review_data = []
    saved_answers = result.get('answers', {}) or {}
    
    for q in questions:
        q_text = q.get('question_text', "Question text missing")
        user_val = saved_answers.get(str(q['id']), "")
        is_correct, user_disp, corr_disp = False, "Skipped", "Unknown"
        
        if q['question_type'] == 'MCQ':
            opt_map = {'A': q.get('option_a'), 'B': q.get('option_b'), 'C': q.get('option_c'), 'D': q.get('option_d')}
            user_disp = opt_map.get(user_val, "Skipped")
            corr_disp = opt_map.get(q.get('correct_option'), "Unknown")
            is_correct = (user_val == q.get('correct_option'))
        elif q['question_type'] == 'FILL_BLANK':
            user_disp = user_val if user_val else "Skipped"
            corr_disp = q.get('correct_option')
            is_correct = (str(user_val).lower() == str(q.get('correct_option')).lower())
        elif q['question_type'] == 'THEORY':
            user_disp = user_val if user_val else "Skipped"
            keywords = q.get('keywords', '').split(',')
            if user_val and any(k.strip().lower() in str(user_val).lower() for k in keywords if k): is_correct = True
            corr_disp = f"Must contain: {q.get('keywords')}"

        review_data.append({
            "question": q_text, "user_answer": user_disp, "correct_answer": corr_disp,
            "is_correct": is_correct, "type": q['question_type']
        })

    return render_template('quiz_result.html', result=result, review=review_data)

if __name__ == '__main__':
    app.run(debug=True)