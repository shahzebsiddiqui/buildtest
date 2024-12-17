import json
import logging
import os
import random
import subprocess
import sys
import time

from jsonschema.exceptions import ValidationError
from rich.panel import Panel
from rich.pretty import pprint

from buildtest.buildsystem.parser import BuildspecParser
from buildtest.cli.build import discover_buildspecs
from buildtest.cli.report import Report
from buildtest.defaults import (
    BUILDSPEC_CACHE_FILE,
    BUILDSPEC_DEFAULT_PATH,
    BUILDTEST_BUILDSPEC_DIR,
    console,
)
from buildtest.exceptions import BuildspecError, BuildTestError, ExecutorError
from buildtest.executors.setup import BuildExecutor
from buildtest.utils.file import (
    create_dir,
    is_dir,
    is_file,
    load_json,
    resolve_path,
    walk_tree,
)
from buildtest.utils.print import print_file_content
from buildtest.utils.table import create_table, print_table, print_terse_format
from buildtest.utils.tools import checkColor

logger = logging.getLogger(__name__)


class BuildspecCache:
    table = {}
    filter_fields = ["type", "executor", "tags", "buildspec"]
    default_format_fields = ["name", "type", "executor", "tags", "description"]
    format_fields = default_format_fields + ["buildspec"]

    def __init__(
        self,
        configuration,
        rebuild=False,
        filterfields=None,
        formatfields=None,
        header=None,
        terse=None,
        pager=None,
        color=None,
        count=None,
        row_count=None,
        search_buildspecs=None,
    ):
        """The initializer method for BuildspecCache class is responsible for loading and finding buildspecs into buildspec cache. First we
        resolve paths to directory where buildspecs will be searched. This can be specified via ``--directory`` option on command line or one can
        specify directory paths in the configuration file. Next we build the cache that contains metadata for each buildspec that will be
        written to file. If any filter or format options are specified we check if they are valid and finally display a content of the cache
        depending on the argument.

        This method is called when using ``buildtest buildspec find`` command.

        Args:
            configuration (buildtest.config.SiteConfiguration): Instance of SiteConfiguration class that is loaded buildtest configuration.
            rebuild (bool, optional): rebuild the buildspec cache by validating all buildspecs when using ``buildtest buildspec find --rebuild``. Defaults to ``False`` if ``--rebuild`` is not specified
            filterfields (str, optional): The filter options specified via ``buildtest buildspec find --filter`` that contains list of key value pairs for filtering buildspecs
            formatfields (str, optional): The format options used for formating table. The format option is a comma separated list of format fields specified via ``buildtest buildspec find --format``
            headers (bool, optional):  Option to control whether header are printed in terse output. This argument contains value of ``buildtest buildspec find --no-header``
            terse (bool, optional): Enable terse mode when printing output. In this mode we don't print output in table format instead output is printed in parseable format. This option can be specified via ``buildtest buildspec find --terse``
            color (str, optional): An instance of a string class that selects the color to use when printing table output
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
            row_count (bool, optional): Print total number of records from the table
            search_buildspecs (list, optional): List of buildspecs to search and add into cache. This can be file or directory and this argument contains value of ``buildtest buildspec find --search``
        """

        if not is_dir(BUILDTEST_BUILDSPEC_DIR):
            create_dir(BUILDTEST_BUILDSPEC_DIR)

        self.configuration = configuration
        self.filter = filterfields
        self.format = formatfields or self.configuration.target_config[
            "buildspecs"
        ].get("format")
        self.header = header
        self.pager = (
            self.configuration.target_config.get("pager") if pager is None else pager
        )
        self.count = (
            self.configuration.target_config["buildspecs"].get("count")
            if count is None
            else count
        )
        self.row_count = row_count

        # if --search is not specified we set to empty list instead of None
        self.search = (
            search_buildspecs
            or self.configuration.target_config["buildspecs"].get("search")
            or []
        )

        # list of buildspec directories to search for .yml files
        self.paths = []

        self.buildspec_files_to_add = []

        # stores invalid buildspecs and the error messages
        self.invalid_buildspecs = {}

        self.terse = terse or self.configuration.target_config["buildspecs"].get(
            "terse"
        )
        self.color = checkColor(color)

        self.rebuild = rebuild or self.configuration.target_config["buildspecs"].get(
            "rebuild"
        )
        # if --search is specified we set rebuild to True
        if self.search:
            self.rebuild = True

        self.cache = {}

        self.build()

        self._check_filter_fields()
        self._check_format_fields()
        self.find_buildspecs()

    def get_cache(self):
        """Returns cache file as loaded dictionary"""

        return self.cache

    def load_paths(self):
        """Add all paths to search for buildspecs. We read configuration file
        and check whether we need to load buildspecs from list of directories.
        We check if directories exist, if any fail we don't add them to path.
        If no root directories are specified we load buildspecs in
        `tutorials <https://github.com/buildtesters/buildtest/tree/devel/tutorials>`_
        and `general_tests <https://github.com/buildtesters/buildtest/tree/devel/general_tests>`_ directory.
        """

        # if no directory is specified we load the default buildspec.
        if not self.search:
            self.paths += BUILDSPEC_DEFAULT_PATH

        # for every root buildspec defined in configuration or via --search option,
        # we resolve path and if path exist add to self.paths. The path must be a
        # file or directory. If it's file, we accept if it ends with .yml extension
        if self.search:
            for dirname in self.search:
                path = resolve_path(dirname, exist=False)
                if not os.path.exists(path):
                    console.print(f"[red]Path: {path} does not exist!")
                # if its a file, then we check if file ends with .yml extension
                if is_file(path):
                    if not path.endswith(".yml"):
                        console.print(
                            f"[red]{path} does not end in .yml extension, please specify a valid buildspec file"
                        )
                        continue
                    else:
                        self.buildspec_files_to_add.append(path)

                if is_dir(path):
                    self.paths.append(path)

    def build(self):
        """This method will build buildspec cache file. If user requests to
        rebuild cache we remove the file and recreate cache. If cache file
        exists, we simply load from cache
        """

        self.load_paths()

        # implements buildtest buildspec find --rebuild which removes cache file
        # before finding all buildspecs. We only remove file if file exists
        if self.rebuild and is_file(BUILDSPEC_CACHE_FILE):
            try:
                os.remove(BUILDSPEC_CACHE_FILE)

                if not self.terse:
                    print(f"Clearing cache file: {BUILDSPEC_CACHE_FILE}")

            except OSError as msg:
                raise BuildTestError(msg)

        # if cache file is not found, then we will build cache by searching
        # all buildspecs paths and traverse directory to find all .yml files

        if not is_file(BUILDSPEC_CACHE_FILE):
            self.build_cache()

        self.cache = load_json(BUILDSPEC_CACHE_FILE)

    def _discover_buildspecs(self):
        """This method retrieves buildspecs based on ``self.paths`` which is a
        list of directory paths to search. If ``--directory`` is specified
        we process each argument and recursively find all .yml files
        """

        buildspecs = []
        file_traversal_limit = self.configuration.target_config.get(
            "file_traversal_limit", 1000
        )
        print("file_traversal_limit", file_traversal_limit)

        # recursively search all .yml files in directory and add to list
        if self.paths:
            for path in self.paths:
                buildspec = walk_tree(
                    path, file_traverse_limit=file_traversal_limit, ext=".yml"
                )
                buildspecs += buildspec

        if self.buildspec_files_to_add:
            buildspecs += self.buildspec_files_to_add

        # if no buildspecs found we raise an exception and exit
        if not buildspecs:
            raise BuildTestError(
                "Unable to find any buildspecs, please specify a valid file or directory when searching for buildspec."
            )

        if not self.terse:
            print(f"Buildspec Paths: {self.paths}")

        return buildspecs

    def _write_buildspec_cache(self):
        """This method is responsible for writing buildspec cache to file"""

        with open(BUILDSPEC_CACHE_FILE, "w") as fd:
            json.dump(self.update_cache, fd, indent=2)

        if not self.terse:
            print(f"Updating buildspec cache file: {BUILDSPEC_CACHE_FILE}")

    def _validate_buildspecs(self, buildspecs):
        """Given a list of buildspec files, validate each buildspec using :class:`buildtest.buildsystem.parser.BuildspecParser`
        class and return a list of valid buildspecs. Any invalid buildspecs are added to separate list

        Args:
            buildspecs: A list of buildspec to validate
        """
        valid_buildspecs = []

        buildexecutor = BuildExecutor(self.configuration)

        with console.status("Processing buildspecs", spinner="aesthetic"):
            for buildspec in buildspecs:
                try:
                    parse = BuildspecParser(
                        buildspec, buildexecutor, executor_match=True
                    )
                # any buildspec that raises SystemExit or ValidationError imply
                # buildspec is not valid, we add this to invalid list along with
                # error message and skip to next buildspec
                except (BuildspecError, ExecutorError, ValidationError) as err:
                    if isinstance(err, BuildspecError):
                        self.invalid_buildspecs[buildspec] = {
                            "msg": err.get_exception()
                        }
                    else:
                        self.invalid_buildspecs[buildspec] = {"msg": repr(err)}

                    self.invalid_buildspecs[buildspec]["exception"] = repr(type(err))
                    continue

                valid_buildspecs.append(parse)
                time.sleep(0.05)

        return valid_buildspecs

    def get_names(self):
        """Return a list of test names found in buildspec cache. We only return test names for valid buildspecs"""

        valid_buildspecs = self.get_valid_buildspecs()

        test_names = []

        for buildspec in valid_buildspecs:
            for name in self.cache["buildspecs"][buildspec]:
                test_names.append(name)

        return test_names

    def get_random_tests(self, num_items=1):
        """Returns a list of random test names from the list of available test. The test are picked
        using `random.sample <https://docs.python.org/3/library/random.html#random.sample>`_

        Args:
            num_items (int, optional): Number of test items to retrieve
        """
        return random.sample(self.get_names(), num_items)

    def lookup_buildspec_by_name(self, name):
        """Given an input test name, return corresponding buildspec file found in the cache.

        Args:
            name (str): Name of test to query in cache

        Return:
            Return path to buildspec that contains name of test
        """
        valid_buildspecs = self.get_valid_buildspecs()

        for buildspec in valid_buildspecs:
            if name in self.cache["buildspecs"][buildspec].keys():
                return buildspec

    def build_cache(self):
        """This method will rebuild the buildspec cache file by recursively searching
        all .yml files specified by input argument ``paths`` which is a list of directory paths.
        The buildspecs are validated and cache file is updated
        """

        self.update_cache = {}
        self.update_cache["unique_tags"] = []
        self.update_cache["unique_executors"] = []
        self.update_cache["buildspecs"] = {}
        self.update_cache["executor"] = {}
        self.update_cache["tags"] = {}
        self.update_cache["maintainers"] = {}
        self.update_cache["paths"] = self.paths

        # for path in self.paths:
        #    self.update_cache[path] = {}

        buildspecs = self._discover_buildspecs()

        self.update_cache["invalids"] = {}

        # validate each buildspec and return a list of valid buildspec parsers that
        # is an instance of BuildspecParser class

        parsers = self._validate_buildspecs(buildspecs)

        if self.invalid_buildspecs:
            for buildspec in self.invalid_buildspecs.keys():
                self.update_cache["invalids"][buildspec] = self.invalid_buildspecs[
                    buildspec
                ]

        # for every parsers (valid buildspecs) we update cache to build an index
        for parser in parsers:
            recipe = parser.recipe["buildspecs"]

            # if maintainer field specified add all maintainers from buildspec to list
            if parser.recipe.get("maintainers"):
                for author in parser.recipe["maintainers"]:
                    if not self.update_cache["maintainers"].get(author):
                        self.update_cache["maintainers"][author] = []

                    self.update_cache["maintainers"][author].append(parser.buildspec)

            if not self.update_cache["buildspecs"].get(parser.buildspec):
                self.update_cache["buildspecs"][parser.buildspec] = {}

            for name in recipe.keys():
                self.update_cache["buildspecs"][parser.buildspec][name] = recipe[name]
                tags = recipe[name].get("tags")
                executor = recipe[name].get("executor")
                description = recipe[name].get("description")

                if tags:
                    # if tag is string, add to unique_tags list and associate name and description with tag name
                    if isinstance(tags, str):
                        self.update_cache["unique_tags"].append(tags)

                        if not self.update_cache["tags"].get(tags):
                            self.update_cache["tags"][tags] = {}

                        self.update_cache["tags"][tags][name] = description

                    elif isinstance(tags, list):
                        self.update_cache["unique_tags"] += tags

                        # for every tagname, build a tags to testname association
                        for tag in tags:
                            if not self.update_cache["tags"].get(tag):
                                self.update_cache["tags"][tag] = {}

                            self.update_cache["tags"][tag][name] = description

                if executor:
                    self.update_cache["unique_executors"].append(executor)

                    if not self.update_cache["executor"].get(executor):
                        self.update_cache["executor"][executor] = {}

                    self.update_cache["executor"][executor][name] = description

        self.update_cache["unique_tags"] = list(set(self.update_cache["unique_tags"]))
        self.update_cache["unique_executors"] = list(
            set(self.update_cache["unique_executors"])
        )

        self._write_buildspec_cache()

    def _check_filter_fields(self):
        """This method checks filter fields are valid. The filter fields are specified
        as ``buildtest buildspec find --filter <KEY1>=<VAL1>,<KEY2>=<VAL2>,...``

        Raises:
            BuildTestError: If there is an invalid filter field
        """

        self.executor_filter = None
        self.tags_filter = None
        self.type_filter = None

        if self.filter:
            filter_error = False
            # check if filter keys are accepted filter fields, if not we raise error
            for key in self.filter.keys():
                if key not in self.filter_fields:
                    print(f"Invalid filter key: {key}")
                    filter_error = True

            # raise error if any filter field is invalid
            if filter_error:
                raise BuildTestError(f"Invalid filter fields format {self.filter}")

            self.executor_filter = self.filter.get("executor")
            self.tags_filter = self.filter.get("tags")
            self.type_filter = self.filter.get("type")

    def _check_format_fields(self):
        """This method will check if all format fields are valid. Format fields
        are passed as comma separated fields: ``--format field1,field2,field3,...``

        Raises:
            BuildTestError: If there is an invalid format field
        """

        for field in self.default_format_fields:
            self.table[field] = []

        if self.format:
            format_error = False
            for key in self.format.split(","):
                if key not in self.format_fields:
                    print(f"Invalid format field: {key}")
                    format_error = True

                if format_error:
                    raise BuildTestError(f"Invalid format fields format {self.format}")

            # if --format option specified we setup cache dictionary based on format
            # fields that are added to list
            self.table = {}
            for field in self.format.split(","):
                self.table[field] = []

    def _filter_buildspecs(self, executor, tags, schema_type):
        """This method will return a boolean True/False that determines if
        buildspec test entry is skipped as part of filter process. The filter
        are done based on executor, tags, type field. ``True`` indicates test
        needs to be skipped.

        Args:
            executor (str): ``executor`` property in buildspec
            tags (list): `List of tagnames specified via `tags`` property in buildspec
            schema_type (str): ``type`` property in buildspec

        Returns:
            bool: Return True if there is **no** match otherwise returns False
        """

        # skip all entries that dont match filtered executor
        if self.executor_filter and self.executor_filter != executor:
            return True

        # if skip all entries that dont match filtered tag. We only search if --filter tag=value is set
        if self.tags_filter:
            # if tags is not set in buildspec cache we default to empty list which and this condition should always be true
            if self.tags_filter not in tags:
                return True

        if self.type_filter and self.type_filter != schema_type:
            return True

        return False

    def find_buildspecs(self):
        """This method will find buildspecs based on cache content. We skip any
        tests based on executor filter, tag filter or type filter and build
        a table of tests that will be printed using ``print_buildspecs`` method.

        Raises:
            BuildTestError: Raises exception if input buildspec for ``buildtest buildspec find --filter buildspec`` is invalid path or directory or buildspec not found in cache.
        """

        # by default we process all buildspecs
        filtered_buildspecs = self.cache["buildspecs"].keys()

        # handle logic for filtering tests by buildspec file.
        if self.filter:
            if self.filter.get("buildspec"):
                buildspec = resolve_path(self.filter["buildspec"])

                # raise exception if there is an issue resolving path
                if not buildspec:
                    raise BuildTestError(
                        f"Invalid file for filtered buildspec: {self.filter['buildspec']}"
                    )

                # if user specified a directory path we raise an exception
                if is_dir(buildspec):
                    raise BuildTestError(
                        f"{buildspec} must be a file not a directory path."
                    )

                # if user specified buildspec not found in buildspec cache we raise error
                if not buildspec in filtered_buildspecs:
                    raise BuildTestError(
                        f"{buildspec} is not found in buildspec cache. "
                    )

                filtered_buildspecs = [buildspec]

        for buildspecfile in filtered_buildspecs:
            for test in self.cache["buildspecs"][buildspecfile].keys():
                test_recipe = self.cache["buildspecs"][buildspecfile][test]
                schema_type = test_recipe.get("type")
                executor = test_recipe.get("executor")
                # if tags not defined in cache we set to empty list for comparison with tag_filter
                tags = test_recipe.get("tags") or []
                description = test_recipe.get("description")

                # convert tags to string if its a list for printing purposes
                if isinstance(tags, list):
                    tags = " ".join(tags)

                # filters buildspecs by executor, tags, type field. The return
                # is a boolean, if its True we skip the test
                if self._filter_buildspecs(executor, tags, schema_type):
                    continue

                if self.format:
                    for field in self.table.keys():
                        if field == "type":
                            self.table[field].append(schema_type)

                        elif field == "buildspec":
                            self.table[field].append(buildspecfile)
                        elif field == "name":
                            self.table[field].append(test)

                        # tags field must be stored as string for printing purposes
                        elif field == "tags":
                            self.table[field].append(tags)
                        else:
                            self.table[field].append(test_recipe.get(field))

                else:
                    self.table["name"].append(test)
                    self.table["type"].append(schema_type)
                    self.table["executor"].append(executor)
                    self.table["tags"].append(tags)
                    self.table["description"].append(description)

    def get_valid_buildspecs(self):
        """Return a list of valid buildspecs"""
        return list(self.cache["buildspecs"].keys())

    def get_invalid_buildspecs(self):
        """Return a list of invalid buildspecs"""
        return list(self.cache["invalids"].keys())

    def get_unique_tags(self):
        """Return a list of unique tags."""
        return list(self.cache["unique_tags"])

    def get_unique_executors(self):
        """Return a list of unique executors."""
        return list(self.cache["unique_executors"])

    def get_maintainers(self):
        """Return a list of maintainers."""
        return list(self.cache["maintainers"].keys())

    def get_paths(self):
        """Return a list of search paths"""
        return self.paths

    def tag_breakdown(self):
        """This method will return a breakdown of tags by test names."""
        tag_summary = []
        for tagname in self.cache["tags"].keys():
            tag_summary.append([tagname, str(len(self.cache["tags"][tagname].keys()))])

        return tag_summary

    def executor_breakdown(self):
        """This method will return a dictionary with breakdown of executors by test names."""
        executor_summary = []
        for executor in self.cache["executor"].keys():
            executor_summary.append(
                [executor, str(len(self.cache["executor"][executor].keys()))]
            )

        return executor_summary

    def test_breakdown_by_buildspec(self):
        """This method will return a dictionary with breakdown of buildspecs by test names."""

        buildspec_summary = []
        for name in self.cache["buildspecs"].keys():
            buildspec_summary.append(
                name, str(len(self.cache["buildspecs"][name].keys()))
            )

        return buildspec_summary

    def print_buildspecfiles(self, terse=None, header=None, row_count=None, count=None):
        """This method implements ``buildtest buildspec find --buildspec`` which reports all buildspec files in cache.

        Args:
            terse (bool, optional): This argument will print output in terse format if ``--terse`` option is specified otherwise will print output in table format
            header (bool, optional): This argument controls whether header will be printed in terse format. If ``--terse`` option is not specified this argument has no effect. This argument holds the value of ``--no-header`` option
            row_count (bool, optional): Print total number of records from the table
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
        """

        self.terse = terse if terse is not None else self.terse
        self.header = header if header is not None else self.header
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        display_buildspecs = self.get_valid_buildspecs()[: self.count]

        if self.count < 0:
            display_buildspecs = self.get_valid_buildspecs()

        data = []
        for idx, buildspec in enumerate(display_buildspecs):
            if count and idx == count:
                break
            data.append([buildspec])

        if terse:
            print_terse_format(
                data,
                headers=["Buildspecs"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        table = create_table(
            columns=["Buildspecs"],
            data=data,
            title="List of Buildspecs",
            column_style=self.color,
        )
        print_table(table, row_count=row_count, pager=self.pager)

    def print_tags(self, row_count=None, count=None, terse=None, header=None):
        """This method implements ``buildtest buildspec find --tags`` which
        reports a list of unique tags from all buildspecs in cache file.

        Args:
            row_count (bool, optional): Print total number of records from the table
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
            terse (bool, optional): This argument will print output in terse format if ``--terse`` option is specified otherwise will print output in table format
            header (bool, optional): This argument controls whether header will be printed in terse format. If ``--terse`` option is not specified this argument has no effect. This argument holds the value of ``--no-header`` option
        """
        self.terse = terse if terse is not None else self.terse
        self.header = header if header is not None else self.header
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        # slice list to only display number of tags specified by --count option
        display_tags = self.get_unique_tags()[: self.count]
        # if --count is negative we show the entire list
        if self.count < 0:
            display_tags = self.get_unique_tags()

        tdata = [[tagname] for tagname in display_tags]

        # if --terse option specified print list of all tags in machine readable format
        if self.terse:
            print_terse_format(
                tdata,
                headers=["Tags"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        table = create_table(
            columns=["Tags"], data=tdata, title="List of Tags", column_style=self.color
        )
        print_table(table, row_count=row_count, pager=self.pager)

    def print_executors(self, row_count=None, count=None, terse=None, header=None):
        """This method implements ``buildtest buildspec find --executors`` which reports all executors from cache.

        Args:
            row_count (bool, optional): Print total number of records from the table
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
            terse (bool, optional): This argument will print output in terse format if ``--terse`` option is specified otherwise will print output in table format
            header (bool, optional): This argument controls whether header will be printed in terse format. If ``--terse`` option is not specified this argument has no effect. This argument holds the value of ``--no-header`` option\
        """
        self.terse = terse if terse is not None else self.terse
        self.header = header if header is not None else self.header
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        display_executors = self.get_unique_executors()[: self.count]
        if self.count < 0:
            display_executors = self.get_unique_executors()

        data = [[executor] for executor in display_executors]

        if self.terse:
            print_terse_format(
                data,
                headers=["Executors"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        table = create_table(
            columns=["Executors"],
            data=data,
            title="List of Executors",
            column_style=self.color,
        )
        print_table(table, row_count=row_count, pager=self.pager)

    def print_by_executors(self, row_count=None, count=None, terse=None, header=None):
        """This method prints executors by tests and implements ``buildtest buildspec find --group-by-executor`` command

        Args:
            row_count (bool, optional): Print total number of records from the table
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
            terse (bool, optional): This argument will print output in terse format if ``--terse`` option is specified otherwise will print output in table format
            header (bool, optional): This argument controls whether header will be printed in terse format. If ``--terse`` option is not specified this argument has no effect. This argument holds the value of ``--no-header`` option
        """
        self.terse = terse if terse is not None else self.terse
        self.header = header if header is not None else self.header
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        data = []
        print_count = 0
        for executor_name in self.cache["executor"].keys():
            for test_name, description in self.cache["executor"][executor_name].items():
                if print_count == self.count:
                    break
                data.append([executor_name, test_name, description])
                print_count += 1

        if self.terse:
            print_terse_format(
                data,
                headers=["Executors", "Name", "Description"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        # Define the column names
        columns = ["Executors", "Name", "Description"]

        # Create and print the table
        table = create_table(
            columns=columns,
            data=data,
            title="Tests by Executors",
            column_style=self.color,
        )
        print_table(table, row_count=row_count, pager=self.pager)

    def print_by_tags(self, count=None, row_count=None, terse=None, header=None):
        """This method prints tags by tests and implements ``buildtest buildspec find --group-by-tags`` command
        Args:
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
            row_count (bool, optional): Print total number of records from the table
            terse (bool, optional): This argument will print output in terse format if ``--terse`` option is specified otherwise will print output in table format
            header (bool, optional): This argument controls whether header will be printed in terse format. If ``--terse`` option is not specified this argument has no effect. This argument holds the value of ``--no-header`` option
        """
        self.terse = terse if terse is not None else self.terse
        self.header = header if header is not None else self.header
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        data = []
        print_count = 0
        for tagname in self.cache["tags"].keys():
            for test_name, description in self.cache["tags"][tagname].items():
                if print_count == self.count:
                    break
                data.append([tagname, test_name, description])
                print_count += 1

        if self.terse:
            print_terse_format(
                data,
                headers=["Tags", "Name", "Description"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        columns = ["Tags", "Name", "Description"]
        # Create and print the table
        table = create_table(
            columns=columns,
            data=data,
            title="Tests by Executors",
            column_style=self.color,
        )
        print_table(table, row_count=row_count, pager=self.pager)

    def print_buildspecs(
        self, terse=None, header=None, quiet=None, row_count=None, count=None
    ):
        """Print buildspec table. This method is typically called when running ``buildtest buildspec find`` or options
        with ``--filter`` and ``--format``.

        Args:
            terse (bool, optional): This argument will print output in terse format if ``--terse`` option is specified otherwise will print output in table format
            header (bool, optional): This argument controls whether header will be printed in terse format. If ``--terse`` option is not specified this argument has no effect. This argument holds the value of ``--no-header`` option
            quiet (bool, optional): If this option is set we return immediately and don't anything. This is specified via ``buildtest buildspec find --quiet`` which can be useful when rebuilding cache without displaying output
            row_count (bool, optional): Print total number of records from the table
            count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec find --count``
        """

        # Don't print anything if --quiet is set
        if quiet and self.rebuild:
            return

        self.terse = terse if terse is not None else self.terse
        self.header = header if header is not None else self.header
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        join_list = []
        for key in self.table.keys():
            join_list.append(self.table[key])

        raw_data = [list(i) for i in zip(*join_list)]

        # display_data is the final data to display in table. If --count is specified we reduce the list to length of self.count
        display_data = raw_data[: self.count]
        # if --count is negative we show the entire list
        if self.count < 0:
            display_data = raw_data

        if self.terse:
            print_terse_format(
                display_data,
                headers=self.table.keys(),
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        table = create_table(
            columns=self.table.keys(),
            data=display_data,
            title=f"Buildspec Cache: {BUILDSPEC_CACHE_FILE}",
            column_style=self.color,
        )
        print_table(table, row_count=row_count, pager=self.pager)

    def list_maintainers(self):
        """Return a list of maintainers"""
        maintainers = [
            [name, str(len(value))] for name, value in self.cache["maintainers"].items()
        ]

        return maintainers

    def print_maintainer(self, row_count=None, terse=None, pager=None, count=None):
        """This method prints maintainers from buildspec cache file which implements ``buildtest buildspec maintainers`` command."""
        terse = terse or self.terse

        self.terse = terse if terse is not None else self.terse
        self.row_count = row_count if row_count is not None else self.row_count
        self.count = count if count is not None else self.count

        tdata = [[maintainer] for maintainer in self.get_maintainers()]
        if count:
            tdata = tdata[:count]

        if self.terse:
            print_terse_format(
                tdata,
                headers=["Maintainers"],
                color=self.color,
                display_header=self.header,
                pager=pager,
            )
            return

        table = create_table(
            columns=["Maintainers"],
            data=tdata,
            title="List of Maintainers",
            column_style=self.color,
        )
        print_table(table, row_count=self.row_count, pager=pager)

    def print_maintainers_find(self, name):
        """Display a list of buildspec files associated to a given maintainer. This command is used when running
        ``buildtest buildspec maintainers find``

        Args:
            name (str): Name of maintainer specified via ``buildtest buildspec maintainers find <name>``
        """

        maintainers = list(self.cache["maintainers"].keys())
        if name in maintainers:
            for file in self.cache["maintainers"][name]:
                console.print(file)

    def print_maintainers_by_buildspecs(self):
        """This method prints maintainers breakdown by buildspecs. This method implements ``buildtest buildspec maintainers --breakdown``."""

        tdata = []
        for maintainer, buildspecs in self.cache["maintainers"].items():
            tdata.append([maintainer, ":".join(buildspecs)])

        if self.terse:
            print_terse_format(
                tdata,
                headers=["Buildspecs"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            return

        table = create_table(
            columns=["Maintainers", "Buildspecs"],
            data=tdata,
            title="List of Maintainers",
            column_style=self.color,
        )
        print(self.pager)
        print_table(table, pager=self.pager)

    def print_invalid_buildspecs(self, error=None, terse=None, row_count=None):
        """Print invalid buildspecs from cache file. This method implements command ``buildtest buildspec find invalid``

        Args:
            error (bool, optional): Display error messages for invalid buildspecs. Default is ``False`` where we only print list of invalid buildspecs
            terse (bool, optional): Display output in machine readable format.
            row_count (bool, optional): Display row count of invalid buildspces table
        """

        terse = terse or self.terse

        tdata = self.get_invalid_buildspecs()

        if error and terse:
            console.print(
                "[red]The --terse flag can not be used with the --error option"
            )
            sys.exit(1)

        if not tdata:
            console.print(
                "[green]Unable to find any invalid buildspecs in cache. All buildspecs are valid!"
            )
            return

        if row_count:
            print(len(tdata))
            sys.exit(1)

        # implementation for machine readable format specified via --terse
        if terse:
            tdata = [[buildspec] for buildspec in tdata]
            print_terse_format(
                tdata,
                headers=["Buildspecs"],
                color=self.color,
                display_header=self.header,
                pager=self.pager,
            )
            # will raise exit 1 to indicate error if there is any invalid buildspec which can be useful for scripting
            sys.exit(1)

        # if --error is specified print list of invalid buildspecs in rich table
        if error:
            # implementation for --error which displays buildspec file and exception message
            for buildspec, exc in self.cache["invalids"].items():
                console.rule(buildspec)
                pprint(exc)
            sys.exit(1)

        # default is to print as table
        tdata = []
        for buildspec, exc in self.cache["invalids"].items():
            tdata.append([buildspec, exc["exception"]])
        table = create_table(
            columns=["Buildspecs", "Exception"],
            data=tdata,
            title="Invalid Buildspecs",
            column_style=self.color,
        )
        print_table(table, row_count=row_count, pager=self.pager)
        sys.exit(1)

    def print_filter_fields(self):
        """This method prints filter fields available for buildspec cache. This
        method implements command ``buildtest buildspec find --helpfilter``
        """

        tdata = [
            ["buildspecs", "Filter tests by buildspec", "FILE"],
            ["executor", "Filter by executor name", "STRING"],
            ["tags", "Filter by tag name", "STRING"],
            ["type", "Filter by schema type", "STRING"],
        ]
        table = create_table(
            title="Filter Field Description",
            header_style="blue",
            column_style=self.color,
            columns=["Field", "Type", "Description"],
            data=tdata,
            show_lines=True,
        )

        print_table(table)

    def print_format_fields(self):
        """This method prints format fields available for buildspec cache. This
        method implements command ``buildtest buildspec find --helpformat``
        """
        tdata = [
            ["buildspec", "Display name of buildspec file"],
            ["description", "Show description of test"],
            ["executor", "Display 'executor' property in test"],
            ["name", "Display name of test"],
            ["tags", "Display 'tag' property in test "],
            ["type", "Display 'type' property in test"],
        ]

        table = create_table(
            title="Format Field Description",
            data=tdata,
            columns=["Field", "Description"],
            header_style="blue",
            column_style=self.color,
            show_lines=True,
        )

        print_table(table)

    def print_raw_filter_fields(self):
        """This method prints the raw filter fields available for buildspec cache. This
        method implements command ``buildtest buildspec find --filterfields``
        """
        for field in self.filter_fields:
            console.print(field, style=self.color)

    def print_raw_format_fields(self):
        """This method prints the raw format fields available for buildspec cache. This
        method implements command ``buildtest buildspec find --formatfields``
        """
        for field in self.format_fields:
            console.print(field, style=self.color)

    def print_paths(self):
        """This method print buildspec paths, this implements command ``buildtest buildspec find --paths``"""
        for path in self.paths:
            console.print(path)


def edit_buildspec_test(test_names, configuration, editor):
    """Open a list of test names in editor mode defined by ``EDITOR`` environment otherwise resort to ``vim``.
    This method will search for buildspec cache and find path to buildspec file corresponding to test name and open
    file in editor. If multiple test are specified via ``buildtest buildspec edit-test`` then each file will be open and
    upon closing file, the next file will be open for edit until all files are written.

    Args:
        test_names (list): A list of test names to open in editor
        configuration (buildtest.config.SiteConfiguration): An instance of SiteConfiguration class
        editor (str): Path to editor to use when opening file
    """
    cache = BuildspecCache(configuration=configuration)

    for name in test_names:
        if name not in cache.get_names():
            print(f"Invalid test name: {name}")
            continue

        buildspec = cache.lookup_buildspec_by_name(name)
        open_buildspec_in_editor(buildspec, editor)
        validate_buildspec(buildspec, configuration)


def edit_buildspec_file(buildspecs, configuration, editor):
    """Open buildspec in editor and validate buildspec with parser. This method is invoked by command ``buildtest buildspec edit-file``.

    Args:
        buildspec (str): Path to buildspec file to edit
        configuration (buildtest.config.SiteConfiguration): An instance of SiteConfiguration class
        editor (str): Path to editor to use when opening file
    """
    for file in buildspecs:
        buildspec = resolve_path(file, exist=False)
        if is_dir(buildspec):
            console.print(
                f"buildspec: {buildspec} is a directory, please specify a file type"
            )
            continue

        open_buildspec_in_editor(buildspec, editor)
        validate_buildspec(buildspec, configuration)


def is_test_name_in_cache(test_name, cache):
    """Check if a test name is in the cache.

    Args:
        test_name (str): The test name to check.
        cache (BuildspecCache): An instance of BuildspecCache used for storing the buildspec cache

    Returns:
        bool: True if the test name is in the cache, False otherwise.
    """
    return test_name in cache.get_names()


def show_buildspecs(test_names, configuration, theme=None):
    """This is the entry point for ``buildtest buildspec show`` command which will print content of
    buildspec based on name of test.

    Args:
        test_names (list): List of test names to show content of file
        configuration (buildtest.config.SiteConfiguration): Instance of SiteConfiguration class
        theme (str, optional): Color theme to choose. This is the Pygments style (https://pygments.org/docs/styles/#getting-a-list-of-available-styles) which is specified by ``--theme`` option
    """
    cache = BuildspecCache(configuration=configuration)
    theme = theme or "monokai"

    error_msg = []
    visited = set()
    for name in test_names:
        if not is_test_name_in_cache(name, cache):
            error_msg.append(f"Invalid test name: {name}")
            continue

        buildspec = cache.lookup_buildspec_by_name(name)
        if buildspec not in visited:
            print_file_content(
                file_path=buildspec, title=buildspec, lexer="yaml", theme=theme
            )
            visited.add(buildspec)

    if error_msg:
        for line in error_msg:
            console.print(line, style="bold red")


def show_tests_by_status(
    configuration, status, test_names=None, report_file=None, theme=None
):
    """This method which will print content of
    buildspec given test names for a desired status. The ``status`` argument can be **FAIL** or **PASS**
    which will be used to search in report file and extract test names based on status and then determine
    the corresponding buildspec that generated the test.

    Args:
        configuration (buildtest.config.SiteConfiguration): Instance of SiteConfiguration class
        status (str): Status of the tests to show ('FAIL' or 'PASS').
        test_names (list, optional): List of test names to show content of file
        report_file (str, optional): Full path to report file to read
        theme (str, optional): Color theme to choose. This is the Pygments style (https://pygments.org/docs/styles/#getting-a-list-of-available-styles) which is specified by ``--theme`` option
    """
    results = Report(report_file=report_file, configuration=configuration)
    all_tests = results.get_test_by_state(state=status)

    if test_names:
        for test_name in test_names:
            if test_name not in all_tests:
                console.print(
                    f"[red]{test_name} is not in one of the following {status} test: {all_tests}"
                )
        tests = test_names
    else:
        tests = all_tests
    show_buildspecs(tests, configuration, theme)


def show_failed_buildspecs(
    configuration, test_names=None, report_file=None, theme=None
):
    """This is the entry point for ``buildtest buildspec show-fail`` command which will print content of
    buildspec on name of all failed tests if a list of test names are not specified

    Args:
        configuration (buildtest.config.SiteConfiguration): Instance of SiteConfiguration class
        test_names (list, optional): List of test names to show content of file
        report_file (str, optional): Full path to report file to read
        theme (str, optional): Color theme to choose. This is the Pygments style (https://pygments.org/docs/styles/#getting-a-list-of-available-styles) which is specified by ``--theme`` option
    """
    show_tests_by_status(configuration, "FAIL", test_names, report_file, theme)


def handle_exception(buildspec, exception):
    """Handle exceptions during buildspec validation."""
    console.rule(buildspec)
    if isinstance(exception, BuildspecError):
        print(exception.get_exception())
    else:
        print(exception)
    print("\n")


def buildspec_validate_command(
    configuration,
    buildspecs=None,
    excluded_buildspecs=None,
    tags=None,
    executors=None,
    name=None,
):
    """Entry point for ``buildtest buildspec validate``. This method is responsible for discovering buildspec
    with same options used for building buildspecs that includes ``--buildspec``, ``--exclude``, ``--tag``, and
    ``--executor``. Upon discovery we pass each buildspec to ``BuildspecParser`` class to validate buildspec and
    report any errors during validation which is raised as exceptions.

    Args:
        configuration (buildtest.config.SiteConfiguration): An instance of SiteConfiguration class which is the loaded buildtest configuration used for validating the buildspecs.
        buildspecs (list, optional): List of paths to buildspec file which can be a file or directory. This option is specified via ``buildtest buildspec validate --buildspec``
        excluded_buildspecs (list, optional): List of excluded buildspecs which can be a file or directory. This option is specified via ``buildtest buildspec validate --exclude``
        tags (list, optional): List of tag names to search for buildspec to validate. This option is specified via ``buildtest buildspec validate --tag``
        executors (list, optional): List of executor names to search for buildspecs to validate. This option is specified via ``buildtest buildspec validate --executor``
        name (str, optional): Name of test to validate. This option is specified via ``buildtest buildspec validate --name``
    """

    buildspecs_dict = discover_buildspecs(
        buildspecs=buildspecs,
        exclude_buildspecs=excluded_buildspecs,
        tags=tags,
        executors=executors,
        name=name,
        site_config=configuration,
    )
    detected_buildspecs = buildspecs_dict["detected"]

    buildexecutor = BuildExecutor(site_config=configuration)

    # counter to keep track of number of exceptions raised during buildspec validation
    exception_counter = 0
    for buildspec in detected_buildspecs:
        try:
            BuildspecParser(
                buildspec=buildspec, buildexecutor=buildexecutor, executor_match=True
            )
        except (BuildspecError, ExecutorError, ValidationError) as err:
            exception_counter += 1
            handle_exception(buildspec, err)
        else:
            console.print(f"[green]buildspec: {buildspec} is valid")

    if exception_counter > 0:
        console.print(f"[red]{exception_counter} buildspecs failed to validate")
        sys.exit(1)

    console.print("[green]All buildspecs passed validation!!!")


def summarize_buildspec_cache(pager, configuration, color=None):
    """This is a helper method used for printing output of ``buildtest buildspec summary`` with and without
    pagination

    Args:
        configuration (buildtest.config.SiteConfiguration): instance of type SiteConfiguration
        pager (bool): Boolean control output of summary with paging
        color (str, optional): An instance of str, color that the summary should be printed in
    """
    if pager:
        with console.pager():
            summary_print(configuration)
            return
    summary_print(configuration, color)


def summary_print(configuration, color=None):
    """This method will print summary of buildspec cache file. This method is the core logic
    used for showing output of command ``buildtest buildspec summary``.

    Args:
        configuration (buildtest.config.SiteConfiguration): instance of type SiteConfiguration
        color (str, optional): An instance of str, color that the summary should be printed in

    """
    cache = BuildspecCache(configuration=configuration)
    consoleColor = checkColor(color)
    msg = f"""
    [yellow]Reading Buildspec Cache File:[/yellow]  [cyan]{BUILDSPEC_CACHE_FILE}[/cyan] 
    [yellow]Total Valid Buildspecs:[/yellow]        [cyan]{len(cache.get_valid_buildspecs())}[/cyan] 
    [yellow]Total Invalid Buildspecs:[/yellow]      [cyan]{len(cache.get_invalid_buildspecs())}[/cyan] 
    [yellow]Total Unique Tags:[/yellow]             [cyan]{len(cache.get_unique_tags())}[/cyan] 
    [yellow]Total Maintainers:[/yellow]             [cyan]{len(cache.get_maintainers())}[/cyan] 
    """
    console.print(Panel.fit(msg))

    tag_table = create_table(
        title="Tag Breakdown",
        columns=["Tag", "Total"],
        data=cache.tag_breakdown(),
        column_style=consoleColor,
    )

    executor_table = create_table(
        title="Executor Breakdown",
        columns=["Executor", "Total"],
        data=cache.executor_breakdown(),
        column_style=consoleColor,
    )
    maintainer_table = create_table(
        title="Maintainers Breakdown",
        columns=["Maintainers", "Total"],
        data=cache.list_maintainers(),
        column_style=consoleColor,
    )

    tdata = [[buildspec] for buildspec in cache.get_invalid_buildspecs()]

    invalid_buildspecs_table = create_table(
        title="Invalid Buildspecs",
        columns=["Buildspecs"],
        data=tdata,
        column_style="red",
        show_lines=False,
    )

    tdata = [[buildspec] for buildspec in cache.get_valid_buildspecs()]

    valid_buildspecs_table = create_table(
        title="Valid Buildspecs",
        columns=["Buildspecs"],
        data=tdata,
        column_style="green",
        show_lines=False,
    )

    print_table(tag_table)
    print_table(executor_table)
    print_table(maintainer_table)
    print_table(valid_buildspecs_table)
    print_table(invalid_buildspecs_table)


def buildspec_maintainers(
    configuration,
    breakdown=None,
    terse=None,
    header=None,
    color=None,
    name=None,
    row_count=None,
    count=None,
    pager=None,
):
    """Entry point for ``buildtest buildspec maintainers`` command.

    Args:
        configuration (buildtest.config.SiteConfiguration): instance of type SiteConfiguration
        terse (bool, optional): Print in terse mode
        header (bool, optional): If True disable printing of headers
        color (bool, optional): Print output of table with selected color
        name (str, optional): List all buildspecs corresponding to maintainer name. This command is specified via ``buildtest buildspec maintainers find <name>``
        row_count (bool, opotional): Print row count of the maintainer table. This command is specified via ``buildtest --row-count buildspec maintainers -l``
        count (int, optional): Number of entries to display in output. This argument contains value of ``buildtest buildspec maintainers --count``
        pager (bool, optional): Enable paging of output
    """

    cache = BuildspecCache(
        configuration=configuration,
        terse=terse,
        header=header,
        color=color,
        pager=pager,
    )

    if row_count:
        print(len(cache.list_maintainers()))
        return

    if breakdown:
        cache.print_maintainers_by_buildspecs()
        return

    if name:
        cache.print_maintainers_find(name=name)
        return

    cache.print_maintainer(row_count=row_count, count=count, pager=pager)


def buildspec_find(args, configuration):
    """Entry point for ``buildtest buildspec find`` command

    Args:
        args (dict): Parsed arguments from `ArgumentParser.parse_args <https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser.parse_args>`_
        configuration (buildtest.config.SiteConfiguration): instance of type SiteConfiguration
    """

    cache = BuildspecCache(
        rebuild=args.rebuild,
        filterfields=args.filter,
        formatfields=args.format,
        search_buildspecs=args.search,
        configuration=configuration,
        header=args.no_header,
        terse=args.terse,
        pager=args.pager,
        color=args.color,
        count=args.count,
        row_count=args.row_count,
    )

    if args.buildspec_find_subcommand == "invalid":
        cache.print_invalid_buildspecs(error=args.error, row_count=args.row_count)
        return

    # buildtest buildspec find --tags
    if args.tags:
        cache.print_tags(row_count=args.row_count, count=args.count)
        return

    # buildtest buildspec find --buildspec
    if args.buildspec:
        cache.print_buildspecfiles(
            row_count=args.row_count,
            count=args.count,
            terse=args.terse,
            header=args.no_header,
        )
        return

    # buildtest buildspec find --paths
    if args.paths:
        cache.print_paths()
        return

    # buildtest buildspec find --executors
    if args.executors:
        cache.print_executors(row_count=args.row_count, count=args.count)
        return

    # buildtest buildspec find --group-by-executors
    if args.group_by_executor:
        cache.print_by_executors(row_count=args.row_count, count=args.count)
        return

    # buildtest buildspec find --group-by-tags
    if args.group_by_tags:
        cache.print_by_tags(row_count=args.row_count, count=args.count)
        return

    # buildtest buildspec find --helpfilter
    if args.helpfilter:
        cache.print_filter_fields()
        return

    # buildtest buildspec find --helpformat
    if args.helpformat:
        cache.print_format_fields()
        return

    # buildtest buildspec find --filterfields
    if args.filterfields:
        cache.print_raw_filter_fields()
        return

    # buildtest buildspec find --formatfields
    if args.formatfields:
        cache.print_raw_format_fields()
        return

    cache.print_buildspecs(quiet=args.quiet, row_count=args.row_count)


def open_buildspec_in_editor(buildspec, editor):
    """Open a buildspec in the specified editor and print a message.

    Args:
        buildspec (str): The path to the buildspec file to open.
        editor (str): The editor to open the buildspec file in.
    """

    # only used for regression testing to ensure test is not stuck for closing file
    if not editor:
        editor = "echo"  # Doesnt call the editor.

    subprocess.call([editor, buildspec])
    print(f"Writing file: {buildspec}")


def validate_buildspec(buildspec, configuration):
    """Validate a buildspec with JSON Schema and print whether it is valid or not.

    Args:
        buildspec (str): Path to buildspec file to validate
        configuration (buildtest.config.SiteConfiguration): An instance of SiteConfiguration class
    """
    be = BuildExecutor(configuration)
    try:
        BuildspecParser(buildspec, be)
        console.print(f"[green]{buildspec} is valid")
    except ValidationError:
        console.print(f"[red]{buildspec} is invalid")
