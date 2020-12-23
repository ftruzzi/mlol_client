import os
import logging
import sys

import vcr
from pytest_cases import parametrize_with_cases
from mlol_client import MLOLClient


def validate_dict(candidate, expected):
    # are all values from expected in candidate?
    return all(v == candidate[k] for k, v in expected.items())


username = os.getenv("MLOL_USER")
password = os.getenv("MLOL_PASS")
domain = os.getenv("MLOL_DOMAIN")
if not username or not password or not domain:
    logging.error("Missing one or more env vars: MLOL_USER, MLOL_PASS, MLOL_DOMAIN")
    sys.exit(1)

client = MLOLClient(domain=domain, username=username, password=password)

# we are recording this data once, and test expected values have to be dependent on the data we have at the moment
with vcr.use_cassette(
    os.path.join("cassettes", "resources", "resources.yaml"),
    record_mode="once",
    filter_headers=["Cookie", "Set-Cookie"],
):
    resources = client.get_resources()
    reservations = resources["reservations"]
    active_loans = resources["active_loans"]
    loan_history = resources["loan_history"]

    def test_reservation_number():
        assert len(reservations) == 2

    @parametrize_with_cases("index, expected", prefix="case_reservation_")
    def test_reservation(index, expected):
        candidate = reservations[index]

        book_dict = candidate.book.__dict__
        date = candidate.date.__str__()
        other_values = [candidate.id, candidate.status, candidate.queue_position]

        expected_book_dict = expected["book"]
        expected_date = expected["date"]
        expected_other_values = [
            expected[k] for k in ["id", "status", "queue_position"]
        ]

        assert (
            validate_dict(book_dict, expected_book_dict)
            and date == expected_date
            and other_values == expected_other_values
        )
