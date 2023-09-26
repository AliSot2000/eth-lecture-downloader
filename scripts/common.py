from dataclasses import dataclass
import requests as rq
import os
import subprocess
import multiprocessing as mp
import time
import queue
import threading as th
from concurrent.futures import ThreadPoolExecutor


@dataclass
class SeriesArgs:
    """
    Url needs to be a match for a series like: https://videos.ethz.ch/lectures/d-infk/2022/spring/NUMBER, no .html or
    .series-metadata. It may also be a specific episode of a series.
    """
    url: str
    folder: str

    username: str = None
    password: str = None

    keep_originals: bool = False
    compressed_suffix: str = None
    compressed_folder: str = None


@dataclass
class CompressionArgument:
    """
    Dataclass passed to the compression workers. Contains all relevant information for compressing.
    """
    command_list: list
    source_path: str
    destination_path: str
    hidden_path: str
    keep_original: bool


@dataclass
class DownloadArgs:
    """
    Dataclass passed to the download workers. Contains all relevant information for downloading.
    """
    full_url: str
    download_path: str


def target_loader(command: DownloadArgs):
    """
    Downloads the given url to the given path. If the download fails, the command is returned.
    """
    url = command.full_url
    path = command.download_path
    print(f"downloading {url}\n"
          f"to {path}")

    try:
        stream = rq.get(url, headers={"user-agent": "Firefox"})
    except Exception as e:
        print(e)
        return command

    if stream.ok:
        with open(path, "wb") as file:
            file.write(stream.content)

        print(f"Done {command.download_path}")
        return "success"
    else:
        return command


def compress_cpu(command: CompressionArgument, identifier: int):
    """
    Function to compress the given file with handbrake. The Command is returned in the end.
    """
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
    """
    Function to use nvenc_h264 - increases encoding speed, increases file size.
    """
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
    """
    Builds teh default command list for handbrake.
    """
    return ['HandBrakeCLI', '-v', '5', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '24.0 ', '-w', '1920',
                '-l', '1080', '--keep-display-aspect']


def build_args(argument: SeriesArgs, present_queue: mp.Queue = None) -> mp.Queue:
    """
    Given the series args indexes the arguments and fills a queue with all the commands to compress all the newly
    available files.

    :param present_queue: Queue to fill with commands to compress the files
    :param argument: SeriesArgs containing all relevant information
    :return: Queue containing all commands to compress the files
    """
    to_compress = mp.Queue()

    if present_queue is not None:
        to_compress = present_queue

    # perform compression
    folder = argument.folder

    # set the suffix if the user hasn't already
    if argument.compressed_suffix is None:
        argument.compressed_suffix = "_comp"

    if os.path.exists(folder):
        download_content = os.listdir(folder)
    else:
        download_content =  []

    # list target folder
    if argument.compressed_folder is not None:
        comp_folder = argument.compressed_folder
    else:
        comp_folder = os.path.join(os.path.dirname(argument.folder), argument.compressed_suffix)

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

            if to_compress.full():
                raise ValueError("Encountered full queue.")
            to_compress.put(CompressionArgument(raw_list, fp, comp_fp, hidden_fp, argument.keep_originals))
    return to_compress


def compress(q: mp.Queue, cpu_i: int = 0, gpu_i: int = 0):
    """
    Function to compress the content of the queue. The function will spawn cpu_i + gpu_i worker threads and try to
    comparess as fast as possiblel.

    WARNING: Using the GPU compresses faster BUT the filesize isn't as small.
    :param cpu_i: number of cpu workers
    :param gpu_i: number of gpu workers.
    :return:
    """
    if gpu_i > 0:
        print("WARNING: Compressing using nvenc will INCREASE file sizes drastically.")
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


def download(username, password, argument: SeriesArgs):
    """
    Try to download the new episodes of a given series.

    :param username: Username for the video.ethz.ch website
    :param password: Password for the video.ethz.ch website
    :param argument: SeriesArgs containing all relevant information

    """
    session = rq.session()

    to_download = []
    folder = None

    # get login
    login = session.post(url="https://video.ethz.ch/j_security_check",
                         headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": username,
                                                                    "j_password": password,
                                                                    "j_validate": True})
    # Check if login was successful
    if login.status_code == 403:
        print("Wrong Credentials")

    # Try to perform login with the series credentials if necessary.
    if argument.username is not None and argument.password is not None:
        strip_url = argument.url.replace("www.", "").replace(".html", "").replace(".series-metadata.json", "")
        login = session.post(url=f"{strip_url}.series-login.json",
                        headers={"user-agent": "lol herre"},
                        data={"_charset_": "utf-8", "username": argument.username, "password": argument.password})

        if not login.ok:
            print("Failed to login to series")

    # load all episodes
    episodes = session.get(argument.url.replace(".html", ".series-metadata.json"),
                           headers={"user-agent": "lol it still works"})
    ep = episodes.json()
    all_episodes = ep["episodes"]

    folder = argument.folder

    # create local target folder
    if not os.path.exists(folder):
        os.makedirs(folder)

    # get streams from episodes:
    for ep in all_episodes:
        eid = ep["id"]
        target = argument.url.replace(".html", f"/{eid}.series-metadata.json")
        episode = session.get(target, headers={"user-agent": "lol it still worked"})

        # episode downloaded correctly
        if episode.ok:
            # get metadata from json
            j = episode.json()
            maxq_url = j["selectedEpisode"]["media"]["presentations"][0]
            date = j["selectedEpisode"]["createdAt"]
            date = date.replace(":", "_")

            if not (os.path.exists(os.path.join(folder, f"{date}.mp4")) or os.path.exists(
                    os.path.join(folder, f".{date}.mp4"))):
                to_download.append(DownloadArgs(full_url=maxq_url["url"],
                                                download_path=os.path.join(folder, f"{date}.mp4")))

        else:
            print(episode.status_code)

    for d in to_download:
        print(d)

    # tp = ThreadPoolExecutor(max_workers=5)
    tp = ThreadPoolExecutor(max_workers=2)
    result = tp.map(target_loader, to_download)

    for r in result:
        print(r)

    tp.shutdown()

