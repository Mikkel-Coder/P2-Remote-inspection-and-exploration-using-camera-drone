import unittest

from jwt_model import JWT, JWTFormatError


class JWTTestCase(unittest.TestCase):
    def test_valid_jwt_format(self) -> None:
        token: str = '123234JIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZGsImV4cCI6MTY4NTM3MzkyM30.l2WWIgzs1pYgi9aUuWk_hc7AXWLzOi23MvPzmei6NUw'
        scheme: str = 'Bearer'

        jwt: JWT = JWT(token, scheme)
        self.assertEqual(jwt._token, token)
        self.assertEqual(jwt.scheme, scheme)

    def test_invalid_jwt_format(self) -> None:
        token: str = 'A.invalid_token'
        scheme: str = 'Bearer'

        with self.assertRaises(JWTFormatError):
            JWT(token, scheme)

    def test_invalid_jwt_scheme(self) -> None:
        token: str = 'eyJhbGciOiJIUzI1NiIsIsdfasdfJ9.eyJzdWIiOiJhZasdfCI6MTY4NTM3MzkyM30.l2WWIgzs1pYgi9asdfLzOi23MvPzmei6NUw'
        scheme: str = 'Basic'

        with self.assertRaises(JWTFormatError):
            JWT(token, scheme)


if __name__ == '__main__':
    unittest.main()
