"""
    .. module:: test_serviceclients
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: Tests for the AWS service clients.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import json
import urllib.parse

from typing import Any, Dict, List, Optional

from ccai import testbase

from ccai.restclient.aws.awserror import ClientError
from ccai.restclient.aws.awstransport import (
    AwsTransport, endpoint_for, signing_region_for
)
from ccai.restclient.aws.serviceclients import build_clients


REGION = "us-east-2"


class FakeResponse:
    """
        Minimal stand-in for a ``requests.Response``.
    """

    def __init__(self, *, status_code: int = 200, text: str = "",
                 payload: Optional[Any] = None,
                 reason: str = "OK") -> None:
        self.status_code = status_code
        self.reason = reason
        self._payload = payload
        if payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = text

    def json(self) -> Any:
        if self._payload is not None:
            return self._payload
        return json.loads(self.text)


class FakeSession:
    """
        Records requests and replays queued responses.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.responses: List[FakeResponse] = []
        self.default_response = FakeResponse(text="")

    def queue(self, response: FakeResponse) -> None:
        self.responses.append(response)
        return

    def request(self, method: str, url: str, params=None, data=None,
                headers=None, timeout=None) -> FakeResponse:
        self.calls.append({"method": method, "url": url,
                           "params": params or {}, "body": data,
                           "headers": headers or {}})

        if len(self.responses) > 0:
            rtnval = self.responses.pop(0)
            return rtnval

        rtnval = self.default_response
        return rtnval


def _clients(session=None):
    if session is None:
        session = FakeSession()
    transport = AwsTransport(access_key="AKIDEXAMPLE",
                             secret_key="secret", region=REGION,
                             session=session)
    return build_clients(transport=transport), session


# ----------------------------------------------------------------------
# endpoints and signing scope
# ----------------------------------------------------------------------

def test_regional_endpoints():
    assert endpoint_for(service="ec2", region="us-east-2") == \
        "https://ec2.us-east-2.amazonaws.com"
    assert endpoint_for(service="s3", region="us-east-2") == \
        "https://s3.us-east-2.amazonaws.com"
    return


def test_route53_is_global():
    # A regional route53 hostname does not resolve.
    assert endpoint_for(service="route53", region="us-east-2") == \
        "https://route53.amazonaws.com"
    assert signing_region_for(service="route53",
                              region="us-east-2") == "us-east-1"
    return


def test_every_request_is_sigv4_signed():
    clients, session = _clients()
    session.queue(FakeResponse(text="<DescribeVpcsResponse><vpcSet/>"
                                    "</DescribeVpcsResponse>"))

    clients["ec2"].describe_vpcs()

    authorization = session.calls[0]["headers"]["Authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 ")
    assert "/us-east-2/ec2/aws4_request" in authorization
    return


def test_signature_is_scoped_per_service():
    clients, session = _clients()
    session.queue(FakeResponse(text=""))
    session.queue(FakeResponse(text=""))

    clients["s3"].head_bucket(Bucket="bkt-a")
    clients["ssm"].get_parameter(Name="/p")

    assert "/s3/aws4_request" in session.calls[0]["headers"]["Authorization"]
    assert "/ssm/aws4_request" in session.calls[1]["headers"]["Authorization"]
    return


# ----------------------------------------------------------------------
# EC2
# ----------------------------------------------------------------------

def test_ec2_action_is_derived_from_the_method_name():
    clients, session = _clients()
    session.queue(FakeResponse(text="<DescribeVpcsResponse><vpcSet/>"
                                    "</DescribeVpcsResponse>"))

    clients["ec2"].describe_vpcs()

    body = urllib.parse.parse_qs(session.calls[0]["body"].decode("utf-8"))
    assert body["Action"] == ["DescribeVpcs"]
    assert body["Version"] == ["2016-11-15"]
    return


def test_ec2_filters_are_flattened_one_indexed():
    clients, session = _clients()
    session.queue(FakeResponse(text="<DescribeVpcsResponse><vpcSet/>"
                                    "</DescribeVpcsResponse>"))

    clients["ec2"].describe_vpcs(
        Filters=[{"Name": "tag:owner", "Values": ["ccai"]}])

    body = urllib.parse.parse_qs(session.calls[0]["body"].decode("utf-8"))
    assert body["Filters.1.Name"] == ["tag:owner"]
    assert body["Filters.1.Values.1"] == ["ccai"]
    return


def test_ec2_decodes_into_the_modeled_shape():
    clients, session = _clients()
    session.queue(FakeResponse(text=(
        "<DescribeVpcsResponse><vpcSet><item>"
        "<vpcId>vpc-1</vpcId><cidrBlock>10.0.0.0/16</cidrBlock>"
        "</item></vpcSet></DescribeVpcsResponse>")))

    result = clients["ec2"].describe_vpcs()

    assert result["Vpcs"][0]["VpcId"] == "vpc-1"
    return


def test_ec2_errors_carry_the_botocore_response_shape():
    clients, session = _clients()
    session.queue(FakeResponse(
        status_code=400, reason="Bad Request",
        text=("<Response><Errors><Error>"
              "<Code>InvalidVpcID.NotFound</Code>"
              "<Message>no such vpc</Message>"
              "</Error></Errors></Response>")))

    with testbase.raises(ClientError) as caught:
        clients["ec2"].describe_vpcs()

    # Consumer code reads xcpt.response["Error"]["Code"].
    assert caught.value.response["Error"]["Code"] == "InvalidVpcID.NotFound"
    assert caught.value.response["ResponseMetadata"]["HTTPStatusCode"] == 400
    return


# ----------------------------------------------------------------------
# S3
# ----------------------------------------------------------------------

def test_head_bucket_404_is_reported_as_code_404():
    clients, session = _clients()
    session.queue(FakeResponse(status_code=404, reason="Not Found", text=""))

    with testbase.raises(ClientError) as caught:
        clients["s3"].head_bucket(Bucket="missing")

    # A failed HEAD has no body, so the status stands in as the code —
    # callers key on it to tell "absent" from "denied".
    assert caught.value.response["Error"]["Code"] == "404"
    return


def test_head_bucket_403_is_not_mistaken_for_absent():
    clients, session = _clients()
    session.queue(FakeResponse(status_code=403, reason="Forbidden", text=""))

    with testbase.raises(ClientError) as caught:
        clients["s3"].head_bucket(Bucket="denied")

    assert caught.value.response["Error"]["Code"] != "404"
    return


def test_create_bucket_omits_the_location_constraint_when_absent():
    clients, session = _clients()
    session.queue(FakeResponse(text=""))

    clients["s3"].create_bucket(Bucket="bkt-a")

    # us-east-1 rejects a request that carries a LocationConstraint.
    assert session.calls[0]["body"] is None
    return


def test_create_bucket_sends_the_location_constraint_when_given():
    clients, session = _clients()
    session.queue(FakeResponse(text=""))

    clients["s3"].create_bucket(
        Bucket="bkt-a",
        CreateBucketConfiguration={"LocationConstraint": "us-east-2"})

    body = session.calls[0]["body"].decode("utf-8")
    assert "<LocationConstraint>us-east-2</LocationConstraint>" in body
    return


def test_list_buckets_reads_names_not_owner_display_name():
    clients, session = _clients()
    session.queue(FakeResponse(text=(
        '<ListAllMyBucketsResult>'
        "<Owner><DisplayName>owner-display</DisplayName></Owner>"
        "<Buckets><Bucket><Name>bkt-a</Name></Bucket>"
        "<Bucket><Name>bkt-b</Name></Bucket></Buckets>"
        "</ListAllMyBucketsResult>")))

    result = clients["s3"].list_buckets()

    names = [entry["Name"] for entry in result["Buckets"]]
    assert names == ["bkt-a", "bkt-b"]
    assert "owner-display" not in names
    return


def test_bucket_tagging_round_trip():
    clients, session = _clients()
    session.queue(FakeResponse(text=""))
    session.queue(FakeResponse(text=(
        "<Tagging><TagSet>"
        "<Tag><Key>owner</Key><Value>ccai</Value></Tag>"
        "</TagSet></Tagging>")))

    clients["s3"].put_bucket_tagging(
        Bucket="bkt-a",
        Tagging={"TagSet": [{"Key": "owner", "Value": "ccai"}]})
    read = clients["s3"].get_bucket_tagging(Bucket="bkt-a")

    written = session.calls[0]["body"].decode("utf-8")
    assert "<Key>owner</Key><Value>ccai</Value>" in written
    assert session.calls[0]["params"] == {"tagging": ""}
    assert read["TagSet"] == [{"Key": "owner", "Value": "ccai"}]
    return


def test_tag_values_are_xml_escaped():
    clients, session = _clients()
    session.queue(FakeResponse(text=""))

    clients["s3"].put_bucket_tagging(
        Bucket="bkt-a",
        Tagging={"TagSet": [{"Key": "k", "Value": "a & b <c>"}]})

    body = session.calls[0]["body"].decode("utf-8")
    assert "a &amp; b &lt;c&gt;" in body
    return


# ----------------------------------------------------------------------
# Route53
# ----------------------------------------------------------------------

def test_list_hosted_zones_shape():
    clients, session = _clients()
    session.queue(FakeResponse(text=(
        "<ListHostedZonesResponse><HostedZones>"
        "<HostedZone><Id>/hostedzone/Z1</Id>"
        "<Name>example.com.</Name></HostedZone>"
        "</HostedZones></ListHostedZonesResponse>")))

    result = clients["route53"].list_hosted_zones()

    zones = result["HostedZones"]
    assert zones[0]["Id"] == "/hostedzone/Z1"
    assert zones[0]["Name"] == "example.com."
    return


def test_change_batch_is_rendered_and_zone_id_is_stripped():
    clients, session = _clients()
    session.queue(FakeResponse(text=(
        "<ChangeResourceRecordSetsResponse><ChangeInfo>"
        "<Id>/change/C1</Id><Status>PENDING</Status>"
        "</ChangeInfo></ChangeResourceRecordSetsResponse>")))

    result = clients["route53"].change_resource_record_sets(
        HostedZoneId="/hostedzone/Z1",
        ChangeBatch={"Changes": [{
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": "srv-a.example.com.", "Type": "A", "TTL": 300,
                "ResourceRecords": [{"Value": "1.2.3.4"}]}}]})

    call = session.calls[0]
    # The zone id arrives prefixed and must not be doubled in the path.
    assert call["url"].endswith("/hostedzone/Z1/rrset")

    body = call["body"].decode("utf-8")
    assert "<Action>UPSERT</Action>" in body
    assert "<Name>srv-a.example.com.</Name>" in body
    assert "<TTL>300</TTL>" in body
    assert "<Value>1.2.3.4</Value>" in body
    assert result["ChangeInfo"]["Status"] == "PENDING"
    return


# ----------------------------------------------------------------------
# JSON 1.1 services
# ----------------------------------------------------------------------

def test_ssm_names_the_operation_in_the_target_header():
    clients, session = _clients()
    session.queue(FakeResponse(payload={"Parameter": {"Value": "ami-123"}}))

    result = clients["ssm"].get_parameter(Name="/aws/service/ami")

    headers = session.calls[0]["headers"]
    assert headers["x-amz-target"] == "AmazonSSM.GetParameter"
    assert headers["content-type"] == "application/x-amz-json-1.1"
    assert json.loads(session.calls[0]["body"]) == {"Name":
                                                    "/aws/service/ami"}
    assert result["Parameter"]["Value"] == "ami-123"
    return


def test_fsx_uses_its_own_target_prefix():
    clients, session = _clients()
    session.queue(FakeResponse(payload={"FileSystems": [
        {"DNSName": "fs-1.fsx.amazonaws.com",
         "LustreConfiguration": {"MountName": "abcd"}}]}))

    result = clients["fsx"].describe_file_systems(FileSystemIds=["fs-1"])

    headers = session.calls[0]["headers"]
    assert headers["x-amz-target"] == \
        "AWSSimbaAPIService_v20180301.DescribeFileSystems"
    entry = result["FileSystems"][0]
    assert entry["DNSName"] == "fs-1.fsx.amazonaws.com"
    assert entry["LustreConfiguration"]["MountName"] == "abcd"
    return


def test_json_errors_read_the_type_field():
    clients, session = _clients()
    session.queue(FakeResponse(
        status_code=400, reason="Bad Request",
        payload={"__type": "com.amazon.ssm#ParameterNotFound",
                 "message": "no such parameter"}))

    with testbase.raises(ClientError) as caught:
        clients["ssm"].get_parameter(Name="/missing")

    # JSON services qualify the type with a namespace that must be stripped.
    assert caught.value.response["Error"]["Code"] == "ParameterNotFound"
    return


def test_none_valued_json_parameters_are_dropped():
    clients, session = _clients()
    session.queue(FakeResponse(payload={}))

    clients["ssm"].get_parameter(Name="/p", WithDecryption=None)

    assert json.loads(session.calls[0]["body"]) == {"Name": "/p"}
    return
