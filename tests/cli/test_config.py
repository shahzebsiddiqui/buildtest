import os
import shutil
import tempfile

import pytest

from buildtest.cli.build import BuildTest
from buildtest.cli.buildspec import buildspec_validate_command
from buildtest.cli.config import (
    list_profiles,
    remove_executors,
    remove_profiles,
    validate_config,
    view_configuration,
    view_executors,
    view_path,
    view_system,
)
from buildtest.config import SiteConfiguration
from buildtest.defaults import BUILDTEST_ROOT, DEFAULT_SETTINGS_SCHEMA, SCHEMA_ROOT
from buildtest.executors.setup import BuildExecutor
from buildtest.schemas.defaults import custom_validator
from buildtest.schemas.utils import load_recipe, load_schema
from buildtest.system import BuildTestSystem
from buildtest.utils.file import walk_tree

pytest_root = os.path.dirname(os.path.dirname(__file__))

system = BuildTestSystem()

configuration = SiteConfiguration(verbose=True)
configuration.detect_system()
configuration.validate()


@pytest.mark.cli
def test_config_systems():
    schema_files = os.path.join(
        SCHEMA_ROOT, "examples", "settings.schema.json", "valid"
    )
    # run 'buildtest config systems' against all valid configuration files
    for config_examples in os.listdir(schema_files):
        fname = os.path.join(schema_files, config_examples)
        configuration = SiteConfiguration(fname)
        view_system(configuration)


def test_container_executor():
    settings_file = os.path.join(
        pytest_root, "configuration", "container_executors.yml"
    )
    config = SiteConfiguration(settings_file=settings_file)
    config.detect_system()
    config.validate()


def test_remove_executors():
    temp_config_file = tempfile.NamedTemporaryFile(suffix=".yml")
    shutil.copy(configuration.file, temp_config_file.name)

    print(temp_config_file.name)
    config = SiteConfiguration(settings_file=temp_config_file.name)
    config.detect_system()
    configuration.validate()

    remove_executors(config, executor_names=["generic.local.bash", "generic.local.sh"])

    # remove an invalid executor type
    remove_executors(config, executor_names=["generic.XYZ.bash"])

    # remove an invalid executor name
    remove_executors(config, executor_names=["generic.local.bash1234"])


@pytest.mark.cli
def test_view_configuration():
    view_configuration(configuration)
    # buildtest config view --theme emacs
    view_configuration(configuration, theme="emacs")

    # buildtest config view --pager
    view_configuration(configuration, pager=True)


def test_valid_config_schemas():
    valid_schema_dir = os.path.join(pytest_root, "examples", "config_schemas", "valid")
    schema_config = load_schema(DEFAULT_SETTINGS_SCHEMA)
    for schema in walk_tree(valid_schema_dir, ".yml"):
        example = load_recipe(os.path.abspath(schema))
        custom_validator(recipe=example, schema=schema_config)


@pytest.mark.cli
def test_config_validate():
    validate_config(configuration=configuration)


@pytest.mark.cli
def test_config_path():
    view_path(configuration)


@pytest.mark.cli
class TestProfiles:
    tf = tempfile.NamedTemporaryFile(suffix=".yml")
    shutil.copy2(configuration.file, tf.name)

    buildtest_config = SiteConfiguration(settings_file=tf.name)
    buildtest_config.detect_system()
    buildtest_config.validate()

    cmd = BuildTest(
        configuration=buildtest_config, tags=["python"], save_profile="python"
    )
    cmd.build()

    def test_list_profiles(self):
        # buildtest config profiles list
        list_profiles(self.buildtest_config)

        # buildtest config profiles list --theme emacs --yaml
        list_profiles(self.buildtest_config, theme="emacs", print_yaml=True)

        # buildtest config profiles list --yaml
        list_profiles(self.buildtest_config, print_yaml=True)

    @pytest.mark.cli
    def test_profiles_remove(self):
        # get all profile names from configuration file
        profiles = list(self.buildtest_config.target_config["profiles"].keys())

        # This will remove all profiles since 'profiles' is list of all profile names
        remove_profiles(self.buildtest_config, profiles)

        # testing removing profiles when no profiles exist
        remove_profiles(self.buildtest_config, profiles[0])


@pytest.mark.cli
def test_config_executors():
    buildexecutor = BuildExecutor(configuration)

    # buildtest config executors list --json
    view_executors(
        configuration=configuration,
        buildexecutor=buildexecutor,
        display_in_json_format=True,
    )

    # buildtest config executors list --yaml
    view_executors(
        configuration=configuration,
        buildexecutor=buildexecutor,
        display_in_yaml_format=True,
    )

    # buildtest config executors list --all
    view_executors(
        configuration=configuration, buildexecutor=buildexecutor, display_all=True
    )

    # buildtest config executors list --disabled
    view_executors(
        configuration=configuration, buildexecutor=buildexecutor, display_disabled=True
    )

    # buildtest config executors list --invalid
    view_executors(
        configuration=configuration, buildexecutor=buildexecutor, display_invalid=True
    )

    # buildtest config executors list
    view_executors(configuration=configuration, buildexecutor=buildexecutor)


def test_disabled_invalid_executors():
    here = os.path.dirname(os.path.abspath(__file__))

    configfile = os.path.join(here, "configuration", "invalid_executors.yml")
    configuration = SiteConfiguration(settings_file=configfile)
    configuration.detect_system()
    configuration.validate()

    print("reading config file:", configfile)
    be = BuildExecutor(configuration)
    # buildtest config executors list --disabled
    view_executors(configuration=configuration, buildexecutor=be, display_disabled=True)

    # buildtest config executors list --invalid
    view_executors(configuration=configuration, buildexecutor=be, display_invalid=True)


def test_file_traversal_limit_in_config():
    here = os.path.dirname(os.path.abspath(__file__))

    configfile = os.path.join(here, "configuration", "file_traversal_example.yml")
    configuration = SiteConfiguration(settings_file=configfile)
    configuration.detect_system()
    configuration.validate()

    # exception can be raised when buildspec is invalid
    with pytest.raises(SystemExit):
        buildspec_validate_command(
            buildspecs=[os.path.join(BUILDTEST_ROOT, "tutorials")],
            configuration=configuration,
        )
