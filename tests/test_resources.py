import os

import vcr
from pytest_cases import parametrize_with_cases, fixture


def validate_dict(candidate, expected):
    # are all values from expected in candidate?
    return all(v == candidate[k] for k, v in expected.items())

@fixture(scope='session')
def resources(client_auth):
    # we are recording this data once, and test expected values have to be dependent on the data we have at the moment
    with vcr.use_cassette(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "cassettes",
            "resources",
            "resources.yaml",
        ),
        record_mode="none",
        filter_headers=["Cookie", "Set-Cookie"],
        filter_query_parameters=["token"],
    ):
        return client_auth.get_resources()

def test_reservation_number(resources):
    assert len(resources["reservations"]) == 2

@parametrize_with_cases("index, expected", prefix="case_reservation_")
def test_reservation(resources, index, expected):
    candidate = resources["reservations"][index]

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
