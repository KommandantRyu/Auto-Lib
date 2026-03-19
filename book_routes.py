from flask import Blueprint, render_template, request, jsonify

import requests

from db import get_db_connection


books_bp = Blueprint("books", __name__)


@books_bp.route("/books_page")
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


@books_bp.route("/api/book_by_uid")
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


@books_bp.route("/search")
def book_search():
    query = request.args.get("q")

    if not query:
        return render_template("Homepage.html", books=None, query=query)

    books: list[dict] = []

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

    try:
        url = "https://openlibrary.org/search.json"
        response = requests.get(url, params={"q": query}, timeout=5)
        data = response.json()

        for item in data.get("docs", []):
            title = item.get("title", "No Title")
            authors = ", ".join(item.get("author_name", ["Unknown Author"]))
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

