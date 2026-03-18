from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from datetime import datetime, timedelta
import os
import re
import time
import threading

import pymysql
import requests
import serial

blue_key_alert = None  # holds user info when blue key is scanned

app = Flask(__name__)
latest_uid = None
latest_scan_event = {"seq": 0, "uid": None, "is_blue_key": False}
app.secret_key = "mahalpakita143"

SERIAL_PORT = os.environ.get("RFID_SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.environ.get("RFID_SERIAL_BAUD", "9600"))
BLUE_KEY_UID = "3E76C301"
UID_PATTERN = re.compile(r"^[0-9A-F]{8,}$")
RFID_THREAD_STARTED = False

def get_db_connection():
    # New connection per thread/request (safer than sharing one connection globally).
    return pymysql.connect(
        host="localhost",
        user="root",
        password="azellus1234",
        database="library",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

def get_table_columns(table_name: str) -> set[str]:
    """Best-effort helper for schema-compat queries."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
            rows = cursor.fetchall()
            return {row["Field"] for row in rows}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def normalize_uid(line: str) -> str | None:
    """
    Arduino prints BOTH UID and other status messages.
    We accept only hex UID strings like: 3E76C301
    """
    if not line:
        return None
    s = line.strip().upper()

    # Accept either:
    # - pure hex UID lines: "3E76C301"
    # - legacy verbose lines: "USER ID tag : 3E 76 C3 01"
    if UID_PATTERN.match(s):
        return s

    if "USER" in s and "ID" in s:
        # Extract hex bytes from line and concatenate
        parts = re.findall(r"\b[0-9A-F]{2}\b", s)
        if parts:
            joined = "".join(parts)
            if UID_PATTERN.match(joined):
                return joined
    return None

def read_rfid():
    global latest_uid, blue_key_alert, latest_scan_event

    ser = None
    while True:
        if not ser:
            try:
                ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
                time.sleep(2)  # Give Arduino time to reset
                print(f"RFID Serial port {SERIAL_PORT} opened successfully")
            except Exception as e:
                print(f"RFID Serial error opening port: {e}")
                print(
                    "Tip: Close Arduino Serial Monitor / any app using the port, "
                    "and ensure only one Flask process is running."
                )
                time.sleep(2)
                continue

        try:
            raw = ser.readline().decode(errors="ignore").strip()
            uid = normalize_uid(raw)
            if not uid:
                continue

            latest_uid = uid
            latest_scan_event = {
                "seq": (latest_scan_event["seq"] or 0) + 1,
                "uid": uid,
                "is_blue_key": uid == BLUE_KEY_UID,
            }
            print("RFID UID:", uid)

            # Log scan + attempt to link to user_id (best-effort; don't crash thread)
            try:
                conn = get_db_connection()
                try:
                    with conn.cursor() as cursor:
                        user_id = None
                        try:
                            cursor.execute("SELECT user_id FROM user WHERE rfid_uid=%s", (uid,))
                            row = cursor.fetchone()
                            user_id = row["user_id"] if row else None
                        except Exception as e:
                            print("RFID link user error:", e)

                        try:
                            cursor.execute(
                                "INSERT INTO rfid_scans (uid, user_id) VALUES (%s, %s)",
                                (uid, user_id),
                            )
                        except Exception as e:
                            print("RFID insert scan error:", e)
                finally:
                    conn.close()
            except Exception as e:
                print("RFID DB error:", e)
            
            if uid == BLUE_KEY_UID:
                # Special admin/blue key: this is not tied to a user record
                blue_key_alert = {"kind": "blue_key", "uid": uid}

        except Exception as e:
            print(f"RFID Serial read error: {e}")
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(2)


def ensure_schema():
    """
    Keep schema requirements minimal:
    - `user` table should have `rfid_uid` column for RFID login (already assumed in code).
    - Create `rfid_scans` table for audit trail shown in dashboard.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS rfid_scans (
                    scan_id INT AUTO_INCREMENT PRIMARY KEY,
                    uid VARCHAR(255) NOT NULL,
                    user_id INT NULL,
                    scanned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX (uid),
                    INDEX (user_id),
                    INDEX (scanned_at)
                )
                """
            )

            # Books table (RFID UID -> physical book card)
            cursor.execute(
                """
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
                )
                """
            )

            # Ensure user.rfid_uid exists (best-effort; ignore if no privileges)
            try:
                cursor.execute("SHOW COLUMNS FROM user LIKE 'rfid_uid'")
                col = cursor.fetchone()
                if not col:
                    cursor.execute("ALTER TABLE user ADD COLUMN rfid_uid VARCHAR(255) NULL")
                    cursor.execute("CREATE INDEX idx_user_rfid_uid ON user (rfid_uid)")
            except Exception as e:
                # Don't crash the app if schema change isn't allowed
                print("Schema note (rfid_uid):", e)

            # Ensure admin has expected columns (some DBs use only: id, username, password)
            try:
                cursor.execute("SHOW COLUMNS FROM admin")
                admin_cols = {row["Field"] for row in cursor.fetchall()}

                if "email" not in admin_cols:
                    cursor.execute("ALTER TABLE admin ADD COLUMN email VARCHAR(255) NULL")
                    cursor.execute("CREATE INDEX idx_admin_email ON admin (email)")

                # Some code paths store display name in session; keep both name + username compatible
                if "name" not in admin_cols:
                    cursor.execute("ALTER TABLE admin ADD COLUMN name VARCHAR(255) NULL")
            except Exception as e:
                print("Schema note (admin columns):", e)

            # Ensure book_borrower supports real checkout data (best-effort)
            try:
                cursor.execute("SHOW COLUMNS FROM book_borrower")
                bb_cols = {row["Field"] for row in cursor.fetchall()}

                if "borrow_id" not in bb_cols and "id" in bb_cols:
                    # We'll keep using `id` in queries, but allow templates to use borrow_id alias if needed.
                    pass

                if "author" not in bb_cols:
                    cursor.execute("ALTER TABLE book_borrower ADD COLUMN author VARCHAR(255) NULL")

                if "book_id" not in bb_cols:
                    cursor.execute("ALTER TABLE book_borrower ADD COLUMN book_id INT NULL")
                    cursor.execute("CREATE INDEX idx_bb_book_id ON book_borrower (book_id)")

                if "due_date" not in bb_cols:
                    cursor.execute("ALTER TABLE book_borrower ADD COLUMN due_date DATETIME NULL")

                if "returned_at" not in bb_cols:
                    cursor.execute("ALTER TABLE book_borrower ADD COLUMN returned_at DATETIME NULL")

                # Back-compat: if older schema used return_date as due_date, preserve it
                if "return_date" in bb_cols:
                    cursor.execute(
                        """
                        UPDATE book_borrower
                        SET due_date = COALESCE(due_date, return_date)
                        WHERE due_date IS NULL AND return_date IS NOT NULL AND status IN ('Borrowed','Overdue')
                        """
                    )
                # Fix legacy foreign key pointing to user_old(id)
                try:
                    cursor.execute("SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='book_borrower' AND REFERENCED_TABLE_NAME IS NOT NULL")
                    fks = cursor.fetchall()
                    for fk in fks:
                        if fk["REFERENCED_TABLE_NAME"] == "user_old":
                            cname = fk["CONSTRAINT_NAME"]
                            try:
                                cursor.execute(f"ALTER TABLE book_borrower DROP FOREIGN KEY `{cname}`")
                            except Exception as e2:
                                print("Note dropping legacy FK:", e2)
                    # Optionally add FK to user(user_id) (ignore if fails)
                    try:
                        cursor.execute(
                            """
                            ALTER TABLE book_borrower
                            ADD CONSTRAINT fk_book_borrower_user
                            FOREIGN KEY (user_id) REFERENCES user(user_id)
                            ON DELETE SET NULL
                            """
                        )
                    except Exception as e3:
                        print("Note adding FK fk_book_borrower_user:", e3)
                except Exception as e:
                    print("Schema note (book_borrower FKs):", e)
            except Exception as e:
                print("Schema note (book_borrower columns):", e)

            # Seed: Gatsby RFID card -> book record (idempotent)
            try:
                cursor.execute("SELECT book_id FROM books WHERE rfid_uid=%s", ("D5B93B03",))
                if not cursor.fetchone():
                    cursor.execute(
                        """
                        INSERT INTO books (rfid_uid, title, author, isbn, category, year_published, total_copies, available_copies)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            "D5B93B03",
                            "The Great Gatsby",
                            "F. Scott Fitzgerald",
                            "978-0-7432-7356-5",
                            "Fiction",
                            1925,
                            1,
                            1,
                        ),
                    )
            except Exception as e:
                print("Schema note (seed books):", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Ensure tables exist before RFID thread starts
ensure_schema()

def start_rfid_thread():
    global RFID_THREAD_STARTED
    if RFID_THREAD_STARTED:
        return
    RFID_THREAD_STARTED = True
    threading.Thread(target=read_rfid, daemon=True).start()

@app.route("/view_user/<int:user_id>")
def view_user(user_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, name, email, rfid_uid FROM user WHERE user_id=%s", (user_id,))
            user = cursor.fetchone()
    finally:
        conn.close()
    if not user:
        flash("User not found.")
        return redirect(url_for("dashboardAdmin_"))

    # Render a read-only view of the user's account
    return render_template("view_user.html", user=user)

@app.route("/blue_key_alert")
def get_blue_key_alert():
    """
    Returns JSON info if blue key card was scanned.
    After reading, it resets the alert so it triggers only once.
    """
    global blue_key_alert
    if blue_key_alert:
        alert = blue_key_alert
        blue_key_alert = None  # reset after notifying
        # Back-compat: some pages expect `user` object
        return jsonify({"alert": True, "kind": alert.get("kind"), "user": alert})
    return jsonify({"alert": False})

@app.route("/rfid")
def rfid():
    """Return the latest scanned RFID UID."""
    # Return a scan sequence id so the frontend can react to repeated scans
    return jsonify(
        {
            "uid": latest_scan_event.get("uid"),
            "seq": latest_scan_event.get("seq", 0),
            "is_blue_key": bool(latest_scan_event.get("is_blue_key")),
        }
    )


@app.route("/rfid_admin_login")
def rfid_admin_login():
    """
    Bypass admin login when the blue key card is scanned.
    """
    global latest_uid
    uid = latest_uid
    latest_uid = None  # consume

    if uid != BLUE_KEY_UID:
        flash("Blue key not detected.")
        return redirect(url_for("loginAdmin_page"))

    session["admin_id"] = 0
    session["admin_name"] = "Blue Key Admin"
    session["last_uid"] = uid
    return redirect(url_for("dashboardAdmin_"))


@app.route("/rfid_user")
def rfid_user():
    """
    Lookup a user based on the latest scanned RFID (or an explicit uid param)
    and return basic info for the dashboard/frontend.
    """
    uid = request.args.get("uid") or latest_uid

    if not uid:
        return jsonify({"found": False, "uid": None, "user": None})

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Assumes an `rfid_uid` column on the `user` table
            cursor.execute(
                "SELECT user_id, name, email, rfid_uid FROM user WHERE rfid_uid=%s",
                (uid,),
            )
            user = cursor.fetchone()
    finally:
        conn.close()

    return jsonify({"found": bool(user), "uid": uid, "user": user})


@app.route("/rfid_login")
def rfid_login():
    global latest_uid
    uid = latest_uid  # UID read from Arduino
    # Consume the UID so we don't redirect-loop on the login page
    latest_uid = None

    if not uid:
        flash("No RFID scanned yet. Please scan your card.")
        return redirect(url_for("login_page"))

    uid = uid.upper()
    if uid == BLUE_KEY_UID:
        return redirect(url_for("rfid_admin_login"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Look for user with this RFID UID
            cursor.execute(
                "SELECT user_id, name FROM user WHERE rfid_uid=%s",
                (uid,)
            )
            user = cursor.fetchone()
    finally:
        conn.close()
    if not user:
        flash("RFID card not registered. Please log in with email/password.")
        return redirect(url_for("login_page"))

    # Set session info
    session["user_id"] = user["user_id"]
    session["user_name"] = user["name"]
    session["last_uid"] = uid

    # Redirect to user dashboard
    return redirect(url_for("dashboardUser_"))  


@app.route("/")
def landing_page():
    return render_template("Welcome.html")


@app.route("/signup")
def signup_page():
    return render_template("signup.html")


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("last_uid", None)
    flash("Logged out.")
    return redirect(url_for("login_page"))


@app.route("/logout_admin")
def logout_admin():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    flash("Admin logged out.")
    return redirect(url_for("loginAdmin_page"))


@app.route("/forgot_password")
def forgot_password():
    # Placeholder page (real email reset can be added later)
    return render_template("forgot_password.html")


@app.route("/contact_admin")
def contact_admin():
    return render_template("contact_admin.html")

@app.route('/loginAdmin_page')
def loginAdmin_page():
    return render_template('loginAdmin.html')

@app.route("/signupAdmin_page")
def signupAdmin_page():
    return render_template("signupAdmin.html")

@app.route('/dashboardAdmin_page')
def dashboardAdmin_page():
    return redirect(url_for('dashboardAdmin_'))

@app.route('/dashboardAdmin')
def dashboardAdmin_():
    # Admin dashboard – show live counts from DB
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM user")
            total_users = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM rfid_scans")
            total_scans = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM rfid_scans WHERE uid=%s", (BLUE_KEY_UID,))
            blue_key_scans = cursor.fetchone()["total"]

            # how many distinct users scanned (registered cards only)
            cursor.execute("SELECT COUNT(DISTINCT user_id) AS total FROM rfid_scans WHERE user_id IS NOT NULL")
            unique_users_scanned = cursor.fetchone()["total"]

            # Activity (real)
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM book_borrower
                WHERE borrow_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """
            )
            checkouts_30d = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM book_borrower
                WHERE returned_at IS NOT NULL AND returned_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """
            )
            returns_30d = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM rfid_scans
                WHERE scanned_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """
            )
            scans_30d = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT COUNT(DISTINCT user_id) AS total
                FROM book_borrower
                WHERE borrow_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """
            )
            active_borrowers_30d = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT uid, COUNT(*) AS total
                FROM rfid_scans
                WHERE scanned_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                GROUP BY uid
                ORDER BY total DESC
                LIMIT 5
                """
            )
            top_uids = cursor.fetchall()
    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_scans=total_scans,
        blue_key_scans=blue_key_scans,
        unique_users_scanned=unique_users_scanned,
        blue_key_uid=BLUE_KEY_UID,
        checkouts_30d=checkouts_30d,
        returns_30d=returns_30d,
        scans_30d=scans_30d,
        active_borrowers_30d=active_borrowers_30d,
        top_uids=top_uids,
    )

@app.route('/dashboardUser_page')
def dashboardUser_page():
    return redirect(url_for('dashboardUser_'))

@app.route('/books_page')
def books_page():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT book_id, rfid_uid, title, author, isbn, category, year_published,
                       total_copies, available_copies
                FROM books
                ORDER BY created_at DESC, book_id DESC
                """
            )
            books = cursor.fetchall()
    finally:
        conn.close()
    return render_template("books.html", books=books)

@app.route('/members_page')
def members_page():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Support both schemas: id/username/password and the newer name/email columns
            cursor.execute("SHOW COLUMNS FROM admin")
            cols = {row["Field"] for row in cursor.fetchall()}
            id_col = "admin_id" if "admin_id" in cols else "id"
            name_expr = "name" if "name" in cols else "username"
            email_expr = "email" if "email" in cols else "username"
            cursor.execute(
                f"SELECT {id_col} AS id, {name_expr} AS name, {email_expr} AS email FROM admin ORDER BY {name_expr} ASC"
            )
            admins = cursor.fetchall()
    finally:
        conn.close()
    return render_template("members.html", admins=admins)


@app.route("/admin/members/<int:admin_id>/delete", methods=["POST"])
def admin_member_delete(admin_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Delete by either admin_id or id, depending on schema
            cursor.execute("SHOW COLUMNS FROM admin")
            cols = {row["Field"] for row in cursor.fetchall()}
            id_col = "admin_id" if "admin_id" in cols else "id"
            cursor.execute(f"DELETE FROM admin WHERE {id_col}=%s", (admin_id,))
    finally:
        conn.close()
    flash("Admin removed.")
    return redirect(url_for("members_page"))

@app.route("/checkout_page")
def checkout_page():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, name, email FROM user ORDER BY name ASC")
            users = cursor.fetchall()

            cursor.execute(
                """
                SELECT bb.id, bb.user_id, u.name AS user_name, u.email AS user_email,
                       bb.book_id, bb.book_title, bb.author,
                       bb.borrow_date, bb.due_date, bb.returned_at, bb.status
                FROM book_borrower bb
                LEFT JOIN user u ON u.user_id = bb.user_id
                WHERE bb.status IN ('Borrowed','Overdue')
                ORDER BY bb.borrow_date DESC, bb.id DESC
                LIMIT 200
                """
            )
            active = cursor.fetchall()

            cursor.execute(
                """
                SELECT bb.id, bb.user_id, u.name AS user_name, u.email AS user_email,
                       bb.book_id, bb.book_title, bb.author,
                       bb.borrow_date, bb.due_date, bb.returned_at, bb.status
                FROM book_borrower bb
                LEFT JOIN user u ON u.user_id = bb.user_id
                WHERE bb.status = 'Returned'
                ORDER BY bb.returned_at DESC, bb.id DESC
                LIMIT 200
                """
            )
            returned = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) AS total FROM book_borrower WHERE status IN ('Borrowed','Overdue')")
            currently_checked_out = cursor.fetchone()["total"]
            cursor.execute("SELECT COUNT(*) AS total FROM book_borrower WHERE status='Overdue'")
            overdue_books = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM book_borrower
                WHERE status='Returned' AND returned_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """
            )
            returned_last_30 = cursor.fetchone()["total"]
    finally:
        conn.close()

    return render_template(
        "checkout.html",
        users=users,
        active=active,
        returned=returned,
        currently_checked_out=currently_checked_out,
        overdue_books=overdue_books,
        returned_last_30=returned_last_30,
    )


@app.route("/api/book_by_uid")
def api_book_by_uid():
    uid = (request.args.get("uid") or "").strip().upper()
    if not uid:
        return jsonify({"found": False, "book": None})
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT book_id, rfid_uid, title, author, isbn, category, year_published,
                       total_copies, available_copies
                FROM books
                WHERE rfid_uid=%s
                """,
                (uid,),
            )
            book = cursor.fetchone()
    finally:
        conn.close()
    return jsonify({"found": bool(book), "book": book})


@app.route("/admin/books/create", methods=["GET", "POST"])
def admin_books_create():
    if request.method == "POST":
        rfid_uid = (request.form.get("rfid_uid") or "").strip().upper()
        title = (request.form.get("title") or "").strip()
        author = (request.form.get("author") or "").strip()
        isbn = (request.form.get("isbn") or "").strip() or None
        category = (request.form.get("category") or "").strip() or None
        year_published = request.form.get("year_published") or None
        total_copies = int(request.form.get("total_copies") or 1)

        if not rfid_uid or not title or not author:
            return render_template("book_form.html", mode="create", error="RFID UID, title, and author are required.", book=request.form)

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO books (rfid_uid, title, author, isbn, category, year_published, total_copies, available_copies, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    """,
                    (rfid_uid, title, author, isbn, category, year_published, total_copies, total_copies),
                )
        except Exception as e:
            return render_template("book_form.html", mode="create", error=str(e), book=request.form)
        finally:
            conn.close()

        return redirect(url_for("books_page"))

    return render_template("book_form.html", mode="create", book={})


@app.route("/admin/books/<int:book_id>/edit", methods=["GET", "POST"])
def admin_books_edit(book_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM books WHERE book_id=%s", (book_id,))
            book = cursor.fetchone()
            if not book:
                flash("Book not found.")
                return redirect(url_for("books_page"))

            if request.method == "POST":
                rfid_uid = (request.form.get("rfid_uid") or "").strip().upper()
                title = (request.form.get("title") or "").strip()
                author = (request.form.get("author") or "").strip()
                isbn = (request.form.get("isbn") or "").strip() or None
                category = (request.form.get("category") or "").strip() or None
                year_published = request.form.get("year_published") or None
                total_copies = int(request.form.get("total_copies") or book.get("total_copies") or 1)
                available_copies = int(request.form.get("available_copies") or book.get("available_copies") or 0)

                if not rfid_uid or not title or not author:
                    return render_template("book_form.html", mode="edit", error="RFID UID, title, and author are required.", book={**book, **request.form})

                if available_copies > total_copies:
                    available_copies = total_copies

                cursor.execute(
                    """
                    UPDATE books
                    SET rfid_uid=%s, title=%s, author=%s, isbn=%s, category=%s, year_published=%s,
                        total_copies=%s, available_copies=%s, updated_at=NOW()
                    WHERE book_id=%s
                    """,
                    (rfid_uid, title, author, isbn, category, year_published, total_copies, available_copies, book_id),
                )
                flash("Book updated.")
                return redirect(url_for("books_page"))
    finally:
        conn.close()

    return render_template("book_form.html", mode="edit", book=book)


@app.route("/admin/books/<int:book_id>/delete", methods=["POST"])
def admin_books_delete(book_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM books WHERE book_id=%s", (book_id,))
    finally:
        conn.close()
    flash("Book deleted.")
    return redirect(url_for("books_page"))


@app.route("/admin/checkout/create", methods=["POST"])
def admin_checkout_create():
    user_id = request.form.get("user_id")
    book_uid = (request.form.get("book_uid") or "").strip().upper()
    if not user_id or not book_uid:
        flash("Select a member and scan a book RFID.")
        return redirect(url_for("checkout_page"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM books WHERE rfid_uid=%s", (book_uid,))
            book = cursor.fetchone()
            if not book:
                flash("Book not found for that RFID.")
                return redirect(url_for("checkout_page"))
            if (book.get("available_copies") or 0) <= 0:
                flash("This book is not available.")
                return redirect(url_for("checkout_page"))

            borrow_date = datetime.now()
            due_date = borrow_date + timedelta(days=7)

            cursor.execute(
                """
                INSERT INTO book_borrower
                  (user_id, book_id, book_title, author, borrow_date, due_date, status)
                VALUES
                  (%s,%s,%s,%s,%s,%s,'Borrowed')
                """,
                (user_id, book["book_id"], book["title"], book["author"], borrow_date, due_date),
            )

            cursor.execute(
                "UPDATE books SET available_copies = GREATEST(available_copies - 1, 0), updated_at=NOW() WHERE book_id=%s",
                (book["book_id"],),
            )
    finally:
        conn.close()

    flash(f"Checked out: {book_uid}")
    return redirect(url_for("checkout_page"))

@app.route("/borrowing")
def borrowing_page():
    return render_template("borrowing.html")


@app.route('/loginAdmin_process', methods=['POST'])
def loginAdmin_process():
    login_value = (request.form.get('email') or "").strip()
    password = request.form.get('password') or ""
    if not login_value or not password:
        return render_template('loginAdmin.html', error="Please enter your credentials.")

    admin_cols = get_table_columns("admin")
    where_col = "email" if "email" in admin_cols else ("username" if "username" in admin_cols else None)
    id_col = "admin_id" if "admin_id" in admin_cols else ("id" if "id" in admin_cols else None)
    name_col = "name" if "name" in admin_cols else ("username" if "username" in admin_cols else None)

    if not where_col or not id_col:
        return render_template('loginAdmin.html', error="Admin table schema is not supported.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM admin WHERE `{where_col}`=%s AND `password`=%s",
                (login_value, password),
            )
            account = cursor.fetchone()
            # Back-compat: if we have email column but old rows used username only
            if not account and where_col == "email" and "username" in admin_cols:
                cursor.execute(
                    "SELECT * FROM admin WHERE `username`=%s AND `password`=%s",
                    (login_value, password),
                )
                account = cursor.fetchone()
    finally:
        conn.close()

    if account:
        session['admin_id'] = account.get(id_col)
        session['admin_name'] = account.get(name_col) if name_col else None
        return redirect(url_for('dashboardAdmin_'))

    return render_template('loginAdmin.html', error="Invalid credentials.")


@app.route('/login_process', methods=['POST'])
def login_process():
    email = request.form.get('email')
    password = request.form.get('password')

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM user WHERE email=%s AND password=%s", (email, password))
            account = cursor.fetchone()
    finally:
        conn.close()

    if account:
        session['user_id'] = account['user_id']
        session['user_name'] = account['name']
        return redirect(url_for('dashboardUser_'))

    flash("Invalid credentials.")
    return redirect(url_for('login_page'))


@app.route('/signup_process', methods=['POST'])
def signup_process():
    name = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if password != confirm_password:
        flash("Passwords do not match.")
        return redirect(url_for('signup_page'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO user (name, email, password) VALUES (%s, %s, %s)",
                (name, email, password)
            )
    finally:
        conn.close()

    flash("Signup successful. Please log in.")
    return redirect(url_for('login_page'))


@app.route('/signupAdmin_process', methods=['GET', 'POST'])
def signupAdmin_process():
    if request.method == 'POST':
        name = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        access_code = request.form.get('access_code')

        if access_code != "PHINMAADMIN2026":
            return render_template('signupAdmin.html', error="Invalid Admin Access Code")

        if password != confirm_password:
            return render_template('signupAdmin.html', error="Passwords do not match")

        admin_cols = get_table_columns("admin")
        has_email = "email" in admin_cols
        has_name = "name" in admin_cols
        has_username = "username" in admin_cols

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Support both schemas:
                # - legacy: (username, password)
                # - newer: (name, email, password)
                if has_name and has_email:
                    cursor.execute(
                        "INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)",
                        (name, email, password),
                    )
                elif has_username:
                    # Use email as username if no email column exists
                    cursor.execute(
                        "INSERT INTO admin (username, password) VALUES (%s, %s)",
                        (email or name, password),
                    )
                else:
                    return render_template('signupAdmin.html', error="Admin table schema is not supported.")
        finally:
            conn.close()

        return redirect(url_for('loginAdmin_page'))

    return render_template('signupAdmin.html')


@app.route("/home_page")
def home_page():
    # Simple search landing page (no user listing)
    return render_template("Homepage.html", users=None, books=None, query=None)


@app.route('/dashboardUser_process')
def dashboardUser_():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user_id = session['user_id']

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, name, email FROM user WHERE user_id=%s", (user_id,))
            user_info = cursor.fetchone()

            cursor.execute(
                """
                SELECT scan_id, uid, scanned_at
                FROM rfid_scans
                WHERE user_id=%s
                ORDER BY scanned_at DESC
                LIMIT 5
                """,
                (user_id,),
            )
            recent_scans = cursor.fetchall()

            cursor.execute("""
                UPDATE book_borrower
                SET status='Overdue'
                WHERE user_id=%s AND status='Borrowed' AND due_date IS NOT NULL AND due_date < NOW()
            """, (user_id,))

            cursor.execute("SELECT COUNT(*) AS total FROM book_borrower WHERE user_id=%s", (user_id,))
            total_borrowed = cursor.fetchone()['total']
    finally:
        conn.close()

    return render_template(
        "dashboardUser.html",
        user_name=session.get("user_name"),
        user_info=user_info,
        total_borrowed=total_borrowed,
        last_uid=session.get("last_uid") or latest_uid,
        recent_scans=recent_scans,
    )


@app.route('/process_borrow', methods=['POST'])
def process_borrow():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user_id = session['user_id']
    book_uid = (request.form.get("book_uid") or "").strip().upper()
    book_title = (request.form.get('book_title') or "").strip() or None
    author = (request.form.get('author') or "").strip() or None

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM book_borrower
                WHERE user_id=%s AND status IN ('Borrowed','Overdue')
            """, (user_id,))
            
            if cursor.fetchone():
                flash("Return previous book first!")
                return redirect(url_for('dashboardUser_'))

            borrow_date = datetime.now()
            due_date = borrow_date + timedelta(days=7)

            book_id = None
            if book_uid:
                cursor.execute("SELECT * FROM books WHERE rfid_uid=%s", (book_uid,))
                book = cursor.fetchone()
                if not book:
                    flash("Book RFID not recognized.")
                    return redirect(url_for('dashboardUser_'))
                if (book.get("available_copies") or 0) <= 0:
                    flash("That book is not available.")
                    return redirect(url_for('dashboardUser_'))
                book_id = book["book_id"]
                book_title = book["title"]
                author = book["author"]
                cursor.execute(
                    "UPDATE books SET available_copies = GREATEST(available_copies - 1, 0), updated_at=NOW() WHERE book_id=%s",
                    (book_id,),
                )

            if not book_title:
                flash("Book title is required.")
                return redirect(url_for('dashboardUser_'))

            cursor.execute(
                """
                INSERT INTO book_borrower
                  (user_id, book_id, book_title, author, borrow_date, due_date, status)
                VALUES
                  (%s,%s,%s,%s,%s,%s,'Borrowed')
                """,
                (user_id, book_id, book_title, author, borrow_date, due_date),
            )
    finally:
        conn.close()

    flash("Book Borrowed!")
    return redirect(url_for('dashboardUser_'))


@app.route('/process_return', methods=['POST'])
def process_return():
    borrow_id = request.form.get('borrow_id') or request.form.get("id")
    if not borrow_id:
        flash("Missing borrow id.")
        return redirect(url_for('dashboardUser_page'))

    try:
        borrow_id_int = int(borrow_id)
    except (TypeError, ValueError):
        flash("Invalid borrow id.")
        return redirect(url_for('dashboardUser_page'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT book_id FROM book_borrower WHERE id=%s", (borrow_id_int,))
            row = cursor.fetchone()
            book_id = row["book_id"] if row else None

            cursor.execute(
                """
                UPDATE book_borrower
                SET status='Returned', returned_at=NOW()
                WHERE id=%s
                """,
                (borrow_id_int,),
            )

            if book_id:
                cursor.execute(
                    "UPDATE books SET available_copies = LEAST(available_copies + 1, total_copies), updated_at=NOW() WHERE book_id=%s",
                    (book_id,),
                )
    finally:
        conn.close()

    flash("Book returned successfully!")
    return redirect(url_for('dashboardUser_page'))


@app.route("/admin/checkout/return", methods=["POST"])
def admin_checkout_return():
    borrow_id = request.form.get("borrow_id") or request.form.get("id")
    if not borrow_id:
        flash("Missing borrow id.")
        return redirect(url_for("checkout_page"))

    try:
        borrow_id_int = int(borrow_id)
    except (TypeError, ValueError):
        flash("Invalid borrow id.")
        return redirect(url_for("checkout_page"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT book_id FROM book_borrower WHERE id=%s", (borrow_id_int,))
            row = cursor.fetchone()
            book_id = row["book_id"] if row else None

            cursor.execute(
                """
                UPDATE book_borrower
                SET status='Returned', returned_at=NOW()
                WHERE id=%s
                """,
                (borrow_id_int,),
            )

            if book_id:
                cursor.execute(
                    "UPDATE books SET available_copies = LEAST(available_copies + 1, total_copies), updated_at=NOW() WHERE book_id=%s",
                    (book_id,),
                )
    finally:
        conn.close()

    flash("Book marked as returned.")
    return redirect(url_for("checkout_page"))


@app.route("/search")
def book_search():
    query = request.args.get("q")

    if not query:
        return render_template("Homepage.html", books=None, query=query)

    books: list[dict] = []

    # Local catalog first (RFID-aware)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT title, author, rfid_uid
                FROM books
                WHERE title LIKE %s
                ORDER BY title ASC
                """,
                (f"%{query}%",),
            )
            local_books = cursor.fetchall()
    finally:
        conn.close()

    for b in local_books:
        books.append(
            {
                "title": b["title"],
                "authors": f"{b['author']}  •  RFID: {b['rfid_uid']}",
            }
        )

    # OpenLibrary results (remote, supplemental)
    try:
        url = "https://openlibrary.org/search.json"
        response = requests.get(url, params={"q": query}, timeout=5)
        data = response.json()

        for item in data.get("docs", []):
            title = item.get("title", "No Title")
            authors = ", ".join(item.get("author_name", ["Unknown Author"]))
            # Avoid duplicate titles we already showed from local DB
            if any(b["title"] == title for b in books):
                continue
            books.append(
                {
                    "title": title,
                    "authors": authors,
                }
            )
    except Exception as e:
        print("OpenLibrary search error:", e)

    return render_template("Homepage.html", books=books, query=query, users=None)

if __name__ == '__main__':
    ensure_schema()
    debug = True
    # Start RFID thread once:
    # - With Flask reloader (debug=True), only in the reloader child process.
    # - Without reloader (debug=False), start normally.
    if (not debug) or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_rfid_thread()
    app.run(debug=debug)