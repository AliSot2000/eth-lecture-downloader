import datetime
# from eth_loader.stream_loader import ConcurrentETHIndexer
from eth_loader.indexer import ConcurrentETHIndexer, ETHIndexer

if __name__ == "__main__":
    start = datetime.datetime.now()
    print("Started")
    eid = ETHIndexer("seq_sites.db")
    eid.index_video_eth()
    end = datetime.datetime.now()
    print(f"required {(end - start).total_seconds()}s")
