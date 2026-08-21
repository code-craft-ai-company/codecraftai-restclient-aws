# Design

## Overview

The AWS client is factored around the one thing the five covered services have
in common — SigV4 signing — and keeps everything they do *not* share in the
service clients. `AwsTransport` owns credentials, endpoint resolution, signing,
sending, and error classification. Each service client owns its protocol:
form-encoding for EC2, hand-rendered XML for S3 and Route53, JSON plus an
`x-amz-target` header for SSM and FSx.

This package deliberately does not subclass `RestClientBase`. The AWS wire
protocols are not the JSON-over-REST shape that base models, and the consumer
contract here is boto3's method and dict shapes rather than a modelled venue
surface. What *is* reused from `codecraftai-restclient-base` is `SigV4Signer`,
which is the part with real cryptographic risk.

---

## Architecture

```
┌────────────────────────────────────────────────────────┐
│  codecraftai-provisioning / venues / aws               │
│  AwsBoto3SessionFactory                                │
│  (unwraps AwsAccessKeyCredential -> raw key material)  │
└──────────────────────────┬─────────────────────────────┘
                           │ build_clients(transport=...)
                           ▼
┌────────────────────────────────────────────────────────┐
│  Ec2Client   S3Client   Route53Client   SsmClient      │
│  (Query)     (REST-XML) (REST-XML)      FsxClient      │
│                                         (JSON 1.1)     │
│      │           │           │              │          │
│      └───── querycodec ──────┘              │          │
│         (flatten / decode)                  │          │
└──────────────────────────┬─────────────────────────────┘
                           │ send / raise_for_status
                           ▼
┌────────────────────────────────────────────────────────┐
│  AwsTransport      ── SigV4Signer (restclient-base)    │
│                    ── requests.Session (injectable)    │
└──────────────────────────┬─────────────────────────────┘
                           ▼
        ec2 / s3 / route53 / ssm / fsx  .amazonaws.com
```

---

## Module Layout

```
source/packages/ccai/restclient/aws/
├── __init__.py
├── awstransport.py     # AwsTransport, endpoint_for, signing_region_for
├── querycodec.py       # flatten_params, decode_response, modeled_name
├── serviceclients.py   # Ec2Client, S3Client, Route53Client, Ssm/Fsx, build_clients
└── awserror.py         # ClientError
```

---

## Notable Choices

**Dynamic operation dispatch.** `Ec2Client` and `JsonServiceClient` resolve
operations through `__getattr__`, converting a snake_case attribute into an
UpperCamelCase action name. botocore generates its methods from a service
model; deriving them by name achieves the same reach without vendoring a
model, and an operation the package has never been told about still works.
`S3Client` and `Route53Client` are the exception — their operations differ in
HTTP method, path, and body shape, so each is written out.

**The name-mapping table is the risky part.** EC2 returns XML whose element
names differ from the ones callers read (`<vpcSet><item><vpcId>` versus
`response["Vpcs"][0]["VpcId"]`). The mechanical rule — de-`Set`, pluralise,
UpperCamelCase — covers most of it, and the ~22 irregular cases are named
explicitly in `NAME_OVERRIDES`. Guessing is not acceptable here because the
failure is silent: a mis-mapped collection decodes to an empty list, which
reads as "no such resource" and drives a duplicate create or a teardown that
walks past live infrastructure.

**Empty collections decode as `[]`, not `""`.** An empty `<vpcSet/>` has no
children to inspect structurally, so `is_collection_tag` decides from the
name. A string would iterate to nothing and pass a loop silently while
breaking on the first index, append, or type check.

**Two XML dialects, one structural test.** `_is_list_container` accepts both
the Query form (all children tagged `item`) and the REST-XML form (all
children share a tag AND the container is its plural). The plural requirement
is what keeps a single-field structure like
`<placement><availabilityZone>…</availabilityZone></placement>` from being
read as a one-element list.

**Global services.** Route53 has one endpoint and still signs against
`us-east-1`; `endpoint_for` and `signing_region_for` special-case it rather
than letting the regional template produce a hostname that does not resolve.

**Error codes come from three places.** XML services nest `<Error><Code>`,
JSON services use `__type` qualified by a namespace that must be stripped at
the `#`, and a failed `HEAD` has no body at all — in which case the HTTP
status stands in as the code. That last case is load-bearing: `head_bucket`
callers key on `"404"` to mean "create it" and must not treat a `403` the
same way.

**`us-east-1` and `CreateBucketConfiguration`.** S3 rejects a create that
carries a `LocationConstraint` in `us-east-1`, so the configuration is
optional and the body is omitted entirely when it is absent, rather than
always sent with a computed value.

---

## Error Model

`ClientError` keeps botocore's name and `.response` envelope:

```python
{"Error": {"Code": ..., "Message": ...},
 "ResponseMetadata": {"HTTPStatusCode": ...}}
```

plus flat `.code`, `.status`, and `.body` attributes. Consumer code in
`codecraftai-provisioning` already catches `ClientError` and reads
`xcpt.response["Error"]["Code"]`; preserving the shape is what lets those
handlers keep working against this package.

---

## See Also

- `codecraftai-restclient-base` — `ccai.restclient.base.awssigv4.SigV4Signer`,
  the reused signing implementation.
- `codecraftai-credentials` — `ccai.credentials.awsaccesskeycredential`,
  the credential type the consumer unwraps.
- `codecraftai-provisioning/venues/aws/awsboto3sessionfactory.py` — the
  consumer that builds the transport and caches the clients.

---

## Testing Strategy

Tests live under
`source/testroots/testbase/ccai/tests/restclient/aws/` and run through the
testbase runner, not pytest.

`test_serviceclients.py` drives every client through a `FakeSession` injected
on the `session=` seam, asserting on the recorded request (method, URL, body,
headers, params) and on the decoded result. It covers signing scope per
service, endpoint globality, EC2 action derivation and filter flattening,
the S3 404-versus-403 distinction, `CreateBucketConfiguration` omission, tag
round-tripping and escaping, Route53 zone-id stripping and change-batch
rendering, and the JSON target headers and `None`-dropping.

`test_querycodec.py` drives the codec directly against captured response
shapes for VPCs, instances-under-reservations, security-group permissions,
route-table associations, gateway and volume attachments, plus the encoding
rules — one-indexed lists, dotted nesting, lowercase boolean literals,
`None` dropping.

No live AWS account is required for any test in the suite.
