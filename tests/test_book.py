import pytest
from pytest_cases import parametrize_with_cases

from mlol_client import MLOLClient

client = MLOLClient()


@pytest.mark.vcr(record_mode="once")
@parametrize_with_cases("book_id, expected")
def test_book(book_id, expected):
    book_dict = client.get_book_by_id(book_id).__dict__
    assert all(v == book_dict[k] for k, v in expected.items())
