import json
import logging
import os
import re
import time
from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from shutil import copy
from typing import Optional, List, Generator

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.models import Response
from requests.packages.urllib3.util.retry import Retry
from requests_toolbelt import sessions

from .mlol_constants import (
    WEB_ENDPOINTS,
    API_ENDPOINTS,
    DEFAULT_API_HEADERS,
    DEFAULT_WEB_HEADERS,
    LIBRARY_MAPPING_FNAME,
)
from .mlol_types import MLOLBook, MLOLLoan, MLOLReservation, MLOLUser
from .mlol_parsers import _parse_search_page, _parse_book_page, _parse_reservation


class MLOLApiConverter:
    @staticmethod
    def get_loan_id(download_url: str) -> Optional[str]:
        try:
            return b64decode(download_url.split("/")[-1]).decode()
        except:
            logging.error("Failed to retrieve loan ID")
            return

    @staticmethod
    def get_date(date: str) -> datetime:
        return datetime.strptime(date, "%Y-%m-%d")

    @staticmethod
    def get_book(api_response) -> MLOLBook:
        # from "Bianchi, Luca|Rossi, Mario"
        # to ["Luca Bianchi", "Mario Rossi"]
        authors = [
            " ".join(list(reversed(a.split(", "))))
            for a in api_response["dc_creator"].split("|")
        ]

        return MLOLBook(
            # skip: description (not a string), language, status (not returned)
            id=str(api_response["id"]),
            title=api_response["dc_title"].strip(),
            authors=authors,
            publisher=api_response["dc_source"],
            # website also returns paper ISBN
            ISBNs=[api_response["isbn"]],
            year=MLOLApiConverter.get_date(api_response["pubdate"]).year,
            formats=[
                f.strip().lower()
                for f in api_response["dc_format"].split()[0].split("/")
            ],
            drm="drm" in api_response["dc_format"].lower(),
        )

    @staticmethod
    def get_loan(api_response) -> Optional[MLOLLoan]:
        if "url_download" not in api_response:
            return

        loan_id = MLOLApiConverter.get_loan_id(api_response["url_download"])

        return MLOLLoan(
            id=loan_id if loan_id else None,
            book=MLOLApiConverter.get_book(api_response),
            start_date=MLOLApiConverter.get_date(api_response["acquired"]),
            end_date=MLOLApiConverter.get_date(api_response["expired"]),
        )

    @staticmethod
    def get_user(api_response) -> MLOLUser:
        return MLOLUser(
            id=api_response["userid"],
            name=api_response["firstname"].capitalize(),
            surname=api_response["lastname"].capitalize(),
            username=api_response["username"],
            remaining_loans=int(api_response["ebook_loans_remaining"]),
            remaining_reservations=int(api_response["ebook_reservations_remaining"]),
            expiration_date=MLOLApiConverter.get_date(api_response["expires"]),
        )


class MLOLClient:
    max_threads = 5
    library_id = None
    session = None
    api_token = None

    def __init__(
        self,
        *,
        domain: str = None,
        username: str = None,
        password: str = None,
        library_id: str = None,
    ):
        self.session = sessions.BaseUrlSession(base_url="https://medialibrary.it")
        self.session.headers.update(DEFAULT_WEB_HEADERS)
        if domain:
            self.domain = domain
            self.session.base_url = "https://" + re.sub(
                r"https?(://)", "", domain.rstrip("/")
            )

        if not (username and password and domain):
            logging.warning(
                "You did not provide authentication credentials and a domain. You will not be able to perform actions that require authentication."
            )
        else:
            self.username = username
            if library_id:
                if isinstance(library_id, int):
                    library_id = str(library_id)
                self.library_id = library_id
            elif saved_library_id := self._get_saved_library_id():
                self.library_id = saved_library_id

            self._authenticate(
                username=username,
                password=password,
                library_id=library_id if library_id else saved_library_id,
            )

        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[404, 429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"],
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

    def _login_web(self, *, username: str, password: str, library_id: str):
        headers = {
            **self.session.headers,
            **{
                "Host": self.domain.replace("https://", ""),
                "Origin": self.domain,
                "Referer": f"{self.session.base_url}/user/logform.aspx",
            },
        }
        data = {"lusername": username, "lpassword": password, "lente": library_id}
        response = self.session.request(
            "POST",
            url=WEB_ENDPOINTS["login"],
            headers=headers,
            data=data,
            allow_redirects=False,
        )
        if response.headers["Location"] == "/media/esplora.aspx":
            return True

        return False

    def _get_saved_library_id(self) -> Optional[str]:
        if (
            not os.path.isfile(LIBRARY_MAPPING_FNAME)
            or os.stat(LIBRARY_MAPPING_FNAME).st_size == 0
        ):
            return

        with open(LIBRARY_MAPPING_FNAME, "r", encoding="utf8") as f:
            try:
                data = json.load(f)
            except:
                logging.warning("Couldn't read library mapping file.")
                return

        k = f"{self.username}@{self.domain}"
        if k in data and data[k]:
            logging.debug(f"Found library ID for {k} in mapping file.")
            return data[k]

    def _update_library_mapping(self, library_id):
        if os.path.isfile(LIBRARY_MAPPING_FNAME):
            with open(LIBRARY_MAPPING_FNAME, "r", encoding="utf8") as f:
                try:
                    data = json.load(f)
                except:
                    if os.stat(LIBRARY_MAPPING_FNAME).st_size != 0:
                        logging.warning(
                            "Couldn't read library mapping file. Backing up and overwriting..."
                        )
                        copy(
                            LIBRARY_MAPPING_FNAME,
                            f"{LIBRARY_MAPPING_FNAME}_{int(time.time())}.bak",
                        )
                    data = {}
        else:
            data = {}

        k = f"{self.username}@{self.domain}"
        data[k] = library_id

        with open(LIBRARY_MAPPING_FNAME, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return True

    def _authenticate(
        self, username: str, password: str, library_id: str
    ) -> Optional[bool]:

        if not library_id:
            response = self.session.request("GET", url=WEB_ENDPOINTS["index"])
            soup = BeautifulSoup(response.text, "html.parser")
            # get all "lente" values for subdomain, try all
            if library_id_els := soup.select("#lente > option"):
                library_id_values = [
                    o.attrs["value"] for o in library_id_els if "value" in o.attrs
                ]
                for l_id in library_id_values:
                    if self._login_web(
                        username=username, password=password, library_id=l_id
                    ):
                        logging.debug(
                            f"Found library ID for username {username} on {self.domain}: {l_id}"
                        )
                        self.library_id = l_id
                        self._update_library_mapping(l_id)
                        break

            if not self.library_id:
                logging.error(
                    "Login failed. Please make sure your credentials are valid or try to specify a manual library ID."
                )
                return
        else:
            if not self._login_web(
                username=username, password=password, library_id=library_id
            ):
                logging.error(
                    "Login failed. Please make sure your credentials are valid."
                )
                return False

        if api_token := self._get_api_token(
            username=username, password=password, library_id=self.library_id
        ):
            self.api_token = api_token
        else:
            logging.error("Failed to retrieve your API token.")
            return

        return True

    def _get_api_token(self, username: str, password: str, library_id: str) -> str:
        data = self._api_request(
            method="POST",
            url=API_ENDPOINTS["login"],
            data={
                "username": username,
                "password": password,
                "portal": library_id,
                "app_code": "",
            },
        )

        return data["token"] if data and "token" in data else None

    def _api_request(self, **kwargs) -> Optional[dict]:
        if self.api_token:
            if "params" in kwargs:
                kwargs["params"].update({"token": self.api_token})
            else:
                kwargs["params"] = {"token": self.api_token}

        kwargs["headers"] = (
            dict(DEFAULT_API_HEADERS, **kwargs["headers"])
            if "headers" in kwargs
            else DEFAULT_API_HEADERS
        )

        response = requests.request(**kwargs)
        response.raise_for_status()
        if "application/json" in response.headers["Content-Type"]:
            return response.json()

        logging.error(f"Unexpected API response: {response.raw}")
        return

    def _get_queue_position(self, reservation_id: str) -> Optional[int]:
        params = {"id": reservation_id}
        response = self.session.request(
            "GET", url=WEB_ENDPOINTS["get_queue_position"], params=params
        )

        if "in coda" in response.text and (
            queue_position := re.search(r"\d+(?=°)", response.text)
        ):
            return int(queue_position.group())

        logging.error(f"Failed to get queue position for reservation #{reservation_id}")
        return

    def _redownload_owned_book(self, book_id: str) -> Response:
        active_loans = self.get_resources()["active_loans"]
        if loan_id := next((l.id for l in active_loans if l.book_id == book_id), None):
            response = self.session.request(
                "GET",
                url=WEB_ENDPOINTS["redownload"],
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
                    url=WEB_ENDPOINTS["search"],
                    params={**req_params, **{"page": i}},
                )
            )
            books = _parse_search_page(BeautifulSoup(response.text, "html.parser"))
            if deep:
                with ThreadPoolExecutor(
                    max_workers=min(len(books), self.max_threads)
                ) as executor:
                    yield list(executor.map(self.get_book_by_id, (b.id for b in books)))
            else:
                yield books

    def _get_reservations(self) -> List[MLOLReservation]:
        reservations = []
        response = self.session.request("GET", WEB_ENDPOINTS["resources"])
        soup = BeautifulSoup(response.text, "html.parser")

        if reservations_el := soup.select_one("#mlolreservation"):
            for i, reservation_el in enumerate(
                reservations_el.select("div.bottom-buffer")
            ):
                reservation = _parse_reservation(reservation_el, index=i)
                reservation.queue_position = self._get_queue_position(reservation.id)
                reservations.append(reservation)

        return [r for r in reservations if r is not None]

    def get_book_by_id(self, book_id: str) -> Optional[MLOLBook]:
        logging.debug(f"Fetching book {book_id}")
        response = self.session.request(
            "GET",
            url=WEB_ENDPOINTS["get_book"],
            params={"id": book_id},
        )
        if "alert.aspx" in response.url:
            logging.warning(
                f"Failed to fetch book {book_id}. Might not be available to your library."
            )
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        book_data = _parse_book_page(soup)
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
            categories=book_data["categories"],
            year=book_data["year"],
            formats=book_data["formats"],
            drm=book_data["drm"],
        )

    def get_book(self, book: MLOLBook) -> Optional[MLOLBook]:
        if not isinstance(book, MLOLBook):
            raise ValueError(f"Expected MLOLBook, got {type(book)}")

        return self.get_book_by_id(book.id)

    def download_book_by_id(self, book_id: str) -> Optional[bytes]:
        if not self.is_logged_in():
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
                url=WEB_ENDPOINTS["download"],
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
        if not isinstance(book, MLOLBook):
            raise ValueError(f"Expected MLOLBook, got {type(book)}")

        return self.download_book_by_id(book.id)

    def get_book_url_by_id(self, book_id: str) -> str:
        return f"{self.session.base_url}{WEB_ENDPOINTS['get_book']}?id={book_id}"

    def get_book_url(self, book: MLOLBook) -> str:
        return self.get_book_url_by_id(book.id)

    def reserve_book_by_id(self, book_id: str, *, email: str) -> Optional[bool]:
        if not self.is_logged_in():
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
                "Referer": f"{self.session.base_url}{WEB_ENDPOINTS['pre_reserve']}?id={book_id}",
                "Accept": "text/html, */*; q=0.01",
            },
        }

        response = self.session.request(
            "GET",
            # don't pass params, build the URL directly to avoid percent encoding
            url=f"{WEB_ENDPOINTS['reserve']}?id={book_id}&email={email}",
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

        logging.error(f"Failed to reserve book with ID {book_id} (unknown outcome)")

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
            url=WEB_ENDPOINTS["cancel_reservation"],
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

        if not self.is_logged_in():
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

        for reservation in self._get_reservations():
            if reservation.book.id == book.id:
                return self.cancel_reservation_by_id(reservation.id)

        logging.error(
            f"Could not cancel reservation for book #{book.id} (reservation ID not found)"
        )
        return

    def get_resources(self, *, deep=False) -> dict:
        resources = {}
        resources["reservations"] = self._get_reservations()

        if (
            loan_response := self._api_request(method="GET", url=API_ENDPOINTS["loans"])
        ) and "loans" in loan_response:
            resources["active_loans"] = [
                MLOLApiConverter.get_loan(l) for l in loan_response["loans"]
            ]

        if (
            loan_history_response := self._api_request(
                method="GET", url=API_ENDPOINTS["loan_history"]
            )
        ) and "loans" in loan_history_response:
            resources["loan_history"] = [
                MLOLApiConverter.get_loan(l) for l in loan_history_response["loans"]
            ]

        if deep:
            for reservation in resources["reservations"]:
                if book := self.get_book_by_id(reservation.book.id):
                    reservation.book = book
            for loan in resources["active_loans"]:
                if book := self.get_book_by_id(loan.book.id):
                    loan.book = book
            for loan in resources["loan_history"]:
                if book := self.get_book_by_id(loan.book.id):
                    loan.book = book

        return resources

    def search_books(
        self, query: str, *, deep: bool = False, only_available: bool = False
    ) -> Generator[List[MLOLBook], None, None]:
        params = {"seltip": 310, "keywords": query.strip(), "nris": 48}
        if only_available:
            if not self.is_logged_in():
                logging.error("You need to be logged in to check for available books.")
                return
            params.update({"chkdispo": "on"})

        response = self.session.request(
            "GET", url=WEB_ENDPOINTS["search"], params=params
        )
        soup = BeautifulSoup(response.text, "html.parser")

        try:
            pages = int(soup.select_one("#pager").attrs["data-pages"])
        except AttributeError:
            pages = 1

        return self._search_books_paginated(
            req_params=params, deep=deep, pages=pages, first_response=response
        )

    def get_latest_books(
        self, *, deep: bool = False, only_available: bool = False
    ) -> Generator[List[MLOLBook], None, None]:
        params = {"seltip": 310, "news": "15day", "nris": 48}
        if only_available:
            if not self.is_logged_in():
                logging.error("You need to be logged in to check for available books.")
                return
            params.update({"chkdispo": "on"})

        response = self.session.request(
            "GET", url=WEB_ENDPOINTS["search"], params=params
        )
        soup = BeautifulSoup(response.text, "html.parser")

        try:
            pages = int(soup.select_one("#pager").attrs["data-pages"])
        except AttributeError:
            pages = 1

        return self._search_books_paginated(
            req_params=params, deep=deep, pages=pages, first_response=response
        )

    def get_user(self) -> Optional[MLOLUser]:
        data = self._api_request(method="GET", url=API_ENDPOINTS["userinfo"])
        if data:
            return MLOLApiConverter.get_user(data)

    def is_logged_in(self) -> bool:
        return (
            self.session.cookies.get(".ASPXAUTH") is not None
            and self.api_token is not None
        )
