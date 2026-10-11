import os, subprocess, sys, uuid
from pathlib import Path


class WindowsJobProcess:
    def __init__(self, mode, args, *, memory, stdout, stderr, env=None):
        if os.name != "nt":
            raise OSError("Windows Job Objects require Windows")
        import win32job, win32api, win32con

        self.job = None
        self.process = None
        try:
            self.job = win32job.CreateJobObject(None, "ArgForge-" + uuid.uuid4().hex)
            info = win32job.QueryInformationJobObject(
                self.job, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
                | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            info["BasicLimitInformation"]["ActiveProcessLimit"] = 4
            info["ProcessMemoryLimit"] = int(memory)
            info["JobMemoryLimit"] = int(memory)
            win32job.SetInformationJobObject(
                self.job, win32job.JobObjectExtendedLimitInformation, info
            )
            command = [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("entry.py")),
                mode,
                *map(str, args),
            ]
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
            h = win32api.OpenProcess(
                win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                False,
                self.process.pid,
            )
            try:
                win32job.AssignProcessToJobObject(self.job, h)
            finally:
                h.Close()
            self.process.stdin.write(b"RUN\n")
            self.process.stdin.close()
        except BaseException:
            self.close()
            raise

    @property
    def pid(self):
        return self.process.pid

    @property
    def returncode(self):
        return self.process.returncode

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        return self.process.wait(timeout=timeout)

    def terminate(self):
        if self.job:
            import win32job

            win32job.TerminateJobObject(self.job, 1)
        elif self.process and self.process.poll() is None:
            self.process.kill()
        if self.process:
            self.process.wait()

    def close(self):
        if self.job:
            self.job.Close()
            self.job = None
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
