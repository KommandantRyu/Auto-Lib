from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
)

from db import get_db_connection, get_table_columns


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def landing_page():
    return render_template("Welcome.html")


@auth_bp.route("/signup")
def signup_page():
    return render_template("signup.html")


@auth_bp.route("/login")
def login_page():
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("last_uid", None)
    flash("Logged out.")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/logout_admin")
def logout_admin():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    flash("Admin logged out.")
    return redirect(url_for("auth.loginAdmin_page"))


@auth_bp.route("/forgot_password")
def forgot_password():
    return render_template("forgot_password.html")


@auth_bp.route("/contact_admin")
def contact_admin():
    return render_template("contact_admin.html")


@auth_bp.route("/loginAdmin_page")
def loginAdmin_page():
    return render_template("loginAdmin.html")


@auth_bp.route("/signupAdmin_page")
def signupAdmin_page():
    return render_template("signupAdmin.html")


@auth_bp.route("/loginAdmin_process", methods=["POST"])
def loginAdmin_process():
    login_value = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    if not login_value or not password:
        return render_template("loginAdmin.html", error="Please enter your credentials.")

    admin_cols = get_table_columns("admin")
    where_col = "email" if "email" in admin_cols else ("username" if "username" in admin_cols else None)
    id_col = "admin_id" if "admin_id" in admin_cols else ("id" if "id" in admin_cols else None)
    name_col = "name" if "name" in admin_cols else ("username" if "username" in admin_cols else None)

    if not where_col or not id_col:
        return render_template("loginAdmin.html", error="Admin table schema is not supported.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM admin WHERE `{where_col}`=%s AND `password`=%s",
                (login_value, password),
            )
            account = cursor.fetchone()
            if not account and where_col == "email" and "username" in admin_cols:
                cursor.execute(
                    "SELECT * FROM admin WHERE `username`=%s AND `password`=%s",
                    (login_value, password),
                )
                account = cursor.fetchone()
    finally:
        conn.close()

    if account:
        session["admin_id"] = account.get(id_col)
        session["admin_name"] = account.get(name_col) if name_col else None
        return redirect(url_for("admin.dashboardAdmin_"))

    return render_template("loginAdmin.html", error="Invalid credentials.")


@auth_bp.route("/login_process", methods=["POST"])
def login_process():
    email = request.form.get("email")
    password = request.form.get("password")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM user WHERE email=%s AND password=%s",
                (email, password),
            )
            account = cursor.fetchone()
    finally:
        conn.close()

    if account:
        session["user_id"] = account["user_id"]
        session["user_name"] = account["name"]
        return redirect(url_for("user.dashboardUser_"))

    flash("Invalid credentials.")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/signup_process", methods=["POST"])
def signup_process():
    name = request.form.get("username")
    email = request.form.get("email")
    password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")

    if password != confirm_password:
        flash("Passwords do not match.")
        return redirect(url_for("auth.signup_page"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO user (name, email, password) VALUES (%s, %s, %s)",
                (name, email, password),
            )
    finally:
        conn.close()

    flash("Signup successful. Please log in.")
    return redirect(url_for("auth.login_page"))


@auth_bp.route("/signupAdmin_process", methods=["GET", "POST"])
def signupAdmin_process():
    if request.method == "POST":
        name = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        access_code = request.form.get("access_code")

        if access_code != "PHINMAADMIN2026":
            return render_template("signupAdmin.html", error="Invalid Admin Access Code")

        if password != confirm_password:
            return render_template("signupAdmin.html", error="Passwords do not match")

        admin_cols = get_table_columns("admin")
        has_email = "email" in admin_cols
        has_name = "name" in admin_cols
        has_username = "username" in admin_cols

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if has_name and has_email:
                    cursor.execute(
                        "INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)",
                        (name, email, password),
                    )
                elif has_username:
                    cursor.execute(
                        "INSERT INTO admin (username, password) VALUES (%s, %s)",
                        (email or name, password),
                    )
                else:
                    return render_template(
                        "signupAdmin.html",
                        error="Admin table schema is not supported.",
                    )
        finally:
            conn.close()

        return redirect(url_for("auth.loginAdmin_page"))

    return render_template("signupAdmin.html")


@auth_bp.route("/home_page")
def home_page():
    return render_template("Homepage.html", users=None, books=None, query=None)

