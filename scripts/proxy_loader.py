import datetime
import requests as rq
from dataclasses import dataclass
import random


@dataclass
class Proxy:
    ip: str
    port: str


class RandomProxy:
    """
    Python wrapper for the proxylist.genode.com service. It fetches the current proxies and randomly returnes one of the
    proxies that 'are working'.
    """
    def __init__(self, update_interval: int = 600, anonymity: tuple = ("elite")):
        """
        Initializes the object with default values and performes a request to the api.

        :param update_interval: how frequently the proxy list should be updated. default 10min
        :param anonymity: Anonymity level of servers to filter.
        :return: Obj
        """
        if update_interval < 10:
            raise ValueError("update Interval needs to be greater than 10")
        self.proxy_list = []
        self.response_json_dict = {}
        self.last_update = datetime.datetime.now()
        self.update_proxies()
        self.update_interval = update_interval
        self.anonymity = anonymity

    def get_proxy(self):
        """
        Returns a Proxy object randomly from the list of available proxies.
        :return:
        """
        self.__update_one_time()
        return random.choice(self.proxy_list)

    def update_proxies(self):
        """
        Performs an api request and parses the result into python.
        :return:
        """
        res = rq.get("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc", headers={"user-agent": "Proxy-list-getter"})

        if res.ok:
            self.response_json_dict = res.json()
            self.__parse_proxies()

    def __parse_proxies(self):
        """
        Parses the response of the api request. Only selects the proxies that have anonymity level elite.
        :return:
        """
        proxy_objs = self.response_json_dict["data"]
        self.proxy_list = []

        for o in proxy_objs:
            if o["anonymityLevel"] in self.anonymity:
                self.proxy_list.append(Proxy(ip=o["ip"], port=o["port"]))

        self.last_update = datetime.datetime.now()

    def __update_one_time(self):
        """
        Updates the proxies every 10 min.
        :return:
        """
        if (datetime.datetime.now() - self.last_update).total_seconds() > self.update_interval:
            self.update_proxies()


if __name__ == "__main__":
    rdp = RandomProxy()
