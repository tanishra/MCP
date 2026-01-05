from fastmcp import FastMCP
import os
import sqlite3
import json
import logging
from datetime import datetime
import csv
import statistics


# ----------------- CONFIG -----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "expenses.db")
CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")
LOG_PATH = os.path.join(BASE_DIR, "expense_tracker.log")

# ----------------- LOGGER -----------------

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("ExpenseTracker")

# ----------------- MCP SERVER -----------------

mcp = FastMCP("ExpenseTracker")

# ----------------- DB INIT -----------------

def init_db():
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS expenses(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
            """)
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.exception("DB Initialization Failed")
        raise RuntimeError("Database initialization error") from e

init_db()

# ----------------- HELPERS -----------------

def validate_date(date_str: str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        raise ValueError("Date must be in YYYY-MM-DD format")

# ----------------- TOOLS -----------------

@mcp.tool()
def add_expense(date, amount, category, subcategory="", note=""):
    """Add new expense"""
    try:
        validate_date(date)
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute(
                "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
                (date, float(amount), category, subcategory, note)
            )
            logger.info(f"Expense added ID={cur.lastrowid}")
            return {"status": "ok", "id": cur.lastrowid}
    except Exception as e:
        logger.exception("Add expense failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def read_expense(expense_id: int):
    """Read single expense by ID"""
    try:
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute("SELECT * FROM expenses WHERE id=?", (expense_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "not_found"}
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
    except Exception as e:
        logger.exception("Read expense failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def update_expense(expense_id, date=None, amount=None, category=None, subcategory=None, note=None):
    """Update existing expense"""
    try:
        fields = []
        params = []

        if date:
            validate_date(date)
            fields.append("date=?")
            params.append(date)
        if amount:
            fields.append("amount=?")
            params.append(float(amount))
        if category:
            fields.append("category=?")
            params.append(category)
        if subcategory:
            fields.append("subcategory=?")
            params.append(subcategory)
        if note:
            fields.append("note=?")
            params.append(note)

        if not fields:
            return {"status": "no_update_fields"}

        params.append(expense_id)

        with sqlite3.connect(DB_PATH) as c:
            c.execute(f"UPDATE expenses SET {','.join(fields)} WHERE id=?", params)
            logger.info(f"Expense updated ID={expense_id}")
            return {"status": "ok"}
    except Exception as e:
        logger.exception("Update expense failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def delete_expense(expense_id: int):
    """Delete expense"""
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
            logger.info(f"Expense deleted ID={expense_id}")
            return {"status": "ok"}
    except Exception as e:
        logger.exception("Delete expense failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def list_expenses(start_date, end_date):
    """Read expenses in a given range"""
    try:
        validate_date(start_date)
        validate_date(end_date)
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute("""
                SELECT * FROM expenses
                WHERE date BETWEEN ? AND ?
                ORDER BY date ASC
            """, (start_date, end_date))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("List expenses failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def summarize(start_date, end_date, category=None):
    """Summarize expenses"""
    try:
        validate_date(start_date)
        validate_date(end_date)
        q = """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE date BETWEEN ? AND ?
        """
        params = [start_date, end_date]

        if category:
            q += " AND category=?"
            params.append(category)

        q += " GROUP BY category ORDER BY total DESC"

        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute(q, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Summarize failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def monthly_report(year, month):
    """Monthly spending breakdown"""
    try:
        start = f"{year}-{str(month).zfill(2)}-01"
        end = f"{year}-{str(month).zfill(2)}-31"
        return summarize(start, end)
    except Exception as e:
        logger.exception("Monthly report failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def top_spending_categories(start_date, end_date, limit=3):
    try:
        validate_date(start_date)
        validate_date(end_date)
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute("""
                SELECT category, SUM(amount) as total
                FROM expenses
                WHERE date BETWEEN ? AND ?
                GROUP BY category
                ORDER BY total DESC
                LIMIT ?
            """, (start_date, end_date, int(limit)))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Top spending failed")
        return {"status": "error", "error": str(e)}


@mcp.tool()
def daily_average(start_date, end_date):
    try:
        validate_date(start_date)
        validate_date(end_date)
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute("""
                SELECT date, SUM(amount)
                FROM expenses
                WHERE date BETWEEN ? AND ?
                GROUP BY date
            """, (start_date, end_date))
            values = [r[1] for r in cur.fetchall()]
            avg = round(statistics.mean(values), 2) if values else 0
            return {"average_daily_spend": avg}
    except Exception as e:
        logger.exception("Daily average failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
def budget_alert(start_date, end_date, limit):
    try:
        summary = summarize(start_date, end_date)
        total = sum(x["total"] for x in summary)

        return {
            "total_spent": total,
            "budget_limit": float(limit),
            "status": "ALERT" if total > float(limit) else "SAFE"
        }
    except Exception as e:
        logger.exception("Budget alert failed")
        return {"status": "error", "error": str(e)}


@mcp.tool()
def export_csv(start_date, end_date):
    try:
        file_path = os.path.join(BASE_DIR, "expenses_export.csv")
        data = list_expenses(start_date, end_date)

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        return {"file": file_path, "status": "exported"}
    except Exception as e:
        logger.exception("CSV export failed")
        return {"status": "error", "error": str(e)}
    
@mcp.tool()
def top_spending_categories(start_date, end_date, limit=3):
    try:
        validate_date(start_date)
        validate_date(end_date)
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute("""
                SELECT category, SUM(amount) AS total
                FROM expenses
                WHERE date BETWEEN ? AND ?
                GROUP BY category
                ORDER BY total DESC
                LIMIT ?
            """, (start_date, end_date, int(limit)))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Top spending categories failed")
        return {"status": "error", "error": str(e)}


@mcp.tool()
def health_check():
    """Service health"""
    return {"status": "running", "db_path": DB_PATH}

# ----------------- RESOURCE -----------------

@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    try:
        with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.exception("Category resource load failed")
        return json.dumps({"error": "categories unavailable"})

# ----------------- RUN -----------------

if __name__ == "__main__":
    mcp.run()