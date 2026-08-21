# Requirements

## Introduction

The `aws-client` feature provides a pure-Python client for the subset of the
AWS APIs the provisioning venue uses, without depending on `boto3` or
`botocore`. It covers five services across three different AWS wire
protocols: EC2 (Query), S3 and Route53 (REST-XML), and SSM and FSx
(JSON 1.1). What the five share is SigV4 request signing, so the package is
factored as one signing transport (`AwsTransport`) plus one client per
protocol family (`serviceclients`), with the Query-protocol wire codec
isolated in `querycodec`.

The package is a *drop-in shape* replacement, not a redesign. Method names,
keyword names, and returned dict shapes match `boto3`'s — `describe_vpcs(
Filters=[...])`, `head_bucket(Bucket=...)`, `response["Vpcs"][0]["VpcId"]` —
because consumer code in `codecraftai-provisioning` already calls them that
way, and errors keep the botocore `ClientError` name and `.response`
envelope because those handlers read `xcpt.response["Error"]["Code"]` to
tell an absent resource from a denied one.

SigV4 signing itself is reused from `ccai.restclient.base.awssigv4`. This
package is consumed by `codecraftai-provisioning/venues/aws/` through
`AwsBoto3SessionFactory`, which is where an `AwsAccessKeyCredential` is
unwrapped into the raw key material this package's transport accepts.

---

## Requirements

### Requirement 1: Sign Every Request With SigV4

**User Story:** As a venue provisioner, I want every AWS request signed with
SigV4 scoped to the right service and region so that the AWS control plane
accepts it without a vendor SDK in the dependency tree.

#### Acceptance Criteria

1. WHEN the caller constructs an `AwsTransport` with an access key, secret
   key, and region THE SYSTEM SHALL build a `SigV4Signer` from
   `ccai.restclient.base.awssigv4` for each request.
2. WHEN a request is sent THE SYSTEM SHALL sign the method, URL, query
   parameters, headers, and body, and SHALL place the result in the
   `Authorization` header as `AWS4-HMAC-SHA256 ...`.
3. THE SYSTEM SHALL scope the credential scope string to the invoked service,
   so that an EC2 call signs against `/ec2/aws4_request` and an SSM call
   against `/ssm/aws4_request`.
4. WHEN the caller supplies a `session_token` THE SYSTEM SHALL pass it to the
   signer so that temporary credentials are usable.

### Requirement 2: Resolve Endpoints and Signing Regions per Service

**User Story:** As a caller, I want endpoint and signing-region resolution
handled for me so that global services do not fail to resolve or fail to
verify.

#### Acceptance Criteria

1. WHEN `endpoint_for(service, region)` is invoked for a regional service THE
   SYSTEM SHALL return `https://<service>.<region>.amazonaws.com`.
2. WHEN `endpoint_for` is invoked for `route53` THE SYSTEM SHALL return the
   global endpoint `https://route53.amazonaws.com`, because a regional
   Route53 hostname does not resolve.
3. WHEN `signing_region_for` is invoked for `route53` THE SYSTEM SHALL return
   `us-east-1` regardless of the transport's region, because the global
   endpoint still signs against `us-east-1`.
4. THE SYSTEM SHALL accept an `endpoint` override on every service client
   constructor so that a test or an alternate partition can redirect traffic.

### Requirement 3: Speak the EC2 Query Protocol

**User Story:** As a provisioner managing VPCs, subnets, security groups and
instances, I want EC2 operations callable by their botocore names so that
existing consumer code works unchanged.

#### Acceptance Criteria

1. WHEN the caller invokes any snake_case attribute on `Ec2Client` THE SYSTEM
   SHALL derive the UpperCamelCase `Action` name from it and issue a
   form-encoded POST carrying `Action` and `Version=2016-11-15`.
2. THE SYSTEM SHALL resolve operation names dynamically via `__getattr__`, so
   that an operation this package has never been told about is still callable
   without adding a stub.
3. WHEN the caller passes a nested structure such as
   `Filters=[{"Name": ..., "Values": [...]}]` THE SYSTEM SHALL flatten it into
   one-indexed dotted parameters (`Filters.1.Name`, `Filters.1.Values.1`).
4. WHEN a response is received THE SYSTEM SHALL decode the XML into the
   modelled dict shape callers read, e.g. `result["Vpcs"][0]["VpcId"]`.

### Requirement 4: Map Query-Protocol Wire Names to Modelled Names

**User Story:** As a maintainer, I want the wire-to-modelled name mapping to be
explicit and total, because a collection mapped to the wrong name yields an
empty list that reads as "no resources found" — so a create runs twice, or a
teardown walks past live infrastructure and reports success.

#### Acceptance Criteria

1. WHEN an element name appears in `NAME_OVERRIDES` THE SYSTEM SHALL use the
   override rather than the mechanical rule.
2. WHEN an element name ends in `Set` THE SYSTEM SHALL strip the suffix,
   pluralise the stem preserving its casing, and UpperCamelCase the result.
3. WHEN an element carries an XML namespace THE SYSTEM SHALL strip it before
   mapping, so that namespaced and un-namespaced bodies decode alike.
4. WHEN an element is EMPTY and its name denotes a collection THE SYSTEM SHALL
   decode it as `[]` and never as `""`.

### Requirement 5: Detect Repetition Structurally in Both XML Dialects

**User Story:** As a maintainer, I want list detection to work on collections
the codec has never seen, so that an unmodelled collection decodes as a list
rather than collapsing into a single object.

#### Acceptance Criteria

1. WHEN an element's children all carry the tag `item` THE SYSTEM SHALL decode
   the element as a list (the Query dialect).
2. WHEN an element's children all share one tag AND the container's name is the
   plural of that tag THE SYSTEM SHALL decode the element as a list (the
   REST-XML dialect, e.g. `<HostedZones><HostedZone>`).
3. WHEN an element has children that share a tag but the container is NOT the
   plural of it THE SYSTEM SHALL decode it as a dict, so that a single-field
   structure such as `<placement><availabilityZone>` is not mistaken for a
   one-element list.
4. WHEN a named element repeats without a wrapper THE SYSTEM SHALL accumulate
   the occurrences into a list rather than dropping all but the last.
5. WHEN element text is `true` or `false` THE SYSTEM SHALL decode it as a
   Python bool.

### Requirement 6: Provide the S3 Bucket-Level Surface

**User Story:** As a provisioner staging buckets, I want the bucket-level S3
operations so that bucket lifecycle and tagging run through the same signed
transport as compute.

#### Acceptance Criteria

1. THE SYSTEM SHALL implement `head_bucket`, `create_bucket`, `delete_bucket`,
   `list_buckets`, `get_bucket_tagging`, and `put_bucket_tagging` on
   `S3Client`.
2. WHEN `create_bucket` is invoked WITHOUT a `CreateBucketConfiguration` THE
   SYSTEM SHALL send no body, because `us-east-1` rejects a request carrying a
   `LocationConstraint`.
3. WHEN `list_buckets` decodes a response THE SYSTEM SHALL read bucket `Name`
   elements only and SHALL NOT pick up the owner's display name.
4. WHEN `put_bucket_tagging` renders a tag set THE SYSTEM SHALL XML-escape
   `&`, `<`, and `>` in keys and values.
5. THE SYSTEM SHALL address the tagging sub-resource with the query parameter
   `tagging` so that it is included in the signature.

### Requirement 7: Provide the Route53 Record Surface

**User Story:** As a provisioner publishing DNS records, I want hosted-zone
enumeration and atomic record changes.

#### Acceptance Criteria

1. WHEN the caller invokes `list_hosted_zones` THE SYSTEM SHALL GET the
   `2013-04-01` hosted-zone path and return a dict carrying `HostedZones`,
   normalising a single-zone response into a list.
2. WHEN the caller invokes `change_resource_record_sets` with a
   `HostedZoneId` carrying a `/hostedzone/` prefix THE SYSTEM SHALL strip the
   prefix so the composed path is not doubled.
3. THE SYSTEM SHALL render the change batch as XML carrying `Action`, `Name`,
   `Type`, optional `TTL`, and each `ResourceRecord` `Value`, and SHALL omit
   `TTL` when it is absent.

### Requirement 8: Speak the JSON 1.1 Protocol for SSM and FSx

**User Story:** As a provisioner reading AMI parameters and FSx file systems, I
want the JSON services callable by their botocore names.

#### Acceptance Criteria

1. WHEN the caller invokes any snake_case attribute on `SsmClient` or
   `FsxClient` THE SYSTEM SHALL derive the UpperCamelCase operation name and
   POST a JSON body with `content-type: application/x-amz-json-1.1`.
2. THE SYSTEM SHALL name the operation in the `x-amz-target` header qualified
   by the service's target prefix — `AmazonSSM` for SSM and
   `AWSSimbaAPIService_v20180301` for FSx.
3. WHEN a keyword argument is `None` THE SYSTEM SHALL drop it from the request
   payload rather than sending a null.
4. WHEN the response body is empty or not decodable as JSON THE SYSTEM SHALL
   return an empty dict rather than raising.

### Requirement 9: Report Errors in the botocore Envelope

**User Story:** As a consumer, I want failures to arrive as a `ClientError`
carrying the AWS error code so that I can tell "absent" from "denied" and
recover only the former.

#### Acceptance Criteria

1. WHEN a response status is outside `200..299` THE SYSTEM SHALL raise
   `ClientError` whose `.response` carries `Error.Code`, `Error.Message`, and
   `ResponseMetadata.HTTPStatusCode`.
2. WHEN the failed body is JSON carrying `__type` THE SYSTEM SHALL use the
   segment after the final `#` as the code, stripping the service namespace.
3. WHEN the failed body is XML carrying an `<Error><Code>` pair THE SYSTEM
   SHALL use that code and message.
4. WHEN the failed response has NO body — as with a failed `HEAD` — THE SYSTEM
   SHALL use the HTTP status as the code, so that a missing bucket reports
   `"404"` and a denied one does not.
5. THE SYSTEM SHALL include the method, URL, status, code, and message in the
   exception's human-readable text, and SHALL retain the raw body on `.body`.

### Requirement 10: Remain Injectable and Bounded

**User Story:** As a test author, I want to drive every client without a live
AWS account and without patching module globals.

#### Acceptance Criteria

1. THE SYSTEM SHALL accept a pre-built `session` object on `AwsTransport`,
   used in place of a `requests.Session`, as the sole transport seam.
2. THE SYSTEM SHALL apply a default per-request timeout of 60 seconds and
   SHALL accept a per-request override.
3. THE SYSTEM SHALL expose `build_clients(transport)` returning a dict keyed by
   the boto3 service names `ec2`, `s3`, `route53`, `ssm`, and `fsx`, all
   sharing one transport.
4. THE SYSTEM SHALL NOT import `boto3` or `botocore` at any point.
