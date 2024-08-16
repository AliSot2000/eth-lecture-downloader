from secrets import arguments
from common import *
import multiprocessing as mp


if __name__ == "__main__":
    q = mp.Queue()
    for arg in arguments:
        q = build_args(argument=arg, present_queue=q)
    print(f"Number of Videos to compress: {q.qsize()}")
    time.sleep(1)

    # For increased performance on Workstation
    compress(q, 2, 0)