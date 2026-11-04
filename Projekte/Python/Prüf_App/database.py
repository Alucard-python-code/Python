import sqlite3
from datetime import datetime
from newsletter import timedelta # Für präzisere Monatsberechnung nutzen wir eine einfache Annäherung via Tage

class Database:
    def __init__(self, db_name="uvv_pruefungen_pro.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company TEXT,
                email TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS protocols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                date_checked TEXT,
                next_due TEXT,
                zip_path TEXT,
                FOREIGN KEY(customer_id) REFERENCES customers(id)
            )
        """)
        self.conn.commit()

    def add_customer(self, name, company, email):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO customers (name, company, email) VALUES (?, ?, ?)", (name, company, email))
        self.conn.commit()
        return cursor.lastrowid

    def get_all_customers(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, company, email FROM customers")
        return cursor.fetchall()

    def get_customer(self, customer_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, name, company, email FROM customers WHERE id = ?", (customer_id,))
        return cursor.fetchone()

    def add_protocol(self, customer_id, zip_path, months=12):
        cursor = self.conn.cursor()
        now = datetime.now()
        date_str = now.strftime("%d.%m.%Y %H:%M")
        
        # Dynamische Berechnung: Monate * 30 Tage als Annäherung für das Fälligkeitsdatum
        days_to_add = months * 30
        from datetime import timedelta
        due_date = now + timedelta(days=days_to_add)
        due_str = due_date.strftime("%d.%m.%Y")
        
        cursor.execute("INSERT INTO protocols (customer_id, date_checked, next_due, zip_path) VALUES (?, ?, ?, ?)", 
                       (customer_id, date_str, due_str, zip_path))
        self.conn.commit()

    def get_history(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT p.id, c.company, c.name, p.date_checked, p.next_due, p.zip_path 
            FROM protocols p
            JOIN customers c ON p.customer_id = c.id
            ORDER BY p.id DESC
        """)
        return cursor.fetchall()
