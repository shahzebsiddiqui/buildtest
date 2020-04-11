import logging
import os
import shutil
from jsonschema import validate

from buildtest.utils.file import create_dir
from buildtest.defaults import (
    BUILDTEST_CONFIG_FILE,
    BUILDTEST_ROOT,
    DEFAULT_CONFIG_FILE,
    DEFAULT_CONFIG_SCHEMA,
)
from buildtest.buildsystem.schemas.utils import load_schema


def create_config_file():
    """If default config files don't exist, copy the default configuration provided by buildtest."""

    if not os.path.exists(BUILDTEST_CONFIG_FILE):
        shutil.copy(DEFAULT_CONFIG_FILE, BUILDTEST_CONFIG_FILE)


def init():
    """Buildtest init should check that the buildtest user root exists,
       and that dependency files are created. This is called by 
       load_configuration."""

    # check if $HOME/.buildtest exists, if not create directory
    if not os.path.exists(BUILDTEST_ROOT):
        print(
            f"Creating buildtest configuration directory: \
                 {BUILDTEST_ROOT}"
        )
        os.mkdir(BUILDTEST_ROOT)

    # Create subfolders for var and root
    create_dir(os.path.join(BUILDTEST_ROOT, "root"))
    create_dir(os.path.join(BUILDTEST_ROOT, "site"))

    # Create config files, module files, and log file
    create_config_file()


def check_configuration(config_path=None):
    """Checks all keys in configuration file (settings/settings.yml) are valid
       keys and ensure value of each key matches expected type . For some keys
       special logic is taken to ensure values are correct and directory path
       exists.       

       If any error is found buildtest will terminate immediately.
       :return: returns gracefully if all checks passes otherwise terminate immediately
       :rtype: exit code 1 if checks failed
    """

    logger = logging.getLogger(__name__)

    user_schema = load_configuration(config_path)

    config_schema = load_schema(DEFAULT_CONFIG_SCHEMA)
    logger.debug(f"Loading default configuration schema: {DEFAULT_CONFIG_SCHEMA}")

    logger.debug(f"Validating user schema: {user_schema} with schema: {config_schema}")
    validate(instance=user_schema, schema=config_schema)
    logger.debug("Validation was successful")


def load_configuration(config_path=None):
    """Load the default configuration file if no argument is specified.

       Parameters:

       :param config_path: Path to buildtest configuration file
       :type config_path: str, optional
    """

    init()

    config_path = config_path or BUILDTEST_CONFIG_FILE

    # load the configuration file
    return load_schema(config_path)


def get_default_configuration():
    """Load and return the default buildtest configuration file. """

    return load_configuration()
