# Deployment

The target is Cloud Run, scaled to zero, so an idle deployment costs nothing. Nothing
here is required to use the harness. A laptop is a perfectly good deployment for a
small organisation.

Read [security.md](security.md) before exposing an instance to anyone.

## What you need

- A Google Cloud project with billing enabled
- `gcloud`, `terraform`, and `docker` installed
- Vertex AI, Firestore, Cloud Storage, and Secret Manager enabled on the project

```bash
gcloud services enable \
  run.googleapis.com aiplatform.googleapis.com firestore.googleapis.com \
  storage.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com
```

Firestore needs a database in native mode, created once:

```bash
gcloud firestore databases create --location=us-central1
```

## Build and push the image

```bash
PROJECT=your-project-id
REGION=us-central1
IMAGE="$REGION-docker.pkg.dev/$PROJECT/harness/nonprofit-agent-harness:latest"

gcloud artifacts repositories create harness \
  --repository-format=docker --location=$REGION

gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker build -t "$IMAGE" -f deployment/Dockerfile .
docker push "$IMAGE"
```

The Dockerfile copies `examples/` into the image. Replace that with your own agent
package, and set `HARNESS_AGENTS` to match.

## Apply the infrastructure

```bash
cd deployment/terraform
terraform init
terraform apply \
  -var="project_id=$PROJECT" \
  -var="region=$REGION" \
  -var="image=$IMAGE" \
  -var="agents=mypackage.agents:BoardBriefAgent" \
  -var="max_cost_usd=1.00" \
  -var="admin_emails=you@example.org"
```

This creates a service account with the narrow roles the harness needs, a documents
bucket with a one year lifecycle rule, a Secret Manager entry for the session signing
secret, and the Cloud Run service itself with `min_instance_count = 0`.

## Set the session secret

Terraform creates the secret container. Put a value in it yourself, so the secret never
passes through a state file:

```bash
openssl rand -base64 48 | gcloud secrets versions add nonprofit-agent-harness-jwt-secret --data-file=-
```

## Turn authentication on

The default is off, which is right for a laptop and wrong for anything with a public
URL. Set both:

```
HARNESS_AUTH_REQUIRED=true
HARNESS_GOOGLE_CLIENT_ID=<your OAuth client id>
```

Create the OAuth client in the Google Cloud console under APIs and Services,
Credentials, as a Web application, with your frontend origin as an authorised origin.

## Check it

```bash
URL=$(terraform output -raw service_url)
curl -s "$URL/healthz"
```

Then confirm the settings that actually took effect, as an admin:

```bash
curl -s "$URL/v1/admin/config" -H "Authorization: Bearer <session token>"
```

Read the `warnings` array in that response. It lists the configuration problems that
would bite in production. An empty array is what you want before you tell anyone the
URL.

## Known gaps to plan around

**Runs execute in-process.** A run is started with FastAPI background tasks. If the
instance is recycled mid-run, the replacement fails that run at startup once it has sat
in `running` longer than `HARNESS_RUN_TIMEOUT_SECONDS`, so a poller gets an answer
instead of waiting forever. Set that threshold above the longest run you expect: a run
genuinely in progress on another instance is indistinguishable from an abandoned one.
For high volumes, move execution to a queue.

**Firestore indexes are created by Terraform.** Listing runs filters on one field and
orders by another, which needs a composite index. The definitions are in `main.tf`. If
you provision Firestore by hand instead, the first listing raises a `StorageError`
carrying the link Firestore supplies to create the index.

**Per-run ceilings are not a total.** See [security.md](security.md).

## Costs

Cloud Run scales to zero, so the service itself costs nothing while idle. Firestore and
Cloud Storage have free tiers that a small deployment stays inside comfortably.

Model calls are the real cost, and they are yours. The harness never routes work
through any third party, and it has no telemetry.
