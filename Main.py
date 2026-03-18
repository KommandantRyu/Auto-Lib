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
app.secret_key = "mahalpakita143"

SERIAL_PORT = os.environ.get("RFID_SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.environ.get("RFID_SERIAL_BAUD", "9600"))
BLUE_KEY_UID = "3E76C301"
UID_PATTERN = re.compile(r"^[0-9A-F]{8,}$")

connection = pymysql.connect(
    host="localhost",
    user="root",
    password="G@briel110406",
    database="library",
    cursorclass=pymysql.cursors.DictCursor,
)


def normalize_uid(line: str) -> str | None:
    """
    Arduino prints BOTH UID and other status messages.
    We accept only hex UID strings like: 3E76C301
    """
    if not line:
        return None
    s = line.strip().upper()
    if UID_PATTERN.match(s):
        return s
    return None

def read_rfid():
    global latest_uid

    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
        # When serial opens, Arduino UNO resets; give it time to boot.
        time.sleep(2.0)

        while True:
            if ser.in_waiting:
                raw = ser.readline().decode(errors="ignore").strip()
                uid = normalize_uid(raw)

                if uid:
                    latest_uid = uid
                    print("RFID UID:", uid)

                    # Log scan immediately (so Admin dashboard can count scans even before login)
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT user_id FROM user WHERE rfid_uid=%s",
                                (uid,),
                            )
                            u = cursor.fetchone()
                            user_id = u["user_id"] if u else None
                            cursor.execute(
                                "INSERT INTO rfid_scans (uid, user_id, scanned_at) VALUES (%s, %s, NOW())",
                                (uid, user_id),
                            )
                            connection.commit()
                    except Exception as e:
                        print("RFID DB log error:", e)

    except Exception as e:
        print("RFID Error:", e)


def ensure_schema():
    """
    Keep schema requirements minimal:
    - `user` table should have `rfid_uid` column for RFID login (already assumed in code).
    - Create `rfid_scans` table for audit trail shown in dashboard.
    """
    with connection.cursor() as cursor:
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
        connection.commit()

        # Ensure user.rfid_uid exists (best-effort; ignore if no privileges)
        try:
            cursor.execute("SHOW COLUMNS FROM user LIKE 'rfid_uid'")
            col = cursor.fetchone()
            if not col:
                cursor.execute("ALTER TABLE user ADD COLUMN rfid_uid VARCHAR(255) NULL")
                cursor.execute("CREATE INDEX idx_user_rfid_uid ON user (rfid_uid)")
                connection.commit()
        except Exception as e:
            # Don't crash the app if schema change isn't allowed
            print("Schema note (rfid_uid):", e)


# Ensure tables exist before RFID thread starts
ensure_schema()

@app.route("/view_user/<int:user_id>")
def view_user(user_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, name, email, rfid_uid FROM user WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
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
        return jsonify({"alert": True, "user": alert})
    return jsonify({"alert": False})

@app.route("/rfid")
def rfid():
    """Return the latest scanned RFID UID."""
    return jsonify({"uid": latest_uid})


@app.route("/rfid_user")
def rfid_user():
    """
    Lookup a user based on the latest scanned RFID (or an explicit uid param)
    and return basic info for the dashboard/frontend.
    """
    uid = request.args.get("uid") or latest_uid

    if not uid:
        return jsonify({"found": False, "uid": None, "user": None})

    with connection.cursor() as cursor:
        # Assumes an `rfid_uid` column on the `user` table
        cursor.execute(
            "SELECT user_id, name, email, rfid_uid FROM user WHERE rfid_uid=%s",
            (uid,),
        )
        user = cursor.fetchone()

    return jsonify({"found": bool(user), "uid": uid, "user": user})


@app.route("/rfid_login")
def rfid_login():
    uid = latest_uid  # UID read from Arduino

    if not uid:
        flash("No RFID scanned yet. Please scan your card.")
        return redirect(url_for("login_page"))

    uid = uid.upper()

    with connection.cursor() as cursor:
        # Look for user with this RFID UID
        cursor.execute(
            "SELECT user_id, name FROM user WHERE rfid_uid=%s",
            (uid,)
        )
        user = cursor.fetchone()
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
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM user")
        total_users = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM rfid_scans")
        total_scans = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM rfid_scans WHERE uid=%s", (BLUE_KEY_UID,))
        blue_key_scans = cursor.fetchone()["total"]

        # how many distinct users scanned (registered cards only)
        cursor.execute("SELECT COUNT(DISTINCT user_id) AS total FROM rfid_scans WHERE user_id IS NOT NULL")
        unique_users_scanned = cursor.fetchone()["total"]

    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_scans=total_scans,
        blue_key_scans=blue_key_scans,
        unique_users_scanned=unique_users_scanned,
        blue_key_uid=BLUE_KEY_UID,
    )

@app.route('/dashboardUser_page')
def dashboardUser_page():
    return redirect(url_for('dashboardUser_'))

@app.route('/books_page')
def books_page():
    return render_template("books.html")

@app.route('/members_page')
def members_page():
    return render_template("members.html",)

@app.route("/checkout_page")
def checkout_page():
    return render_template("checkout.html")

@app.route("/borrowing")
def borrowing_page():
    return render_template("borrowing.html")


@app.route('/loginAdmin_process', methods=['POST'])
def loginAdmin_process():
    email = request.form.get('email')
    password = request.form.get('password')

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM admin WHERE email=%s AND password=%s", (email, password))
        account = cursor.fetchone()

    if account:
        session['admin_id'] = account['admin_id']
        session['admin_name'] = account['name']
        return redirect(url_for('dashboardAdmin_'))

    return render_template('loginAdmin.html', error="Invalid email or password.")


@app.route('/login_process', methods=['POST'])
def login_process():
    email = request.form.get('email')
    password = request.form.get('password')

    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM user WHERE email=%s AND password=%s", (email, password))
        account = cursor.fetchone()

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

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO user (name, email, password) VALUES (%s, %s, %s)",
            (name, email, password)
        )
        connection.commit()

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

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)",
                (name, email, password)
            )
            connection.commit()

        return redirect(url_for('loginAdmin_page'))

    return render_template('signupAdmin.html')


@app.route("/home_page")
def home_page():
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM user")
        users = cursor.fetchall()

    return render_template("Homepage.html", users=users)


@app.route('/dashboardUser_process')
def dashboardUser_():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    user_id = session['user_id']

    with connection.cursor() as cursor:
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
            WHERE user_id=%s AND status='Borrowed' AND return_date < NOW()
        """, (user_id,))
        connection.commit()

        cursor.execute("SELECT COUNT(*) AS total FROM book_borrower WHERE user_id=%s", (user_id,))
        total_borrowed = cursor.fetchone()['total']

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
    book_title = request.form.get('book_title')
    author = request.form.get('author')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT * FROM book_borrower
            WHERE user_id=%s AND status IN ('Borrowed','Overdue')
        """, (user_id,))
        
        if cursor.fetchone():
            flash("Return previous book first!")
            return redirect(url_for('dashboardUser_'))

        borrow_date = datetime.now()
        due_date = borrow_date + timedelta(days=7)

        cursor.execute("""
            INSERT INTO book_borrower
            (user_id, book_title, author, borrow_date, return_date, status)
            VALUES (%s,%s,%s,%s,%s,'Borrowed')
        """, (user_id, book_title, author, borrow_date, due_date))

        connection.commit()

    flash("Book Borrowed!")
    return redirect(url_for('dashboardUser_'))


@app.route('/process_return', methods=['POST'])
def process_return():
    borrow_id = request.form['borrow_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE book_borrower
            SET status='Returned', return_date=NOW()
            WHERE borrow_id=%s
        """, (borrow_id,))
        connection.commit()

    flash("Book returned successfully!")
    return redirect(url_for('dashboardUser_page'))


@app.route("/search")
def book_search():
    query = request.args.get("q")

    if not query:
        return render_template("Homepage.html", books=None)

    url = "https://openlibrary.org/search.json"
    response = requests.get(url, params={"q": query})
    data = response.json()

    books = []
    for item in data.get("docs", []):
        books.append({
            "title": item.get("title", "No Title"),
            "authors": ", ".join(item.get("author_name", ["Unknown Author"]))
        })

    return render_template("Homepage.html", books=books, query=query)

threading.Thread(target=read_rfid, daemon=True).start()

if __name__ == '__main__':
    ensure_schema()
    threading.Thread(target=read_rfid, daemon=True).start()
    app.run(debug=True)