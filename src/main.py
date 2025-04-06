from contextlib import asynccontextmanager
from typing import AsyncIterator
from mcp.server.fastmcp import FastMCP, Context
from db_client.pool import ConnectionPool
from db_client.db import DB
from dataclasses import dataclass

pool = ConnectionPool()

@dataclass
class AppContext:
    db: DB

@asynccontextmanager
async def app_lifespan(app: FastMCP) -> AsyncIterator[AppContext]:
    db = None
    try:
        log.info("🔄 Getting database connection")
        db = pool.get_connection()
        yield AppContext(db=db)
    finally:
        if db is not None:
            pool.return_connection(db)

mcp = FastMCP("tidb", instructions="""
    you are a tidb database expert, you can help me query, create, and execute sql statements in string on the tidb database.
    Notice:
    - use TiDB instead of MySQL syntax for sql statements
    """
    , lifespan=app_lifespan)

import logging
log = logging.getLogger(__name__)

@mcp.tool(
    description="Show all tables in the database"
)
def show_tables(ctx: Context, db_name: str):
    db : DB = ctx.request_context.lifespan_context.db
    try:
        tables = db.query(f"SHOW TABLES FROM {db_name}")
        return [table[0] for table in tables]
    except Exception as e:
        log.error(f"Error showing tables: {e}")
        raise e

@mcp.tool(
    description="""
    query the tidb database via sql, best practices:
    - sql is always a string
    - always add LIMIT in the query
    - always add ORDER BY in the query
    """
)
def db_query(ctx: Context, db_name: str, sql: str) -> list[dict]:
    db : DB = ctx.request_context.lifespan_context.db
    try:
        with db.transaction():
            if db_name is not None:
                db.execute(f"USE {db_name}")
            rows = db.query(f"{sql}")
            return [tuple(row) for row in rows]
    except Exception as e:
        log.error(f"Error querying database: {e}")
        raise e

@mcp.tool(
    description="""
    show create_table sql for a table
    """
)
def show_create_table(ctx: Context, db_name: str, table: str) -> str:
    db : DB = ctx.request_context.lifespan_context.db
    try:
        sql = db.query_one(f"SHOW CREATE TABLE {db_name}.{table}")
        return sql[1]
    except Exception as e:
        log.error(f"Error showing create table: {e}")
        raise e

@mcp.tool(
    description="""
    execute sql statments on the sepcific database with TiDB, best practices:
    - sql_stmts is always a string or a list of string
    - always use transaction to execute sql statements
    """
)
def db_execute(ctx: Context, db_name: str, sql_stmts: str | list[str]):
    db : DB = ctx.request_context.lifespan_context.db
    try:
        with db.transaction():
            if db_name is not None:
                db.execute(f"USE {db_name}")
            if isinstance(sql_stmts, str):
                db.execute(sql_stmts)
            elif isinstance(sql_stmts, list):
                for sql in sql_stmts:
                    db.execute(f"{sql}")
        return "success"
    except Exception as e:
        log.error(f"Error executing database: {e}")
        raise e

def get_username_prefix(ctx: Context) -> str:
    db : DB = ctx.request_context.lifespan_context.db
    try:
        username = db.query_one("SELECT CURRENT_USER()")
        if "." in username[0]:
            return username[0].split(".")[0]
        else:
            return ""
    except Exception as e:
        log.error(f"Error getting username prefix: {e}")
        raise e

@mcp.tool(
    description="""
    create a new database user, will return the username with prefix
    """
)
def create_db_user(ctx: Context, username: str, password: str) -> str:
    db : DB = ctx.request_context.lifespan_context.db
    try:
        username_prefix = get_username_prefix(ctx)
        full_username = f"{username_prefix}.{username}" if username_prefix else username
        db.execute(f"CREATE USER '{full_username}'@'%' IDENTIFIED BY '{password}'")
        return f"success, username: {full_username}"
    except Exception as e:
        raise e

@mcp.tool(
    description="""
    remove a database user in tidb serverless
    """
)
def remove_db_user(ctx: Context, username: str):
    db : DB = ctx.request_context.lifespan_context.db
    # if user provide a full username, use it directly
    # else get the username prefix and append it to the username
    if "." in username:
        full_username = username
    else:
        username_prefix = get_username_prefix(ctx)
        full_username = f"{username_prefix}.{username}"
    try:
        db.execute(f"DROP USER '{full_username}'@'%'")
        return f"success, username: {full_username}"
    except Exception as e:
        raise e

@mcp.tool(
    description="""
    get connection host and port
    """
)
def get_tidb_serverless_address(ctx: Context) -> str:
    db : DB = ctx.request_context.lifespan_context.db
    return f"{db.host}:{db.port}"

if __name__ == '__main__':
    log.info("Starting tidb serverless mcp server...")
    mcp.run(transport='stdio')
