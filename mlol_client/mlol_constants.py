import os

LIBRARY_MAPPING_FNAME = os.path.join(os.path.dirname(__file__), "library_mapping.json")

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.67 Safari/537.36"
DEFAULT_WEB_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Upgrade-Insecure-Requests": "1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

WEB_ENDPOINTS = {
    "index": "/home/index.aspx",
    "search": "/media/ricerca.aspx",
    "login": "/user/login.aspx",
    "resources": "/user/risorse.aspx",
    "get_book": "/media/scheda.aspx",
    "redownload": "/help/dlrepeat.aspx",
    "download": "/media/downloadebadok.aspx",
    "pre_reserve": "/media/prenota.aspx",
    "reserve": "/media/prenota2.aspx",
    "cancel_reservation": "/media/annullaPr.aspx",
    "get_queue_position": "/commons/QueuePos.aspx",
}

# taken from MLOL mobile app
DEFAULT_API_HEADERS = {
    "Host": "api.medialibrary.it",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "User-Agent": "okhttp/3.9.0",
}

API_ENDPOINTS = {
    "login": "https://api.medialibrary.it/app/login",
    "portals": "https://api.medialibrary.it/app/portals",
    "loan_history": "https://api.medialibrary.it/app/loanhistory",
    "loans": "https://api.medialibrary.it/app/loans",
    "userinfo": "https://api.medialibrary.it/app/profile",
}
