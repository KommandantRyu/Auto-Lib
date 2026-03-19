from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
)

from db import get_db_connection
from rfid_routes import latest_uid


user_bp = Blueprint("user", __name__)


@user_bp.route("/dashboardUser_page")
def dashboardUser_page():
    return redirect(url_for("user.dashboardUser_"))


@user_bp.route("/dashboardUser_process")
def dashboardUser_():
    if "user_id" not in session:
        return redirect(url_for("auth.login_page"))

    user_id = session["user_id"]

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, name, email FROM user WHERE user_id=%s",
                (user_id,),
            )
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

            cursor.execute(
                """
                UPDATE book_borrower
                SET status='Overdue'
                WHERE user_id=%s AND status='Borrowed' AND due_date IS NOT NULL AND due_date < NOW()
                """,
                (user_id,),
            )

            cursor.execute(
                "SELECT COUNT(*) AS total FROM book_borrower WHERE user_id=%s",
                (user_id,),
            )
            total_borrowed = cursor.fetchone()["total"]
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


@user_bp.route("/process_borrow", methods=["POST"])
def process_borrow():
    if "user_id" not in session:
        return redirect(url_for("auth.login_page"))

    user_id = session["user_id"]
    book_uid = (request.form.get("book_uid") or "").strip().upper()
    book_title = (request.form.get("book_title") or "").strip() or None
    author = (request.form.get("author") or "").strip() or None

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM book_borrower
                WHERE user_id=%s AND status IN ('Borrowed','Overdue')
                """,
                (user_id,),
            )

            if cursor.fetchone():
                flash("Return previous book first!")
                return redirect(url_for("user.dashboardUser_"))

            borrow_date = datetime.now()
            due_date = borrow_date + timedelta(days=7)

            book_id = None
            if book_uid:
                cursor.execute(
                    "SELECT * FROM books WHERE rfid_uid=%s",
                    (book_uid,),
                )
                book = cursor.fetchone()
                if not book:
                    flash("Book RFID not recognized.")
                    return redirect(url_for("user.dashboardUser_"))
                if (book.get("available_copies") or 0) <= 0:
                    flash("That book is not available.")
                    return redirect(url_for("user.dashboardUser_"))
                book_id = book["book_id"]
                book_title = book["title"]
                author = book["author"]
                cursor.execute(
                    "UPDATE books SET available_copies = GREATEST(available_copies - 1, 0), updated_at=NOW() WHERE book_id=%s",
                    (book_id,),
                )

            if not book_title:
                flash("Book title is required.")
                return redirect(url_for("user.dashboardUser_"))

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
    return redirect(url_for("user.dashboardUser_"))


@user_bp.route("/process_return", methods=["POST"])
def process_return():
    borrow_id = request.form.get("borrow_id") or request.form.get("id")
    if not borrow_id:
        flash("Missing borrow id.")
        return redirect(url_for("user.dashboardUser_page"))

    try:
        borrow_id_int = int(borrow_id)
    except (TypeError, ValueError):
        flash("Invalid borrow id.")
        return redirect(url_for("user.dashboardUser_page"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT book_id FROM book_borrower WHERE id=%s",
                (borrow_id_int,),
            )
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
    return redirect(url_for("user.dashboardUser_page"))


@user_bp.route("/borrowing")
def borrowing_page():
    return render_template("borrowing.html")

