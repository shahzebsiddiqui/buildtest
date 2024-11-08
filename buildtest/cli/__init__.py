"""
buildtest cli: include functions to build, get test configurations, and
interact with a global configuration for buildtest.
"""

import argparse
import datetime
import sys

from pygments.styles import STYLE_MAP
from rich.color import Color, ColorParseError

from buildtest import BUILDTEST_COPYRIGHT, BUILDTEST_VERSION
from buildtest.defaults import console


def build_filters_format(val):
    """This method is used as validate argument type for ``buildtest build --filter``.
    This method returns a dict of key, value pairs where input is in the format
    **key1=val1,val2;key2=val3**. The semicolon is used to separate the keys and multiple values
    can be specified via comma

    Args:
       val (str): Input string in ``key1=value1,val2;key2=value3`` format that is processed into a dictionary type

    Returns:
        dict: A dict mapping of key=value pairs
    """

    kv_dict = {}

    if ";" in val:
        entries = val.split(";")
        for entry in entries:
            if "=" not in entry:
                raise argparse.ArgumentTypeError("Must specify k=v")

            key, values = entry.split("=")[0], entry.split("=")[1]
            value_list = values.split(",")
            kv_dict[key] = value_list

        return kv_dict

    if "=" not in val:
        raise argparse.ArgumentTypeError("Must specify in key=value format")

    key, values = val.split("=")[0], val.split("=")[1]
    value_list = values.split(",")
    kv_dict[key] = value_list

    return kv_dict


def handle_kv_string(val):
    """This method is used as type field in --filter argument in ``buildtest buildspec find``.
    This method returns a dict of key,value pair where input is in format
    key1=val1,key2=val2,key3=val3

    Args:
       val (str): Input string in ``key1=value1,key2=value2`` format that is processed into a dictionary type

    Returns:
        dict: A dict mapping of key=value pairs
    """

    kv_dict = {}

    if "," in val:
        args = val.split(",")
        for kv in args:
            if "=" not in kv:
                raise argparse.ArgumentTypeError("Must specify k=v")

            key, value = kv.split("=")[0], kv.split("=")[1]
            kv_dict[key] = value

        return kv_dict

    if "=" not in val:
        raise argparse.ArgumentTypeError("Must specify in key=value format")

    key, value = val.split("=")[0], val.split("=")[1]
    kv_dict[key] = value

    return kv_dict


def positive_number(value):
    """Checks if input is positive number and returns value as an int type.

    Args:
        value (str or int): Specify an input number

    Returns:
        int: Return value as int type

    Raises:
        argparse.ArgumentTypeError will be raised if input is not positive number or input is not str or int type

    >>> positive_number("1")
    1

    >>> positive_number(2)
    2
    """

    if not isinstance(value, (str, int)):
        raise argparse.ArgumentTypeError(
            f"Input must be an integer or string type, you have specified '{value}' which is of type {type(value)}"
        )

    try:
        int_val = int(value)
    except ValueError:
        console.print(f"[red]Unable to convert {value} to int ")
        console.print_exception()
        raise ValueError

    if int_val <= 0:
        raise argparse.ArgumentTypeError(
            f"Input: {value} converted to int: {int_val} must be a positive number"
        )
    return int_val


def supported_color(input_color):
    """Checks if input is a supported color and returns value as an Color type.

    Args:
        input_color (str): Specify an input color

    Returns:
        str: Return value as rich.color.Color type

    Raises:
        argparse.ArgumentTypeError will be raised if input is not a supported color input or is not str type

    >>> supported_color("red")
    red
    """

    if not isinstance(input_color, (str)):
        raise argparse.ArgumentTypeError(
            f"Input must be a string type, you have specified '{input_color}' which is of type {type(input_color)}"
        )
    try:
        color_val = Color.parse(input_color)
    except ColorParseError:
        console.print(f"[red]Unable to convert {input_color} to a Color ")
        console.print_exception()
        return
    return color_val


def valid_time(value):
    """Checks if input is valid time and returns value as a str type.

    Args:
        value (str): Specify an input date in yyyy-mm-dd format

    Returns:
        int: Return value as str type in correct format

    Raises:
        argparse.ArgumentTypeError will be raised if input is not str or input is not in desired format

    >>> valid_time("2022-01-01")
    "2022-01-01"

    >>> valid_time("2022-01-13")
    "2022-01-13"
    """

    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(
            f"Input must be string type, you have specified '{value}' which is of type {type(value)}"
        )

    fmt = "%Y-%m-%d"

    try:
        dt_object = datetime.datetime.strptime(value, fmt)
    except ValueError:
        console.print(f"[red]Unable to convert {value} to correct date format")
        console.print_exception()
        raise ValueError

    return dt_object


def get_parser():
    """This method is used to simply return the parser for sphinx-argparse."""
    bp = BuildTestParser()
    return bp.parser


class BuildTestParser:
    """This class implements the buildtest command line interface. This class
    implements the following methods:

    - :func:`get_parser`: This method builds the command line interface for buildtest
    - :func:`parse`: This method parses arguments passed to buildtest command line interface
    """

    _github = "https://github.com/buildtesters/buildtest"
    _docs = "https://buildtest.readthedocs.io/en/latest/index.html"
    _slack = "http://hpcbuildtest.slack.com/"
    _issues = "https://github.com/buildtesters/buildtest/issues"
    _progname = "buildtest"
    _description = (
        "buildtest is a HPC testing framework for building and running tests."
    )
    epilog_str = f"""
    References

    GitHub:                  {_github}
    Documentation:           {_docs}
    Slack:                   {_slack}

    Please report issues at {_issues}

    {BUILDTEST_COPYRIGHT}
    """

    _buildtest_show_commands = [
        "bd",
        "build",
        "bc",
        "buildspec",
        "cdash",
        "cg",
        "config",
        "hy",
        "history",
        "it",
        "inspect",
        "path",
        "rt",
        "report",
        "style",
        "stylecheck",
        "test",
        "unittests",
    ]

    def __init__(self):
        self.parent_parser = self.get_parent_parser()

        self.subcommands = {
            "build": {"help": "Build and Run test", "aliases": ["bd"]},
            "buildspec": {"help": "Buildspec Interface", "aliases": ["bc"]},
            "config": {"help": "Query buildtest configuration", "aliases": ["cg"]},
            "report": {
                "help": "Query test report",
                "aliases": ["rt"],
                "parents": [
                    self.parent_parser["pager"],
                    self.parent_parser["row-count"],
                    self.parent_parser["terse"],
                    self.parent_parser["no-header"],
                    self.parent_parser["count"],
                ],
            },
            "inspect": {"help": "Inspect a test", "aliases": ["it"]},
            "path": {"help": "Show path attributes for a given test", "aliases": ["p"]},
            "history": {"help": "Query build history", "aliases": ["hy"]},
            "cdash": {"help": "Upload test to CDASH server"},
            "cd": {"help": "Change directory to root of test given a test name"},
            "clean": {
                "help": "Remove all generate files from buildtest including test directory, log files, report file, buildspec cache, history files"
            },
            "debugreport": {
                "help": "Display system information and additional information for debugging purposes.",
                "aliases": ["debug"],
            },
            "stats": {"help": "Show test statistics for given test"},
            "info": {"help": " Show details regarding current buildtest setup"},
            "show": {"help": "buildtest command guide"},
            "commands": {"help": "List all buildtest commands", "aliases": ["cmds"]},
        }

        self.parser = argparse.ArgumentParser(
            prog=self._progname,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=self._description,
            usage="%(prog)s [options] [COMMANDS]",
            epilog=self.epilog_str,
        )

        self.subparsers = self.parser.add_subparsers(
            title="COMMANDS", dest="subcommands", metavar=""
        )

        self._build_options()

        self.hidden_subcommands = {
            "docs": {},
            "tutorial-examples": {},
            "unittests": {"aliases": ["test"]},
            "stylecheck": {"aliases": ["style"]},
        }

        # Variables needed to show all sub commands and their help message
        show_all_help = any(arg in ["-H", "--help-all"] for arg in sys.argv)
        if show_all_help:
            self.hidden_subcommands = {
                "tutorial-examples": {
                    "help": "Generate documentation examples for Buildtest Tutorial"
                },
                "docs": {"help": "Open buildtest docs in browser"},
                "unittests": {"help": "Run buildtest unit tests", "aliases": ["test"]},
                "stylecheck": {
                    "help": "Run buildtest style checks",
                    "aliases": ["style"],
                },
            }

        self.buildtest_subcommands = list(self.subcommands.keys()) + list(
            self.hidden_subcommands.keys()
        )

        self._build_subparsers()

        self.build_menu()
        self.buildspec_menu()
        self.config_menu()
        self.report_menu()
        self.inspect_menu()
        self.path_menu()
        self.history_menu()
        self.cdash_menu()
        self.unittest_menu()
        self.stylecheck_menu()
        self.tutorial_menu()
        self.misc_menu()

    def parse(self):
        """This method parses arguments passed to buildtest command line interface."""
        return self.parser.parse_args()

    def get_subparsers(self):
        return self.subparsers

    def retrieve_main_options(self):
        """This method retrieves all options for buildtest command line interface. This is invoked by ``buildtest --listopts`` command and useful when user
        wants to see all options."""
        options_list = []

        # Iterate over the actions of the parser to extract short and long options
        for action in self.parser._actions:
            option_strings = action.option_strings
            options_list.extend(option_strings)

        return sorted(options_list)

    def _build_subparsers(self):
        """This method builds subparsers for buildtest command line interface."""

        for name, kwargs in self.subcommands.items():
            self.subparsers.add_parser(name, **kwargs)

        for name, kwargs in self.hidden_subcommands.items():
            self.subparsers.add_parser(name, **kwargs)

    def _build_options(self):
        """This method builds the main options for buildtest command line interface."""

        self.buildtest_options = [
            (
                ["-V", "--version"],
                {
                    "action": "version",
                    "version": f"%(prog)s version {BUILDTEST_VERSION}",
                },
            ),
            (["-c", "--configfile"], {"help": "Specify Path to Configuration File"}),
            (
                ["-d", "--debug"],
                {"action": "store_true", "help": "Stream log messages to stdout"},
            ),
            (
                ["-l", "--loglevel"],
                {
                    "help": "Filter log messages based on logging level",
                    "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                    "default": "DEBUG",
                },
            ),
            (
                ["--editor"],
                {
                    "help": "Select your preferred editor when opening files.",
                    "choices": ["vi", "vim", "emacs", "nano"],
                },
            ),
            (
                ["--view-log"],
                {"action": "store_true", "help": "Show content of last log"},
            ),
            (
                ["--logpath"],
                {"action": "store_true", "help": "Print full path to last log file"},
            ),
            (
                ["--print-log"],
                {
                    "action": "store_true",
                    "help": "Print content of last log without pagination",
                },
            ),
            (
                ["--color"],
                {
                    "type": supported_color,
                    "metavar": "COLOR",
                    "help": "Print output of table with the selected color.",
                },
            ),
            (
                ["--no-color"],
                {"help": "Disable colored output", "action": "store_true"},
            ),
            (
                ["--helpcolor"],
                {
                    "action": "store_true",
                    "help": "Print available color options in a table format.",
                },
            ),
            (["-r", "--report"], {"help": "Specify path to test report file"}),
            (
                ["-H", "--help-all"],
                {"help": "List all commands and options", "action": "help"},
            ),
            (
                ["--listopts"],
                {"action": "store_true", "help": "List all options for buildtest"},
            ),
            (["--verbose"], {"action": "store_true", "help": "Enable verbose output"}),
        ]

        for args, kwargs in self.buildtest_options:
            self.parser.add_argument(*args, **kwargs)

    def get_subcommands(self):
        """Return a list of buildtest commands. This is useful for ``buildtest commands`` command to show a list of buildtest commands"""
        return list(self.subcommands.keys()) + list(self.hidden_subcommands.keys())

    def get_parent_parser(self):
        parent_parser = {}

        parent_parser["pager"] = argparse.ArgumentParser(add_help=False)
        parent_parser["pager"].add_argument(
            "--pager", action="store_true", help="Enable PAGING when viewing result"
        )

        parent_parser["file"] = argparse.ArgumentParser(add_help=False)
        parent_parser["file"].add_argument(
            "--file", help="Write configuration file to a new file"
        )

        parent_parser["row-count"] = argparse.ArgumentParser(add_help=False)
        parent_parser["row-count"].add_argument(
            "--row-count",
            action="store_true",
            help="Display number of rows from query shown in table",
        )
        parent_parser["terse"] = argparse.ArgumentParser(add_help=False)
        parent_parser["terse"].add_argument(
            "--terse",
            action="store_true",
            help="Print output in machine readable format",
        )
        parent_parser["no-header"] = argparse.ArgumentParser(add_help=False)
        parent_parser["no-header"].add_argument(
            "-n",
            "--no-header",
            action="store_true",
            help="Do not print header columns in terse output (--terse)",
        )
        parent_parser["count"] = argparse.ArgumentParser(add_help=False)
        parent_parser["count"].add_argument(
            "-c",
            "--count",
            type=int,
            help="Retrieve limited number of rows that get printed",
        )
        parent_parser["theme"] = argparse.ArgumentParser(add_help=False)
        parent_parser["theme"].add_argument(
            "--theme",
            metavar="Color Themes",
            help="Specify a color theme, Pygments style to use when displaying output. See https://pygments.org/docs/styles/#getting-a-list-of-available-styles for available themese",
            choices=list(STYLE_MAP.keys()),
        )
        return parent_parser

    def misc_menu(self):
        """Build the command line menu for some miscellaneous commands"""

        subcommands = [
            {
                "name": "cd",
                "help": "Change directory to root of test for last run of test.",
                "arguments": [
                    (
                        ["test"],
                        {
                            "help": "Change directory to root of test for last run of test."
                        },
                    )
                ],
            },
            {
                "name": "clean",
                "help": "Remove all generate files from buildtest including test directory, log files, report file, buildspec cache, history files.",
                "arguments": [
                    (
                        ["-y", "--yes"],
                        {"action": "store_true", "help": "Confirm yes for all prompts"},
                    )
                ],
            },
            {
                "name": "stats",
                "help": "Display statistics for a specific test.",
                "arguments": [(["name"], {"help": "Name of test"})],
            },
            {
                "name": "commands",
                "help": "List all buildtest commands",
                "arguments": [
                    (
                        ["-a", "--with-aliases"],
                        {
                            "action": "store_true",
                            "help": "Return all buildtest commands including command aliases",
                        },
                    )
                ],
            },
            {
                "name": "show",
                "help": "Show help message for a specific command.",
                "arguments": [
                    (
                        ["command"],
                        {
                            "help": "Show help message for command.",
                            "choices": self._buildtest_show_commands,
                        },
                    )
                ],
            },
        ]

        # Create argument parsers for each subcommand
        parsers = {}
        for subcommand in subcommands:
            parser = self.subparsers.choices[subcommand["name"]]
            for args, kwargs in subcommand.get("arguments", []):
                parser.add_argument(*args, **kwargs)
            parsers[subcommand["name"]] = parser

    def stylecheck_menu(self):
        """This method will create command options for ``buildtest stylecheck``"""

        parser = self.subparsers.choices["stylecheck"]

        stylecheck_args = [
            (
                ["--no-black"],
                {"action": "store_true", "help": "Don't run black style check"},
            ),
            (
                ["--no-isort"],
                {"action": "store_true", "help": "Don't run isort style check"},
            ),
            (
                ["--no-pyflakes"],
                {"action": "store_true", "help": "Don't run pyflakes check"},
            ),
            (
                ["-a", "--apply"],
                {"action": "store_true", "help": "Apply style checks to codebase."},
            ),
        ]

        for args, kwargs in stylecheck_args:
            parser.add_argument(*args, **kwargs)

    def tutorial_menu(self):
        parser = self.subparsers.choices["tutorial-examples"]

        tutorial = [
            (
                ["examples"],
                {
                    "help": "Select which tutorial examples to build",
                    "choices": ["aws", "spack"],
                },
            ),
            (
                ["-d", "--dryrun"],
                {
                    "action": "store_true",
                    "help": "Just print commands that will be generated without running them",
                },
            ),
            (
                ["-w", "--write"],
                {
                    "action": "store_true",
                    "help": "Write the content of each command to file",
                },
            ),
            (["--failfast"], {"action": "store_true", "help": "Stop on first failure"}),
        ]

        for args, kwargs in tutorial:
            parser.add_argument(*args, **kwargs)

    def unittest_menu(self):
        """This method builds the command line menu for ``buildtest unittests`` command"""
        parser = self.subparsers.choices["unittests"]

        unittests_args = [
            (
                ["-c", "--coverage"],
                {
                    "action": "store_true",
                    "help": "Enable coverage when running regression test",
                },
            ),
            (["-p", "--pytestopts"], {"type": str, "help": "Specify option to pytest"}),
            (
                ["-s", "--sourcefiles"],
                {
                    "type": str,
                    "help": "Specify path to file or directory when running regression test",
                    "action": "append",
                },
            ),
        ]

        for args, kwargs in unittests_args:
            parser.add_argument(*args, **kwargs)

    def path_menu(self):
        """This method builds the command line menu for ``buildtest path`` command"""

        path = self.subparsers.choices["path"]

        path_options = [
            (
                ["-be", "--buildenv"],
                {"action": "store_true", "help": "Show path to build environment"},
            ),
            (
                ["-t", "--testpath"],
                {"action": "store_true", "help": "Show path to test script"},
            ),
            (
                ["-o", "--outfile"],
                {"action": "store_true", "help": "Show path to output file"},
            ),
            (
                ["-e", "--errfile"],
                {"action": "store_true", "help": "Show path to error file"},
            ),
            (
                ["-b", "--buildscript"],
                {"action": "store_true", "help": "Show path to build script"},
            ),
            (
                ["-s", "--stagedir"],
                {"action": "store_true", "help": "Show path to stage directory"},
            ),
        ]

        path_group = path.add_mutually_exclusive_group()
        for args, kwargs in path_options:
            path_group.add_argument(*args, **kwargs)

        path.add_argument("name", help="Name of test")

    def history_menu(self):
        """This method builds the command line menu for ``buildtest history`` command"""

        history_subcmd = self.subparsers.choices["history"]

        history_subparser = history_subcmd.add_subparsers(
            metavar="", description="Query build history file", dest="history"
        )

        subparser_info = [
            {
                "name": "list",
                "help": "List a summary of all builds",
                "parents": [
                    self.parent_parser["pager"],
                    self.parent_parser["row-count"],
                    self.parent_parser["terse"],
                    self.parent_parser["no-header"],
                ],
                "arguments": [],
            },
            {
                "name": "query",
                "help": "Query information for a particular build",
                "parents": [self.parent_parser["pager"]],
                "arguments": [
                    (["id"], {"type": int, "help": "Select a build ID"}),
                    (
                        ["-l", "--log"],
                        {
                            "action": "store_true",
                            "help": "Display logfile for corresponding build id",
                        },
                    ),
                    (
                        ["-o", "--output"],
                        {
                            "action": "store_true",
                            "help": "View raw output from buildtest build command",
                        },
                    ),
                ],
            },
        ]

        for subparser_info in subparser_info:
            subparser = history_subparser.add_parser(
                subparser_info["name"],
                help=subparser_info["help"],
                parents=subparser_info["parents"],
            )
            for args, kwargs in subparser_info["arguments"]:
                subparser.add_argument(*args, **kwargs)

    def build_menu(self):
        """This method implements command line menu for ``buildtest build`` command."""

        parser_build = self.subparsers.choices["build"]

        groups = [
            (
                "discover",
                "discover",
                "Select buildspec file to run based on file, tag, executor",
            ),
            ("filter", "filter", "Filter tests after selection"),
            ("module", "module", "Module Selection option"),
            ("batch", "batch", "Batch Submission options"),
            ("extra", "extra", "All extra options"),
        ]
        arguments = {
            "discover": [
                (
                    ["-b", "--buildspec"],
                    {
                        "help": "Specify a buildspec (file or directory) to build. A buildspec must end in '.yml' extension.",
                        "action": "append",
                    },
                ),
                (
                    ["-x", "--exclude"],
                    {
                        "action": "append",
                        "help": "Exclude one or more buildspecs (file or directory) from processing. A buildspec must end in '.yml' extension.",
                    },
                ),
                (
                    ["-n", "--name"],
                    {
                        "action": "append",
                        "help": "Specify a name of test to run",
                        "type": str,
                    },
                ),
                (
                    ["-e", "--executor"],
                    {
                        "action": "append",
                        "type": str,
                        "help": "Discover buildspecs by executor name found in buildspec cache",
                    },
                ),
                (
                    ["-xt", "--exclude-tags"],
                    {
                        "action": "append",
                        "type": str,
                        "help": "Exclude tests by one or more tagnames found in buildspec cache",
                    },
                ),
                (
                    ["-t", "--tags"],
                    {
                        "action": "append",
                        "type": str,
                        "help": "Discover buildspecs by tags found in buildspec cache",
                    },
                ),
                (
                    ["--rerun"],
                    {
                        "action": "store_true",
                        "help": "Rerun last successful buildtest build command.",
                    },
                ),
            ],
            "filter": [
                (
                    ["-f", "--filter"],
                    {
                        "type": build_filters_format,
                        "help": "Filter buildspec based on tags, type, or maintainers. Usage:  --filter key1=val1,val2;key2=val3;key3=val4,val5",
                    },
                ),
                (
                    ["--helpfilter"],
                    {
                        "action": "store_true",
                        "help": "Show available filter fields used with --filter option",
                    },
                ),
                (
                    ["-et", "--executor-type"],
                    {
                        "choices": ["local", "batch"],
                        "help": "Filter tests by executor type (local, batch)",
                    },
                ),
            ],
            "module": [
                (
                    ["--module-purge"],
                    {
                        "action": "store_true",
                        "help": "Run 'module purge' before running any test",
                    },
                ),
                (
                    ["-m", "--modules"],
                    {
                        "type": str,
                        "help": "Specify a list of modules to load during test execution, to specify multiple modules each one must be comma separated for instance if you want to load 'gcc' and 'python' module you can do '-m gcc,python'",
                    },
                ),
                (
                    ["-u", "--unload-modules"],
                    {
                        "type": str,
                        "help": "Specify a list of modules to unload during test execution",
                    },
                ),
            ],
            "batch": [
                (
                    ["--account"],
                    {
                        "type": str,
                        "help": "Specify project account used to charge batch jobs (applicable for batch jobs only)",
                    },
                ),
                (
                    ["--maxpendtime"],
                    {
                        "type": positive_number,
                        "help": "Specify Maximum Pending Time (sec) for job before cancelling job. This only applies for batch job submission.",
                    },
                ),
                (
                    ["--pollinterval"],
                    {
                        "type": positive_number,
                        "help": "Specify Poll Interval (sec) for polling batch jobs",
                    },
                ),
                (
                    ["--procs"],
                    {
                        "nargs": "+",
                        "type": positive_number,
                        "help": "Specify number of processes to run tests (only applicable with batch jobs). Multiple values can be specified comma separated.",
                    },
                ),
                (
                    ["--nodes"],
                    {
                        "nargs": "+",
                        "type": positive_number,
                        "help": "Specify number of nodes to run tests (only applicable with batch jobs). Multiple values can be specified comma separated.",
                    },
                ),
            ],
            "extra": [
                (
                    ["--display"],
                    {
                        "action": "append",
                        "type": str,
                        "help": "Display content of output/error or test",
                        "choices": ["output", "test"],
                    },
                ),
                (
                    ["--dry-run"],
                    {
                        "action": "store_true",
                        "help": "Show a list of tests that will potentially be run without actually running them.",
                    },
                ),
                (
                    ["--limit"],
                    {
                        "type": positive_number,
                        "help": "Limit number of tests that can be run.",
                    },
                ),
                (
                    ["--max-jobs"],
                    {
                        "type": positive_number,
                        "help": "Maximum number of jobs that can be run concurrently.",
                    },
                ),
                (
                    ["--profile"],
                    {"help": "Specify a profile to load from configuration file"},
                ),
                (
                    ["--remove-stagedir"],
                    {
                        "action": "store_true",
                        "help": "Remove stage directory after job completion.",
                    },
                ),
                (
                    ["--rebuild"],
                    {
                        "type": positive_number,
                        "help": "Rebuild test X number of times. Must be a positive number between [1-50]",
                    },
                ),
                (
                    ["--retry"],
                    {
                        "type": positive_number,
                        "default": 1,
                        "help": "Retry failed jobs",
                    },
                ),
                (
                    ["--save-profile"],
                    {
                        "help": "Save buildtest command options into a profile and update configuration file"
                    },
                ),
                (
                    ["--strict"],
                    {
                        "action": "store_true",
                        "help": "Enable strict mode for test by setting 'set -eo pipefail' in test script",
                    },
                ),
                (
                    ["--testdir"],
                    {
                        "help": "Specify a custom test directory where to write tests. This overrides configuration file and default location."
                    },
                ),
                (
                    ["--timeout"],
                    {
                        "type": positive_number,
                        "help": "Specify test timeout in number of seconds",
                    },
                ),
                (
                    ["--validate"],
                    {
                        "action": "store_true",
                        "help": "Validate given buildspecs and control behavior of buildtest build to stop execution after parsing the YAML files.",
                    },
                ),
                (
                    ["--write-config-file"],
                    {
                        "type": str,
                        "help": "Specify path to configuration file to write changes when saving profile",
                    },
                ),
            ],
        }

        for group_name, dest_name, desc in groups:
            group = parser_build.add_argument_group(group_name, description=desc)

            # self.argument_group(arguments=arguments, group=group, dest_name=dest_name)

            for args, kwargs in arguments[dest_name]:
                group.add_argument(*args, **kwargs)

    def buildspec_menu(self):
        """This method implements ``buildtest buildspec`` command"""

        parser_buildspec = self.subparsers.choices["buildspec"]

        subparsers_buildspec = parser_buildspec.add_subparsers(
            description="Buildspec Interface subcommands",
            dest="buildspecs_subcommand",
            metavar="",
        )

        buildspec_subcommands = [
            {
                "name": "edit-file",
                "help": "Edit buildspec file based on filename",
                "parents": [],
                "aliases": ["ef"],
                "arguments": [
                    (["file"], {"help": "Edit buildspec file in editor", "nargs": "*"})
                ],
            },
            {
                "name": "edit-test",
                "help": "Edit buildspec file based on test name",
                "parents": [],
                "aliases": ["et"],
                "arguments": [
                    (
                        ["name"],
                        {
                            "help": "Show content of buildspec based on test name",
                            "nargs": "*",
                        },
                    )
                ],
            },
            {
                "name": "find",
                "help": "Query information from buildspecs cache",
                "aliases": ["f"],
                "parents": [
                    self.parent_parser["count"],
                    self.parent_parser["no-header"],
                    self.parent_parser["pager"],
                    self.parent_parser["row-count"],
                    self.parent_parser["terse"],
                ],
                " args": [],
            },
            {
                "name": "maintainers",
                "help": "Query maintainers from buildspecs cache",
                "aliases": ["m"],
                "parents": [
                    self.parent_parser["count"],
                    self.parent_parser["no-header"],
                    self.parent_parser["pager"],
                    self.parent_parser["row-count"],
                    self.parent_parser["terse"],
                ],
                "arguments": [
                    (
                        ["-b", "--breakdown"],
                        {
                            "action": "store_true",
                            "help": "Breakdown of buildspecs by maintainers",
                        },
                    )
                ],
            },
            {
                "name": "show",
                "help": "Show content of buildspec file",
                "parents": [self.parent_parser["theme"]],
                "aliases": ["s"],
                "arguments": [
                    (
                        ["name"],
                        {
                            "help": "Show content of buildspec based on test name",
                            "nargs": "*",
                        },
                    )
                ],
            },
            {
                "name": "show-fail",
                "help": "Show content of buildspec file for all failed tests",
                "parents": [self.parent_parser["theme"]],
                "aliases": ["sf"],
                "arguments": [
                    (
                        ["name"],
                        {
                            "help": "Show content of buildspec based on failed test name",
                            "nargs": "*",
                        },
                    )
                ],
            },
            {
                "name": "summary",
                "help": "Print summary of buildspec cache",
                "parents": [self.parent_parser["pager"]],
                "arguments": [],
                "aliases": ["sm"],
            },
            {
                "name": "validate",
                "help": "Validate buildspecs with JSON Schema",
                "parents": [],
                "aliases": ["val"],
                "arguments": [
                    (
                        ["-b", "--buildspec"],
                        {
                            "type": str,
                            "action": "append",
                            "help": "Specify path to buildspec (file, or directory) to validate",
                        },
                    ),
                    (
                        ["-x", "--exclude"],
                        {
                            "type": str,
                            "action": "append",
                            "help": "Specify path to buildspec to exclude (file or directory) during validation",
                        },
                    ),
                    (
                        ["-e", "--executor"],
                        {
                            "type": str,
                            "action": "append",
                            "help": "Specify buildspecs by executor name to validate",
                        },
                    ),
                    (
                        ["-t", "--tag"],
                        {
                            "type": str,
                            "action": "append",
                            "help": "Specify buildspecs by tag name to validate",
                        },
                    ),
                    (
                        ["-n", "--name"],
                        {
                            "type": str,
                            "action": "append",
                            "help": "Specify buildspecs by name to validate",
                        },
                    ),
                ],
            },
        ]

        subcommand = {}
        # Loop through the list of dictionaries and create subcommands with their parent parsers and arguments
        for cmd_info in buildspec_subcommands:
            name = cmd_info["name"]
            subcommand[name] = subparsers_buildspec.add_parser(
                cmd_info["name"],
                help=cmd_info["help"],
                parents=cmd_info["parents"],
                aliases=cmd_info.get("aliases", []),
            )
            for arg_info in cmd_info.get("arguments", []):
                subcommand[name].add_argument(*arg_info[0], **arg_info[1])

        # build menu for 'buildtest buildspec maintainers' command

        subparsers_maintainers = subcommand["maintainers"].add_subparsers()
        maintainers_find = subparsers_maintainers.add_parser(
            "find", help="Find buildspecs based on maintainer name"
        )
        maintainers_find.add_argument(
            "name", help="Find buildspec based on maintainer name"
        )

        # build menu for 'buildtest buildspec find' command
        self.buildspec_find_menu(subcommand["find"])

    def buildspec_find_menu(self, buildspec_find_parser):
        groups = [
            ("query", "query", "query options to retrieve from buildspec cache"),
            ("filter", "filter", "filter and format options"),
            ("extra", "extra", "All extra options"),
        ]
        arguments = {
            "query": [
                (
                    ["-b", "--buildspec"],
                    {
                        "help": "Get all buildspec files from cache",
                        "action": "store_true",
                    },
                ),
                (
                    ["-e", "--executors"],
                    {
                        "help": "Get all unique executors from buildspecs",
                        "action": "store_true",
                    },
                ),
                (
                    ["--group-by-tags"],
                    {"action": "store_true", "help": "Group tests by tag name"},
                ),
                (
                    ["--group-by-executor"],
                    {"action": "store_true", "help": "Group tests by executor name"},
                ),
                (
                    ["-p", "--paths"],
                    {"action": "store_true", "help": "Print all root buildspec paths"},
                ),
                (
                    ["-t", "--tags"],
                    {"action": "store_true", "help": "List all available tags"},
                ),
            ],
            "filter": [
                (
                    ["--filter"],
                    {
                        "type": handle_kv_string,
                        "help": "Filter buildspec cache with filter fields in format --filter key1=val1,key2=val2",
                    },
                ),
                (
                    ["--format"],
                    {
                        "help": "Format buildspec cache with format fields in format --format field1,field2,..."
                    },
                ),
                (
                    ["--filterfields"],
                    {
                        "action": "store_true",
                        "help": "Print raw filter fields for --filter option for filtering buildspec cache output",
                    },
                ),
                (
                    ["--formatfields"],
                    {
                        "action": "store_true",
                        "help": "Print raw format fields for --format option for formatting buildspec cache output",
                    },
                ),
                (
                    ["--helpfilter"],
                    {
                        "action": "store_true",
                        "help": "Show filter fields for --filter option for filtering buildspec cache output",
                    },
                ),
                (
                    ["--helpformat"],
                    {
                        "action": "store_true",
                        "help": "Show format fields for --format option for formatting buildspec cache output",
                    },
                ),
            ],
            "extra": [
                (
                    ["-q", "--quiet"],
                    {
                        "action": "store_true",
                        "help": "Don't print output of buildspec cache when rebuilding cache",
                    },
                ),
                (
                    ["-r", "--rebuild"],
                    {
                        "action": "store_true",
                        "help": "Rebuild buildspec cache and find all buildspecs again",
                    },
                ),
                (
                    ["-s", "--search"],
                    {
                        "type": str,
                        "action": "append",
                        "help": "Search for buildspecs to load into cache. This can be a file or a directory. A file must end in '.yml' extension, for directory buildtest will recursively search for all '.yml' extensions. This option can be specified multiple times to search multiple files",
                    },
                ),
            ],
        }

        for group_name, dest_name, desc in groups:
            group = buildspec_find_parser.add_argument_group(
                group_name, description=desc
            )

            for args, kwargs in arguments[dest_name]:
                group.add_argument(*args, **kwargs)

        buildtest_find_commands = [
            {
                "name": "invalid",
                "help": "Show invalid buildspecs",
                "parents": [
                    self.parent_parser["row-count"],
                    self.parent_parser["terse"],
                    self.parent_parser["pager"],
                ],
                "arguments": [
                    (
                        ["-e", "--error"],
                        {"action": "store_true", "help": "Show error messages"},
                    )
                ],
            }
        ]
        subcommand = {}
        subparsers_invalid = buildspec_find_parser.add_subparsers(
            metavar="", dest="buildspec_find_subcommand"
        )
        for cmd_info in buildtest_find_commands:
            name = cmd_info["name"]
            subcommand[name] = subparsers_invalid.add_parser(
                cmd_info["name"],
                help=cmd_info["help"],
                parents=cmd_info["parents"],
                aliases=cmd_info.get("aliases", []),
            )
            for arg_info in cmd_info.get("arguments", []):
                subcommand[name].add_argument(*arg_info[0], **arg_info[1])

    def config_menu(self):
        """This method adds argparse argument for ``buildtest config``"""

        parser_config = self.subparsers.choices["config"]

        subparsers_config = parser_config.add_subparsers(
            description="Query information from buildtest configuration file",
            dest="config",
            metavar="",
        )

        # Define the top-level commands and their subcommands in a list
        command_menu = [
            {
                "name": "edit",
                "aliases": ["e"],
                "help": "Open configuration file in editor",
            },
            {
                "name": "path",
                "aliases": ["p"],
                "help": "Show path to configuration file",
            },
            {"name": "systems", "help": "List all available systems"},
            {
                "name": "validate",
                "aliases": ["val"],
                "help": "Validate buildtest settings file with schema.",
            },
            {
                "name": "view",
                "aliases": ["v"],
                "help": "View configuration file",
                "parents": [self.parent_parser["pager"], self.parent_parser["theme"]],
            },
            {
                "name": "profiles",
                "aliases": ["prof"],
                "help": "Query profile from buildtest configuration",
                "subcommands": [
                    {
                        "name": "list",
                        "aliases": ["ls"],
                        "help": "List all profiles",
                        "parents": [self.parent_parser["theme"]],
                        "arguments": [
                            (
                                ("-y", "--yaml"),
                                {
                                    "action": "store_true",
                                    "help": "List Profile details in YAML Format",
                                },
                            )
                        ],
                    },
                    {
                        "name": "remove",
                        "aliases": ["rm"],
                        "help": "Remove a profile from configuration",
                        "arguments": [
                            (
                                ("profile_name",),
                                {
                                    "nargs": "*",
                                    "help": "Specify profile name to remove",
                                },
                            )
                        ],
                    },
                ],
            },
            {
                "name": "executors",
                "aliases": ["ex"],
                "help": "Query executors from buildtest configuration",
                "subcommands": [
                    {
                        "name": "list",
                        "aliases": ["ls"],
                        "help": "List all executors",
                        "mutually_exclusive_group": True,
                        "arguments": [
                            (
                                ("-j", "--json"),
                                {
                                    "action": "store_true",
                                    "help": "View executor in JSON format",
                                },
                            ),
                            (
                                ("-y", "--yaml"),
                                {
                                    "action": "store_true",
                                    "help": "View executors in YAML format",
                                },
                            ),
                            (
                                ("-d", "--disabled"),
                                {
                                    "action": "store_true",
                                    "help": "Show disabled executors",
                                },
                            ),
                            (
                                ("-i", "--invalid"),
                                {
                                    "action": "store_true",
                                    "help": "Show invalid executors",
                                },
                            ),
                            (
                                ("-a", "--all"),
                                {"action": "store_true", "help": "Show all executors"},
                            ),
                        ],
                    },
                    {
                        "name": "remove",
                        "aliases": ["rm"],
                        "help": "Remove executor from configuration",
                        "arguments": [
                            (
                                ("executor_names",),
                                {
                                    "nargs": "*",
                                    "help": "Specify an executor name to remove",
                                },
                            )
                        ],
                    },
                ],
            },
            {
                "name": "compilers",
                "aliases": ["co"],
                "help": "Search compilers",
                "subcommands": [
                    {
                        "name": "list",
                        "help": "List compilers",
                        "mutually_exclusive_group": True,
                        "arguments": [
                            (
                                ("-j", "--json"),
                                {
                                    "action": "store_true",
                                    "help": "List compiler details in JSON format",
                                },
                            ),
                            (
                                ("-y", "--yaml"),
                                {
                                    "action": "store_true",
                                    "help": "List compiler details in YAML format",
                                },
                            ),
                        ],
                    },
                    {
                        "name": "test",
                        "help": "Test each compiler instance by performing module load test",
                        "arguments": [
                            (
                                ("compiler_names",),
                                {"nargs": "*", "help": "Specify compiler name to test"},
                            )
                        ],
                    },
                    {
                        "name": "find",
                        "help": "Find compilers",
                        "parents": [self.parent_parser["file"]],
                        "arguments": [
                            (
                                ("-d", "--detailed"),
                                {
                                    "help": "Display detailed output when finding compilers",
                                    "action": "store_true",
                                },
                            ),
                            (
                                ("-u", "--update"),
                                {
                                    "action": "store_true",
                                    "help": "Update configuration file with new compilers",
                                },
                            ),
                            (
                                ("-m", "--modulepath"),
                                {
                                    "type": str,
                                    "nargs": "+",
                                    "help": "Specify a list of directories to search for modules via MODULEPATH to detect compilers",
                                },
                            ),
                        ],
                    },
                    {
                        "name": "remove",
                        "aliases": ["rm"],
                        "help": "Remove compilers",
                        "arguments": [
                            (
                                ("compiler_names",),
                                {
                                    "nargs": "*",
                                    "help": "Specify compiler name to remove",
                                },
                            )
                        ],
                    },
                ],
            },
        ]

        # Iterate through the command menu and create subparsers and arguments
        for command_data in command_menu:
            # if command_data["name"] == "compilers":
            #    continue

            subparser_command = subparsers_config.add_parser(
                command_data["name"],
                aliases=command_data.get("aliases", []),
                help=command_data["help"],
                parents=command_data.get("parents", []),
            )

            subcommands = command_data.get("subcommands", [])
            subparsers_subcommand = subparser_command.add_subparsers(
                description=f"Query information about {command_data['name']}",
                dest=command_data["name"],
                metavar="",
            )

            for subcommand_data in subcommands:
                subparser_subcommand = subparsers_subcommand.add_parser(
                    subcommand_data["name"],
                    aliases=subcommand_data.get("aliases", []),
                    help=subcommand_data["help"],
                    parents=subcommand_data.get("parents", []),
                )

                arguments = subcommand_data.get("arguments", [])
                mutually_exclusive_group = None
                if (
                    "mutually_exclusive_group" in subcommand_data
                    and subcommand_data["mutually_exclusive_group"]
                ):
                    # Add the options to a mutually exclusive group
                    mutually_exclusive_group = (
                        subparser_subcommand.add_mutually_exclusive_group()
                    )

                for args, kwargs in arguments:
                    if not mutually_exclusive_group:
                        subparser_subcommand.add_argument(*args, **kwargs)
                        continue

                    mutually_exclusive_group.add_argument(*args, **kwargs)

    def report_menu(self):
        """This method implements the ``buildtest report`` command options"""

        report_arguments = [
            (
                ["--latest"],
                {
                    "help": "Retrieve latest record of a particular test",
                    "action": "store_true",
                },
            ),
            (
                ["--oldest"],
                {
                    "help": "Retrieve oldest record of a particular test",
                    "action": "store_true",
                },
            ),
            (
                ["-s", "--start"],
                {"type": valid_time, "help": "Filter test by starttime"},
            ),
            (["-e", "--end"], {"type": valid_time, "help": "Filter test by endtime"}),
        ]

        filter_arguments = [
            (
                ["--filter"],
                {
                    "type": handle_kv_string,
                    "help": "Filter report by filter fields. The filter fields must be in key=value format and multiple fields can be comma separated (e.g., --filter key1=val1,key2=val2). For a list of filter fields, run --helpfilter.",
                },
            ),
            (
                ["--helpfilter"],
                {
                    "action": "store_true",
                    "help": "List available filter fields to be used with --filter option",
                },
            ),
            (
                ["--filterfields"],
                {
                    "action": "store_true",
                    "help": "Print raw filter fields for --filter option to filter the report",
                },
            ),
        ]

        format_arguments = [
            (
                ["--helpformat"],
                {
                    "action": "store_true",
                    "help": "List available format fields to be used with --format option",
                },
            ),
            (
                ["--formatfields"],
                {
                    "action": "store_true",
                    "help": "Print raw format fields for --format option to format the report",
                },
            ),
        ]

        groups = {
            "filter": filter_arguments,
            "format": format_arguments,
            "extra": report_arguments,
        }

        parser_report = self.subparsers.choices["report"]

        subparsers = parser_report.add_subparsers(
            description="Fetch test results from the report file and print them in table format",
            metavar="",
            dest="report_subcommand",
        )

        subcommands = [
            ("clear", ["c"], "Remove all report files"),
            ("list", ["ls"], "List all report files"),
            ("path", ["p"], "Print full path to the report file being used"),
            ("summary", ["sm"], "Summarize test report"),
        ]

        report_subparsers = {}

        for cmd, aliases, help_text in subcommands:
            if cmd == "summary":
                report_subparsers[cmd] = subparsers.add_parser(
                    cmd,
                    aliases=aliases,
                    help=help_text,
                    parents=[self.parent_parser["pager"]],
                )
                continue

            report_subparsers[cmd] = subparsers.add_parser(
                cmd, aliases=aliases, help=help_text
            )

        for group_name, group_arguments in groups.items():
            group = parser_report.add_argument_group(group_name)

            for args, args_info in group_arguments:
                group.add_argument(*args, **args_info)

        # Define mutually exclusive groups
        pass_fail_group = parser_report.add_mutually_exclusive_group()
        pass_fail_group.add_argument(
            "-f", "--fail", help="Retrieve all FAIL tests", action="store_true"
        )
        pass_fail_group.add_argument(
            "-p",
            "--pass",
            dest="passed",
            help="Retrieve all PASS tests",
            action="store_true",
        )

        format_group = parser_report.add_mutually_exclusive_group()
        format_group.add_argument(
            "--format",
            help="Format field for printing purposes. Fields must be separated by commas (e.g., --format field1,field2,...).",
        )
        format_group.add_argument(
            "-d",
            "--detailed",
            action="store_true",
            help="Print a detailed summary of the test results",
        )

        report_subparsers["summary"].add_argument(
            "--detailed",
            "-d",
            action="store_true",
            help="Enable a more detailed report",
        )

    def inspect_menu(self):
        """This method builds argument for ``buildtest inspect`` command"""

        parser_inspect = self.subparsers.choices["inspect"]

        subparser = parser_inspect.add_subparsers(
            description="Inspect Test result based on Test ID or Test Name",
            dest="inspect",
            metavar="",
        )

        menu = {
            "buildspec": {
                "aliases": ["b"],
                "help": "Inspect a test based on buildspec",
                "parents": [self.parent_parser["pager"]],
                "arguments": [
                    (
                        ["buildspec"],
                        {"nargs": "*", "help": "List of buildspecs to query"},
                    ),
                    (
                        ["-a", "--all"],
                        {
                            "action": "store_true",
                            "help": "Fetch all records for a given test",
                        },
                    ),
                ],
            },
            "name": {
                "aliases": ["n"],
                "help": "Specify name of test",
                "parents": [self.parent_parser["pager"]],
                "arguments": [(["name"], {"nargs": "*", "help": "Name of test"})],
            },
            "query": {
                "aliases": ["q"],
                "help": "Query fields from record",
                "parents": [self.parent_parser["pager"], self.parent_parser["theme"]],
                "arguments": [
                    (
                        ["-b", "--buildscript"],
                        {"action": "store_true", "help": "Print build script"},
                    ),
                    (
                        ["-be", "--buildenv"],
                        {"action": "store_true", "help": "Print content of build env"},
                    ),
                    (
                        ["-e", "--error"],
                        {"action": "store_true", "help": "Print error file"},
                    ),
                    (
                        ["-o", "--output"],
                        {"action": "store_true", "help": "Print output file"},
                    ),
                    (
                        ["-t", "--testpath"],
                        {"action": "store_true", "help": "Print content of testpath"},
                    ),
                    (
                        ["name"],
                        {
                            "nargs": "*",
                            "help": "Name of builder to query in report file",
                        },
                    ),
                ],
            },
            "list": {
                "aliases": ["ls"],
                "help": "List all test names, ids, and corresponding buildspecs",
                "parents": [
                    self.parent_parser["pager"],
                    self.parent_parser["row-count"],
                    self.parent_parser["terse"],
                    self.parent_parser["no-header"],
                ],
                "arguments": [
                    (
                        ["-b", "--builder"],
                        {"action": "store_true", "help": "List test in builder format"},
                    )
                ],
            },
        }

        # Create parsers and arguments using the menu dictionary
        for command, options in menu.items():
            parser = subparser.add_parser(
                command,
                aliases=options["aliases"],
                help=options["help"],
                parents=options["parents"],
            )
            for arg_info in options["arguments"]:
                parser.add_argument(*arg_info[0], **arg_info[1])

        return

    def cdash_menu(self):
        """This method builds arguments for ``buildtest cdash`` command."""

        cdash_commands = {
            "view": {"help": "Open CDASH project in web browser"},
            "upload": {"help": "Upload test results to CDASH server"},
        }

        cdash_arguments = {
            "view": [],
            "upload": [
                (["--site"], {"help": "Specify site name reported in CDASH"}),
                (["buildname"], {"help": "Specify Build Name reported in CDASH"}),
                (
                    ["-o", "--open"],
                    {"action": "store_true", "help": "Open CDASH report in browser"},
                ),
            ],
        }

        parser_cdash = self.subparsers.choices["cdash"]
        subparser = parser_cdash.add_subparsers(
            description="buildtest CDASH integration", dest="cdash", metavar=""
        )

        for command, command_info in cdash_commands.items():
            cdash_parser = subparser.add_parser(command, **command_info)
            for args, args_info in cdash_arguments[command]:
                cdash_parser.add_argument(*args, **args_info)
