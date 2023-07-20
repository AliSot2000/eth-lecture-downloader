from dataclasses import dataclass
import requests as rq
import os
import subprocess
import multiprocessing as mp
import time
import queue
import threading as th
from typing import List


@dataclass
class SeriesArgs:
    """
    Url needs to be a match for a series like: https://videos.ethz.ch/lectures/d-infk/2022/spring/NUMBER, no .html or
    .series-metadata. It may also be a specific episode of a series.
    """
    url: str
    username: str = None
    password: str = None

    folder: str = None
    keep_originals: bool = False
    compressed_suffix: str = None
    compressed_folder: str = None


@dataclass
class SeriesArgs:
    """
    Url needs to be a match for a series like: https://videos.ethz.ch/lectures/d-infk/2022/spring/NUMBER, no .html or
    .series-metadata. It may also be a specific episode of a series.
    """
    url: str
    username: str = None
    password: str = None

    folder: str = None
    keep_originals: bool = False
    compressed_suffix: str = None
    compressed_folder: str = None


@dataclass
class CompressionArgument:
    command_list: list
    source_path: str
    destination_path: str
    hidden_path: str
    keep_original: bool


@dataclass
class DownloadArgs:
    full_url: str
    download_path: str


def target_loader(command: DownloadArgs):
    url = command.full_url
    path = command.download_path
    print(f"downloading {url}\n"
          f"to {path}")

    stream = rq.get(url, headers={"user-agent": "Firefox"})
    if stream.ok:
        with open(path, "wb") as file:
            file.write(stream.content)

        print(f"Done {command.download_path}")
        return "success"
    else:
        return command

def compress_cpu(command: CompressionArgument, identifier: int):
    proc = subprocess.Popen(
        command.command_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True)

    # Do something else
    for line in iter(proc.stdout.readline, ""):
        print(f"{identifier:02}: {line.strip()}")

    return_code = proc.poll()
    if return_code is not None:
        print(f'{identifier:02}: RETURN CODE', return_code)

        output = proc.stdout.read()
        print(output)


    if command.keep_original is False:
        os.remove(command.source_path)
        with open(command.hidden_path, "w") as file:
            file.write(f"{identifier:02}: Keep originals is false")

    # nvenc_h264 returns NONE!!!
    if return_code != 0 and return_code is not None:
        raise RuntimeError(f"{identifier:02}: Handbrake returned non-zero return code {return_code}")

    return command


def compress_gpu(command: CompressionArgument, identifier: int):
    command.command_list.extend(["-e", "nvenc_h264"])
    return compress_cpu(command, identifier)


def handler(worker_nr: int, command_queue: mp.Queue, result_queue: mp.Queue, fn: callable):
    """
    Function executed in a worker thread. The function tries to download the given url in the queue. If the queue is
    empty for 20s, it will kill itself.

    :param fn: Function to be called in handler
    :param worker_nr: Itendifier for debugging
    :param command_queue: Queue containing dictionaries containing all relevant information for downloading
    :param result_queue: Queue to put the results in. Handled in main thread.
    :return:
    """
    print("Starting")
    ctr = 0
    while ctr < 60:
        try:
            arguments = command_queue.get(block=False)
            ctr = 0
        except queue.Empty:
            ctr += 1
            time.sleep(1)
            continue

        try:
            result = fn(arguments, worker_nr)
        except Exception as e:
            print(f"{worker_nr:02}: {e}")
            result_queue.put(f"EXCEPTION")
            break

        result_queue.put(result)

    print(f"{worker_nr:02}: Terminated")
    result_queue.put("TERMINATED")

def get_cmd_list():
    # return ['HandBrakeCLI', '-v', '5', '--json', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '24.0 ', '-w', '1920',
    #             '-l', '1080', '--keep-display-aspect']
    return ['HandBrakeCLI', '-v', '5', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '24.0 ', '-w', '1920',
                '-l', '1080', '--keep-display-aspect']

# exit(100)
def build_args(dl_args: List[SeriesArgs], dl_dir: str) -> mp.Queue:
    to_compress = mp.Queue()

    # perform compression
    for argument in dl_args:
        # list download folder
        if argument.folder is not None:
            folder = argument.folder
        else:
            folder = argument.url.split("/")[-1]
            folder = folder.replace(".html", "")
            folder = os.path.join(dl_dir, folder)

        # set the suffix if the user hasn't already
        if argument.compressed_suffix is None:
            argument.compressed_suffix = "_comp"

        download_content = os.listdir(folder)

        # list target folder
        if argument.compressed_folder is not None:
            comp_folder = argument.compressed_folder
        else:
            comp_folder = argument.url.split("/")[-1]
            comp_folder = comp_folder.replace(".html", "")
            comp_folder += "_compressed"
            comp_folder = os.path.join(dl_dir, comp_folder)

        if os.path.exists(comp_folder):
            compressed_content = os.listdir(comp_folder)
        else:
            os.makedirs(comp_folder)
            compressed_content = []

        # iterate over files and compress the ones that aren't done
        for file in download_content:
            fp = os.path.join(folder, file)
            if os.path.isfile(fp):
                # skip hidden files
                if file[0] == ".":
                    continue

                hidden_fp = os.path.join(folder, f".{file}")

                name, ext = os.path.splitext(file)
                comp_name = f"{name}{argument.compressed_suffix}{ext}"

                # in compressed folder -> it is done
                if comp_name in compressed_content:
                    continue

                comp_fp = os.path.join(comp_folder, comp_name)

                # perform compression
                raw_list = get_cmd_list()
                file_list = ["-i", fp, "-o", comp_fp]
                raw_list.extend(file_list)

                to_compress.put(CompressionArgument(raw_list, fp, comp_fp, hidden_fp, argument.keep_originals))
    return to_compress


def compress(q: mp.Queue, cpu_i: int = 0, gpu_i: int = 0):
    if q.empty():
        return

    cpu_h = []
    gpu_h = []
    resq = mp.Queue()

    for i in range(cpu_i):
        cpu_h.append(th.Thread(target=handler, args=(i, q, resq, compress_cpu)))
        cpu_h[i].start()

    for i in range(cpu_i, cpu_i + gpu_i):
        gpu_h.append(th.Thread(target=handler, args=(i, q, resq, compress_gpu)))
        gpu_h[i - cpu_i].start()

    to = 0
    e_count = 0

    while to < 3600 and e_count < cpu_i+gpu_i:
        time.sleep(1)

        if not resq.empty():
            res = resq.get(block=False)
            if res == "EXCEPTION":
                exit(1)
            elif res == "TERMINATED":
                e_count += 1
                to = 0
            else:
                print("DONE with:")
                print(res)
                to = 0

    for i in cpu_h:
        i.join()

    for i in gpu_h:
        i.join()
