## Examples
### sh.a()
Run a command named `a`.

### sh.redir(stdout='afile').a()
Run a command named `a` and pipe it's stdout into a file named `afile`.

### redir(stdout='afile').a().b()
Run a command named `a` and pipe it's stdout into a file named `afile`. Then 
run `a`.

### sh.var().a()
Run a command named `a` and return it's stdout as a variable.

### var().a().b()
Invalid usage. `var().a()` will return a byte string.

### pipe().a().b().end()
Run a command named `a` and pipe it's stdout of into command named `b`.

### pipe().a().b().var().end()
Run a command named `a` and pipe it's stdout of into command named `b`, and 
return `b`'s stdout as a variable

### sh.exe-with-invalid-name()
Invalid. An executable with a invalid python name can't be called like this.

### sh['exe-with-invalid-name']()
Run an exe with the name 'exe-with-invalid-name'

## builtins
#### cd
Change current working dir.
#### end
Declare end of a pipe. Read from stdout/err until the last command finishes.
#### pipe
Tell the shell to pipe the next commands together until the end command is met.
Each command is executed in a pipe, and when end is called that last one is read until it finishes.
Maybe equivalent to calling redir before each command
#### redir
Tell the shell to redirect stdin/out/err to a file, /dev/null, or a variable for the next command.
Can be used in a pipe
#### var
Tell the shell to redirect stdin/out/err to a variable.
#### which
Output the path to the exe a command is associated with.

