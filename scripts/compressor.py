from secrets import arguments, download_directory
from common import *


if __name__ == "__main__":
    compression_queue = build_args(dl_args=arguments, dl_dir=download_directory)
    compress(compression_queue, 1, 0)