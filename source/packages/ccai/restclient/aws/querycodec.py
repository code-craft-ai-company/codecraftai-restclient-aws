"""
    .. module:: querycodec
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: The EC2 Query-protocol codec — request flattening and response
               shape mapping.

    EC2 does not speak JSON.  Requests are form-encoded with a flattened
    parameter naming (``Filter.1.Name``, ``Filter.1.Value.1``), and responses
    are XML whose element names differ from the names callers read:

    .. code:: xml

        <DescribeVpcsResponse>
          <vpcSet>
            <item>
              <vpcId>vpc-123</vpcId>
              <cidrBlock>10.0.0.0/16</cidrBlock>
              <tagSet><item><key>Name</key><value>a</value></item></tagSet>
            </item>
          </vpcSet>
        </DescribeVpcsResponse>

    Callers read ``response["Vpcs"][0]["VpcId"]`` and
    ``["Tags"][0]["Key"]``.  That mapping is the risky part of this whole
    client: a collection mapped to the wrong name yields an EMPTY LIST, which
    reads as "no resources found" — so a create runs twice, or a teardown
    walks past live infrastructure and reports success.

    The mapping is mostly mechanical.  A ``<xxxSet>`` element is a list whose
    children are ``<item>``; its modelled name is the de-``Set``-ed,
    pluralised, UpperCamelCase form.  Everything else is UpperCamelCase.  The
    irregular cases are named explicitly in :data:`NAME_OVERRIDES` rather than
    left to the rule, because a wrong guess here is silent.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import xml.etree.ElementTree as ElementTree

from typing import Any, Dict, List, Optional


# Elements whose modelled name the mechanical rule gets wrong.  Keyed by the
# wire name, lowercase.
NAME_OVERRIDES = {
    "instancesset": "Instances",
    "reservationset": "Reservations",
    "groupset": "Groups",
    "ipranges": "IpRanges",
    "ippermissions": "IpPermissions",
    "ippermissionsegress": "IpPermissionsEgress",
    "keyset": "KeyPairs",
    "iteminstancesset": "Instances",
    "networkinterfaceset": "NetworkInterfaces",
    "blockdevicemapping": "BlockDeviceMappings",
    "placementgroupset": "PlacementGroups",
    "volumeset": "Volumes",
    "attachmentset": "Attachments",
    "associationset": "Associations",
    "routeset": "Routes",
    "imagesset": "Images",
    "tagset": "Tags",
    "securitygroupinfo": "SecurityGroups",
    "internetgatewayset": "InternetGateways",
    "routetableset": "RouteTables",
    "subnetset": "Subnets",
    "vpcset": "Vpcs",
}

# Values EC2 renders as XML text but callers read as booleans.
BOOLEAN_TEXT = {"true": True, "false": False}


def strip_namespace(tag: str) -> str:
    """
        Remove any XML namespace from an element tag.

        :param tag: The element tag.

        :returns: The local name.
    """
    if tag.startswith("{") is True:
        rtnval = tag.split("}", 1)[1]
        return rtnval

    rtnval = tag
    return rtnval


def _pluralize(name: str) -> str:
    """
        Pluralise an already-lowercased singular name.

        :param name: The singular name.

        :returns: The plural form.
    """
    if name.endswith("s") is True:
        rtnval = name
        return rtnval
    if name.endswith("y") is True and len(name) > 1:
        rtnval = name[:-1] + "ies"
        return rtnval

    rtnval = name + "s"
    return rtnval


def _upper_camel(name: str) -> str:
    """
        Convert a lowerCamelCase wire name to UpperCamelCase.

        :param name: The wire name.

        :returns: The modelled name.
    """
    if len(name) == 0:
        rtnval = name
        return rtnval

    rtnval = name[0].upper() + name[1:]
    return rtnval


def modeled_name(wire_name: str) -> str:
    """
        Map a wire element name to the name callers read.

        :param wire_name: The XML element's local name.

        :returns: The modelled name.
    """
    override = NAME_OVERRIDES.get(wire_name.lower(), None)
    if override is not None:
        rtnval = override
        return rtnval

    if wire_name.endswith("Set") is True:
        stem = wire_name[:-3]
        rtnval = _upper_camel(_pluralize_preserving(stem))
        return rtnval

    rtnval = _upper_camel(wire_name)
    return rtnval


def _pluralize_preserving(name: str) -> str:
    """
        Pluralise a camelCase stem without disturbing its casing.

        :param name: The stem.

        :returns: The pluralised stem.
    """
    if name.endswith("s") is True:
        rtnval = name
        return rtnval
    if name.endswith("y") is True and len(name) > 1:
        rtnval = name[:-1] + "ies"
        return rtnval

    rtnval = name + "s"
    return rtnval


def _is_list_container(element: Any) -> bool:
    """
        Report whether an element is a list wrapper.

        EC2 wraps every repeated structure in a container whose children are
        all ``<item>``.  Detecting it structurally rather than by name means a
        collection this code has never seen still decodes as a list rather
        than collapsing into a single object — which is the failure that would
        otherwise read as "one resource" or "none".

        :param element: The element to inspect.

        :returns: True when the element is a list container.
    """
    children = list(element)
    if len(children) == 0:
        rtnval = False
        return rtnval

    for child in children:
        if strip_namespace(child.tag) != "item":
            rtnval = False
            return rtnval

    rtnval = True
    return rtnval


def _coerce_text(text: Optional[str]) -> Any:
    """
        Convert element text to the type callers expect.

        :param text: The element's text.

        :returns: A bool for true/false, otherwise the stripped string.
    """
    if text is None:
        rtnval: Any = ""
        return rtnval

    stripped = text.strip()

    lowered = stripped.lower()
    if lowered in BOOLEAN_TEXT:
        rtnval = BOOLEAN_TEXT[lowered]
        return rtnval

    rtnval = stripped
    return rtnval


def is_collection_tag(wire_name: str) -> bool:
    """
        Report whether an element name denotes a collection.

        Used for EMPTY elements, where there are no ``<item>`` children to
        detect structurally.  An empty ``<vpcSet/>`` must decode to ``[]``,
        not ``""``: the string iterates to nothing and so passes a loop
        silently, but breaks the moment a caller indexes, appends or type
        checks it — and it is the wrong answer regardless.

        :param wire_name: The element's local name.

        :returns: True when the element is a collection.
    """
    if wire_name.endswith("Set") is True:
        rtnval = True
        return rtnval

    override = NAME_OVERRIDES.get(wire_name.lower(), None)
    if override is not None:
        # Every override in the table names a collection.
        rtnval = True
        return rtnval

    rtnval = False
    return rtnval


def decode_element(element: Any) -> Any:
    """
        Decode one XML element into modelled data.

        :param element: The element.

        :returns: A dict, a list, or a scalar.
    """
    children = list(element)

    if len(children) == 0:
        text = element.text
        if text is None or len(text.strip()) == 0:
            if is_collection_tag(strip_namespace(element.tag)) is True:
                rtnval: Any = []
                return rtnval
        rtnval = _coerce_text(text)
        return rtnval

    if _is_list_container(element) is True:
        rtnval = [decode_element(child) for child in children]
        return rtnval

    decoded: Dict[str, Any] = {}
    for child in children:
        name = modeled_name(strip_namespace(child.tag))
        value = decode_element(child)

        if name in decoded:
            # A repeated element without a Set wrapper still has to become a
            # list, or every occurrence but the last would be dropped.
            existing = decoded[name]
            if isinstance(existing, list) is True:
                existing.append(value)
            else:
                decoded[name] = [existing, value]
            continue

        decoded[name] = value

    rtnval = decoded
    return rtnval


def decode_response(xml_text: str) -> Dict[str, Any]:
    """
        Decode an EC2 Query-protocol response body.

        :param xml_text: The XML body.

        :returns: The modelled response dict, empty when the body is empty.
    """
    if xml_text is None or len(xml_text.strip()) == 0:
        rtnval: Dict[str, Any] = {}
        return rtnval

    root = ElementTree.fromstring(xml_text)

    decoded = decode_element(root)
    if isinstance(decoded, dict) is False:
        rtnval = {"Value": decoded}
        return rtnval

    rtnval = decoded
    return rtnval


def flatten_params(value: Any, prefix: str = "",
                   into: Optional[Dict[str, str]] = None
                   ) -> Dict[str, str]:
    """
        Flatten a request structure into Query-protocol parameters.

        Lists are ONE-indexed — ``Filter.1.Name``, not ``Filter.0.Name`` —
        which is the detail most easily got wrong, and which EC2 answers with
        a confusing "missing parameter" rather than an index error.

        :param value: The value to flatten.
        :param prefix: The parameter-name prefix.
        :param into: The accumulator.

        :returns: The flat parameter mapping.
    """
    collected: Dict[str, str] = into if into is not None else {}

    if isinstance(value, dict) is True:
        for name, item in value.items():
            if item is None:
                continue
            child_prefix = name if len(prefix) == 0 else "{}.{}".format(
                prefix, name)
            flatten_params(item, child_prefix, collected)
        rtnval = collected
        return rtnval

    if isinstance(value, (list, tuple)) is True:
        for index, item in enumerate(value, start=1):
            child_prefix = "{}.{}".format(prefix, index)
            flatten_params(item, child_prefix, collected)
        rtnval = collected
        return rtnval

    if isinstance(value, bool) is True:
        collected[prefix] = "true" if value is True else "false"
        rtnval = collected
        return rtnval

    collected[prefix] = str(value)
    rtnval = collected
    return rtnval
