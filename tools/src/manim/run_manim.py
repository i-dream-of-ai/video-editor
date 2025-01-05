import subprocess

# Launch manim with pipes for stdin/stdout/stderr
process = subprocess.Popen(
    ["uv", "run", "manim", "manim_loop.py", "-p", "--renderer=opengl"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,  # This makes it use text mode instead of bytes
)

while True:
    b = input(": ")
    if b == "exit":
        break
    process.stdin.write(b + "\n")
    process.stdin.flush()
