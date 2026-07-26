"""
    .. module:: awserror
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: Errors raised for non-success AWS responses.

    :class:`ClientError` keeps the name and the ``response`` shape botocore
    used, because consumer code catches it and reads
    ``xcpt.response["Error"]["Code"]`` to decide whether a resource is merely
    absent — a 404 from ``head_bucket`` means "create it", while a 403 means
    "stop".  Keeping the shape lets those handlers keep working.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


from typing import Any, Dict, Optional


class ClientError(Exception):
    """
        Raised when an AWS service returns a non-success status.

        :ivar response: The botocore-shaped error envelope, carrying
            ``Error.Code``, ``Error.Message`` and
            ``ResponseMetadata.HTTPStatusCode``.
    """

    def __init__(self, message: str, *, code: str = "", status: int = 0,
                 detail: str = "", body: Optional[str] = None) -> None:
        """
            Construct a ClientError.

            :param message: The human-readable error message.
            :param code: The AWS error code, e.g. ``NoSuchBucket``.
            :param status: The HTTP status code.
            :param detail: The AWS error message.
            :param body: The raw response body.
        """
        super().__init__(message)
        self.response: Dict[str, Any] = {
            "Error": {"Code": code, "Message": detail},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        self.code: str = code
        self.status: int = status
        self.body: Optional[str] = body
        return
