import sys
import functools
import os
import shutil
import subprocess
from subprocess import Popen
from pathlib import Path
from tempfile import TemporaryFile
from functools import partial

STDIN=-1
STDOUT=-2
STDERR=-3
PIPE=-4
VAR=-5
NULL=-6
FILE=-7


def var(job):
    """Try to read and then close stdout/stderr of a job"""
    try:
        job.stdout.seek(0)
        stdout = job.stdout.read().decode()
        job.stdout.close()
    except:
        stdout = None
    try:
        job.stderr.seek(0)
        stderr = job.stderr.read().decode()
        job.stderr.close()
    except:
        stderr = None

    if stdout is not None and stderr is not None:
        result = (stdout, stderr)
    elif stdout and stderr is None:
        result = stdout
    elif stderr and stdout is None:
        result = stderr
    else:
        result = None

    return result


class Job:
    """A Job is a wrapper around a Popen.

    You might be asking, why do we need a wrapper around Popen?
    The main reason is that I want to be able to modify the object
    before starting the process. It's also nice to be able to
    control the interface.
    """

    def __init__(self, path, *args, env=os.environ, cwd=None):
        self.path = path
        self.args = args
        self.env = env
        self.proc = None
        self.cwd = cwd or env.get('PWD', '/')

        # Default files. Use stdxxx.buffer for byte buffers
        self.stdin = sys.stdin
        self.stdout = sys.stdout.buffer
        self.stderr = sys.stderr.buffer

    def start(self):
        """Start the process ifbit isn't running"""
        # Dont start if a proc is already running.
        status = self.status()
        if status != "unstarted" and status != "finished":
            return

        # Setup the command
        cmd = [str(self.path)]+list(self.args)

        # Run the process
        self.proc = Popen(cmd, cwd=self.cwd, env=self.env, stdout=self.stdout, stderr=self.stderr, stdin=self.stdin)

    def status(self):
        """Status of the job: eg. running, finished"""
        if self.proc is None:
            return 'unstarted'
        self.proc.poll()
        if self.proc.returncode is not None:
            return 'finished'
        else:
            return 'running'

    def wait(self):
        if self.proc and self.status != "finished":
            # If this proc outputs too much this might cause issues
            self.proc.communicate()

    def get_fds(self):
        if self.proc:
            return self.proc.stdout, self.proc.stderr
        else:
            return None, None


class Posh:
    def __init__(self, cwd=None, environ=None):
        self.cwd = cwd or os.getcwd()
        self.environ = dict(os.environ) if environ is None else environ
        self.returncode = 0

        # Files
        self._stdin = sys.stdin
        self._stdout = sys.stdout.buffer
        self._stderr = sys.stderr.buffer

        # Some state
        self._pipe_stdout = False
        self._pipe_stderr = False
        self._var_stdout = False
        self._var_stderr = False
        self._last_job = None
        self._bg = False

    def _reset_state(self):
        if self._stdin != sys.stdin:
            try:
                self._stdin.close()
            except:
                pass
        self._stdin = sys.stdin

        if self._stdout != sys.stdout.buffer:
            try:
                self._stdout.close()
            except:
                pass
        self._stdout = sys.stdout.buffer

        if self._stderr != sys.stderr.buffer:
            try:
                self._stderr.close()
            except:
                pass
        self._stderr = sys.stderr.buffer

        self._pipe_stdout = False
        self._pipe_stderr = False
        self._var_stdout = False
        self._var_stderr = False
        self._bg = False

    def _resolve_path(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = Path(self.cwd, path)
        return path.resolve()

    def cd(self, path=None):
        if not path:
            path = self.environ.get('HOME', '/')
        path = self._resolve_path(path)
        if os.access(path, os.W_OK):
            self.returncode = 0
            self.cwd = str(path)
            self.environ['PWD'] = self.cwd
        else:
            self._builtin_response(1, "No permission")
        return self

    def redir(self, stdin=None, stdout=None, stderr=None):
        if stdin == STDIN:
            self._stdin = sys.stdin
        elif isinstance(stdin, (str, Path)):
            path = self._resolve_path(stdin)
            self._stdin = path.open('rb')

        if stdout == STDOUT:
            self._stdout = sys.stdout.buffer
        elif stdout == VAR:
            self._stdout = TemporaryFile()
            self._var_stdout = True
        elif stdout == NULL:
            self._stdout = subprocess.DEVNULL
        elif isinstance(stdout, (str, Path)):
            path = self._resolve_path(stdout)
            self._stdout = path.open('ab')

        if stderr == STDERR:
            self._stderr = sys.stderr.buffer
        elif stderr == VAR:
            self._stderr = TemporaryFile()
            self._var_stderr = True
        elif stderr == NULL:
            self._stderr = subprocess.DEVNULL
        elif stderr == STDOUT:
            self._stderr = sys.stdout.buffer
        elif isinstance(stderr, (str, Path)):
            path = self._resolve_path(stderr)
            self._stderr = path.open('ab')
        return self

    def null(self, *args):
        redir_args = {}
        if STDOUT in args or STDERR not in args:
            redir_args['stdout'] = NULL
        if STDERR in args or STDERR not in args:
            redir_args['stderr'] = NULL
        return self.redir(**redir_args)

    def var(self, *args):
        redir_args = {}
        if STDOUT in args or STDERR not in args:
            redir_args['stdout'] = VAR
        if STDERR in args:
            redir_args['stderr'] = VAR
        return self.redir(**redir_args)

    def pipe(self, *args):
        if STDOUT in args or STDERR not in args:
            self._pipe_stdout = True
        if STDERR in args:
            self._pipe_stderr = True
        self._last_job = None
        return self

    def end(self):
        job = self._last_job

        job.stdout = self._stdout
        job.stderr = self._stderr
                    
        self._pipe_stdout = False
        self._pipe_stderr = False

        return self._execute(job)

    def bg(self):
        self._bg = True
        return self

    def _builtin_response(self, status, output):
        self.returncode = status
        self._stderr.write(output.encode()+b'\n')
        
    def __getattr__(self, name):
        path = shutil.which(name, path=self.environ.get("PATH"))
        if not path:
            def error(*args, **kwargs):
                self._builtin_response(1, "Couldn't find "+name)
                return self
            return error
        else:
            return partial(self._run, path)

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __bool__(self):
        return self.returncode == 0

    def _run(self, path, *args, **kwargs):
        #TODO catch errors
        job = Job(path, *args, env=self.environ)

        # Use the env's files
        job.stdin = self._stdin
        job.stdout = self._stdout
        job.stderr = self._stderr

        if self._pipe_stdout or self._pipe_stderr:
            self._execute_pipe(job)
            return self
        return self._execute(job)

    def _execute(self, job):
        job.start()

        self._reset_state()

        if self._bg:
            return job
        job.wait()
        self.returncode = job.proc.returncode

        self._last_job = job

        result = var(job) or self
        return result


    def _execute_pipe(self, job):
        last_job = self._last_job
        if last_job:
            last_job.start()

            stdout, stderr = last_job.get_fds()
            if self._pipe_stdout:
                if stdout is not None:
                    job.stdin = stdout
            elif self._pipe_stderr:
                if stderr is not None:
                    job.stdin = stderr

        if self._pipe_stdout and not self._pipe_stderr:
            job.stdout = subprocess.PIPE
        elif self._pipe_stdout and self._pipe_stderr:
            job.stdout = subprocess.PIPE
            job.stderr = subprocess.STDOUT
        elif self._pipe_stderr and not self._pipe_stdout:
            job.stderr = subprocess.PIPE

        self._last_job = job
        
    
sh = Posh()
