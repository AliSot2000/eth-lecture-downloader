import multiprocessing as mp
import os.path
import queue
import time
import traceback

import requests as rq
import threading
import json


class OverConstrictionException(Exception):
    pass


def retrieve_metadata(website_url: str, identifier: str, headers: dict) -> dict:
    """
    Function to download a single metadata file for a given video_site. The website_url needs to be of type:

    /category/subcategory/year/season/lecture_id.html

    or:

    /category/subcategory/site.html

    The function **expects** to receive a valid lecture url. If an url is provided, that doesn't contain a video,
    it will try to download it anyway. The function shouldn't fail except if the site doesn't exist.

    :param website_url: url to download eg. /category/subcategory/year/season/lecture_id.html
    :param identifier: str for thread to give information where the download was executed in case of an error.
    :param headers: dict to be passed to the request library. Download will fail if no user-agent is provided.
    """

    url = website_url.replace(".html", ".series-metadata.json").replace("\n", "")

    result = rq.get(url=url, headers=headers)
    content = None
    # https://www.asdf.com/path?args

    if result.ok:
        content = result.content.decode("utf-8")
    else:
        print(f"{identifier} error {result.status_code}")

    # only everything after .com or something
    path = url.split("/", 3)[3]

    # remove get arguments
    path = path.split("?")[0]
    print(f"{identifier} Done {url}")

    return {"url": url, "path": path, "status": result.status_code, "content": content}


def handler(worker_nr: int, command_queue: mp.Queue, result_queue: mp.Queue, cookie = None):
    """
    Function executed in a worker thread. The function tries to download the given url in the queue. If the queue is
    empty for 20s, it will kill itself.

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

        result = retrieve_metadata(arguments["url"], str(worker_nr),
                                   headers={"user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:100.0) "
                                                          "Gecko/20100101 Firefox/100.0"})

        result_queue.put(result)
    print(f"{worker_nr} Terminated")


class EpisodeLoader:
    def __init__(self, urls: list = None, file: str = None):
        """
        Initialise downloader function. Provide the function either with a file containing valid urls or a list of urls.

        Examples for urls:

        /category/subcategory/year/season/lecture_id.html

        /category/subcategory/site.html


        :param urls: list of urls to download.      /category/subcategory/site.html

        :param file: file path to a file containing the urls, one url per line
        """
        if urls is None and file is None:
            raise OverConstrictionException("Both urls and file were not None")
        elif urls is None and file is None:
            raise ValueError("One of the arguments must be given.")

        self.urls = urls
        self.file_path = file

        self.result_queue = mp.Queue()
        self.command_queue = mp.Queue()
        self.nod = 0

        self.workers = None

        self.genera_cookie = None

    def download(self, workers: int = 100, multi_file: bool = False, target_dir: str = None, target_file: str = None, beautify: bool = False):
        """
        Initiate main Download of the urls provided in the init method.
        Calls the enqueue function and then the check_result function.

        Either choose multi_file, then the target_dir is also evaluated and the site structure is stored inside the dir
        or the entire metadata is stored inside the target file. **WARNING the target file WILL be overwritten**

        :param beautify: if Ture the metadata-json will be indented.
        :param workers: number of worker threads to run concurrently
        :param multi_file: store each meta-data object inside a file
        :param target_dir: directory to start the file structure for multifile
        :param target_file: provide a single file to store the entire metadata inside.
        :return:
        """
        self.enqueue_th(workers)
        self.check_result(multi_file, target_dir, target_file, beautify=beautify)
        print("DOWNLOAD DONE")

    def enqueue_th(self, workers):
        """
        Function to load the urls and put them inside a queue for the workers to download them. Also spawns the worker threads.

        :param workers: number of workers. At least 1 maybe at most 10'000
        :return:
        """
        # TODO join threads is not currently done.

        # generate arguments for the worker threads
        commands = [(i, self.command_queue, self.result_queue, self.genera_cookie, ) for i in range(workers)]
        threads = []

        # spawn threads
        for command in commands:
            t = threading.Thread(target=handler, args=command)
            t.start()
            threads.append(t)

        self.workers = threads

        # generate argument dict
        if self.urls is not None:
            self.nod = len(self.urls)
            for url in self.urls:
                self.command_queue.put({"url": url})

        else:
            with open(self.file_path, 'r') as fp:
                self.nod = len(fp.readlines())
            with open(self.file_path, "r") as file:
                line = file.readline()

                while line:
                    self.command_queue.put({"url": line})
                    line = file.readline()

    def check_result(self, multi_file: bool = False, target_dir: str = None, target_file: str = None, beautify: bool = False):
        """
        Function check the results in the results queue.

        Either choose multi_file, then the target_dir is also evaluated and the site structure is stored inside the dir
        or the entire metadata is stored inside the target file. **WARNING the target file WILL be overwritten**

        :param beautify: if Ture the metadata-json will be indented.
        :param multi_file: store each meta-data object inside a file
        :param target_dir: directory to start the file structure for multifile
        :param target_file: provide a single file to store the entire metadata inside.
        :return:
        """
        g_counter = 0
        e_counter = 0

        if not multi_file and target_file is None:
            raise ValueError("target_file must be given if the multi_file option isn't wanted")

        if multi_file:
            if target_dir is not None:
                if beautify:
                    def write_file(f_path: str, data: str):
                        # create valid directory
                        f_dir = os.path.join(target_dir, os.path.dirname(f_path))
                        f_dir += "/"

                        if not os.path.exists(f_dir):
                            os.makedirs(f_dir)

                        with open(os.path.join(target_dir, f_path), "w") as f:
                            f.write(json.dumps(json.loads(data), indent=2))
                else:
                    def write_file(f_path: str, data: str):
                        # create valid directory
                        f_dir = os.path.join(target_dir, os.path.dirname(f_path))
                        f_dir += "/"

                        if not os.path.exists(f_dir):
                            os.makedirs(f_dir)

                        with open(os.path.join(target_dir, f_path), "w") as f:
                            f.write(data)
            else:
                if beautify:
                    def write_file(f_path: str, data: str):
                        if not os.path.exists(os.path.dirname(f_path) + "/"):
                            os.makedirs(os.path.dirname(f_path) + "/")

                        with open(f_path, "w") as f:
                            f.write(json.dumps(json.loads(data), indent=2))
                else:
                    def write_file(f_path: str, data: str):
                        if not os.path.exists(os.path.dirname(f_path) + "/"):
                            os.makedirs(os.path.dirname(f_path) + "/")

                        with open(f_path, "w") as f:
                            f.write(data)

            ctr = 0
            while ctr < 20:
                if not self.result_queue.empty():
                    try:
                        res = self.result_queue.get()
                        path = res["path"]
                        if res["status"] == 200:
                            write_file(path, res["content"])
                        ctr = 0
                    except Exception as e:
                        print(traceback.format_exc())
                        print(f"\n\n\n FUCKING EXCEPTION {e}\n\n\n")
                        print(res["url"])
                        print(res["content"])
                        e_counter += 1
                    g_counter += 1
                else:
                    time.sleep(1)
                    ctr += 1

        else:
            with open(target_file, "w") as tf:
                ctr = 0
                while ctr < 20:
                    if not self.result_queue.empty():
                        try:
                            res = self.result_queue.get()
                            if res["status"] == 200:
                                tf.write(res["url"])
                                tf.write("\n")
                                tf.write(res["content"])
                                tf.write("\n")
                                ctr = 0

                        except Exception as e:
                            print(traceback.format_exc())
                            print(f"\n\n\n FUCKING EXCEPTION {e}\n\n\n")
                            print(res["url"])
                            print(res["content"])
                            e_counter += 1
                        g_counter += 1
                    else:
                        time.sleep(1)
                        ctr += 1

        print(f"Downloaded {g_counter} with {e_counter} errors.")
