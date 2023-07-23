from secrets import username, password, arguments, download_directory
from common import *


if __name__ == "__main__":
    for arg in arguments:
        download(username=username, password=password, argument=arg)

    q = mp.Queue()
    for arg in arguments:
        build_args(argument=arg, present_queue=q)

    compress(q, cpu_i=2)
