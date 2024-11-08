"""
BuilderBase class is an abstract class that defines common
functions for any types of builders. Each type schema (script, compiler, spack)
is implemented as separate Builder which extends BuilderBase class.
"""

import datetime
import getpass
import json
import logging
import os
import re
import shutil
import socket
import stat
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from buildtest.buildsystem.checks import (
    assert_range_check,
    comparison_check,
    contains_check,
    exists_check,
    file_count_check,
    file_linecount_check,
    file_regex_check,
    is_dir_check,
    is_file_check,
    is_symlink_check,
    linecount_check,
    regex_check,
    returncode_check,
    runtime_check,
)
from buildtest.cli.compilers import BuildtestCompilers
from buildtest.defaults import BUILDTEST_EXECUTOR_DIR, console
from buildtest.exceptions import BuildTestError
from buildtest.scheduler.job import Job
from buildtest.schemas.defaults import schema_table
from buildtest.utils.command import BuildTestCommand
from buildtest.utils.file import (
    create_dir,
    is_file,
    read_file,
    resolve_path,
    write_file,
)
from buildtest.utils.print import print_content, print_file_content
from buildtest.utils.shell import Shell, is_csh_shell
from buildtest.utils.timer import Timer
from buildtest.utils.tools import check_container_runtime, deep_get


class BuilderBase(ABC):
    """The BuilderBase is an abstract class that implements common functions used for building and running test.

    buildtest will create a builder object which resembles a test. The builder will contains metadata that is unique
    to each builder that is captured in the report file upon completion of test.

    """

    def __init__(
        self,
        name,
        recipe,
        buildspec,
        executor,
        buildexecutor,
        testdir,
        numprocs=None,
        numnodes=None,
        compiler=None,
        display=None,
    ):
        """The BuilderBase provides common functions for any builder. The builder
        is an instance of BuilderBase. The initializer method will setup the builder
        attributes based on input test by ``name`` parameter.

        Args:
            name (str): Name of test in buildspec recipe
            recipe (str): The loaded test section from the buildspec file
            buildspec (str): Full path to buildspec file
            buildexecutor (:obj:`buildtest.executors.setup.BuildExecutor`): An instance of BuildExecutor class used for accessing executors
            testdir (str): Test directory where tests are written. Must be full path on filesystem.
            display (list, optional):  Display content of output/error or test.
        """

        self.name = name

        self.compiler = compiler
        self.cc = None
        self.fc = None
        self.cxx = None
        self.cflags = None
        self.cxxflags = None
        self.fflags = None
        self.ldflags = None
        self.cppflags = None
        self.display = display or []
        self.metadata = {}

        self.duration = 0

        self.numprocs = numprocs
        self.numnodes = numnodes
        self._retry = None
        self.timer = Timer()

        # store state of builder which can be True/False. This value is changed by self.success(), self.failure()
        self._buildstate = None

        # The type must match the type of the builder
        self.recipe = recipe

        self.executor = executor

        # For batch jobs this variable is an instance of Job class which would be one of the subclass
        self.job = None

        # Controls the state of the builder object, a complete job  will set
        # this value to True. A job cancellation or job failure in submission will set this to False
        self._state = "PENDING"

        # this value holds the 'status' property from the buildspec
        self.status = None

        # this value hosts the 'metrics' property from the buildspec
        self.metrics = None

        self.buildspec = buildspec

        # used for storing output content
        self._output = None
        # used for storing error content
        self._error = None

        # strip .yml extension from file name
        file_name = re.sub("[.](yml)", "", os.path.basename(buildspec))
        self.testdir = os.path.join(testdir, self.executor, file_name, self.name)

        self.logger = logging.getLogger(__name__)

        self.logger.debug(f"Processing Buildspec File: {self.buildspec}")
        self.logger.debug(f"Processing Test: {self.name}")

        # get type attribute from Executor class (local, slurm, pbs, lsf)
        self.executor_type = buildexecutor.executors[self.executor].type
        self.buildexecutor = buildexecutor

        # Generate a unique id for the build based
        self.testid = str(uuid.uuid4())

        self._dependency = False

        self._set_metadata_values()
        self.shell_detection()
        self.set_scheduler_settings()

    @property
    def dependency(self):
        return self._dependency

    @dependency.setter
    def dependency(self, state):
        self._dependency = state

    def shell_detection(self):
        """Detect shell and shebang used for test script"""
        # if 'shell' property not defined in buildspec use this shell otherwise use the 'shell' property from the executor definition
        self.shell = Shell(
            self.recipe.get("shell")
            or self.buildexecutor.executors[self.executor]._settings.get("shell")
            or "bash"
        )

        # set shebang to value defined in Buildspec, if not defined then get one from Shell class
        self.shebang = (
            self.recipe.get("shebang") or f"{self.shell.shebang} {self.shell.opts}"
        )
        self.logger.debug(f"Using shell {self.shell.name}")
        self.logger.debug(f"Shebang used for test: {self.shebang}")

    def _set_metadata_values(self):
        """This method sets ``self.metadata`` that contains metadata for each builder object."""
        self.metadata["name"] = self.name
        self.metadata["buildspec"] = self.buildspec

        # store tags
        self.metadata["tags"] = self.recipe.get("tags")
        # store executor name
        self.metadata["executor"] = self.executor

        # store schemafile used for validating
        self.metadata["schemafile"] = os.path.basename(
            schema_table[f"{self.recipe['type']}.schema.json"]["path"]
        )

        # store output content of test
        self.metadata["output"] = None
        # store error content of test
        self.metadata["error"] = None

        # store current hostname
        self.metadata["hostname"] = socket.gethostname()
        # store current username
        self.metadata["user"] = getpass.getuser()

        # root of test directory
        self.metadata["testroot"] = None
        # location of stage directory in test root
        self.metadata["stagedir"] = None

        self.metadata["description"] = self.recipe.get("description") or ""
        self.metadata["summary"] = self.recipe.get("summary") or ""

        # location of test script
        self.metadata["testpath"] = None

        # store content of buildspec file
        self.metadata["buildspec_content"] = read_file(self.buildspec)
        # used to store content of test
        self.metadata["test_content"] = None
        self.metadata["buildscript_content"] = None

        # used to store compiler name used the test. Only applicable with compiler schema
        self.metadata["compiler"] = None

        self.metadata["result"] = {"state": "N/A", "returncode": "-1", "runtime": 0}
        status_check_names = [
            "regex",
            "returncode",
            "runtime",
            "file_regex",
            "slurm_job_state",
            "pbs_job_state",
            "lsf_job_state",
            "assert_ge",
            "assert_gt",
            "assert_le",
            "assert_lt",
            "assert_eq",
            "assert_ne",
            "contains",
            "not_contains",
            "is_symlink",
            "exists",
            "is_dir",
            "is_file",
            "file_count",
            "linecount",
            "file_linecount",
        ]
        self.metadata["check"] = {name: None for name in status_check_names}
        self.metadata["metrics"] = {}

        # used to store job id from batch scheduler
        self.metadata["jobid"] = None
        # used to store job metrics for given JobID from batch scheduler
        self.metadata["job"] = {}

        self.metadata["full_id"] = self.testid
        self.metadata["id"] = self.testid[:8]

    def get_test_extension(self):
        """Return the test extension, which depends on the shell type. By default we return `sh`
        file extension for all shells except for `csh` which will return "csh" extension.

        Returns
            str: Returns test extension name for generated test.
        """

        # for csh we return shell extension 'csh'
        if is_csh_shell(self.shell.name):
            return "csh"

        # default file extension
        return "sh"

    def is_local_executor(self):
        """Return True if current builder executor type is LocalExecutor otherwise returns False.

        Returns:
            bool: returns True if builder is using executor type LocalExecutor otherwise returns False

        """

        return self.buildexecutor.executors[self.executor].type == "local"

    def is_container_executor(self):
        return self.buildexecutor.executors[self.executor].type == "container"

    def is_batch_job(self):
        """Return True/False if builder.job attribute is of type Job instance if not returns False.
        This method indicates if builder has a job submitted to queue
        """

        return isinstance(self.job, Job)

    def start(self):
        """Keep internal timer for test using class :class:`buildtest.utils.timer.Timer`. This method will start the timer for builder which is invoked upon running test."""

        self.timer.start()

    def stop(self):
        """Stop internal timer for builder."""
        self.timer.stop()

    def retry(self, retry):
        self._retry = retry

    def build(self, modules=None, modulepurge=None, unload_modules=None):
        """This method is responsible for invoking setup, creating test
        directory and writing test. This method is called from an instance
        object of this class that does ``builder.build()``.

        args:
            modules (str, optional): Specify a list of modules to load in the build script
            modulepurge (bool, optional): A boolean to control whether 'module purge' is run before running test
            unload_modules (str, optional): Specify a list of modules to unload in the build script
        """

        self._build_setup()
        self._write_test()
        self._write_build_script(modules, modulepurge, unload_modules)
        self._display_test_content(
            filepath=self.build_script, title="Start of Build Script"
        )
        self._display_test_content(filepath=self.testpath, title="Start of Test Script")
        self._write_post_run_script()

    def run(self, cmd, timeout=None):
        """This is the entry point for running the test. This method will prepare test to be run, then
        run the test. Once test is complete, we also handle test results by capturing output and error.

        Returns:
            If success, the return type is an object of type :class:`buildtest.utils.command.BuildTestCommand`

            If their is a failure (non-zero) returncode we retry test and if it doesn't pass we
            raise exception of :class:`buildtest.exceptions.RuntimeFailure`
        """
        self.prepare_run(cmd)
        command_result = self.execute_run(cmd, timeout)
        run_result = self.handle_run_result(command_result, timeout)
        return run_result

    def prepare_run(self, cmd):
        """This method prepares the test to be run by recording starttime, setting state to running and starting the timer.
        In additional we will write build environment into build-env.txt which is used for debugging purposes.
        """

        self.metadata["command"] = cmd
        console.print(f"[blue]{self}[/]: Current Working Directory : {os.getcwd()}")
        command = BuildTestCommand("env")
        command.execute()
        content = "".join(command.get_output())
        self.metadata["buildenv"] = os.path.join(self.test_root, "build-env.txt")
        write_file(self.metadata["buildenv"], content)
        console.print(f"[blue]{self}[/]: Running Test via command: [cyan]{cmd}[/cyan]")
        self.record_starttime()
        self.running()
        self.start()

    def execute_run(self, cmd, timeout):
        """This method will execute the test and return the instance object of type
        BuildTestCommand which is used by Executors for processing output and error"""

        command = BuildTestCommand(cmd)
        command.execute(timeout=timeout)
        return command

    def execute_post_run_script(self):
        """This method will execute the post run script which is invoked after test is complete. This is called
        if ``post_run`` is defined in buildspec.
        """
        if os.path.exists(self.post_run_script):
            post_run = BuildTestCommand(self.post_run_script)
            post_run.execute()
            output = "".join(post_run.get_output())
            error = "".join(post_run.get_error())

            console.print(
                f"[blue]{self}[/]: Running Post Run Script: [cyan]{self.post_run_script}[/cyan]"
            )
            console.print(
                f"[blue]{self}[/]: Post run script exit code: {post_run.returncode()}"
            )

            self._display_output_content(output, title="Start of Post Run Output")
            self._display_output_content(error, title="Start of Post Run Error")

    def _display_output_content(self, output, title, show_last_lines=10):
        """This method will display content of output or error results. The ``output`` is content of file to display. A title
        is displayed at top which can be customized via ``title``. We can configure number of lines to display from end of file via
        ```show_last_lines``.

        Args:
            output (str): Output content to display
            title (str): Title to display before content
            show_last_lines (int, optional): Number of lines to display from end of file. Default is 10
        """

        if "output" in self.display:
            print_content(
                output,
                title=f"[blue]{self}[/]: {title}",
                theme="monokai",
                lexer="text",
                show_last_lines=show_last_lines,
            )

    def _display_test_content(self, filepath, title) -> None:
        """Display content of test file, given a path to file and title to display.
        Args:
            filepath (str): Path to file to display content
            title (str): Title to display before content
        """

        if "test" in self.display:
            print_file_content(
                file_path=filepath,
                title=f"[blue]{self}[/]: {title}",
                lexer="bash",
                theme="monokai",
            )

    def handle_run_result(self, command_result, timeout):
        """This method will handle the result of running test. If the test is successful we will record endtime,
        copy output and error file to test directory and set state to complete. If the test fails we will retry the test based on retry count.
        If the test fails after retry we will mark test as failed.

        Args:
            command_result (BuildTestCommand): An instance object of BuildTestCommand
            timeout (int): Timeout value for test run
        """
        launch_command = command_result.get_command()
        self.logger.debug(f"Running Test via command: {launch_command}")
        ret = command_result.returncode()
        output_msg = "".join(command_result.get_output())
        err_msg = "".join(command_result.get_error())

        self._display_output_content(output_msg, title="Start of Output")

        if not self._retry or ret == 0:
            return command_result

        console.print(f"[red]{self}: failed to submit job with returncode: {ret}")

        self._display_output_content(
            output=err_msg, title="Start of Error", show_last_lines=30
        )

        console.print(
            f"[red]{self}: Detected failure in running test, will attempt to retry test: {self._retry} times"
        )
        for run in range(1, self._retry + 1):
            print(f"{self}: Run - {run}/{self._retry}")
            command = self.execute_run(launch_command, timeout)

            console.print(
                f"[blue]{self}[/]: Running Test via command: [cyan]{launch_command}[/cyan]"
            )
            self.logger.debug(f"Running Test via command: {launch_command}")
            ret = command.returncode()
            if ret == 0:
                return command
            console.print(f"[red]{self}: failed to submit job with returncode: {ret}")

        return command

    def record_starttime(self):
        """This method will record the starttime when job starts execution by using
        ``datetime.datetime.now()``
        """

        self._starttime = datetime.datetime.now()

        # this is recorded in the report file
        self.metadata["result"]["starttime"] = self._starttime.strftime("%Y/%m/%d %X")

    def record_endtime(self):
        """This method is called upon termination of job, we get current time using
        ``datetime.datetime.now()`` and calculate runtime of job
        """

        self._endtime = datetime.datetime.now()

        # this is recorded in the report file
        self.metadata["result"]["endtime"] = self._endtime.strftime("%Y/%m/%d %X")

        self.runtime()

    def runtime(self):
        """Calculate runtime of job by calculating delta between endtime and starttime. The unit of measure
        is seconds.
        """

        runtime = self._endtime - self._starttime
        self._runtime = runtime.total_seconds()

        # for batch jobs we use the elapsed time for job to calculate the runtime
        if self.is_batch_job():
            self._runtime = self.job.elapsedtime

        self.metadata["result"]["runtime"] = self._runtime

    def get_runtime(self):
        """Return runtime of test"""
        return self._runtime

    def state(self):
        return self._state

    def failed(self):
        """Mark test as failure by updating the ``self._state``. A fail test will not be reported in test report"""
        self._state = "FAILED"

    def complete(self):
        """Mark test as complete by updating the ``self._state``. A complete test assumes test ran to completion"""
        self._state = "COMPLETE"

    def running(self):
        self._state = "RUNNING"

    def is_pending(self):
        return self._state == "PENDING"

    def is_complete(self):
        """If builder completes execution of test this method will return ``True`` otherwise returns ``False``.
        A builder could fail due to job cancellation, failure to submit job or raise exception during the run phase.
        In those case, this method will return ``False``."""
        return self._state == "COMPLETE"

    def is_failed(self):
        """Return True if builder fails to run test."""
        return self._state == "FAILED"

    def is_running(self):
        """Return True if builder fails to run test."""
        return self._state == "RUNNING"

    def _build_setup(self) -> None:
        """Setup operation to get ready to build test."""
        self._create_directories()
        self._resolve_paths()
        self._copy_files_to_stage()

    def _create_directories(self) -> None:
        """Create necessary directories for the build."""
        create_dir(self.testdir)
        self.test_root = os.path.join(self.testdir, self.testid[:8])
        create_dir(self.test_root)
        self.stage_dir = os.path.join(self.test_root, "stage")
        create_dir(self.stage_dir)
        self.logger.debug(f"Creating the stage directory: {self.stage_dir}")
        self.metadata["stagedir"] = self.stage_dir
        self.metadata["testroot"] = self.test_root

    def _resolve_paths(self) -> None:
        """Resolve full paths to generated test script and build script."""
        self.testpath = (
            os.path.join(self.stage_dir, self.name) + "." + self.get_test_extension()
        )
        self.testpath = os.path.expandvars(self.testpath)
        self.metadata["testpath"] = self.testpath
        self.build_script = f"{os.path.join(self.stage_dir, self.name)}_build.sh"

    def _copy_files_to_stage(self) -> None:
        """Copy all files from buildspec directory to stage directory."""
        for fname in Path(os.path.dirname(self.buildspec)).glob("*"):
            if fname.is_dir():
                shutil.copytree(
                    fname, os.path.join(self.stage_dir, os.path.basename(fname))
                )
            elif fname.is_file():
                shutil.copy2(fname, self.stage_dir)
        console.print(f"[blue]{self}[/]: Creating Test Directory: {self.test_root}")

    def _write_build_script(
        self,
        modules: List[str] = None,
        modulepurge: bool = None,
        unload_modules: List[str] = None,
    ) -> None:
        """Write the content of build script."""
        lines = self._generate_build_script_lines(modules, modulepurge, unload_modules)
        lines = "\n".join(lines)
        write_file(self.build_script, lines)
        self._set_execute_perm(self.build_script)
        self._copy_build_script_to_test_root()
        self.metadata["buildscript_content"] = lines

    def _generate_build_script_lines(
        self, modules: List[str], modulepurge: bool, unload_modules: List[str]
    ) -> List[str]:
        """Generate lines for the build script."""
        lines = ["#!/bin/bash"]
        lines.append(self._generate_trap_message())
        lines += self._set_default_test_variables()
        if modulepurge:
            lines.append("module purge")
        if unload_modules:
            lines.append("# Specify list of modules to unload")
            lines += [f"module unload {module}" for module in unload_modules]
        if modules:
            lines.append("# Specify list of modules to load")
            lines += [f"module load {module}" for module in modules]
        lines.append(
            f"source {os.path.join(BUILDTEST_EXECUTOR_DIR, self.executor, 'before_script.sh')}"
        )
        lines.append("# Run generated script")
        lines += self._get_execution_command()
        lines.append("# Get return code")
        lines.append("returncode=$?")
        lines.append("# Exit with return code")
        lines.append("exit $returncode")
        return lines

    def _generate_trap_message(self) -> str:
        """Generate trap message for the build script."""
        return """
# Function to handle all signals and perform cleanup
function cleanup() {
    echo "Signal trapped. Performing cleanup before exiting."
    exitcode=$?
    echo "buildtest: command '$BASH_COMMAND' failed (exit code: $exitcode)"
    exit $exitcode
}

# Trap all signals and call the cleanup function
trap cleanup SIGINT SIGTERM SIGHUP SIGQUIT SIGABRT SIGKILL SIGALRM SIGPIPE SIGTERM SIGTSTP SIGTTIN SIGTTOU
"""

    def _get_execution_command(self) -> List[str]:
        """Get the command to execute the script."""
        if self.is_local_executor():
            return [" ".join(self._emit_command())]
        elif self.is_container_executor():
            return self.get_container_invocation()
        else:
            launcher = self.buildexecutor.executors[self.executor].launcher_command( numprocs=self.numprocs, numnodes=self.numnodes)
            return [" ".join(launcher) + " " + f"{self.testpath}"]

    def _copy_build_script_to_test_root(self) -> None:
        """Copy build script to test root directory."""
        dest = os.path.join(self.test_root, os.path.basename(self.build_script))
        shutil.copy2(self.build_script, dest)
        self.logger.debug(f"Copying build script to: {dest}")
        self.build_script = dest
        self.metadata["build_script"] = self.build_script

    def _write_post_run_script(self):
        """This method will write the content of post run script that is run after the test is complete.
        The post run script is used to perform cleanup operations after test is complete.
        Upon creating file we set permission of builder script to 755 so test can be run.
        """

        self.post_run_script = f"{os.path.join(self.stage_dir, self.name)}_postrun.sh"

        if not self.recipe.get("post_run"):
            return

        lines = ["#!/bin/bash -v"]
        lines += self.recipe["post_run"].split("\n")

        lines = "\n".join(lines)
        write_file(self.post_run_script, lines)
        self._set_execute_perm(self.post_run_script)
        console.print(
            f"[blue]{self}[/]: Writing Post Run Script: {self.post_run_script}"
        )
        self._display_test_content(
            filepath=self.post_run_script, title="Start of Post Run Script"
        )

    def _write_test(self):
        """This method is responsible for invoking ``generate_script`` that
        formulates content of testscript which is implemented in each subclass.
        Next we write content to file and apply 755 permission on script so
        it has executable permission.
        """

        # Implementation to write file generate.sh
        lines = []
        lines += self.generate_script()
        lines = "\n".join(lines)

        self.logger.info(f"Opening Test File for Writing: {self.testpath}")
        write_file(self.testpath, lines)

        self.metadata["test_content"] = lines
        self._set_execute_perm(self.testpath)
        # copy testpath to root test directory
        shutil.copy2(
            self.testpath, os.path.join(self.test_root, os.path.basename(self.testpath))
        )

    def get_container_invocation(self):
        """This method returns a list of lines containing the container invocation"""
        lines = []
        platform = self.buildexecutor.executors[self.executor]._settings.get("platform")
        image = self.buildexecutor.executors[self.executor]._settings.get("image")
        options = self.buildexecutor.executors[self.executor]._settings.get("options")
        mounts = self.buildexecutor.executors[self.executor]._settings.get("mounts")

        container_path = check_container_runtime(
            platform, self.buildexecutor.configuration
        )

        if platform in ["docker", "podman"]:
            lines += [
                f"{container_path} run -it --rm -v {self.stage_dir}:/buildtest -w /buildtest"
            ]

            if mounts:
                lines += [f"-v {mounts}"]
            if options:
                lines += [f"{options}"]

            lines += [
                f"{image} bash -c {os.path.join('/buildtest', os.path.basename(self.testpath))}"
            ]
        elif platform == "singularity":
            lines += [f"{container_path} exec -B {self.stage_dir}/buildtest"]
            if mounts:
                lines += [f"-B {mounts}"]
            if options:
                lines += [f"{options}"]
            lines += [f"{image} {self.testpath}"]
        return [" ".join(lines)]

    def _emit_command(self):
        """This method will return a shell command used to invoke the script that is used for tests that
        use local executors

        Returns:
            list: a list to show generated command used to run test.

            Test can be run without any argument with path to script: ``/path/to/script.sh``
            Test can be run with shell name followed by path to script: ``bash /path/to/script.sh``
            Test can be run with shell name, shell options and path to script: ``bash -x /path/to/script.sh``
        """
        # if not self.recipe.get("shell") or self.recipe.get("shell") == "python":
        if self.recipe.get("shell") == "python":
            return [self.testpath]

        # if not self.recipe.get("shell"):
        #    return [self.shell.name, self.shell.default_opts, self.testpath]

        # if not self.shell.opts:
        #    return [self.shell.name, self.testpath]

        return [self.shell.name, self.shell.opts, self.testpath]

    def _emit_set_command(self):
        """This method will emit the set command for strict mode that will exit immediately. In bash, zsh the command is ``set -eo pipefail``. For csh, tcsh and sh there is
        no such command so we return empty string."""

        if self.shell.name == "bash" or self.shell.name == "zsh":
            return "set -eo pipefail"

        return ""

    def _set_default_test_variables(self):
        """Return a list of lines inserted in build script that define buildtest specific variables
        that can be referenced when writing tests. The buildtest variables all start with BUILDTEST_*
        """

        lines = [
            f"export BUILDTEST_TEST_NAME={self.name}",
            f"export BUILDTEST_TEST_ROOT={self.test_root}",
            f"export BUILDTEST_BUILDSPEC_DIR={os.path.dirname(self.buildspec)}",
            f"export BUILDTEST_STAGE_DIR={self.stage_dir}",
        ]

        if self.numnodes:
            lines.append(f"export BUILDTEST_NUMNODES={self.numnodes}")
        if self.numprocs:
            lines.append(f"export BUILDTEST_NUMPROCS={self.numprocs}")

        return lines

    def set_scheduler_settings(self):
        """This method will resolve scheduler fields: 'sbatch', 'pbs', 'bsub'"""
        self.sbatch = deep_get(
            self.recipe, "executors", self.executor, "sbatch"
        ) or self.recipe.get("sbatch")
        self.bsub = deep_get(
            self.recipe, "executors", self.executor, "bsub"
        ) or self.recipe.get("bsub")
        self.pbs = deep_get(
            self.recipe, "executors", self.executor, "pbs"
        ) or self.recipe.get("pbs")

        self.burstbuffer = self.recipe.get("BB") or deep_get(
            self.recipe, "executors", self.executor, "BB"
        )
        self.datawarp = self.recipe.get("DW") or deep_get(
            self.recipe, "executors", self.executor, "DW"
        )

    def get_job_directives(self):
        """This method returns a list of lines containing the scheduler directives"""
        lines = []

        if self.sbatch:
            for line in self.sbatch:
                lines.append(f"#SBATCH {line}")

            lines += [f"#SBATCH --job-name={self.name}"]
            lines += [f"#SBATCH --output={self.name}.out"]
            lines += [f"#SBATCH --error={self.name}.err"]

        if self.bsub:
            for line in self.bsub:
                lines.append(f"#BSUB {line}")

            lines += [f"#BSUB -J {self.name}"]
            lines += [f"#BSUB -o {self.name}.out"]
            lines += [f"#BSUB -e {self.name}.err"]

        if self.pbs:
            for line in self.pbs:
                lines.append(f"#PBS {line}")
            lines.append(f"#PBS -N {self.name}")
            lines.append(f"#PBS -o {self.name}.o")
            lines.append(f"#PBS -e {self.name}.e")

        burst_buffer = self._get_burst_buffer(self.burstbuffer)
        data_warp = self._get_data_warp(self.datawarp)
        if burst_buffer:
            lines += burst_buffer
        if data_warp:
            lines += data_warp
        return lines

    def _get_burst_buffer(self, burstbuffer):
        """Get Burst Buffer directives (**#BB**) lines specified by ``BB`` property

        Args:
            burstbuffer (str): Burst Buffer configuration specified by ``BB`` property in buildspec

        Returns:
            list: List of string values containing containing ``#BB`` directives written in test
        """

        if not burstbuffer:
            return

        lines = []
        lines.append("####### START OF BURST BUFFER DIRECTIVES #######")
        for arg in burstbuffer:
            lines += [f"#BB {arg} "]

        lines.append("####### END OF BURST BUFFER DIRECTIVES   #######")
        return lines

    def _get_data_warp(self, datawarp):
        """Get Cray Data Warp directives (**#DW**) lines specified by ``DW`` property.

        Args:
            datawarp (str): Data Warp configuration specified by ``DW`` property in buildspec

        Returns:
            list: List of string values containing ``#DW`` directives written in test
        """

        if not datawarp:
            return

        lines = []
        lines.append("####### START OF DATAWARP DIRECTIVES #######")
        for arg in datawarp:
            lines += [f"#DW {arg}"]

        lines.append("####### END OF DATAWARP DIRECTIVES   #######")
        return lines

    def _set_execute_perm(self, fname):
        """Set permission to 755 for a given file. The filepath must be an absolute path to file"""

        # Change permission of the file to executable
        os.chmod(
            fname,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        self.logger.debug(f"Changing permission to 755 for script: {fname}")

    def _get_environment(self, env):
        """Retrieve a list of environment variables defined in buildspec and
        return them as list with the shell equivalent command

        Args:
            env (dict): list of environment variables defined by ``env`` property in buildspec
        """

        lines = []

        # if env not defined return immediately
        if not env:
            return

        if not isinstance(env, dict):
            raise BuildTestError(f"{env} must be a dict but got type: {type(env)}")

        # bash, sh, zsh environment variable declaration is export KEY=VALUE
        if re.fullmatch("(bash|sh|zsh|/bin/bash|/bin/sh|/bin/zsh)$", self.shell.name):
            for k, v in env.items():
                lines.append(f'export {k}="{v}"')

        # tcsh, csh,  environment variable declaration is setenv KEY VALUE
        elif re.fullmatch("(tcsh|csh|/bin/tcsh|/bin/csh)$", self.shell.name):
            for k, v in env.items():
                lines.append(f'setenv {k} "{v}"')

        else:
            self.logger.warning(
                f"{self.shell.name} is not supported, skipping environment variables."
            )
            return

        return lines

    def _get_variables(self, variables):
        """Retrieve a list of  variables defined in buildspec and
        return them as list with the shell equivalent command.

        Args:
            variables (dict): list of variable defined by ``vars`` property in buildspec
        """

        lines = []

        if not variables:
            return

        if not isinstance(variables, dict):
            raise BuildTestError(
                f"{variables} must be a dict but got type:  {type(variables)}"
            )

        # bash, sh, zsh variable declaration is KEY=VALUE
        if re.fullmatch("(bash|sh|zsh|/bin/bash|/bin/sh|/bin/zsh)$", self.shell.name):
            for k, v in variables.items():
                if v:
                    lines.append(f'{k}="{v}"')
                else:
                    lines.append(f"{k}=")

        # tcsh, csh variable declaration is set KEY=VALUE
        elif re.fullmatch("(tcsh|csh|/bin/tcsh|/bin/csh)$", self.shell.name):
            for k, v in variables.items():
                if v:
                    lines.append(f'set {k}="{v}"')
                else:
                    lines.append(f"set {k}=")

        else:
            self.logger.warning(
                f"{self.shell.name} is not supported, skipping environment variables."
            )
            return

        return lines

    def _extract_line(self, linenum, content):
        """Extract content based on the line number and return it as a string.

        Args:
            linenum (int): line number
            content (str): content to be extracted from
        """

        if linenum is None:
            return content

        lines = content.split("\n")
        # removen last line if file ends in new line character
        if lines[-1] == "":
            lines.pop()
        try:
            content = lines[linenum]
        except IndexError as e:
            content = ""
            self.logger.error(e)
        return content

    def add_metrics(self):
        """This method will update the metrics field stored in ``self.metadata['metrics']``. The ``metrics``
        property can be defined in the buildspec to assign value to a metrics name based on regular expression,
        environment or variable assignment.
        """

        if not self.metrics:
            return

        for key, metric in self.metrics.items():
            self.metadata["metrics"][key] = ""
            regex = metric.get("regex")
            file_regex = metric.get("file_regex")

            if regex:
                self.handle_regex_metric(key, regex)
            elif file_regex:
                self.handle_file_regex_metric(key, file_regex)

            self.metadata["metrics"][key] = str(self.metadata["metrics"][key])

    def handle_regex_metric(self, key, regex):
        """Handle metrics based on regular expressions."""

        stream = regex.get("stream")
        content_input = self._output if stream == "stdout" else self._error

        linenum = regex.get("linenum")
        content = self._extract_line(linenum, content_input)

        match = self.get_match(regex, content)
        if match:
            try:
                self.metadata["metrics"][key] = match.group(regex.get("item", 0))
            except IndexError:
                self.logger.error(
                    f"Unable to fetch match group: {regex.get('item', 0)} for metric: {key}."
                )

    def handle_file_regex_metric(self, key, file_regex):
        """Handle metrics based on file regular expressions."""

        fname = file_regex["file"]
        if fname:
            resolved_fname = resolve_path(fname)
            if not is_file(resolved_fname):
                msg = f"[blue]{self}[/]: Unable to resolve file path: {fname} for metric: {key}"
                self.logger.error(msg)
                console.print(msg, style="red")
                return

            linenum = file_regex.get("linenum")
            content_input = read_file(resolved_fname)
            content = self._extract_line(linenum, content_input)

            match = (
                re.search(file_regex["exp"], content, re.MULTILINE) if content else None
            )
            if match:
                try:
                    self.metadata["metrics"][key] = match.group(
                        file_regex.get("item", 0)
                    )
                except IndexError:
                    self.logger.error(
                        f"Unable to fetch match group: {file_regex.get('item', 0)} for metric: {key}."
                    )

    def get_match(self, regex, content):
        """Get the match based on the regular expression."""

        if regex.get("re") == "re.match":
            return re.match(regex["exp"], content, re.MULTILINE)
        elif regex.get("re") == "re.fullmatch":
            return re.fullmatch(regex["exp"], content, re.MULTILINE)
        else:
            return re.search(regex["exp"], content, re.MULTILINE)

    def output(self):
        """Return output content"""
        return self._output

    def error(self):
        """Return error content"""
        return self._error

    @abstractmethod
    def generate_script(self):
        """Build the testscript content implemented in each subclass"""

    def post_run_steps(self):
        """This method is called after test is complete. This method will copy files from stage directory
        such as output, error and test script. We will check state of test and mark job is complete.
        """

        # ensure we are back in stage directory before processing. For batch jobs like Slurm the
        # current working directory is changed to the submit line which can cause issues for file checks
        os.chdir(self.stage_dir)

        self._output = read_file(self.metadata["outfile"])
        self._error = read_file(self.metadata["errfile"])

        self.metadata["output"] = self._output
        self.metadata["error"] = self._error

        # copy output and error file from stage directory to top-level test directory
        shutil.copy2(
            os.path.join(self.stage_dir, os.path.basename(self.metadata["outfile"])),
            os.path.join(self.test_root, os.path.basename(self.metadata["outfile"])),
        )
        shutil.copy2(
            os.path.join(self.stage_dir, os.path.basename(self.metadata["errfile"])),
            os.path.join(self.test_root, os.path.basename(self.metadata["errfile"])),
        )

        # update outfile and errfile metadata records which show up in report file
        self.metadata["outfile"] = os.path.join(
            self.test_root, os.path.basename(self.metadata["outfile"])
        )
        self.metadata["errfile"] = os.path.join(
            self.test_root, os.path.basename(self.metadata["errfile"])
        )

        console.print(
            f"[blue]{self}[/]: Test completed in {self.metadata['result']['runtime']} seconds with returncode: {self.metadata['result']['returncode']}"
        )
        console.print(
            f"[blue]{self}[/]: Writing output file -  [green1]{self.metadata['outfile']}"
        )
        console.print(
            f"[blue]{self}[/]: Writing error file - [red3]{self.metadata['errfile']}"
        )
        self.add_metrics()
        self.check_test_state()

        # mark job is success if it finished all post run steps
        self.complete()

        self.execute_post_run_script()

    def is_valid_metric(self, name):
        if name not in list(self.metadata["metrics"].keys()):
            return False

        return True

    def check_test_state(self):
        """This method is responsible for detecting state of test (PASS/FAIL) based on returncode or regular expression."""

        self.metadata["result"]["state"] = "FAIL"

        if self.metadata["result"]["returncode"] == 0:
            self.metadata["result"]["state"] = "PASS"

        # if status is defined in Buildspec, then check for returncode and regex
        if self.status:
            # if 'state' property is specified explicitly honor this value regardless of what is calculated
            if self.status.get("state"):
                self.metadata["result"]["state"] = self.status["state"]
                return

            # Define a dictionary mapping status keys to their corresponding check functions
            status_checks = {
                "returncode": returncode_check,
                "regex": regex_check,
                "runtime": runtime_check,
                "file_regex": file_regex_check,
                "assert_ge": lambda builder: comparison_check(
                    builder=builder, comparison_type="ge"
                ),
                "assert_le": lambda builder: comparison_check(
                    builder=builder, comparison_type="le"
                ),
                "assert_gt": lambda builder: comparison_check(
                    builder=builder, comparison_type="gt"
                ),
                "assert_lt": lambda builder: comparison_check(
                    builder=builder, comparison_type="lt"
                ),
                "assert_eq": lambda builder: comparison_check(
                    builder=builder, comparison_type="eq"
                ),
                "assert_ne": lambda builder: comparison_check(
                    builder=builder, comparison_type="ne"
                ),
                "assert_range": assert_range_check,
                "contains": lambda builder: contains_check(
                    builder=builder, comparison_type="contains"
                ),
                "not_contains": lambda builder: contains_check(
                    builder=builder, comparison_type="not_contains"
                ),
                "is_symlink": is_symlink_check,
                "exists": exists_check,
                "is_dir": is_dir_check,
                "is_file": is_file_check,
                "file_count": file_count_check,
                "linecount": linecount_check,
                "file_linecount": file_linecount_check,
            }

            # Iterate over the status_checks dictionary and perform the checks
            for key, check_func in status_checks.items():
                if key in self.status:
                    self.metadata["check"][key] = check_func(self)

            # filter out any None values from status check
            status_checks = [
                value for value in self.metadata["check"].values() if value is not None
            ]

            state = (
                all(status_checks)
                if self.status.get("mode") in ["AND", "and"]
                else any(status_checks)
            )
            self.metadata["result"]["state"] = "PASS" if state else "FAIL"

    def _process_compiler_config(self):
        """This method is responsible for setting cc, fc, cxx class variables based
        on compiler selection. The order of precedence is ``config``, ``default``,
        then buildtest setting. Compiler settings in 'config' takes highest precedence,
        this overrides any configuration in 'default'. Finally we resort to compiler
        configuration in buildtest setting if none defined. This method is responsible
        for setting cc, fc, cxx, cflags, cxxflags, fflags, ldflags, and cppflags.
        """
        bc = BuildtestCompilers(configuration=self.configuration)

        self.compiler_group = bc.compiler_name_to_group[self.compiler]
        self.logger.debug(
            f"[{self.name}]: compiler: {self.compiler} belongs to compiler group: {self.compiler_group}"
        )

        # compiler from buildtest settings
        self.bc_compiler = self.configuration.target_config["compilers"]["compiler"][
            self.compiler_group
        ][self.compiler]

        self.logger.debug(self.bc_compiler)
        # set compiler values based on 'default' property in buildspec. This can override
        # compiler setting defined in configuration file. If default is not set we load from buildtest settings for appropriate compiler.

        # set compiler variables to ones defined in buildtest configuration
        self.cc = self.bc_compiler["cc"]
        self.cxx = self.bc_compiler["cxx"]
        self.fc = self.bc_compiler["fc"]

        self.logger.debug(
            f"[{self.name}]: Compiler setting for {self.compiler} from configuration file"
        )
        self.logger.debug(
            f"[{self.name}]: {self.compiler}: {json.dumps(self.bc_compiler, indent=2)}"
        )

        # if default compiler setting provided in buildspec let's assign it.
        if deep_get(self.compiler_section, "default", self.compiler_group):
            self.cc = (
                self.compiler_section["default"][self.compiler_group].get("cc")
                or self.cc
            )
            self.fc = (
                self.compiler_section["default"][self.compiler_group].get("fc")
                or self.fc
            )
            self.cxx = (
                self.compiler_section["default"][self.compiler_group].get("cxx")
                or self.cxx
            )

            self.cflags = (
                self.compiler_section["default"][self.compiler_group].get("cflags")
                or self.cflags
            )
            self.cxxflags = (
                self.compiler_section["default"][self.compiler_group].get("cxxflags")
                or self.cxxflags
            )
            self.fflags = (
                self.compiler_section["default"][self.compiler_group].get("fflags")
                or self.fflags
            )
            self.ldflags = (
                self.compiler_section["default"][self.compiler_group].get("ldflags")
                or self.ldflags
            )
            self.cppflags = (
                self.compiler_section["default"][self.compiler_group].get("cppflags")
                or self.cppflags
            )
        # if compiler instance defined in config section read from buildspec. This overrides default section if specified
        if deep_get(self.compiler_section, "config", self.compiler):
            self.logger.debug(
                f"[{self.name}]: Detected compiler: {self.compiler} in 'config' scope overriding default compiler group setting for: {self.compiler_group}"
            )

            self.cc = (
                self.compiler_section["config"][self.compiler].get("cc") or self.cc
            )
            self.fc = (
                self.compiler_section["config"][self.compiler].get("fc") or self.fc
            )
            self.cxx = (
                self.compiler_section["config"][self.compiler].get("cxx") or self.cxx
            )
            self.cflags = (
                self.compiler_section["config"][self.compiler].get("cflags")
                or self.cflags
            )
            self.cxxflags = (
                self.compiler_section["config"][self.compiler].get("cxxflags")
                or self.cxxflags
            )
            self.fflags = (
                self.compiler_section["config"][self.compiler].get("fflags")
                or self.fflags
            )
            self.cppflags = (
                self.compiler_section["config"][self.compiler].get("cppflags")
                or self.cppflags
            )
            self.ldflags = (
                self.compiler_section["config"][self.compiler].get("ldflags")
                or self.ldflags
            )

        self.logger.debug(
            f"cc: {self.cc}, cxx: {self.cxx} fc: {self.fc} cppflags: {self.cppflags} cflags: {self.cflags} fflags: {self.fflags} ldflags: {self.ldflags}"
        )
        # this condition is a safety check before compiling code to ensure if all C, C++, Fortran compiler not set we raise error
        if not self.cc and not self.cxx and not self.fc:
            raise BuildTestError(
                "Unable to set C, C++, and Fortran compiler wrapper, please specify 'cc', 'cxx','fc' in your compiler settings in buildtest configuration or specify in buildspec file. "
            )

    def __str__(self):
        return f"{self.name}/{self.metadata['id']}"

    def __repr__(self):
        return self.__str__()
