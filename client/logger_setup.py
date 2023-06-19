import logging

logging.basicConfig(
    # Set the desired log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    # filename='app.log',  # Specify the log file name
    # filemode='w'  # Choose the file mode (e.g., 'w' for write mode, 'a' for append mode)
)

log = logging.getLogger(__name__)
