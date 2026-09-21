# infrastructure

Terraform for the whole stack.

Run it through `scripts/tf.py`, which passes everything through to terraform
with `-chdir=infrastructure` and feeds it the deployment's own names from
`.env` as `TF_VAR_*`:

```
python scripts/tf.py init
python scripts/tf.py plan
python scripts/tf.py apply
python scripts/tf.py output cloudfront_domain_name
```

`bucket_name`, `domain_name` and `cognito_domain_prefix` have no defaults, so
a missing or incomplete `.env` fails before anything is created.
`terraform.tfvars` is committed and holds only `project_tag`.

## What it builds

One S3 bucket and one CloudFront distribution serve everything, so the
Cognito cookies stay first-party:

| behaviour | origin | notes |
| --- | --- | --- |
| default | S3 `/site` | the static site |
| `/photos/*` | S3 | signed cookies required |
| `/auth/*` | auth-callback Lambda | login and logout |
| `/api/*` | comments-api Lambda | no caching, Cookie forwarded |

A 403 from `/photos/*` is rewritten to `/login.html`, so a viewer with no
valid cookies lands on the login page rather than an AWS error.

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
| `terraform.tfvars` | committed; project_tag only |
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
python scripts/build_lambdas.py
python scripts/tf.py init
python scripts/tf.py apply -target=aws_acm_certificate.albums
python scripts/tf.py output acm_validation_records  # add this CNAME at the registrar
python scripts/tf.py apply                          # once it resolves
python scripts/tf.py output cloudfront_domain_name  # point your domain here
```

The certificate is created on its own first because `terraform output` cannot
print the validation record until the certificate exists, and the full apply
blocks waiting for that record.

Then:

1. `scripts/deploy_site.sh`
2. Create Cognito users with `name` and `email`, and add yourself to the
   `admin` group.
3. Scan and sync -- see `scripts/README.md`.

## Later applies

`python scripts/tf.py apply` on its own. Re-run `build_lambdas.py` first if a
handler changed; the zip's hash is what tells Terraform to redeploy the
function.
