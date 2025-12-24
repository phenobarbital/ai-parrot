from .types import SafeDict  # pylint: disable=no-name-in-module
from .toml import parse_toml_config
from navconfig.logging import logging

def cPrint(msg: str, level: str = "INFO"):
    """
    Console Print.

    Args:
        msg (str): Message to print.
        level (str, optional): Log level. Defaults to "INFO".
    """
    if level == "DEBUG":
        logging.debug(msg)
    elif level == "INFO":
        logging.info(msg)
    elif level == "WARNING":
        logging.warning(msg)
    elif level == "ERROR":
        logging.error(msg)
    else:
        print(msg)
