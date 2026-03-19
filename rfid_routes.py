import os
import re
import time
import threading
from datetime import datetime

import serial
from flask import Blueprint, jsonify, redirect, session, flash, url_for

from db import get_db_connection


rfid_bp = Blueprint("rfid", __name__)


SERIAL_PORT = os.environ.get("RFID_SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.environ.get("RFID_SERIAL_BAUD", "9600"))
BLUE_KEY_UID = "3E76C301"
UID_PATTERN = re.compile(r"^[0-9A-F]{8,}$")

latest_uid: str | None = None
latest_scan_event: dict = {"seq": 0, "uid": None, "is_blue_key": False}
blue_key_alert: dict | None = None
_RFID_THREAD_STARTED = False


def normalize_uid(line: str) -> str | None:
    if not line:
        return None
    s = line.strip().upper()

    if UID_PATTERN.match(s):
        return s

    if "USER" in s and "ID" in s:
        parts = re.findall(r"\b[0-9A-F]{2}\b", s)
        if parts:
            joined = "".join(parts)
            if UID_PATTERN.match(joined):
                return joined
    return None


def _read_rfid():
    global latest_uid, latest_scan_event, blue_key_alert

    ser = None
    while True:
        if not ser:
            try:
                ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
                time.sleep(2)
                print(f"RFID Serial port {SERIAL_PORT} opened successfully")
            except Exception as e:
                print(f"RFID Serial error opening port: {e}")
                time.sleep(2)
                continue

        try:
            raw = ser.readline().decode(errors="ignore").strip()
            uid = normalize_uid(raw)
            if not uid:
                continue

            latest_uid = uid
            latest_scan_event = {
                "seq": (latest_scan_event.get("seq") or 0) + 1,
                "uid": uid,
                "is_blue_key": uid == BLUE_KEY_UID,
            }
            print("RFID UID:", uid)

            try:
                conn = get_db_connection()
                try:
                    with conn.cursor() as cursor:
                        user_id = None
                        try:
                            cursor.execute(
                                "SELECT user_id FROM user WHERE rfid_uid=%s",
                                (uid,),
                            )
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
                blue_key_alert = {"kind": "blue_key", "uid": uid}

        except Exception as e:
            print(f"RFID Serial read error: {e}")
            try:
                if ser:
                    ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(2)


def start_rfid_thread():
    global _RFID_THREAD_STARTED
    if _RFID_THREAD_STARTED:
        return
    _RFID_THREAD_STARTED = True
    threading.Thread(target=_read_rfid, daemon=True).start()


@rfid_bp.route("/rfid")
def rfid():
    return jsonify(
        {
            "uid": latest_scan_event.get("uid"),
            "seq": latest_scan_event.get("seq", 0),
            "is_blue_key": bool(latest_scan_event.get("is_blue_key")),
        }
    )


@rfid_bp.route("/blue_key_alert")
def get_blue_key_alert():
    global blue_key_alert
    if blue_key_alert:
        alert = blue_key_alert
        blue_key_alert = None
        return jsonify({"alert": True, "kind": alert.get("kind"), "user": alert})
    return jsonify({"alert": False})


@rfid_bp.route("/rfid_admin_login")
def rfid_admin_login():
    global latest_uid
    uid = latest_uid
    latest_uid = None

    if uid != BLUE_KEY_UID:
        flash("Blue key not detected.")
        return redirect(url_for("auth.loginAdmin_page"))

    session["admin_id"] = 0
    session["admin_name"] = "Blue Key Admin"
    session["last_uid"] = uid
    return redirect(url_for("admin.dashboardAdmin_"))


@rfid_bp.route("/rfid_user")
def rfid_user():
    uid = (  # type: ignore[assignment]
        os.environ.get("RFID_TEST_UID")
        or os.environ.get("RFID_UID")
        or latest_uid
    )

    if not uid:
        return jsonify({"found": False, "uid": None, "user": None})

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, name, email, rfid_uid FROM user WHERE rfid_uid=%s",
                (uid,),
            )
            user = cursor.fetchone()
    finally:
        conn.close()

    return jsonify({"found": bool(user), "uid": uid, "user": user})


@rfid_bp.route("/rfid_login")
def rfid_login():
    global latest_uid
    uid = latest_uid
    latest_uid = None

    if not uid:
        flash("No RFID scanned yet. Please scan your card.")
        return redirect(url_for("auth.login_page"))

    uid = uid.upper()
    if uid == BLUE_KEY_UID:
        return redirect(url_for("rfid.rfid_admin_login"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, name FROM user WHERE rfid_uid=%s",
                (uid,),
            )
            user = cursor.fetchone()
    finally:
        conn.close()

    if not user:
        flash("RFID card not registered. Please log in with email/password.")
        return redirect(url_for("auth.login_page"))

    session["user_id"] = user["user_id"]
    session["user_name"] = user["name"]
    session["last_uid"] = uid

    return redirect(url_for("user.dashboardUser_"))


@rfid_bp.route("/view_user/<int:user_id>")
def view_user(user_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT user_id, name, email, rfid_uid FROM user WHERE user_id=%s",
                (user_id,),
            )
            user = cursor.fetchone()
    finally:
        conn.close()

    from flask import render_template

    if not user:
        flash("User not found.")
        return redirect(url_for("admin.dashboardAdmin_"))

    return render_template("view_user.html", user=user)

