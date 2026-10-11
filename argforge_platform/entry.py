import sys, os

if __name__ == "__main__":
    if os.name != "nt" or sys.stdin.buffer.readline(16) != b"RUN\n":
        raise SystemExit("Windows Job admission required")
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    mode = sys.argv[1]
    args = sys.argv[2:]
    if mode == "evaluate":
        from argforge_platform.windows import worker

        worker(*args)
    elif mode == "research":
        from argforge.evaluation_runner.research_worker import main

        main(*args)
    else:
        raise SystemExit("Unknown worker mode")
