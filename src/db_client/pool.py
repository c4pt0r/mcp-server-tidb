from queue import Queue, Empty
from threading import Lock
import threading
from typing import Optional, Set
from .db import DB, DatabaseError
import time
from utils.logging import setup_logger

# Replace the existing logging setup with:
log = setup_logger(__name__)

class ConnectionPool:
    """Thread-safe database connection pool"""
    
    def __init__(
        self,
        min_connections: int = 10,
        max_connections: int = 100,
        timeout: float = 10.0
    ):
        """
        Initialize connection pool
        
        Args:
            min_connections: Minimum number of connections to maintain
            max_connections: Maximum number of connections allowed
            timeout: Timeout in seconds when waiting for a connection
        """
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.timeout = timeout
        
        self._pool: Queue = Queue()
        self._active_connections: Set[DB] = set()  # Track active connections
        self._lock = Lock()
        
        # Initialize minimum connections
        log.info("Initializing connection pool with %d connections", min_connections)
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Create initial connections"""
        for i in range(self.min_connections):
            try:
                conn = DB()
                self._pool.put(conn)
                self._active_connections.add(conn)
                log.debug("Created initial connection %d/%d", i+1, self.min_connections)
            except Exception as e:
                log.error("Failed to create initial connection: %s", e)
                raise DatabaseError(f"Failed to initialize pool: {str(e)}")
        log.info("Connection pool initialized successfully")
    
    def _create_connection(self) -> DB:
        """Create a new database connection"""
        try:
            return DB()
        except Exception as e:
            log.error("Failed to create new connection: %s", e)
            raise DatabaseError(f"Failed to create connection: {str(e)}")
    
    def get_connection(self) -> DB:
        """Get a connection from the pool"""
        start_time = time.time()
        log.debug("Attempting to get database connection")
        
        while True:
            # First try to get from pool
            try:
                conn = self._pool.get_nowait()
                # Verify connection is valid
                try:
                    conn.ping()
                    log.debug("Retrieved valid connection from pool")
                    return conn
                except:
                    # Remove invalid connection
                    with self._lock:
                        self._active_connections.discard(conn)
                    log.warning("Discarded invalid connection from pool")
                    continue
            except Empty:
                log.debug("Connection pool empty, trying alternatives")
                pass
            
            # If pool is empty, try to create new connection
            with self._lock:
                if len(self._active_connections) < self.max_connections:
                    try:
                        conn = self._create_connection()
                        self._active_connections.add(conn)
                        log.debug("Created new connection (active: %d/%d)", 
                                 len(self._active_connections), self.max_connections)
                        return conn
                    except Exception as e:
                        log.error("Failed to create new connection: %s", e)
                
            # If we can't create new connection, wait for one to be returned
            try:
                log.debug("Waiting for connection to be returned to pool")
                conn = self._pool.get(timeout=0.5)
                try:
                    conn.ping()
                    log.debug("Retrieved valid connection after waiting")
                    return conn
                except:
                    # Remove invalid connection
                    with self._lock:
                        self._active_connections.discard(conn)
                    log.warning("Discarded invalid connection after waiting")
                    continue
            except Empty:
                if time.time() - start_time > self.timeout:
                    log.error("Connection timeout after %.2f seconds", self.timeout)
                    raise DatabaseError(
                        "Maximum connections reached"
                    )
                continue
    
    def return_connection(self, connection: Optional[DB]) -> None:
        """Return a connection to the pool"""
        if not connection:
            return
            
        try:
            # Verify connection is still valid
            connection.ping()
            
            # Reset any transaction state
            if connection._in_transaction:
                try:
                    connection.rollback()
                    log.debug("Rolled back transaction on returned connection")
                except:
                    pass
            
            # Only return to pool if we're under max size
            with self._lock:
                if len(self._active_connections) <= self.max_connections:
                    self._pool.put(connection)
                    log.debug("Connection returned to pool (pool size: %d)", self._pool.qsize())
                    return
                
                # If we're over max size, close the connection
                try:
                    connection.close()
                    log.debug("Closed excess connection")
                finally:
                    self._active_connections.discard(connection)
                    
        except Exception as e:
            # If connection is invalid, remove and create new one if needed
            with self._lock:
                self._active_connections.discard(connection)
                try:
                    connection.close()
                    log.warning("Closed invalid connection: %s", e)
                except:
                    pass
                
                # Only create new connection if we're under minimum
                if len(self._active_connections) < self.min_connections:
                    try:
                        new_conn = self._create_connection()
                        self._active_connections.add(new_conn)
                        self._pool.put(new_conn)
                        log.info("Created replacement connection (active: %d)", 
                                len(self._active_connections))
                    except Exception as e:
                        log.error("Failed to create replacement connection: %s", e)
    
    @property
    def size(self) -> int:
        """Current number of connections in the pool"""
        return self._pool.qsize()
    
    @property
    def active_connections(self) -> int:
        """Total number of active connections"""
        return len(self._active_connections)
    
    def close_all(self) -> None:
        """Close all connections in the pool"""
        log.info("Closing all database connections")
        with self._lock:
            closed_count = 0
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    try:
                        conn.close()
                        closed_count += 1
                    except:
                        pass
                except Empty:
                    break
            
            # Close any active connections not in pool
            for conn in list(self._active_connections):
                try:
                    conn.close()
                    closed_count += 1
                except:
                    pass
            self._active_connections.clear()
            log.info("Closed %d database connections", closed_count)

    def __enter__(self) -> 'ConnectionPool':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close_all()
