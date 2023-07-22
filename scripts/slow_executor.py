from common import *
from secrets import username, password, download_directory, arguments
import os


def folder_tree_size(path: str):
    total_size = 0
    for path, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(path, f)
            total_size += os.path.getsize(fp)
    return total_size


if __name__ == "__main__":
    for arg in arguments:
        download(username=username, password=password, argument=arg)
        target_dir = arg.folder
        before = 0
        after = 0
        if target_dir is not None:
            before = folder_tree_size(target_dir)
            with open(os.path.join(target_dir, "stats.txt"), "a") as f:
                f.write(f"Downloaded size: {before}")

        q = build_args(argument=arg)
        compress(q, cpu_i=2)
        new_target_dir = arg.compressed_folder
        if new_target_dir is not None:
            after = folder_tree_size(new_target_dir)
            with open(os.path.join(new_target_dir, "stats.txt"), "w") as f:
                f.write(f"Compressed Size: {after}\n")


