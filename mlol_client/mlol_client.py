import logging
import re
from base64 import b64encode, b64decode
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List, Generator

import requests
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
    "pre_reserve": "/media/prenota.aspx",
    "reserve": "/media/prenota2.aspx",
    "cancel_reservation": "/media/annullaPr.aspx",
    "get_queue_position": "/commons/QueuePos.aspx",
    "api": {
        "login": "https://api.medialibrary.it/app/login",
        "portals": "https://api.medialibrary.it/app/portals",
        "loans_history": "https://api.medialibrary.it/app/loanhistory",
        "loans": "https://api.medialibrary.it/app/loans",
        "reservations": "https://api.medialibrary.it/app/reservations",
        "userinfo": "https://api.medialibrary.it/app/profile"
    },
}


class MLOLUser:
    def __init__(
        self,
        id: int,
        name: str,
        surname: str,
        username: str,
        remaining_loans: int,
        remaining_resvs: int,
        expiration_date: datetime,
    ):
        self.id = id
        self.name = name
        self.surname = surname
        self.username = username
        self.remaining_loans = remaining_loans
        self.remaining_resvs = remaining_resvs
        self.expiration_date = expiration_date

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLUser: {values}>"


class MLOLBook:
    def __init__(
        self,
        *,
        id: str,
        title: str,
        authors: str = None,
        status: str = None,
        publisher: str = None,
        ISBNs: List[str] = None,
        language: str = None,
        description: str = None,
        year: int = None,
        formats: List[str] = None,
        drm: bool = None,
        download_url: str = None,
    ):
        self.id = str(id)
        self.title = title
        self.authors = authors
        self.status = status
        self.publisher = publisher
        self.ISBNs = ISBNs
        self.language = language
        self.description = description
        self.year = year
        self.formats = formats
        self.drm = drm
        self.download_url = download_url

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLBook: {values}>"


class MLOLReservation:
    def __init__(
        self,
        *,
        id: str,
        book: MLOLBook,
        date: datetime = None,
        status: str = None,
        queue_position: int = None,
    ):
        self.id = str(id)
        self.book = book
        self.date = date
        self.status = status
        self.queue_position = queue_position

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLReservation: {values}>"


class MLOLLoan:
    def __init__(
        self,
        *,
        id: str,
        book: MLOLBook,
        start_date: datetime = None,
        end_date: datetime = None,
    ):
        self.id = str(id)
        self.book = book
        self.start_date = start_date
        self.end_date = end_date

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLLoan: {values}>"


class MLOLApiConverter:
    @staticmethod
    def get_date(date: str) -> datetime:
        # Convert 2020-12-20 into a datetime
        return datetime.strptime(date, "%Y-%m-%d")

    @staticmethod
    def get_book(api_response) -> MLOLBook:
        return MLOLBook(
            id=str(api_response["id"]),
            title=api_response["dc_title"],
            authors=api_response["dc_creator"],
            # status = None, I don't insert the status here...
            publisher=api_response["dc_source"],
            ISBNs=api_response["isbn"],
            # language = None, The API doesn't tell me this
            description=api_response["dc_description"],
            year=api_response["pubdate"].split('-')[0],
            formats=[f.strip().lower()
                     for f in api_response["dc_format"].split()[0].split("/")],
            drm="drm" in api_response["dc_format"].lower(),
            download_url=None if "url_download" not in api_response else api_response[
                "url_download"]
        )

    @staticmethod
    def get_reservation(api_response) -> MLOLReservation:
        return MLOLReservation(
            id=None,
            book=MLOLApiConverter.get_book(api_response),
            date=MLOLApiConverter.get_date(api_response["inserted"])
            # status = api_response["status"] # Is 'attiva' a correct value? I don't think so... shouldn't it always be 'reserved'?
            # As for the queue position, we don't know and this will be a problem since we cannot get the queue position...
        )

    @staticmethod
    def get_loan(api_response) -> MLOLLoan:
        return MLOLLoan(
            id=b64decode(api_response["url_download"].split('/')[-1]),
            book=MLOLApiConverter.get_book(api_response),
            start_date=MLOLApiConverter.get_date(api_response["acquired"]),
            end_date=MLOLApiConverter.get_date(api_response["expired"]),
        )

    @staticmethod
    def get_user(api_response) -> MLOLUser:
        return MLOLUser(api_response["userid"],
                        api_response["firstname"],
                        api_response["lastname"],
                        api_response["username"],
                        int(api_response["ebook_loans_remaining"]),
                        int(api_response["ebook_loans_remaining"]),
                        MLOLApiConverter.get_date(api_response["expires"])
                        )


class MLOLClient:
    max_threads = 5
    session = None
    # Token for the REST API
    token = None

    def __init__(self, *, domain=None, username=None, password=None, library_id_or_name=None):
        self.session = sessions.BaseUrlSession(
            base_url="https://medialibrary.it")
        self.session.headers.update(DEFAULT_HEADERS)

        if not (username and password and domain and library_id_or_name):
            logging.warning(
                "You did not provide authentication credentials and a subdomain. You will not be able to perform actions that require authentication."
            )
        else:
            library_id = self._get_library_id_from_string(library_id_or_name)[
                0]
            self.domain = domain
            self.username = username
            self.session.base_url = "https://" + re.sub(
                r"https?(://)", "", domain.rstrip("/")
            )
            self.session.cookies = self._get_auth_cookies(
                username, password, str(library_id))
            self.token = self._get_api_token(
                username, password, str(library_id))

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

    def _get_auth_cookies(self, username: str, password: str, library_id: str) -> RequestsCookieJar:
        # using RoboBrowser to avoid keeping a mapping of MLOL subdomains to their numeric IDs
        # a POST request including a "lente" param would be enough
        browser = RoboBrowser(parser="html.parser",
                              user_agent=DEFAULT_USER_AGENT)
        browser.open(f"{self.session.base_url}{ENDPOINTS['login']}")
        form = [f for f in browser.get_forms() if "lusername" in f.fields][0]
        form["lusername"] = username
        form["lpassword"] = password
        if library_id is not None:
            form["lente"] = library_id
        browser.submit_form(form)
        return browser.session.cookies

    def _get_api_token(self, username: str, password: str, library_id: str) -> str:
        return requests.post(ENDPOINTS["api"]["login"], data={"username": username, "password": password, "portal": library_id, "app_code": ""}).json()["token"]

    def _get_queue_position(self, reservation_id: str) -> Optional[int]:
        params = {"id": reservation_id}
        response = self.session.request(
            "GET", url=ENDPOINTS["get_queue_position"], params=params
        )

        if "in coda" in response.text and (
            queue_position := re.search(r"\d+(?=°)", response.text)
        ):
            return int(queue_position.group())

        logging.error(
            f"Failed to get queue position for reservation #{reservation_id}")
        return

    @staticmethod
    def _get_library_id_from_string(search: str) -> List[int]:
        return [i["id"] for i in requests.get(ENDPOINTS["api"]["portals"]).json() if str(i["id"]) == search or i["name"].find(search) != -1]

    @staticmethod
    def _parse_search_page(page: Tag) -> List[MLOLBook]:
        books = []
        for i, book in enumerate(page.select(".result-item")):
            try:
                ID_RE = r"(?<=id=)\d+$"
                title = book.find("h4").attrs["title"]
                url = book.find("a").attrs["href"]
                id = re.search(ID_RE, url).group()
            except:
                logging.error(
                    f"Could not parse ID or title. Skipping book #{i+1}...")
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

    @staticmethod
    def _parse_book_status(status: str) -> Optional[str]:
        status = status.strip().lower()
        if "scarica" in status:
            return "available"
        if "ripeti" in status:
            return "owned"
        if "prenotato" in status:
            return "reserved"
        if "occupato" in status:
            return "taken"
        if "non disponibile" in status:
            return "unavailable"
        return None

    @staticmethod
    def _parse_book_page(page: Tag) -> dict:
        book_data = defaultdict(lambda: None)

        if title := page.select_one(".book-title"):
            book_data["title"] = title.text.strip()

        if authors := page.select_one(".authors_title"):
            book_data["authors"] = [a.strip()
                                    for a in authors.text.strip().split(";")]

        if publisher := page.select_one(".publisher_title > span > a"):
            book_data["publisher"] = publisher.text.strip()

        if ISBNs := page.find_all(attrs={"itemprop": "isbn"}):
            book_data["ISBNs"] = [i.text.strip() for i in ISBNs]

        if status_element := page.select_one(".panel-mlol"):
            book_data["status"] = MLOLClient._parse_book_status(
                status_element.text.strip()
            )

        if description := next(
            filter(
                lambda x: hasattr(x, "text"),
                page.find("div", attrs={"itemprop": "description"}),
            )
        ):
            book_data["description"] = description.text.strip()

        if language := page.find("span", attrs={"itemprop": "inLanguage"}):
            book_data["language"] = language.text.strip()

        if year := page.find("span", attrs={"itemprop": "datePublished"}):
            book_data["year"] = int(year.text.strip())

        try:
            # e.g. "EPUB/PDF con DRM Adobe"
            formats_str = (
                page.find("b", text=re.compile("FORMATO"))
                .parent.parent.find("span")
                .text.strip()
            )
            book_data["drm"] = "drm" in formats_str.lower()
            book_data["formats"] = [
                f.strip().lower() for f in formats_str.split()[0].split("/")
            ]
        except:
            logging.warning(
                f"Failed to parse formats for book {book_data['title']}")

        return book_data

    @staticmethod
    def _parse_active_loan(loan_el: Tag, *, index: int = -1) -> Optional[MLOLLoan]:
        loan_id = book_id = None
        if loan_id_element := loan_el.find(
            "a", attrs={"href": re.compile(r"(?<=idp=)\d+$")}
        ):
            loan_id = re.search(
                r"(?<=\=)\d+$", loan_id_element.attrs["href"]).group()
        else:
            logging.error(f"Could not find loan ID for loan #{index + 1}")
            return

        if book_id_element := loan_el.find(
            "a", attrs={"href": re.compile(r"(?<=scheda.aspx\?id=)\d+$")}
        ):
            book_id = re.search(
                r"(?<=\=)\d+$", book_id_element.attrs["href"]).group()
        else:
            logging.error(f"Could not find book ID for loan #{index + 1}")
            return

        loan = MLOLLoan(id=loan_id, book=MLOLBook(id=book_id, title=""))

        if book_title_el := loan_el.select_one("div > div > h3"):
            loan.book.title = book_title_el.text.strip()

        if authors_el := loan_el.find("span", attrs={"itemprop": "author"}):
            loan.book.authors = [a.strip()
                                 for a in authors_el.text.strip().split(";")]

        table_els = loan_el.select("tr")
        start_date_els = [c for c in table_els[0] if c != "\n"]
        end_date_els = [c for c in table_els[1] if c != "\n"]
        if start_date_els and len(start_date_els) >= 3:
            start_date = start_date_els[1].text.strip()
            start_time = start_date_els[2].text.strip()
            loan.start_date = datetime.strptime(
                f"{start_date} {start_time}", "%d/%m/%Y %H:%M"
            )

        if end_date_els and len(end_date_els) >= 3:
            end_date = end_date_els[1].text.strip()
            end_time = end_date_els[2].text.strip()
            loan.end_date = datetime.strptime(
                f"{end_date} {end_time}", "%d/%m/%Y %H:%M"
            )

        return loan

    @staticmethod
    def _parse_reservation(
        reservation_el: Tag, *, index: int = -1
    ) -> Optional[MLOLReservation]:
        reservation_id = book_id = None
        if reservation_id_element := reservation_el.find(
            "a", attrs={"href": re.compile(r"(?<=annullaPr.aspx\?id=)\d+$")}
        ):
            reservation_id = re.search(
                r"(?<=\=)\d+$", reservation_id_element.attrs["href"]
            ).group()
        else:
            logging.error(
                f"Could not find loan ID for reservation #{index + 1}")
            return

        if book_id_element := reservation_el.find(
            "a", attrs={"href": re.compile(r"(?<=scheda.aspx\?id=)\d+$")}
        ):
            book_id = re.search(
                r"(?<=\=)\d+$", book_id_element.attrs["href"]).group()
        else:
            logging.error(
                f"Could not find book ID for reservation #{index + 1}")
            return

        reservation = MLOLReservation(
            id=reservation_id, book=MLOLBook(id=book_id, title="")
        )

        if book_title_el := reservation_el.select_one("div > div > h3"):
            reservation.book.title = book_title_el.text.strip()

        if authors_el := reservation_el.find("span", attrs={"itemprop": "author"}):
            reservation.book.authors = [
                a.strip() for a in authors_el.text.strip().split(";")
            ]

        table_els = reservation_el.select("tr")
        datetime_els = [c for c in table_els[0] if c != "\n"]
        status_els = [c for c in table_els[1] if c != "\n"]
        if datetime_els and len(datetime_els) >= 3:
            date = datetime_els[1].text.strip()
            time = datetime_els[2].text.strip()
            reservation.date = datetime.strptime(
                f"{date} {time}", "%d/%m/%Y %H:%M")

        if status_els and len(status_els) >= 2:
            # TODO discover more statuses
            if status_els[1].find("b").text.strip() == "attiva":
                reservation.status = "active"

        return reservation

    def _redownload_owned_book(self, book_id: str) -> Response:
        active_loans = self.get_resources()["active_loans"]
        if loan_id := next((l.id for l in active_loans if l.book_id == book_id), None):
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

        logging.error(f"Failed to find owned book {book_id} in your profile")
        raise

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
                    url=ENDPOINTS["search"],
                    params={**req_params, **{"page": i}},
                )
            )
            books = self._parse_search_page(
                BeautifulSoup(response.text, "html.parser"))
            if deep:
                with ThreadPoolExecutor(
                    max_workers=min(len(books), self.max_threads)
                ) as executor:
                    yield list(executor.map(self.get_book_by_id, (b.id for b in books)))
            else:
                yield books

    def _scrape_resources(self, *, deep=False) -> dict:
        reservations = []
        response = self.session.request("GET", ENDPOINTS["resources"])
        soup = BeautifulSoup(response.text, "html.parser")

        if reservations_el := soup.select_one("#mlolreservation"):
            for i, reservation_el in enumerate(
                reservations_el.select("div.bottom-buffer")
            ):
                reservation = self._parse_reservation(reservation_el, index=i)
                reservation.queue_position = self._get_queue_position(
                    reservation.id)
                if deep:
                    reservation.book = self.get_book_by_id(reservation.book.id)
                reservations.append(reservation)

        return [r for r in reservations if r is not None]

    def get_book_by_id(self, book_id: str) -> Optional[MLOLBook]:
        logging.debug(f"Fetching book {book_id}")
        response = self.session.request(
            "GET",
            url=ENDPOINTS["get_book"],
            params={"id": book_id},
        )
        if "alert.aspx" in response.url:
            logging.warning(
                f"Failed to fetch book {book_id}. Might not be available to your library."
            )
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        book_data = self._parse_book_page(soup)
        if book_data["title"] is None:
            logging.warning(
                f"Failed to get book title for id {book_id}, skipping...")
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
            formats=book_data["formats"],
            drm=book_data["drm"],
        )

    def get_book(self, book: MLOLBook) -> Optional[MLOLBook]:
        if not isinstance(book, MLOLBook):
            raise ValueError(f"Expected MLOLBook, got {type(book)}")

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
            logging.error(
                f"Book is not available for download. Status: {book.status}")
            return
        else:
            response = self.session.request(
                "GET",
                url=ENDPOINTS["download"],
                headers={
                    **self.session.headers,
                    **{
                        "Host": self.session.base_url.replace("https://", ""),
                        "Referer": f"{self.session.base_url}/media/downloadebad2.aspx?unid={book_id}&form=epub",
                    },
                },
                params={"unid": book_id, "form": "epub"},
                allow_redirects=False,
            )

        if response.status_code == 302:
            response = self.session.request(
                "GET",
                url=response.headers["Location"],
                headers={**self.session.headers, **
                         {"Sec-Fetch-Site": "cross-site"}},
            )

        if response.text.startswith("<fulfillmentToken"):
            logging.info(f"Book {book_id} downloaded")
            return response.content
        else:
            logging.error(f"Failed to download book {book_id}")
            logging.debug(response.text)
            return None

    def download_book(self, book: MLOLBook) -> Optional[bytes]:
        if not isinstance(book, MLOLBook):
            raise ValueError(f"Expected MLOLBook, got {type(book)}")

        if book.download_url is not None:
            return requests.get(book.download_url).content

        return self.download_book_by_id(book.id)

    def get_book_url_by_id(self, book_id: str) -> str:
        return f"{self.session.base_url}{ENDPOINTS['get_book']}?id={book_id}"

    def get_book_url(self, book: MLOLBook) -> str:
        return self.get_book_url_by_id(book.id)

    def reserve_book_by_id(self, book_id: str, *, email: str) -> Optional[bool]:
        if not self.session.cookies.get(".ASPXAUTH"):
            logging.error(
                "You need to be authenticated to MLOL in order to download books."
            )
            return

        book = self.get_book_by_id(book_id)
        if book.status != "taken":
            logging.error(
                f"You can only reserve taken books. Book status: {book.status}"
            )

        headers = {
            **self.session.headers,
            **{
                "Host": self.session.base_url.replace("https://", ""),
                "Referer": f"{self.session.base_url}{ENDPOINTS['pre_reserve']}?id={book_id}",
                "Accept": "text/html, */*; q=0.01",
            },
        }

        response = self.session.request(
            "GET",
            # don't pass params, build the URL directly to avoid percent encoding
            url=f"{ENDPOINTS['reserve']}?id={book_id}&email={email}",
            headers=headers,
        )
        soup = BeautifulSoup(response.text, "html.parser")
        if outcome := soup.select_one("#lblInfo"):
            message = outcome.text.strip().lower()
            if "con successo" in message:
                return True
            elif "prenotazione attiva" in message:
                logging.warning(
                    f"You already have an active reservation for book #{book_id}"
                )
                return True
            else:
                logging.error(f"Failed to reserve book #{book_id}")
                return False

        logging.error(
            f"Failed to reserve book with ID {book_id} (unknown outcome)")

    def reserve_book(self, book: MLOLBook, *, email: str) -> bool:
        if not isinstance(book, MLOLBook):
            raise ValueError(f"Expected MLOLBook, got {type(book)}")

        return self.reserve_book_by_id(book.id, email=email)

    def cancel_reservation_by_id(self, reservation_id: str) -> Optional[bool]:
        params = {"id": reservation_id}
        headers = {
            **self.session.headers,
            **{
                "Host": self.session.base_url.replace("https://", ""),
                "Referer": f"{self.session.base_url}/user/risorse.aspx",
                "Accept-Encoding": "gzip, deflate, br",
            },
        }
        response = self.session.request(
            "GET",
            url=ENDPOINTS["cancel_reservation"],
            headers=headers,
            params=params,
            allow_redirects=False,
        )
        redirect_url = response.headers["Location"]

        if redirect_url.endswith("msg=970"):
            # this is a "success" redirect
            return True
        elif redirect_url.endswith("msg=960"):
            # "error" redirect
            logging.error(f"Failed to cancel reservation #{reservation_id}")
            return False
        else:
            logging.error(
                f"Failed to cancel reservation #{reservation_id} (unknown outcome)"
            )

    def cancel_book_reservation(self, book: MLOLBook) -> Optional[bool]:
        if not isinstance(book, MLOLBook):
            raise ValueError(f"Expected MLOLBook, got {type(book)}")

        if not self.session.cookies.get(".ASPXAUTH"):
            logging.error(
                "You need to be authenticated to MLOL in order to manage reservations."
            )
            return

        if book.status is None:
            book = self.get_book_by_id(book.id)

        if book.status != "reserved":
            logging.error(
                f"You don't have book #{book.id} reserved. Status: {book.status}"
            )
            return False

        for reservation in self._scrape_resources()["reservations"]:
            if reservation.book_id == book.id:
                return self.cancel_reservation_by_id(reservation.id)

        logging.error(
            f"Could not cancel reservation for book #{book.id} (reservation ID not found)"
        )
        return

    def get_resources(self, *, deep=False) -> dict:
        reservations = self._scrape_resources(deep=deep)

        return {
            "active_loans": [MLOLApiConverter.get_loan(l) for l in requests.get(
                ENDPOINTS["api"]["loans"],
                params={"token": self.token}
            ).json()["loans"]],
            "reservations": reservations,
            "history": [MLOLApiConverter.get_loan(r) for r in requests.get(
                ENDPOINTS["api"]["loans_history"],
                params={"token": self.token}
            ).json()["loans"]],
        }

    def search_books(
        self, query: str, *, deep: bool = False
    ) -> Generator[List[MLOLBook], None, None]:
        params = {"seltip": 310, "keywords": query.strip(), "nris": 48}
        response = self.session.request(
            "GET", url=ENDPOINTS["search"], params=params)
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
        response = self.session.request(
            "GET", url=ENDPOINTS["search"], params=params)
        soup = BeautifulSoup(response.text, "html.parser")

        try:
            pages = int(soup.select_one("#pager").attrs["data-pages"])
        except AttributeError:
            pages = 1

        return self._search_books_paginated(
            req_params=params, deep=deep, pages=pages, first_response=response
        )

    def get_user_info(self) -> MLOLUser:
        return MLOLApiConverter.get_user(requests.get(ENDPOINTS["api"]["userinfo"], params={"token": self.token}).json())
