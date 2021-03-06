import os

import vcr
from pytest_cases import parametrize, fixture, fixture_ref
from vcr import record_mode

from mlol_client import MLOLClient, MLOLBook

CASSETTE_BASE_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "cassettes", "test_search"
)

NO_RESULT_QUERY = "asdqwedasdzxc"
ONE_PAGE_QUERY = "quammen"
MULTIPLE_PAGES_QUERY = "filosofia"
PAGE_SIZE = 48

client = MLOLClient()


@fixture
@parametrize("client", [fixture_ref("client_no_auth")])
def no_search_results(client):
    with vcr.use_cassette(
        os.path.join(CASSETTE_BASE_PATH, "no_search_results.yaml"), record_mode="none"
    ):
        results_generator = client.search_books(NO_RESULT_QUERY)
        results = []
        for page in results_generator:
            results += page
        return results


def test_no_results_length(no_search_results):
    assert len(no_search_results) == 0


@fixture
@parametrize("client", [fixture_ref("client_no_auth")])
def search_results_single_page(client):
    with vcr.use_cassette(
        os.path.join(CASSETTE_BASE_PATH, "search_results_single_page.yaml"),
        record_mode="none",
    ):
        results_generator = client.search_books(ONE_PAGE_QUERY, deep=False)
        results = []
        for page in results_generator:
            results += page
        return results


@fixture
@parametrize("client", [fixture_ref("client_no_auth")])
def search_results_single_page_deep(client):
    # don't record cassette here -- deep page queries are threaded and not executed in the same order
    # with vcr.use_cassette(os.path.join(CASSETTE_BASE_PATH, "search_results_single_page_deep.yaml")):
    results_generator = client.search_books(ONE_PAGE_QUERY, deep=True)
    results = []
    for page in results_generator:
        results += page
    return results


@parametrize(
    "search_results",
    [
        fixture_ref(search_results_single_page),
        fixture_ref(search_results_single_page_deep),
    ],
)
def test_single_page_results_length(search_results):
    assert len(search_results) > 0 and len(search_results) <= PAGE_SIZE


@parametrize(
    "search_results",
    [
        fixture_ref(search_results_single_page),
        fixture_ref(search_results_single_page_deep),
    ],
)
def test_search_results_type(search_results):
    assert all(isinstance(b, MLOLBook) for b in search_results)


def test_search_result_fields_simple(search_results_single_page):
    assert all(b.id and b.title and b.authors for b in search_results_single_page)
    assert all(
        not any(
            [
                b.status,
                b.publisher,
                b.ISBNs,
                b.language,
                b.description,
                b.year,
                b.formats,
                b.drm,
            ]
        )
        for b in search_results_single_page
    )


@fixture
@parametrize("client", [fixture_ref("client_no_auth")])
def search_results_multiple_pages(client):
    with vcr.use_cassette(
        os.path.join(CASSETTE_BASE_PATH, "search_results_multiple_pages.yaml"),
        record_mode="none",
    ):
        results_generator = client.search_books(MULTIPLE_PAGES_QUERY)
        results = []
        for page in results_generator:
            results += page
        return results


def test_multiple_page_results_length(search_results_multiple_pages):
    assert len(search_results_multiple_pages) > PAGE_SIZE
