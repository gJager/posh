## Examples
pipe().a(args).b(args).c().end()
v = var().x(args)
v = var().pipe().a().b().end()
redir(1, 'filename').pipe().a().b().end()

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

## Interactive shell usage
python3 -i posh.py
