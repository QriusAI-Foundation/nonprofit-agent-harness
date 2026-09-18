terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" { type = string }
variable "region" { default = "us-central1" }
variable "service_name" { default = "nonprofit-agent-harness" }
variable "image" { type = string }
variable "agents" { default = "examples.summarizer:SummarizerAgent" }
variable "max_cost_usd" { default = "1.00" }
variable "admin_emails" { default = "" }

resource "google_storage_bucket" "documents" {
  name                        = "${var.project_id}-harness-documents"
  location                    = var.region
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition { age = 365 }
    action { type = "Delete" }
  }
}

# Filtering on one field and ordering by another needs a composite index, which
# Firestore will not create on its own. Without these, listing runs fails at runtime
# with FAILED_PRECONDITION on the first real deployment.
resource "google_firestore_index" "runs_by_org" {
  project    = var.project_id
  collection = "harness_runs"

  fields {
    field_path = "org_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "runs_by_org_and_status" {
  project    = var.project_id
  collection = "harness_runs"

  fields {
    field_path = "org_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "blobs_by_org" {
  project    = var.project_id
  collection = "harness_blobs"

  fields {
    field_path = "org_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "DESCENDING"
  }
}

resource "google_service_account" "harness" {
  account_id   = "${var.service_name}-sa"
  display_name = "Nonprofit Agent Harness"
}

resource "google_project_iam_member" "firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.harness.email}"
}

resource "google_project_iam_member" "vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.harness.email}"
}

resource "google_storage_bucket_iam_member" "documents" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.harness.email}"
}

resource "google_secret_manager_secret" "jwt" {
  secret_id = "${var.service_name}-jwt-secret"
  replication { auto {} }
}

resource "google_secret_manager_secret_iam_member" "jwt" {
  secret_id = google_secret_manager_secret.jwt.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.harness.email}"
}

resource "google_cloud_run_v2_service" "harness" {
  name     = var.service_name
  location = var.region

  template {
    service_account = google_service_account.harness.email

    # Scale to zero: an idle deployment should cost nothing.
    scaling {
      min_instance_count = 0
      max_instance_count = 4
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "HARNESS_STORAGE"
        value = "gcp"
      }
      env {
        name  = "HARNESS_PROVIDER"
        value = "google"
      }
      env {
        name  = "HARNESS_DOCUMENTS_BUCKET"
        value = google_storage_bucket.documents.name
      }
      env {
        name  = "HARNESS_AGENTS"
        value = var.agents
      }
      env {
        name  = "HARNESS_MAX_COST_USD"
        value = var.max_cost_usd
      }
      env {
        name  = "HARNESS_ADMIN_EMAILS"
        value = var.admin_emails
      }
      env {
        name = "HARNESS_JWT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

output "service_url" {
  value = google_cloud_run_v2_service.harness.uri
}

output "documents_bucket" {
  value = google_storage_bucket.documents.name
}
