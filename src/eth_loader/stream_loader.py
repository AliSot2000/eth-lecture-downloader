import os
import traceback

import requests as rq
import multiprocessing as mp
import queue
import time
import pickle
from threading import Thread
import json


def get_stream(website_url: str, identifier: str, headers: dict, cookies: bytes) -> dict:
    """
    Function to download a single metadata file for a given video_site and video entry. The website_url needs to be of type:

    /category/subcategory/year/season/lecture_id/long-id.series-metadata.json

    or:

    /category/subcategory/site.html

    The function **expects** to receive a valid lecture url. If an url is provided, that doesn't contain a video,
    it will try to download it anyway. The function shouldn't fail except if the site doesn't exist.

    :param cookies:
    :param website_url: url to download eg. /category/subcategory/year/season/lecture_id.html
    :param identifier: str for thread to give information where the download was executed in case of an error.
    :param headers: dict to be passed to the request library. Download will fail if no user-agent is provided.
    """

    url = website_url.replace("\n", "")
    cj = pickle.loads(cookies)

    result = rq.get(url=url, headers=headers, cookies=cj)
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


def handler(worker_nr: int, command_queue: mp.Queue, result_queue: mp.Queue):
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

        result = get_stream(arguments["url"], str(worker_nr),
                            headers={"user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:100.0) "
                                                   "Gecko/20100101 Firefox/100.0"}, cookies=arguments["cookie-jar"])

        result_queue.put(result)
    print(f"{worker_nr} Terminated")


def folder_builder(root_folder: str) -> list:
    files = []
    sub_dirs = []

    dir_o_files = os.listdir(root_folder)

    for dof in dir_o_files:
        if os.path.isdir(os.path.join(root_folder, dof)):
            sub_dirs.append(os.path.join(root_folder, dof))
        elif os.path.isfile(os.path.join(root_folder, dof)):
            files.append(os.path.join(root_folder, dof))
        else:
            print(f"Couldn't assign {os.path.join(root_folder, dof)}")

    for subdir in sub_dirs:
        sub = folder_builder(subdir)
        files.extend(sub)

    return files


class BetterStreamLoader:
    def __init__(self, file_list: list, prefix_path: str, user_name: str = None, password: str = None,
                 spec_login: list = None):

        self.file_list = file_list
        self.path_prefix = prefix_path

        if self.path_prefix[-1] != "/":
            self.path_prefix += "/"

        if spec_login is not None:
            self.specific_urls = [entry["url"] for entry in spec_login]
            self.specific_auth = [{"username": entry["username"], "password": entry["password"]} for entry in spec_login]
        else:
            self.specific_urls = []
            self.specific_auth = []

        # prepare urls for matching (removing file extension)
        for i in range(len(self.specific_urls)):
            # turn
            # /category/subcategory/year/season/lecture_id.series-metadata.json
            # or
            # /category/subcategory/year/season/lecture_id.html
            # into
            # /category/subcategory/year/season/lecture_id
            self.specific_urls[i] = self.specific_urls[i].replace(".html", "").replace(".series-metadata.json", "")

        self.workers = []

        self.result_queue = mp.Queue(maxsize=1000)
        self.command_queue = mp.Queue(maxsize=1000)
        self.nod = len(self.file_list)

        self.general_cookie = None
        self.login(user_name, password)

    def spawn(self, threads: int = 100):
        """
        Spawns worker theads.

        :param threads: number of threads to spawn 1-10000
        :return:
        """
        if not 1 < threads < 10000:
            raise ValueError("Thread number outside supported range [1:10'000]")

        self.workers = []
        for i in range(threads):
            t = Thread(target=handler, args=(i, self.command_queue, self.result_queue))
            t.start()
            self.workers.append(t)

        print("Workers Spawned")

    def initiator(self, workers: int = 100, beautify: bool = False, target_path: str = None):
        if target_path is None:
            target_path = self.path_prefix

        self.spawn(workers)
        dequeue = Thread(target=self.dequeue_job, args=(target_path, beautify,))
        dequeue.start()
        self.enqueue_job()

        while dequeue.is_alive():
            time.sleep(30)
            print("Initiator Thread Sleeping Dequeue")

        dequeue.join()

        while self.workers_alive():
            time.sleep(30)
            print("Initiator Thread Sleeping Workers")

        self.cleanup()
        print("DONE")

    def cleanup(self):
        """
        Waits for all worker processes to terminate and then joins them.
        :return:
        """
        for worker in self.workers:
            worker: Thread
            worker.join()

    def workers_alive(self):
        """
        Function to verify that at least one of the workers hasn't exited.
        :return:
        """
        for worker in self.workers:
            worker: Thread
            if worker.is_alive():
                return True

        return False

    def login(self, usr: str = None, pw: str = None):
        """
        Retrieves the login cookie to access LDAP restricted recordings.


        :param usr: ETH LDAP Username
        :param pw: ETH LDAP Password
        :return:
        """
        if pw is None or usr is None:
            print("No Credentials")
            return

        login = rq.post(url="https://video.ethz.ch/j_security_check",
                        headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": usr,
                                                                   "j_password": pw,
                                                                   "j_validate": True})

        if login.ok:
            self.general_cookie = login.cookies

        elif login.status_code == 403:
            print("Wrong Credentials")

        else:
            print(login.status_code)
            print(vars(login))

    def spec_login(self, strip_url: str, usr: str, pw: str, other_cookies = None):
        """
        Provide the url as the series-metadata or html for the course site

        :param other_cookies:
        :param pw:
        :param usr:
        :param strip_url:
        :return:
        """
        login = rq.post(url=f"{strip_url}.series-login.json",
                        headers={"user-agent": "lol herre"},
                        data={"_charset_": "utf-8", "username": usr, "password": pw},
                        cookies=self.general_cookie)
        if login.ok:
            cj = login.cookies
            cj.update(self.general_cookie)

            if other_cookies is not None:
                cj.update(other_cookies)

            return cj
        else:
            print(login.status_code)
            print(vars(login))
            return self.general_cookie

    def enqueue_job(self):
        general_cookie_jar = pickle.dumps(self.general_cookie)

        for file in self.file_list:
            cookie = self.general_cookie
            cookie_jar = general_cookie_jar

            # url from file path
            base_url = file.replace(self.path_prefix, "https://video.ethz.ch/")

            # url without file extension
            strip_url = base_url.replace(".html", "").replace(".series-metadata.json", "")

            # if the stripped url is a specified url, get login of that url as well
            if strip_url in self.specific_urls:
                index = self.specific_urls.index(strip_url)

                cookie = self.spec_login(strip_url, self.specific_auth[index]["username"],
                                                 self.specific_auth[index]["password"])
                cookie_jar = pickle.dumps(cookie)

            # initialise file content
            content = ""

            # load file content with json
            with open(file, "r") as f:
                content = json.load(f)

            # get a list of all episodes
            episode_list = content["episodes"]

            # iterate over all episode ids
            for episode in episode_list:
                episode_cookie_jar = cookie_jar
                episode_id = episode["id"]

                episode_striped_url = f"{strip_url}/{episode_id}"
                episode_url = f"{strip_url}/{episode_id}.series-metadata.json"

                # get specific login for specific episode if necessary
                if episode_striped_url in self.specific_urls:
                    index = self.specific_urls.index(strip_url)

                    episode_cookie = self.spec_login(strip_url, self.specific_auth[index]["username"],
                                             self.specific_auth[index]["password"], other_cookies=cookie)
                    episode_cookie_jar = pickle.dumps(episode_cookie)

                print(f"Enqueueing: {episode_url}")
                self.command_queue.put({"url": episode_url, "cookie-jar": episode_cookie_jar})

    def dequeue_job(self, target_folder: str = None, beautify: bool = False):
        if beautify:
            def write_file(f_path: str, data: str):
                # create valid directory
                f_dir = os.path.join(target_folder, os.path.dirname(f_path))
                f_dir += "/"

                if not os.path.exists(f_dir):
                    os.makedirs(f_dir)

                with open(os.path.join(target_folder, f_path), "w") as f:
                    f.write(json.dumps(json.loads(data), indent=2))
        else:
            def write_file(f_path: str, data: str):
                # create valid directory
                f_dir = os.path.join(target_folder, os.path.dirname(f_path))
                f_dir += "/"

                if not os.path.exists(f_dir):
                    os.makedirs(f_dir)

                with open(os.path.join(target_folder, f_path), "w") as f:
                    f.write(data)

        ctr = 0
        while ctr < 20:
            if not self.result_queue.empty():
                try:
                    res = self.result_queue.get()
                    path = res["path"]
                    if res["status"] == 200:
                        write_file(path, res["content"])
                    else:
                        print(f"url {res['url']} with status code {res['status']}")
                    ctr = 0
                except Exception as e:
                    print(traceback.format_exc())
                    print("\n\n\n FUCKING EXCEPTION \n\n\n")
            else:
                time.sleep(1)
                ctr += 1


