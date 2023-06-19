'''A authentication interface for the `requests` library.

For more detail visit `requests` docs. 
'''

from requests.auth import AuthBase

from models.json_web_token.jwt_model import JWT


class HTTPBearer(AuthBase):
    """A HTTP Bearer Authorization interface for the `requests` library."""

    def __init__(self, jwt: JWT) -> None:
        self.jwt: JWT = jwt

    def __call__(self, r):
        r.headers['Authorization'] = f'{self.jwt.scheme} {self.jwt._token}'
        return r
