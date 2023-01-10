import os.path
import subprocess
import requests as rq
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import multiprocessing as mp
import threading as th
import queue
import time
from secrets import username, password, arguments, download_directory, SeriesArgs


session = rq.session()


@dataclass()
class CompressionArgument:
    command_list: list
    source_path: str
    destination_path: str
    hidden_path: str
    keep_original: bool


def target_loader(command: dict):
    url = command["url"]
    path = command["path"]
    print(f"downloading {url}\n"
          f"to {path}")
    stream = rq.get(url, headers={"user-agent": "Firefox"})
    if stream.ok:
        with open(path, "wb") as f:
            f.write(stream.content)

        print(f"Done {os.path.join(folder, f'{date}.mp4')}")
        return "success"


def get_cmd_list():
    return ['HandBrakeCLI', '-v', '5', '--json', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '24.0 ', '-w', '1920',
                '-l', '1080', '--keep-display-aspect']


to_download = []

# get login
login = session.post(url="https://video.ethz.ch/j_security_check",
                     headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": username,
                                                                "j_password": password,
                                                                "j_validate": True})

cookies = login.cookies

if login.status_code == 403:
    print("Wrong Credentials")

for argu in arguments:
    if argu.username is not None and argu.password is not None:
        strip_url = argu.url.replace("www.", "").replace(".html", "").replace(".series-metadata.json", "")
        login = rq.post(url=f"{strip_url}.series-login.json",
                        headers={"user-agent": "lol herre"},
                        data={"_charset_": "utf-8", "username": argu.username, "password": argu.password})

    # load all episodes
    episodes = session.get(argu.url.replace(".html", ".series-metadata.json"),
                           headers={"user-agent": "lol it still works"})
    ep = episodes.json()

    all_episodes = ep["episodes"]

    if argu.folder is not None:
        folder = argu.folder
    else:
        folder = argu.url.split("/")[-1]
        folder = folder.replace(".html", "")
        folder = os.path.join(download_directory, folder)

    # create local target folder
    if not os.path.exists(folder):
        os.makedirs(folder)

    # get streams from episodes:
    for ep in all_episodes:
        eid = ep["id"]
        target = argu.url.replace(".html", f"/{eid}.series-metadata.json")
        episode = session.get(target, headers={"user-agent": "lol it still worked"})

        # episode downloaded correctly
        if episode.ok:
            # get metadata from json
            j = episode.json()
            maxq_url = j["selectedEpisode"]["media"]["presentations"][0]
            date = j["selectedEpisode"]["createdAt"]

            if not (os.path.exists(os.path.join(folder, f"{date}.mp4")) or os.path.exists(
                    os.path.join(folder, f".{date}.mp4"))):

                to_download.append({"url": maxq_url["url"], "path": os.path.join(folder, f"{date}.mp4")})

        else:
            print(episode.status_code)

for d in to_download:
    print(d)


tp = ThreadPoolExecutor(max_workers=5)
result = tp.map(target_loader, to_download)

for r in result:
    print(r)

exit(100)
to_compress = mp.Queue()

# perform compression
for argument in arguments:
    # list download folder
    if argument.folder is not None:
        folder = argument.folder
    else:
        folder = argument.url.split("/")[-1]
        folder = folder.replace(".html", "")
        folder = os.path.join(download_directory, folder)

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
        comp_folder = os.path.join(download_directory, comp_folder)

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


if to_compress.empty():
    exit(0)


def compress_cpu(command: CompressionArgument):
    proc = subprocess.Popen(
        command.command_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True)

    while True:
        # Do something else
        output = proc.stdout.read()
        print(output)

        return_code = proc.poll()
        if return_code is not None:
            print('RETURN CODE', return_code)

            output = proc.stdout.read()
            print(output)

            break

    if command.keep_original is False:
        os.remove(command.source_path)
        with open(command.hidden_path, "w") as file:
            file.write("Keep originals is false")

    if return_code != 0:
        raise RuntimeError("Handbrake returned non-zero return code")

    return command


def compress_gpu(command: CompressionArgument):
    command.command_list.extend(["-e", "nvenc_h264"])
    return compress_cpu(command)


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
    while ctr < 20:
        try:
            arguments = command_queue.get(block=False)
            ctr = 0
        except queue.Empty:
            ctr += 1
            time.sleep(1)
            continue

        try:
            result = fn(arguments)
        except Exception as e:
            print(e)
            result_queue.put("EXCEPTION")
            break

        result_queue.put(result)

    print(f"{worker_nr} Terminated")
    result_queue.put("TERMINATED")


while not to_compress.empty():
    compress_cpu(to_compress.get())
print("Done")
