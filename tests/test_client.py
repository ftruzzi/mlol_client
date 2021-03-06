def test_unauthenticated_base_url(client_no_auth):
    assert client_no_auth.session.base_url == "https://medialibrary.it"


def test_web_authentication(client_auth):
    cookies = client_auth.session.cookies
    assert cookies.get(".ASPXAUTH") and cookies.get("X_MLOL_User")


def test_api_token_authentication(client_auth):
    assert client_auth.api_token is not None


def test_authenticated_base_url(client_auth):
    base_url = client_auth.session.base_url
    assert base_url.startswith("https://") and base_url.endswith("medialibrary.it")


def test_authentication_failure(client_failed_auth):
    cookies = client_failed_auth.session.cookies
    assert (
        cookies.get(".ASPXAUTH") is None
        and cookies.get("X_MLOL_User") is None
        and client_failed_auth.api_token is None
    )
