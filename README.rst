===========================
codecraftai-restclient-aws
===========================

A pure-Python client for the AWS APIs, replacing ``boto3``.

Status
======

**In progress.** The EC2 Query-protocol codec is complete and tested; the
service clients are not yet written, and the provisioning venue still uses
``boto3``.  Nothing depends on this package yet.

Why the codec came first
========================

EC2 does not speak JSON.  Responses are XML whose element names differ from
the names callers read — ``<vpcSet><item><vpcId>`` becomes
``response["Vpcs"][0]["VpcId"]`` — and that mapping is the risky part of the
whole client.

A collection mapped to the wrong name decodes as an EMPTY LIST.  Nothing
raises; it simply reads as "no resources found".  Downstream that means a
create runs a second time, or a teardown walks past live infrastructure and
reports success.  So the mapping is verified against realistically-shaped EC2
XML before anything is built on top of it.

The mapping is mostly mechanical: a ``<xxxSet>`` element is a list whose
children are ``<item>``, and its modelled name is the de-``Set``-ed,
pluralised, UpperCamelCase form.  The irregular cases — ``instancesSet`` →
``Instances``, ``securityGroupInfo`` → ``SecurityGroups``, ``ipRanges`` →
``IpRanges`` — are named explicitly rather than left to the rule.

Two details worth recording:

* **Lists are detected structurally**, by all children being ``<item>``, so a
  collection this code has never seen still decodes as a list rather than
  collapsing into a single object.
* **Empty collections need the NAME**, since there are no children to inspect.
  An empty ``<vpcSet/>`` decodes to ``[]``, not ``""`` — the string iterates
  to nothing and so passes a loop silently, while breaking the moment a caller
  indexes, appends or type checks it.

Requests flatten the other way, into the Query protocol's dotted parameters
(``Filters.1.Values.1``).  Those lists are ONE-indexed; EC2 answers a
zero-indexed list with a confusing "missing parameter" rather than an index
error.

Signing comes from ``ccai.restclient.base.awssigv4``, already tested
against AWS's published example.
