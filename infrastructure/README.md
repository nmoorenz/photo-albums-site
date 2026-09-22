# infrastructure

Terraform for the whole stack, all in one region.

`aws_region` defaults to `ap-southeast-2`. The region must support Lambda
function URLs. `ap-southeast-6` does not.

Run every terraform command through `scripts/tf.py`, from the repo root. It
passes its arguments straight through, adds `-chdir=infrastructure`, and
feeds terraform the deployment's own names from `.env` as `TF_VAR_*`.

`bucket_name`, `domain_name` and `cognito_domain_prefix` have no defaults;
an incomplete `.env` stops the run. Everything else defaults in
`variables.tf`.

There is no `terraform.tfvars`, and `tf.py` will not run while one exists.
Set values in `.env`, or change a default in `variables.tf`.

`tf.py` builds any missing Lambda bundle before calling terraform.

## What it builds

One S3 bucket and one CloudFront distribution serve everything. The Cognito
cookies are first-party.

| behaviour | origin | notes |
| --- | --- | --- |
| default | S3 `/site` | the static site |
| `/photos/*` | S3 | signed cookies required |
| `/auth/*` | auth-callback Lambda | login and logout |
| `/api/*` | comments-api Lambda | no caching, Cookie forwarded |

A 403 from `/photos/*` is rewritten to `/login.html`.

| file | contents |
| --- | --- |
| `providers.tf` | AWS provider, plus a us-east-1 alias for ACM |
| `variables.tf` | profile, region, bucket, domain, Cognito domain prefix |
| `s3.tf` | bucket, versioning, OAC, bucket policy, manifest bootstrap |
| `acm.tf` | certificate and its DNS validation |
| `cognito.tf` | user pool, client, hosted UI domain, `admin` group |
| `cloudfront_keys.tf` | cookie-signing key pair, SSM SecureStrings |
| `cloudfront.tf` | the distribution and its four behaviours |
| `lambda.tf` | both functions, their roles, and their function URLs |
| `outputs.tf` | domain, distribution id, ACM records, Cognito ids |
| `lambda/` | the two Python 3.12 handlers and their requirements |

`build/` and `dist/` are produced by `scripts/build_lambdas.py` and
gitignored.

## Access model

Cognito user pool with the Hosted UI. Self sign-up is disabled: you create
each account, Cognito emails a one-time password, and the person sets their
own at first sign-in. Password reset is self-service. Set each user's `name`
attribute -- it is what appears on their comments.

One group, `admin`, can delete anyone's comment. Everyone else signed in can
read every album and post and delete their own comments.

`auth-callback` exchanges the Cognito code for tokens, verifies the ID token,
issues CloudFront signed cookies for `/photos/*`, and sets an `id_token`
cookie scoped to `/api/*`. `/auth/logout` clears all of them.

Both function URLs are `authorization_type = NONE` and gated instead by an
`X-Origin-Verify` header that only CloudFront sends.

## The Lambdas

Python 3.12. `auth-callback` uses PyJWT for token verification and
`cryptography` to sign the CloudFront cookie policy. `comments-api` uses
PyJWT and boto3 (pinned `>=1.35` for `PutObject`'s If-Match).

`python scripts/build_lambdas.py` assembles each function into
`build/<name>/` -- handler plus its requirements, installed for Lambda's
platform rather than the machine doing the build -- and Terraform zips that
directory into `dist/`. Re-run it after changing a handler or a
`requirements.txt`.

## First deploy

```
cp env.example .env                                 # then edit it
python scripts/tf.py init
python scripts/tf.py plan                           # check before creating anything
python scripts/tf.py cert                           # stage one: the certificate
                                                    # add the CNAME it prints
python scripts/tf.py plan                           # once the CNAME resolves
python scripts/tf.py apply                          # stage two: everything else
python scripts/tf.py output cloudfront_domain_name  # point your domain here
```

`tf.py cert` is stage one: it applies the certificate alone and prints its
validation record. Add that record at the registrar, wait for it to resolve,
then run the second apply.

### The two DNS records

Both go in your domain's DNS panel, wherever the zone is hosted -- the
registrar, or whatever nameservers it points at.

| when | type | host | value |
| --- | --- | --- | --- |
| after `tf.py cert` | CNAME | the name from `acm_validation_records` | the value from the same output |
| after the full apply | CNAME | your subdomain, e.g. `albums` | the `cloudfront_domain_name` output |

ACM prints the validation name fully qualified, ending in a dot:

```
_a1b2c3d4e5.albums.example.com.
```

Most panels take only the part in front of the zone and append the rest:
enter `_a1b2c3d4e5.albums`. Drop the trailing dot unless the panel expects
one. Paste the value as-is.

Two checks before the second apply -- DNS first, then ACM:

```powershell
Resolve-DnsName _a1b2c3d4e5.albums.example.com -Type CNAME
aws acm list-certificates --region us-east-1 --profile $env:AWS_PROFILE `
  --query "CertificateSummaryList[?DomainName=='$env:DOMAIN_NAME'].Status"
```

The record resolves within minutes of adding it; ACM moves from
`PENDING_VALIDATION` to `ISSUED` within about another 30, and the second
apply waits on that.

Then:

1. `python scripts/deploy_site.py`
2. Create Cognito users with `name` and `email`, and add yourself to the
   `admin` group.
3. Scan and sync -- see `scripts/README.md`.

## Later applies

`python scripts/tf.py plan`, then `python scripts/tf.py apply`. Re-run
`build_lambdas.py` first if a handler changed; the zip's hash is what tells
Terraform to redeploy the function.
