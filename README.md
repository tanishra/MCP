## ExpenseTracker MCP Server

A production-ready Model Context Protocol (MCP) server that turns your AI assistant into a persistent personal finance manager using PostgreSQL.

This project allows Claude Desktop or any MCP-enabled agent to securely store, analyze, and export expense data using real database transactions instead of chat memory.

---

## What Is It?

ExpenseTracker MCP is a local backend service exposing structured financial tools to AI agents.

It enables your assistant to:

- Store expenses permanently
- Edit and delete past records
- Summarize spending patterns
- Detect top spending categories
- Generate monthly reports
- Export data for accounting or tax use

---

## How It Works

1. Claude Desktop sends a tool request using MCP.
2. ExpenseTracker MCP receives the request.
3. The server executes the database operation in PostgreSQL.
4. Results are returned to Claude as structured JSON.
5. Logs are written to `expense_tracker.log`.

The AI never invents data — it only queries your real database.

---

## How To Run Using uv

### Install dependencies

```bash
uv add fastmcp psycopg2-binary python-dotenv
```

### Create .env file

```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=expense_tracker
DB_USER=expense_user
DB_PASSWORD=your_password
```

### Start MCP server

#### For Testing 

```bash
uv run fastmcp dev main.py
```

#### For Run

```bash
uv run fastmcp run main.py
```

### How to connect to Claude Desktop

```bash
uv run fastmcp install claude-desktop main.py
```

Restart Claude Desktop

---

## Contribution

Contributions are welcome.

- Fork the repository  
- Create a feature branch  
- Add or improve MCP tools or documentation  
- Submit a pull request with a clear description of your changes  