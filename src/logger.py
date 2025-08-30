"""
Centralized logging configuration for SMBX2 Episode Updater.
Handles both windowed and console builds properly.
"""
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path


def setup_logging(log_dir: Path = None, app_name: str = "SMBX2EpisodeUpdater"):
    """
    Set up logging for the application.
    
    Args:
        log_dir: Directory to store log files. Defaults to current working directory.
        app_name: Name for the log file.
    """
    if log_dir is None:
        log_dir = Path.cwd() / "logs"
    
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{app_name}.log"
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # File handler with rotation (keeps last 5 files, 10MB each)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler (only if stdout exists)
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # Handle windowed builds where stdout/stderr are None
    if sys.stdout is None:
        # Redirect stdout to log file
        sys.stdout = open(log_file.with_suffix('.stdout.log'), 'a', encoding='utf-8', buffering=1)
    if sys.stderr is None:
        # Redirect stderr to log file
        sys.stderr = open(log_file.with_suffix('.stderr.log'), 'a', encoding='utf-8', buffering=1)
    
    # Set up exception logging
    def log_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            # Don't log keyboard interrupts
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logger = logging.getLogger("exception")
        logger.error(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
    
    sys.excepthook = log_exception
    
    # Log startup
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """Get a logger instance for a module."""
    return logging.getLogger(name)


def log_tkinter_exception(exc_type, exc_value, exc_traceback):
    """Handler for Tkinter callback exceptions."""
    logger = logging.getLogger("tkinter")
    logger.error(
        "Tkinter callback exception",
        exc_info=(exc_type, exc_value, exc_traceback)
    )
