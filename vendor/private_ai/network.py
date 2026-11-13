"""Redirect boundary used by the Google connector."""
from urllib.request import HTTPRedirectHandler

class ProviderError(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError("Provider redirected the request; stopped")
