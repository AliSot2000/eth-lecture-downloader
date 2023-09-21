from concurrent.futures import ThreadPoolExecutor
import threading as th
from secrets import username, password, arguments, download_directory
import datetime
from common import *

print(" THIS SCRIPT USES THE GPU")
print(" COMPRESSING WITH GPU IS A LOT FASTER BUT ALSO PRODUCES LESS COMPRESSED FILES.")
start = datetime.datetime.now()
session = rq.session()


def get_cmd_list():
    # return ['HandBrakeCLI', '-v', '5', '--json', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '24.0 ', '-w', '1920',
    #             '-l', '1080', '--keep-display-aspect']
    return ['HandBrakeCLI', '-v', '5', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '24.0 ', '-w', '1920',
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
tp = ThreadPoolExecutor(max_workers=1)
result = tp.map(target_loader, to_download)

for r in result:
    print(r)

# exit(100)

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

resq = mp.Queue()
cpu = th.Thread(target=handler, args=(0, to_compress, resq, compress_cpu))
gpu = th.Thread(target=handler, args=(0, to_compress, resq, compress_gpu))
gpu2 = th.Thread(target=handler, args=(0, to_compress, resq, compress_gpu))

cpu.start()
gpu.start()
gpu2.start()

counter = 0
t_counter = 0

while counter < 3600 and t_counter < 2:
    time.sleep(1)

    if not resq.empty():
        res = resq.get(block=False)
        if res == "EXCEPTION":
            exit(1)
        elif res == "TERMINATED":
            t_counter += 1
            counter = 0
        else:
            print("DONE with:")
            print(res)
            counter = 0

gpu2.join()
gpu.join()
cpu.join()
print("Processes killed, completely done")
stop = datetime.datetime.now()
print(f"It took {(stop - start).total_seconds()}")
