from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
)

from db import get_db_connection


admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/dashboardAdmin_page")
def dashboardAdmin_page():
    return redirect(url_for("admin.dashboardAdmin_"))


@admin_bp.route("/dashboardAdmin")
def dashboardAdmin_():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM user")
            total_users = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS total FROM rfid_scans")
            total_scans = cursor.fetchone()["total"]

            from rfid_routes import BLUE_KEY_UID

            cursor.execute(
                "SELECT COUNT(*) AS total FROM rfid_scans WHERE uid=%s",
                (BLUE_KEY_UID,),
            )
            blue_key_scans = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(DISTINCT user_id) AS total FROM rfid_scans WHERE user_id IS NOT NULL"
            )
            unique_users_scanned = cursor.fetchone()["total"]

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

    from rfid_routes import BLUE_KEY_UID

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


@admin_bp.route("/members_page")
def members_page():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
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


@admin_bp.route("/admin/members/<int:admin_id>/delete", methods=["POST"])
def admin_member_delete(admin_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM admin")
            cols = {row["Field"] for row in cursor.fetchall()}
            id_col = "admin_id" if "admin_id" in cols else "id"
            cursor.execute(f"DELETE FROM admin WHERE {id_col}=%s", (admin_id,))
    finally:
        conn.close()
    flash("Admin removed.")
    return redirect(url_for("admin.members_page"))


@admin_bp.route("/checkout_page")
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

            cursor.execute(
                "SELECT COUNT(*) AS total FROM book_borrower WHERE status IN ('Borrowed','Overdue')"
            )
            currently_checked_out = cursor.fetchone()["total"]
            cursor.execute(
                "SELECT COUNT(*) AS total FROM book_borrower WHERE status='Overdue'"
            )
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


@admin_bp.route("/admin/checkout/create", methods=["POST"])
def admin_checkout_create():
    user_id = request.form.get("user_id")
    book_uid = (request.form.get("book_uid") or "").strip().upper()
    if not user_id or not book_uid:
        flash("Select a member and scan a book RFID.")
        return redirect(url_for("admin.checkout_page"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM books WHERE rfid_uid=%s", (book_uid,))
            book = cursor.fetchone()
            if not book:
                flash("Book not found for that RFID.")
                return redirect(url_for("admin.checkout_page"))
            if (book.get("available_copies") or 0) <= 0:
                flash("This book is not available.")
                return redirect(url_for("admin.checkout_page"))

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
    return redirect(url_for("admin.checkout_page"))


@admin_bp.route("/admin/checkout/return", methods=["POST"])
def admin_checkout_return():
    borrow_id = request.form.get("borrow_id") or request.form.get("id")
    if not borrow_id:
        flash("Missing borrow id.")
        return redirect(url_for("admin.checkout_page"))

    try:
        borrow_id_int = int(borrow_id)
    except (TypeError, ValueError):
        flash("Invalid borrow id.")
        return redirect(url_for("admin.checkout_page"))

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

    flash("Book marked as returned.")
    return redirect(url_for("admin.checkout_page"))

