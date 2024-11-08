"""Entry point for buildtest"""

import os
import shutil
import tempfile
import webbrowser

from rich.traceback import install

from buildtest.cli import BuildTestParser
from buildtest.cli.build import BuildTest, Tee
from buildtest.cli.buildspec import (
    BuildspecCache,
    buildspec_find,
    buildspec_maintainers,
    buildspec_validate_command,
    edit_buildspec_file,
    edit_buildspec_test,
    show_buildspecs,
    show_failed_buildspecs,
    summarize_buildspec_cache,
)
from buildtest.cli.cd import change_directory
from buildtest.cli.cdash import upload_test_cdash, view_cdash_project
from buildtest.cli.clean import clean
from buildtest.cli.commands import list_buildtest_commands
from buildtest.cli.compilers import compiler_cmd
from buildtest.cli.config import config_cmd
from buildtest.cli.debugreport import print_debug_report
from buildtest.cli.helpcolor import print_available_colors
from buildtest.cli.history import build_history
from buildtest.cli.info import buildtest_info
from buildtest.cli.inspect import (
    inspect_buildspec,
    inspect_by_name,
    inspect_list,
    inspect_query,
)
from buildtest.cli.path import path_cmd
from buildtest.cli.report import Report, report_cmd
from buildtest.cli.show import buildtest_show
from buildtest.cli.stats import stats_cmd
from buildtest.config import SiteConfiguration
from buildtest.defaults import (
    BUILDSPEC_CACHE_FILE,
    BUILDTEST_BUILDSPEC_DIR,
    BUILDTEST_EXECUTOR_DIR,
    BUILDTEST_LOGFILE,
    BUILDTEST_USER_HOME,
    console,
)
from buildtest.exceptions import BuildTestError
from buildtest.log import init_logfile
from buildtest.system import BuildTestSystem
from buildtest.tools.editor import set_editor
from buildtest.tools.stylecheck import run_style_checks
from buildtest.tools.tutorialexamples import generate_tutorial_examples
from buildtest.tools.unittests import run_unit_tests
from buildtest.utils.file import (
    create_dir,
    is_file,
    read_file,
    remove_file,
    resolve_path,
)
from buildtest.utils.tools import deep_get


def main():
    """Entry point to buildtest."""

    parser = BuildTestParser()
    args = parser.parse()
    system, configuration, buildtest_editor, report_file = setup(args)

    # print logfile if one specifies buildtest --view-log or buildtest --print-log
    if handle_log_viewing(args):
        return

    if args.listopts:
        print("\n".join(parser.retrieve_main_options()))
        return
    # print the available color options in a table format if buildtest --helpcolor is specified
    if args.helpcolor:
        print_available_colors()
        return

    # print full path to the lastlog file if buildtest --logpath is specified
    if args.logpath:
        console.print(BUILDTEST_LOGFILE)
        return

    # buildtest build command
    if args.subcommands in ["build", "bd"]:
        handle_build_command(args, configuration, report_file)

    # buildtest build history
    if args.subcommands in ["history", "hy"]:
        build_history(args)

    # implementation for 'buildtest buildspec find'
    elif args.subcommands in ["buildspec", "bc"]:
        handle_buildspec_command(args, configuration, report_file, buildtest_editor)

    # running buildtest inspect
    elif args.subcommands in ["inspect", "it"]:
        handle_inspect_command(args, configuration, report_file)

    elif args.subcommands in ["stats"]:
        stats_cmd(name=args.name, configuration=configuration, report_file=report_file)

    # running buildtest config
    elif args.subcommands in ["config", "cg"]:
        #  running buildtest config compilers
        if args.config in ["compilers", "co"]:
            compiler_cmd(args, configuration)
        else:
            config_cmd(
                command_args=args,
                configuration=configuration,
                editor=buildtest_editor,
                system=system,
            )

    # buildtest report
    elif args.subcommands in ["report", "rt"]:
        report_cmd(args, configuration=configuration, report_file=report_file)

    elif args.subcommands == "path":
        path_cmd(
            name=args.name,
            outfile=args.outfile,
            errfile=args.errfile,
            testpath=args.testpath,
            buildscript=args.buildscript,
            stagedir=args.stagedir,
            buildenv=args.buildenv,
            configuration=configuration,
            report_file=report_file,
        )

    # running buildtest cdash
    elif args.subcommands == "cdash":
        handle_cdash_command(args, configuration, report_file)

    elif args.subcommands in ["show", "s"]:
        buildtest_show(command=args.command)

    elif args.subcommands == "clean":
        clean(configuration=configuration, yes=args.yes)

    elif args.subcommands == "cd":
        change_directory(args.test, configuration=configuration)

    elif args.subcommands == "docs":
        webbrowser.open("https://buildtest.readthedocs.io/")

    elif args.subcommands == "info":
        buildtest_info(configuration, system)

    elif args.subcommands in ["debug", "debugreport"]:
        print_debug_report(system, configuration)

    elif args.subcommands in ["unittests", "test"]:
        run_unit_tests(
            pytestopts=args.pytestopts,
            sourcefiles=args.sourcefiles,
            enable_coverage=args.coverage,
        )

    elif args.subcommands == "tutorial-examples":
        generate_tutorial_examples(
            examples=args.examples,
            dryrun=args.dryrun,
            write=args.write,
            failfast=args.failfast,
        )

    elif args.subcommands in ["stylecheck", "style"]:
        run_style_checks(
            no_black=args.no_black,
            no_isort=args.no_isort,
            no_pyflakes=args.no_pyflakes,
            apply_stylechecks=args.apply,
        )

    elif args.subcommands in ["commands", "cmds"]:
        list_buildtest_commands(with_aliases=args.with_aliases)


def setup(args):
    """This function sets up the environment for buildtest.
    This function initializes logging, configuration, and system object.
    This function returns a tuple of system, configuration, buildtest_editor, and report_file.
    This function is called at the beginning of main() function.

    Args:
        args (argparse.Namespace): An argparse namespace object containing command line arguments

    Returns:
        Tuple: A tuple of system, configuration, buildtest_editor, and report_file
    """
    install(show_locals=True)
    no_color = False

    # disable color if buildtest --no-color or BUILDTEST_COLOR=False is set
    if args.no_color or os.getenv("BUILDTEST_COLOR") == "False":
        no_color = True

    console.no_color = no_color

    if args.verbose:
        console.print("Coloring mode: ", "off" if no_color else "on")

    report_file = args.report

    if is_file(BUILDTEST_LOGFILE):
        remove_file(BUILDTEST_LOGFILE)

    logger = init_logfile(debug=args.debug, loglevel=args.loglevel)

    create_dir(BUILDTEST_USER_HOME)
    create_dir(BUILDTEST_EXECUTOR_DIR)
    create_dir(BUILDTEST_BUILDSPEC_DIR)

    # Create a build test system, and check requirements
    system = BuildTestSystem()

    if args.verbose:
        console.print("Finish system initialization", style="bold blue")

    config_file = (
        resolve_path(args.configfile) or os.getenv("BUILDTEST_CONFIGFILE") or None
    )
    configuration = SiteConfiguration(config_file, verbose=args.verbose)
    configuration.detect_system()
    configuration.validate()

    if args.verbose:
        console.print("Finish configuration initialization", style="bold blue")
        console.print(
            f"Using configuration file: {configuration.file}", style="bold blue"
        )

    buildtest_editor = set_editor(args.editor)
    logger.info(f"[red]Processing buildtest configuration file: {configuration.file}")

    # build buildspec cache file automatically if it doesn't exist
    if not is_file(BUILDSPEC_CACHE_FILE):
        search_buildspecs = []
        if hasattr(args, "search"):
            search_buildspecs = args.search

        BuildspecCache(search_buildspecs=search_buildspecs, configuration=configuration)

    return system, configuration, buildtest_editor, report_file


def handle_log_viewing(args):
    """This function handles the viewing of the log file. If the user specifies --view-log or --print-log, this function will display the log file content and return True.
    If the log file is not present, this function will raise an exception. If the user does not specify --view-log or --print-log, this function will return False.

    Args:
        args (argparse.Namespace): An argparse namespace object containing command line arguments

    Returns:
        bool: Return True if user specifies --view-log or --print-log and implements logic, otherwise return False
    """
    if args.view_log or args.print_log:
        # if logfile is not present we should raise exception since this file is only created upon running 'buildtest build'
        if not is_file(BUILDTEST_LOGFILE):
            raise BuildTestError(
                f"Unable to find logfile: {BUILDTEST_LOGFILE}, please run 'buildtest build'"
            )

        content = read_file(BUILDTEST_LOGFILE)

        if args.view_log:
            with console.pager():
                console.print(content)
        else:
            console.print(content)

        return True
    return False


def handle_build_command(args, configuration, report_file):
    if args.subcommands in ["build", "bd"]:
        stdout_file = tempfile.NamedTemporaryFile(delete=True, suffix=".txt")
        with Tee(stdout_file.name):
            cmd = BuildTest(
                account=args.account,
                buildspecs=args.buildspec,
                configuration=configuration,
                display=args.display,
                dry_run=args.dry_run,
                exclude_buildspecs=args.exclude,
                exclude_tags=args.exclude_tags,
                executors=args.executor,
                executor_type=args.executor_type,
                filter_buildspecs=args.filter,
                helpfilter=args.helpfilter,
                limit=args.limit,
                max_jobs=args.max_jobs,
                maxpendtime=args.maxpendtime,
                modules=args.modules,
                modulepurge=args.module_purge,
                numnodes=args.nodes,
                numprocs=args.procs,
                name=args.name,
                poll_interval=args.pollinterval,
                profile=args.profile,
                rebuild=args.rebuild,
                remove_stagedir=args.remove_stagedir,
                report_file=report_file,
                rerun=args.rerun,
                retry=args.retry,
                save_profile=args.save_profile,
                strict=args.strict,
                tags=args.tags,
                testdir=args.testdir,
                timeout=args.timeout,
                unload_modules=args.unload_modules,
                validate=args.validate,
                verbose=args.verbose,
                write_config_file=args.write_config_file,
            )
            cmd.build()

        if cmd.build_success():
            build_history_dir = cmd.get_build_history_dir()

            shutil.copyfile(
                stdout_file.name, os.path.join(build_history_dir, "output.txt")
            )

        stdout_file.close()


def handle_buildspec_command(args, configuration, report_file, buildtest_editor):
    if args.buildspecs_subcommand in ["find", "f"]:
        buildspec_find(args=args, configuration=configuration)
    elif args.buildspecs_subcommand in ["summary", "sm"]:
        summarize_buildspec_cache(
            pager=args.pager, configuration=configuration, color=args.color
        )
    elif args.buildspecs_subcommand in ["show", "s"]:
        show_buildspecs(
            test_names=args.name, configuration=configuration, theme=args.theme
        )
    elif args.buildspecs_subcommand in ["show-fail", "sf"]:
        show_failed_buildspecs(
            configuration=configuration,
            test_names=args.name,
            report_file=report_file,
            theme=args.theme,
        )
    elif args.buildspecs_subcommand in ["edit-test", "et"]:
        edit_buildspec_test(
            test_names=args.name, configuration=configuration, editor=buildtest_editor
        )
    elif args.buildspecs_subcommand in ["edit-file", "ef"]:
        edit_buildspec_file(
            buildspecs=args.file, configuration=configuration, editor=buildtest_editor
        )
    elif args.buildspecs_subcommand in ["maintainers", "m"]:
        name = None
        if hasattr(args, "name"):
            name = args.name
        buildspec_maintainers(
            configuration=configuration,
            breakdown=args.breakdown,
            terse=args.terse,
            header=args.no_header,
            color=args.color,
            name=name,
            row_count=args.row_count,
            count=args.count,
            pager=args.pager,
        )

    elif args.buildspecs_subcommand in ["validate", "val"]:
        buildspec_validate_command(
            buildspecs=args.buildspec,
            excluded_buildspecs=args.exclude,
            tags=args.tag,
            executors=args.executor,
            name=args.name,
            configuration=configuration,
        )


def handle_inspect_command(args, configuration, report_file):
    report = Report(configuration=configuration, report_file=report_file)
    if args.inspect in ["list", "ls"]:
        inspect_list(
            report,
            terse=args.terse,
            no_header=args.no_header,
            builder=args.builder,
            color=args.color,
            pager=args.pager,
            row_count=args.row_count,
        )
    # implements command 'buildtest inspect name'
    if args.inspect in ["name", "n"]:
        inspect_by_name(report, names=args.name, pager=args.pager)

    if args.inspect in ["query", "q"]:
        inspect_query(
            report,
            name=args.name,
            theme=args.theme,
            output=args.output,
            error=args.error,
            testpath=args.testpath,
            buildscript=args.buildscript,
            buildenv=args.buildenv,
            pager=args.pager,
        )

    if args.inspect in ["buildspec", "b"]:
        inspect_buildspec(
            report,
            input_buildspecs=args.buildspec,
            all_records=args.all,
            pager=args.pager,
        )


def handle_cdash_command(args, configuration, report_file):
    cdash_config = deep_get(configuration.target_config, "cdash")

    if not cdash_config:
        raise BuildTestError(
            f"We found no 'cdash' setting set in configuration file: {configuration.file}. Please specify 'cdash' setting in order to use 'buildtest cdash' command"
        )

    if args.cdash == "view":
        view_cdash_project(
            cdash_config=cdash_config, config_file=configuration.file, open_browser=True
        )
    elif args.cdash == "upload":
        upload_test_cdash(
            build_name=args.buildname,
            configuration=configuration,
            site=args.site,
            report_file=report_file,
            open_browser=args.open,
        )


if __name__ == "__main__":
    main()
