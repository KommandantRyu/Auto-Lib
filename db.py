import pymysql


def get_db_connection():
    """Create a new DB connection (one per request/thread)."""
    return pymysql.connect(
        host="localhost",
        user="root",
        password="G@briel110406",
        database="library",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def get_table_columns(table_name: str) -> set[str]:
    """Return the set of column names for a given table."""
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

