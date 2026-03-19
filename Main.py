from flask import Flask

from auth_routes import auth_bp
from admin_routes import admin_bp
from user_routes import user_bp
from book_routes import books_bp
from rfid_routes import rfid_bp, start_rfid_thread


app = Flask(__name__)
app.secret_key = "mahalpakita143"

# Register blueprints (no URL prefix so existing routes stay the same)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)
app.register_blueprint(books_bp)
app.register_blueprint(rfid_bp)

if __name__ == "__main__":
    debug = True
    # Only start RFID thread in the main process
    import os

    if (not debug) or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_rfid_thread()
    app.run(debug=debug)