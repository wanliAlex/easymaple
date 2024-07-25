import subprocess

subprocess.Popen(["python", "main.py"], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL)