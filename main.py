from fastmcp import FastMCP
import os
import logging
from datetime import datetime
import csv
import statistics
import asyncpg
from dotenv import load_dotenv
import asyncio
import sys

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

db_pool = None

async def init_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=int(DB_PORT),
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        min_size=1,
        max_size=10
    )

# ----------------- DB INIT -----------------

async def init_db():
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                amount NUMERIC(10,2) NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)
        logger.info("PostgreSQL database initialized successfully")

# ----------------- HELPERS -----------------

def validate_date(date_str: str):
    datetime.strptime(date_str, "%Y-%m-%d")

# ----------------- TOOLS -----------------

@mcp.tool()
async def add_expense(date, amount, category, subcategory="", note=""):
    try:
        validate_date(date)
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO expenses(date, amount, category, subcategory, note)
                VALUES ($1,$2,$3,$4,$5) RETURNING id
            """, date, float(amount), category, subcategory, note)
            return {"status": "ok", "id": row["id"]}
    except Exception as e:
        logger.exception("Add expense failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
async def read_expense(expense_id: int):
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM expenses WHERE id=$1", expense_id)
            return dict(row) if row else {"status": "not_found"}
    except Exception as e:
        logger.exception("Read expense failed")
        return {"status": "error", "error": str(e)}

@mcp.tool()
async def update_expense(expense_id, date=None, amount=None, category=None, subcategory=None, note=None):
    try:
        fields, values = [], []
        idx = 1
        for k, v in [("date",date),("amount",amount),("category",category),("subcategory",subcategory),("note",note)]:
            if v:
                if k=="date": validate_date(v)
                fields.append(f"{k}=${idx}")
                values.append(v)
                idx+=1
        if not fields:
            return {"status":"no_update_fields"}
        values.append(expense_id)
        async with db_pool.acquire() as conn:
            await conn.execute(f"UPDATE expenses SET {','.join(fields)} WHERE id=${idx}", *values)
            return {"status":"ok"}
    except Exception as e:
        logger.exception("Update expense failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def delete_expense(expense_id: int):
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM expenses WHERE id=$1", expense_id)
            return {"status":"ok"}
    except Exception as e:
        logger.exception("Delete expense failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def list_expenses(start_date, end_date):
    try:
        validate_date(start_date); validate_date(end_date)
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM expenses WHERE date BETWEEN $1 AND $2 ORDER BY date ASC
            """, start_date, end_date)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.exception("List expenses failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def summarize(start_date, end_date, category=None):
    try:
        validate_date(start_date); validate_date(end_date)
        q = "SELECT category, SUM(amount) AS total FROM expenses WHERE date BETWEEN $1 AND $2"
        params=[start_date,end_date]
        if category:
            q+=" AND category=$3"; params.append(category)
        q+=" GROUP BY category ORDER BY total DESC"
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(q,*params)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.exception("Summarize failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def monthly_report(year, month):
    start=f"{year}-{str(month).zfill(2)}-01"; end=f"{year}-{str(month).zfill(2)}-31"
    return await summarize(start,end)

@mcp.tool()
async def top_spending_categories(start_date,end_date,limit=3):
    try:
        validate_date(start_date); validate_date(end_date)
        async with db_pool.acquire() as conn:
            rows=await conn.fetch("""
                SELECT category,SUM(amount) AS total FROM expenses
                WHERE date BETWEEN $1 AND $2
                GROUP BY category ORDER BY total DESC LIMIT $3
            """,start_date,end_date,int(limit))
            return [dict(r) for r in rows]
    except Exception as e:
        logger.exception("Top spending failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def daily_average(start_date,end_date):
    try:
        validate_date(start_date); validate_date(end_date)
        async with db_pool.acquire() as conn:
            rows=await conn.fetch("""
                SELECT date,SUM(amount) FROM expenses
                WHERE date BETWEEN $1 AND $2 GROUP BY date
            """,start_date,end_date)
            values=[r[1] for r in rows]
            avg=round(statistics.mean(values),2) if values else 0
            return {"average_daily_spend":avg}
    except Exception as e:
        logger.exception("Daily average failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def budget_alert(start_date,end_date,limit):
    summary=await summarize(start_date,end_date)
    total=sum(x["total"] for x in summary)
    return {"total_spent":total,"budget_limit":float(limit),"status":"ALERT" if total>float(limit) else "SAFE"}

@mcp.tool()
async def export_csv(start_date,end_date):
    try:
        data=await list_expenses(start_date,end_date)
        file_path=os.path.join(BASE_DIR,"expenses_export.csv")
        with open(file_path,"w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=data[0].keys())
            writer.writeheader(); writer.writerows(data)
        return {"file":file_path,"status":"exported"}
    except Exception as e:
        logger.exception("CSV export failed")
        return {"status":"error","error":str(e)}

@mcp.tool()
async def health_check():
    return {"status":"running","db":DB_NAME}

@mcp.resource("expense://categories", mime_type="application/json")
async def categories():
    with open(CATEGORIES_PATH,"r",encoding="utf-8") as f:
        return f.read()

async def startup():
    await init_pool()
    await init_db()
    mcp.run(transport="http", host="0.0.0.0", port=8000)

if __name__ == "__main__" and "inspect" not in sys.argv:
    asyncio.run(startup())