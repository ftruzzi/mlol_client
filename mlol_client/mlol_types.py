from datetime import datetime
from typing import List


class MLOLBook:
    def __init__(
        self,
        *,
        id: str,
        title: str,
        authors: List[str] = None,
        status: str = None,
        publisher: str = None,
        ISBNs: List[str] = None,
        language: str = None,
        description: str = None,
        year: int = None,
        formats: List[str] = None,
        drm: bool = None,
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

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLBook: {values}>"


class MLOLLoan:
    def __init__(
        self,
        *,
        id: str,
        book: MLOLBook,
        start_date: datetime = None,
        end_date: datetime = None,
    ):
        self.id = str(id) if id else None
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


class MLOLUser:
    def __init__(
        self,
        id: int,
        name: str,
        surname: str,
        username: str,
        remaining_loans: int,
        remaining_reservations: int,
        expiration_date: datetime,
    ):
        self.id = id
        self.name = name
        self.surname = surname
        self.username = username
        self.remaining_loans = remaining_loans
        self.remaining_reservations = remaining_reservations
        self.expiration_date = expiration_date

    def __repr__(self):
        values = {
            k: "{}{}".format(str(v)[:50], "..." if len(str(v)) > 50 else "")
            for k, v in self.__dict__.items()
            if v is not None
        }
        return f"<mlol_client.MLOLUser: {values}>"
