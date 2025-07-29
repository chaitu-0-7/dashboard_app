from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import uuid
import os
from functools import wraps

# Configuration
SESSION_VALIDITY_DAYS = 2
MAX_FAILED_LOGIN_ATTEMPTS = 3
MAX_CONCURRENT_SESSIONS = 5 # User can have up to 5 active sessions

class AuthManager:
    def __init__(self, db):
        self.db = db
        self.users_collection = self.db.users
        self.sessions_collection = self.db.sessions

    def create_user(self, username, password):
        hashed_password = generate_password_hash(password)
        user_data = {
            "username": username,
            "password": hashed_password,
            "failed_login_attempts": 0,
            "locked_until": None,
            "created_at": datetime.now()
        }
        self.users_collection.insert_one(user_data)
        print(f"User '{username}' created successfully.")

    def get_user(self, username):
        return self.users_collection.find_one({"username": username})

    def verify_password(self, user, password):
        return check_password_hash(user["password"], password)

    def record_failed_login(self, username):
        user = self.get_user(username)
        if user:
            new_attempts = user.get("failed_login_attempts", 0) + 1
            update_data = {"$set": {"failed_login_attempts": new_attempts}}
            if new_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                # Lock account for a period (e.g., 1 hour)
                update_data["$set"]["locked_until"] = datetime.now() + timedelta(hours=1)
                print(f"User '{username}' locked due to too many failed attempts.")
            self.users_collection.update_one({"username": username}, update_data)
        return new_attempts

    def reset_failed_logins(self, username):
        self.users_collection.update_one({"username": username}, {"$set": {"failed_login_attempts": 0, "locked_until": None}})

    def is_account_locked(self, user):
        locked_until = user.get("locked_until")
        return locked_until and locked_until > datetime.now()

    def create_session(self, username):
        # Clean up old sessions if user exceeds MAX_CONCURRENT_SESSIONS
        existing_sessions = list(self.sessions_collection.find({"username": username}).sort("created_at", 1))
        if len(existing_sessions) >= MAX_CONCURRENT_SESSIONS:
            # Remove the oldest session
            self.sessions_collection.delete_one({"_id": existing_sessions[0]["_id"]})
            print(f"Removed oldest session for user '{username}'.")

        session_token = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=SESSION_VALIDITY_DAYS)
        session_data = {
            "username": username,
            "session_token": session_token,
            "created_at": datetime.now(),
            "expires_at": expires_at
        }
        self.sessions_collection.insert_one(session_data)
        return session_token

    def get_session(self, session_token):
        session = self.sessions_collection.find_one({"session_token": session_token})
        if session and session["expires_at"] > datetime.now():
            return session
        # If session is expired or not found, delete it
        if session:
            self.sessions_collection.delete_one({"_id": session["_id"]})
        return None

    def delete_session(self, session_token):
        self.sessions_collection.delete_one({"session_token": session_token})

# Decorator for protecting routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import session, redirect, url_for, flash, g
        if 'session_token' not in session or not g.user:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
