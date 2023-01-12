from eth_loader.stream_loader import SpecLogin

user_name = "<your username>"
password = "<your password>"
spec_login = [
    # url="https://www.video.ethz.ch/lectures/d-infk/2021/autumn/252-0027-00L"   # EXAMPLE
    SpecLogin(password="<lecture password>",
              username="<lecture username>",
              url="<url to lecture>")
]