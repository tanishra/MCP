from fastmcp import FastMCP
import os
import logging
from datetime import datetime
import csv
import statistics
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

load_dotenv()

# ----------------- CONFIG -----------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")
LOG_PATH = os.path.join(BASE_DIR, "expense_tracker.log")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# ----------------- LOGGER -----------------

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("ExpenseTracker")

# ----------------- MCP SERVER -----------------

mcp = FastMCP("ExpenseTracker")

# ----------------- POSTGRES POOL -----------------

pool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    host=DB_HOST,
    port=DB_PORT,
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD
)

# ----------------- DB INIT -----------------

def init_db():
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS expenses(
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    amount NUMERIC(10,2) NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
            """)
            conn.commit()
            logger.info("PostgreSQL database initialized successfully")
    except Exception as e:
        logger.exception("PostgreSQL init failed")
        raise RuntimeError("Database initialization error") from e
    finally:
        pool.putconn(conn)

init_db()

# ----------------- HELPERS -----------------

def validate_date(date_str: str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        raise ValueError("Date must be in YYYY-MM-DD format")

def get_conn():
    return pool.getconn()

def put_conn(conn):
    pool.putconn(conn)

# ----------------- TOOLS -----------------

@mcp.tool()
def add_expense(date, amount, category, subcategory="", note=""):
    try:
        validate_date(date)
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO expenses(date, amount, category, subcategory, note)
                VALUES (%s,%s,%s,%s,%s) RETURNING id
            """, (date, float(amount), category, subcategory, note))
            expense_id = cur.fetchone()[0]
            conn.commit()
            return {"status": "ok", "id": expense_id}
    except Exception as e:
        logger.exception("Add expense failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def read_expense(expense_id: int):
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM expenses WHERE id=%s", (expense_id,))
            row = cur.fetchone()
            if not row:
                return {"status": "not_found"}
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))
    except Exception as e:
        logger.exception("Read expense failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def update_expense(expense_id, date=None, amount=None, category=None, subcategory=None, note=None):
    try:
        fields, params = [], []

        if date:
            validate_date(date)
            fields.append("date=%s"); params.append(date)
        if amount:
            fields.append("amount=%s"); params.append(float(amount))
        if category:
            fields.append("category=%s"); params.append(category)
        if subcategory:
            fields.append("subcategory=%s"); params.append(subcategory)
        if note:
            fields.append("note=%s"); params.append(note)

        if not fields:
            return {"status": "no_update_fields"}

        params.append(expense_id)
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(f"UPDATE expenses SET {','.join(fields)} WHERE id=%s", params)
            conn.commit()
            return {"status": "ok"}
    except Exception as e:
        logger.exception("Update expense failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def delete_expense(expense_id: int):
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM expenses WHERE id=%s", (expense_id,))
            conn.commit()
            return {"status": "ok"}
    except Exception as e:
        logger.exception("Delete expense failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def list_expenses(start_date, end_date):
    try:
        validate_date(start_date)
        validate_date(end_date)
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM expenses
                WHERE date BETWEEN %s AND %s
                ORDER BY date ASC
            """, (start_date, end_date))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("List expenses failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def summarize(start_date, end_date, category=None):
    try:
        validate_date(start_date)
        validate_date(end_date)
        q = """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE date BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if category:
            q += " AND category=%s"; params.append(category)
        q += " GROUP BY category ORDER BY total DESC"

        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(q, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Summarize failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def monthly_report(year, month):
    start = f"{year}-{str(month).zfill(2)}-01"
    end = f"{year}-{str(month).zfill(2)}-31"
    return summarize(start, end)

@mcp.tool()
def top_spending_categories(start_date, end_date, limit=3):
    try:
        validate_date(start_date)
        validate_date(end_date)
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT category, SUM(amount) AS total
                FROM expenses
                WHERE date BETWEEN %s AND %s
                GROUP BY category
                ORDER BY total DESC
                LIMIT %s
            """, (start_date, end_date, int(limit)))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        logger.exception("Top spending failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def daily_average(start_date, end_date):
    try:
        validate_date(start_date)
        validate_date(end_date)
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT date, SUM(amount)
                FROM expenses
                WHERE date BETWEEN %s AND %s
                GROUP BY date
            """, (start_date, end_date))
            values = [r[1] for r in cur.fetchall()]
            avg = round(statistics.mean(values), 2) if values else 0
            return {"average_daily_spend": avg}
    except Exception as e:
        logger.exception("Daily average failed")
        return {"status": "error", "error": str(e)}
    finally:
        put_conn(conn)

@mcp.tool()
def budget_alert(start_date, end_date, limit):
    summary = summarize(start_date, end_date)
    total = sum(x["total"] for x in summary)
    return {"total_spent": total, "budget_limit": float(limit), "status": "ALERT" if total > float(limit) else "SAFE"}

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
def health_check():
    return {"status": "running", "db": DB_NAME}

# ----------------- RESOURCE -----------------

@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()

# ----------------- RUN -----------------

if __name__ == "__main__":
    mcp.run()