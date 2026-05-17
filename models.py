from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date

db = SQLAlchemy()

STATUS_COLORS = {
    'urgent': 'danger',
    'followup': 'warning',
    'active': 'primary',
    'closed': 'secondary',
}

STATUS_LABELS = {
    'urgent': 'דחוף',
    'followup': 'במעקב',
    'active': 'פעיל',
    'closed': 'סגור',
}

URGENCY_LABELS = {
    'low': 'נמוך',
    'medium': 'בינוני',
    'high': 'גבוה',
}

URGENCY_COLORS = {
    'low': 'success',
    'medium': 'warning',
    'high': 'danger',
}

SERVICE_STATUS_LABELS = {
    'active': 'פעיל',
    'waiting': 'ממתין',
    'finished': 'הסתיים',
}

DOC_CATEGORIES = [
    'שיחה אישית עם תלמיד',
    'מפגש עם הורים',
    'שיחה עם מחנכת',
    'שיחה עם מורה מקצועי',
    'ועדה רב מקצועית',
    'תלמיד עם סל אישי',
    'תלמיד חינוך מיוחד',
    'טיפולים דרך מת"א',
    'התערבות קב"ס',
    'התערבות עו"ס / רווחה',
    'טיפולים או סדנאות דרך גפ"ן',
    'חדר חם',
    'מעקב יועצת',
    'קושי רגשי',
    'קושי חברתי',
    'קושי לימודי',
    'היעדרויות',
    'התנהגות מאתגרת',
    'פנייה לגורם חיצוני',
    'אחר',
]

SERVICE_TYPES = [
    'סל אישי',
    'חינוך מיוחד',
    'מת"א',
    'רווחה',
    'קב"ס',
    'גפ"ן',
    'חדר חם',
    'טיפול רגשי',
    'טיפול קבוצתי',
    'שיחות אישיות עם יועצת',
    'סדנה רגשית/חברתית',
    'מעקב קבוע',
]


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='reader')  # admin / reader
    full_name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username}>'


class Student(db.Model):
    __tablename__ = 'student'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    class_name = db.Column(db.String(20), nullable=False)
    grade_level = db.Column(db.String(5), nullable=False)  # ז / ח / ט
    homeroom_teacher = db.Column(db.String(100))
    parent1_name = db.Column(db.String(200))
    parent1_phone = db.Column(db.String(30))
    parent2_name = db.Column(db.String(200))
    parent2_phone = db.Column(db.String(30))
    dob = db.Column(db.Date)
    gender = db.Column(db.String(5))  # ז / נ
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')  # active/followup/urgent/closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('full_name', 'class_name', name='uq_student_class'),)

    documentation = db.relationship('Documentation', backref='student', lazy='dynamic',
                                    cascade='all, delete-orphan')
    support_services = db.relationship('SupportService', backref='student', lazy='dynamic',
                                       cascade='all, delete-orphan')
    followup_tasks = db.relationship('FollowUpTask', backref='student', lazy='dynamic',
                                     cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', backref='student', lazy='dynamic',
                                  cascade='all, delete-orphan')

    @property
    def status_color(self):
        return STATUS_COLORS.get(self.status, 'secondary')

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def open_tasks_count(self):
        return self.followup_tasks.filter_by(is_completed=False).count()

    @property
    def last_doc_date(self):
        last = self.documentation.order_by(Documentation.date.desc()).first()
        return last.date if last else None

    def __repr__(self):
        return f'<Student {self.full_name} {self.class_name}>'


class Documentation(db.Model):
    __tablename__ = 'documentation'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    summary = db.Column(db.Text, nullable=False)
    concerns = db.Column(db.Text)
    decisions = db.Column(db.Text)
    next_steps = db.Column(db.Text)
    participants = db.Column(db.Text)
    followup_date = db.Column(db.Date)
    urgency = db.Column(db.String(20), default='low')  # low/medium/high
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categories = db.relationship('DocumentationCategory', backref='documentation',
                                 lazy='dynamic', cascade='all, delete-orphan')
    tasks = db.relationship('FollowUpTask', backref='documentation', lazy='dynamic')
    attachments = db.relationship('Attachment', backref='documentation', lazy='dynamic',
                                  cascade='all, delete-orphan')

    @property
    def categories_list(self):
        return [c.category_name for c in self.categories.all()]

    @property
    def urgency_label(self):
        return URGENCY_LABELS.get(self.urgency, self.urgency)

    @property
    def urgency_color(self):
        return URGENCY_COLORS.get(self.urgency, 'secondary')

    def __repr__(self):
        return f'<Documentation {self.id} student={self.student_id}>'


class DocumentationCategory(db.Model):
    __tablename__ = 'documentation_category'
    id = db.Column(db.Integer, primary_key=True)
    documentation_id = db.Column(db.Integer, db.ForeignKey('documentation.id',
                                                            ondelete='CASCADE'), nullable=False)
    category_name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<DocCategory {self.category_name}>'


class SupportService(db.Model):
    __tablename__ = 'support_service'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    service_type = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    responsible_person = db.Column(db.String(100))
    frequency = db.Column(db.String(100))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')  # active/waiting/finished
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status_label(self):
        return SERVICE_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        colors = {'active': 'success', 'waiting': 'warning', 'finished': 'secondary'}
        return colors.get(self.status, 'secondary')

    def __repr__(self):
        return f'<SupportService {self.service_type} student={self.student_id}>'


class FollowUpTask(db.Model):
    __tablename__ = 'followup_task'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    documentation_id = db.Column(db.Integer, db.ForeignKey('documentation.id'), nullable=True)
    due_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text, nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_overdue(self):
        return not self.is_completed and self.due_date < date.today()

    @property
    def days_until_due(self):
        return (self.due_date - date.today()).days

    def __repr__(self):
        return f'<FollowUpTask {self.id} due={self.due_date}>'


class Attachment(db.Model):
    __tablename__ = 'attachment'
    id = db.Column(db.Integer, primary_key=True)
    documentation_id = db.Column(db.Integer, db.ForeignKey('documentation.id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Attachment {self.original_name}>'
