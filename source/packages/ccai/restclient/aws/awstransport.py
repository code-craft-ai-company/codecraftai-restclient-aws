"""
    .. module:: awstransport
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: :class:`AwsTransport` — the SigV4-signed transport.

    AWS speaks four different protocols across the services this package
    covers, and they differ in more than encoding:

    * EC2 uses the **Query** protocol — form-encoded requests, XML responses
      whose element names differ from the modelled ones.
    * S3 and Route53 use **REST-XML** — the operation is the HTTP method and
      path, and responses are XML that already carries modelled names.
    * FSx and SSM use **JSON 1.1** — the operation is named in an
      ``X-Amz-Target`` header and both directions are JSON.

    What they share is SigV4, so this transport owns signing and each client
    owns its protocol.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import os

from typing import Any, Dict, Optional

import requests

from ccai.restclient.base.awssigv4 import SigV4Signer

from ccai.restclient.aws.awserror import ClientError
from ccai.restclient.aws.querycodec import decode_response, strip_namespace


DEFAULT_TIMEOUT_SECONDS = 60.0

# S3 addresses its single global endpoint by this region name when signing,
# regardless of where a bucket lives.
S3_GLOBAL_REGION = "us-east-1"


def endpoint_for(*, service: str, region: str) -> str:
    """
        Build a service endpoint.

        Route53 and IAM are global services with a single endpoint; giving
        them a regional hostname would fail to resolve.

        :param service: The service name.
        :param region: The region name.

        :returns: The endpoint URL.
    """
    if service == "route53":
        rtnval = "https://route53.amazonaws.com"
        return rtnval

    rtnval = "https://{}.{}.amazonaws.com".format(service, region)
    return rtnval


def signing_region_for(*, service: str, region: str) -> str:
    """
        Return the region a service's signature is scoped to.

        :param service: The service name.
        :param region: The caller's region.

        :returns: The signing region.
    """
    if service == "route53":
        # A global endpoint still signs against us-east-1.
        rtnval = S3_GLOBAL_REGION
        return rtnval

    rtnval = region
    return rtnval


class AwsTransport:
    """
        SigV4-signed transport shared by the service clients.
    """

    def __init__(self, *, access_key: str, secret_key: str, region: str,
                 session_token: Optional[str] = None,
                 session: Optional[Any] = None,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        """
            Construct an AwsTransport.

            :param access_key: The access key id.
            :param secret_key: The secret access key.
            :param region: The default region.
            :param session_token: Optional session token, for temporary
                credentials.
            :param session: Optional pre-built ``requests.Session`` — the test
                seam.
            :param timeout_seconds: The default per-request timeout.
        """
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._session_token = session_token
        self._timeout_seconds = timeout_seconds

        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
        return

    @property
    def region(self) -> str:
        """
            Return the default region.

            :returns: The region name.
        """
        rtnval = self._region
        return rtnval

    def signer_for(self, *, service: str) -> SigV4Signer:
        """
            Build a signer scoped to one service.

            :param service: The service name.

            :returns: The :class:`SigV4Signer`.
        """
        rtnval = SigV4Signer(
            access_key=self._access_key, secret_key=self._secret_key,
            region=signing_region_for(service=service, region=self._region),
            service=service, session_token=self._session_token)
        return rtnval

    def send(self, *, service: str, method: str, url: str,
             params: Optional[Dict[str, Any]] = None,
             body: Optional[bytes] = None,
             headers: Optional[Dict[str, str]] = None,
             timeout_seconds: Optional[float] = None) -> Any:
        """
            Sign and send one request.

            :param service: The service name, which scopes the signature.
            :param method: The HTTP method.
            :param url: The absolute URL.
            :param params: Query parameters, which are signed.
            :param body: The request body.
            :param headers: Any caller headers, which are signed.
            :param timeout_seconds: Optional per-request timeout override.

            :returns: The raw response.
        """
        signer = self.signer_for(service=service)

        signed = signer.sign(method=method, url=url, params=params,
                             headers=headers, body=body)

        timeout = timeout_seconds
        if timeout is None:
            timeout = self._timeout_seconds

        rtnval = self._session.request(method, url, params=params or {},
                                       data=body, headers=signed,
                                       timeout=timeout)
        return rtnval

    def raise_for_status(self, *, response: Any, method: str,
                         url: str) -> None:
        """
            Raise a botocore-shaped error for a non-success response.

            :param response: The response.
            :param method: The HTTP method, for the message.
            :param url: The URL, for the message.

            :returns: ``None``

            :raises: :class:`ClientError` on a non-success status.
        """
        status = getattr(response, "status_code", 0)
        if 200 <= status < 300:
            return

        text = getattr(response, "text", "")
        code, detail = self._error_of(response=response, status=status)

        err_msg_lines = ["The AWS request failed."]
        err_msg_lines.append("METHOD: {}".format(method))
        err_msg_lines.append("URL: {}".format(url))
        err_msg_lines.append("STATUS: {}".format(status))
        err_msg_lines.append("CODE: {}".format(code))
        err_msg_lines.append("MESSAGE: {}".format(detail))
        err_msg = os.linesep.join(err_msg_lines)

        raise ClientError(err_msg, code=code, status=status, detail=detail,
                          body=text)

    def _error_of(self, *, response: Any, status: int) -> Any:
        """
            Pull the AWS error code and message out of a failed response.

            The three protocols report errors differently: XML services nest
            a ``<Error><Code>``, JSON services use ``__type``, and a failed
            ``HEAD`` has no body at all — in which case the status stands in,
            because callers key on the code to tell "absent" from "denied".

            :param response: The failed response.
            :param status: The HTTP status code.

            :returns: A ``(code, message)`` pair.
        """
        text = getattr(response, "text", "")

        if text is not None and len(text.strip()) > 0:
            try:
                decoded = response.json()
                if isinstance(decoded, dict) is True:
                    typed = decoded.get("__type", None)
                    message = decoded.get("message", None)
                    if message is None:
                        message = decoded.get("Message", "")
                    if typed is not None:
                        # JSON services qualify the type with a namespace.
                        rtnval = (str(typed).split("#")[-1], str(message))
                        return rtnval
            except Exception:
                # Probing for a JSON error body; a body that does not decode as
                # JSON is an XML (or empty) error body and is handled below.
                pass

            found = self._error_from_xml(text=text)
            if found is not None:
                rtnval = found
                return rtnval

        rtnval = (str(status), getattr(response, "reason", ""))
        return rtnval

    def _error_from_xml(self, *, text: str) -> Any:
        """
            Read an ``<Error><Code>`` pair out of an XML body.

            :param text: The body text.

            :returns: A ``(code, message)`` pair, or None.
        """
        import xml.etree.ElementTree as ElementTree

        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            rtnval = None
            return rtnval

        code = ""
        message = ""
        for element in root.iter():
            name = strip_namespace(element.tag)
            if name == "Code" and len(code) == 0:
                code = (element.text or "").strip()
            elif name == "Message" and len(message) == 0:
                message = (element.text or "").strip()

        if len(code) == 0:
            rtnval = None
            return rtnval

        rtnval = (code, message)
        return rtnval

    def decode_xml(self, *, response: Any) -> Dict[str, Any]:
        """
            Decode an XML response body into modelled data.

            :param response: The response.

            :returns: The decoded body.
        """
        text = getattr(response, "text", "")
        rtnval = decode_response(text)
        return rtnval
