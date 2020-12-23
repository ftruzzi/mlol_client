import logging
import os
import sys

from mlol_client import MLOLClient

client_no_auth = MLOLClient()


def test_unauthenticated_base_url():
    assert client_no_auth.session.base_url == "https://medialibrary.it"


username = os.getenv("MLOL_USER")
password = os.getenv("MLOL_PASS")
domain = os.getenv("MLOL_DOMAIN")
if not username or not password or not domain:
    logging.error("Missing one or more env vars: MLOL_USER, MLOL_PASS, MLOL_DOMAIN")
    sys.exit(1)

client_auth = MLOLClient(domain=domain, username=username, password=password)


def test_web_authentication():
    cookies = client_auth.session.cookies
    assert cookies.get(".ASPXAUTH") and cookies.get("X_MLOL_User")


def test_api_token_authentication():
    assert client_auth.api_token is not None


def test_authenticated_base_url():
    base_url = client_auth.session.base_url
    assert base_url.startswith("https://") and base_url.endswith("medialibrary.it")


def test_authentication_failure():
    client = MLOLClient(domain=domain, username=username, password="hunter2")
    cookies = client.session.cookies
    assert (
        cookies.get(".ASPXAUTH") is None
        and cookies.get("X_MLOL_User") is None
        and client.api_token is None
    )
