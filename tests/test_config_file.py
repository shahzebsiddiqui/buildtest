import os

from buildtest.defaults import (
    BUILDTEST_CONFIG_FILE,
    BUILDTEST_CONFIG_BACKUP_FILE,
)
from buildtest.menu.config import func_config_view, func_config_restore


def test_config_file_exists():
    assert os.path.exists(BUILDTEST_CONFIG_FILE)


def test_view_configuration():
    func_config_view()


def test_config_restore():
    func_config_restore()
    # removing backup file and testing of restore works
    os.remove(BUILDTEST_CONFIG_BACKUP_FILE)
    func_config_restore()
