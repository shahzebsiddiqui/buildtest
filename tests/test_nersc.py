import os
import shutil
import tempfile

import pytest

from buildtest.cli.build import BuildTest
from buildtest.cli.buildspec import BuildspecCache
from buildtest.cli.compilers import (
    BuildtestCompilers,
    compiler_find,
    compiler_test,
    remove_compilers,
)
from buildtest.config import SiteConfiguration
from buildtest.defaults import BUILDTEST_ROOT
from buildtest.system import BuildTestSystem


class TestNersc:
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.getenv("NERSC_HOST") in ["perlmutter", "muller"]:
        pytest.skip(
            "This test can only run on Perlmutter Login nodes", allow_module_level=True
        )
    settings_file = os.path.join(here, "settings", "nersc.yml")

    system = BuildTestSystem()

    bc = SiteConfiguration(settings_file)
    bc.detect_system()
    bc.validate()
    BuildspecCache(rebuild=True, configuration=bc)

    def test_slurm_hostname(self):
        if not os.getenv("NERSC_HOST") in ["perlmutter", "muller"]:
            pytest.skip(
                "This test can only run on Perlmutter Login nodes",
                allow_module_level=True,
            )

        cmd = BuildTest(
            configuration=self.bc,
            buildspecs=[
                os.path.join(
                    BUILDTEST_ROOT, "tests", "examples", "perlmutter", "hostname.yml"
                )
            ],
            poll_interval=5,
            maxpendtime=120,
            numprocs=[1, 4],
        )
        try:
            cmd.build()
        except SystemExit:
            pass

    def test_slurm_max_pend(self):
        if not os.getenv("NERSC_HOST") in ["perlmutter", "muller"]:
            pytest.skip(
                "This test can only run on Perlmutter Login nodes",
                allow_module_level=True,
            )
        cmd = BuildTest(
            configuration=self.bc,
            buildspecs=[
                os.path.join(
                    os.getenv("BUILDTEST_ROOT"),
                    "tests",
                    "examples",
                    "perlmutter",
                    "hold_job.yml",
                )
            ],
            poll_interval=5,
            maxpendtime=10,
        )
        with pytest.raises(SystemExit):
            cmd.build()

    def test_compiler_find(self):
        if not os.getenv("NERSC_HOST") in ["perlmutter", "muller"]:
            pytest.skip(
                "This test can only run on Perlmutter Login nodes",
                allow_module_level=True,
            )
        # testing buildtest config compilers find
        compilers = BuildtestCompilers(configuration=self.bc)
        compilers.find_compilers()

        # test entry point for 'buildtest config compilers find --detailed'
        compiler_find(configuration=self.bc, detailed=True)

    def test_compiler_test(self):
        if not os.getenv("NERSC_HOST") in ["perlmutter", "muller"]:
            pytest.skip(
                "This test can only run on Perlmutter Login nodes",
                allow_module_level=True,
            )
        # testing buildtest config compilers test
        compiler_test(configuration=self.bc)

    def test_compiler_find_alternative_filepath(self):
        if not os.getenv("NERSC_HOST") in ["perlmutter", "muller"]:
            pytest.skip(
                "This test can only run on Perlmutter Login nodes",
                allow_module_level=True,
            )
        # testing buildtest config compilers find
        compilers = BuildtestCompilers(configuration=self.bc)
        compilers.find_compilers()

        # test entry point for 'buildtest config compilers find --file'
        temp_path = tempfile.NamedTemporaryFile(dir=os.path.expanduser("~"))
        compiler_find(configuration=self.bc, filepath=temp_path.name)
        temp_path.close()

    def test_compiler_remove(self):
        # will create a copy of configuration file and remove one compiler from configuration. We dont want to modify the original configuration file
        tf = tempfile.NamedTemporaryFile(suffix=".yml")
        shutil.copy(self.settings_file, tf.name)

        config = SiteConfiguration(tf.name)
        config.detect_system()
        config.validate()

        compilers = BuildtestCompilers(configuration=config)
        # remove one compiler from configuration
        remove_compilers(configuration=self.bc, names=[compilers.names()[0]])
