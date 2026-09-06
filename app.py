import os
import uuid
import json
from calendar import monthrange
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, redirect, url_for, request,
                   flash, jsonify, send_from_directory, send_file, abort, make_response)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename
from sqlalchemy import func, or_

from models import (db, User, Student, Documentation, DocumentationCategory,
                    SupportService, FollowUpTask, Attachment,
                    DOC_CATEGORIES, SERVICE_TYPES,
                    STATUS_LABELS, STATUS_COLORS, URGENCY_LABELS, URGENCY_COLORS,
                    SERVICE_STATUS_LABELS)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'xlsx', 'xls', 'txt'}


def create_app():
    app = Flask(__name__)

    # ── Secret key (use env var in production) ────────────────────────────
    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY', 'school-counselor-secret-key-2024-rtl-hebrew')

    # ── Database ─────────────────────────────────────────────────────────
    _db_url = os.environ.get('DATABASE_URL')
    if _db_url:
        # Fix old-style postgres:// → postgresql://
        if _db_url.startswith('postgres://'):
            _db_url = _db_url.replace('postgres://', 'postgresql+psycopg2://', 1)
        elif _db_url.startswith('postgresql://') and '+psycopg2' not in _db_url:
            _db_url = _db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    elif os.environ.get('SUPABASE_DB_PASSWORD'):
        # Local development against Supabase Session Pooler.
        # Credentials come from environment variables (see .env) — never hardcode secrets here.
        from sqlalchemy.engine import URL as _DB_URL_CLS
        _db_url = _DB_URL_CLS.create(
            'postgresql+psycopg2',
            username=os.environ.get('SUPABASE_DB_USER', 'postgres.orsyquixinhvfshkoawn'),
            password=os.environ['SUPABASE_DB_PASSWORD'],
            host=os.environ.get('SUPABASE_DB_HOST', 'aws-0-eu-west-1.pooler.supabase.com'),
            port=int(os.environ.get('SUPABASE_DB_PORT', 5432)),
            database=os.environ.get('SUPABASE_DB_NAME', 'postgres'),
        )

    if _db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'connect_args': {'sslmode': 'require', 'connect_timeout': 10},
        }
        try:
            from sqlalchemy import create_engine
            create_engine(_db_url, connect_args={'sslmode': 'require', 'connect_timeout': 5}).connect().close()
        except Exception as exc:
            print(f'WARNING: could not reach the cloud database ({exc}); falling back to local SQLite '
                  f'({os.path.join(BASE_DIR, "counselor.db")}).')
            _db_url = None

    if not _db_url:
        # No cloud DB configured, or it is unreachable (e.g. paused Supabase project):
        # fall back to the local SQLite file so the app keeps working offline.
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'counselor.db')
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'יש להתחבר כדי לגשת לדף זה.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    with app.app_context():
        db.create_all()
        seed_initial_data()

    register_routes(app)
    register_context_processors(app)
    return app


def seed_initial_data():
    if User.query.count() == 0:
        admin = User(username='admin', role='admin', full_name='יועצת')
        admin.set_password('counselor2024')
        viewer = User(username='viewer', role='reader', full_name='גורם חיצוני')
        viewer.set_password('view2024')
        db.session.add_all([admin, viewer])
        db.session.commit()

    if Documentation.query.count() == 0 and Student.query.count() > 0:
        seed_sample_docs()


def seed_sample_docs():
    admin = User.query.filter_by(username='admin').first()
    students = Student.query.limit(5).all()
    if not students:
        return

    today = date.today()
    samples = [
        {
            'student': students[0],
            'date': today - timedelta(days=14),
            'summary': 'שיחה אישית עם התלמיד בעקבות דיווח של המחנכת על קשיים חברתיים וירידה בלימודים.',
            'concerns': 'הילד מדווח על בדידות בהפסקות ואי-השתתפות בשיעורים.',
            'decisions': 'נקבעה פגישת הורים לשבוע הבא. נבדקה אפשרות לשיחת תמיכה קבועה.',
            'next_steps': 'לתאם עם המחנכת מעקב שבועי. לקיים שיחה עם הורים.',
            'participants': 'תלמיד, יועצת',
            'followup_date': today + timedelta(days=7),
            'urgency': 'high',
            'categories': ['שיחה אישית עם תלמיד', 'קושי חברתי', 'מעקב יועצת'],
        },
        {
            'student': students[1] if len(students) > 1 else students[0],
            'date': today - timedelta(days=7),
            'summary': 'מפגש עם הורי התלמידה לדיון על ירידה בהישגים ובנוכחות.',
            'concerns': 'הוריה מדווחים על קשיים רגשיים בבית.',
            'decisions': 'הוחלט להפנות לטיפול רגשי דרך גפ"ן.',
            'next_steps': 'פנייה לרכזת גפ"ן לקביעת הערכה ראשונית.',
            'participants': 'הורים, יועצת',
            'followup_date': today + timedelta(days=14),
            'urgency': 'medium',
            'categories': ['מפגש עם הורים', 'קושי רגשי', 'פנייה לגורם חיצוני'],
        },
        {
            'student': students[2] if len(students) > 2 else students[0],
            'date': today - timedelta(days=3),
            'summary': 'ועדת תמיכה רב-מקצועית לדיון בצרכי התלמיד ותכנית הלימודים המותאמת.',
            'concerns': 'קשיי קריאה וכתיבה משמעותיים.',
            'decisions': 'אושר סל שירותים אישי. תינתן תמיכה בקריאה פעמיים בשבוע.',
            'next_steps': 'תיאום עם מרכזת מת"א להתחלת הטיפול.',
            'participants': 'תלמיד, הורים, מחנכת, יועצת, מרכזת מת"א',
            'followup_date': today + timedelta(days=30),
            'urgency': 'low',
            'categories': ['ועדה רב מקצועית', 'תלמיד עם סל אישי', 'טיפולים דרך מת"א'],
        },
    ]

    for s in samples:
        doc = Documentation(
            student_id=s['student'].id,
            date=s['date'],
            summary=s['summary'],
            concerns=s['concerns'],
            decisions=s['decisions'],
            next_steps=s['next_steps'],
            participants=s['participants'],
            followup_date=s['followup_date'],
            urgency=s['urgency'],
            created_by=admin.id,
        )
        db.session.add(doc)
        db.session.flush()
        for cat in s['categories']:
            db.session.add(DocumentationCategory(documentation_id=doc.id, category_name=cat))
        if s['followup_date']:
            task = FollowUpTask(
                student_id=s['student'].id,
                documentation_id=doc.id,
                due_date=s['followup_date'],
                description=f'מעקב: {s["summary"][:60]}',
                created_by=admin.id,
            )
            db.session.add(task)

    overdue_task = FollowUpTask(
        student_id=students[0].id,
        due_date=today - timedelta(days=5),
        description='מעקב על קשיים חברתיים — לבדוק שיפור',
        created_by=admin.id,
    )
    db.session.add(overdue_task)

    service_samples = [
        {'student': students[0], 'service_type': 'מעקב קבוע', 'status': 'active',
         'frequency': 'שבועי', 'responsible_person': 'יועצת', 'start_date': today - timedelta(days=30)},
        {'student': students[1] if len(students) > 1 else students[0],
         'service_type': 'גפ"ן', 'status': 'waiting',
         'frequency': 'דו-שבועי', 'responsible_person': 'רכזת גפ"ן',
         'start_date': today - timedelta(days=7)},
        {'student': students[2] if len(students) > 2 else students[0],
         'service_type': 'סל אישי', 'status': 'active',
         'frequency': 'שלוש פעמים בשבוע', 'responsible_person': 'מרכזת מת"א',
         'start_date': today - timedelta(days=60)},
    ]
    for ss in service_samples:
        svc = SupportService(
            student_id=ss['student'].id,
            service_type=ss['service_type'],
            status=ss['status'],
            frequency=ss['frequency'],
            responsible_person=ss['responsible_person'],
            start_date=ss['start_date'],
        )
        db.session.add(svc)

    db.session.commit()


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('אין לך הרשאה לבצע פעולה זו.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def register_context_processors(app):
    @app.context_processor
    def inject_globals():
        today = date.today()
        urgent_count = 0
        overdue_count = 0
        if current_user.is_authenticated:
            urgent_count = Student.query.filter_by(status='urgent').count()
            overdue_count = FollowUpTask.query.filter(
                FollowUpTask.is_completed == False,
                FollowUpTask.due_date < today,
            ).count()
        return {
            'today': today,
            'urgent_count': urgent_count,
            'overdue_count': overdue_count,
            'DOC_CATEGORIES': DOC_CATEGORIES,
            'SERVICE_TYPES': SERVICE_TYPES,
        }


def register_routes(app):

    # ── Auth ──────────────────────────────────────────────────────────────
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()
            if user and user.is_active and user.check_password(password):
                login_user(user, remember=True)
                return redirect(request.args.get('next') or url_for('dashboard'))
            flash('שם משתמש או סיסמה שגויים.', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    @app.route('/ping')
    def ping():
        return 'ok', 200

    # ── Dashboard ─────────────────────────────────────────────────────────
    @app.route('/')
    @login_required
    def dashboard():
        today = date.today()
        week_ahead = today + timedelta(days=7)

        total_students = Student.query.count()
        status_counts = dict(db.session.query(Student.status, func.count(Student.id))
                             .group_by(Student.status).all())

        service_counts = {}
        for stype in SERVICE_TYPES:
            cnt = db.session.query(func.count(SupportService.id)).filter(
                SupportService.service_type == stype,
                SupportService.status != 'finished',
            ).scalar()
            service_counts[stype] = cnt

        upcoming_tasks = (FollowUpTask.query
                          .filter(FollowUpTask.is_completed == False,
                                  FollowUpTask.due_date >= today,
                                  FollowUpTask.due_date <= week_ahead)
                          .order_by(FollowUpTask.due_date)
                          .limit(10).all())

        overdue_tasks = (FollowUpTask.query
                         .filter(FollowUpTask.is_completed == False,
                                 FollowUpTask.due_date < today)
                         .order_by(FollowUpTask.due_date)
                         .limit(10).all())

        urgent_students = (Student.query.filter_by(status='urgent')
                           .order_by(Student.updated_at.desc()).limit(10).all())

        # Chart data: docs per month (last 6 months)
        # Use date-range filtering so it works on both SQLite (local) and PostgreSQL (Supabase)
        docs_by_month = []
        for i in range(5, -1, -1):
            m = today.replace(day=1) - timedelta(days=30 * i)
            month_start = m.replace(day=1)
            month_end = month_start.replace(day=monthrange(month_start.year, month_start.month)[1])
            cnt = Documentation.query.filter(
                Documentation.date >= month_start,
                Documentation.date <= month_end,
            ).count()
            docs_by_month.append({'label': m.strftime('%m/%Y'), 'count': cnt})

        # Chart data: students per grade
        grade_counts = dict(db.session.query(Student.grade_level, func.count(Student.id))
                            .group_by(Student.grade_level).all())

        return render_template('dashboard.html',
                               total_students=total_students,
                               status_counts=status_counts,
                               service_counts=service_counts,
                               upcoming_tasks=upcoming_tasks,
                               overdue_tasks=overdue_tasks,
                               urgent_students=urgent_students,
                               docs_by_month=json.dumps(docs_by_month),
                               grade_counts=json.dumps(grade_counts),
                               status_counts_json=json.dumps(status_counts),
                               STATUS_LABELS=STATUS_LABELS,
                               SERVICE_STATUS_LABELS=SERVICE_STATUS_LABELS)

    # ── Students ──────────────────────────────────────────────────────────
    @app.route('/students')
    @login_required
    def students_list():
        q = request.args.get('q', '').strip()
        grade = request.args.get('grade', '')
        class_name = request.args.get('class', '')
        status = request.args.get('status', '')
        view = request.args.get('view', 'cards')
        page = request.args.get('page', 1, type=int)
        per_page = 48

        query = Student.query
        if q:
            query = query.filter(Student.full_name.contains(q))
        if grade:
            query = query.filter_by(grade_level=grade)
        if class_name:
            query = query.filter_by(class_name=class_name)
        if status:
            query = query.filter_by(status=status)

        pagination = query.order_by(Student.class_name, Student.full_name).paginate(
            page=page, per_page=per_page, error_out=False)
        students = pagination.items
        student_ids = [s.id for s in students]

        # 3 queries instead of N*3 queries
        doc_counts = {}
        task_counts = {}
        last_dates = {}
        if student_ids:
            doc_counts = dict(db.session.query(
                Documentation.student_id, func.count(Documentation.id)
            ).filter(Documentation.student_id.in_(student_ids)
            ).group_by(Documentation.student_id).all())

            task_counts = dict(db.session.query(
                FollowUpTask.student_id, func.count(FollowUpTask.id)
            ).filter(
                FollowUpTask.student_id.in_(student_ids),
                FollowUpTask.is_completed == False
            ).group_by(FollowUpTask.student_id).all())

            last_dates = dict(db.session.query(
                Documentation.student_id, func.max(Documentation.date)
            ).filter(Documentation.student_id.in_(student_ids)
            ).group_by(Documentation.student_id).all())

        classes = [r[0] for r in db.session.query(Student.class_name)
                   .distinct().order_by(Student.class_name).all()]
        grades = [r[0] for r in db.session.query(Student.grade_level)
                  .distinct().order_by(Student.grade_level).all()]

        return render_template('students/list.html',
                               students=students,
                               pagination=pagination,
                               doc_counts=doc_counts,
                               task_counts=task_counts,
                               last_dates=last_dates,
                               classes=classes,
                               grades=grades,
                               q=q, grade=grade,
                               class_name=class_name,
                               status=status,
                               view=view,
                               STATUS_LABELS=STATUS_LABELS,
                               STATUS_COLORS=STATUS_COLORS)

    @app.route('/students/add', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def student_add():
        classes = [r[0] for r in db.session.query(Student.class_name)
                   .distinct().order_by(Student.class_name).all()]
        if request.method == 'POST':
            student = Student(
                full_name=request.form['full_name'].strip(),
                class_name=request.form['class_name'].strip(),
                grade_level=request.form['grade_level'].strip(),
                homeroom_teacher=request.form.get('homeroom_teacher', '').strip() or None,
                parent1_name=request.form.get('parent1_name', '').strip() or None,
                parent1_phone=request.form.get('parent1_phone', '').strip() or None,
                parent2_name=request.form.get('parent2_name', '').strip() or None,
                parent2_phone=request.form.get('parent2_phone', '').strip() or None,
                gender=request.form.get('gender', '').strip() or None,
                notes=request.form.get('notes', '').strip() or None,
                status='active',
            )
            dob_str = request.form.get('dob', '').strip()
            if dob_str:
                try:
                    student.dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            db.session.add(student)
            db.session.commit()
            flash(f'התלמיד {student.full_name} נוסף בהצלחה.', 'success')
            return redirect(url_for('student_profile', student_id=student.id))
        return render_template('students/add.html', student=None, classes=classes)

    @app.route('/students/<int:student_id>')
    @login_required
    def student_profile(student_id):
        student = Student.query.get_or_404(student_id)
        docs = student.documentation.order_by(Documentation.date.desc()).all()
        services = student.support_services.order_by(SupportService.created_at.desc()).all()
        tasks = student.followup_tasks.order_by(FollowUpTask.due_date).all()
        attachments = student.attachments.order_by(Attachment.uploaded_at.desc()).all()
        return render_template('students/profile.html',
                               student=student,
                               docs=docs,
                               services=services,
                               tasks=tasks,
                               attachments=attachments,
                               STATUS_LABELS=STATUS_LABELS,
                               SERVICE_TYPES=SERVICE_TYPES,
                               today=date.today())

    @app.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def student_edit(student_id):
        student = Student.query.get_or_404(student_id)
        classes = [r[0] for r in db.session.query(Student.class_name)
                   .distinct().order_by(Student.class_name).all()]
        if request.method == 'POST':
            student.full_name = request.form['full_name'].strip()
            student.class_name = request.form['class_name'].strip()
            student.grade_level = request.form['grade_level'].strip()
            student.homeroom_teacher = request.form.get('homeroom_teacher', '').strip() or None
            student.parent1_name = request.form.get('parent1_name', '').strip() or None
            student.parent1_phone = request.form.get('parent1_phone', '').strip() or None
            student.parent2_name = request.form.get('parent2_name', '').strip() or None
            student.parent2_phone = request.form.get('parent2_phone', '').strip() or None
            student.gender = request.form.get('gender', '').strip() or None
            student.notes = request.form.get('notes', '').strip() or None
            student.status = request.form.get('status', 'active')
            dob_str = request.form.get('dob', '').strip()
            if dob_str:
                try:
                    student.dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            student.updated_at = datetime.utcnow()
            db.session.commit()
            flash('פרטי התלמיד עודכנו בהצלחה.', 'success')
            return redirect(url_for('student_profile', student_id=student.id))
        return render_template('students/add.html', student=student, classes=classes)

    # ── Excel Import ──────────────────────────────────────────────────────
    @app.route('/students/import', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def students_import():
        import tempfile

        # ── Advanced mode: show manual mapping UI ─────────────────────────
        if request.args.get('advanced') == '1' and request.method == 'GET':
            return render_template('students/import.html', step='upload')

        # ── POST: upload, auto-detect, import immediately ─────────────────
        if request.method == 'POST' and request.form.get('step') == 'upload':
            f = request.files.get('excel_file')
            if not f or not f.filename:
                flash('לא נבחר קובץ.', 'danger')
                return redirect(url_for('students_import'))

            ext = f.filename.rsplit('.', 1)[-1].lower()
            if ext not in ('xlsx', 'xls', 'csv'):
                flash('יש להעלות קובץ Excel (.xlsx / .xls) או CSV.', 'danger')
                return redirect(url_for('students_import'))

            # Save temp file
            tmp = tempfile.NamedTemporaryFile(delete=False,
                                              suffix=f'.{ext}',
                                              dir=UPLOAD_FOLDER)
            f.save(tmp.name)
            tmp_path = tmp.name

            default_class = request.form.get('default_class', '').strip()
            default_grade = request.form.get('default_grade', '').strip()

            try:
                headers, preview = _parse_excel_preview(tmp_path, ext)
                auto_map, auto_matched = _auto_detect_columns(headers)

                # Build mapping from auto-detected columns
                mapping = {
                    'first_name':    auto_map.get('col_first_name', ''),
                    'last_name':     auto_map.get('col_last_name', ''),
                    'full_name':     auto_map.get('col_full_name', ''),
                    'class_name':    auto_map.get('col_class_name', ''),
                    'grade_level':   auto_map.get('col_grade_level', ''),
                    'gender':        auto_map.get('col_gender', ''),
                    'dob':           auto_map.get('col_dob', ''),
                    'homeroom':      auto_map.get('col_homeroom', ''),
                    'parent1_name':  auto_map.get('col_parent1_name', ''),
                    'parent1_phone': auto_map.get('col_parent1_phone', ''),
                    'parent2_name':  auto_map.get('col_parent2_name', ''),
                    'parent2_phone': auto_map.get('col_parent2_phone', ''),
                }

                imported, skipped, errors, sample_ids = _do_import(
                    tmp_path, ext, mapping, default_class, default_grade
                )
            except Exception as e:
                flash(f'שגיאה בקריאת הקובץ: {e}', 'danger')
                return redirect(url_for('students_import'))
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

            # Build human-readable detected columns summary
            FIELD_LABELS = {
                'col_full_name':    'שם מלא',
                'col_first_name':   'שם פרטי',
                'col_last_name':    'שם משפחה',
                'col_class_name':   'כיתה',
                'col_grade_level':  'שכבה',
                'col_gender':       'מין',
                'col_dob':          'תאריך לידה',
                'col_homeroom':     'מחנכת',
                'col_parent1_name': 'הורה 1',
                'col_parent1_phone':'טלפון 1',
                'col_parent2_name': 'הורה 2',
                'col_parent2_phone':'טלפון 2',
            }
            detected_cols = {FIELD_LABELS[k]: v for k, v in auto_map.items()}
            sample_students = Student.query.filter(Student.id.in_(sample_ids)).all() if sample_ids else []

            return render_template('students/import.html',
                                   step='results',
                                   imported=imported,
                                   skipped=skipped,
                                   errors=errors,
                                   detected_cols=detected_cols,
                                   sample_students=sample_students)

        # ── POST: manual mapping confirm ──────────────────────────────────
        if request.method == 'POST' and request.form.get('step') == 'confirm':
            tmp_path = request.form.get('tmp_path', '')
            ext      = request.form.get('ext', 'xlsx')

            if not tmp_path or not os.path.exists(tmp_path):
                flash('הקובץ הזמני לא נמצא — נסי שוב.', 'danger')
                return redirect(url_for('students_import'))

            mapping = {
                'first_name':    request.form.get('col_first_name', ''),
                'last_name':     request.form.get('col_last_name', ''),
                'full_name':     request.form.get('col_full_name', ''),
                'class_name':    request.form.get('col_class_name', ''),
                'grade_level':   request.form.get('col_grade_level', ''),
                'gender':        request.form.get('col_gender', ''),
                'dob':           request.form.get('col_dob', ''),
                'homeroom':      request.form.get('col_homeroom', ''),
                'parent1_name':  request.form.get('col_parent1_name', ''),
                'parent1_phone': request.form.get('col_parent1_phone', ''),
                'parent2_name':  request.form.get('col_parent2_name', ''),
                'parent2_phone': request.form.get('col_parent2_phone', ''),
            }
            default_class = request.form.get('default_class', '').strip()
            default_grade = request.form.get('default_grade', '').strip()

            try:
                imported, skipped, errors, _ = _do_import(
                    tmp_path, ext, mapping, default_class, default_grade
                )
            except Exception as e:
                flash(f'שגיאה בייבוא: {e}', 'danger')
                return redirect(url_for('students_import'))
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

            flash(f'יובאו {imported} תלמידים. דולגו {skipped} כפולים.', 'success')
            return redirect(url_for('students_list'))

        # ── GET: upload form ──────────────────────────────────────────────
        return render_template('students/import.html', step='upload')

    @app.route('/students/<int:student_id>/status', methods=['POST'])
    @login_required
    @admin_required
    def student_status(student_id):
        student = Student.query.get_or_404(student_id)
        new_status = request.form.get('status')
        if new_status in ('active', 'followup', 'urgent', 'closed'):
            student.status = new_status
            student.updated_at = datetime.utcnow()
            db.session.commit()
        return jsonify({'status': student.status,
                        'label': STATUS_LABELS.get(student.status, ''),
                        'color': STATUS_COLORS.get(student.status, '')})

    # ── Documentation ──────────────────────────────────────────────────────
    @app.route('/documentation/add', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def documentation_add():
        student_id = request.args.get('student_id', type=int)
        pre_student = Student.query.get(student_id) if student_id else None
        students = Student.query.order_by(Student.class_name, Student.full_name).all()

        if request.method == 'POST':
            sid = request.form.get('student_id', type=int)
            student = Student.query.get_or_404(sid)
            date_str = request.form.get('date', '').strip()
            doc_date = date.today()
            if date_str:
                try:
                    doc_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            followup_date = None
            fup_str = request.form.get('followup_date', '').strip()
            if fup_str:
                try:
                    followup_date = datetime.strptime(fup_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            doc = Documentation(
                student_id=sid,
                date=doc_date,
                summary=request.form.get('summary', '').strip(),
                concerns=request.form.get('concerns', '').strip() or None,
                decisions=request.form.get('decisions', '').strip() or None,
                next_steps=request.form.get('next_steps', '').strip() or None,
                participants=request.form.get('participants', '').strip() or None,
                followup_date=followup_date,
                urgency=request.form.get('urgency', 'low'),
                created_by=current_user.id,
            )
            db.session.add(doc)
            db.session.flush()

            selected_cats = request.form.getlist('categories')
            for cat in selected_cats:
                if cat in DOC_CATEGORIES:
                    db.session.add(DocumentationCategory(
                        documentation_id=doc.id, category_name=cat))

            if followup_date:
                summary_short = doc.summary[:60] + ('...' if len(doc.summary) > 60 else '')
                task = FollowUpTask(
                    student_id=sid,
                    documentation_id=doc.id,
                    due_date=followup_date,
                    description=f'מעקב: {summary_short}',
                    created_by=current_user.id,
                )
                db.session.add(task)
                if student.status == 'active':
                    student.status = 'followup'

            if doc.urgency == 'high':
                student.status = 'urgent'
            student.updated_at = datetime.utcnow()

            db.session.commit()

            # Handle file upload
            if 'file' in request.files:
                file = request.files['file']
                if file and file.filename and allowed_file(file.filename):
                    orig_name = file.filename
                    stored_name = f"{uuid.uuid4().hex}_{secure_filename(orig_name)}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
                    file.save(filepath)
                    att = Attachment(
                        documentation_id=doc.id,
                        student_id=sid,
                        filename=stored_name,
                        original_name=orig_name,
                        file_size=os.path.getsize(filepath),
                        mime_type=file.content_type,
                        uploaded_by=current_user.id,
                    )
                    db.session.add(att)
                    db.session.commit()

            flash('התיעוד נשמר בהצלחה.', 'success')
            return redirect(url_for('student_profile', student_id=sid) + '#documentation')

        return render_template('documentation/add.html',
                               pre_student=pre_student,
                               students=students,
                               doc=None,
                               DOC_CATEGORIES=DOC_CATEGORIES)

    @app.route('/documentation/<int:doc_id>')
    @login_required
    def documentation_view(doc_id):
        doc = Documentation.query.get_or_404(doc_id)
        return render_template('documentation/view.html', doc=doc,
                               URGENCY_LABELS=URGENCY_LABELS,
                               URGENCY_COLORS=URGENCY_COLORS)

    @app.route('/documentation/<int:doc_id>/edit', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def documentation_edit(doc_id):
        doc = Documentation.query.get_or_404(doc_id)
        students = Student.query.order_by(Student.class_name, Student.full_name).all()
        if request.method == 'POST':
            date_str = request.form.get('date', '').strip()
            if date_str:
                try:
                    doc.date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            doc.summary = request.form.get('summary', '').strip()
            doc.concerns = request.form.get('concerns', '').strip() or None
            doc.decisions = request.form.get('decisions', '').strip() or None
            doc.next_steps = request.form.get('next_steps', '').strip() or None
            doc.participants = request.form.get('participants', '').strip() or None
            doc.urgency = request.form.get('urgency', 'low')

            fup_str = request.form.get('followup_date', '').strip()
            doc.followup_date = None
            if fup_str:
                try:
                    doc.followup_date = datetime.strptime(fup_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            DocumentationCategory.query.filter_by(documentation_id=doc.id).delete()
            for cat in request.form.getlist('categories'):
                if cat in DOC_CATEGORIES:
                    db.session.add(DocumentationCategory(documentation_id=doc.id, category_name=cat))

            doc.updated_at = datetime.utcnow()
            db.session.commit()
            flash('התיעוד עודכן בהצלחה.', 'success')
            return redirect(url_for('student_profile', student_id=doc.student_id) + '#documentation')
        return render_template('documentation/add.html',
                               pre_student=doc.student,
                               students=students,
                               doc=doc,
                               DOC_CATEGORIES=DOC_CATEGORIES)

    # ── Support Services ───────────────────────────────────────────────────
    @app.route('/services')
    @login_required
    def services_overview():
        stype = request.args.get('type', '')
        status_filter = request.args.get('status', '')
        query = SupportService.query
        if stype:
            query = query.filter_by(service_type=stype)
        if status_filter:
            query = query.filter_by(status=status_filter)
        services = query.order_by(SupportService.service_type, SupportService.status).all()
        type_counts = {}
        for st in SERVICE_TYPES:
            type_counts[st] = SupportService.query.filter(
                SupportService.service_type == st,
                SupportService.status != 'finished'
            ).count()
        return render_template('services.html',
                               services=services,
                               type_counts=type_counts,
                               SERVICE_TYPES=SERVICE_TYPES,
                               SERVICE_STATUS_LABELS=SERVICE_STATUS_LABELS,
                               stype=stype,
                               status_filter=status_filter)

    @app.route('/services/add', methods=['POST'])
    @login_required
    @admin_required
    def service_add():
        student_id = request.form.get('student_id', type=int)
        student = Student.query.get_or_404(student_id)
        start_str = request.form.get('start_date', '').strip()
        start_date = None
        if start_str:
            try:
                start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        svc = SupportService(
            student_id=student_id,
            service_type=request.form.get('service_type', ''),
            start_date=start_date,
            responsible_person=request.form.get('responsible_person', '').strip() or None,
            frequency=request.form.get('frequency', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
            status=request.form.get('status', 'active'),
        )
        db.session.add(svc)
        db.session.commit()
        flash('השירות נוסף בהצלחה.', 'success')
        return redirect(url_for('student_profile', student_id=student_id) + '#services')

    @app.route('/services/<int:svc_id>/status', methods=['POST'])
    @login_required
    @admin_required
    def service_status(svc_id):
        svc = SupportService.query.get_or_404(svc_id)
        new_status = request.form.get('status')
        if new_status in ('active', 'waiting', 'finished'):
            svc.status = new_status
            db.session.commit()
        return jsonify({'status': svc.status, 'label': SERVICE_STATUS_LABELS.get(svc.status, '')})

    @app.route('/services/<int:svc_id>/edit', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def service_edit(svc_id):
        svc = SupportService.query.get_or_404(svc_id)
        if request.method == 'POST':
            svc.service_type = request.form.get('service_type', svc.service_type)
            svc.responsible_person = request.form.get('responsible_person', '').strip() or None
            svc.frequency = request.form.get('frequency', '').strip() or None
            svc.notes = request.form.get('notes', '').strip() or None
            new_status = request.form.get('status', svc.status)
            if new_status in ('active', 'waiting', 'finished'):
                svc.status = new_status
            start_str = request.form.get('start_date', '').strip()
            end_str = request.form.get('end_date', '').strip()
            if start_str:
                try:
                    svc.start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            if end_str:
                try:
                    svc.end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            db.session.commit()
            flash('השירות עודכן בהצלחה.', 'success')
            return redirect(url_for('student_profile', student_id=svc.student_id) + '#services')
        return render_template('service_edit.html', svc=svc,
                               SERVICE_TYPES=SERVICE_TYPES,
                               SERVICE_STATUS_LABELS=SERVICE_STATUS_LABELS)

    @app.route('/services/<int:svc_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def service_delete(svc_id):
        svc = SupportService.query.get_or_404(svc_id)
        student_id = svc.student_id
        db.session.delete(svc)
        db.session.commit()
        flash('השירות נמחק בהצלחה.', 'success')
        return redirect(url_for('student_profile', student_id=student_id) + '#services')

    @app.route('/documentation/<int:doc_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def documentation_delete(doc_id):
        doc = Documentation.query.get_or_404(doc_id)
        student_id = doc.student_id
        FollowUpTask.query.filter_by(documentation_id=doc_id).delete()
        Attachment.query.filter_by(documentation_id=doc_id).delete()
        DocumentationCategory.query.filter_by(documentation_id=doc_id).delete()
        db.session.delete(doc)
        db.session.commit()
        flash('התיעוד נמחק בהצלחה.', 'success')
        return redirect(url_for('student_profile', student_id=student_id) + '#documentation')

    @app.route('/students/<int:student_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def student_delete(student_id):
        student = Student.query.get_or_404(student_id)
        # Delete all related data first
        for doc in student.documentation:
            FollowUpTask.query.filter_by(documentation_id=doc.id).delete()
            Attachment.query.filter_by(documentation_id=doc.id).delete()
            DocumentationCategory.query.filter_by(documentation_id=doc.id).delete()
            db.session.delete(doc)
        SupportService.query.filter_by(student_id=student_id).delete()
        FollowUpTask.query.filter_by(student_id=student_id).delete()
        Attachment.query.filter_by(student_id=student_id).delete()
        db.session.delete(student)
        db.session.commit()
        flash('התלמיד נמחק מהמערכת.', 'success')
        return redirect(url_for('students_list'))

    @app.route('/students/<int:student_id>/print')
    @login_required
    def student_print(student_id):
        student = Student.query.get_or_404(student_id)
        docs = (Documentation.query
                .filter_by(student_id=student_id)
                .order_by(Documentation.date.desc()).all())
        services = (SupportService.query
                    .filter_by(student_id=student_id)
                    .order_by(SupportService.start_date.desc()).all())
        tasks = (FollowUpTask.query
                 .filter_by(student_id=student_id)
                 .order_by(FollowUpTask.due_date).all())
        return render_template('students/print.html',
                               student=student, docs=docs,
                               services=services, tasks=tasks,
                               now=datetime.now())

    @app.route('/students/<int:student_id>/export-pdf')
    @login_required
    def student_export_pdf(student_id):
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, HRFlowable, KeepTogether)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        student = Student.query.get_or_404(student_id)
        docs = (Documentation.query
                .filter_by(student_id=student_id)
                .order_by(Documentation.date.desc()).all())
        services = (SupportService.query
                    .filter_by(student_id=student_id)
                    .order_by(SupportService.start_date.desc()).all())
        tasks = (FollowUpTask.query
                 .filter_by(student_id=student_id)
                 .filter_by(is_completed=False)
                 .order_by(FollowUpTask.due_date).all())

        # Register Windows Arial font (supports Hebrew & Arabic)
        FONT_NAME = 'Arial'
        FONT_BOLD = 'Arial-Bold'
        font_registered = False
        for font_path, bold_path in [
            (r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf'),
            (r'C:\Windows\Fonts\ARIAL.TTF', r'C:\Windows\Fonts\ARIALBD.TTF'),
        ]:
            if os.path.exists(font_path) and os.path.exists(bold_path):
                try:
                    pdfmetrics.registerFont(TTFont(FONT_NAME, font_path))
                    pdfmetrics.registerFont(TTFont(FONT_BOLD, bold_path))
                    font_registered = True
                    break
                except Exception:
                    pass
        if not font_registered:
            FONT_NAME = 'Helvetica'
            FONT_BOLD = 'Helvetica-Bold'

        # RTL helper — use python-bidi if available, else reverse words
        def rtl(text):
            if not text:
                return ''
            text = str(text)
            try:
                from bidi.algorithm import get_display
                try:
                    import arabic_reshaper
                    text = arabic_reshaper.reshape(text)
                except ImportError:
                    pass
                return get_display(text)
            except ImportError:
                # Simple fallback: reverse the word order for RTL display
                return ' '.join(reversed(text.split()))

        def fmt_date(d):
            return d.strftime('%d/%m/%Y') if d else '—'

        # Colours
        PRIMARY = colors.HexColor('#2B6CB0')
        ACCENT  = colors.HexColor('#276749')
        LIGHT   = colors.HexColor('#EBF4FF')
        GRAY    = colors.HexColor('#718096')
        RED     = colors.HexColor('#C53030')
        ORANGE  = colors.HexColor('#C05621')

        def style(font=FONT_NAME, size=10, bold=False, color=colors.black,
                  align='RIGHT', leading=None):
            return ParagraphStyle(
                name='_',
                fontName=FONT_BOLD if bold else FONT_NAME,
                fontSize=size,
                textColor=color,
                alignment={'RIGHT': 2, 'LEFT': 0, 'CENTER': 1}.get(align, 2),
                leading=leading or size * 1.4,
                wordWrap='RTL',
            )

        buf = BytesIO()
        pdf_doc = SimpleDocTemplate(buf, pagesize=A4,
                                    rightMargin=2*cm, leftMargin=2*cm,
                                    topMargin=2*cm, bottomMargin=2*cm,
                                    title=student.full_name)
        story = []
        W = A4[0] - 4*cm  # usable width

        # ── Header ──────────────────────────────────────────────────────────
        story.append(Paragraph(rtl('מערכת ייעוץ חינוכי — תיק תלמיד'), style(size=9, color=GRAY)))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(rtl(student.full_name), style(size=18, bold=True, color=PRIMARY)))
        story.append(Spacer(1, 0.2*cm))

        meta_parts = [student.class_name or '']
        if student.grade_level:
            meta_parts.append(f'שכבה {student.grade_level}')
        if student.gender:
            meta_parts.append('זכר' if student.gender == 'ז' else 'נקבה')
        story.append(Paragraph(rtl(' | '.join(p for p in meta_parts if p)),
                               style(size=11, color=GRAY)))
        story.append(Spacer(1, 0.15*cm))
        story.append(HRFlowable(width=W, color=PRIMARY, thickness=2))
        story.append(Spacer(1, 0.4*cm))

        # ── Personal Details Table ────────────────────────────────────────
        story.append(Paragraph(rtl('פרטים אישיים'), style(size=13, bold=True, color=PRIMARY)))
        story.append(Spacer(1, 0.2*cm))

        def detail_row(label, value):
            return [Paragraph(rtl(str(value) if value else '—'), style(size=10)),
                    Paragraph(rtl(label), style(size=10, bold=True, color=GRAY))]

        detail_data = [
            detail_row('תאריך לידה', fmt_date(student.dob)),
            detail_row('כיתה', student.class_name),
            detail_row('מחנך/ת', student.homeroom_teacher or '—'),
            detail_row('הורה 1', f"{student.parent1_name or ''}  {student.parent1_phone or ''}".strip() or '—'),
            detail_row('הורה 2', f"{student.parent2_name or ''}  {student.parent2_phone or ''}".strip() or '—'),
            detail_row('סטטוס', STATUS_LABELS.get(student.status, student.status)),
        ]
        tbl = Table(detail_data, colWidths=[W*0.6, W*0.4])
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.white),
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, LIGHT]),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.5*cm))

        # ── Documentation ────────────────────────────────────────────────
        story.append(HRFlowable(width=W, color=colors.HexColor('#E2E8F0'), thickness=0.5))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(rtl(f'תיעוד ({len(docs)} רשומות)'),
                               style(size=13, bold=True, color=PRIMARY)))
        story.append(Spacer(1, 0.3*cm))

        if docs:
            for doc in docs:
                urg_color = {'high': RED, 'medium': ORANGE, 'low': ACCENT}.get(doc.urgency, GRAY)
                cats = ', '.join(c.category_name for c in doc.categories) if doc.categories else ''
                block = []
                block.append(Paragraph(
                    rtl(f'{fmt_date(doc.date)}  |  {URGENCY_LABELS.get(doc.urgency, "")}'),
                    style(size=9, color=urg_color, bold=True)))
                if cats:
                    block.append(Paragraph(rtl(cats), style(size=9, color=GRAY)))
                if doc.summary:
                    block.append(Spacer(1, 0.1*cm))
                    block.append(Paragraph(rtl(doc.summary), style(size=10)))
                if doc.concerns:
                    block.append(Paragraph(rtl(f'קשיים: {doc.concerns}'), style(size=9, color=GRAY)))
                if doc.decisions:
                    block.append(Paragraph(rtl(f'החלטות: {doc.decisions}'), style(size=9, color=GRAY)))
                if doc.next_steps:
                    block.append(Paragraph(rtl(f'צעדים הבאים: {doc.next_steps}'), style(size=9, color=GRAY)))
                if doc.followup_date:
                    block.append(Paragraph(rtl(f'מעקב: {fmt_date(doc.followup_date)}'),
                                           style(size=9, color=ACCENT)))
                story.append(KeepTogether(block))
                story.append(HRFlowable(width=W, color=colors.HexColor('#E2E8F0'), thickness=0.3))
                story.append(Spacer(1, 0.15*cm))
        else:
            story.append(Paragraph(rtl('אין תיעוד.'), style(size=10, color=GRAY)))

        story.append(Spacer(1, 0.4*cm))

        # ── Support Services ─────────────────────────────────────────────
        story.append(HRFlowable(width=W, color=colors.HexColor('#E2E8F0'), thickness=0.5))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph(rtl(f'שירותי תמיכה ({len(services)})'),
                               style(size=13, bold=True, color=ACCENT)))
        story.append(Spacer(1, 0.2*cm))

        if services:
            svc_header = [Paragraph(rtl(h), style(size=9, bold=True, color=colors.white))
                          for h in ['סטטוס', 'תאריך', 'אחראי/ת', 'תדירות', 'סוג שירות']]
            svc_rows = [svc_header]
            for svc in services:
                svc_rows.append([
                    Paragraph(rtl(SERVICE_STATUS_LABELS.get(svc.status, '')), style(size=9)),
                    Paragraph(rtl(fmt_date(svc.start_date)), style(size=9)),
                    Paragraph(rtl(svc.responsible_person or '—'), style(size=9)),
                    Paragraph(rtl(svc.frequency or '—'), style(size=9)),
                    Paragraph(rtl(svc.service_type), style(size=10, bold=True)),
                ])
            svc_tbl = Table(svc_rows, colWidths=[W*0.12, W*0.15, W*0.2, W*0.15, W*0.38])
            svc_tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), ACCENT),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT]),
                ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#E2E8F0')),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
            ]))
            story.append(svc_tbl)
        else:
            story.append(Paragraph(rtl('אין שירותי תמיכה.'), style(size=10, color=GRAY)))

        story.append(Spacer(1, 0.4*cm))

        # ── Open Tasks ───────────────────────────────────────────────────
        if tasks:
            story.append(HRFlowable(width=W, color=colors.HexColor('#E2E8F0'), thickness=0.5))
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph(rtl(f'משימות פתוחות ({len(tasks)})'),
                                   style(size=13, bold=True, color=ORANGE)))
            story.append(Spacer(1, 0.2*cm))
            today = date.today()
            for task in tasks:
                overdue = task.due_date < today
                c = RED if overdue else colors.black
                prefix = 'באיחור! ' if overdue else ''
                story.append(Paragraph(
                    rtl(f'{prefix}{task.description}  —  {fmt_date(task.due_date)}'),
                    style(size=10, color=c)))
            story.append(Spacer(1, 0.3*cm))

        # ── Footer ───────────────────────────────────────────────────────
        story.append(Spacer(1, 0.5*cm))
        story.append(HRFlowable(width=W, color=GRAY, thickness=0.5))
        story.append(Spacer(1, 0.1*cm))
        story.append(Paragraph(
            rtl(f'הופק בתאריך {date.today().strftime("%d/%m/%Y")} | מערכת ייעוץ חינוכי'),
            style(size=8, color=GRAY)))

        pdf_doc.build(story)
        buf.seek(0)
        safe_name = ''.join(c for c in student.full_name if c.isalnum() or c in ' _-')
        filename = f"תיק_תלמיד_{safe_name}_{student.id}.pdf"
        response = make_response(buf.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="student_{student.id}.pdf"'
        return response

    # ── Reminders / Tasks ──────────────────────────────────────────────────
    @app.route('/reminders')
    @login_required
    def reminders():
        today = date.today()
        week_ahead = today + timedelta(days=7)

        overdue = (FollowUpTask.query
                   .filter(FollowUpTask.is_completed == False,
                           FollowUpTask.due_date < today)
                   .order_by(FollowUpTask.due_date).all())

        upcoming = (FollowUpTask.query
                    .filter(FollowUpTask.is_completed == False,
                            FollowUpTask.due_date >= today,
                            FollowUpTask.due_date <= week_ahead)
                    .order_by(FollowUpTask.due_date).all())

        later = (FollowUpTask.query
                 .filter(FollowUpTask.is_completed == False,
                         FollowUpTask.due_date > week_ahead)
                 .order_by(FollowUpTask.due_date).limit(30).all())

        completed = (FollowUpTask.query
                     .filter(FollowUpTask.is_completed == True)
                     .order_by(FollowUpTask.completed_at.desc()).limit(20).all())

        students = Student.query.order_by(Student.class_name, Student.full_name).all()
        return render_template('reminders.html',
                               overdue=overdue,
                               upcoming=upcoming,
                               later=later,
                               completed=completed,
                               students=students,
                               today=today)

    @app.route('/reminders/<int:task_id>/complete', methods=['POST'])
    @login_required
    def task_complete(task_id):
        task = FollowUpTask.query.get_or_404(task_id)
        task.is_completed = True
        task.completed_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True})

    @app.route('/reminders/add', methods=['POST'])
    @login_required
    @admin_required
    def task_add():
        student_id = request.form.get('student_id', type=int)
        Student.query.get_or_404(student_id)
        due_str = request.form.get('due_date', '').strip()
        due_date = date.today() + timedelta(days=7)
        if due_str:
            try:
                due_date = datetime.strptime(due_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        task = FollowUpTask(
            student_id=student_id,
            due_date=due_date,
            description=request.form.get('description', '').strip(),
            created_by=current_user.id,
        )
        db.session.add(task)
        db.session.commit()
        flash('המשימה נוספה בהצלחה.', 'success')
        return redirect(request.referrer or url_for('reminders'))

    # ── Reports ────────────────────────────────────────────────────────────
    @app.route('/reports')
    @login_required
    def reports():
        grade = request.args.get('grade', '')
        class_name = request.args.get('class', '')
        status = request.args.get('status', '')
        svc_type = request.args.get('service', '')
        has_open_tasks = request.args.get('open_tasks', '')
        searched = any([grade, class_name, status, svc_type, has_open_tasks])

        students = []
        doc_counts = {}
        task_counts = {}
        last_dates = {}
        svc_map = {}

        if searched:
            students = _filtered_students(request.args)
            ids = [s.id for s in students]
            if ids:
                doc_counts = dict(db.session.query(
                    Documentation.student_id, func.count(Documentation.id)
                ).filter(Documentation.student_id.in_(ids)
                ).group_by(Documentation.student_id).all())

                task_counts = dict(db.session.query(
                    FollowUpTask.student_id, func.count(FollowUpTask.id)
                ).filter(
                    FollowUpTask.student_id.in_(ids),
                    FollowUpTask.is_completed == False
                ).group_by(FollowUpTask.student_id).all())

                last_dates = dict(db.session.query(
                    Documentation.student_id, func.max(Documentation.date)
                ).filter(Documentation.student_id.in_(ids)
                ).group_by(Documentation.student_id).all())

                svcs = SupportService.query.filter(
                    SupportService.student_id.in_(ids),
                    SupportService.status == 'active'
                ).all()
                for svc in svcs:
                    svc_map.setdefault(svc.student_id, []).append(svc.service_type)

        classes = [r[0] for r in db.session.query(Student.class_name)
                   .distinct().order_by(Student.class_name).all()]
        grades = [r[0] for r in db.session.query(Student.grade_level)
                  .distinct().order_by(Student.grade_level).all()]

        return render_template('reports.html',
                               students=students,
                               searched=searched,
                               doc_counts=doc_counts,
                               task_counts=task_counts,
                               last_dates=last_dates,
                               svc_map=svc_map,
                               classes=classes,
                               grades=grades,
                               SERVICE_TYPES=SERVICE_TYPES,
                               STATUS_LABELS=STATUS_LABELS,
                               params=request.args)

    @app.route('/reports/export')
    @login_required
    def reports_export():
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            flash('ספריית openpyxl אינה מותקנת.', 'danger')
            return redirect(url_for('reports'))

        students = _filtered_students(request.args)

        wb = Workbook()
        ws = wb.active
        ws.title = 'דוח תלמידים'
        ws.sheet_view.rightToLeft = True

        headers = ['שם תלמיד', 'כיתה', 'שכבה', 'מגדר', 'סטטוס', 'מחנך/ת',
                   'טלפון הורה 1', 'טלפון הורה 2', 'תיעודים', 'משימות פתוחות', 'תאריך תיעוד אחרון']
        header_fill = PatternFill(start_color='2B6CB0', end_color='2B6CB0', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF', size=11)
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='right')

        ids = [s.id for s in students]
        xdoc_counts = dict(db.session.query(Documentation.student_id, func.count(Documentation.id)).filter(Documentation.student_id.in_(ids)).group_by(Documentation.student_id).all()) if ids else {}
        xtask_counts = dict(db.session.query(FollowUpTask.student_id, func.count(FollowUpTask.id)).filter(FollowUpTask.student_id.in_(ids), FollowUpTask.is_completed == False).group_by(FollowUpTask.student_id).all()) if ids else {}
        xlast_dates = dict(db.session.query(Documentation.student_id, func.max(Documentation.date)).filter(Documentation.student_id.in_(ids)).group_by(Documentation.student_id).all()) if ids else {}

        for row, s in enumerate(students, 2):
            last_doc = xlast_dates.get(s.id)
            ws.cell(row=row, column=1, value=s.full_name)
            ws.cell(row=row, column=2, value=s.class_name)
            ws.cell(row=row, column=3, value=s.grade_level)
            ws.cell(row=row, column=4, value=s.gender or '')
            ws.cell(row=row, column=5, value=STATUS_LABELS.get(s.status, s.status))
            ws.cell(row=row, column=6, value=s.homeroom_teacher or '')
            ws.cell(row=row, column=7, value=s.parent1_phone or '')
            ws.cell(row=row, column=8, value=s.parent2_phone or '')
            ws.cell(row=row, column=9, value=xdoc_counts.get(s.id, 0))
            ws.cell(row=row, column=10, value=xtask_counts.get(s.id, 0))
            ws.cell(row=row, column=11, value=last_doc.strftime('%d/%m/%Y') if last_doc else '')
            for col in range(1, 12):
                ws.cell(row=row, column=col).alignment = Alignment(horizontal='right')

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        import io
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = make_response(buf.read())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = 'attachment; filename=report.xlsx'
        return response

    @app.route('/reports/export-pdf')
    @login_required
    def reports_export_pdf():
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib import colors
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError:
            flash('ספריית reportlab אינה מותקנת.', 'danger')
            return redirect(url_for('reports'))

        import io
        students = _filtered_students(request.args)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                rightMargin=40, leftMargin=40,
                                topMargin=40, bottomMargin=40)

        styles = getSampleStyleSheet()
        story = []

        title_style = styles['Title']
        title = Paragraph('דוח תלמידים', title_style)
        story.append(title)
        story.append(Spacer(1, 12))
        story.append(Paragraph(f'תאריך: {date.today().strftime("%d/%m/%Y")}  |  סה"כ תלמידים: {len(students)}', styles['Normal']))
        story.append(Spacer(1, 20))

        pids = [s.id for s in students]
        pdoc_counts = dict(db.session.query(Documentation.student_id, func.count(Documentation.id)).filter(Documentation.student_id.in_(pids)).group_by(Documentation.student_id).all()) if pids else {}
        ptask_counts = dict(db.session.query(FollowUpTask.student_id, func.count(FollowUpTask.id)).filter(FollowUpTask.student_id.in_(pids), FollowUpTask.is_completed == False).group_by(FollowUpTask.student_id).all()) if pids else {}

        data = [['שם תלמיד', 'כיתה', 'סטטוס', 'תיעודים', 'משימות פתוחות']]
        for s in students:
            data.append([
                s.full_name,
                s.class_name,
                STATUS_LABELS.get(s.status, s.status),
                str(pdoc_counts.get(s.id, 0)),
                str(ptask_counts.get(s.id, 0)),
            ])

        table = Table(data, colWidths=[200, 60, 80, 70, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2B6CB0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(table)

        doc.build(story)
        buf.seek(0)
        response = make_response(buf.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'attachment; filename=report.pdf'
        return response

    def _filtered_students(args):
        grade = args.get('grade', '')
        class_name = args.get('class', '')
        status = args.get('status', '')
        svc_type = args.get('service', '')
        has_open_tasks = args.get('open_tasks', '')

        query = Student.query
        if grade:
            query = query.filter_by(grade_level=grade)
        if class_name:
            query = query.filter_by(class_name=class_name)
        if status:
            query = query.filter_by(status=status)
        if svc_type:
            query = query.join(SupportService).filter(
                SupportService.service_type == svc_type,
                SupportService.status != 'finished')
        if has_open_tasks:
            query = query.join(FollowUpTask).filter(FollowUpTask.is_completed == False)
        return query.distinct().order_by(Student.class_name, Student.full_name).all()

    # ── File Upload / Download ─────────────────────────────────────────────
    @app.route('/files/upload', methods=['POST'])
    @login_required
    @admin_required
    def file_upload():
        student_id = request.form.get('student_id', type=int)
        doc_id = request.form.get('documentation_id', type=int)
        student = Student.query.get_or_404(student_id)

        if 'file' not in request.files:
            flash('לא נבחר קובץ.', 'warning')
            return redirect(request.referrer)

        file = request.files['file']
        if not file or not file.filename:
            flash('לא נבחר קובץ.', 'warning')
            return redirect(request.referrer)

        if not allowed_file(file.filename):
            flash('סוג הקובץ אינו נתמך.', 'danger')
            return redirect(request.referrer)

        orig_name = file.filename
        stored_name = f"{uuid.uuid4().hex}_{secure_filename(orig_name)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
        file.save(filepath)

        att = Attachment(
            documentation_id=doc_id,
            student_id=student_id,
            filename=stored_name,
            original_name=orig_name,
            file_size=os.path.getsize(filepath),
            mime_type=file.content_type,
            uploaded_by=current_user.id,
        )
        db.session.add(att)
        db.session.commit()
        flash('הקובץ הועלה בהצלחה.', 'success')
        return redirect(url_for('student_profile', student_id=student_id) + '#files')

    @app.route('/files/<int:att_id>/download')
    @login_required
    def file_download(att_id):
        att = Attachment.query.get_or_404(att_id)
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            att.filename,
            as_attachment=True,
            download_name=att.original_name,
        )

    @app.route('/files/<int:att_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def file_delete(att_id):
        att = Attachment.query.get_or_404(att_id)
        student_id = att.student_id
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], att.filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        db.session.delete(att)
        db.session.commit()
        flash('הקובץ נמחק.', 'success')
        return redirect(url_for('student_profile', student_id=student_id) + '#files')

    # ── Settings ───────────────────────────────────────────────────────────
    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def settings():
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add_user':
                uname = request.form.get('username', '').strip()
                if User.query.filter_by(username=uname).first():
                    flash('שם משתמש זה כבר קיים.', 'danger')
                else:
                    u = User(
                        username=uname,
                        role=request.form.get('role', 'reader'),
                        full_name=request.form.get('full_name', '').strip(),
                    )
                    u.set_password(request.form.get('password', 'temp1234'))
                    db.session.add(u)
                    db.session.commit()
                    flash(f'המשתמש {uname} נוסף בהצלחה.', 'success')
            elif action == 'change_password':
                u = User.query.get(request.form.get('user_id', type=int))
                if u:
                    u.set_password(request.form.get('new_password', ''))
                    db.session.commit()
                    flash('הסיסמה שונתה בהצלחה.', 'success')
            elif action == 'toggle_user':
                u = User.query.get(request.form.get('user_id', type=int))
                if u and u.id != current_user.id:
                    u.is_active = not u.is_active
                    db.session.commit()
                    flash('סטטוס המשתמש עודכן.', 'success')
            elif action == 'reset_all_data':
                confirm = request.form.get('confirm_reset', '').strip()
                if confirm == 'מחק הכל':
                    # Delete all student-related data (keep users)
                    Attachment.query.delete()
                    FollowUpTask.query.delete()
                    DocumentationCategory.query.delete()
                    Documentation.query.delete()
                    SupportService.query.delete()
                    Student.query.delete()
                    db.session.commit()
                    # Clean up uploaded files
                    try:
                        for fn in os.listdir(UPLOAD_FOLDER):
                            fp = os.path.join(UPLOAD_FOLDER, fn)
                            if os.path.isfile(fp):
                                os.remove(fp)
                    except Exception:
                        pass
                    flash('כל הנתונים נמחקו בהצלחה. ניתן לייבא קובץ חדש.', 'success')
                else:
                    flash('אישור שגוי — הנתונים לא נמחקו.', 'danger')
            return redirect(url_for('settings'))

        users = User.query.order_by(User.created_at).all()
        total_students = Student.query.count()
        total_docs = Documentation.query.count()
        total_tasks = FollowUpTask.query.count()
        return render_template('settings.html',
                               users=users,
                               total_students=total_students,
                               total_docs=total_docs,
                               total_tasks=total_tasks)

    # ── TEMPORARY diagnostic route: reconcile every student against the
    # source Excel files (the declared full/authoritative roster) ──────────
    @app.route('/admin/diag-reconcile')
    @login_required
    @admin_required
    def diag_reconcile():
        with open(os.path.join(BASE_DIR, 'file_keys_data.json'), encoding='utf-8') as f:
            file_keys = set(tuple(x) for x in json.load(f))

        not_in_files = []
        in_files = 0
        for s in Student.query.all():
            key = (s.full_name, str(s.dob))
            if key in file_keys:
                in_files += 1
            else:
                not_in_files.append({
                    'id': s.id, 'name': s.full_name, 'grade': s.grade_level,
                    'class_name': s.class_name, 'dob': str(s.dob),
                    'created_at': str(s.created_at),
                })

        for item in not_in_files:
            sid = item['id']
            item['doc_count'] = Documentation.query.filter_by(student_id=sid).count()
            item['service_count'] = SupportService.query.filter_by(student_id=sid).count()
            item['task_count'] = FollowUpTask.query.filter_by(student_id=sid).count()

        return jsonify({
            'total': Student.query.count(),
            'in_files': in_files,
            'not_in_files_count': len(not_in_files),
            'not_in_files': not_in_files,
        })

    # ── TEMPORARY diagnostic route: grade/class breakdown ───────────────────
    @app.route('/admin/diag-grades')
    @login_required
    @admin_required
    def diag_grades():
        rows = (db.session.query(Student.grade_level, func.count(Student.id))
                .group_by(Student.grade_level).all())
        by_class = (db.session.query(Student.grade_level, Student.class_name, func.count(Student.id))
                    .group_by(Student.grade_level, Student.class_name)
                    .order_by(Student.grade_level, Student.class_name).all())
        bare = Student.query.filter(Student.class_name.in_(['ז', 'ח', 'ט'])).all()
        proper = Student.query.filter(~Student.class_name.in_(['ז', 'ח', 'ט'])).all()
        proper_keys = {(s.full_name, s.dob) for s in proper}
        proper_name_keys = {}
        for s in proper:
            proper_name_keys.setdefault(s.full_name, []).append((s.id, s.class_name, str(s.dob)))

        bare_details = []
        for s in bare:
            exact_dup = (s.full_name, s.dob) in proper_keys
            name_matches = proper_name_keys.get(s.full_name, [])
            bare_details.append({
                'id': s.id, 'name': s.full_name, 'grade': s.grade_level,
                'dob': str(s.dob), 'created_at': str(s.created_at),
                'exact_dup_of_proper': exact_dup,
                'same_name_proper_records': name_matches,
            })

        dup_rows = (db.session.query(Student.full_name, Student.grade_level, func.count(Student.id))
                    .group_by(Student.full_name, Student.grade_level)
                    .having(func.count(Student.id) > 1).all())
        dup_details = []
        for name, grade, cnt in dup_rows:
            members = Student.query.filter_by(full_name=name, grade_level=grade).all()
            dup_details.append({
                'name': name, 'grade': grade, 'count': cnt,
                'members': [{'id': s.id, 'class_name': s.class_name, 'dob': str(s.dob),
                             'created_at': str(s.created_at)} for s in members],
            })

        return jsonify({
            'by_grade': {g: c for g, c in rows},
            'by_class': [[g, c, n] for g, c, n in by_class],
            'total': Student.query.count(),
            'bare_class_students': bare_details,
            'same_name_same_grade_dupes': dup_details,
        })

    # ── TEMPORARY one-time route: clean up bare-grade class_name records ────
    # Deletes exact-duplicate rows (same name+dob as a properly-classed
    # record) and fixes the class_name of genuinely unique students whose
    # class was left as just the bare grade letter, using a precomputed
    # name/dob -> correct class mapping recovered from the source files.
    @app.route('/admin/run-bare-class-cleanup-once', methods=['POST'])
    @login_required
    @admin_required
    def run_bare_class_cleanup_once():
        import traceback
        try:
            with open(os.path.join(BASE_DIR, 'dup_delete_ids.json'), encoding='utf-8') as f:
                delete_ids = json.load(f)
            with open(os.path.join(BASE_DIR, 'class_fixes_data.json'), encoding='utf-8') as f:
                fixes = json.load(f)

            deleted_count = 0
            if delete_ids:
                deleted_count = (Student.query.filter(Student.id.in_(delete_ids))
                                  .delete(synchronize_session=False))
                db.session.flush()

            fixed = []
            if fixes:
                temp_mappings = [{'id': f['id'], 'class_name': f"__tmp_{f['id']}"} for f in fixes]
                db.session.bulk_update_mappings(Student, temp_mappings)
                db.session.flush()

                final_mappings = [{'id': f['id'], 'grade_level': f['new_grade'],
                                    'class_name': f['new_class']} for f in fixes]
                db.session.bulk_update_mappings(Student, final_mappings)
                fixed = [{'id': f['id'], 'name': f['name'], 'new_class': f['new_class']} for f in fixes]

            db.session.commit()

            return jsonify({
                'deleted_count': deleted_count,
                'fixed_count': len(fixed),
                'fixed': fixed,
                'after_total': Student.query.count(),
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

    # ── TEMPORARY one-time maintenance route: merge grade-promotion dupes ───
    # Removed after use. Matches old-grade student records (from before this
    # year's re-import) to their newly-imported duplicate in the next grade
    # up, keeps the OLD record (and its documentation history) and just
    # updates its grade/class, then deletes the history-less duplicate.
    @app.route('/admin/run-promotion-merge-once', methods=['POST'])
    @login_required
    @admin_required
    def run_promotion_merge_once():
        import traceback
        try:
            pairs_path = os.path.join(BASE_DIR, 'promotion_pairs_data.json')
            with open(pairs_path, encoding='utf-8') as f:
                pairs = json.load(f)

            all_pairs = [(oid, nid, cls, 'ח') for oid, nid, cls in pairs['z_to_h']] + \
                        [(oid, nid, cls, 'ט') for oid, nid, cls in pairs['h_to_t']]

            old_ids = [p[0] for p in all_pairs]
            new_ids = [p[1] for p in all_pairs]

            existing_old = {s.id: s.full_name for s in
                             Student.query.filter(Student.id.in_(old_ids)).all()}
            existing_new = {s.id: s.full_name for s in
                             Student.query.filter(Student.id.in_(new_ids)).all()}

            related_new_ids = set()
            for model in (Documentation, SupportService, FollowUpTask):
                rows = (db.session.query(model.student_id)
                        .filter(model.student_id.in_(new_ids))
                        .distinct().all())
                related_new_ids.update(r[0] for r in rows)

            promoted = []
            skipped_had_related = []
            already_gone = []
            to_update = []   # (old_id, new_grade, new_class, name)
            delete_ids = []

            for old_id, new_id, new_class, new_grade in all_pairs:
                old_name = existing_old.get(old_id)
                new_name = existing_new.get(new_id)
                if old_name is None or new_name is None:
                    already_gone.append({'old_id': old_id, 'new_id': new_id})
                    continue
                if new_id in related_new_ids:
                    skipped_had_related.append({'old_id': old_id, 'new_id': new_id, 'name': new_name})
                    continue
                delete_ids.append(new_id)
                to_update.append((old_id, new_grade, new_class, old_name))

            if delete_ids:
                Student.query.filter(Student.id.in_(delete_ids)).delete(synchronize_session=False)
                db.session.flush()

            if to_update:
                temp_mappings = [{'id': oid, 'class_name': f'__tmp_{oid}'} for oid, g, c, n in to_update]
                db.session.bulk_update_mappings(Student, temp_mappings)
                db.session.flush()

                final_mappings = [{'id': oid, 'grade_level': g, 'class_name': c} for oid, g, c, n in to_update]
                db.session.bulk_update_mappings(Student, final_mappings)
                for oid, g, c, n in to_update:
                    promoted.append({'old_id': oid, 'name': n, 'new_class': c})

            db.session.commit()

            return jsonify({
                'promoted_count': len(promoted),
                'skipped_had_related': skipped_had_related,
                'already_gone_count': len(already_gone),
                'after_total': Student.query.count(),
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

    # ── Import Debug: show detected columns without importing ──────────────
    @app.route('/students/import/debug', methods=['POST'])
    @login_required
    @admin_required
    def students_import_debug():
        import tempfile
        f = request.files.get('excel_file')
        if not f or not f.filename:
            return jsonify({'error': 'no file'}), 400
        ext = f.filename.rsplit('.', 1)[-1].lower()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}', dir=UPLOAD_FOLDER)
        f.save(tmp.name)
        try:
            headers, preview = _parse_excel_preview(tmp.name, ext)
            auto_map, matched = _auto_detect_columns(headers)
        finally:
            try:
                os.remove(tmp.name)
            except Exception:
                pass
        LABELS = {
            'col_full_name': 'שם מלא', 'col_first_name': 'שם פרטי',
            'col_last_name': 'שם משפחה', 'col_class_name': 'כיתה',
            'col_grade_level': 'שכבה', 'col_gender': 'מין',
            'col_dob': 'תאריך לידה', 'col_homeroom': 'מחנכת',
            'col_parent1_name': 'הורה 1', 'col_parent1_phone': 'טלפון 1',
            'col_parent2_name': 'הורה 2', 'col_parent2_phone': 'טלפון 2',
        }
        return jsonify({
            'headers': headers,
            'auto_map': {LABELS[k]: v for k, v in auto_map.items()},
            'matched': matched,
            'preview_row': preview[0] if preview else {},
        })

    # ── API ────────────────────────────────────────────────────────────────
    @app.route('/api/students/search')
    @login_required
    def api_students_search():
        q = request.args.get('q', '').strip()
        students = Student.query.filter(
            Student.full_name.contains(q)
        ).order_by(Student.class_name, Student.full_name).limit(20).all()
        return jsonify([{
            'id': s.id,
            'name': s.full_name,
            'class': s.class_name,
            'label': f'{s.full_name} — {s.class_name}',
        } for s in students])


# ── Excel Import Helper Functions ─────────────────────────────────────────────

def _norm(s):
    """Normalise a string for fuzzy matching: lowercase, strip spaces/punctuation."""
    import unicodedata
    s = unicodedata.normalize('NFC', str(s))
    for ch in (' ', '\t', ' ', '-', '_', "'", '"', '״', '׳', '/', '\\', '.', ','):
        s = s.replace(ch, '')
    return s.lower()


def _auto_detect_columns(headers):
    """
    Given column headers, return (auto_map, matched_count).
    auto_map: field_id -> best matching header string ('' if not found).

    Strategy: for each field, try keywords in priority order.
    A keyword matches a header if either is a substring of the other (after normalise).
    'used_headers' prevents assigning the same column twice.
    """
    # Priority-ordered keyword lists per field.
    # More specific (longer) keywords come first to avoid false matches.
    FIELD_KEYWORDS = {
        # ── Name fields ───────────────────────────────────────────────────
        'col_full_name': [
            'שםהתלמיד', 'שםתלמיד', 'שםהתלמידה', 'שםמלא',
            'שםתלמידה', 'studentname', 'fullname', 'student',
            'תלמיד', 'תלמידה',
        ],
        'col_first_name': [
            'שםפרטי', 'שםריאשון', 'firstname', 'givenname', 'שם1',
        ],
        'col_last_name': [
            'שםמשפחה', 'משפחה', 'familyname', 'lastname', 'surname', 'שם2',
        ],

        # ── Class / grade ─────────────────────────────────────────────────
        'col_class_name': [
            'כיתה', 'class', 'classroom', 'section', 'קבוצה', 'group',
        ],
        'col_grade_level': [
            'שכבה', 'gradelevel', 'grade', 'level', 'שנה', 'year',
        ],

        # ── Personal ──────────────────────────────────────────────────────
        'col_gender': [
            'מין', 'gender', 'sex', 'זכר', 'נקבה',
        ],
        'col_dob': [
            'תאריךלידה', 'תלידה', 'birthdate', 'dateofbirth', 'dob',
            'birthday', 'לידה', 'תאריך',
        ],
        'col_homeroom': [
            'מחנכת', 'מחנך', 'מחנכ', 'homeroom', 'classteacher', 'teacher',
        ],

        # ── Parent names ──────────────────────────────────────────────────
        # Specific two-parent columns first, then individual
        'col_parent1_name': [
            'שםהורה1', 'שםהורהראשון', 'שםאמא', 'שםאב', 'שםאבא',
            'שמותהורים', 'שמהורים', 'שניההורים', 'הורים',
            'parent1name', 'mother', 'father', 'parent1',
            'אמא', 'אבא', 'הורה1', 'הורהראשון',
        ],
        'col_parent2_name': [
            'שםהורה2', 'שםהורהשני', 'parent2name', 'parent2',
            'הורה2', 'הורהשני',
        ],

        # ── Parent phones ─────────────────────────────────────────────────
        'col_parent1_phone': [
            'טלפוןהורה1', 'נייד1', 'טל1', 'phone1', 'mobile1', 'tel1',
            'טלפוןאמא', 'טלפוןאבא', 'נייד', 'טלפון', 'phone', 'mobile',
            'tel', 'cellphone', 'מספרטלפון', 'מספרנייד',
        ],
        'col_parent2_phone': [
            'טלפוןהורה2', 'נייד2', 'טל2', 'phone2', 'mobile2', 'tel2',
            'הורה2',   # catches "טלפון נייד של הורה 2" after parent2_name already claimed "שם הורה 2"
        ],
    }

    norm_headers = [(h, _norm(h)) for h in headers if h and str(h).strip()]
    used = set()
    auto_map = {fid: '' for fid in FIELD_KEYWORDS}

    for field_id, keywords in FIELD_KEYWORDS.items():
        for kw in keywords:
            kw_n = _norm(kw)
            if not kw_n:
                continue
            for orig, norm in norm_headers:
                if orig in used:
                    continue
                # Match if either contains the other (min length 2 to avoid false positives)
                if len(kw_n) >= 2 and len(norm) >= 2:
                    if kw_n in norm or norm in kw_n:
                        auto_map[field_id] = orig
                        used.add(orig)
                        break
            if auto_map[field_id]:
                break

    matched = sum(1 for v in auto_map.values() if v)
    return auto_map, matched

def _parse_excel_preview(filepath, ext):
    """
    Read an Excel/CSV file and return (headers_list, preview_rows).
    Smart header detection: skips title rows (rows with only 1 filled cell).
    """
    rows = _read_all_rows(filepath, ext)
    if not rows:
        raise ValueError('הקובץ ריק או לא ניתן לקריאה.')

    # Find the best header row:
    # - Skip rows that are completely empty
    # - Skip rows that have only 1 non-empty cell (title rows)
    # - The first row with ≥2 non-empty cells is the header
    header_idx = 0
    for i, row in enumerate(rows):
        non_empty = [c for c in row if c is not None and str(c).strip()]
        if len(non_empty) >= 2:
            header_idx = i
            break

    raw_headers = [str(c).strip() if c is not None else '' for c in rows[header_idx]]
    # Trim trailing empty headers
    while raw_headers and raw_headers[-1] == '':
        raw_headers.pop()

    data_rows = rows[header_idx + 1:]
    preview = []
    for row in data_rows[:6]:
        if not any(c is not None and str(c).strip() for c in row):
            continue
        d = {}
        for i, h in enumerate(raw_headers):
            val = row[i] if i < len(row) else ''
            d[h] = str(val).strip() if val is not None else ''
        preview.append(d)
        if len(preview) == 5:
            break

    return raw_headers, preview


def _read_all_rows(filepath, ext):
    """Read all rows from xlsx/xls/csv as list of lists."""
    if ext in ('xlsx', 'xls'):
        import openpyxl
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        return [list(row) for row in ws.iter_rows(values_only=True)]
    elif ext == 'csv':
        import csv
        # Try common encodings
        for enc in ('utf-8-sig', 'utf-8', 'windows-1255', 'cp1255', 'iso-8859-8'):
            try:
                with open(filepath, encoding=enc, newline='') as f:
                    content = f.read()
                # Detect delimiter
                delim = ';' if content.count(';') > content.count(',') else ','
                import io
                reader = csv.reader(io.StringIO(content), delimiter=delim)
                return [row for row in reader]
            except (UnicodeDecodeError, Exception):
                continue
        raise ValueError('לא ניתן לקרוא את קובץ ה-CSV. נסי לשמור אותו מחדש כ-Excel.')
    return []


def _do_import(filepath, ext, mapping, default_class, default_grade):
    """
    Import students from file using the given column mapping.
    Returns (imported_count, skipped_count, error_list, sample_ids).
    sample_ids: first 5 imported student IDs for preview.
    """
    from sqlalchemy.exc import IntegrityError

    rows = _read_all_rows(filepath, ext)
    if not rows:
        return 0, 0, ['הקובץ ריק'], []

    # Find header row = first row with ≥2 non-empty cells (skip title rows)
    header_idx = 0
    for i, row in enumerate(rows):
        non_empty = [c for c in row if c is not None and str(c).strip()]
        if len(non_empty) >= 2:
            header_idx = i
            break

    raw_headers = rows[header_idx]
    headers = [str(c).strip() if c is not None else '' for c in raw_headers]
    data_rows = rows[header_idx + 1:]

    def get_col(row, col_name):
        """Return cell value by column name, '' if not found/empty."""
        if not col_name:
            return ''
        # Try exact match first
        for i, h in enumerate(headers):
            if h == col_name:
                val = row[i] if i < len(row) else None
                return str(val).strip() if val is not None else ''
        # Fallback: normalised match (handles minor whitespace differences)
        col_n = _norm(col_name)
        for i, h in enumerate(headers):
            if _norm(h) == col_n:
                val = row[i] if i < len(row) else None
                return str(val).strip() if val is not None else ''
        return ''

    def parse_dob(s):
        if not s or s in ('None', ''):
            return None
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y',
                    '%m/%d/%Y', '%Y/%m/%d', '%d/%m/%y'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    imported = 0
    skipped  = 0
    errors   = []
    sample_ids = []

    for i, row in enumerate(data_rows):
        if not any(c is not None and str(c).strip() for c in row):
            continue  # skip blank rows

        # Build full name from available name columns
        first = get_col(row, mapping.get('first_name', ''))
        last  = get_col(row, mapping.get('last_name', ''))
        full  = get_col(row, mapping.get('full_name', ''))

        if first and last:
            full_name = f'{first} {last}'.strip()
        elif full:
            full_name = full
        elif first:
            full_name = first
        elif last:
            full_name = last
        else:
            errors.append(f'שורה {i + header_idx + 2}: שם חסר — דולגה')
            continue

        class_name  = get_col(row, mapping.get('class_name', ''))  or default_class
        grade_level = get_col(row, mapping.get('grade_level', '')) or default_grade

        # Auto-infer grade from class name
        if not grade_level and class_name:
            if class_name and class_name[0] in ('ז', 'ח', 'ט'):
                grade_level = class_name[0]

        # If class is still missing but grade is known, use grade as class placeholder
        if not class_name and grade_level:
            class_name = grade_level

        if not class_name:
            errors.append(f'שורה {i + header_idx + 2} ({full_name}): כיתה ושכבה חסרות — דולגה')
            continue

        gender_raw = get_col(row, mapping.get('gender', ''))
        # Normalise gender: accept ז/נ/זכר/נקבה/m/f
        gender = None
        if gender_raw in ('ז', 'זכר', 'm', 'male', 'M'):
            gender = 'ז'
        elif gender_raw in ('נ', 'נקבה', 'f', 'female', 'F'):
            gender = 'נ'

        dob = parse_dob(get_col(row, mapping.get('dob', '')))

        student = Student(
            full_name=full_name,
            class_name=class_name,
            grade_level=grade_level,
            gender=gender,
            dob=dob,
            homeroom_teacher=get_col(row, mapping.get('homeroom', '')) or None,
            parent1_name=get_col(row, mapping.get('parent1_name', '')) or None,
            parent1_phone=get_col(row, mapping.get('parent1_phone', '')) or None,
            parent2_name=get_col(row, mapping.get('parent2_name', '')) or None,
            parent2_phone=get_col(row, mapping.get('parent2_phone', '')) or None,
            status='active',
        )
        db.session.add(student)
        try:
            db.session.flush()
            imported += 1
            if len(sample_ids) < 5:
                sample_ids.append(student.id)
        except IntegrityError:
            db.session.rollback()
            skipped += 1

    db.session.commit()
    return imported, skipped, errors, sample_ids


# Expose global 'app' for gunicorn (Render uses 'gunicorn app:app')
app = create_app()

if __name__ == '__main__':
    import sys as _sys, io as _io
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace')
    application = create_app()
    print('School Counselor App running at: http://localhost:5000')
    print('Login: admin / counselor2024')
    application.run(debug=False, port=5000, use_reloader=False)
