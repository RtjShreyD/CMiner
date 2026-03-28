#!/usr/bin/env python3
import subprocess
import os

def run_test():
    # Ensure execution from project root
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root_dir)
    
    prompt = "A futuristic debate between a stoic AI researcher and a passionate digital artist about the soul of generative art."
    print(f"Running podcasting test with prompt: {prompt}")
    
    cmd = [
        ".venv/bin/python3", "main.py", "podcasting",
        "--prompt", prompt,
        "--thinking", "minimal"
    ]
    
    try:
        result = subprocess.run(cmd, check=True, text=True)
        print("Test completed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Test failed with exit code {e.returncode}")
        print(e.output)

if __name__ == "__main__":
    run_test()
