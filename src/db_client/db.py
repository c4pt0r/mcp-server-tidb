import os
import time
import platform
from contextlib import contextmanager
from typing import Any, Optional, Callable, List, Tuple, Union
import pymysql
from pymysql.cursors import Cursor, DictCursor
from pymysql.connections import Connection
from dotenv import load_dotenv
from utils.logging import setup_logger
import threading

# Replace the existing logging setup with:
log = setup_logger(__name__)

class DatabaseError(Exception):
    """Base exception for database errors"""
    pass

def get_ssl_cert_path() -> str:
    """Get SSL certificate path based on operating system"""
    system = platform.system()
    if system == 'Darwin':  # macOS
        return '/private/etc/ssl/cert.pem'
    elif system == 'Linux':
        return '/etc/ssl/certs/ca-certificates.crt'
    else:
        raise ValueError(f"Unsupported operating system: {system}")

def get_db_config() -> dict:
    load_dotenv()
    """Get database configuration from environment variables"""
    env_configs = [
        {
            'host': ('DB_HOST', 'localhost'),
            'port': ('DB_PORT', '4000'),
            'user': ('DB_USERNAME', 'root'),
            'password': ('DB_PASSWORD', ''),
            'database': ('DB_DATABASE', 'test')
        },
        {
            'host': ('TIDB_HOST', 'localhost'),
            'port': ('TIDB_PORT', '4000'),
            'user': ('TIDB_USERNAME', 'root'),
            'password': ('TIDB_PASSWORD', ''),
            'database': ('TIDB_DATABASE', 'test')
        }
    ]

    for config in env_configs:
        if all(os.getenv(env_var[0]) for env_var in config.values()):
            return {key: os.getenv(env_var[0], env_var[1]) 
                   for key, env_var in config.items()}
    
    raise ValueError("Missing environment variables for database connection")

# Get configuration
DB_CONFIG = get_db_config()

class DB:
    """Database connection handler class"""
    def __init__(
        self,
        host: str = DB_CONFIG['host'],
        port: Union[str, int] = DB_CONFIG['port'],
        user: str = DB_CONFIG['user'],
        password: str = DB_CONFIG['password'],
        database: str = DB_CONFIG['database'],
        ssl_cert: str = get_ssl_cert_path(),
        max_tries: int = 10
    ):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.database = database
        self.ssl_cert = ssl_cert
        self.max_tries = max_tries
        self.conn = None
        self._in_transaction = False
        log.debug("Initializing database connection to %s:%d", self.host, self.port)
        self.init()

    def _get_connection_params(self) -> dict:
        """Get database connection parameters"""
        return {
            'host': self.host,
            'port': self.port,
            'user': self.user,
            'password': self.password,
            'database': self.database,
            'ssl_verify_cert': True,
            'ssl_verify_identity': True,
            'ssl_ca': self.ssl_cert,
            'charset': 'utf8mb4',
            'autocommit': True,
        }

    def init(self) -> None:
        """Initialize database connection"""
        self.reconnect()

    def reconnect(self) -> None:
        """Reconnect to database"""
        try:
            if self.conn and not self.conn.open:
                self.conn.close()
                log.debug("Closing existing connection before reconnect")
            
            log.info("Reconnecting to database %s@%s:%d", self.database, self.host, self.port)
            self.conn = pymysql.connect(**self._get_connection_params())
            log.info("Successfully reconnected to database")
        except pymysql.Error as e:
            log.error("Failed to connect to database: %s", e)
            raise DatabaseError(f"Connection failed: {str(e)}")
    
    def _is_connection_error(self, e: Exception) -> bool:
        """Check if the error is a connection error"""
        return isinstance(e, (pymysql.err.InterfaceError))

    def _execute_with_retry(self, operation: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute database operation with retry logic"""
        for i in range(self.max_tries):
            try:
                return operation(*args, **kwargs)
            except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as e:
                # Check if this is a network error that should be retried
                if self._is_connection_error(e):
                    # Max retries reached
                    if i == self.max_tries - 1:
                        log.error("Max retries reached: %s", e)
                        raise DatabaseError(f"Max retries reached: {str(e)}")
                    
                    # Network error - retry with exponential backoff
                    log.warning("Error: %s", e)
                    log.info("Reconnecting to db... sleeping for %s seconds", 2 ** i)
                    time.sleep(2 ** i)
                    self.reconnect()
                else:
                    # Non-network errors don't need retry
                    log.error("Database error: %s", e)
                    raise DatabaseError(f"Database error: {str(e)}")
            except Exception as e:
                # All other errors are non-retryable
                log.error("Database operation failed: %s", e)
                raise DatabaseError(f"Database operation failed: {str(e)}")

    @contextmanager
    def transaction(self):
        """Context manager for database transactions"""
        try:
            self.begin()
            yield self
            self.commit()
        except Exception:
            self.rollback()
            raise

    def query(
        self, 
        sql: str, 
        args: Optional[Union[tuple, dict]] = None,
        dictionary: bool = False
    ) -> List[Union[tuple, dict]]:
        """Execute a query and return all results"""
        def _query():
            cursor_class = DictCursor if dictionary else Cursor
            with self.conn.cursor(cursor_class) as cursor:
                cursor.execute(sql, args)
                return cursor.fetchall()
        return self._execute_with_retry(_query)

    def query_one(
        self,
        sql: str,
        args: Optional[Union[tuple, dict]] = None,
        dictionary: bool = False
    ) -> Optional[Union[tuple, dict]]:
        """Execute a query and return one result"""
        results = self.query(sql, args, dictionary)
        return results[0] if results else None

    def execute(self, sql: str, args: Optional[Union[tuple, dict]] = None) -> int:
        """Execute a SQL statement and return affected row count"""
        def _execute():
            with self.conn.cursor() as cursor:
                return cursor.execute(sql, args)
        return self._execute_with_retry(_execute)

    def execute_many(self, sql: str, args: List[Union[tuple, dict]]) -> int:
        """Execute many SQL statements and return affected row count"""
        def _execute_many():
            with self.conn.cursor() as cursor:
                return cursor.executemany(sql, args)
        return self._execute_with_retry(_execute_many)

    def begin(self) -> None:
        """Begin a transaction"""
        if not self.conn:
            log.error("No connection to database")
            raise DatabaseError("No connection to database")
        self.conn.begin()
        self._in_transaction = True
        log.debug("Started new transaction")

    def commit(self) -> None:
        """Commit the current transaction"""
        if not self.conn:
            log.error("No connection to database")
            raise DatabaseError("No connection to database")
        self.conn.commit()
        self._in_transaction = False
        log.debug("Committed transaction")

    def rollback(self) -> None:
        """Rollback the current transaction"""
        if not self.conn:
            log.error("No connection to database")
            raise DatabaseError("No connection to database")
        self.conn.rollback()
        self._in_transaction = False
        log.debug("Rolled back transaction")

    def close(self) -> None:
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            log.debug("Closed database connection")

    def __enter__(self) -> 'DB':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        """Cleanup on object destruction"""
        try:
            self.close()
        except Exception as e:
            log.error("Error during DB cleanup: %s", e)

    def ping(self) -> None:
        """Test database connection"""
        if not self.conn:
            log.error("No connection to database")
            raise DatabaseError("No connection to database")
        self.conn.ping()
        log.debug("Database connection is alive")
