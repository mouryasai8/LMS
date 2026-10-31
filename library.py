from datetime import date, datetime, timedelta
import csv

from database import DatabaseManager
from models import (Book, Librarian, Transaction, make_member, hash_password,
                    LibraryError, DuplicateIDError, InvalidBookError, InvalidMemberError)

LIBRARIAN_CODE = "LIB2026"  # needed to create a librarian account


class Library:
    def __init__(self, db_path="library_data.db"):
        self.db = DatabaseManager(db_path)

    # ---------- accounts ----------

    def check_new_login(self, username, password):
        username = username.strip()
        if len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(password) < 4:
            raise ValueError("Password must be at least 4 characters")
        taken = (self.db.fetch("SELECT 1 FROM librarians WHERE username = ?", (username,))
                 or self.db.fetch("SELECT 1 FROM member_accounts WHERE username = ?", (username,)))
        if taken:
            raise DuplicateIDError("That username is already taken")
        return username

    def create_librarian(self, username, password, code):
        if code != LIBRARIAN_CODE:
            raise LibraryError("Wrong librarian code")
        username = self.check_new_login(username, password)
        self.db.execute("INSERT INTO librarians VALUES (?, ?)",
                        (username, hash_password(password)))

    def create_member_account(self, member, username, password):
        username = self.check_new_login(username, password)
        self.add_member(member)
        self.db.execute("INSERT INTO member_accounts VALUES (?, ?, ?)",
                        (username, hash_password(password), member.member_id))

    def login(self, username, password):
        """Returns a Librarian, Student or Faculty object."""
        username = username.strip()
        rows = self.db.fetch("SELECT * FROM librarians WHERE username = ?", (username,))
        if rows:
            librarian = Librarian(*rows[0])
            if librarian.check_password(password):
                return librarian
        else:
            rows = self.db.fetch("SELECT * FROM member_accounts WHERE username = ?", (username,))
            if rows and rows[0][1] == hash_password(password):
                return self.get_member(rows[0][2])
        raise LibraryError("Wrong username or password")

    # ---------- books ----------

    def add_book(self, book):
        added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute("INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (book.book_id, book.title, book.author, book.category,
                         book.copies, book.available, added))

    def get_book(self, book_id):
        rows = self.db.fetch("SELECT * FROM books WHERE book_id = ?", (book_id,))
        if not rows:
            raise InvalidBookError(f"No book found with ID {book_id}")
        return Book(*rows[0])

    def update_book(self, book):
        old = self.get_book(book.book_id)  # raises an error if the ID does not exist
        on_loan = old.copies - old.available
        if book.copies < on_loan:
            raise LibraryError(f"{on_loan} copies are on loan, so copies cannot be less than {on_loan}")
        self.db.execute("""UPDATE books SET title = ?, author = ?, category = ?,
                           total_copies = ?, available_copies = ? WHERE book_id = ?""",
                        (book.title, book.author, book.category,
                         book.copies, book.copies - on_loan, book.book_id))

    def delete_book(self, book_id):
        book = self.get_book(book_id)
        if book.available < book.copies:
            raise LibraryError("Some copies are on loan, so this book cannot be deleted")
        self.db.execute("DELETE FROM books WHERE book_id = ?", (book_id,))

    def search_books(self, text=""):
        """Search by ID, title, author or category. Empty text returns every book."""
        like = f"%{text}%"
        return self.db.fetch(
            """SELECT * FROM books
               WHERE CAST(book_id AS TEXT) LIKE ? OR title LIKE ?
                  OR author LIKE ? OR category LIKE ?
               ORDER BY book_id""", (like, like, like, like))

    def recent_books(self):
        return self.db.fetch(
            """SELECT book_id, title, author, category, added_date
               FROM books ORDER BY added_date DESC LIMIT 5""")

    def popular_books(self):
        return self.db.fetch(
            """SELECT b.book_id, b.title, b.author, COUNT(*) AS times_issued
               FROM transactions t JOIN books b ON t.book_id = b.book_id
               GROUP BY b.book_id ORDER BY times_issued DESC LIMIT 5""")

    # ---------- members ----------

    def add_member(self, member):
        self.db.execute("INSERT INTO members VALUES (?, ?, ?, ?, ?)",
                        (member.member_id, member.name, member.email,
                         member.phone, member.member_type()))

    def get_member(self, member_id):
        rows = self.db.fetch("SELECT * FROM members WHERE member_id = ?", (member_id,))
        if not rows:
            raise InvalidMemberError(f"No member found with ID {member_id}")
        return make_member(*rows[0])

    def update_member(self, member):
        self.get_member(member.member_id)
        self.db.execute("""UPDATE members SET name = ?, email = ?, phone = ?, member_type = ?
                           WHERE member_id = ?""",
                        (member.name, member.email, member.phone,
                         member.member_type(), member.member_id))

    def delete_member(self, member_id):
        self.get_member(member_id)
        open_loans = self.db.fetch(
            "SELECT 1 FROM transactions WHERE member_id = ? AND status = 'Issued'", (member_id,))
        if open_loans:
            raise LibraryError("This member still has issued books")
        self.db.execute("DELETE FROM member_accounts WHERE member_id = ?", (member_id,))
        self.db.execute("DELETE FROM members WHERE member_id = ?", (member_id,))

    def all_members(self):
        return self.db.fetch("SELECT * FROM members ORDER BY member_id")

    # ---------- issue and return ----------

    def issue_book(self, book_id, member_id):
        book = self.get_book(book_id)
        member = self.get_member(member_id)
        already = self.db.fetch(
            "SELECT 1 FROM transactions WHERE book_id = ? AND member_id = ? AND status = 'Issued'",
            (book_id, member_id))
        if already:
            raise LibraryError("This member already has a copy of this book")

        book.take_copy()  # raises BookNotAvailableError when no copies are left
        due = date.today() + timedelta(days=member.loan_days())
        self.db.execute(
            """INSERT INTO transactions (book_id, member_id, issue_date, due_date, fine_amount, status)
               VALUES (?, ?, ?, ?, 0, 'Issued')""", (book_id, member_id, str(date.today()), str(due)))
        self.db.execute("UPDATE books SET available_copies = ? WHERE book_id = ?",
                        (book.available, book_id))
        return due

    def return_book(self, transaction_id):
        rows = self.db.fetch(
            "SELECT * FROM transactions WHERE transaction_id = ? AND status = 'Issued'",
            (transaction_id,))
        if not rows:
            raise LibraryError("This book is not currently issued")

        transaction = Transaction(*rows[0])
        rate = self.get_member(transaction.member_id).fine_per_day()
        fine = transaction.calculate_fine(rate)
        book = self.get_book(transaction.book_id)
        book.put_back()
        self.db.execute(
            """UPDATE transactions SET return_date = ?, fine_amount = ?, status = 'Returned'
               WHERE transaction_id = ?""", (str(date.today()), fine, transaction_id))
        self.db.execute("UPDATE books SET available_copies = ? WHERE book_id = ?",
                        (book.available, book.book_id))
        return fine

    def loans_report(self, only_overdue=False, member_id=None):
        """Books that are currently issued, with due date, days overdue and fine.
        Pass member_id to see only one member's books."""
        report = []
        for row in self.db.fetch("SELECT * FROM transactions WHERE status = 'Issued'"):
            t = Transaction(*row)
            days = t.overdue_days()
            if only_overdue and days == 0:
                continue
            if member_id is not None and t.member_id != member_id:
                continue
            member = self.get_member(t.member_id)
            title = self.get_book(t.book_id).title
            report.append((t.transaction_id, title, member.name, t.issue_date,
                           t.due_date, days, t.calculate_fine(member.fine_per_day())))
        return report


def export_csv(columns, rows, path):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
