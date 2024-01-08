from common import *
from secrets import *

if __name__ == "__main__":
    for arg in arguments:
        download(arg, username, password, 4)
        # download(arg, username, password, 2)