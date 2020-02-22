"""
This module contains all the methods related to "buildtest build" which is used
for building test scripts from test configuration.
"""


import json
import os
import re
import sys

from buildtest.tools.config import config_opts
from buildtest.tools.defaults import TESTCONFIG_ROOT

from buildtest.tools.file import create_dir
from buildtest.tools.log import init_log


def func_get_subcmd(args):
    """Entry point for ``buildtest get`` sub-command. The expected
    single argument provided should be a valid repository address to clone.

    :param args: arguments passed from command line
    :type args: dict, required

    :rtype: None
    """
    if not args.repo:
        sys.exit("A repository address is required.")

    print(args.repo)
    print(config_opts)
    url = args.repo[0]

    # Currently just support for GitHub
    if not re.search("github.com", url):
        sys.exit("Currently only GitHub is supported for buildtest get.")

    logger, LOGFILE = init_log(config_opts)
    root = os.path.join(TESTCONFIG_ROOT, "github.com")
    create_dir(root)

    # Parse the repository name
    username = url.split("/")[-2]
    repo = url.split("/")[-1]
    username_path = os.path.join(root, username)
    clone_path = os.path.join(username_path, repo)
    create_dir(username_path)

    # Clone to install
    clone(url, clone_path)


def clone(url, dest):
    """clone a repository from Github"""
    name = os.path.basename(url).replace(".git", "")
    dest = os.path.join(dest, name)
    return_code = os.system("git clone %s %s" % (url, dest))
    if return_code == 0:
        return dest
    sys.exit("Error cloning repo %s" % url)
