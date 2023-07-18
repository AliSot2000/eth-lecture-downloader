from dataclasses import dataclass
import requests as rq
import os
import subprocess
import multiprocessing as mp
import time
import queue
import select


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
