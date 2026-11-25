"""Kerberos HTTP authentication on Windows through SSPI (winkerberos), without MIT Kerberos.

Mirrors how requests_gssapi.HTTPSPNEGOAuth is used on other platforms: no opportunistic
authentication, a "Negotiate" answer to a 401 challenge, and no mutual authentication.
The Windows logon session supplies the Kerberos ticket.
"""
from urllib.parse import urlsplit

import winkerberos
from requests.auth import AuthBase
from requests.cookies import extract_cookies_to_jar


def negotiate_challenge(response):
    """Return the server's Negotiate token ('' when bare), or None when Negotiate is not offered."""
    for challenge in response.headers.get('www-authenticate', '').split(','):
        scheme, _, token = challenge.strip().partition(' ')
        if scheme.lower() == 'negotiate':
            return token.strip()
    return None


class SSPINegotiateAuth(AuthBase):
    def __init__(self, service='HTTP', mech_oid=winkerberos.GSS_MECH_OID_KRB5):
        self.service = service
        self.mech_oid = mech_oid
        self.pos = None

    def __call__(self, request):
        request.register_hook('response', self.handle_response)
        try:
            self.pos = request.body.tell()
        except AttributeError:
            self.pos = None
        return request

    def authorization_header(self, host):
        _, context = winkerberos.authGSSClientInit(
            f'{self.service}@{host}', gssflags=winkerberos.GSS_C_MUTUAL_FLAG | winkerberos.GSS_C_SEQUENCE_FLAG,
            mech_oid=self.mech_oid)
        winkerberos.authGSSClientStep(context, '')
        return 'Negotiate ' + winkerberos.authGSSClientResponse(context)

    def handle_response(self, response, **kwargs):
        # Answer one challenge; a second 401 means the server rejected the ticket.
        if response.status_code != 401 or negotiate_challenge(response) is None \
                or response.request.headers.get('Authorization', '').startswith('Negotiate '):
            return response
        try:
            header = self.authorization_header(urlsplit(response.url).hostname)
        except winkerberos.KrbError:
            # No usable ticket (e.g. local account): keep the 401 so callers report the login failure.
            return response
        if self.pos is not None:
            response.request.body.seek(self.pos)
        # Consume the content so the connection can be reused for the authenticated request.
        response.content
        response.raw.release_conn()
        request = response.request.copy()
        # Keep cookies the server set on the challenge, as requests does for redirects.
        extract_cookies_to_jar(request._cookies, response.request, response.raw)
        request.prepare_cookies(request._cookies)
        request.headers['Authorization'] = header
        authenticated = response.connection.send(request, **kwargs)
        authenticated.history.append(response)
        authenticated.request = request
        return authenticated
