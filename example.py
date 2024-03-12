#!/bin/python3
import posh
from posh import posh
from pathlib import Path
sh = posh.sh
afile = Path('afile')
if afile.exists():
    afile.unlink()


### Examples
#### sh.a()
#Run a command named `a`.
sh.true()

#### sh.redir(stdout='afile').a()
#Run a command named `a` and pipe it's stdout into a file named `afile`.
sh.redir(stdout=afile).echo('hi')
assert(afile.read_text() == 'hi\n')
v = sh.var().redir(stdin='afile').cat()
assert(v == 'hi\n')
afile.unlink()

#### redir(stdout='afile').a().b()
#Run a command named `a` and pipe it's stdout into a file named `afile`. Then 
#run `a`.
sh.redir(stdout='afile').echo('hi').rm('afile')
assert not afile.exists()

#### sh.var().a()
#Run a command named `a` and return it's stdout as a variable.
assert sh.var().echo('hi') == 'hi\n'

#### var().a().b()
#Invalid usage. `var().a()` will return a byte string.
try:
    sh.var().echo('hi').true()
    assert False
except AttributeError:
    pass

#### pipe().a().b().end()
#Run a command named `a` and pipe it's stdout of into command named `b`.
assert sh.var().pipe().echo('hi').cat().end() == 'hi\n'

#### pipe().a().b().var().end()
#Run a command named `a` and pipe it's stdout of into command named `b`, and 
#return `b`'s stdout as a variable
assert sh.pipe().echo('hi').cat().var().end() == 'hi\n'
assert sh.pipe().var().echo('hi').cat().end() == 'hi\n'
assert sh.pipe().echo('hi').var().cat().end() == 'hi\n'

#### sh.exe-with-invalid-name()
#Invalid. An executable with a invalid python name can't be called like this.
try:
    sh.curl-config
    assert False
except NameError:
    pass

#### sh['exe-with-invalid-name']()
#Run an exe with the name 'exe-with-invalid-name'
sh.null()['curl-config']()

assert sh.false().returncode == 1
assert sh.true().returncode == 0
assert sh.true() and sh.true()
assert sh.false() or sh.true()
assert not sh.false() and sh.true()

# Check if things are in path
assert not sh.asdfaes
assert sh.ls

# Test adding to path
assert not sh['example.py']
posh.add_to_path(sh, sh.cwd)
assert sh['example.py']

# Test background process
job = sh.bg().sleep(3)
assert job.status() == 'running'
assert sh.true()
job.wait()
assert job.status() == 'finished'

# Test chaining a couple things together
a = sh.var().bg().pipe().ping('-c', 10, 'localhost').grep('bytes from').end()
assert a.status() == 'running'
a.wait()
assert len(a.var().splitlines()) == 10

### builtins
##### cd
#Change current working dir.
##### end
#Declare end of a pipe. Read from stdout/err until the last command finishes.
##### pipe
#Tell the shell to pipe the next commands together until the end command is met.
#Each command is executed in a pipe, and when end is called that last one is read until it finishes.
#Maybe equivalent to calling redir before each command
##### redir
#Tell the shell to redirect stdin/out/err to a file, /dev/null, or a variable for the next command.
#Can be used in a pipe
##### var
#Tell the shell to redirect stdin/out/err to a variable.
##### which
#Output the path to the exe a command is associated with.
#
