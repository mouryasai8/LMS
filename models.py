import hashlib
from abc import ABC, abstractmethod
from datetime import date, datetime


# ---------- custom exceptions ----------

class LibraryError(Exception):
    pass


class DuplicateIDError(LibraryError):
    pass


class InvalidBookError(LibraryError):
    pass


class InvalidMemberError(LibraryError):
    pass


class BookNotAvailableError(LibraryError):
    pass


# ---------- books ----------

class Book:
    def __init__(self, book_id, title, author, category, copies, available=None, added_date=""):
        if not title.strip() or not author.strip():
            raise ValueError("Title and author cannot be empty")
        if copies < 1:
            raise ValueError("A book needs at least 1 copy")
        self.book_id = book_id
        self.title = title.strip()
        self.author = author.strip()
        self.category = category.strip()
        self.copies = copies
        self.added_date = added_date
        self.available = copies if available is None else available

    @property
    def available(self):
        return self.__available

    @available.setter
    def available(self, value):
        if not 0 <= value <= self.copies:
            raise ValueError("Available copies must be between 0 and the total copies")
        self.__available = value

    def take_copy(self):
        if self.available == 0:
            raise BookNotAvailableError(f"No copies of '{self.title}' are available")
        self.available -= 1

    def put_back(self):
        self.available += 1

    def __str__(self):
        return f"{self.book_id}: {self.title} by {self.author} ({self.available}/{self.copies} available)"


# ---------- members ----------

class Member(ABC):
    def __init__(self, member_id, name, email, phone):
        if not name.strip():
            raise ValueError("Name cannot be empty")
        if "@" not in email:
            raise ValueError("Enter a valid email address")
        self.member_id = member_id
        self.name = name.strip()
        self.email = email.strip()
        self.phone = phone  # goes through the setter below

    @property
    def phone(self):
        return self.__phone

    @phone.setter
    def phone(self, value):
        value = str(value).strip()
        if not (value.isdigit() and len(value) == 10):
            raise ValueError("Phone number must be 10 digits")
        self.__phone = value

    @abstractmethod
    def loan_days(self):
        pass

    @abstractmethod
    def fine_per_day(self):
        pass

    def member_type(self):
        return type(self).__name__

    def can_manage(self):
        return False

    def __str__(self):
        return f"{self.name} ({self.member_type()})"


class Student(Member):
    def loan_days(self):
        return 14

    def fine_per_day(self):
        return 2


class Faculty(Member):
    def loan_days(self):
        return 30

    def fine_per_day(self):
        return 1


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


class Librarian:
    def __init__(self, username, password_hash):
        self.username = username
        self.__password_hash = password_hash

    def check_password(self, password):
        return self.__password_hash == hash_password(password)

    def can_manage(self):
        return True

    def __str__(self):
        return f"{self.username} (Librarian)"


def make_member(member_id, name, email, phone, member_type):
    types = {"Student": Student, "Faculty": Faculty}
    if member_type not in types:
        raise ValueError("Member type must be Student or Faculty")
    return types[member_type](member_id, name, email, phone)


# ---------- transactions ----------

class Transaction:
    def __init__(self, transaction_id, book_id, member_id, issue_date, due_date,
                 return_date=None, fine_amount=0, status="Issued"):
        self.transaction_id = transaction_id
        self.book_id = book_id
        self.member_id = member_id
        self.issue_date = issue_date
        self.due_date = due_date
        self.return_date = return_date
        self.fine_amount = fine_amount
        self.status = status

    def overdue_days(self):
        due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
        return max((date.today() - due).days, 0)

    def calculate_fine(self, rate):
        return self.overdue_days() * rate
