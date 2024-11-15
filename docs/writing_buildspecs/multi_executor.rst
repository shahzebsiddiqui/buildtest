.. _multiple_executors:

Running Test Across Multiple Executors
=========================================

The `executor` property can support regular expression to search for compatible
executors, this can be used if you want to run a test across multiple executors. In buildtest,
we use `re.fullmatch <https://docs.python.org/3/library/re.html#re.fullmatch>`_ with the input
pattern defined by **executor** property against a list of available executors defined in configuration file.
You can retrieve a list of executors by running ``buildtest config executors list``.

In example below we will run this test on `generic.local.bash` and `generic.local.sh` executor based
on the regular expression.

.. literalinclude:: ../tutorials/multi_executors/executor_regex_script.yml
   :language: yaml

If we build this test, notice that there are two tests, one for each executor.

.. dropdown:: ``buildtest build -b tutorials/multi_executors/executor_regex_script.yml``

   .. command-output:: buildtest build -b tutorials/multi_executors/executor_regex_script.yml

Multiple Executors
-------------------

.. Note:: This feature is in active development

.. Note:: This feature is compatible with ``type: script`` and ``type: spack``.

The ``executors`` property can be used to define executor specific configuration
for each test, currently this field can be used with :ref:`vars <variables>`, :ref:`env <environment_variables>`
, scheduler directives: ``sbatch``, ``bsub``, ``pbs``,  and :ref:`cray burst buffer/data warp <cray_burstbuffer_datawarp>`.
The ``executors`` field is a JSON object that expects name of executor followed by property set per executor. In this next example,
we define variables ``X``, ``Y`` and environment ``SHELL`` based on executors **generic.local.sh** and **generic.local.bash**.

.. literalinclude:: ../tutorials/multi_executors/executors_var_env_declaration.yml
   :language: yaml
   :emphasize-lines: 12-23

Let's build this test.

.. dropdown:: ``buildtest build -b tutorials/multi_executors/executors_var_env_declaration.yml``

   .. command-output:: buildtest build -b tutorials/multi_executors/executors_var_env_declaration.yml

Now let's look at the generated content of the test as follows. We will see that buildtest will
set **X=1**, **Y=3** and **SHELL=bash** for ``generic.local.bash`` and **X=2**, **Y=4** and **SHELL=sh** for
``generic.local.sh``

.. dropdown:: ``buildtest inspect query -t executors_vars_env_declaration/``

   .. command-output:: buildtest inspect query -t executors_vars_env_declaration/

Scheduler Directives
----------------------

We can also define scheduler directives based on executor type, in this example we define
``sbatch`` property per executor type. Note that ``sbatch`` property in the ``executors`` section
will override the ``sbatch`` property defined in the top-level file otherwise it will use the default.


.. literalinclude:: ../tutorials/multi_executors/executor_scheduler.yml
   :language: yaml
   :emphasize-lines: 8-13

.. dropdown:: ``buildtest build -b tutorials/multi_executors/executor_scheduler.yml``

   .. command-output:: buildtest build -b tutorials/multi_executors/executor_scheduler.yml

If we inspect this test, we will see each each test have different ``#SBATCH`` directives for each test
based on the ``sbatch`` property defined in the ``executors`` field.

.. dropdown:: ``buildtest inspect query -t executors_sbatch_declaration/``

   .. command-output:: buildtest inspect query -t executors_sbatch_declaration/

Cray Burst Buffer and Data Warp
---------------------------------

You can also define ``BB`` and ``DW`` directives in the ``executors`` field to override
cray burst buffer and data warp settings per executor. buildtest will use the fields ``BB``
and ``DW`` and insert the ``#BB`` and ``#DW`` directives in the job script.

.. literalinclude:: ../tutorials/burstbuffer_datawarp_executors.yml
    :language: yaml
    :emphasize-lines: 9-18

Custom Status by Executor
--------------------------

The :ref:`status <status>` and :ref:`metrics <metrics>` field are supported in ``executors``
which can be defined within the named executor. In this next example, we will define executor ``generic.local.bash`` to
match for returncode **0** or **2** while second test will use executor ``generic.local.sh`` to match returncode of **1**.

.. literalinclude:: ../tutorials/multi_executors/status_by_executors.yml
    :language: yaml
    :emphasize-lines: 8-14

Now let's run this test and we will see the test using executor **generic.local.sh** will fail because
we have a returncode mismatch even though both tests got a 0 returncode as its actual value.

.. dropdown:: ``buildtest build -b tutorials/multi_executors/status_by_executors.yml``

   .. command-output:: buildtest build -b tutorials/multi_executors/status_by_executors.yml