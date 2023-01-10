import datetime
import os.path
import sqlite3

import traceback
import requests as rq
from lxml import etree
from lxml.etree import _Element
import multiprocessing as mp
from threading import Thread
from time import sleep
from queue import Empty
from sqlite3 import *

"""
# Functionality of Class:

## Life cycle of ConcurrentETHSiteIndexer
- init: create the queues and initialize the attributes, connect to the database
- index_video_eth: schedule all links (hrefs) found on the root site of video site of the eth for the workers.
    uses sub_index to add the first results to the ingest queue (can be switched to __sub_index func for debugging)
- spawn: spawns the workers and returns (doesn't wait for workers to exit)
- dequeue: dequeues the results from the results queue, uses 'not_in_db' to insert only the new results into the db
    uses 'workers_alive' to check if new results are still added to the queue, 
- gen_parent: create the linking to create the site hirarchie in the database with foreign keys.
    uses 'get_url_id' to find the key of the parent. store the result in dict to make accessing faster (db is slow)
    
## Worker life cycle
- __indexer: try to dequeue, queue empty for 20s, exit, uses '__sub_index' to recursively search site
- __sub_index: fetches page from arguments, checks if page is a video if so, put that in queue, and return
    else, put no video in queue and  get all hrefs, make sure the parent matches, then add them to the todo queue

"""


def parent_site(url: str) -> str:
    """
    Generates the url to the parent site.
    :param url: url to get the parent of.
    :return:
    """
    snippets = url.split("/")
    del snippets[-1]

    url = snippets[0]
    for i in range(1, len(snippets)):
        url += "/" + snippets[i]

    url += ".html"
    return url


def is_video(root: _Element) -> bool:
    """
    Checks if the video is present on the video.
    :param root: lxml.etree._Element, root element of the html
    :return:
    """
    video = root.xpath("//vp-episode-page")

    if len(video) > 0:
        return True

    return False


class ConcurrentETHSiteIndexer:
    """
    Creates a Database of the hierarchy of the video sites of video.ethz.ch
    It tracks the parent site which contained the link to the current site.
    It also has a found tag which stores the date the site was found.
    """
    def __init__(self, file: str, prefixes: list = None):
        """
        Initializer for concurrent indexing of entire video.ethz.ch site.

        The time permitted indexes are: campus, conferences, events, speakers, lectures

        :param file: output where the video-series urls are stored. (at the time 6460 urls)
        :param prefixes: provide custom prefixes, main_header [campus, lectures, ...]
        """
        self.prefixes = ["/campus", "/conferences", "/events", "/speakers", "/lectures"]
        self.file = file
        make_db = not os.path.exists(file)

        self.sq_con = Connection(file)
        self.sq_cur = self.sq_con.cursor()

        if make_db:
            self.init_db()

        self.to_download_queue = mp.Queue()
        self.found_url_queue = mp.Queue(maxsize=100)
        self.threads = []

    def val_uri(self, url: str) -> bool:
        """
        Checks if the uri is valid and can be processed.
        :param url: url to check.
        :return:
        """
        # it is a valid site
        if ".html" not in url:
            return False

        # it is a child
        if len(url.split("/")) > 2:
            return False

        # it is a desired url
        for pref in self.prefixes:
            if pref in url:
                return True

        return False

    def init_db(self):
        """
        Initialises the database.
        :return:
        """
        self.sq_cur.execute("CREATE TABLE sites "
                            "(key INTEGER PRIMARY KEY AUTOINCREMENT, "
                            "parent INTEGER, "
                            "URL TEXT UNIQUE , "
                            "IS_VIDEO INTEGER CHECK (IS_VIDEO >= 0 AND IS_VIDEO <= 1),"
                            "found TEXT);")

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Dummy entry to have a root.
        self.sq_cur.execute(f"INSERT INTO sites (key, parent, URL, IS_VIDEO, found) VALUES (0, -1, 'https://www.video.ethz.ch', 0, '{now}')")
        print("Table Created")

    def index_video_eth(self):
        """
        Starts the indexing of the site.
        :return:
        """
        # load main site
        resp = rq.get("https://www.video.ethz.ch/", headers={"user-agent": "Mozilla Firefox"})

        # get the html
        html = resp.content.decode("utf-8")

        # prepare for xpath
        tree = etree.HTML(html)
        x = tree.xpath("//a")

        uris = []

        # find all <a> elements
        for a in x:
            a: _Element

            # Verify that href is a key
            if "href" in a.keys():
                uri = a.attrib["href"]

                if self.val_uri(uri) and uri not in uris:
                    uris.append(uri)
                    print(f"uri {uri}")
                    self.sub_index(f"https://www.video.ethz.ch{uri}", uri)

        self.spawn()
        self.dequeue()

        # TODO: logger and debug shit
        print("Cleanup")
        self.cleanup()
        self.sq_con.commit()

    def __sub_index(self, url: str, prefix: str):
        """
        Function that loads sub site and then proceeds to search it for either a video div or a list of sub sites.
        Sub sites are put into the to_download queue, video urls are put in the video_url queue

        WARNING: This function is a member function of the same object. As a result it has access to the queues.
        HOWEVER, it can create data-races so DO NOT ACCESS ANYTHING ELSE OTHER THAN THE QUEUES!

        :param url: full url of sub site to index like https://www.video.ethz.ch/speakers/d-infk/2015.html
        :param prefix: prefix of the site, only searching urls with identical prefix, like /speakers/d-infk
        :return:
        """
        # load target site
        resp = rq.get(url, headers={"user-agent": "Mozilla Firefox"})
        # get the html
        html = resp.content.decode("utf-8")

        # prepare for xpath
        tree = etree.HTML(html)
        # x = tree.xpath("//a")

        # get the box where the list of 'child organizers' are stored say d-infk/[list of all years.]
        x = tree.xpath("//div[@class='newsListBox']/a")

        # dump the site to the list of video urls if it matches
        if is_video(tree):

            # TODO: logger and debug shit
            print(f"put {url}")
            self.found_url_queue.put({"url": url, "is_video": 1})
            return

        else:
            # TODO: logger and debug shit
            print(f"put {url}")
            self.found_url_queue.put({"url": url, "is_video": 0})

        # find all <a> elements
        for a in x:
            a: _Element

            # asure href is a key
            if "href" in a.keys():
                uri = a.attrib["href"]

                # verify it is on the same branch but not the same uri
                if (prefix.split(".")[0] in uri) and (prefix != uri):
                    self.sub_index(f"https://www.video.ethz.ch{uri}", uri)

        # TODO: logger and debug shit
        print(f"Done {url}")

    def cleanup(self):
        """
        Waits for all worker processes to terminate and then joins them.
        :return:
        """
        for worker in self.threads:
            worker: Thread
            worker.join(10)

    def spawn(self, threads: int = 100):
        """
        Spawns worker threads.

        :param threads: number of threads to spawn 1-10000
        :return:
        """
        if not 1 < threads < 10000:
            raise ValueError("Thread number outside supported range [1:10'000]")

        for i in range(threads):
            t = Thread(target=self.__indexer)
            t.start()
            self.threads.append(t)

        print("Workers Spawned")

    def __indexer(self):
        """
        Function executed by a worker thread. If the to_download queue is empty for 10s,
        the worker kills itself.
        For every target in the queue, it calls the __sub_index func.

        WARNING: This function is a member function of the same object. As a result it has access to the queues.
        HOWEVER, it can create data-races so DO NOT ACCESS ANYTHING ELSE OTHER THAN THE QUEUES!
        :return:
        """
        # after timeout of 10s the indexer subprocess kills itself
        counter = 0
        while counter < 10:
            try:
                # dequeue the next element
                target = self.to_download_queue.get(block=False)

                # perform sub index task
                self.__sub_index(target["url"], target["prefix"])

                # reset timeout
                counter = 0

            # sleep and timeout if queue is empty
            except Empty:
                counter += 1
                sleep(1)

    def sub_index(self, url: str, prefix: str):
        """
        Wrapper for __sub_index function. (Here to allow for multiprocessing) switch back in case you want to debug or
        test something, have here the self.__sub__index function

        :param url: full url of sub site to index like https://www.video.ethz.ch/speakers/d-infk/2015.html
        :param prefix: prefix of the site, only searching urls with identical prefix, like /speakers/d-infk
        :return:
        """
        self.to_download_queue.put({"url": url, "prefix": prefix})

    def dequeue(self):
        """
        Function retrieves the urls from the video_url queue and writes them to the file specified in init.
        Function exits after 10s of an empty queue or when all workers are done.
        :return:
        """
        # Timeout to prevent endless loop if a subprocesses crash
        insert_counter = 0
        counter = 0
        while counter < 10 and self.workers_alive():
            if not self.found_url_queue.empty():
                while not self.found_url_queue.empty():
                    arguments = self.found_url_queue.get()
                    url = arguments["url"]
                    a_video = arguments["is_video"]

                    try:
                        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if self.not_in_db(url):
                            self.sq_cur.execute("INSERT INTO sites (URL, IS_VIDEO, found) VALUES "
                                                f"('{url}', {a_video}, '{now}')")
                            self.sq_con.commit()
                            insert_counter += 1
                        else:
                            # TODO: logger and debug shit
                            print("Already in db")

                    except sqlite3.IntegrityError:
                        # TODO: logger and debug shit
                        print(traceback.format_exc())
                        print(arguments)
                    counter = 0
            else:
                counter += 1
                sleep(1)
        # TODO: logger and debug shit
        print(f"Inserted {insert_counter} entries in sites table")

    def not_in_db(self, url):
        """
        Verifies the url is not already in the database. (Search ONLY based on url)
        :param url:
        :return:
        """
        self.sq_cur.execute(f"SELECT key FROM sites WHERE URL = '{url}'")
        return self.sq_cur.fetchone() is None

    def gen_parent(self):
        """
        Generates the tree hierarchy for the site index.
        :return:
        """
        # temporary storage of parent url:key to parent_id:value.
        parent_ids = {}

        self.sq_cur.execute("SELECT key, URL FROM sites WHERE parent IS NULL")
        one = self.sq_cur.fetchone()

        # perform the parent linking while there are entries that have no parent.
        while one is not None:
            key = one[0]
            url = one[1]

            # generate the parent url from own url.
            parent_url = parent_site(url)

            # try to locate the parent_id in the temporary dictionary.
            parent_id = parent_ids.get(parent_url)

            # if no id is found, search the id and put it in the temp dict.
            if parent_id is None:
                parent_id = self.get_url_id(parent_url)
                parent_ids[parent_url] = parent_id

            # TODO: logging and debug shit
            print(f"UPDATE sites SET parent = {parent_id} WHERE key IS {key}")
            self.sq_cur.execute(f"UPDATE sites SET parent = {parent_id} WHERE key IS {key}")

            # Fetch the next entry which has no parent.
            self.sq_cur.execute("SELECT key, URL FROM sites WHERE parent IS NULL")
            one = self.sq_cur.fetchone()

    def get_url_id(self, url: str):
        """
        Given an url, the function searches the database for the url and returns the key. If it doesn't exist, it
        returns -1
        :param url: url to retrieve the key from.
        :return: key or -1 if no key found.
        """
        self.sq_cur.execute(f"SELECT (key) FROM sites WHERE URL IS '{url}'")
        query_result = self.sq_cur.fetchall()

        if len(query_result) == 0 or len(query_result[0]) == 0:
            return -1

        return query_result[0][0]

    def workers_alive(self):
        """
        Function to verify that at least one of the workers hasn't exited.
        :return:
        """
        for worker in self.threads:
            worker: Thread
            if worker.is_alive():
                return True

        return False
