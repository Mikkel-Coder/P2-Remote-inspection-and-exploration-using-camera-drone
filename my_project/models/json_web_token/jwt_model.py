'''The JWT dataclass.

The file contains a JWT class, that is used to represent a JSON Web Token.
See RFC 7519 for more detail.
'''

from dataclasses import dataclass


class JWTFormatError(SyntaxError):
    """The format of a JWT is incorrect"""


@dataclass
class JWT:
    """A JWT dataclass

    This dataclass is used to represent a JWT, with the associated
    token and scheme.

    Raises:
        JWTFormatError: If the format or scheme is incorrect. 

    Note:
        See RFC 7519 for more detail.
    """
    _token: str
    scheme: str

    def __post_init__(self) -> None:
        self._validate_format()

    def _validate_format(self) -> None:
        if not self._token.count('.') == 2:
            raise JWTFormatError(
                'The JWT tokens format is incorrect.'
            )

        if not self.scheme == 'Bearer':
            raise JWTFormatError(
                'The JWT scheme is not `Bearer`.'
            )

    def __repr__(self) -> str:
        return self._token
