import multiprocessing as mp
import os.path
import queue
import time
import traceback
import datetime
import requests as rq
import threading
from sqlite3 import *


def retrieve_metadata(website_url: str, identifier: str, headers: dict, parent_id: int = -1) -> dict:
    """
    Function to download a single metadata file for a given video_site. The website_url needs to be of type:

    /category/subcategory/year/season/lecture_id.html

    or:

    /category/subcategory/site.html

    The function **expects** to receive a valid lecture url. If an url is provided, that doesn't contain a video,
    it will try to download it anyway. The function shouldn't fail except if the site doesn't exist.

    :param website_url: url to download eg. /category/subcategory/year/season/lecture_id.html
    :param identifier: str for thread to give i/home/alisot2000/Documents/01 ReposNCode/ETH-Lecture-Loadernformation
    where the download was executed in case of an error.
    :param headers: dict to be passed to the request library. Download will fail if no user-agent is provided.
    """

    url = website_url.replace(".html", ".series-metadata.json").replace("\n", "")

    result = rq.get(url=url, headers=headers)
    content = None
    # https://www.asdf.com/path?args

    if result.ok:
        content = result.content.decode("utf-8")
    else:
        print(f"{identifier:.02} error {result.status_code}")

    # only everything after .com or something
    path = url.split("/", 3)[3]

    # remove get arguments
    path = path.split("?")[0]
    print(f"{identifier} Done {url}")

    return {"url": url, "parent_id": parent_id, "status": result.status_code, "content": content}


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

        result = retrieve_metadata(arguments["url"], str(worker_nr),
                                   headers={"user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:100.0) "
                                                          "Gecko/20100101 Firefox/100.0"},
                                   parent_id=arguments["parent_id"])

        result_queue.put(result)
    print(f"{worker_nr} Terminated")


class EpisodeLoader:
    def __init__(self, index_db: str):
        """
        Initialise downloader function. Provide the function either with a file containing valid urls or a list of urls.

        Examples for urls:

        /category/subcategory/year/season/lecture_id.html

        /category/subcategory/site.html


        :param index_db: Database result of the indexer.
        """

        self.db_path = os.path.abspath(index_db)

        self.sq_con = Connection(self.db_path)
        self.sq_cur = self.sq_con.cursor()

        self.result_queue = mp.Queue()
        self.command_queue = mp.Queue()
        self.urls = []
        self.nod = 0

        self.workers = None

        self.genera_cookie = None

        self.get_video_urls()
        self.check_results_table()

    def get_video_urls(self):
        self.verify_args_table()
        self.sq_cur.execute("SELECT key, url FROM sites WHERE IS_VIDEO=1")
        self.urls = self.sq_cur.fetchall()

    def verify_args_table(self):
        self.sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sites'")

        if self.sq_cur.fetchone() is None:
            raise ValueError("didn't find the 'sites' table inside the given database.")

    def check_results_table(self):
        self.sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")

        if self.sq_cur.fetchone() is None:
            self.sq_cur.execute("CREATE TABLE metadata "
                                "(key INTEGER PRIMARY KEY AUTOINCREMENT, "
                                "parent INTEGER, "
                                "URL TEXT , "
                                "json TEXT,"
                                "deprecated INTEGER DEFAULT 0 CHECK (metadata.deprecated >= 0 AND metadata.deprecated <= 1),"
                                "found TEXT,"
                                "last_seen TEXT)")

    def cleanup(self):
        """
        Waits for all worker processes to terminate and then joins them.
        :return:
        """
        for worker in self.workers:
            worker: threading.Thread
            worker.join(10)

    def download(self, workers: int = 100):
        """
        Initiate main Download of the urls provided in the init method.
        Calls the enqueue function and then the check_result function.

        Either choose multi_file, then the target_dir is also evaluated and the site structure is stored inside the dir
        or the entire metadata is stored inside the target file. **WARNING the target file WILL be overwritten**

        :param workers: number of worker threads to run concurrently
        :return:series
        """
        self.enqueue_th(workers)
        self.check_result()
        self.cleanup()
        self.sq_con.commit()
        print("DOWNLOAD DONE")

    def spawn(self, workers: int):
        """
        Spawns the worker threads using threading package.

        :param workers: number of workers to spawn.
        :return:
        """
        # generate arguments for the worker threads
        commands = [(i, self.command_queue, self.result_queue,) for i in range(workers)]
        threads = []

        # spawn threads
        for command in commands:
            t = threading.Thread(target=handler, args=command)
            t.start()
            threads.append(t)

        self.workers = threads

    def enqueue_th(self, workers):
        """
        Function to load the urls and put them inside a queue for the workers to download them. Also spawns the worker threads.

        :param workers: number of workers. At least 1 maybe at most 10'000
        :return:
        """

        self.spawn(workers)

        if self.urls is not None:
            self.nod = len(self.urls)
            for url in self.urls:
                self.command_queue.put({"url": url[1], "parent_id": url[0]})
        else:
            raise ValueError("Database apparently doesn't have any urls, get_urls retrieved None")

    def check_result(self):
        """
        Function check the results in the results queue.

        Either choose multi_file, then the target_dir is also evaluated and the site structure is stored inside the dir
        or the entire metadata is stored inside the target file. **WARNING the target file WILL be overwritten**
        :return:
        """
        g_counter = 0
        e_counter = 0

        ctr = 0
        res = {"url": "Empty", "content": "empty"}
        while ctr < 20:
            if not self.result_queue.empty():
                try:
                    res = self.result_queue.get()
                    parent_id = res["parent_id"]
                    url = res["url"]
                    content = res["content"].replace("'", "''")

                    if res["status"] == 200:
                        self.insert_update_db(parent_id=parent_id, url=url, json=content)
                    else:
                        print(f"Failed to download {url} with status code {res['status']}")
                        e_counter += 1
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

    def insert_update_db(self, parent_id: int, url: str, json: str):
        # exists:
        self.sq_cur.execute(f"SELECT key FROM metadata WHERE parent = {parent_id} AND URL = '{url}' AND json = '{json}' AND deprecated = 0")

        # it exists, abort
        if self.sq_cur.fetchone() is not None:
            print("Found active in db")
            return

        # exists but is deprecated
        self.sq_cur.execute(f"SELECT key FROM metadata WHERE parent = {parent_id} AND URL = '{url}' AND json = '{json}' AND deprecated = 1")

        result = self.sq_cur.fetchone()
        if result is not None:

            print("Found inactive in db, reacivate and set everything else matching parent, url and series to deprecated")

            # update all entries, to deprecated, unset deprecated where it is here
            self.sq_cur.execute(f"UPDATE metadata SET deprecated = 1 WHERE parent = {parent_id} AND URL = {url}")
            self.sq_cur.execute(f"UPDATE metadata SET deprecated = 0 WHERE key = {result}")
            return

        # doesn't exist -> insert
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("Inserting")
        self.sq_cur.execute(
            f"INSERT INTO metadata (parent, URL, json, found) VALUES ({parent_id}, '{url}', '{json}', '{now}')")
