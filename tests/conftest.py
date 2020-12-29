from re import L
from _pytest.assertion import pytest_runtest_protocol
import os
import logging
import sys

import pytest

from mlol_client import MLOLClient

username = os.getenv("MLOL_USER")
password = os.getenv("MLOL_PASS")
domain = os.getenv("MLOL_DOMAIN")
if not username or not password or not domain:
    logging.error("Missing one or more env vars: MLOL_USER, MLOL_PASS, MLOL_DOMAIN")
    sys.exit(1)


@pytest.fixture(scope="session")
def client_no_auth():
    yield MLOLClient()


@pytest.fixture(scope="session")
def client_auth():
    yield MLOLClient(domain=domain, username=username, password=password)


@pytest.fixture(scope="session")
def client_failed_auth():
    yield MLOLClient(domain=domain, username=username, password="hunter2")
