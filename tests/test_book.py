import pytest
from pytest_cases import parametrize_with_cases, fixture_ref, parametrize


@pytest.mark.vcr(record_mode="none")
@parametrize_with_cases("book_id, expected")
def test_book(client_no_auth, book_id, expected):
    book_dict = client_no_auth.get_book_by_id(book_id).__dict__
    assert all(v == book_dict[k] for k, v in expected.items())
