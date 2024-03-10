#TODO Run str() on non str/byte command args
#TODO Change how files are handled so that we are opening/closing them properly
#TODO Stretch goal. Make Job generic. Make sh that can run Popen jobs as well as
#       run jobs in a process (this would allow control via ssh)
import sys
import os
import shutil
import subprocess
import enum
from typing import IO
from subprocess import Popen
from pathlib import Path
from tempfile import TemporaryFile
from functools import partial

class PoshError(Exception):
    """Error caught by Posh."""

    pass

class Files(enum.Enum):
    """Types of files."""

    PIPE = enum.auto()
    VAR = enum.auto()
    NULL = enum.auto()
    DEFAULT = enum.auto()
    STDIN = enum.auto()
    STDOUT = enum.auto()
    STDERR = enum.auto()

FileInputType = (IO | Files | str | Path)

class Job:
    """A Job is a wrapper around a Popen."""

    def __init__(self,
                 path: str | Path,
                 *args: str,
                 env: dict = dict(os.environ),
                 cwd: str | Path = ''):
        """Initialize a Job."""
        self.path = path
        self.args = args
        self.env = env
        self.proc = None
        self.cwd = cwd or env.get('PWD', '/')

        # Default files. Use stdxxx.buffer for byte buffers
        self.stdin: FileInputType = sys.stdin
        self.stdout: FileInputType = sys.stdout.buffer
        self.stderr: FileInputType = sys.stderr.buffer

        self._var_stdout = None
        self._var_stdout = None

    def _resolve_file(self, file: FileInputType) -> int | IO:
        """Translate normalized user input to what Popen expects."""
        # Assume str is a Path. Open Paths.
        if isinstance(file, (str, Path)):
            return open(file, 'ab')

        # Translate enums
        if file == Files.PIPE:
            return subprocess.PIPE
        if file == Files.NULL:
            return subprocess.DEVNULL
        if file == Files.VAR:
            return TemporaryFile()
        if file == Files.STDIN:
            return sys.stdin
        if file == Files.STDOUT:
            return sys.stdout.buffer
        if file == Files.STDERR:
            return sys.stderr.buffer
        if isinstance(file, Files):
            raise PoshError(f"{file} is not valid in a job")

        # If we are here it should already be a file
        return file

    def _resolve_files(self):
        """Resolve stdin/stdout/stderr and return values for Popen."""
        stdin = self._resolve_file(self.stdin)
        stdout = self._resolve_file(self.stdout)
        stderr = self._resolve_file(self.stderr)
        return stdin, stdout, stderr

    def _handle_opened_files(self, stdin, stdout, stderr):
        """Handle files we opened."""
        # Close files we opened just to pass to Popen
        if isinstance(self.stdin, (str, Path)):
            stdin.close()
        if isinstance(self.stdout, (str, Path)):
            stdout.close()
        if isinstance(self.stderr, (str, Path)):
            stderr.close()

        # Save files we opened to buffer a variable
        if self.stdout == Files.VAR:
            self._var_stdout = stdout
        if self.stderr == Files.VAR:
            self._var_stderr = stderr

    def start(self):
        """Start the process if it isn't running."""
        # Dont start if a proc is already running.
        status = self.status()
        if status != "unstarted" and status != "finished":
            return

        # Setup the files
        stdin, stdout, stderr = self._resolve_files()

        # Setup the command
        cmd = [str(self.path)]+list(self.args)

        # Run the process
        self.proc = Popen(
                cmd,
                cwd=self.cwd,
                env=self.env,
                stdout=stdout,
                stderr=stderr,
                stdin=stdin)

        # Close files based off paths
        self._handle_opened_files(stdin, stdout, stderr)

    def status(self):
        """Status of the job: eg. running, finished."""
        if self.proc is None:
            return 'unstarted'
        self.proc.poll()
        if self.proc.returncode is not None:
            return 'finished'
        else:
            return 'running'

    def wait(self):
        """Wait for the process to finish."""
        if self.proc and self.status != "finished":
            self.proc.communicate()

    def get_fds(self):
        """Get stdout/stderr if the proc is running."""
        if self.proc:
            return self.proc.stdout, self.proc.stderr
        else:
            return None, None

    # TODO figure out how to get partial writes
    def _read_and_close(self, file):
        # Check status before reading
        status = self.status()
        try:
            file.seek(0)
            output = file.read().decode()
        except Exception:
            output = None
        if status == 'finished':
            file.close()
        return output

    def var(self):
        """Get the output."""
        stdout = stderr = None
        if self.stdout == Files.VAR and self._var_stdout:
            stdout = self._read_and_close(self._var_stdout)
        if self.stderr == Files.VAR and self._var_stderr:
            stderr = self._read_and_close(self._var_stderr)

        if stdout is not None and stderr is not None:
            result = (stdout, stderr)
        elif stdout and stderr is None:
            result = stdout
        elif stderr and stdout is None:
            result = stderr
        else:
            result = None

        return result

class Posh:
    def __init__(self, cwd=None, env=None):
        """Initialize the shell.

        Args:
          cwd: A path to set cwd to.
          env: Dictionary of environment variables.
        """
        self.cwd = cwd or os.getcwd()
        self.env = dict(os.environ) if env is None else env
        self.returncode = 0
        self.error = ''

        # Default files
        self._stdin_default = sys.stdin
        self._stdout_default = sys.stdout.buffer
        self._stderr_default = sys.stderr.buffer

        # Files
        self._stdin = self._stdin_default
        self._stdout = self._stdout_default
        self._stderr = self._stderr_default

        # Some state
        self._pipe_stdout = False
        self._pipe_stderr = False
        self._var_stdout = False
        self._var_stderr = False
        self._bg = False

        self._last_job: Job | None = None

    def _reset_state(self):
        self._stdin = self._stdin_default
        self._stdout = self._stdout_default
        self._stderr = self._stderr_default

        self._pipe_stdout = False
        self._pipe_stderr = False
        self._var_stdout = False
        self._var_stderr = False
        self._bg = False

    def _resolve_path(self, path):
        """Resolve a path relative to the cwd."""
        path = Path(path)
        if not path.is_absolute():
            path = Path(self.cwd, path)
        return path.resolve()

    def _builtin_response(self, status, output=''):
        """Set returncode and write an error to stderr."""
        self.returncode = status
        if output:
            self.error = output

    def default_files(self,
                      stdin=sys.stdin,
                      stdout=sys.stdout.buffer,
                      stderr=sys.stderr.buffer):
        """Set the default files.

        This is useful if you are redirecting many commands to
        the same set of files
        """
        self._stdin_default = stdin
        self._stdout_default = stdout
        self._stderr_default = stderr

    def cd(self, path=None):
        """Change the shell's current working directory."""
        if not path:
            path = self.env.get('HOME', '/')
        path = self._resolve_path(path)
        if os.access(path, os.W_OK):
            self._builtin_response(0)
            self.cwd = str(path)
            self.env['PWD'] = self.cwd
        else:
            self._builtin_response(1, "No permission")
        return self

    def redir(self,
              stdin: IO | str | None=None,
              stdout=None,
              stderr=None):
        """Redirect stdin or stdout or stderr.

        DEFAULT = Set the file to the shell's default
            str = This is assumed to be a file path. If it's not,
                  that's your problem.
           Path = A path to a file.

        Args:
            stdin: One of - DEFAULT/str/Path
            stdout: One of - DEFAULT/VAR/NULL/str/Path
            stderr: One of - DEFAULT/VAR/NULL/str/Path
        """
        if stdin == Files.DEFAULT:
            self._stdin = self._stdin_default
        elif isinstance(stdin, (str, Path)):
            self._stdin = stdin

        if stdout == Files.DEFAULT:
            self._stdout = self._stdout_default
        elif stdout in [Files.VAR, Files.NULL] or \
                isinstance(stdout, (str, Path)):
            self._stdout = stdout

        if stderr == Files.DEFAULT:
            self._stderr = self._stderr_default
        elif stderr in [Files.VAR, Files.NULL] or \
                isinstance(stderr, (str, Path)):
            self._stderr = stderr
        return self

    def null(self, *args):
        """Redirect stdout or stderr to /dev/null.

        By default, both stdout and stderr are redirected.

        Args:
            *args: STDOUT and/or STDERR
        """
        redir_args = {}
        if Files.STDOUT in args or Files.STDERR not in args:
            redir_args['stdout'] = Files.NULL
        if Files.STDERR in args or Files.STDERR not in args:
            redir_args['stderr'] = Files.NULL
        return self.redir(**redir_args)

    def var(self, *args):
        """Buffer stdout/stderr so they can be parsed afterwards.
        
        When the next job completes or pipe ends, instead of
        returning the shell, the stdout/stderr will be returned
        instead. By default, only stdout is returned.

        Args:
            *args: STDOUT and/or STDERR
        """
        redir_args = {}
        if Files.STDOUT in args or Files.STDERR not in args:
            redir_args['stdout'] = Files.VAR
        if Files.STDERR in args:
            redir_args['stderr'] = Files.VAR
        return self.redir(**redir_args)

    def pipe(self, *args):
        """Pipe commands together until 'end' is called.
        
        By default, stdout is piped and stderr will use it's
        default file.
        
        Args:
            *args: STDOUT and/or STDERR
        """
        if Files.STDOUT in args or Files.STDERR not in args:
            self._pipe_stdout = True
        if Files.STDERR in args:
            self._pipe_stderr = True

        # Set _last_job to None to prevent trying to pipe job not in pipe
        self._last_job = None

        return self

    def end(self):
        """Signal the end of a pipe."""
        job = self._last_job

        self._pipe_stdout = False
        self._pipe_stderr = False

        if job is None:
            return self

        job.stdout = self._stdout
        job.stderr = self._stderr
                    
        return self._execute(job)

    def bg(self):
        self._bg = True
        return self

    def __getattr__(self, name):
        path = shutil.which(name, path=self.env.get("PATH"))
        this_shell = self
        if not path:
            # I tried setting __bool__ on a function but that didn't
            # work, so instead we define a class that we can call like
            # a function.
            class Error:
                def __call__(self, *args, **kwargs):
                    this_shell._builtin_response(1, "Couldn't find "+name)
                    return this_shell
                def __bool__(self):
                    return False
            error = Error()
            return error
        else:
            return partial(self._run, path)

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __bool__(self):
        return self.returncode == 0

    def _run(self, path, *args, **kwargs):
        #TODO catch errors
        string_args = []
        for param in args:
            if not isinstance(param, (bytes, bytearray)):
                param = str(param)
            string_args.append(param)
        job = Job(path, *string_args, env=self.env)

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
        
        # We need to reset state, including _bg, before we leave this function.
        # If we want to be able to background the process, we need to know _bg
        bg = self._bg
        
        self._reset_state()

        if bg:
            return job
        job.wait()
        self.returncode = job.proc.returncode

        self._last_job = job

        var = job.var()
        result = self if var is None else var
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

def add_to_path(sh, path, mode='append'):
    PATH = sh.env.get('PATH', '')
    if path in PATH:
        return

    if mode == 'append':
        PATH = PATH + f":{path}"
    else:
        PATH = f"{path}:" + PATH

    sh.env['PATH'] = PATH

sh = Posh()
