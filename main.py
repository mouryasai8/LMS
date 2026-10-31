import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from library import Library, export_csv
from models import Book, make_member, LibraryError

BOOK_COLUMNS = ("ID", "Title", "Author", "Category", "Copies", "Available", "Added On")
MEMBER_COLUMNS = ("ID", "Name", "Email", "Phone", "Type")
LOAN_COLUMNS = ("Txn", "Book", "Member", "Issued On", "Due Date", "Days Overdue", "Fine (Rs)")

MEMBER_FIELDS = ["Member ID", "Name", "Email", "Phone", "Username", "Password"]
SIGNUP_FIELDS = {"Student": MEMBER_FIELDS,
                 "Faculty": MEMBER_FIELDS,
                 "Librarian": ["Username", "Password", "Librarian Code"]}
SECRET_FIELDS = ("Password", "Librarian Code")


# ---------- small helpers for building the window ----------

def make_form(parent, labels):
    box = ttk.Frame(parent)
    box.pack(pady=5)
    entries = {}
    for i, text in enumerate(labels):
        ttk.Label(box, text=text).grid(row=i, column=0, sticky="w", padx=5, pady=3)
        entries[text] = ttk.Entry(box, width=30, show="*" if text in SECRET_FIELDS else "")
        entries[text].grid(row=i, column=1, padx=5, pady=3)
    return entries


def make_buttons(parent, buttons):
    row = ttk.Frame(parent)
    row.pack(pady=5)
    for text, command in buttons:
        ttk.Button(row, text=text, command=command).pack(side="left", padx=3)


def make_table(parent):
    table = ttk.Treeview(parent, show="headings", height=10)
    table.pack(fill="both", expand=True, padx=10, pady=5)
    return table


def fill_table(table, columns, rows):
    table["columns"] = columns
    for col in columns:
        table.heading(col, text=col)
        table.column(col, width=110)
    table.delete(*table.get_children())
    for row in rows:
        table.insert("", "end", values=row)


def fill_form(form, values):
    for entry, value in zip(form.values(), values):
        entry.delete(0, "end")
        entry.insert(0, value)


def clear_form(form):
    for entry in form.values():
        entry.delete(0, "end")


def clear_window(root):
    for widget in root.winfo_children():
        widget.destroy()


def to_int(text, field):
    if not text.strip().isdigit():
        raise ValueError(f"{field} must be a number")
    return int(text)


def selected_id(table, message):
    """The ID in the first column of the highlighted row."""
    chosen = table.selection()
    if not chosen:
        raise ValueError(message)
    return int(table.item(chosen[0])["values"][0])


# ---------- login and create account ----------

class LoginScreen:
    def __init__(self, root, lib):
        self.root, self.lib = root, lib
        clear_window(root)
        root.geometry("400x300")
        ttk.Label(root, text="Library Management System",
                  font=("Arial", 14, "bold")).pack(pady=20)
        self.form = make_form(root, ["Username", "Password"])
        make_buttons(root, [("Login", self.login),
                            ("Create Account", lambda: SignupScreen(root, lib))])

    def login(self):
        try:
            user = self.lib.login(self.form["Username"].get(), self.form["Password"].get())
            App(self.root, self.lib, user)
        except LibraryError as e:
            messagebox.showerror("Login failed", str(e))


class SignupScreen:
    def __init__(self, root, lib):
        self.root, self.lib = root, lib
        clear_window(root)
        root.geometry("400x460")
        ttk.Label(root, text="Create Account", font=("Arial", 14, "bold")).pack(pady=15)
        self.role = ttk.Combobox(root, values=list(SIGNUP_FIELDS), state="readonly", width=27)
        self.role.set("Student")
        self.role.bind("<<ComboboxSelected>>", self.draw_form)
        self.role.pack()
        self.box = ttk.Frame(root)
        self.box.pack()
        self.draw_form()
        make_buttons(root, [("Create Account", self.create),
                            ("Back to Login", lambda: LoginScreen(root, lib))])

    def draw_form(self, event=None):
        for widget in self.box.winfo_children():
            widget.destroy()
        self.form = make_form(self.box, SIGNUP_FIELDS[self.role.get()])

    def create(self):
        role = self.role.get()
        f = {label: entry.get() for label, entry in self.form.items()}
        try:
            if role == "Librarian":
                self.lib.create_librarian(f["Username"], f["Password"], f["Librarian Code"])
            else:
                member = make_member(to_int(f["Member ID"], "Member ID"), f["Name"],
                                     f["Email"], f["Phone"], role)
                self.lib.create_member_account(member, f["Username"], f["Password"])
            messagebox.showinfo("Account created", "You can log in now")
            LoginScreen(self.root, self.lib)
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))


# ---------- the application ----------

class App:
    def __init__(self, root, lib, user):
        clear_window(root)
        root.geometry("900x600")
        self.root, self.lib, self.user = root, lib, user
        self.is_librarian = user.can_manage()
        # a student or faculty member only sees their own loans
        self.owner = None if self.is_librarian else user.member_id
        self.report = None  # last report shown, used by Export CSV

        top = ttk.Frame(root)
        top.pack(fill="x", padx=10, pady=5)
        ttk.Label(top, text=f"Logged in as {user}").pack(side="left")
        ttk.Button(top, text="Logout", command=self.logout).pack(side="right")
        self.overdue_label = ttk.Label(top, text="Overdue books: 0")
        self.overdue_label.pack(side="right", padx=20)

        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True)
        self.build_books_tab(tabs)
        if self.is_librarian:
            self.build_members_tab(tabs)
            self.build_loans_tab(tabs)
        else:
            self.build_my_books_tab(tabs)
        self.build_reports_tab(tabs)

        self.refresh()
        if self.is_librarian:
            self.show_members()
        self.start_overdue_checker()

    def refresh(self):
        self.show_books()
        self.show_loans()

    def logout(self):
        self.stop.set()  # tells the background thread to finish
        LoginScreen(self.root, self.lib)

    # ----- background thread: overdue checker -----

    def start_overdue_checker(self):
        self.overdue_count = 0
        self.stop = threading.Event()
        self.checker = threading.Thread(target=self.check_overdue, daemon=True)
        self.checker.start()
        self.show_overdue_count()

    def check_overdue(self):
        """Runs in its own thread: counts overdue books every 10 seconds."""
        while not self.stop.is_set():
            overdue = self.lib.loans_report(only_overdue=True, member_id=self.owner)
            self.overdue_count = len(overdue)
            self.stop.wait(10)

    def show_overdue_count(self):
        """Runs in the main thread: Tkinter widgets must only be changed from here."""
        if not self.stop.is_set():
            self.overdue_label.config(text=f"Overdue books: {self.overdue_count}")
            self.root.after(1000, self.show_overdue_count)

    # ----- books -----

    def build_books_tab(self, tabs):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text="Books")
        if self.is_librarian:
            self.book_form = make_form(frame, ["ID", "Title", "Author", "Category", "Copies"])
            make_buttons(frame, [("Add", self.add_book), ("Update", self.update_book),
                                 ("Delete", self.delete_book),
                                 ("Clear", lambda: clear_form(self.book_form))])
        self.search_box = ttk.Entry(frame, width=30)
        self.search_box.pack(pady=5)
        make_buttons(frame, [("Search", self.show_books), ("Show All", self.show_all_books)])
        if not self.is_librarian:
            make_buttons(frame, [("Issue Selected Book", self.take_book)])
        self.book_table = make_table(frame)
        if self.is_librarian:
            self.book_table.bind("<<TreeviewSelect>>", self.pick_book)

    def book_from_form(self):
        f = self.book_form
        return Book(to_int(f["ID"].get(), "Book ID"), f["Title"].get(), f["Author"].get(),
                    f["Category"].get(), to_int(f["Copies"].get(), "Copies"))

    def show_books(self):
        fill_table(self.book_table, BOOK_COLUMNS, self.lib.search_books(self.search_box.get()))

    def show_all_books(self):
        self.search_box.delete(0, "end")
        self.show_books()

    def pick_book(self, event):
        chosen = self.book_table.selection()
        if chosen:
            fill_form(self.book_form, self.book_table.item(chosen[0])["values"][:5])

    def add_book(self):
        try:
            self.lib.add_book(self.book_from_form())
            clear_form(self.book_form)
            self.show_all_books()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    def update_book(self):
        try:
            self.lib.update_book(self.book_from_form())
            self.show_all_books()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    def delete_book(self):
        try:
            book_id = to_int(self.book_form["ID"].get(), "Book ID")
            if messagebox.askyesno("Confirm", f"Delete book {book_id}?"):
                self.lib.delete_book(book_id)
                clear_form(self.book_form)
                self.show_all_books()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    def take_book(self):
        """Student or faculty issues the highlighted book to themselves."""
        try:
            book_id = selected_id(self.book_table, "Click a book in the table first")
            due = self.lib.issue_book(book_id, self.user.member_id)
            messagebox.showinfo("Issued", f"Book issued. Due date: {due}")
            self.refresh()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    # ----- members (librarian) -----

    def build_members_tab(self, tabs):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text="Members")
        self.member_form = make_form(frame, ["ID", "Name", "Email", "Phone"])
        self.member_type = ttk.Combobox(frame, values=["Student", "Faculty"],
                                        state="readonly", width=27)
        self.member_type.set("Student")
        self.member_type.pack()
        make_buttons(frame, [("Add", self.add_member), ("Update", self.update_member),
                             ("Delete", self.delete_member),
                             ("Clear", lambda: clear_form(self.member_form))])
        self.member_table = make_table(frame)
        self.member_table.bind("<<TreeviewSelect>>", self.pick_member)

    def member_from_form(self):
        f = self.member_form
        return make_member(to_int(f["ID"].get(), "Member ID"), f["Name"].get(),
                           f["Email"].get(), f["Phone"].get(), self.member_type.get())

    def show_members(self):
        fill_table(self.member_table, MEMBER_COLUMNS, self.lib.all_members())

    def pick_member(self, event):
        chosen = self.member_table.selection()
        if chosen:
            values = self.member_table.item(chosen[0])["values"]
            fill_form(self.member_form, values[:4])
            self.member_type.set(values[4])

    def add_member(self):
        try:
            self.lib.add_member(self.member_from_form())
            clear_form(self.member_form)
            self.show_members()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    def update_member(self):
        try:
            self.lib.update_member(self.member_from_form())
            self.show_members()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    def delete_member(self):
        try:
            member_id = to_int(self.member_form["ID"].get(), "Member ID")
            if messagebox.askyesno("Confirm", f"Delete member {member_id}?"):
                self.lib.delete_member(member_id)
                clear_form(self.member_form)
                self.show_members()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    # ----- loans: librarian tab and the student / faculty "My Books" tab -----

    def build_loans_tab(self, tabs):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text="Issue / Return")
        self.loan_form = make_form(frame, ["Member ID", "Book ID"])
        make_buttons(frame, [("Issue Book", self.issue_book),
                             ("Return Selected Book", self.return_book)])
        self.loan_table = make_table(frame)

    def build_my_books_tab(self, tabs):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text="My Books")
        make_buttons(frame, [("Return Selected Book", self.return_book)])
        self.loan_table = make_table(frame)

    def show_loans(self):
        fill_table(self.loan_table, LOAN_COLUMNS, self.lib.loans_report(member_id=self.owner))

    def issue_book(self):
        f = self.loan_form
        try:
            due = self.lib.issue_book(to_int(f["Book ID"].get(), "Book ID"),
                                      to_int(f["Member ID"].get(), "Member ID"))
            messagebox.showinfo("Issued", f"Book issued. Due date: {due}")
            self.refresh()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    def return_book(self):
        try:
            txn = selected_id(self.loan_table, "Click a book in the table first")
            fine = self.lib.return_book(txn)
            messagebox.showinfo("Returned", f"Book returned. Fine: Rs {fine}")
            self.refresh()
        except (LibraryError, ValueError) as e:
            messagebox.showerror("Error", str(e))

    # ----- reports -----

    def build_reports_tab(self, tabs):
        frame = ttk.Frame(tabs)
        tabs.add(frame, text="Reports")
        buttons = [("Recently Added", self.show_recent), ("Popular Books", self.show_popular)]
        if self.is_librarian:
            buttons += [("Overdue Books", self.show_overdue), ("Export CSV", self.export_report)]
        make_buttons(frame, buttons)
        self.report_table = make_table(frame)

    def show_report(self, columns, rows):
        self.report = (columns, rows)
        fill_table(self.report_table, columns, rows)

    def show_recent(self):
        self.show_report(("ID", "Title", "Author", "Category", "Added On"),
                         self.lib.recent_books())

    def show_popular(self):
        self.show_report(("ID", "Title", "Author", "Times Issued"),
                         self.lib.popular_books())

    def show_overdue(self):
        self.show_report(LOAN_COLUMNS, self.lib.loans_report(only_overdue=True))

    def export_report(self):
        if self.report is None:
            messagebox.showinfo("Export", "Open a report first, then export it")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV files", "*.csv")])
        if path:
            export_csv(*self.report, path)
            messagebox.showinfo("Export", "Report saved")


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Library Management System")
    LoginScreen(root, Library())
    root.mainloop()
