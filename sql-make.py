import sqlite3
import csv

# Map original CSV columns to safe SQL column names (same as before)
COLUMN_MAP = {
    'term_code': 'term_code',
    'numeric_term_code': 'numeric_term_code',
    'subject_code': 'subject_code',
    'course_code': 'course_code',
    'course_title': 'course_title',
    'instructors': 'instructors',
    'total_grades': 'total_grades',
    'amount_of_grades': 'amount_of_grades',
    'average_grade': 'average_grade',
    '4.0': 'grade_4_0',
    '3.5': 'grade_3_5',
    '3.0': 'grade_3_0',
    '2.5': 'grade_2_5',
    '2.0': 'grade_2_0',
    '1.5': 'grade_1_5',
    '1.0': 'grade_1_0',
    '0.0': 'grade_0_0',
    'A+': 'grade_A_plus',
    'A': 'grade_A',
    'A-': 'grade_A_minus',
    'B+': 'grade_B_plus',
    'B': 'grade_B',
    'B-': 'grade_B_minus',
    'C+': 'grade_C_plus',
    'C': 'grade_C',
    'C-': 'grade_C_minus',
    'D+': 'grade_D_plus',
    'D': 'grade_D',
    'D-': 'grade_D_minus',
    'F': 'grade_F',
    'pass': 'pass',
    'no_grade': 'no_grade',
    'deferred': 'deferred',
    'satisfactory': 'satisfactory',
    'not_satisfactory': 'not_satisfactory',
    'credit': 'credit',
    'no_credit': 'no_credit',
    'incomplete': 'incomplete',
    'withdrawn': 'withdrawn',
    'unfinished_work': 'unfinished_work',
}

# List columns to store as REAL (float)
NUMERIC_COLUMNS = {
    'numeric_term_code',
    'total_grades',
    'amount_of_grades',
    'average_grade',
    '4.0', '3.5', '3.0', '2.5', '2.0', '1.5', '1.0', '0.0',
    'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'D-', 'F',
    'pass', 'no_grade', 'deferred', 'satisfactory', 'not_satisfactory',
    'credit', 'no_credit', 'incomplete', 'withdrawn', 'unfinished_work'
}

def create_course_grades_table():
    conn = sqlite3.connect('grades.db')
    cursor = conn.cursor()

    columns_def = []
    for orig_col, sql_col in COLUMN_MAP.items():
        col_type = "REAL" if orig_col in NUMERIC_COLUMNS else "TEXT"
        columns_def.append(f"{sql_col} {col_type}")
    columns_def_str = ',\n'.join(columns_def)

    create_stmt = f'''
    CREATE TABLE IF NOT EXISTS course_grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        {columns_def_str}
    )
    '''
    cursor.execute(create_stmt)
    conn.commit()
    conn.close()

def load_csv_into_db(csv_filepath):
    conn = sqlite3.connect('grades.db')
    cursor = conn.cursor()

    with open(csv_filepath, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)

        columns = list(COLUMN_MAP.values())
        placeholders = ', '.join(['?'] * len(columns))
        insert_stmt = f"INSERT INTO course_grades ({', '.join(columns)}) VALUES ({placeholders})"

        for row in reader:
            values = []
            for orig_col in COLUMN_MAP.keys():
                val = row[orig_col]
                if orig_col in NUMERIC_COLUMNS:
                    # Convert empty strings to None, else float
                    if val.strip() == '':
                        values.append(None)
                    else:
                        try:
                            values.append(float(val))
                        except ValueError:
                            values.append(None)  # fallback if conversion fails
                else:
                    values.append(val)
            cursor.execute(insert_stmt, values)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_course_grades_table()
    load_csv_into_db('newgrades.csv')
    print("CSV data loaded into database with proper types!")
