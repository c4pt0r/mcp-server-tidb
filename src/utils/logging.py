import logging
import threading

class ThreadFormatter(logging.Formatter):
    """Custom formatter that adds thread information to log messages"""
    
    def format(self, record):
        record.thread_name = threading.current_thread().name
        return super().format(record)

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up a logger with thread information
    
    Args:
        name: The name of the logger
        level: The logging level (default: INFO)
        
    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Only add handler if it doesn't already exist
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = ThreadFormatter(
            "%(asctime)s [%(thread_name)s] %(levelname)s - %(name)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    logger.setLevel(level)
    return logger 