import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from bs4 import Tag

from .mlol_types import MLOLBook, MLOLReservation


def _parse_search_page(page: Tag) -> List[MLOLBook]:
    books = []
    for i, book in enumerate(page.select(".result-item")):
        try:
            ID_RE = r"(?<=id=)\d+$"
            title = book.find("h4").attrs["title"]
            url = book.find("a").attrs["href"]
            id = re.search(ID_RE, url).group()
        except:
            logging.error(f"Could not parse ID or title. Skipping book #{i + 1}...")
            continue

        try:
            author_el = book.select("p > a.authorref")
            if len(author_el) > 0:
                authors = author_el[0].string.strip()
            elif author_el := book.find("p", attrs={"itemprop": "author"}):
                authors = author_el.string.strip()
            elif author_el := book.select_one(".product-author"):
                authors = author_el.string.strip()
            else:
                logging.warning(f"Failed to parse author for book {title}")
                authors = None

        except Exception:
            logging.warning(f"Failed to parse author for book {title}")
            authors = None

        books.append(
            MLOLBook(
                id=id,
                title=title,
                authors=[a.strip() for a in authors.split(";")] if authors else None,
            )
        )

    return books


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


def _parse_book_page(page: Tag) -> dict:
    book_data = defaultdict(lambda: None)

    if title := page.select_one(".book-title"):
        book_data["title"] = title.text.strip()

    if authors := page.select_one(".authors_title"):
        book_data["authors"] = [a.strip() for a in authors.text.strip().split(";")]

    if publisher := page.select_one(".publisher_title > span > a"):
        book_data["publisher"] = publisher.text.strip()

    if ISBNs := page.find_all(attrs={"itemprop": "isbn"}):
        book_data["ISBNs"] = [i.text.strip() for i in ISBNs]

    if status_element := page.select_one(".panel-mlol"):
        book_data["status"] = _parse_book_status(status_element.text.strip())

    if (description_el := page.find("div", attrs={"itemprop": "description"})) and (
        description := next(
            filter(
                lambda x: hasattr(x, "text"),
                description_el,
            )
        )
    ):
        book_data["description"] = description.text.strip()

    if categories := page.find("span", attrs={"itemprop": "keywords"}):
        book_data["categories"] = []
        for category_line in categories.text.replace("# in ", "").split("\n\n"):
            stripped_category_line = category_line.strip()
            if not stripped_category_line:
                continue

            category = [
                c.strip() for c in stripped_category_line.split("/") if c.strip()
            ]
            book_data["categories"].append(category)

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
        logging.warning(f"Failed to parse formats for book {book_data['title']}")

    return book_data


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
        logging.error(f"Could not find loan ID for reservation #{index + 1}")
        return

    if book_id_element := reservation_el.find(
        "a", attrs={"href": re.compile(r"(?<=scheda.aspx\?id=)\d+$")}
    ):
        book_id = re.search(r"(?<=\=)\d+$", book_id_element.attrs["href"]).group()
    else:
        logging.error(f"Could not find book ID for reservation #{index + 1}")
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
        reservation.date = datetime.strptime(f"{date} {time}", "%d/%m/%Y %H:%M")

    if status_els and len(status_els) >= 2:
        # TODO discover more statuses
        if status_els[1].find("b").text.strip() == "attiva":
            reservation.status = "active"

    return reservation
