import subprocess

# Launch manim with pipes for stdin/stdout/stderr
process = subprocess.Popen(
    ["uv", "run", "manim", "manim_loop.py", "-p", "--renderer=opengl"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,  # This makes it use text mode instead of bytes
)

# To send input to it:
process.stdin.write("self.add(Circle())\n")
process.stdin.flush()

# To read its output:
while True:
    output = process.stdout.readline()
    if output:
        print(output.strip())
    if process.poll() is not None:
        break
