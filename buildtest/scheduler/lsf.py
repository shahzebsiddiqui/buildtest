import json
import logging
import time

from buildtest.scheduler.job import Job
from buildtest.utils.command import BuildTestCommand

logger = logging.getLogger(__name__)


class LSFJob(Job):
    def __init__(self, jobID, lsf_cmds):
        super().__init__(jobID)
        self.lsf_cmds = lsf_cmds

    def is_pending(self):
        """Check if Job is pending which is reported by LSF as ``PEND``. Return ``True`` if there is a match otherwise returns ``False``"""

        return self._state == "PEND"

    def is_running(self):
        """Check if Job is running which is reported by LSF as ``RUN``. Return ``True`` if there is a match otherwise returns ``False``"""

        return self._state == "RUN"

    def is_complete(self):
        """Check if Job is complete which is in ``DONE`` state. Return ``True`` if there is a match otherwise return ``False``"""

        return self._state == "DONE"

    def is_suspended(self):
        """Check if Job is in suspended state which could be in any of the following states: [``PSUSP``, ``USUSP``, ``SSUSP``].
        We return ``True`` if job is in one of the states otherwise return ``False``
        """

        return self._state in ["PSUSP", "USUSP", "SSUSP"]

    def is_failed(self):
        """Check if Job failed. We return ``True`` if job is in ``EXIT`` state otherwise return ``False``"""

        return self._state == "EXIT"

    def poll(self):
        """Given a job id we poll the LSF Job by retrieving its job state, output file, error file and exit code.
        We run the following commands to retrieve following states

        - Job State: ``bjobs -noheader -o 'stat' <JOBID>``
        - Exit Code: ``bjobs -noheader -o 'EXIT_CODE' <JOBID>'``
        """

        # get job state
        query = f"{self.lsf_cmds['bjobs']} -noheader -o 'stat' {self.jobid}"
        logger.debug(query)
        logger.debug(
            f"Extracting Job State for job: {self.jobid} by running  '{query}'"
        )
        cmd = BuildTestCommand(query)
        cmd.execute()
        job_state = cmd.get_output()
        self._state = "".join(job_state).rstrip()
        logger.debug(f"Job State: {self._state}")

        query = f"{self.lsf_cmds['bjobs']} -noheader -o 'EXIT_CODE' {self.jobid} "
        logger.debug(
            f"Extracting EXIT CODE for job: {self.jobid} by running  '{query}'"
        )
        cmd = BuildTestCommand(query)
        cmd.execute()
        output = "".join(cmd.get_output()).rstrip()

        # for 0 or negative exit code output is in form "-" otherwise set value retrieved by bjobs
        try:
            self._exitcode = int(output)
        except ValueError:
            self._exitcode = 0

        logger.debug(f"Exit Code: {self._exitcode}")

        # if job is running and the start time is not recorded then we record the start time
        if self.is_running() and not self.starttime:
            self.starttime = time.time()

    def get_output_and_error_files(self):
        """This method will extract output and error file for a given jobID by running the following commands:
        ``bjobs -noheader -o 'output_file' <JOBID>`` and ``bjobs -noheader -o 'error_file' <JOBID>``

         .. code-block:: console

             $ bjobs -noheader -o 'output_file' 70910
             hold_job.out

         .. code-block:: console

             $ bjobs -noheader -o 'error_file' 70910
             hold_job.err
        """
        # get path to output file
        query = f"{self.lsf_cmds['bjobs']} -noheader -o 'output_file' {self.jobid} "
        logger.debug(
            f"Extracting OUTPUT FILE for job: {self.jobid} by running  '{query}'"
        )
        cmd = BuildTestCommand(query)
        cmd.execute()
        self._outfile = "".join(cmd.get_output()).rstrip()
        logger.debug(f"Output File: {self._outfile}")

        # get path to error file
        query = f"{self.lsf_cmds['bjobs']} -noheader -o 'error_file' {self.jobid} "
        logger.debug(
            f"Extracting ERROR FILE for job: {self.jobid} by running  '{query}'"
        )
        cmd = BuildTestCommand(query)
        cmd.execute()
        self._errfile = "".join(cmd.get_output()).rstrip()
        logger.debug(f"Error File: {self._errfile}")

    def retrieve_jobdata(self):
        """We will gather job record at onset of job completion by running ``bjobs -o '<format1> <format2>' <jobid> -json``. T

        Shown below is the output format and we retrieve the job records defined in **RECORDS** property

        .. code-block:: console

            $ bjobs -o 'job_name stat user user_group queue proj_name pids exit_code from_host exec_host submit_time start_time finish_time nthreads exec_home exec_cwd output_file error_file' 58652 -json
            {
              "COMMAND":"bjobs",
              "JOBS":1,
              "RECORDS":[
                {
                  "JOB_NAME":"hold_job",
                  "STAT":"PSUSP",
                  "USER":"shahzebsiddiqui",
                  "USER_GROUP":"GEN014ECPCI",
                  "QUEUE":"batch",
                  "PROJ_NAME":"GEN014ECPCI",
                  "PIDS":"",
                  "EXIT_CODE":"",
                  "FROM_HOST":"login1",
                  "EXEC_HOST":"",
                  "SUBMIT_TIME":"May 28 12:45",
                  "START_TIME":"",
                  "FINISH_TIME":"",
                  "NTHREADS":"",
                  "EXEC_HOME":"",
                  "EXEC_CWD":"",
                  "OUTPUT_FILE":"hold_job.out",
                  "ERROR_FILE":"hold_job.err"
                }
              ]
            }
        """

        self.get_output_and_error_files()

        format_fields = [
            "job_name",
            "stat",
            "user",
            "user_group",
            "queue",
            "proj_name",
            "pids",
            "exit_code",
            "from_host",
            "exec_host",
            "submit_time",
            "start_time",
            "finish_time",
            "nthreads",
            "exec_home",
            "exec_cwd",
            "output_file",
            "error_file",
        ]

        query = f"{self.lsf_cmds['bjobs']} -o '{' '.join(format_fields)}' {self.jobid} -json"

        logger.debug(f"Gather LSF job: {self.jobid} data by running: {query}")
        cmd = BuildTestCommand(query)
        cmd.execute()
        out = cmd.get_output()
        out = "".join(out).rstrip()

        out = json.loads(out)

        logger.debug(json.dumps(out, indent=2))
        job_data = {}

        records = out["RECORDS"][0]
        for field, value in records.items():
            job_data[field] = value

        self._jobdata = job_data

    def cancel(self):
        """Cancel LSF Job by running ``bkill <jobid>``. This method is called if job pending time exceeds
        `maxpendtime` limit during poll stage."""

        query = f"{self.lsf_cmds['bkill']} {self.jobid}"
        logger.debug(f"Cancelling job {self.jobid} by running: {query}")
        cmd = BuildTestCommand(query)
        cmd.execute()
