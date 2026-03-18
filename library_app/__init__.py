from flask import Flask
from .blueprints.main import main_bp
from .blueprints.user import user_bp
from .blueprints.admin import admin_bp
from .blueprints.rfid_routes import rfid_bp
from .rfid import ensure_schema, start_rfid_thread

def create_app():
    app = Flask(__name__)
    app.secret_key = "mahalpakita143"

    ensure_schema()
    start_rfid_thread()

    app.register_blueprint(main_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(rfid_bp)

    return app