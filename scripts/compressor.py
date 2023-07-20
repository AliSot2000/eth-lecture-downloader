from concurrent.futures import ThreadPoolExecutor
import threading as th
from secrets import username, password, arguments, download_directory
import datetime
from common import *


start = datetime.datetime.now()
session = rq.session()


if __name__ == "__main__":
    compression_queue = build_args(dl_args=arguments, dl_dir=download_directory)
    compress(compression_queue, 1, 2)