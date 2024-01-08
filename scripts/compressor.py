from secrets import arguments, download_directory
from common import *
import multiprocessing as mp


if __name__ == "__main__":
    q = mp.Queue()
    for arg in arguments:
        q = build_args(argument=arg, present_queue=q)
    print(q.qsize())
    time.sleep(1)
    compress(q, 1, 0)