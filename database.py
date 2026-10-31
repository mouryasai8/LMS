import sqlite3
from models import LibraryError, DuplicateIDError


class DatabaseManager:
    def __init__(self, path="library_data.db"):
        self.path = path
        self.execute("""CREATE TABLE IF NOT EXISTS books (
            book_id INTEGER PRIMARY KEY, title TEXT, author TEXT, category TEXT,
            total_copies INTEGER, available_copies INTEGER, added_date TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS members (
            member_id INTEGER PRIMARY KEY, name TEXT, email TEXT,
            phone TEXT, member_type TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER REFERENCES books(book_id),
            member_id INTEGER REFERENCES members(member_id),
            issue_date TEXT, due_date TEXT, return_date TEXT,
            fine_amount REAL, status TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS librarians (
            username TEXT PRIMARY KEY, password_hash TEXT)""")
        self.execute("""CREATE TABLE IF NOT EXISTS member_accounts (
            username TEXT PRIMARY KEY, password_hash TEXT,
            member_id INTEGER REFERENCES members(member_id))""")

    def execute(self, query, params=()):
        """Run an INSERT / UPDATE / DELETE."""
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(query, params)
            conn.commit()
        except sqlite3.IntegrityError:
            raise DuplicateIDError("A record with this ID already exists")
        except sqlite3.Error as e:
            raise LibraryError(f"Database error: {e}")
        finally:
            conn.close()

    def fetch(self, query, params=()):
        """Run a SELECT and return all rows."""
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute(query, params).fetchall()
        except sqlite3.Error as e:
            raise LibraryError(f"Database error: {e}")
        finally:
            conn.close()
