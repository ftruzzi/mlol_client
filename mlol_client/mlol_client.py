import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Generator

from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from requests.cookies import RequestsCookieJar
from requests.models import Response
from requests.packages.urllib3.util.retry import Retry
from requests_toolbelt import sessions
from robobrowser import RoboBrowser

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.67 Safari/537.36"
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Upgrade-Insecure-Requests": "1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}
ENDPOINTS = {
    "search": "/media/ricerca.aspx",
    "login": "/user/logform.aspx",
    "resources": "/user/risorse.aspx",
    "get_book": "/media/scheda.aspx",
    "redownload": "/help/dlrepeat.aspx",
    "download": "/media/downloadebadok.aspx",
}


class MLOLBook:
    def __init__(
        self,
        *,
        id,
        title,
        authors=None,
        status=None,
        publisher=None,
        ISBNs=None,
        language=None,
        description=None,
        year=None,
    ):
        self.id = id
        self.title = title
        self.authors = authors
        self.status = status
        self.publisher = publisher
        self.ISBNs = ISBNs
        self.language = language
        self.description = description
        self.year = year

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLBook: {values}>"


class MLOLClient:
    max_threads = 5
    session = None

    def __init__(self, *, domain=None, username=None, password=None):
        self.session = sessions.BaseUrlSession(base_url="https://medialibrary.it")
        self.session.headers.update(DEFAULT_HEADERS)

        if not (username and password and domain):
            logging.warning(
                "You did not provide authentication credentials and a subdomain. You will not be able to perform actions that require authentication."
            )
        else:
            self.domain = domain
            self.username = username
            self.session.base_url = "https://" + re.sub(
                r"https?(://)", "", domain.rstrip("/")
            )
            self.session.cookies = self._get_auth_cookies(username, password)

        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[404, 429, 500, 502, 503, 504],
                method_whitelist=["HEAD", "GET", "OPTIONS"],
            )
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        assert_status_hook = (
            lambda response, *args, **kwargs: response.raise_for_status()
        )
        self.session.hooks["response"] = [assert_status_hook]

    def __repr__(self):
        values = {k: v for k, v in self.__dict__.items()}
        values["password"] = "***"
        return f"<mlol_client.MLOLClient: {values}"

    def _get_auth_cookies(self, username: str, password: str) -> RequestsCookieJar:
        # using RoboBrowser to avoid keeping a mapping of MLOL subdomains to their numeric IDs
        # a POST request including a "lente" param would be enough
        browser = RoboBrowser(parser="html.parser", user_agent=DEFAULT_USER_AGENT)
        browser.open(f"{self.session.base_url}{ENDPOINTS['login']}")
        form = [f for f in browser.get_forms() if "lusername" in f.fields][0]
        form["lusername"] = username
        form["lpassword"] = password
        browser.submit_form(form)
        return browser.session.cookies

    def _parse_search_page(self, page: Tag) -> List[MLOLBook]:
        books = []
        for i, book in enumerate(page.select(".result-item")):
            try:
                ID_RE = r"(?<=id=)\d+$"
                title = book.find("h4").attrs["title"]
                url = book.find("a").attrs["href"]
                id = re.search(ID_RE, url).group()
            except Exception as e:
                logging.error(f"Could not parse ID or title. Skipping book #{i+1}...")
                continue

            try:
                author_el = book.select("p > a.authorref")
                if len(author_el) > 0:
                    authors = author_el[0].string.strip()
                else:
                    author_el = page.find("p")
                    if author_el.attrs["itemprop"] == "author":
                        authors = author_el.string.strip()
            except Exception:
                authors = None

            books.append(
                MLOLBook(
                    id=id,
                    title=title,
                    authors=[a.strip() for a in authors.split(";")]
                    if authors
                    else None,
                )
            )

        return books

    def _parse_book_status(self, status: str) -> str:
        status = status.strip().lower()
        if "scarica" in status:
            return "available"
        if "ripeti" in status:
            return "owned"
        if "occupato" in status:
            return "taken"
        if "non disponibile" in status:
            return "unavailable"
        return None

    def _parse_book_page(self, page: Tag) -> dict:
        title = (
            authors
        ) = publisher = ISBNs = status = description = language = year = None

        try:
            title = page.select(".book-title")[0].text.strip()
            authors = [
                a.strip()
                for a in page.select(".authors_title")[0].text.strip().split(";")
            ]
            publisher = page.select(".publisher_title > span > a")[0].text.strip()
            ISBNs = [i.text.strip() for i in page.find_all(attrs={"itemprop": "isbn"})]
            status = self._parse_book_status(page.select(".panel-mlol")[0].text.strip())
            description = next(
                filter(
                    lambda x: hasattr(x, "text"),
                    page.find("div", attrs={"itemprop": "description"}),
                )
            ).text.strip()
            language = page.find("span", attrs={"itemprop": "inLanguage"}).text.strip()
            year = int(
                page.find("span", attrs={"itemprop": "datePublished"}).text.strip()
            )
        except AttributeError as e:
            # silently fail if we can't get specific values -- not all books have them
            pass

        return {
            "title": title,
            "authors": authors,
            "publisher": publisher,
            "ISBNs": ISBNs,
            "status": status,
            "description": description,
            "language": language,
            "year": year,
        }

    def _redownload_owned_book(self, book_id: str) -> Response:
        response = self.session.request("GET", url=ENDPOINTS["resources"])
        soup = BeautifulSoup(response.text, "html.parser")
        try:
            loan_entry = soup.find(
                "a", attrs={"href": re.compile(f"({book_id})")}
            ).parent.parent
            loan_id = re.search(
                r"(?<=idp=)\d+$",
                loan_entry.select(".download_button.bottom-buffer-10 > a")[0]
                .attrs["href"]
                .lstrip(".."),
            ).group()
        except Exception as e:
            logging.error(f"Failed to find owned book {book_id} in your profile")
            raise

        response = self.session.request(
            "GET",
            url=ENDPOINTS["redownload"],
            headers={
                **self.session.headers,
                **{
                    "Host": self.session.base_url.replace("https://", ""),
                    "Referer": f"{self.session.base_url}/help/helpdeskdl.aspx?idp={loan_id}",
                },
            },
            params={"idp": loan_id},
            allow_redirects=False,
        )
        return response

    def get_book_by_id(self, book_id: str) -> Optional[MLOLBook]:
        logging.debug(f"Fetching book {book_id}")
        response = self.session.request(
            "GET",
            url=ENDPOINTS["get_book"],
            params={"id": book_id},
        )
        if "alert.aspx" in response.url:
            logging.warning(f"Failed to fetch book {book_id}. Might not be available to your library.")
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        book_data = self._parse_book_page(soup)
        if book_data["title"] is None:
            logging.warning(f"Failed to get book title for id {book_id}, skipping...")
            return None

        return MLOLBook(
            id=book_id,
            title=book_data["title"],
            authors=book_data["authors"],
            publisher=book_data["publisher"],
            ISBNs=book_data["ISBNs"],
            status=book_data["status"],
            language=book_data["language"],
            description=book_data["description"],
            year=book_data["year"],
        )

    def get_book(self, book: MLOLBook) -> Optional[MLOLBook]:
        return self.get_book_by_id(book.id)

    def download_book_by_id(self, book_id: str) -> Optional[bytes]:
        if not self.session.cookies.get(".ASPXAUTH"):
            logging.error(
                "You need to be authenticated to MLOL in order to download books."
            )
            return

        book = self.get_book_by_id(book_id)
        if book.status == "owned":
            logging.info("You already own this book. Redownloading...")
            response = self._redownload_owned_book(book_id)
        elif book.status != "available":
            logging.error(f"Book is not available for download. Status: {book.status}")
            return
        else:
            response = self.session.request(
                "GET",
                url=ENDPOINTS["download"],
                headers={
                    **self.session.headers,
                    **{
                        "Host": self.session.base_url.lstrip("https://"),
                        "Referer": f"{self.session.base_url}/media/downloadebad2.aspx&unid={book_id}&form=epub",
                    },
                },
                params={"unid": book_id, "form": "epub"},
                allow_redirects=False,
            )

        if response.status_code == 302:
            response = self.session.request(
                "GET",
                url=response.headers["Location"],
                headers={**self.session.headers, **{"Sec-Fetch-Site": "cross-site"}},
            )

        if response.text.startswith("<fulfillmentToken"):
            logging.info(f"Book {book_id} downloaded")
            return response.content
        else:
            logging.error(f"Failed to download book {book_id}")
            logging.debug(response.text)
            return None

    def download_book(self, book: MLOLBook) -> Optional[bytes]:
        return self.download_book_by_id(book.id)

    def _search_books_paginated(
        self,
        *,
        req_params: dict,
        pages: int,
        deep: bool = False,
        first_response: Response = None,
    ) -> Generator[List[MLOLBook], None, None]:
        for i in range(1, pages + 1):
            response = (
                first_response
                if pages == 1
                else self.session.request(
                    method="GET",
                    endpoint=ENDPOINTS["search"],
                    params={**req_params, **{"page": i}},
                )
            )
            books = self._parse_search_page(BeautifulSoup(response.text, "html.parser"))
            if deep:
                with ThreadPoolExecutor(
                    max_workers=min(len(books), self.max_threads)
                ) as executor:
                    yield list(executor.map(self.get_book_by_id, (b.id for b in books)))
            else:
                yield books

    def search_books(
        self, query: str, *, deep: bool = False
    ) -> Generator[List[MLOLBook], None, None]:
        params = {"seltip": 310, "keywords": query.strip(), "nris": 48}

        response = self.session.request("GET", url=ENDPOINTS["search"], params=params)
        soup = BeautifulSoup(response.text, "html.parser")

        try:
            pages = int(soup.select_one("#pager").attrs["data-pages"])
        except AttributeError:
            pages = 1

        return self._search_books_paginated(
            req_params=params, deep=deep, pages=pages, first_response=response
        )

    def get_latest_books(
        self, *, deep: bool = False
    ) -> Generator[List[MLOLBook], None, None]:
        params = {"seltip": 310, "news": "15day", "nris": 48}

        response = self.session.request("GET", url=ENDPOINTS["search"], params=params)
        soup = BeautifulSoup(response.text, "html.parser")

        try:
            pages = int(soup.select_one("#pager").attrs["data-pages"])
        except AttributeError:
            pages = 1

        return self._search_books_paginated(
            req_params=params, deep=deep, pages=pages, first_response=response
        )

    def get_book_url_by_id(self, book_id: str) -> str:
        return f"{self.session.base_url}{ENDPOINTS['get_book']}?id={book_id}"

    def get_book_url(self, book: MLOLBook) -> str:
        return self.get_book_url_by_id(book.id)
