# Implementation Plan — AWS Client

## Package Skeleton

- [x] 1. Create `source/packages/ccai/restclient/aws/` with `awstransport`, `querycodec`, `serviceclients`, and `awserror`.
- [x] 2. Take SigV4 signing from `codecraftai-restclient-base` rather than vendoring a signer.

## Transport

- [x] 3. Implement `AwsTransport` holding key material, region, and optional session token, with an injectable `session` seam.
- [x] 4. Implement `signer_for(service)` scoping a `SigV4Signer` to the service and its signing region.
- [x] 5. Implement `send()` signing method, URL, params, headers, and body, with a 60-second default timeout and per-request override.
- [x] 6. Implement `endpoint_for()` / `signing_region_for()`, special-casing Route53 as a global endpoint signed against `us-east-1`.
- [x] 7. Implement `raise_for_status()` / `_error_of()` covering the XML `<Error><Code>` form, the JSON `__type` form with namespace stripping, and the bodiless fallback to HTTP status.

## Query Codec

- [x] 8. Implement `flatten_params()` with one-indexed lists, dotted nesting, lowercase booleans, and `None` dropping.
- [x] 9. Implement `strip_namespace()`, `_upper_camel()`, `_pluralize_preserving()`.
- [x] 10. Implement `modeled_name()` with the de-`Set` rule plus the 22-entry `NAME_OVERRIDES` table for irregular cases.
- [x] 11. Implement `is_collection_tag()` so empty collection elements decode as `[]`, not `""`.
- [x] 12. Implement `_is_list_container()` covering the Query `item` form and the REST-XML plural-container form, rejecting single-field structures.
- [x] 13. Implement `decode_element()` / `decode_response()` with boolean coercion and accumulation of unwrapped repeated elements.

## Service Clients

- [x] 14. Implement `Ec2Client` with `call()` and `__getattr__` action derivation, pinned to API version `2016-11-15`.
- [x] 15. Implement `S3Client`: `head_bucket`, `create_bucket`, `delete_bucket`, `list_buckets`, `get_bucket_tagging`, `put_bucket_tagging`, with XML escaping and the `us-east-1` `LocationConstraint` omission.
- [x] 16. Implement `Route53Client.list_hosted_zones` and `change_resource_record_sets`, stripping the `/hostedzone/` prefix and rendering the change batch.
- [x] 17. Implement `JsonServiceClient` with `x-amz-target` dispatch, plus `SsmClient` and `FsxClient` carrying their target prefixes.
- [x] 18. Implement `build_clients()` returning all five clients over one transport, keyed by boto3 service name.
- [x] 19. Implement `ClientError` preserving botocore's `.response` envelope alongside flat `.code`, `.status`, `.body`.

## Tests

- [x] 20. Implement `FakeSession` / `FakeResponse` and drive every client through the `session=` seam.
- [x] 21. Signing tests: `AWS4-HMAC-SHA256` present, credential scope correct per service, Route53 globality.
- [x] 22. EC2 tests: action derivation, one-indexed filter flattening, modelled response shape, botocore error envelope.
- [x] 23. S3 tests: 404-versus-403 on `head_bucket`, `CreateBucketConfiguration` omission and inclusion, `list_buckets` name extraction, tagging round trip and escaping.
- [x] 24. Route53 tests: zone-id stripping, change-batch rendering.
- [x] 25. JSON-service tests: target headers per service, `None` dropping, `__type` namespace stripping.
- [x] 26. Codec tests over captured shapes (VPCs, reservations, security groups, route tables, gateways, volumes) plus empty-collection and unwrapped-repetition cases.
- [x] 27. Migrate the suite from pytest to testbase (`testbase.raises`, `testbase.parametrize`).

## Open Items

- [ ] 28. No method accepts an `aspects` parameter, which the repository coding standard requires of every behaviour-bearing method. Retry, backoff, and timeout policy are not caller-controlled beyond the transport timeout.
- [ ] 29. `AwsTransport` accepts raw `access_key` / `secret_key` strings rather than a typed `AwsAccessKeyCredential`. Unwrapping happens one layer up in `AwsBoto3SessionFactory`, leaving raw key material on this package's public surface.
- [ ] 30. No pagination. `NextToken` / `Marker` continuation is not followed by any `describe_*` or `list_*` call, so a caller past the first page must loop by hand.
- [ ] 31. No retry or throttling handling. `ClientError` carries the code so a caller can classify a throttle, but nothing here acts on it.
- [ ] 32. No property-based tests. `ccai.testbase.properties` is available; `modeled_name` mapping and the `flatten_params` round trip are the natural candidates, since a mis-mapped collection fails silently.
- [ ] 33. `decode_element` is imported in `serviceclients.py` but never used there; drop the import.
- [ ] 34. No live-API smoke tier. Every test runs against `FakeSession`.
