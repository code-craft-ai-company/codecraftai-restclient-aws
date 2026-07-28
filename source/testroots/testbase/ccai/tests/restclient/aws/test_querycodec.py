"""
    .. module:: test_querycodec
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: Tests for the EC2 Query-protocol codec.

    These are the load-bearing tests of the AWS client.  A collection mapped
    to the wrong name decodes as an EMPTY LIST, which reads as "no resources
    found" — so a create runs twice, or a teardown walks past live
    infrastructure and reports success.  Nothing raises.

    The XML below is shaped the way EC2 really answers, so the names being
    asserted are the ones callers actually read.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


from ccai import testbase

from ccai.restclient.aws.querycodec import (
    decode_response, flatten_params, modeled_name, strip_namespace
)


EC2_NS = 'xmlns="http://ec2.amazonaws.com/doc/2016-11-15/"'


DESCRIBE_VPCS = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeVpcsResponse {ns}>
  <requestId>req-1</requestId>
  <vpcSet>
    <item>
      <vpcId>vpc-111</vpcId>
      <state>available</state>
      <cidrBlock>10.0.0.0/16</cidrBlock>
      <isDefault>false</isDefault>
      <tagSet>
        <item><key>Name</key><value>net-a</value></item>
        <item><key>owner</key><value>ccai</value></item>
      </tagSet>
    </item>
  </vpcSet>
</DescribeVpcsResponse>""".format(ns=EC2_NS)


DESCRIBE_INSTANCES = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeInstancesResponse {ns}>
  <reservationSet>
    <item>
      <reservationId>r-1</reservationId>
      <instancesSet>
        <item>
          <instanceId>i-111</instanceId>
          <instanceType>m5.large</instanceType>
          <privateIpAddress>10.0.0.5</privateIpAddress>
          <instanceState><code>16</code><name>running</name></instanceState>
          <placement><availabilityZone>us-east-1a</availabilityZone></placement>
          <tagSet><item><key>Name</key><value>srv-a</value></item></tagSet>
        </item>
        <item>
          <instanceId>i-222</instanceId>
          <instanceType>m5.large</instanceType>
        </item>
      </instancesSet>
    </item>
  </reservationSet>
</DescribeInstancesResponse>""".format(ns=EC2_NS)


DESCRIBE_SECURITY_GROUPS = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeSecurityGroupsResponse {ns}>
  <securityGroupInfo>
    <item>
      <groupId>sg-111</groupId>
      <groupName>sg-a</groupName>
      <vpcId>vpc-111</vpcId>
      <ipPermissions>
        <item>
          <ipProtocol>tcp</ipProtocol>
          <fromPort>22</fromPort>
          <toPort>22</toPort>
          <ipRanges>
            <item><cidrIp>0.0.0.0/0</cidrIp></item>
          </ipRanges>
        </item>
      </ipPermissions>
      <tagSet><item><key>owner</key><value>ccai</value></item></tagSet>
    </item>
  </securityGroupInfo>
</DescribeSecurityGroupsResponse>""".format(ns=EC2_NS)


DESCRIBE_ROUTE_TABLES = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeRouteTablesResponse {ns}>
  <routeTableSet>
    <item>
      <routeTableId>rtb-111</routeTableId>
      <vpcId>vpc-111</vpcId>
      <associationSet>
        <item>
          <routeTableAssociationId>rtbassoc-1</routeTableAssociationId>
          <main>true</main>
        </item>
      </associationSet>
      <routeSet>
        <item><destinationCidrBlock>0.0.0.0/0</destinationCidrBlock></item>
      </routeSet>
    </item>
  </routeTableSet>
</DescribeRouteTablesResponse>""".format(ns=EC2_NS)


DESCRIBE_INTERNET_GATEWAYS = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeInternetGatewaysResponse {ns}>
  <internetGatewaySet>
    <item>
      <internetGatewayId>igw-111</internetGatewayId>
      <attachmentSet>
        <item><vpcId>vpc-111</vpcId><state>available</state></item>
      </attachmentSet>
      <tagSet><item><key>owner</key><value>ccai</value></item></tagSet>
    </item>
  </internetGatewaySet>
</DescribeInternetGatewaysResponse>""".format(ns=EC2_NS)


CREATE_VPC = """<?xml version="1.0" encoding="UTF-8"?>
<CreateVpcResponse {ns}>
  <vpc>
    <vpcId>vpc-999</vpcId>
    <cidrBlock>10.1.0.0/16</cidrBlock>
  </vpc>
</CreateVpcResponse>""".format(ns=EC2_NS)


DESCRIBE_VOLUMES = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeVolumesResponse {ns}>
  <volumeSet>
    <item>
      <volumeId>vol-111</volumeId>
      <size>100</size>
      <volumeType>gp3</volumeType>
      <availabilityZone>us-east-1a</availabilityZone>
      <attachmentSet>
        <item><instanceId>i-111</instanceId><device>/dev/sdf</device></item>
      </attachmentSet>
    </item>
  </volumeSet>
</DescribeVolumesResponse>""".format(ns=EC2_NS)


EMPTY_VPCS = """<?xml version="1.0" encoding="UTF-8"?>
<DescribeVpcsResponse {ns}>
  <vpcSet/>
</DescribeVpcsResponse>""".format(ns=EC2_NS)


# ----------------------------------------------------------------------
# name mapping
# ----------------------------------------------------------------------

@testbase.parametrize("wire,modeled", [
    ("vpcSet", "Vpcs"),
    ("subnetSet", "Subnets"),
    ("tagSet", "Tags"),
    ("instancesSet", "Instances"),
    ("reservationSet", "Reservations"),
    ("attachmentSet", "Attachments"),
    ("associationSet", "Associations"),
    ("routeTableSet", "RouteTables"),
    ("internetGatewaySet", "InternetGateways"),
    ("volumeSet", "Volumes"),
    ("securityGroupInfo", "SecurityGroups"),
    ("ipPermissions", "IpPermissions"),
    ("ipRanges", "IpRanges"),
    ("vpcId", "VpcId"),
    ("cidrBlock", "CidrBlock"),
    ("groupId", "GroupId"),
    ("availabilityZone", "AvailabilityZone"),
])
def test_wire_names_map_to_the_names_callers_read(wire, modeled):
    assert modeled_name(wire) == modeled
    return


def test_strip_namespace():
    assert strip_namespace("{http://ec2}vpcSet") == "vpcSet"
    assert strip_namespace("vpcSet") == "vpcSet"
    return


# ----------------------------------------------------------------------
# decoding — the shapes callers actually read
# ----------------------------------------------------------------------

def test_describe_vpcs_shape():
    decoded = decode_response(DESCRIBE_VPCS)

    vpcs = decoded["Vpcs"]
    assert len(vpcs) == 1
    assert vpcs[0]["VpcId"] == "vpc-111"
    assert vpcs[0]["CidrBlock"] == "10.0.0.0/16"
    assert vpcs[0]["Tags"] == [{"Key": "Name", "Value": "net-a"},
                               {"Key": "owner", "Value": "ccai"}]
    return


def test_describe_instances_nests_instances_under_reservations():
    decoded = decode_response(DESCRIBE_INSTANCES)

    reservations = decoded["Reservations"]
    assert len(reservations) == 1

    instances = reservations[0]["Instances"]
    # Two items under one reservation; collapsing them would silently lose a
    # machine from every inventory.
    assert len(instances) == 2
    assert instances[0]["InstanceId"] == "i-111"
    assert instances[0]["InstanceType"] == "m5.large"
    assert instances[0]["PrivateIpAddress"] == "10.0.0.5"
    assert instances[0]["Placement"]["AvailabilityZone"] == "us-east-1a"
    assert instances[1]["InstanceId"] == "i-222"
    return


def test_security_group_permissions_shape():
    decoded = decode_response(DESCRIBE_SECURITY_GROUPS)

    groups = decoded["SecurityGroups"]
    assert groups[0]["GroupId"] == "sg-111"
    assert groups[0]["VpcId"] == "vpc-111"

    permission = groups[0]["IpPermissions"][0]
    assert permission["IpProtocol"] == "tcp"
    assert permission["FromPort"] == "22"
    assert permission["ToPort"] == "22"
    assert permission["IpRanges"] == [{"CidrIp": "0.0.0.0/0"}]
    return


def test_route_table_associations_shape():
    decoded = decode_response(DESCRIBE_ROUTE_TABLES)

    table = decoded["RouteTables"][0]
    assert table["RouteTableId"] == "rtb-111"

    association = table["Associations"][0]
    assert association["RouteTableAssociationId"] == "rtbassoc-1"
    # The venue skips the main association when tearing down; reading this as
    # the string "true" would make every association look non-main.
    assert association["Main"] is True
    return


def test_internet_gateway_attachments_shape():
    decoded = decode_response(DESCRIBE_INTERNET_GATEWAYS)

    gateway = decoded["InternetGateways"][0]
    assert gateway["InternetGatewayId"] == "igw-111"
    assert gateway["Attachments"] == [{"VpcId": "vpc-111",
                                       "State": "available"}]
    return


def test_volume_attachments_shape():
    decoded = decode_response(DESCRIBE_VOLUMES)

    volume = decoded["Volumes"][0]
    assert volume["VolumeId"] == "vol-111"
    assert volume["Size"] == "100"
    assert volume["Attachments"][0]["InstanceId"] == "i-111"
    return


def test_create_returns_the_singular_resource():
    decoded = decode_response(CREATE_VPC)

    assert decoded["Vpc"]["VpcId"] == "vpc-999"
    return


def test_empty_collection_decodes_as_an_empty_list_not_a_string():
    decoded = decode_response(EMPTY_VPCS)

    # An empty <vpcSet/> has no children, so the structural rule cannot tell
    # it is a list — the NAME has to.  Decoding it as "" would iterate to
    # nothing and so pass a loop silently, while breaking the moment a caller
    # indexes, appends or type checks it.
    assert decoded["Vpcs"] == []
    assert isinstance(decoded["Vpcs"], list) is True
    return


def test_empty_nested_collections_are_lists_too():
    body = ("<DescribeSecurityGroupsResponse><securityGroupInfo><item>"
            "<groupId>sg-1</groupId><ipPermissions/><tagSet/>"
            "</item></securityGroupInfo></DescribeSecurityGroupsResponse>")

    group = decode_response(body)["SecurityGroups"][0]

    assert group["IpPermissions"] == []
    assert group["Tags"] == []
    return


def test_repeated_elements_without_a_set_wrapper_still_become_a_list():
    body = ("<Resp><thing><name>a</name></thing>"
            "<thing><name>b</name></thing></Resp>")

    decoded = decode_response(body)

    # Without this, every occurrence but the last would be dropped.
    assert decoded["Thing"] == [{"Name": "a"}, {"Name": "b"}]
    return


def test_booleans_are_decoded_as_booleans():
    decoded = decode_response(DESCRIBE_VPCS)

    assert decoded["Vpcs"][0]["IsDefault"] is False
    return


def test_empty_body_decodes_to_an_empty_dict():
    assert decode_response("") == {}
    assert decode_response("   ") == {}
    return


def test_namespaced_and_unnamespaced_bodies_decode_alike():
    without = DESCRIBE_VPCS.replace(EC2_NS, "")

    assert decode_response(without)["Vpcs"][0]["VpcId"] == "vpc-111"
    return


# ----------------------------------------------------------------------
# request flattening
# ----------------------------------------------------------------------

def test_lists_are_one_indexed():
    params = flatten_params({"Filters": [{"Name": "vpc-id",
                                          "Values": ["vpc-1"]}]})

    # EC2 answers a zero-indexed list with a confusing "missing parameter"
    # rather than an index error.
    assert params["Filters.1.Name"] == "vpc-id"
    assert params["Filters.1.Values.1"] == "vpc-1"
    return


def test_nested_structures_flatten_with_dotted_names():
    params = flatten_params({
        "TagSpecifications": [
            {"ResourceType": "vpc",
             "Tags": [{"Key": "owner", "Value": "ccai"}]}]})

    assert params["TagSpecifications.1.ResourceType"] == "vpc"
    assert params["TagSpecifications.1.Tags.1.Key"] == "owner"
    assert params["TagSpecifications.1.Tags.1.Value"] == "ccai"
    return


def test_booleans_flatten_to_lowercase_literals():
    params = flatten_params({"DryRun": True, "Force": False})

    assert params["DryRun"] == "true"
    assert params["Force"] == "false"
    return


def test_none_values_are_dropped():
    params = flatten_params({"VpcId": "vpc-1", "CidrBlock": None})

    assert "CidrBlock" not in params
    assert params["VpcId"] == "vpc-1"
    return


def test_scalars_are_stringified():
    params = flatten_params({"MaxCount": 3, "MinCount": 1})

    assert params["MaxCount"] == "3"
    assert params["MinCount"] == "1"
    return


def test_rest_xml_named_repetition_decodes_as_a_list():
    """
        REST-XML repeats a NAMED element inside a plural container, unlike
        Query's <item> wrapper.
    """
    body = ("<ListHostedZonesResponse><HostedZones>"
            "<HostedZone><Id>Z1</Id></HostedZone>"
            "<HostedZone><Id>Z2</Id></HostedZone>"
            "</HostedZones></ListHostedZonesResponse>")

    zones = decode_response(body)["HostedZones"]

    assert [entry["Id"] for entry in zones] == ["Z1", "Z2"]
    return


def test_single_field_structures_are_not_mistaken_for_lists():
    """
        A one-field structure also has children that all share a tag, so the
        named-repetition rule must additionally require the container to be
        the plural of the child.
    """
    body = ("<DescribeInstancesResponse><reservationSet><item>"
            "<instancesSet><item><instanceId>i-1</instanceId>"
            "<placement><availabilityZone>us-east-1a</availabilityZone>"
            "</placement></item></instancesSet>"
            "</item></reservationSet></DescribeInstancesResponse>")

    instance = decode_response(body)["Reservations"][0]["Instances"][0]

    # Placement is a structure, not a one-element list.
    assert instance["Placement"] == {"AvailabilityZone": "us-east-1a"}
    return


def test_singleton_named_repetition_still_decodes_as_a_list():
    body = ("<Resp><HostedZones><HostedZone><Id>Z1</Id></HostedZone>"
            "</HostedZones></Resp>")

    zones = decode_response(body)["HostedZones"]

    # One zone is still a list; collapsing it would break every caller that
    # iterates the result.
    assert isinstance(zones, list) is True
    assert len(zones) == 1
    return
