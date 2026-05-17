# import_data.py
# One-time script to import student rosters from Excel/CSV files
# Run once: python import_data.py

import os
import sys
import io
from datetime import datetime

# Fix Hebrew/Arabic output in Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Allow importing from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = r'C:\Users\WIN 11 HOME\Documents\אולפן תלמידים'


def parse_filename(filename):
    """
    Extract grade and class_name from file name.
    Examples:
      "ז' 1.xlsx"  -> ('ז', "ז'1")
      "ח'5.csv"    -> ('ח', "ח'5")
      "ז'2.xlsx"   -> ('ז', "ז'2")
    """
    name = os.path.splitext(filename)[0].strip()
    # First character is the grade letter
    grade = name[0]  # 'ז' or 'ח' or 'ט'
    # Normalise class name: remove all spaces → "ז'1", "ח'5"
    class_name = name.replace(' ', '')
    return grade, class_name


def parse_date(date_str):
    """Parse DD/MM/YYYY to a date object. Returns None on failure."""
    if not date_str or str(date_str).strip() in ('', 'None'):
        return None
    s = str(date_str).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def read_xlsx(filepath):
    """Return list of row dicts from an xlsx roster file."""
    try:
        import openpyxl
    except ImportError:
        print('  [!] openpyxl לא מותקן. הפעל: pip install openpyxl')
        return []

    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    # Row layout: row[0]=title, row[1]=blank, row[2]=headers, row[3+]=data
    if len(rows) < 4:
        return []

    # headers in row index 2
    headers = [str(h).strip() if h else '' for h in rows[2]]

    results = []
    for row in rows[3:]:
        if all(v is None or str(v).strip() == '' for v in row):
            continue  # skip fully empty rows
        d = {}
        for i, h in enumerate(headers):
            val = row[i] if i < len(row) else None
            d[h] = str(val).strip() if val is not None else ''
        results.append(d)
    return results


def read_csv(filepath):
    """Return list of row dicts from a semicolon-delimited CSV roster file."""
    import csv
    results = []
    with open(filepath, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f, delimiter=';')
        all_rows = list(reader)

    if len(all_rows) < 4:
        return []

    headers = [h.strip() for h in all_rows[2]]
    for row in all_rows[3:]:
        if all(c.strip() == '' for c in row):
            continue
        d = {}
        for i, h in enumerate(headers):
            d[h] = row[i].strip() if i < len(row) else ''
        results.append(d)
    return results


def import_file(filepath, grade, class_name, Student, db):
    """Import one roster file. Returns (imported_count, skipped_count)."""
    from sqlalchemy.exc import IntegrityError

    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.xlsx':
        rows = read_xlsx(filepath)
    elif ext == '.csv':
        rows = read_csv(filepath)
    else:
        return 0, 0

    # Hebrew column name aliases
    NAME_COL    = 'שם התלמיד'
    GENDER_COL  = 'מין'
    GRADE_COL   = 'שכבה'
    DOB_COL     = 'תאריך לידה'
    P1_NAME_COL = 'שם הורה 1'
    P1_TEL_COL  = 'טלפון נייד של הורה 1'
    P2_NAME_COL = 'שם הורה 2'
    P2_TEL_COL  = 'טלפון נייד של הורה 2'

    imported = 0
    skipped  = 0

    for row in rows:
        full_name = row.get(NAME_COL, '').strip()
        if not full_name:
            continue

        dob = parse_date(row.get(DOB_COL, ''))
        gender_raw = row.get(GENDER_COL, '').strip()
        # Normalise gender: keep ז/נ, ignore others
        gender = gender_raw if gender_raw in ('ז', 'נ') else None

        student = Student(
            full_name=full_name,
            class_name=class_name,
            grade_level=grade,
            dob=dob,
            gender=gender,
            parent1_name=row.get(P1_NAME_COL, '').strip() or None,
            parent1_phone=row.get(P1_TEL_COL, '').strip() or None,
            parent2_name=row.get(P2_NAME_COL, '').strip() or None,
            parent2_phone=row.get(P2_TEL_COL, '').strip() or None,
            status='active',
        )
        db.session.add(student)
        try:
            db.session.flush()
            imported += 1
        except IntegrityError:
            db.session.rollback()
            skipped += 1

    db.session.commit()
    return imported, skipped


def import_all():
    from app import create_app
    from models import db, Student

    if not os.path.isdir(DATA_DIR):
        print(f'[!] תיקיית הנתונים לא נמצאה: {DATA_DIR}')
        sys.exit(1)

    app = create_app()

    with app.app_context():
        total_imported = 0
        total_skipped  = 0

        # Collect files: process .xlsx before .csv to handle ח'5 duplicate
        files = []
        for fname in os.listdir(DATA_DIR):
            ext = os.path.splitext(fname)[1].lower()
            if ext in ('.xlsx', '.csv'):
                files.append(fname)

        # Sort: xlsx files first, then csv
        files.sort(key=lambda f: (0 if f.endswith('.xlsx') else 1, f))

        # Track which class_names already have students (for dedup of xlsx+csv same class)
        processed_classes = set()

        for fname in files:
            fpath = os.path.join(DATA_DIR, fname)
            grade, class_name = parse_filename(fname)

            # If this class was already processed (e.g. ח'5.xlsx done, skip ח'5.csv)
            if class_name in processed_classes:
                print(f'  [~] דילוג (כפול): {fname}')
                continue

            print(f'  ייבוא: {fname}  →  כיתה {class_name} (שכבה {grade})')
            imp, skp = import_file(fpath, grade, class_name, Student, db)
            print(f'       ✓ יובאו: {imp}  |  דולגו (כפולים): {skp}')
            total_imported += imp
            total_skipped  += skp
            processed_classes.add(class_name)

        print()
        print('=' * 50)
        print(f'סה"כ יובאו:  {total_imported} תלמידים')
        print(f'סה"כ דולגו: {total_skipped} כפולים')
        print('=' * 50)
        print()
        print('כעת הפעל את האפליקציה:')
        print('    python app.py')
        print('ופתח בדפדפן: http://localhost:5000')
        print('כניסה: admin / counselor2024')


if __name__ == '__main__':
    import_all()
