import pymysql
from .config import BLUE_KEY_UID

def get_db_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="azellus1234",
        database="library",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def get_table_columns(table_name: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
            return {row["Field"] for row in cursor.fetchall()}
    finally:
        conn.close()

def ensure_schema():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS rfid_scans (
                scan_id INT AUTO_INCREMENT PRIMARY KEY,
                uid VARCHAR(255) NOT NULL,
                user_id INT NULL,
                scanned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX (uid),
                INDEX (user_id),
                INDEX (scanned_at)
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                book_id INT AUTO_INCREMENT PRIMARY KEY,
                rfid_uid VARCHAR(255) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL,
                author VARCHAR(255) NOT NULL,
                isbn VARCHAR(64) NULL,
                category VARCHAR(80) NULL,
                year_published INT NULL,
                total_copies INT NOT NULL DEFAULT 1,
                available_copies INT NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL,
                INDEX (title),
                INDEX (author),
                INDEX (category)
            )""")
            # Optional: seed book
            cursor.execute("SELECT book_id FROM books WHERE rfid_uid=%s", ("D5B93B03",))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO books (rfid_uid, title, author, isbn, category, year_published, total_copies, available_copies)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, ("D5B93B03", "The Great Gatsby", "F. Scott Fitzgerald", "978-0-7432-7356-5", "Fiction", 1925, 1, 1))
    finally:
        conn.close()