"""
This module contains all the methods related to "buildtest build" which is used
for building test scripts from a Buildspec
"""

import getpass
import json
import logging
import os
import platform
import re
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from typing import Dict, List, Optional

import yaml
from jsonschema.exceptions import ValidationError
from rich import box
from rich.panel import Panel
from rich.table import Column, Table

from buildtest import BUILDTEST_VERSION
from buildtest.builders.script import ScriptBuilder
from buildtest.builders.spack import SpackBuilder
from buildtest.buildsystem.builders import Builder
from buildtest.buildsystem.parser import BuildspecParser
from buildtest.cli.compilers import BuildtestCompilers
from buildtest.config import SiteConfiguration
from buildtest.defaults import (
    BUILD_HISTORY_DIR,
    BUILD_REPORT,
    BUILDSPEC_CACHE_FILE,
    BUILDTEST_DEFAULT_TESTDIR,
    BUILDTEST_LOGFILE,
    BUILDTEST_REPORTS,
    BUILDTEST_RERUN_FILE,
    DEFAULT_LOGDIR,
    console,
)
from buildtest.exceptions import (
    BuildTestError,
    InvalidBuildspec,
    InvalidBuildspecSchemaType,
)
from buildtest.executors.setup import BuildExecutor
from buildtest.log import init_logfile
from buildtest.schemas.defaults import custom_validator, schema_table
from buildtest.utils.file import (
    create_dir,
    is_dir,
    is_file,
    load_json,
    resolve_path,
    walk_tree,
)

logger = logging.getLogger(__name__)


# Context manager that copies stdout and any exceptions to a log file
class Tee(object):
    def __init__(self, filename):
        self.file = open(filename, "w")
        self.stdout = sys.stdout

    def __enter__(self):
        sys.stdout = self

    def __exit__(self, exc_type, exc_value, tb):
        sys.stdout = self.stdout
        if exc_type is not None:
            self.file.write(traceback.format_exc())
        self.file.close()

    def write(self, data):
        self.file.write(data)
        self.stdout.write(data)

    def flush(self):
        self.file.flush()
        self.stdout.flush()


def resolve_testdirectory(configuration: SiteConfiguration, testdir: str = None) -> str:
    """This method resolves which test directory to select. For example, one
    can specify test directory via command line ``buildtest build --testdir <path>``
    or path in configuration file. The default is $HOME/.buildtest/var/tests

    Args:
        configuration (buildtest.config.SiteConfiguration): An instance of SiteConfiguration class which contains content of buildtest configuration file
        testdir (str, optional): Path to test directory specified via command line ``buildtest build --testdir``

    Returns:
        str: Path to test directory
    """

    # variable to set test directory if prefix is set
    config_testdir = resolve_path(
        configuration.target_config.get("testdir"), exist=False
    )

    # resolve full path for test directory specified by --testdir option
    testdir = resolve_path(testdir, exist=False)

    # Order of precedence when detecting test directory
    # 1. Command line option --testdir
    # 2. Configuration option specified by 'testdir'
    # 3. Defaults to $BUILDTEST_ROOT/.var/tests
    test_directory = testdir or config_testdir or BUILDTEST_DEFAULT_TESTDIR

    return test_directory


def discover_buildspecs(
    buildspecs: Optional[List[str]] = None,
    exclude_buildspecs: Optional[List[str]] = None,
    name: Optional[List[str]] = None,
    executors: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    verbose: Optional[bool] = False,
    site_config: Optional[SiteConfiguration] = None,
) -> Dict[str, List[str]]:
    """This method discovers all buildspecs based on --buildspecs, --tags, --executor
    and excluding buildspecs (--exclude).

    Args:
        buildspecs (list, optional): List of input buildspecs passed by argument ``buildtest build --buildspec``
        exclude_buildspecs (list, optional): List of excluded buildspecs by argument ``buildtest build --exclude``
        name (list, optional): List of test names to discover buildspecs that are specified by ``buildtest build --name``
        tags (list, optional): List of input tags for discovering buildspecs by argument ``buildtest build --tags``
        executors (list, optional): List of input executors for discovering buildspecs by argument ``buildtest build --executor``
        verbose (bool, optional): Enable verbose output for buildtest that is specified by ``buildtest --verbose``
        site_config (buildtest.config.SiteConfiguration, optional): instance of SiteConfiguration class that has the buildtest configuration

    Returns:
        dict: A dictionary containing a list of included, excluded, detected buildspecs and buildspecs detected based on tags and executors
    """

    # a dictionary used to keep track of included, excluded and detected buildspecs.
    buildspec_dict = {}
    buildspec_dict["included"] = []
    buildspec_dict["excluded"] = []
    buildspec_dict["detected"] = []
    buildspec_dict["tags"] = {}
    buildspec_dict["name"] = {}
    buildspec_dict["executors"] = {}

    logger.debug(
        f"Discovering buildspecs based on tags={tags}, executor={executors}, buildspec={buildspecs}, excluded buildspec={exclude_buildspecs}"
    )

    cache = load_json(BUILDSPEC_CACHE_FILE)
    
    # get file_traversal_limit from the config
    if site_config and site_config.target_config:
        file_traversal_limit = site_config.target_config.get("file_traversal_limit", 1000)
    else:
        file_traversal_limit = 1000

    # discover buildspecs based on --tags
    if tags:
        found_buildspecs, buildspec_dict["tags"] = discover_buildspecs_by_tags(
            buildspec_cache=cache, tagnames=tags
        )

        buildspec_dict["included"] += found_buildspecs

        logger.debug(f"Discovered buildspecs based on tags: {tags}")
        logger.debug(found_buildspecs)

        if verbose:
            console.print(
                f"Discovered {len(found_buildspecs)} buildspecs based on tag: {tags}",
                style="bold blue",
            )

    # discover buildspecs based on --executor
    if executors:
        found_buildspecs, buildspec_dict["executors"] = discover_buildspecs_by_executor(
            buildspec_cache=cache, executors=executors
        )

        buildspec_dict["included"] += found_buildspecs
        logger.debug(f"Discovered buildspecs based on executors: {executors}")
        logger.debug(found_buildspecs)

        if verbose:
            console.print(
                f"Discovered {len(found_buildspecs)} buildspecs based on executor: {executors}",
                style="bold blue",
            )

    if name:
        found_buildspecs, buildspec_dict["name"] = discover_buildspecs_by_name(
            buildspec_cache=cache, names=name
        )

        buildspec_dict["included"] += found_buildspecs
        logger.debug(f"Discovered buildspecs based on names: {name}")
        logger.debug(found_buildspecs)

        if verbose:
            console.print(
                f"Discovered {len(found_buildspecs)} buildspecs based on names: {name}",
                style="bold blue",
            )

    # discover buildspecs based on --buildspec
    if buildspecs:
        # Discover list of one or more Buildspec files based on path provided. Since --buildspec can be provided multiple
        # times we need to invoke discover_buildspecs once per argument.
        for option in buildspecs:
            bp = discover_by_buildspecs(option, file_traversal_limit)

            # only add buildspecs if its not None
            if bp:
                buildspec_dict["included"] += bp

            if verbose:
                console.print(
                    f"Discovered {len(bp)} buildspecs based on argument {option}",
                    style="bold blue",
                )

    # remove any duplicate Buildspec from list by converting list to set and then back to list
    buildspec_dict["included"] = list(set(buildspec_dict["included"]))

    # if no files discovered let's stop now
    if not buildspec_dict["included"]:
        console.print("[red]No buildspecs discovered based on input arguments.")
        sys.exit(1)

    logger.debug(
        f"buildtest discovered the following Buildspecs: {buildspec_dict['included']}"
    )

    buildspec_dict["detected"] = buildspec_dict["included"].copy()

    # if user pass buildspecs to be excluded (buildtest build -x <buildspec>) then
    # discover all excluded buildspecs and remove from discovered list
    if exclude_buildspecs:
        # discover all excluded buildspecs, if its file add to list,
        # if its directory traverse all .yml files
        for name in exclude_buildspecs:
            bp = discover_by_buildspecs(name, file_traversal_limit)
            if bp:
                buildspec_dict["excluded"] += bp

        # remove any duplicates from list
        buildspec_dict["excluded"] = list(set(buildspec_dict["excluded"]))

        logger.debug(
            f"The exclude pattern is the following: {buildspec_dict['excluded']}"
        )

        # detected buildspecs are any buildspecs in included buildspecs not in excluded buildspecs
        buildspec_dict["detected"] = [
            file
            for file in buildspec_dict["included"]
            if file not in buildspec_dict["excluded"]
        ]

        logger.debug(
            f"After excluding all buildspecs we found the following buildspecs that will be run: {buildspec_dict['detected']}"
        )

    # if no files remain after exclusion let's stop now.
    if not buildspec_dict["detected"]:
        console.print("[red]Unable to detect any buildspec files to process.")
        sys.exit(1)

    return buildspec_dict


def print_discovered_buildspecs(buildspec_dict):
    """This method will print the discovered buildspecs in table format

    Args:
        buildspec_dict (dict): A dictionary containing a list of included and excluded buildspecs and breakdown of buildspecs by tags and executors
    """

    console.rule("[bold red] Discovering Buildspecs")

    table = Table(
        title="Discovered buildspecs",
        box=box.DOUBLE_EDGE,
        header_style="blue",
        show_footer=True,
    )
    table.add_column(
        "buildspec",
        style="green",
        overflow="fold",
        footer=f"[bold]Total: {len(buildspec_dict['included'])}",
    )

    for i in buildspec_dict["included"]:
        table.add_row(i)
    console.print(table)

    # if any buildspecs removed due to -x option we print them to screen
    if buildspec_dict["excluded"]:
        table = Table(
            title="Excluded buildspecs",
            box=box.DOUBLE_EDGE,
            header_style="blue",
            show_footer=True,
        )
        table.add_column(
            "buildspec",
            style="red",
            overflow="fold",
            footer=f"[bold]Total: {len(buildspec_dict['excluded'])}",
        )

        for i in buildspec_dict["excluded"]:
            table.add_row(i)
        console.print(table)

    # print breakdown of buildspecs by tags
    if buildspec_dict.get("tags"):
        for tagname in buildspec_dict["tags"].keys():
            table = Table(
                title=f"Buildspecs By Tag={tagname}",
                box=box.DOUBLE_EDGE,
                header_style="blue",
                show_footer=True,
            )
            table.add_column(
                "buildspec",
                style="turquoise2",
                overflow="fold",
                footer=f"[bold]Total: {len(buildspec_dict['tags'][tagname])}",
            )
            for row in buildspec_dict["tags"][tagname]:
                table.add_row(row)
            console.print(table)

    # print breakdown of buildspecs by executors
    if buildspec_dict.get("executors"):
        for executorname in buildspec_dict["executors"].keys():
            table = Table(
                title=f"Buildspecs by Executor={executorname}",
                box=box.DOUBLE_EDGE,
                header_style="blue",
                show_footer=True,
            )
            table.add_column(
                "buildspecs",
                style="magenta1",
                overflow="fold",
                footer=f"[bold]Total: {len(buildspec_dict['executors'][executorname])}",
            )
            for row in buildspec_dict["executors"][executorname]:
                table.add_row(f"{row}")
            console.print(table)

    # print breakdown of buildspecs by executors
    if buildspec_dict.get("name"):
        for name in buildspec_dict["name"].keys():
            table = Table(
                title=f"Buildspecs by Name={name}",
                box=box.DOUBLE_EDGE,
                header_style="blue",
                show_footer=True,
            )
            table.add_column(
                "buildspecs",
                style="yellow2",
                overflow="fold",
                footer=f"[bold]Total: {len(buildspec_dict['name'][name])}",
            )
            for row in buildspec_dict["name"][name]:
                table.add_row(f"{row}")
            console.print(table)

    print("\n")
    console.print(
        "[green bold]Total Discovered Buildspecs: ", len(buildspec_dict["included"])
    )
    console.print(
        "[red bold]Total Excluded Buildspecs: ", len(buildspec_dict["excluded"])
    )
    console.print(
        "[blue bold]Detected Buildspecs after exclusion: ",
        len(buildspec_dict["detected"]),
    )


def discover_buildspecs_by_tags(buildspec_cache, tagnames):
    """This method discovers buildspecs by tags, using ``buildtest build --tags`` option.
    This method will read BUILDSPEC_CACHE_FILE and search for ``tags`` key in buildspec recipe and
    match with input tag. The input ``tags`` are a list of tagnames to search in buildspec with the
    ``tags`` property in buildspec. The return is a list of buildspec files to process.

    Args:
        buildspec_cache (dict): Loaded buildspec cache as a dictionary
        tagnames (list): List of input tags from command line argument ``buildtest build --tags <tags>``

    Returns:
        list, dict: first argument is a list of buildspecs discovered for all tag names. The second argument is
        dictionary breakdown of buildspecs by each tag name
    """

    buildspecs_by_tags = {}

    buildspecs = []
    # query all buildspecs from BUILDSPEC_CACHE_FILE for tags keyword and
    # if it matches input_tag we add buildspec to list
    tagnames = [
        tag.strip() for tagname in tagnames for tag in tagname.split(",") if tag.strip()
    ]

    if not tagnames:
        return buildspecs, buildspecs_by_tags

    for name in tagnames:
        buildspecs_by_tags[name] = set()

        for buildspecfile in buildspec_cache["buildspecs"].keys():
            for test in buildspec_cache["buildspecs"][buildspecfile].keys():
                # if input tag is not of type str we skip the tag name since it is not valid
                if not isinstance(name, str):
                    logger.warning(f"Tag: {name} is not of type 'str'")
                    continue

                # if tags is not declared we set to empty list
                tag = (
                    buildspec_cache["buildspecs"][buildspecfile][test].get("tags") or []
                )

                if name in tag:
                    buildspecs.append(buildspecfile)
                    buildspecs_by_tags[name].add(buildspecfile)

    # remove any duplicates and return a list
    buildspecs = list(set(buildspecs))

    return buildspecs, buildspecs_by_tags


def discover_buildspecs_by_name(buildspec_cache, names):
    """This method will discover buildspecs given a list of test names.

     Args:
        buildspec_cache (dict): Loaded buildspec cache as a dictionary
        names (list): List of test names to search for buildspecs from cache


    Returns:
         list, dict: first argument is a list of buildspecs discovered for all test names. The second argument is
         dictionary breakdown of buildspecs by each name
    """

    buildspec_by_names = {}
    found_buildspecs = []
    for name in names:
        for buildspecfile in buildspec_cache["buildspecs"].keys():
            # if there is a match, add buildspecs and proceed to next test name
            if name in buildspec_cache["buildspecs"][buildspecfile].keys():
                buildspec_by_names[name] = [buildspecfile]
                found_buildspecs.append(buildspecfile)
                break

    found_buildspecs = list(set(found_buildspecs))
    return found_buildspecs, buildspec_by_names


def discover_buildspecs_by_executor(buildspec_cache, executors):
    """This method discovers buildspecs by executor name, using ``buildtest build --executor``
    command. This method will read BUILDSPEC_CACHE_FILE and search for ``executor`` property
    in buildspec and match with input executor name. The return is a list of matching
    buildspec with executor name to process.

    Args:
        buildspec_cache (dict): Loaded buildspec cache as a dictionary
        executors (list): List of input executor name from command line argument ``buildtest build --executor <name>``

    Returns:
         list, dict: first argument is a list of buildspecs discovered for all executors. The second argument is
         dictionary breakdown of buildspecs by each executor name
    """

    buildspecs_by_executors = {}

    buildspecs = []
    # query all buildspecs from BUILDSPEC_CACHE_FILE for tags keyword and
    # if it matches input_tag we add buildspec to list

    for name in executors:
        buildspecs_by_executors[name] = set()

        for buildspecfile in buildspec_cache["buildspecs"].keys():
            for test in buildspec_cache["buildspecs"][buildspecfile].keys():
                # check if executor in buildspec matches one in argument (buildtest build --executor <EXECUTOR>)
                if name == buildspec_cache["buildspecs"][buildspecfile][test].get(
                    "executor"
                ):
                    buildspecs.append(buildspecfile)
                    buildspecs_by_executors[name].add(buildspecfile)

    # remove any duplicates and return back a list
    buildspecs = list(set(buildspecs))

    return buildspecs, buildspecs_by_executors


def discover_by_buildspecs(buildspec: str, file_traversal_limit: int) -> list:
    """Given a buildspec file specified by the user with ``buildtest build --buildspec``,
    discover one or more files and return a list for buildtest to process.
    This method is called once per argument of ``--buildspec`` or ``--exclude``
    option. If its a directory path we recursively find all buildspecs with
    with **.yml** extension. If filepath doesn't exist or file extension is not **.yml** we
    return None and capture error in log.

    .. code-block:: console

        # file path
        buildtest build --buildspec tutorials/hello.sh.yml

        # directory path
        buildtest build --buildspec tutorials

        # invalid file path returns None
        buildtest build -b /xyz.yml

        # invalid file extension
        buildtest build -b README.md


    Args:
        buildspec (str): Full path to buildspec based on argument ``buildtest build --buildspec``
        file_traversal_limit (int): Limit the number of files that can be traversed when searching for buildspecs

    Returns:
        list: List of resolved buildspecs.
    """

    buildspecs = []

    # if buildspec doesn't exist print message and log error and return
    if not os.path.exists(os.path.abspath(buildspec)):
        msg = (
            f"[red]Unable to find any buildspecs: {os.path.abspath(buildspec)} [/red] \n"
            + "Please provide an absolute or relative path to a file or directory"
        )
        console.print(msg)
        logger.error(msg)
        return

    # Now handle path based on being a directory or file path
    if os.path.isdir(buildspec):
        logger.debug(
            f"Buildspec File: {buildspec} is a directory so traversing directory tree to find all Buildspec files with .yml extension"
        )
        buildspecs = walk_tree(buildspec, ".yml", file_traverse_limit=file_traversal_limit)
    elif os.path.isfile(buildspec):
        # if buildspec doesn't end in .yml extension we print message and return None
        if not re.search(".yml$", buildspec):
            msg = f"[red]{buildspec} does not end in file extension .yml"
            console.print(msg)
            logger.error(msg)
            return

        buildspecs = [buildspec]
        logger.debug(f"Buildspec: {buildspec} is a file")

    # If we don't have any files discovered
    if not buildspecs:
        msg = "[red]Unable to find buildspecs in %s." % resolve_path(buildspec)
        console.print(msg)
        logger.error(msg)
        return

    # return all buildspec by resolving path, this gets the real canonical path and address shell expansion and user expansion
    buildspecs = [resolve_path(file) for file in buildspecs]

    logger.info(
        f"Based on input argument we discovered the following buildspecs: {buildspecs}"
    )
    return buildspecs


def print_filters():
    """This method will print list of filters fields used by ``buildtest build --filter``. This method is invoked by
    running ``buildtest build --helpfilter``.
    """

    table = Table(title="Buildtest Filters", header_style="blue")
    table.add_column("Field", style="green", overflow="fold")
    table.add_column("Description", style="red", overflow="fold")

    table.add_row("tags", "Filter tests by [italic]'tag'[/italic] field")
    table.add_row("type", "Filter test by [italic]'type'[/italic] field")
    table.add_row("maintainers", "Filter test by [italic]'maintainers'[/italic] field")
    console.print(table)


class BuildTest:
    """This class is an interface to building tests via ``buildtest build`` command."""

    def __init__(
        self,
        account=None,
        buildspecs=None,
        configuration=None,
        display=None,
        dry_run=None,
        exclude_buildspecs=None,
        exclude_tags=None,
        executors=None,
        executor_type=None,
        filter_buildspecs=None,
        helpfilter=None,
        limit=None,
        max_jobs=None,
        maxpendtime=None,
        modulepurge=None,
        modules=None,
        name=None,
        numnodes=None,
        numprocs=None,
        poll_interval=None,
        profile=None,
        rebuild=None,
        remove_stagedir=None,
        report_file=None,
        rerun=None,
        retry=None,
        save_profile=None,
        strict=None,
        tags=None,
        testdir=None,
        timeout=None,
        unload_modules=None,
        validate=None,
        verbose=None,
        write_config_file=None,
    ):
        """The initializer method is responsible for checking input arguments for type
        check, if any argument fails type check we raise an error. If all arguments pass
        we assign the values and proceed with building the test.

        Args:

            account (str, optional): Project account to charge jobs. This takes input argument ``buildtest build --account``
            buildspecs (list, optional): list of buildspecs from command line ``buildtest build --buildspec``
            configuration (buildtest.config.SiteConfiguration, optional): Loaded configuration content which is an instance of SiteConfiguration
            display (list, optional): Display content of output or test. This is specified via ``buildtest build --display``
            dry_run (bool, optional): Show a list of tests that will potentially be run without actually running them via ``buildtest build --dry-run``
            exclude_buildspecs (list, optional): list of excluded buildspecs from command line ``buildtest build --exclude``
            exclude_tags (list, optional): list if tags to exclude specified via command line ``buildtest build --exclude-tags``
            executor_type (bool, optional): Filter test by executor type. This option will filter test after discovery by local or batch executors. This can be specified via ``buildtest build --exec-type``
            executors (list, optional): list of executors passed from command line ``buildtest build --executors``
            filter_buildspecs (dict, optional): filters buildspecs and tests based on ``buildtest build --filter`` argument which is a key/value dictionary that can filter tests based on **tags**, **type**, and **maintainers**
            helpfilter (bool, optional): Display available filter fields for ``buildtest build --filter`` command. This argument is set to ``True`` if one specifies ``buildtest build --helpfilter``
            limit (int, optional): Limit number of tests that can be run. This option is specified by ``buildtest build --limit``
            max_jobs (int, optional): Maximum number of jobs to run concurrently. This option is specified by ``buildtest build --max-jobs``
            maxpendtime (int, optional): Specify maximum pending time in seconds for batch job until job is cancelled
            modulepurge (bool, optional): Determine whether to run 'module purge' before running test. This is specified via ``buildtest build --modulepurge``.
            modules (str, optional): List of modules to load for every test specified via ``buildtest build --modules``.
            name (list, optional): list of test names to run specified via command line ``buildtest build --name``
            numnodes (list, optional): List of comma separated nodes values to run batch jobs specified via ``buildtest build --nodes``
            numprocs (list, optional): List of comma separated process values to run batch jobs specified via ``buildtest build --procs``
            poll_interval (int, optional): Specify poll interval in seconds for polling batch jobs.
            profile (str, optional): Profile to load from buildtest configuration specified by ``buildtest build --profile``
            rebuild (int, optional): Rebuild tests X times based on ``buildtest build --rebuild`` option.
            remove_stagedir (bool, optional): remove stage directory after job completion
            report_file (str, optional): Location to report file where test data will be written upon completion. This can be specified via ``buildtest build --report`` command
            rerun (bool, optional): Rerun last successful **buildtest build** command. This is specified via ``buildtest build --rerun``. All other options will be ignored and buildtest will read buildtest options from file **BUILDTEST_RERUN_FILE**.
            retry (int, optional): Number of retry for failed jobs
            save_profile (str, optional): Save profile to buildtest configuration specified by ``buildtest build --save-profile``
            strict (bool, optional): Enable strict mode for buildtest. This option is specified by ``buildtest build --strict``
            tags (list, optional): list if tags to discover tests specified via command line ``buildtest build --tags``
            testdir (str): Path to test directory where tests are written. This argument can be passed from command line ``buildtest build --testdir``
            timeout (int, optional): Test timeout in seconds specified by ``buildtest build --timeout``
            unload_modules (str, optional): List of modules to unload for every test specified via ``buildtest build --unload-modules``.
            validate (bool, optional): Validate given buildspecs and buildtest will stop after parse stage which can be configured via ``buildtest build --validate`` option
            verbose (bool, optional): Enable verbose output for buildtest that is specified by ``buildtest --verbose``
            write_config_file (str, optional): Write configuration file to specified location. This is specified by ``buildtest build --write-config-file``

        """
        self.verbose = verbose

        # variable used to determine if buildtest build command was successful. We initially start with False and if method runs to completion we set to True
        self.success = False

        if self.verbose:
            console.print("[blue]Starting buildtest build")
            console.print(
                "[blue]Performing type check on all arguments to buildtest build"
            )

        # check for input arguments that are expected to be a list
        for arg_name in [
            buildspecs,
            exclude_buildspecs,
            tags,
            exclude_tags,
            executors,
            name,
            display,
        ]:
            if arg_name and not isinstance(arg_name, list):
                raise BuildTestError(f"{arg_name} is not of type list")

        # check for input arguments that are expected to be a string
        for arg_name in [testdir, save_profile, profile, write_config_file]:
            if arg_name and not isinstance(arg_name, str):
                raise BuildTestError(f"{arg_name} is not of type str")

        # if --rebuild is specified check if its an integer and within 50 rebuild limit
        if rebuild:
            if not isinstance(rebuild, int):
                raise BuildTestError(f"{rebuild} is not of type int")

            if rebuild > 50:
                raise BuildTestError(
                    f"--rebuild {rebuild} exceeds maximum rebuild limit of 50"
                )

        for field in [timeout, limit, retry, max_jobs]:
            if field is not None:
                if not isinstance(field, int):
                    raise BuildTestError(f"{field} is not of type int")
                if field <= 0:
                    raise BuildTestError(f"{field} must be greater than 0")

        self.remove_stagedir = remove_stagedir
        self.configuration = configuration
        self.buildspecs = buildspecs
        self.display = display
        self.exclude_buildspecs = exclude_buildspecs
        self.tags = tags
        self.name = name
        self.exclude_tags = exclude_tags
        self.executors = executors
        self.maxpendtime = maxpendtime
        self.pollinterval = poll_interval
        self.helpfilter = helpfilter
        self.retry = retry
        self.rerun = rerun
        self.account = account
        self.validate = validate
        self.dry_run = dry_run
        self.filter_buildspecs = filter_buildspecs
        self.rebuild = rebuild
        self.modules = modules
        self.modulepurge = modulepurge
        self.unload_modules = unload_modules
        self.numprocs = numprocs
        self.numnodes = numnodes
        self.executor_type = executor_type
        self.timeout = timeout
        self.limit = limit
        self.save_profile = save_profile
        self.profile = profile
        self.max_jobs = max_jobs
        self.strict = strict
        self.write_config_file = write_config_file

        # this variable contains the detected buildspecs that will be processed by buildtest.
        self.detected_buildspecs = None
        self.invalid_buildspecs = None
        self.builders = None
        self.finished_builders = None

        # This command should will print available filters (buildtest build --helpfilter) and exit
        if self.helpfilter:
            print_filters()
            return

        if self.exclude_tags:
            # if tags are specified as comma separated list such as 'buildtest bd -xt tag1,tag2' then we split and convert to list
            self.exclude_tags = [
                tag.strip()
                for tagname in self.exclude_tags
                for tag in tagname.split(",")
                if tag.strip()
            ]

        # get real path to log directory which accounts for variable expansion, user expansion, and symlinks
        self.logdir = (
            resolve_path(self.configuration.target_config.get("logdir"), exist=False)
            or DEFAULT_LOGDIR
        )

        # create a temporary file to store logfile and we don't delete file by setting 'delete=False'
        # by default tempfile will delete file upon exit.
        self.logfile = tempfile.NamedTemporaryFile(
            prefix="buildtest_", delete=False, suffix=".log"
        )

        if self.logdir:
            create_dir(self.logdir)
            self.logfile.name = os.path.join(
                self.logdir, os.path.basename(self.logfile.name)
            )

        logger = logging.getLogger(__name__)
        # if BUILDTEST_LOGFILE is not created we initialize logger. This is relevant when invoking BuildTest class in regression test
        if not is_file(BUILDTEST_LOGFILE):
            logger = init_logfile(logfile=BUILDTEST_LOGFILE)

        self.testdir = resolve_testdirectory(self.configuration, testdir)

        create_dir(self.testdir)

        logger.debug(f"Tests will be written in {self.testdir}")

        self.report_file = resolve_path(report_file, exist=False) or BUILD_REPORT

        if is_dir(self.report_file):
            raise BuildTestError(
                f"{report_file} is a directory please specify a file name where report will be written"
            )

        if self.save_profile:
            self.save_profile_to_configuration()
            return

        # if buildtest build --rerun is set read file then rerun last command regardless of input specified in command line.
        # the last command is stored in file BUILDTEST_RERUN_FILE which is a dictionary containing the input arguments.
        if self.rerun:
            self.load_rerun_file()

        # if --profile is invoked then we load profile from configuration file
        if self.profile:
            self.load_profile()

        self.buildexecutor = BuildExecutor(
            self.configuration,
            maxpendtime=self.maxpendtime,
            account=self.account,
            pollinterval=self.pollinterval,
            timeout=self.timeout,
            max_jobs=self.max_jobs,
        )
        """
        self.system = buildtest_system

        if not isinstance(self.system, BuildTestSystem):
            self.system = BuildTestSystem()
        """
        if self.filter_buildspecs:
            self._validate_filters()

        msg = f"""
[magenta]User:[/]               [cyan]{getpass.getuser()}
[magenta]Hostname:[/]           [cyan]{platform.node()}
[magenta]Platform:[/]           [cyan]{platform.system()}
[magenta]Current Time:[/]       [cyan]{datetime.now().strftime('%Y/%m/%d %X')}
[magenta]buildtest path:[/]     [cyan]{shutil.which('buildtest')}
[magenta]buildtest version:[/]  [cyan]{BUILDTEST_VERSION}    
[magenta]python path:[/]        [cyan]{os.getenv("BUILDTEST_PYTHON")}
[magenta]python version:[/]     [cyan]{platform.python_version()}[/]
[magenta]Configuration File:[/] [cyan]{self.configuration.file}[/]
[magenta]Test Directory:[/]     [cyan]{self.testdir}[/]
[magenta]Report File:[/]        [cyan]{self.report_file}[/]
[magenta]Command:[/]            [cyan]{' '.join(sys.argv)}[/]
"""
        console.print(Panel.fit(msg, title="buildtest summary"), justify="left")

    def load_rerun_file(self):
        """This will load content of file BUILDTEST_RERUN_FILE that contains a dictionary of key/value pair
        that keeps track of last ``buildtest build`` command. This is used with ``buildtest build --rerun``. Upon loading
        file we reinitalize all class variables that store argument for ``buildtest build`` options
        """

        if not is_file(BUILDTEST_RERUN_FILE):
            raise BuildTestError(
                "Please run a 'buildtest build' command before using '--rerun' option. "
            )
        console.print(
            f"Reading content of rerun file {BUILDTEST_RERUN_FILE} all other options will be ignored."
        )

        content = load_json(BUILDTEST_RERUN_FILE)

        configuration = SiteConfiguration(content["configuration"])
        configuration.detect_system()
        configuration.validate()
        self.configuration = configuration
        self.buildspecs = content["buildspecs"]
        self.display = content["display"]
        self.tags = content["tags"]
        self.exclude_tags = content["exclude_tags"]
        self.name = content["name"]
        self.filter = content["filter"]
        self.exclude_buildspecs = content["exclude_buildspecs"]
        self.executors = content["executors"]
        self.report_file = content["report_file"]
        self.validate = content["validate"]
        self.dry_run = content["dry_run"]
        self.remove_stagedir = content["remove_stagedir"]
        self.testdir = content["testdir"]
        self.maxpendtime = content["maxpendtime"]
        self.pollinterval = content["pollinterval"]
        self.account = content["account"]
        self.retry = content["retry"]
        self.modules = content["modules"]
        self.modulepurge = content["modulepurge"]
        self.unload_modules = content["unload_modules"]
        self.rebuild = content["rebuild"]
        self.numnodes = content["numnodes"]
        self.numprocs = content["numprocs"]
        self.executor_type = content["executor_type"]
        self.timeout = content["timeout"]
        self.limit = content["limit"]
        self.max_jobs = content["max_jobs"]
        self.strict = content["strict"]

    def save_rerun_file(self):
        """Record buildtest command options and save them into rerun file which is read when invoking ``buildtest build --rerun``."""
        buildtest_cmd = {
            "configuration": self.configuration.file,
            "buildspecs": self.buildspecs,
            "display": self.display,
            "tags": self.tags,
            "exclude_tags": self.exclude_tags,
            "name": self.name,
            "filter": self.filter_buildspecs,
            "exclude_buildspecs": self.exclude_buildspecs,
            "executors": self.executors,
            "report_file": self.report_file,
            "dry_run": self.dry_run,
            "validate": self.validate,
            "remove_stagedir": self.remove_stagedir,
            "testdir": self.testdir,
            "maxpendtime": self.maxpendtime,
            "pollinterval": self.pollinterval,
            "account": self.account,
            "rebuild": self.rebuild,
            "retry": self.retry,
            "modules": self.modules,
            "modulepurge": self.modulepurge,
            "unload_modules": self.unload_modules,
            "numprocs": self.numprocs,
            "numnodes": self.numnodes,
            "executor_type": self.executor_type,
            "timeout": self.timeout,
            "limit": self.limit,
            "max_jobs": self.max_jobs,
            "strict": self.strict,
        }

        with open(BUILDTEST_RERUN_FILE, "w") as fd:
            fd.write(json.dumps(buildtest_cmd, indent=2))

    def save_profile_to_configuration(self):
        """This method will save profile to configuration file. This method is called when ``buildtest build --save-profile`` is invoked. We will open the configuration
        file and update the profile section, if profile already exist we will override it, otherwise we will insert into the configuration file.
        """
        config_file_path = None
        if self.write_config_file:
            config_file_path = resolve_path(self.write_config_file, exist=False)
            if not config_file_path:
                raise BuildTestError(
                    f"Unable to resolve path for {self.write_config_file}"
                )
            if is_dir(config_file_path):
                raise BuildTestError(
                    f"{config_file_path} is a directory, please specify a file path"
                )

            if os.path.exists(config_file_path):
                raise BuildTestError(
                    f"[red]Configuration file {config_file_path} already exists. Please specify a new file path"
                )
            if not os.path.splitext(config_file_path)[1] == ".yml":
                raise BuildTestError(
                    f"[red]Configuration file {config_file_path} must end in .yml extension"
                )

        config_file_path = config_file_path or self.configuration.file
        resolved_buildspecs = []
        if self.buildspecs:
            for file in self.buildspecs:
                resolved_buildspecs.append(resolve_path(file, exist=True))

        # dictionary to store configuration for a profile
        profile_configuration = {
            "buildspecs": resolved_buildspecs or None,
            "exclude-buildspecs": self.exclude_buildspecs,
            "display": self.display,
            "tags": self.tags,
            "exclude-tags": self.exclude_tags,
            "name": self.name,
            "executors": self.executors,
            "module": self.modules,
            "unload-modules": self.unload_modules,
            "module-purge": self.modulepurge,
            "validate": self.validate,
            "dry-run": self.dry_run,
            "rebuild": self.rebuild,
            "limit": self.limit,
            "account": self.account,
            "procs": self.numprocs,
            "nodes": self.numnodes,
            "testdir": self.testdir,
            "timeout": self.timeout,
            "filter": self.filter_buildspecs,
            "executor-type": self.executor_type,
            "max_jobs": self.max_jobs,
            "remove-stagedir": self.remove_stagedir,
            "strict": self.strict,
        }
        # we need to set module-purge to None if it is False. We delete all keys  that are 'None' before writing to configuration file
        profile_configuration["module-purge"] = (
            None if self.modulepurge is False else True
        )

        if self.verbose:
            console.print(
                f"Showing Profile Configuration in JSON format for profile name: {self.save_profile}",
                style="bold blue",
            )
            console.print(json.dumps(profile_configuration, indent=2))

        # iterate over profile configuration and remove keys that are None
        remove_keys = []
        for key, value in profile_configuration.items():
            if value is None:
                remove_keys.append(key)
        for key in remove_keys:
            del profile_configuration[key]

        system = self.configuration.name()
        # delete system entry since we need to update with new profile
        del self.configuration.config["system"][system]

        self.configuration.config["system"][system] = self.configuration.target_config

        # if profile section does not exist we create it
        if not self.configuration.target_config.get("profiles"):
            self.configuration.target_config["profiles"] = {}

        # update profile section with new profile. If profile already exist we override it
        self.configuration.target_config["profiles"][
            self.save_profile
        ] = profile_configuration

        # validate entire buildtest configuration with schema to ensure configuration is valid
        custom_validator(
            self.configuration.config, schema_table["settings.schema.json"]["recipe"]
        )

        console.print(
            f"Saved profile {self.save_profile} to configuration file {config_file_path}"
        )

        with open(config_file_path, "w") as fd:
            yaml.safe_dump(
                self.configuration.config, fd, default_flow_style=False, sort_keys=False
            )

    def load_profile(self):
        """This method will load profile from configuration file and update class variables used for ``buildtest build`` command.
        This method is called when ``buildtest build --profile`` is invoked."""

        if self.verbose:
            console.print(
                f"[blue]Loading profile {self.profile} from configuration file"
            )

        profile_configuration = self.configuration.get_profile(self.profile)

        self.buildspecs = profile_configuration.get("buildspecs")
        self.exclude_buildspecs = profile_configuration.get("exclude-buildspecs")
        self.display = profile_configuration.get("display")
        self.tags = profile_configuration.get("tags")
        self.exclude_tags = profile_configuration.get("exclude-tags")
        self.name = profile_configuration.get("name")
        self.executors = profile_configuration.get("executors")
        self.limit = profile_configuration.get("limit")
        self.account = profile_configuration.get("account")
        self.numprocs = profile_configuration.get("procs")
        self.numnodes = profile_configuration.get("nodes")
        self.testdir = profile_configuration.get("testdir")
        self.timeout = profile_configuration.get("timeout")
        self.modules = profile_configuration.get("module")
        self.unload_modules = profile_configuration.get("unload-modules")
        self.modulepurge = profile_configuration.get("module-purge")
        self.validate = profile_configuration.get("validate")
        self.dry_run = profile_configuration.get("dry-run")
        self.rebuild = profile_configuration.get("rebuild")
        self.filter_buildspecs = profile_configuration.get("filter")
        self.executor_type = profile_configuration.get("executor-type")
        self.max_jobs = profile_configuration.get("max_jobs")
        self.remove_stagedir = profile_configuration.get("remove-stagedir")
        self.strict = profile_configuration.get("strict")

    def _validate_filters(self):
        """Check filter fields provided by ``buildtest build --filter`` are valid types and supported. Currently
        supported filter fields are ``tags``, ``type``, ``maintainers``

        Raises:
            BuildTestError: if input filter field is not valid we raise exception. For ``type`` filter we check for value and make sure the schema type is supported
        """

        valid_fields = ["tags", "type", "maintainers"]

        for key in self.filter_buildspecs.keys():
            if key not in valid_fields:
                raise BuildTestError(
                    f"Invalid filter field: {key} the available filter fields are: {valid_fields}"
                )

            if key == "type":
                if any(
                    type_value not in schema_table["types"]
                    for type_value in self.filter_buildspecs[key]
                ):
                    raise BuildTestError(
                        f"Invalid value for filter 'type': '{self.filter_buildspecs[key]}', valid schema types are : {schema_table['types']}"
                    )

    def build(self):
        """This method is responsible for discovering buildspecs based on input argument. Then we parse
        the buildspecs and retrieve builder objects for each test. Each builder object will invoke :func:`buildtest.buildsystem.base.BuilderBase.build`
        which will build the test script, and then we run the test and update report.
        """

        # if --helpfilter is specified then return immediately.
        if self.helpfilter or self.save_profile:
            return

        # pass in self.config
        self.discovered_bp = discover_buildspecs(
            buildspecs=self.buildspecs,
            exclude_buildspecs=self.exclude_buildspecs,
            name=self.name,
            tags=self.tags,
            executors=self.executors,
            verbose=self.verbose,
            site_config=self.configuration,
        )

        print_discovered_buildspecs(buildspec_dict=self.discovered_bp)

        self.detected_buildspecs = self.discovered_bp["detected"]

        self.save_rerun_file()

        # Parse all buildspecs and skip any buildspecs that fail validation, return type
        # is a builder object used for building test.
        self.parse_buildspecs()

        # if no builders found or buildtest build --validate set we return from method
        if not self.builders or self.validate:
            return

        if self.limit:
            self.builders = self.builders[: self.limit]
            console.print(
                f"[red]Limit number of tests to {self.limit} for Building and Running. "
            )

        self.build_phase()

        # if --dry-run is specified we return from method
        if self.dry_run:
            return

        self.finished_builders = self.run_phase()

        # store path to logfile in each builder object. There is a single logfile per build.
        for builder in self.finished_builders:
            builder.metadata["logpath"] = self.logfile.name

        if self.remove_stagedir:
            logger.debug("Removing stage directory for all tests")
            for builder in self.finished_builders:
                shutil.rmtree(builder.stage_dir)

        update_report(
            valid_builders=self.finished_builders,
            report_file=self.report_file,
            verbose=self.verbose,
        )

        print(f"Writing Logfile to {self.logfile.name}")

        self._update_build_history(self.finished_builders)
        self.success = True

    def parse_buildspecs(self):
        """Parse all buildspecs by passing buildspec file to :class:`buildtest.buildsystem.parser.BuildspecParser` class.
        If buildspec fails validation we skip the buildspec and print all skipped buildspecs.
        If buildspec passes validation we get all builders by invoking :class:`buildtest.buildsystem.builders.Builder` class that
        is responsible for creating builder objects for each test.

        Raises:
            SystemExit: If no builders are created after parsing buildspecs
        """

        console.rule("[bold red]Parsing Buildspecs")
        self.builders = []

        self.invalid_buildspecs = []
        # store list of valid buildspecs that pass after calling BuildspecParser and used only for printing purpose
        valid_buildspecs = []

        # stores a list of buildspecs that are filtered out
        filtered_buildspecs = []

        bc = BuildtestCompilers(configuration=self.configuration)

        for buildspec in self.detected_buildspecs:
            try:
                # Read in Buildspec file here, loading each will validate the buildspec file
                bp = BuildspecParser(
                    buildspec=buildspec, buildexecutor=self.buildexecutor
                )
            except (
                InvalidBuildspec,
                InvalidBuildspecSchemaType,
                ValidationError,
            ) as err:
                self.invalid_buildspecs.append(buildspec)
                logger.error(err)
                continue

            valid_buildspecs.append(buildspec)

            builder = Builder(
                bp=bp,
                buildtest_compilers=bc,
                buildexecutor=self.buildexecutor,
                filters=self.filter_buildspecs,
                testdir=self.testdir,
                rebuild=self.rebuild,
                configuration=self.configuration,
                numprocs=self.numprocs,
                numnodes=self.numnodes,
                executor_type=self.executor_type,
                exclude_tags=self.exclude_tags,
                strict=self.strict,
                display=self.display,
            )

            if not builder.get_builders():
                filtered_buildspecs.append(buildspec)
                continue

            self.builders += builder.get_builders()

        console.print(f"[green]Valid Buildspecs: {len(valid_buildspecs)}")
        console.print(f"[red]Invalid Buildspecs: {len(self.invalid_buildspecs)}")

        for buildspec in valid_buildspecs:
            console.print(f"[green]{buildspec}: VALID")

        # print any skipped buildspecs if they failed to validate during build stage
        if self.invalid_buildspecs:
            for buildspec in self.invalid_buildspecs:
                console.print(f"[red]{buildspec}: INVALID")

        if filtered_buildspecs:
            table = Table(
                "buildspecs",
                title="Buildspecs Filtered out",
                header_style="blue",
                row_styles=["red"],
            )

            for test in filtered_buildspecs:
                table.add_row(test)
            console.print(table)

        # if no builders found we return from this method
        if not self.builders:
            console.print(
                "[red]\nbuildtest is unable to create any tests because there are no valid buildspecs. "
            )

            print(f"\nPlease see logfile: {BUILDTEST_LOGFILE}")
            sys.exit(1)

        console.print("Total builder objects created:", len(self.builders))

        script_builders = []
        spack_builder = []
        batch_builders = []

        for builder in self.builders:
            if isinstance(builder, ScriptBuilder):
                script_builders.append(builder)

            if isinstance(builder, SpackBuilder):
                spack_builder.append(builder)

            if not builder.is_local_executor():
                batch_builders.append(builder)

        self.print_builders(spack_builder, script_builders, batch_builders)

    def build_phase(self):
        """This method will build all tests by invoking class method ``build`` for
        each builder that generates testscript in the test directory. If no builders are
        present upon building test we raise exception and terminate immediately

        Raises:
            BuildTestError: If no builders are present in build phase
        """

        invalid_builders = []
        console.rule("[bold red]Building Test")

        valid_builders = []

        for builder in self.builders:
            try:
                builder.build(
                    modules=self.modules,
                    modulepurge=self.modulepurge,
                    unload_modules=self.unload_modules,
                )
            except BuildTestError as err:
                console.print(f"[red]{err}")
                invalid_builders.append(builder)
                logger.error(err)
                continue

            valid_builders.append(builder)

            # set retry limit for each builder
            builder.retry(self.retry)

        # remove builders if any invalid builders detected in build phase
        if invalid_builders:
            for test in invalid_builders:
                self.builders.remove(test)

        if not self.builders:
            raise BuildTestError(
                f"Unable to create any test during build phase. Please check {BUILDTEST_LOGFILE} for more details"
            )

    def run_phase(self):
        """This method will run all builders with the appropriate executor.
        The :class:`buildtest.executors.setup.BuildExecutor` class is responsible for orchestrating builder execution to the
        appropriate executor class. The BuildExecutor contains a list of executors picked up from buildtest configuration.
        For tests running locally, we get the test metadata and count PASS/FAIL test
        state which is printed at end in Test Summary. For tests that need batch submission
        via scheduler, the first stage of run will dispatch job, and state will be
        unknown. After dispatching all jobs, we will poll jobs until they are complete.
        The poll section is skipped if all tests are run locally. In poll section we
        regenerate table with all valid builders and updated test state and returncode
        and recalculate total pass/fail tests. Any test that failed to run or be
        dispatched will be skipped during run stage and they will not be recorded in the test report

        Returns:
            A list of valid builders after running tests
        """

        console.rule("[bold red]Running Tests")

        self.buildexecutor.run(self.builders)

        builders = self.buildexecutor.get_validbuilders()
        ########## TEST SUMMARY ####################
        if not builders:
            sys.exit("Unable to run any tests")

        self.print_test_summary(builders)

        return builders

    def build_success(self):
        """Returns status of build whether it was successful or not. The return value is a boolean where ``True``
        indicates build was successful and ``False`` indicates build failed."""
        return self.success

    def print_test_summary(self, builders):
        """Print a summary of total pass and fail test with percentage breakdown.

        Args:
            builders (list): List of builders that ran to completion
        """

        table = Table(title="Test Summary", show_lines=True, header_style="blue")
        table.add_column("builder", overflow="fold")
        table.add_column("executor", overflow="fold")
        table.add_column("status", overflow="fold")
        table.add_column("returncode", overflow="fold")
        table.add_column("runtime", overflow="fold")

        passed_tests = 0
        failed_tests = 0
        total_tests = 0
        for builder in builders:
            if builder.metadata["result"]["state"] == "PASS":
                passed_tests += 1
                color_row = "green"
            else:
                failed_tests += 1
                color_row = "red"

            table.add_row(
                f"[{color_row}]{builder}",
                f"[{color_row}]{builder.executor}",
                f"[{color_row}]{builder.metadata['result']['state']}",
                f"[{color_row}]{builder.metadata['result']['returncode']}",
                f"[{color_row}]{format(builder.metadata['result']['runtime'],'.3f')}",
            )

            total_tests += 1

        console.print(table)
        print("\n\n")

        pass_rate = passed_tests * 100 / total_tests
        pass_rate = format(pass_rate, ".3f")
        fail_rate = failed_tests * 100 / total_tests
        fail_rate = format(fail_rate, ".3f")

        console.print(
            f"[green]Passed Tests: {passed_tests}/{total_tests} Percentage: {pass_rate}%"
        )
        console.print(
            f"[red]Failed Tests: {failed_tests}/{total_tests} Percentage: {fail_rate}%"
        )
        print("\n")

        self.test_summary = {
            "total": str(total_tests),
            "pass": str(passed_tests),
            "fail": str(failed_tests),
            "pass_rate": pass_rate,
            "fail_rate": fail_rate,
        }

    def _update_build_history(self, builders):
        """Write a build history file that is stored in ``$BUILDTEST_ROOT/var/.history`` directory summarizing output of build. The history
        file is a json file named `build.json` which contains a copy of the build log for troubleshooting. buildtest will create a sub-directory
        that is incremented such as 0, 1, 2 in **$BUILDTEST_ROOT/var/.history** which is used to differentiate builds.

        Shown below is content of the top-level directory for the history directory. There is one subdirectory for each build ID starting with 0

        .. code-block:: console

            bash-3.2$ ls -l $BUILDTEST_ROOT/var/.history
            total 0
            drwxr-xr-x  4 siddiq90  92503  128 Sep  8 13:50 0
            drwxr-xr-x  4 siddiq90  92503  128 Sep  8 13:50 1

        For every build ID we have a ``build.json`` and log file for each build.

        .. code-block:: console

            bash-3.2$ ls $BUILDTEST_ROOT/var/.history/{0,1}
            /Users/siddiq90/Documents/GitHubDesktop/buildtest/var/.history/0:
            build.json             buildtest_y3gh46j_.log

            /Users/siddiq90/Documents/GitHubDesktop/buildtest/var/.history/1:
            build.json             buildtest_a1rjdy59.log
        """

        create_dir(BUILD_HISTORY_DIR)
        num_files = len(os.listdir(BUILD_HISTORY_DIR))
        # create a sub-directory in $BUILDTEST_ROOT/var/.history/ that is incremented for every build starting with 0, 1, 2, ...
        self.build_history_dir = os.path.join(BUILD_HISTORY_DIR, str(num_files))

        create_dir(self.build_history_dir)
        build_history_file = os.path.join(self.build_history_dir, "build.json")

        # copy the log file.
        shutil.copyfile(BUILDTEST_LOGFILE, self.logfile.name)
        shutil.copyfile(
            BUILDTEST_LOGFILE,
            os.path.join(self.build_history_dir, os.path.basename(self.logfile.name)),
        )

        if self.verbose:
            console.print(
                f"Creating build history directory: {BUILD_HISTORY_DIR}",
                style="bold blue",
            )
            console.print(
                f"Creating build history file: {build_history_file}", style="bold blue"
            )
            console.print(
                "Copying log file to build history directory", style="bold blue"
            )

        history_data = {
            "command": " ".join(sys.argv),
            "user": getpass.getuser(),
            "hostname": platform.node(),
            "platform": platform.system(),
            "date": datetime.now().strftime("%Y/%m/%d %X"),
            "buildtest": shutil.which("buildtest"),
            "python": os.getenv("BUILDTEST_PYTHON"),
            "python_version": platform.python_version(),
            "testdir": self.testdir,
            "configuration": self.configuration.file,
            "system": self.configuration.name(),
            "logpath": os.path.join(
                self.build_history_dir, os.path.basename(self.logfile.name)
            ),
            "invalid_buildspecs": self.invalid_buildspecs,
            "buildspecs": {
                "detected": self.discovered_bp["detected"],
                "included": self.discovered_bp["included"],
                "excluded": self.discovered_bp["excluded"],
            },
            "test_summary": {
                "pass": self.test_summary["pass"],
                "fail": self.test_summary["fail"],
                "total": self.test_summary["total"],
                "pass_rate": self.test_summary["pass_rate"],
                "fail_rate": self.test_summary["fail_rate"],
            },
        }

        history_data["builders"] = {}
        for builder in builders:
            uid = str(builder.metadata["full_id"])
            history_data["builders"][uid] = {}
            history_data["builders"][uid]["name"] = builder.name
            history_data["builders"][uid]["buildspec"] = builder.buildspec
            history_data["builders"][uid]["tags"] = builder.metadata["tags"]
            history_data["builders"][uid]["executors"] = builder.metadata["executor"]
            history_data["builders"][uid]["state"] = builder.metadata["result"]["state"]
            history_data["builders"][uid]["returncode"] = builder.metadata["result"][
                "returncode"
            ]
            history_data["builders"][uid]["runtime"] = builder.metadata["result"][
                "runtime"
            ]
            history_data["builders"][uid]["testpath"] = builder.metadata["testpath"]
            history_data["builders"][uid]["errfile"] = builder.build_script
            history_data["builders"][uid]["outfile"] = builder.metadata["outfile"]
            history_data["builders"][uid]["errfile"] = builder.metadata["errfile"]

        with open(build_history_file, "w") as fd:
            fd.write(json.dumps(history_data, indent=2))

    def get_build_history_dir(self):
        """Return root of build history directory"""
        return self.build_history_dir

    def print_builders_by_type(self, builders, builder_type):
        """This method will print the builders in table format. The builders are printed by their
         builder type

        Args:
            builders (list): A list of builder objects that were run that need to be printed
            builder_type (str): The builder type corresponding to the list of ``builders``. This type corresponds to the ``type`` field in the test
        """
        table = Table(
            Column(header="builder", style="blue", overflow="fold"),
            Column(header="type", style="cyan1", overflow="fold"),
            Column(header="executor", style="green", overflow="fold"),
            Column(header="compiler", style="red", overflow="fold"),
            Column(header="nodes", style="orange3", overflow="fold"),
            Column(header="procs", style="orange3", overflow="fold"),
            Column(header="description", style="magenta", overflow="fold"),
            Column(header="buildspecs", style="yellow", overflow="fold"),
            title=f"Builders by type={builder_type}",
            show_lines=True,
            header_style="blue",
        )

        for builder in builders:
            description = builder.recipe.get("description") or ""
            # table entries must be rendered by rich and for purpose we need everything to be converted to string.
            table.add_row(
                f"{builder}",
                f"{builder.recipe['type']}",
                f"{builder.executor}",
                f"{builder.compiler}",
                f"{builder.numnodes}",
                f"{builder.numprocs}",
                f"{description}",
                f"{builder.buildspec}",
            )

        if table.row_count:
            console.print(table)

    def print_batch_builders(self, builders):
        """This method will print the builders that were run in batch mode. The builders will be displayed in table format along with
        builders by numnodes and numprocs."""

        batch_builders_table = Table(
            title="Batch Job Builders", show_lines=True, header_style="blue"
        )
        batch_builders_table.add_column("builder", overflow="fold", style="blue")
        batch_builders_table.add_column("executor", overflow="fold", style="green")
        batch_builders_table.add_column("buildspecs", overflow="fold", style="yellow")

        for builder in builders:
            batch_builders_table.add_row(
                f"{builder}", f"{builder.executor}", f"{builder.buildspec}"
            )

        if batch_builders_table.row_count:
            console.print(batch_builders_table)

        if self.numprocs:
            batch_builders_numprocs_table = Table(
                title="Batch Job Builders by Processors",
                show_lines=True,
                header_style="blue",
            )
            batch_builders_numprocs_table.add_column(
                "builder", overflow="fold", style="blue"
            )
            batch_builders_numprocs_table.add_column(
                "type", overflow="fold", style="cyan1"
            )
            batch_builders_numprocs_table.add_column(
                "executor", overflow="fold", style="green"
            )
            batch_builders_numprocs_table.add_column(
                "procs", overflow="fold", style="orange3"
            )
            batch_builders_numprocs_table.add_column(
                "buildspecs", overflow="fold", style="yellow"
            )

            for builder in builders:
                # skip builders that dont have attribute builder.numprocs which is set if buildtest build --procs is specified
                if not builder.numprocs:
                    continue

                batch_builders_numprocs_table.add_row(
                    f"{builder}",
                    f"{builder.recipe['type']}",
                    f"{builder.executor}",
                    f"{builder.numprocs}",
                    f"{builder.buildspec}",
                )

            console.print(batch_builders_numprocs_table)

        if self.numnodes:
            batch_builders_numnodes_table = Table(
                title="Batch Job Builders by Nodes",
                show_lines=True,
                header_style="blue",
            )
            batch_builders_numnodes_table.add_column(
                "builder", overflow="fold", style="blue"
            )
            batch_builders_numnodes_table.add_column(
                "type", overflow="fold", style="cyan1"
            )
            batch_builders_numnodes_table.add_column(
                "executor", overflow="fold", style="green"
            )
            batch_builders_numnodes_table.add_column(
                "nodes", overflow="fold", style="orange3"
            )
            batch_builders_numnodes_table.add_column(
                "buildspecs", overflow="fold", style="yellow"
            )

            for builder in builders:
                # skip builders that dont have attribute builder.numprocs which is set if buildtest build --procs is specified
                if not builder.numnodes:
                    continue

                batch_builders_numnodes_table.add_row(
                    f"{builder}",
                    f"{builder.recipe['type']}",
                    f"{builder.executor}",
                    f"{builder.numnodes}",
                    f"{builder.buildspec}",
                )

            console.print(batch_builders_numnodes_table)

    def print_builders(self, spack_builder, script_builder, batch_builder):
        """Print detected builders during build phase"""

        self.print_builders_by_type(script_builder, builder_type="script")
        self.print_builders_by_type(spack_builder, builder_type="spack")
        self.print_batch_builders(batch_builder)


def update_report(valid_builders, report_file, verbose=None):
    """This method will update BUILD_REPORT after every test run performed
    by ``buildtest build``. If BUILD_REPORT is not created, we will create
    file and update json file by extracting contents from builder metadata

    Args:
        valid_builders (list): List of valid builders that ran to completion
        report_file (str): Specify location to report file.
    """

    create_dir(os.path.dirname(report_file))

    report = {}

    # if file exists, read json file
    if is_file(report_file):
        report = load_json(report_file)

        if verbose:
            console.print(f"Loading report file: {report_file}", style="bold blue")

    if verbose:
        console.print(
            "Attempting to upload test results to report file", style="bold blue"
        )

    for builder in valid_builders:
        buildspec = builder.buildspec
        name = builder.name
        entry = {}

        report[buildspec] = report.get(buildspec) or {}

        report[buildspec][name] = report[buildspec].get(name) or []

        # query over attributes found in builder.metadata, we only assign
        # keys that we care about for reporting
        for item in [
            "id",
            "full_id",
            "description",
            "summary",
            "schemafile",
            "executor",
            "compiler",
            "hostname",
            "user",
            "testroot",
            "testpath",
            "stagedir",
            "command",
            "outfile",
            "errfile",
            "buildenv",
            "buildspec_content",
            "test_content",
            "buildscript_content",
            "logpath",
            "metrics",
            "check",
        ]:
            entry[item] = builder.metadata[item]

        entry["tags"] = ""
        # convert tags to string if defined in buildspec
        if builder.metadata["tags"]:
            if isinstance(builder.metadata["tags"], list):
                entry["tags"] = " ".join(builder.metadata["tags"])
            else:
                entry["tags"] = builder.metadata["tags"]

        # query over result attributes, we only assign some keys of interest
        for item in ["starttime", "endtime", "runtime", "state", "returncode"]:
            entry[item] = str(builder.metadata["result"][item])

        entry["output"] = builder.metadata["output"]
        entry["error"] = builder.metadata["error"]

        entry["job"] = builder.metadata["job"]
        entry["build_script"] = builder.build_script
        report[buildspec][name].append(entry)

    with open(report_file, "w") as fd:
        json.dump(report, fd, indent=2)

    logger.debug(f"Updating report file: {report_file}")
    console.print(
        f"Adding {len(valid_builders)} test results to report file: {report_file}"
    )
    #  BUILDTEST_REPORTS file keeps track of all report files which
    #  contains a single line that denotes path to report file. This file only contains unique report files

    content = []
    if is_file(BUILDTEST_REPORTS):
        content = load_json(BUILDTEST_REPORTS)

    if report_file not in content:
        content.append(report_file)

    with open(BUILDTEST_REPORTS, "w") as fd:
        json.dump(content, fd, indent=2)
