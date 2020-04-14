"""
This module contains all the methods related to "buildtest build" which is used
for building test scripts from test configuration.
"""

import logging
import os
import re
import sys

from buildtest.defaults import TESTCONFIG_ROOT, BUILDTEST_CONFIG_FILE

from buildtest.buildsystem.base import BuildspecParser
from buildtest.config import load_configuration, check_configuration
from buildtest.executors.base import BuildExecutor
from buildtest.utils.file import walk_tree, resolve_path, is_dir, is_file

logger = logging.getLogger(__name__)


def discover_buildspecs(buildspec):
    """Given a buildspec file specified by the user with ``buildtest build --buildspec``,
       discover one or more files and return a list for buildtest to parse.
       Examples of intended functionality are documented here. For all of
       the below, test config root refers to $HOME/.buildtest/site
 
       # A relative path to a file in the PWD (outside of test config root, returns single)
       buildtest build --buildspec relative-folder/hello.sh.yml

       # A relative path to a file in build test root (returns single)
       buildtest build --buildspec github.com/HPC-buildtest/tutorials/hello-world/hello.sh.yml

       # relative directory path (returns multiple)
       buildtest build --buildspec hello-world

       # relative directory path in build test root (returns multiple)
       buildtest build --buildspec github.com/HPC-buildtest/tutorials/hello-world/
    """

    buildspecs = []

    # If no config file provided, assume discovering across buildtest/site
    if not buildspec:
        buildspec = TESTCONFIG_ROOT

    # First try, the path is an absolute path to file or folder
    # Second try, the path can be relative to the TESTCONFIG_ROOT
    elif not os.path.exists(buildspec):
        buildspec = os.path.join(TESTCONFIG_ROOT, buildspec)

    # Now handle path based on being a directory or file path
    if os.path.isdir(buildspec):
        logger.debug(
            f"Buildspec File: {buildspec} is a directory so traversing directory tree to find all Buildspec files with .yml extension"
        )
        buildspecs = walk_tree(buildspec, ".yml")
    elif os.path.isfile(buildspec):
        if not re.search("[.](yaml|yml)$", buildspec):
            msg = f"{buildspec} does not end in file extension .yaml or .yml"
            logger.error(msg)
            sys.exit(msg)

        buildspecs = [buildspec]
        logger.debug(f"Config File: {buildspec} is a file")
    else:
        msg = (
            "Please provide an absolute or relative path to a directory file from your present working directory or %s"
            % TESTCONFIG_ROOT
        )
        logger.error(msg)
        sys.exit(msg)

    # If we don't have any files discovered
    if not buildspecs:
        msg = "No Buildspec files found as %s." % buildspecs
        logger.error(msg)
        sys.exit(msg)

    # return all buildspec by resolving path, this gets the real canonical path and address shell expansion and user expansion
    buildspecs = [resolve_path(file) for file in buildspecs]

    logger.info(f"Found the following config files: {buildspecs}")
    return buildspecs


def include_file(file_path, white_list_patterns):
    """Check if file is included based on OR regular expression. If no white_list_patterns
       provided method will return ``True``. Otherwise it will return the list of files that don't
       match the regular expression

       Parameters:

       :param file_path: file path to run regular expression upon
       :type file_path: str, required
       :param white_list_patterns: the exclude list provided on command line option
       :type white_list_patterns: list, required
       :return: Returns True or a list of files that don't match regular expression
       :rtype: bool or str
    """

    if not white_list_patterns:
        logger.debug("No white list patterns provided, returning True")
        return True

    logger.debug(f"white list pattern before resolving paths: {white_list_patterns}")

    white_list_patterns = [resolve_path(path) for path in white_list_patterns]

    logger.debug(f"white list pattern after resolving paths: {white_list_patterns}")

    regexp = "(%s)" % "|".join(white_list_patterns)
    logger.debug(f"Applying Regular Expression Search: {regexp} to file: {file_path}")

    return not re.search(regexp, file_path)


def func_build_subcmd(args):
    """Entry point for ``buildtest build`` sub-command. This method will discover
       buildspecs in method ``discover_buildspecs``. If there are any exclusion list
       this will be checked, once buildtest knows all buildspecs to process it will
       begin validation in ``ValidateBuildSpec`` and finally kick of an execution
       using one of the executors. A report of all builds, along with test summary
       will be displayed to screen.

       Parameters:

       :param args: arguments passed from command line
       :type args: dict, required

       :rtype: None
    """

    # if buildtest settings specified on CLI, it would be in args.settings otherwise set
    # to default configuration (BUILDTEST_CONFIG_FILE)
    settings_file = args.settings or BUILDTEST_CONFIG_FILE

    if args.settings:
        logger.debug(
            "Detected --settings from command line so override default settings file."
        )

    logger.debug(f"Detected the following buildtest settings file: {settings_file}")

    # load the configuration file
    config_opts = load_configuration(settings_file)

    check_configuration(settings_file)

    # Discover list of one or more buildspec files based on path provided
    buildspecs = discover_buildspecs(args.buildspec)

    # if no files discovered let's stop now
    if not buildspecs:
        msg = "There are no config files to process."
        sys.exit(msg)

    logger.debug(
        f"Based on input argument: --buildspec {args.buildspec} buildtest discovered the following Buildspecs: {buildspecs}"
    )

    if args.exclude:
        logger.debug(f"The exclude config pattern are the following: -e {args.exclude}")
        buildspecs = [
            config for config in buildspecs if include_file(config, args.exclude)
        ]
        logger.debug(f"Buildspec list after applying exclusion: {buildspecs}")

        # if no files remain after exclusion let's stop now.
        if not buildspecs:
            msg = "There are no Buildspec files to process."
            sys.exit(msg)

    print("\n {:^45} \n".format("Discovered Buildspecs "))
    [print(buildspec) for buildspec in buildspecs]
    print("\n\n")

    # Keep track of total metrics
    total_tests = 0
    failed_tests = 0
    passed_tests = 0

    # Load BuildExecutors
    executor = BuildExecutor(config_opts, default=args.executor)
    print(
        "{:<30} {:<30} {:<30} {:<30}".format(
            "Buildspec Name", "SubTest", "Status", "Buildspec Path"
        )
    )
    print("{:_<120}".format(""))
    # Each configuration file can have multiple tests
    for buildspec in buildspecs:

        # Read in buildspec file here, loading each will validate the buildspec file
        bp = BuildspecParser(buildspec)

        # And builders parsed through for each
        for builder in bp.get_builders(testdir=args.testdir):

            # Keep track of total number of tests run
            total_tests += 1
            if not args.dry:
                result = executor.run(builder)

                # Update results
                if result["RETURN_CODE"] == 0:
                    passed_tests += 1
                else:
                    failed_tests += 1
            else:
                result = executor.dry_run(builder)

    if not args.dry:
        print("\n\n{:=<60}".format(""))
        print("{:^60}".format("Test summary"))
        print("{:=<60}".format(""))
        print(f"Executed {total_tests} tests")

        pass_rate = passed_tests * 100 / total_tests
        fail_rate = failed_tests * 100 / total_tests

        print(
            f"Passed Tests: {passed_tests}/{total_tests} Percentage: {pass_rate:.3f}%"
        )

        print(
            f"Failed Tests: {failed_tests}/{total_tests} Percentage: {fail_rate:.3f}%"
        )
        print
        print
