import sys
import functools
import os
import subprocess
from subprocess import Popen
from pathlib import Path
from tempfile import TemporaryFile

STDIN=-1
STDOUT=-2
STDERR=-3
PIPE=-4
VAR=-5
NULL=-6
FILE=-7


class Job:
    def __init__(self, path, *args, var=os.environ, cwd=None):
        self.path = path
        self.args = args
        self.var = var
        self.proc = None
        self.cwd = cwd or var.get('PWD', None)

        # Default files. Use stdxxx.buffer for bytes.
        self.stdin = sys.stdin
        self.stdout = sys.stdout.buffer
        self.stderr = sys.stderr.buffer

    def start(self):
        # Setup the command
        cmd = [str(self.path)]+list(self.args)

        # Run the process
        self.proc = Popen(cmd, cwd=self.cwd, env=self.var, stdout=self.stdout, stderr=self.stderr, stdin=self.stdin)

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
        if self.proc:
            self.proc.communicate()

    def get_fds(self):
        if self.proc:
            return self.proc.stdout, self.proc.stderr
        else:
            return None, None


class Command:
    """A command that can be run"""
    def __init__(self, env):
        self.env = env

    def run(self):
        pass


class BuiltinCommand(Command):
    def __init__(self, env, name, func):
        super().__init__(env)
        self.name = name
        self.func = func

    def run(self, *args, **kwargs):
        self.func(self, *args, **kwargs)


class ExecCommand(Command):
    def __init__(self, env, path):
        super().__init__(env)
        self.path = Path(path)
        self.name = self.path.name

    def run(self, *args, **kwargs):
        job = Job(self.path, *args, var=self.env.var)

        # Use the env's files
        job.stdin = self.env._stdin
        job.stdout = self.env._stdout
        job.stderr = self.env._stderr

        # Setup pipes
        piping = True
        if self.env._pipe_stdout and not self.env._pipe_stderr:
            job.stdout = subprocess.PIPE
        elif self.env._pipe_stdout and self.env._pipe_stderr:
            job.stdout = subprocess.PIPE
            job.stderr = subprocess.STDOUT
        elif self.env._pipe_stderr and not self.env._pipe_stdout:
            job.stderr = subprocess.PIPE
        else:
            piping = False

        job.start()

        jobout, joberr = job.get_fds()

        # If we are piping, pass it into the next stdin
        if self.env._pipe_stdout:
            if jobout is not None:
                self.env._stdin = jobout
            else:
                raise ValueError("I expected the job's stdout to be piped")
        elif self.env._pipe_stderr:
            if joberr is not None:
                self.env._stdin = joberr
            else:
                raise ValueError("I expected the job's stderr to be piped")

        # If we aren't piping, wait for the job to finish
        if not piping:
            job.wait()

        self.env._last_job = job


builtins = {}

def pipe(self, *args):
    if STDOUT in args or STDERR not in args:
        self.env._pipe_stdout = True
    if STDERR in args:
        self.env._pipe_stderr = True

builtins['pipe'] = pipe

def end(self):
    job = self.env._last_job
    fds = [fd for fd in job.get_fds() if fd is not None]

    while True:
        for fd in fds:
            data = fd.read()
            self.env._stdout.write(data)
        if job.status() == 'finished':
            break
                
    self.env._pipe_stdout = False
    self.env._pipe_stderr = False


builtins['end'] = end

def cd(self, path=None):
    if path is None:
        path = self.env.var.get('HOME', '/')
    path = Path(self.env.var['PWD'], path)
    if path.is_dir():
        self.env.var['PWD'] = str(path.resolve())
    else:
        self.env._stderr.write(b'No such directory: '+bytes(path)+b'\n')

builtins['cd'] = cd

def redir(self, stdin=STDIN, stdout=STDOUT, stderr=STDERR):
    if stdout == NULL:
        stdout = '/dev/null'
    if stderr == NULL:
        stderr = '/dev/null'

    if stdin == STDIN:
        self.env._stdin = sys.stdin
    elif isinstance(stdin, (str, Path)):
        path = self.env.normalize_path(stdin)
        self.env._stdin = path.open('rb')

    if stdout == STDOUT:
        self.env._stdout = sys.stdout.buffer
    elif stdout == VAR:
        self.env._stdout = TemporaryFile()
        self.env._var_stdout = True
    elif isinstance(stdout, (str, Path)):
        path = self.env.normalize_path(stdout)
        self.env._stdout = path.open('ab')

    if stderr == STDERR:
        self.env._stderr = sys.stderr.buffer
    elif stdout == VAR:
        self.env._stderr = TemporaryFile()
        self.env._var_stderr = True
    elif stderr == STDOUT:
        self.env._stderr = sys.stdout.buffer
    elif isinstance(stderr, (str, Path)):
        path = self.env.normalize_path(stderr)
        self.env._stderr = path.open('ab')

builtins['redir'] = redir

def var(self, *args):
    redir_args = {}
    if STDOUT in args or STDERR not in args:
        redir_args['stdout'] = VAR
    if STDERR in args:
        redir_args['stderr'] = VAR
    return redir(self, **redir_args)

builtins['var'] = var


class PoshEnv:
    def __init__(self, posh, var=None):
        """Create a shell env for the shell (posh). Can take env vars"""

        # Tracking things
        self.posh = posh
        self._paths = []
        self._commands = {}

        # Some state
        self._pipe_stdout = False
        self._pipe_stderr = False
        self._var_stdout = False
        self._var_stderr = False
        self._last_job = None

        # Files
        self._stdin = sys.stdin
        self._stdout = sys.stdout.buffer
        self._stderr = sys.stderr.buffer

        # Default to parent's env vars
        self.var = var or os.environ

        # Setup env variables
        self._set_default_env()

        # Load builtin commands
        self._add_builtins()

        # Load path
        for path in self.var.get('PATH', '').split(':'):
            self.add_path(path)

    def normalize_path(self, path):
        path = Path(path)
        if not path.is_absolute():
            path = Path(self.var['PWD'], path)
        return path

    def _reset_state(self):
        if self._stdin != sys.stdin:
            self._stdin.close()
        self._stdin = sys.stdin

        if self._stdout != sys.stdout.buffer:
            self._stdout.close()
        self._stdout = sys.stdout.buffer

        if self._stderr != sys.stderr.buffer:
            self._stderr.close()
        self._stderr = sys.stderr.buffer

        self._pipe_stdout = False
        self._pipe_stderr = False
        self._var_stdout = False
        self._var_stderr = False

    def _set_default_env(self):
        self.var.setdefault('PWD', '/')

    def _add_builtins(self):
        for builtin, func in builtins.items():
            self._add_command(BuiltinCommand(self, builtin, func))

    def add_path(self, path):
        path = Path(path)

        exes = []

        # Test if path is a dir
        if not path.is_dir():
            return

        # Get a list of executables in the path
        for filename in list(path.iterdir()):
            if os.access(filename, os.X_OK):
                exes.append(ExecCommand(self, filename))

        # Add the executables to the shell
        for exe in exes:
            self._add_command(exe)

        # Track which paths we have loaded
        self._paths.append(path)

        # If we are adding a path not in PATH, add it there
        if str(path) not in self.var.get('PATH', ''):
            self.var['PATH'] = self.var.get('PATH', '') + ':' + str(path)

    def _add_command(self, command):
        # Skip collisions
        if getattr(self.posh, command.name, None):
            return

        # Preload the function with the exe
        func = functools.partial(self._run_command, command)

        # Add to shell
        setattr(self.posh, command.name, func)
        #print('added ', command.name)

        # Track commands
        self._commands[command.name] = command

        # TODO add to globals here

    def remove_path(self, path):
        path = Path(path)

        # Stop tracking this path
        if path in self._paths:
            self._paths.remove(path)

        # Remove this path from PATH
        if str(path) in self.var.get('PATH', ''):
            self.var['PATH'] = self.var.get('PATH', '').replace(str(path), '').replace('::', ':')

        # Get a list of exes added from this path
        from_path = []
        for command in self._commands:
            if not isinstance(command, ExecCommand):
                continue
            if command.path.parent.samefile(path):
                from_path.append(command)


    def _remove_command(self, command):

        # Remove from shell
        if getattr(self.posh, command.name, ""):
            delattr(self.posh, command.name) 

        # TODO remove from globals

        # Stop tracking exe
        if command.name in self._commands: 
            del self._commands[command.name]


    def _run_command(self, command, *args, **kwargs):
        #TODO handle different circumstances here.
        #print('im gonna run a command now', command.name, args, kwargs)
        if self._var_stdout or self._var_stderr:
            var_out = True
        else:
            var_out = False

        command.run(*args, **kwargs)

        result = self.posh

        # We just turned on var, so don't turn it off yet
        if not var_out and self._var_stdout or self._var_stderr:
            return result

        if self._pipe_stdout or self._pipe_stderr:
            return result

        if self._var_stdout:
            self._stdout.seek(0)
            result = self._stdout.read().decode()
        if self._var_stderr:
            self._stderr.seek(0)
            result = self._stderr.read().decode()

        self._reset_state()
        return result


class Posh:
    def __init__(self, env=None):
        self.env = env or PoshEnv(self)

    def __getitem__(self, arg):
        if arg not in self.__dict__:
            raise AttributeError(f"No function named {arg}")
        return self.__dict__[arg]

sh = Posh()
