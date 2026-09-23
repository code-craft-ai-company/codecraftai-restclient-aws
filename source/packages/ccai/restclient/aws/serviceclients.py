"""
    .. module:: serviceclients
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: The EC2, S3, Route53, FSx and SSM clients.

    Method and keyword names match ``boto3``'s, because consumer code already
    calls them that way — ``describe_vpcs(Filters=[...])``,
    ``head_bucket(Bucket=...)``, ``get_parameter(Name=...)``.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import json

from typing import Any, Dict, List, Optional
import urllib.parse
import xml.etree.ElementTree as ElementTree

from ccai.restclient.aws.awstransport import AwsTransport, endpoint_for
from ccai.restclient.aws.querycodec import (
    decode_response,
    flatten_params,
    strip_namespace,
)


EC2_API_VERSION = "2016-11-15"

ROUTE53_API_VERSION = "2013-04-01"

# JSON 1.1 services name the operation in a header, qualified by a target
# prefix that differs per service.
SSM_TARGET_PREFIX = "AmazonSSM"

FSX_TARGET_PREFIX = "AWSSimbaAPIService_v20180301"


class Ec2Client:
    """
        The EC2 client, speaking the Query protocol.

        Every operation is a form-encoded POST naming ``Action``; the response
        shape mapping lives in :mod:`querycodec`.
    """

    def __init__(self, *, transport: AwsTransport,
                 endpoint: Optional[str] = None) -> None:
        """
            Construct an Ec2Client.

            :param transport: The shared :class:`AwsTransport`.
            :param endpoint: Optional endpoint override.
        """
        self._transport = transport
        if endpoint is not None:
            self._endpoint = endpoint.rstrip("/")
        else:
            self._endpoint = endpoint_for(service="ec2",
                                          region=transport.region)
        return

    @property
    def endpoint(self) -> str:
        """
            Return the endpoint this client addresses.

            :returns: The endpoint URL.
        """
        rtnval = self._endpoint
        return rtnval

    def call(self, action: str, **kwargs: Any) -> Dict[str, Any]:
        """
            Invoke one EC2 action.

            :param action: The action name, e.g. ``DescribeVpcs``.
            :param kwargs: The action parameters, in botocore spelling.

            :returns: The decoded response.
        """
        params = flatten_params(kwargs)
        params["Action"] = action
        params["Version"] = EC2_API_VERSION

        body = urllib.parse.urlencode(sorted(params.items())).encode("utf-8")

        response = self._transport.send(
            service="ec2", method="POST", url=self._endpoint, body=body,
            headers={"content-type":
                     "application/x-www-form-urlencoded; charset=utf-8"})

        self._transport.raise_for_status(response=response, method="POST",
                                         url=self._endpoint)

        rtnval = self._transport.decode_xml(response=response)
        return rtnval

    def __getattr__(self, name: str) -> Any:
        """
            Expose every EC2 action as a snake_case method.

            botocore generates its methods from the service model; doing the
            same by name here means an operation this package has never been
            told about still works, rather than needing a new stub for each.

            :param name: The snake_case operation name.

            :returns: A callable invoking that action.
        """
        if name.startswith("_") is True:
            raise AttributeError(name)

        action = "".join(part.title() for part in name.split("_"))

        def _invoke(**kwargs: Any) -> Dict[str, Any]:
            return self.call(action, **kwargs)

        return _invoke


class S3Client:
    """
        The S3 client, speaking REST-XML.

        Only the bucket-level operations the provisioning venue uses are
        implemented.
    """

    def __init__(self, *, transport: AwsTransport,
                 endpoint: Optional[str] = None) -> None:
        """
            Construct an S3Client.

            :param transport: The shared :class:`AwsTransport`.
            :param endpoint: Optional endpoint override.
        """
        self._transport = transport
        if endpoint is not None:
            self._endpoint = endpoint.rstrip("/")
        else:
            self._endpoint = endpoint_for(service="s3",
                                          region=transport.region)
        return

    @property
    def endpoint(self) -> str:
        """
            Return the endpoint this client addresses.

            :returns: The endpoint URL.
        """
        rtnval = self._endpoint
        return rtnval

    def _call(self, *, method: str, path: str,
              params: Optional[Dict[str, Any]] = None,
              body: Optional[bytes] = None,
              headers: Optional[Dict[str, str]] = None) -> Any:
        """
            Perform one S3 request.

            :returns: The raw response.
        """
        url = "{}{}".format(self._endpoint, path)

        response = self._transport.send(service="s3", method=method,
                                        url=url, params=params, body=body,
                                        headers=headers)

        self._transport.raise_for_status(response=response, method=method,
                                         url=url)
        return response

    def head_bucket(self, *, Bucket: str) -> Dict[str, Any]:
        """
            Check that a bucket exists and is reachable.

            :param Bucket: The bucket name.

            :returns: A response-metadata dict.

            :raises: :class:`ClientError` with code ``"404"`` when absent —
                which the caller recovers — and any other code otherwise,
                which it must not.
        """
        response = self._call(method="HEAD",
                              path="/{}".format(Bucket))

        rtnval = {"ResponseMetadata": {
            "HTTPStatusCode": getattr(response, "status_code", 200)}}
        return rtnval

    def create_bucket(self, *, Bucket: str,
                      CreateBucketConfiguration: Optional[
                          Dict[str, Any]] = None) -> Dict[str, Any]:
        """
            Create a bucket.

            :param Bucket: The bucket name.
            :param CreateBucketConfiguration: Optional configuration carrying
                ``LocationConstraint``.  us-east-1 must NOT carry one — S3
                rejects the request if it does, which is why this is optional
                rather than always sent.

            :returns: A dict carrying the bucket location.
        """
        body = None
        headers = None
        if CreateBucketConfiguration is not None:
            constraint = CreateBucketConfiguration.get("LocationConstraint",
                                                       None)
            if constraint is not None:
                body = (
                    '<CreateBucketConfiguration '
                    'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    "<LocationConstraint>{}</LocationConstraint>"
                    "</CreateBucketConfiguration>".format(constraint)
                ).encode("utf-8")
                headers = {"content-type": "application/xml"}

        self._call(method="PUT", path="/{}".format(Bucket), body=body,
                   headers=headers)

        rtnval = {"Location": "/{}".format(Bucket)}
        return rtnval

    def delete_bucket(self, *, Bucket: str) -> Dict[str, Any]:
        """
            Delete a bucket.

            :param Bucket: The bucket name.

            :returns: A response-metadata dict.
        """
        response = self._call(method="DELETE", path="/{}".format(Bucket))

        rtnval = {"ResponseMetadata": {
            "HTTPStatusCode": getattr(response, "status_code", 204)}}
        return rtnval

    def list_buckets(self, **kwargs: Any) -> Dict[str, Any]:
        """
            List every bucket the credential can see.

            :returns: A dict carrying ``Buckets``, each with a ``Name``.
        """
        response = self._call(method="GET", path="/")

        names: List[Dict[str, Any]] = []

        text = getattr(response, "text", "")
        if text is not None and len(text.strip()) > 0:
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError:
                root = None

            if root is not None:
                for element in root.iter():
                    if strip_namespace(element.tag) != "Bucket":
                        continue
                    for child in element:
                        if strip_namespace(child.tag) != "Name":
                            continue
                        if child.text is None:
                            continue
                        names.append({"Name": child.text.strip()})
                        break

        rtnval = {"Buckets": names}
        return rtnval

    def get_bucket_tagging(self, *, Bucket: str) -> Dict[str, Any]:
        """
            Read a bucket's tag set.

            :param Bucket: The bucket name.

            :returns: A dict carrying ``TagSet``.

            :raises: :class:`ClientError` with code ``NoSuchTagSet`` when the
                bucket has no tags — S3 treats "no tags" as an error rather
                than an empty set, and callers recover that one code.
        """
        response = self._call(method="GET", path="/{}".format(Bucket),
                              params={"tagging": ""})

        tags: List[Dict[str, Any]] = []

        text = getattr(response, "text", "")
        if text is not None and len(text.strip()) > 0:
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError:
                root = None

            if root is not None:
                for element in root.iter():
                    if strip_namespace(element.tag) != "Tag":
                        continue
                    entry: Dict[str, Any] = {}
                    for child in element:
                        entry[strip_namespace(child.tag)] = (
                            child.text or "").strip()
                    tags.append(entry)

        rtnval = {"TagSet": tags}
        return rtnval

    def put_bucket_tagging(self, *, Bucket: str,
                           Tagging: Dict[str, Any]) -> Dict[str, Any]:
        """
            Replace a bucket's tag set.

            :param Bucket: The bucket name.
            :param Tagging: A dict carrying ``TagSet``.

            :returns: A response-metadata dict.
        """
        entries = Tagging.get("TagSet", []) or []

        rendered = "".join(
            "<Tag><Key>{}</Key><Value>{}</Value></Tag>".format(
                _escape(str(entry.get("Key", ""))),
                _escape(str(entry.get("Value", ""))))
            for entry in entries)

        body = ('<Tagging xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                "<TagSet>{}</TagSet></Tagging>".format(rendered)
                ).encode("utf-8")

        response = self._call(method="PUT", path="/{}".format(Bucket),
                              params={"tagging": ""}, body=body,
                              headers={"content-type": "application/xml"})

        rtnval = {"ResponseMetadata": {
            "HTTPStatusCode": getattr(response, "status_code", 204)}}
        return rtnval


class Route53Client:
    """
        The Route53 client, speaking REST-XML.
    """

    def __init__(self, *, transport: AwsTransport,
                 endpoint: Optional[str] = None) -> None:
        """
            Construct a Route53Client.

            :param transport: The shared :class:`AwsTransport`.
            :param endpoint: Optional endpoint override.
        """
        self._transport = transport
        if endpoint is not None:
            self._endpoint = endpoint.rstrip("/")
        else:
            self._endpoint = endpoint_for(service="route53",
                                          region=transport.region)
        return

    @property
    def endpoint(self) -> str:
        """
            Return the endpoint this client addresses.

            :returns: The endpoint URL.
        """
        rtnval = self._endpoint
        return rtnval

    def list_hosted_zones(self, **kwargs: Any) -> Dict[str, Any]:
        """
            List the account's hosted zones.

            :returns: A dict carrying ``HostedZones``, each with ``Id`` and
                ``Name``.
        """
        url = "{}/{}/hostedzone".format(self._endpoint, ROUTE53_API_VERSION)

        response = self._transport.send(service="route53", method="GET",
                                        url=url)
        self._transport.raise_for_status(response=response, method="GET",
                                         url=url)

        decoded = decode_response(getattr(response, "text", ""))

        zones = decoded.get("HostedZones", [])
        if isinstance(zones, list) is False:
            zones = [zones]

        rtnval = {"HostedZones": zones}
        return rtnval

    def change_resource_record_sets(self, *, HostedZoneId: str,
                                    ChangeBatch: Dict[str, Any]
                                    ) -> Dict[str, Any]:
        """
            Apply a batch of record changes.

            Route53 applies the batch atomically, which is what makes an
            upsert-plus-delete safe to express as one call.

            :param HostedZoneId: The zone id, with or without its
                ``/hostedzone/`` prefix.
            :param ChangeBatch: The change batch.

            :returns: The decoded change info.
        """
        zone_id = HostedZoneId.rsplit("/", 1)[-1]

        url = "{}/{}/hostedzone/{}/rrset".format(
            self._endpoint, ROUTE53_API_VERSION, zone_id)

        body = _render_change_batch(batch=ChangeBatch).encode("utf-8")

        response = self._transport.send(
            service="route53", method="POST", url=url, body=body,
            headers={"content-type": "application/xml"})
        self._transport.raise_for_status(response=response, method="POST",
                                         url=url)

        rtnval = decode_response(getattr(response, "text", ""))
        return rtnval


class JsonServiceClient:
    """
        A JSON 1.1 service client.

        The operation is named in an ``X-Amz-Target`` header rather than by
        path, and both directions are JSON.

        :cvar SERVICE: The service name, which scopes the signature.
        :cvar TARGET_PREFIX: The prefix qualifying the operation name.
    """

    SERVICE: str = ""
    TARGET_PREFIX: str = ""

    def __init__(self, *, transport: AwsTransport,
                 endpoint: Optional[str] = None) -> None:
        """
            Construct a JsonServiceClient.

            :param transport: The shared :class:`AwsTransport`.
            :param endpoint: Optional endpoint override.
        """
        self._transport = transport
        if endpoint is not None:
            self._endpoint = endpoint.rstrip("/")
        else:
            self._endpoint = endpoint_for(service=self.SERVICE,
                                          region=transport.region)
        return

    @property
    def endpoint(self) -> str:
        """
            Return the endpoint this client addresses.

            :returns: The endpoint URL.
        """
        rtnval = self._endpoint
        return rtnval

    def call(self, operation: str, **kwargs: Any) -> Dict[str, Any]:
        """
            Invoke one operation.

            :param operation: The operation name, e.g. ``GetParameter``.
            :param kwargs: The operation parameters.

            :returns: The decoded response.
        """
        payload: Dict[str, Any] = {}
        for name, value in kwargs.items():
            if value is not None:
                payload[name] = value

        body = json.dumps(payload).encode("utf-8")

        headers = {
            "content-type": "application/x-amz-json-1.1",
            "x-amz-target": "{}.{}".format(self.TARGET_PREFIX, operation),
        }

        response = self._transport.send(service=self.SERVICE, method="POST",
                                        url=self._endpoint, body=body,
                                        headers=headers)
        self._transport.raise_for_status(response=response, method="POST",
                                         url=self._endpoint)

        text = getattr(response, "text", "")
        if text is None or len(text.strip()) == 0:
            rtnval: Dict[str, Any] = {}
            return rtnval

        try:
            decoded = response.json()
        except Exception:
            rtnval = {}
            return rtnval

        if isinstance(decoded, dict) is False:
            rtnval = {"Value": decoded}
            return rtnval

        rtnval = decoded
        return rtnval

    def __getattr__(self, name: str) -> Any:
        """
            Expose every operation as a snake_case method.

            :param name: The snake_case operation name.

            :returns: A callable invoking that operation.
        """
        if name.startswith("_") is True:
            raise AttributeError(name)

        operation = "".join(part.title() for part in name.split("_"))

        def _invoke(**kwargs: Any) -> Dict[str, Any]:
            return self.call(operation, **kwargs)

        return _invoke


class SsmClient(JsonServiceClient):
    """
        The SSM Parameter Store client.
    """

    SERVICE = "ssm"
    TARGET_PREFIX = SSM_TARGET_PREFIX


class FsxClient(JsonServiceClient):
    """
        The FSx client.
    """

    SERVICE = "fsx"
    TARGET_PREFIX = FSX_TARGET_PREFIX


def _escape(value: str) -> str:
    """
        Escape text for inclusion in an XML body.

        :param value: The text.

        :returns: The escaped text.
    """
    rtnval = (value.replace("&", "&amp;").replace("<", "&lt;")
              .replace(">", "&gt;"))
    return rtnval


def _render_change_batch(*, batch: Dict[str, Any]) -> str:
    """
        Render a Route53 change batch as XML.

        :param batch: The change batch.

        :returns: The XML body.
    """
    parts: List[str] = []

    comment = batch.get("Comment", None)
    if comment is not None:
        parts.append("<Comment>{}</Comment>".format(_escape(str(comment))))

    changes: List[str] = []
    for change in batch.get("Changes", []) or []:
        record = change.get("ResourceRecordSet", {}) or {}

        values = "".join(
            "<ResourceRecord><Value>{}</Value></ResourceRecord>".format(
                _escape(str(entry.get("Value", ""))))
            for entry in record.get("ResourceRecords", []) or [])

        record_parts = [
            "<Name>{}</Name>".format(_escape(str(record.get("Name", "")))),
            "<Type>{}</Type>".format(_escape(str(record.get("Type", "")))),
        ]
        ttl = record.get("TTL", None)
        if ttl is not None:
            record_parts.append("<TTL>{}</TTL>".format(ttl))
        record_parts.append(
            "<ResourceRecords>{}</ResourceRecords>".format(values))

        changes.append(
            "<Change><Action>{}</Action>"
            "<ResourceRecordSet>{}</ResourceRecordSet></Change>".format(
                _escape(str(change.get("Action", ""))),
                "".join(record_parts)))

    parts.append("<Changes>{}</Changes>".format("".join(changes)))

    rtnval = (
        '<ChangeResourceRecordSetsRequest '
        'xmlns="https://route53.amazonaws.com/doc/2013-04-01/">'
        "<ChangeBatch>{}</ChangeBatch>"
        "</ChangeResourceRecordSetsRequest>".format("".join(parts))
    )
    return rtnval


def build_clients(*, transport: AwsTransport) -> Dict[str, Any]:
    """
        Build every service client over one transport.

        :param transport: The shared :class:`AwsTransport`.

        :returns: A dict keyed by boto3 service name.
    """
    rtnval = {
        "ec2": Ec2Client(transport=transport),
        "s3": S3Client(transport=transport),
        "route53": Route53Client(transport=transport),
        "ssm": SsmClient(transport=transport),
        "fsx": FsxClient(transport=transport),
    }
    return rtnval
