import datetime
from eth_loader.stream_loader import ConcurrentETHIndexer

if __name__ == "__main__":
    start = datetime.datetime.now()
    print("Started")
    eid = ConcurrentETHIndexer("seq_sites.txt")
    eid.index_video_eth()
    end = datetime.datetime.now()
    print(f"required {(end - start).total_seconds()}s")
