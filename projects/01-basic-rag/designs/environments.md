# Design: environments

Designed 2026-09-18, in a `grill-me` session, after a read-only audit of the
live AWS account the same day.

## Problem

Project 01 runs on AWS. One `image`, two ECS services, a Qdrant task holding the
vectors on EFS, deployed by GitHub Actions on every push to `main`. It works —
the audit found a healthy task and a `POST /query` that returned 200.

What it does not have is **a name for what it is**. There is no `dev` in any
resource name, no `prod`, no tag, no workflow variable. `basic-rag-api-service`
is just *the* service. And yet a merge to `main` builds an `image` and rolls it
straight out to the only copy that exists, with no gate, no approval, and no
check that the new task can actually answer a question.

So the single environment is doing two incompatible jobs at once. It is the
place where work is tried, and it is the place where work is shipped. Those want
opposite things: one wants to be broken freely, the other wants to be stable.
Nothing in the account records which job is meant to be winning.

**This session set out to design DEV, STAGING and PROD, and concluded that this
project should build one environment, not three.** That conclusion is the
design. The reasoning is below, and so is the shape the other two would take,
because knowing what you are *not* building is worth writing down.

## Scope

**In.** A definition of what DEV means here, the naming and configuration
convention that makes a second environment possible later, and the documented
shape STAGING and PROD would take if they are ever built.

**Out**, deliberately.

- **Creating STAGING or PROD.** No second ECS service, no second Qdrant, no
  second EFS filesystem, no `ALB`, no extra IAM roles. This is the decision, not
  an omission — see **One environment, and it is DEV**.
- **Terraform, or any IaC.** Argued for below as the next real step, and
  deliberately not started here. A design document that cannot be read without
  knowing Terraform is a worse document.
- **Any change to AWS or to `.github/workflows/ci.yml`.** Nothing in this file
  has been applied. It describes intent.
- **A reproducible ingestion path.** It is the largest open question in the
  project and it needs its own session. Recorded here as a dependency, not
  solved here — see **Stateful data**.
- **A domain name, HTTPS, and the `ALB`.** They belong to PROD, and PROD is not
  being built. The `ALB` returns as a *learning* step in its own right, which is
  a different thing from an environment — see **The remaining roadmap**.
- **Any change to Python.** Not one line of `api.py`, `asgi.py` or `src/`.

## Design

### One environment, and it is DEV

The audit priced the alternative. Three environments running continuously, at
us-east-1 ARM64 Fargate rates:

```
per environment          api task   1 vCPU / 3 GB   $31.43
                      qdrant task   0.5 vCPU / 1 GB $14.42
                                                    ───────
                                                    $45.85 / month

DEV + STAGING + PROD                               $137.55
shared ALB (base + minimal LCU)                    ~$17.00
Cloud Map private zones, Route 53, EFS, ECR, logs   ~$3.00
                                                   ────────
                                                   ~$157 / month
```

Roughly **$1,900 a year**, for a project with one user, whose purpose is to
learn AWS rather than to serve anyone.

The thing that decided it: **almost none of that money buys a lesson.** A second
ECS service teaches what the first one taught. A second Qdrant teaches what the
first one taught. What is actually unlearned in this project — health checks,
`ALB`s and TLS, IaC, task roles, private networking, alarms, reproducible
ingestion — is unlearned *in DEV too*, and every one of them can be built there
for a fraction of the cost.

**So DEV is the only environment, and it absorbs the learning.** STAGING and
PROD are described below as a target shape, not as work.

**The cost, named and accepted.** There is no environment in which a change has
been proven before it reaches the one that matters, because there is only one
environment and it is the one that matters. That is a real property of this
design and it is acceptable here for exactly one reason: **nobody is served by
this deployment.** The moment somebody is — the moment a link goes to an
interviewer — that reasoning expires, and PROD stops being optional. This is
recorded in **When this design expires**.

### DEV scales to zero

DEV runs when work is happening and is scaled to `desiredCount=0` otherwise. At
a realistic four hours a day, twenty-two days a month:

```
88 hours × $0.06281/hour   ≈  $5.53
EFS, ECR, SSM, logs, Cloud Map  ≈  $1.50
                              ────────
                                ≈  $7 / month
```

Against $45.85 for the same environment left running. **The saving is larger
than every other cost decision in this document combined**, which is why it
comes before any of them.

Two consequences, both of which will otherwise be discovered the hard way:

**Start Qdrant before the API.** When the Qdrant task stops, ECS deregisters its
Cloud Map A record and `qdrant.basic-rag.local` stops resolving. The API does
not care at startup — `asgi.py` opens no connection at import, and `retrieval`
opens the `vector_store` per request — so the task goes healthy and then fails
every query. That is this project's established failure signature wearing a new
hat: the README already warns that an empty collection answers **200 OK with
plausible English**, and an absent Qdrant lands in the same place.

**Scaling Qdrant to zero does not lose the vectors.** The EFS filesystem exists
independently of the task that mounts it. "Scale the database to zero" sounds
alarming and here it genuinely is not — the `chunk`s are on `fs-07941fd9547a1fee7`
whether or not anything is running.

### What DEV, STAGING and PROD would mean here

Not the generic definitions. These are the ones that fit this project, arrived
at by asking what each environment would *catch* that the others did not.

**DEV — where the application is tested.** Broken freely. Reached directly on
the task's public IP, because it has no audience to present a stable URL to.
Holds a corpus that may be scratch data. **This exists.**

**STAGING — where the deployment path is rehearsed.** Its value is being
PROD-*shaped*, not holding different data: an `ALB` in front, TLS terminated, a
target group with a health check, registered and deregistered the same way
PROD's would be. It exists so that promoting to PROD is a move already made
once. **This does not exist and is not being built.**

Note what STAGING is explicitly *not* for here: **it is not where retrieval
quality is judged.** That belongs to LangSmith, measured against
`01-basic-rag-benchmark`, and it is measured on an `evaluation_run` rather than
by looking at a deployed environment. Removing that job from STAGING is what
lets it skip a separate corpus entirely.

**PROD — where someone else is served.** A stable public HTTPS endpoint on a
dedicated domain, always-on, because a demo link that cold-starts for two
minutes when a recruiter clicks it is worse than no demo link. **This does not
exist and is not being built.**

### The promotion model, which survives having one environment

Build the `image` **once**, tag it with the commit SHA, push it to ECR, and
deploy that exact artifact. With one environment this is already what
`ci.yml` does. With three it would be the same `image` moving DEV → STAGING →
PROD, promoted rather than rebuilt.

```
  push to main
       │
       ▼
   ┌────────┐   build once    ┌─────────────────────────┐
   │   CI   │ ──────────────► │ ECR  basic-rag-api:<sha> │
   └────────┘                 └─────────────────────────┘
                                   │        │        │
                        deploy ────┘        │        │
                          ▼                 │        │
                       ┌─────┐              │        │
                       │ DEV │              │        │   ← today: this arrow only
                       └─────┘              │        │
                                    promote ┘        │
                                      ▼              │
                                 ┌─────────┐         │
                                 │ STAGING │         │   ← future
                                 └─────────┘         │
                                            promote ─┘
                                              ▼
                                           ┌──────┐
                                           │ PROD │      ← future
                                           └──────┘
```

**Why the `image` must never be rebuilt per environment.** A rebuilt `image` is
a different artifact. `uv sync --frozen` pins the Python dependencies, but
nothing pins the base layer: `python:3.12-slim` is a moving tag, and a rebuild
three days later can pull a different Debian with different system libraries. So
a STAGING that was rebuilt rather than promoted is not evidence about PROD — it
is evidence about a build that no longer exists. The entire value of a rehearsal
is that the thing rehearsed is the thing shipped.

The same argument is already written into `ci.yml`, which tags by commit SHA and
never `latest`, on the grounds that "the tag a task definition points at must
mean exactly one set of bytes, forever, or a rollback cannot say what it is
rolling back to." Promotion is that argument applied across environments instead
of across time.

**This is the single most important thing to keep intact** while there is one
environment, because it is what makes a second one cheap to add later. Nothing
in this design breaks it.

### What would be shared, and what would be separate

Decided as though three environments existed, because the point of the table is
to make the second one cheap — and because getting it wrong is what makes
environments expensive to add.

| Resource | Shared / separate | Why |
|---|---|---|
| AWS account | **Shared** | Account separation is the real isolation boundary and it is real work: Organizations, SSO, cross-account roles, per-account billing. Correct at a company; pure overhead for one person. Rejected on cost of understanding, not on money. |
| Region | **Shared** | us-east-1 for all. Multi-region solves latency and disaster recovery, neither of which this project has. |
| VPC | **Shared** | The default VPC. A VPC is a network boundary, and these environments do not need to be isolated from each other at the network layer — they need to be isolated at the *data* layer, which is EFS and Qdrant. |
| Subnets | **Shared** | All six default public subnets. |
| ECS cluster | **Shared** | A cluster is a logical grouping with no isolation boundary and no cost. Cluster-per-environment is a common instinct and buys nothing here; the service name already carries the environment. |
| **ECS services** | **Separate** | This is the unit of "a running copy". One per environment per component. |
| **Task definition families** | **Separate** | Each environment's task definition differs in its `QDRANT_URL`, its secret ARNs and its log group. Sharing a family would mean revisions from different environments interleaving in one numbering, so `:7` could be DEV and `:8` PROD — which makes rollback unreadable. |
| ECR repositories | **Shared** | **Forced by the promotion model.** The same `image` moves through all three, so it must live in one repository under one tag. A per-environment repository would require a copy, and a copy is a rebuild by another name. |
| Docker images | **Shared** | One `image`, one SHA tag, promoted. See above. |
| **Qdrant** | **Separate** | One task per environment. See **Stateful data**. |
| **EFS** | **Separate** | One filesystem per environment. See **Stateful data**. |
| Cloud Map namespace | **Separate** | `basic-rag-<env>.local`. A private DNS namespace is a Route 53 private hosted zone at $0.50/month, so this is cheap, and it means the service name stays `qdrant` in every environment — only the namespace changes. The alternative, one namespace with `qdrant-dev`, `qdrant-staging`, puts the environment inside the hostname where a typo resolves successfully to the wrong environment. |
| **SSM Parameter Store** | **Separate** | By path: `/basic-rag/<env>/*`. See **Configuration and secrets**. |
| **Security groups** | **Separate** | They reference each other by group ID — the API's SG is what the Qdrant SG admits. Sharing one across environments would make DEV's API able to reach PROD's Qdrant, which is precisely the isolation the data separation exists to provide. |
| **CloudWatch log groups** | **Separate** | `/ecs/basic-rag-<env>-api`. Interleaved logs from two environments in one group is a debugging tax paid every time. |
| IAM task execution role | **Shared**, with a widened policy | One `ecsTaskExecutionRole`, whose SSM policy grants the `/basic-rag/*` path prefix rather than one parameter ARN. Splitting it buys nothing: the role only pulls images and reads secrets, and the secrets are already separated by path. |
| **IAM task role** | **Separate**, when one exists | There is no task role today. When the containers need an AWS identity of their own, it is per-environment, because that is the identity that would touch environment-specific data. |
| IAM deploy role | **Shared today** | One `github-actions-basic-rag-deploy`. See the note below. |
| GitHub OIDC provider | **Shared** | One per AWS account is all AWS permits. |

**The deploy role, and what changed.** An earlier turn of this session settled on
*three* deploy roles, one per environment, each trusted on the OIDC
`environment:<env>` claim rather than on the branch — so that AWS itself
enforces a GitHub approval gate instead of trusting the workflow YAML to do it.
That reasoning is sound and it is recorded here because it is worth keeping. It
is also **moot while there is one environment**, since there is no gate to
enforce. One role stays. The split belongs with STAGING, and this paragraph
exists so the next session does not rediscover it.

### Where the environment boundary falls: naming

`basic-rag-<env>-<component>` for everything ECS, `/basic-rag/<env>/*` for
configuration, `/ecs/basic-rag-<env>-<component>` for logs.

**DEV does not follow this convention today, and will not until Terraform
lands.** That is a decision rather than an oversight, and it is the subject of
**The current deployment is DEV** below.

### Configuration and secrets

Three levels, and the distinction matters more than it looks:

**Baked into the `image`** — nothing environment-specific, ever. `.env` is
excluded by `.dockerignore` and is never copied into a `layer`, because a file
in a `layer` survives its own deletion and a secret baked at build time cannot
be rotated without a rebuild. This is settled in `designs/containerisation.md`
and nothing here changes it.

**In the task definition as `environment`** — non-secret values that differ per
environment. Today that is `QDRANT_URL`. It is per-environment by nature: it
names that environment's own Qdrant.

**In SSM as `secrets`** — anything that must not appear in a task definition a
`describe-task-definition` call will print. Today that is `OPENROUTER_API_KEY`,
which the CI workflow reads and re-registers on every deploy, in the clear, as a
`valueFrom` ARN. That is the correct shape: the ARN travels, the value does not.

**Why separate paths per environment.** `/basic-rag/dev/*` and
`/basic-rag/prod/*` rather than one `/basic-rag/*`:

- **An IAM policy can express a path prefix.** `/basic-rag/dev/*` is one
  wildcard, so a per-environment task role gets least privilege for free. A flat
  namespace forces per-parameter ARNs, and the list falls behind.
- **Separate keys can be rotated and revoked separately.** A leaked DEV
  OpenRouter key should not require rotating the key PROD is serving with.
- **It makes the environment visible at the point of the mistake.** Writing to
  `/basic-rag/prod/openrouter-api-key` announces what you are touching.

**The hazard already present, and it will get worse with a second environment.**
`config.py` derives `collection_name` from `EMBEDDING_MODEL`, `CHUNK_SIZE` and
`CHUNK_OVERLAP`. **None of the three is set in the live task definition**, so
all three fall back to the defaults, giving `bge-m3-1000-200`. Set any one of
them differently in one environment and that environment answers **200 OK from
an empty collection** — the exact failure `designs/containerisation.md`
identified when it chose to pass the whole of `.env` to the `api` Compose
service rather than a hand-written list. The ECS task definition took the
opposite approach, a hand-written list of one variable, and did not carry the
mitigation across. Making the three settings explicit in the task definition is
in **Known gaps**.

### Stateful data

**Every environment gets its own Qdrant task and its own EFS filesystem.** This
is the one place in the table where sharing is cheapest and most wrong.

**Why not share one Qdrant.** The tempting version is one Qdrant task serving
all environments, separated by collection — the names are already derived from
settings, so `bge-m3-1000-200` could sit beside a DEV collection at no cost,
saving ~$14/month per environment. Rejected, for three reasons:

- **`index()` deletes.** Ingestion is not append-only: `cleanup="scoped_full"`
  removes `chunk`s whose source file is gone. A DEV ingest pointed at the wrong
  collection does not add junk, it **deletes PROD's `chunk`s**, and the symptom
  is a 200 with an empty `chunks` array rather than an error.
- **One process, one failure.** A Qdrant that dies takes every environment with
  it, which means DEV can take PROD down — the opposite of what environments are
  for.
- **The blast radius is invisible.** The two collections differ by a name
  derived from settings nobody sets explicitly. There is no wall, only a
  convention, and the convention is already the weakest link in the system.

Sharing a *filesystem* between two Qdrant tasks is worse still and is not on the
table: Qdrant assumes a single writer on its storage directory, which is why the
existing service runs at `minimumHealthyPercent=0` / `maximumPercent=100` —
stop-then-start, so two tasks never hold the same EFS at once. That choice is
correct and it is also why **every Qdrant deploy is a full outage**, which is
acceptable for DEV and would need revisiting for PROD.

### Ingestion: two stores, and only one of them is the vector store

A distinction worth stating plainly, because the two are easy to confuse and
only one of them survives into AWS.

**Qdrant is the `vector_store`.** It holds the `chunk`s and their vectors. It is
the thing retrieval queries, and it is the thing that must exist in every
environment.

**Postgres was never a vector store.** It backs LangChain's `SQLRecordManager`,
which holds *indexing state* only: one row per `chunk` key, recording a content
hash and the source file it came from, so that a re-run of `ingest` can tell an
unchanged file from an edited one and skip the work. It stores no text and no
vectors. Losing it costs re-embedding, not data.

The audit found **no RDS instance**, so the `record_manager` exists only in
`docker-compose.yml` on the development machine. That is the fact that forces
the decision below.

### Decided: AWS ingestion drops the `record_manager` and rebuilds in full

**Option A.** The AWS ingestion path does not use `SQLRecordManager`. It reads
the complete source corpus and rebuilds the Qdrant collection, every time.

Why, for this project:

- **No Postgres to run in AWS.** An RDS instance, or a container with its own
  EFS, is roughly $15/month and a second stateful component to operate — for
  state whose only job is to avoid re-embedding 126 `chunk`s.
- **The corpus is small.** 126 `chunk`s across four files. A full rebuild is
  seconds of work and cents of embedding cost.
- **A full rebuild is reproducible by construction.** Incremental indexing is
  correct only if the state and the store agree; a rebuild has no state to
  disagree with. For a path whose entire purpose is being repeatable, that is
  the property worth buying.
- **Adding documents still works.** Ingestion processes the whole corpus and
  rebuilds the collection, so a new file is picked up by the same run.

**The local path is unchanged.** `docker-compose.yml`, Postgres, pgAdmin and the
`record_manager` stay exactly as they are for development, where incremental
indexing genuinely saves time on repeated runs. **What is decided is only that
none of it is assumed to exist in AWS.**

**The cost, named and accepted:** every AWS ingest re-embeds the whole corpus.
At this size that is negligible; at a corpus large enough to matter, this
decision gets revisited.

**Intended future flow**, recorded as direction rather than design:

```
  S3 (source documents)
        │
        ▼
  one-off ECS task  ──►  load ──► split ──► embed ──► rebuild Qdrant collection
   (run-task, same cluster and subnets, reaches Qdrant over Cloud Map)
```

Running it inside the VPC is the point: it reaches Qdrant the same way the API
does, so no security-group hole and no laptop is involved. It costs nothing when
not running, which fits the scale-to-zero decision above.

**Not designed here.** What carries `main.py` into AWS — an extended `image`, a
second `image`, or something else — is unsettled, and so is how a rebuild
replaces a live collection without a window where the API answers from an empty
one. **That needs its own `grill-me` session**, and until it happens this remains
a documented intention rather than a plan.

### How the corpus actually got into DEV

Investigated 2026-09-18 from CloudTrail, CloudWatch and local state. Recorded
because "nobody knows" was the previous answer and it was blocking.

**Verified:**

- A rule on the Qdrant security group allowed `103.104.46.77/32 → tcp/6333`,
  described `"temporary: verification from my laptop"`, from
  `2026-09-16T10:22:06Z` until it was revoked at `2026-09-17T05:25:53Z`.
- EFS `StorageBytes` on `fs-07941fd9547a1fee7` went **30,720 → 1,789,952 bytes
  between `2026-09-17T04:00Z` and `05:00Z`**, and has been flat since. The hole
  was closed within the hour that followed.
- The local `record_manager` was **not** involved: its `bge-m3-1000-200`
  namespace carries `updated_at` of 2026-09-02 on all 126 keys, and `index()`
  refreshes that timestamp even for skipped `chunk`s
  (`langchain_core/indexing/api.py:527`).
- Local Qdrant holds 126 points in that collection, occupying 2,032 KB — close
  enough to EFS's 1.79 MB to be consistent with a faithful copy.

**Inferred, near-certain:** the corpus was pushed from the development machine
through that temporary rule, in that hour. DEV is very probably correctly
populated rather than silently empty.

**Still unresolved:** the exact mechanism. A plain `main.py ingest` re-pointed
at AWS *would have written nothing* — the `record_manager` already held all 126
hashes, so `index()` would have skipped every one while reporting success. So it
was either a Qdrant snapshot upload or an ingest against a cleared record
manager, and the evidence does not separate them.

**The trap this exposes, which Option A removes.** Re-ingesting into a fresh
Qdrant while reusing an existing `record_manager` writes **nothing** and prints
`added 0, skipped 126`. It looks like success. That is the same silent-success
failure mode this project keeps meeting, and dropping the `record_manager` from
the AWS path deletes the whole category.

**What remains blocked regardless:** the four source documents are third-party,
`data/*` is git-ignored, and `data/README.md` records that their origins were
never written down. A fresh clone gets hashes and a checker, not documents. **No
ingestion design can fix that** — it needs the provenance to be found.

### The future shape, drawn once

If STAGING and PROD are ever built, this is the shape agreed in this session.
Recorded so the reasoning is not lost, and so the decisions above can be checked
against the thing they are meant to enable.

```
                        Internet
                            │
                            ▼
        ┌───────────────────────────────────────────┐
        │   ONE shared ALB   (HTTPS :443, ACM cert) │
        │   host-based routing, two target groups   │
        └───────────────────────────────────────────┘
             │                              │
  staging.<domain>                    api.<domain>
             ▼                              ▼
     ┌───────────────┐              ┌───────────────┐
     │   STAGING     │              │     PROD      │
     │ api + qdrant  │              │ api + qdrant  │
     │ scale-to-zero │              │  always-on    │
     └───────────────┘              └───────────────┘

     ┌───────────────┐
     │      DEV      │   laptop ──► task public IP :8000
     │ api + qdrant  │   no ALB: nothing to rehearse, nobody to serve
     │ scale-to-zero │
     └───────────────┘
```

**One `ALB` shared by STAGING and PROD, and DEV left on direct access.** An
`ALB` in front of DEV would test nothing STAGING's does not, cost ~$16/month,
and force rework of the environment we most want to leave alone.

**The cost, named and accepted:** STAGING and PROD would share a failure domain.
A botched listener rule while working on STAGING can take PROD down. Worth $16 a
month at this scale, and a real trade rather than a free one.

**The honest limitation:** a shared `ALB` rehearses the target group, the health
check, and task registration — most of what breaks — but it does **not** rehearse
creating an `ALB`, because it already exists. The thing that rehearses resource
creation is applying one IaC module twice. That is an argument for Terraform,
not for a second load balancer.

## The current deployment is DEV

Nothing is recreated. DEV is the deployment that exists, relabelled.

The complication is that **AWS makes almost every name here immutable.** An ECS
service cannot be renamed; a task definition family cannot be renamed; nor can a
log group, an SSM parameter, a security group, an ECR repository, or a Cloud Map
namespace. Only the EFS `Name` tag is free to change, because it is only a tag.

So the convention above cannot be applied to DEV without deleting and
recreating most of it — which is the one thing this step is not for.

**The decision: DEV keeps its current names until Terraform lands, and adopts
the convention then.** Terraform will be creating or importing these resources
anyway, so the rename comes free with work already planned. The inconsistency is
a scheduled debt with a date attached, not a permanent quirk.

| Resource today | Becomes | When |
|---|---|---|
| `basic-rag-cluster` | unchanged — shared across environments by design | never |
| `basic-rag-api-service` | `basic-rag-dev-api-service` | Terraform |
| `basic-rag-qdrant-service` | `basic-rag-dev-qdrant-service` | Terraform |
| task family `basic-rag-api` | `basic-rag-dev-api` | Terraform |
| task family `basic-rag-qdrant` | `basic-rag-dev-qdrant` | Terraform |
| ECR `basic-rag-api` | unchanged — shared by design | never |
| ECR `qdrant` | unchanged — shared by design | never |
| `fs-07941fd9547a1fee7` | `Name` tag → `basic-rag-dev-qdrant-storage` | any time; it is a tag |
| namespace `basic-rag.local` | `basic-rag-dev.local` | Terraform |
| `/basic-rag/openrouter-api-key` | `/basic-rag/dev/openrouter-api-key` | can be done early; create, repoint, delete |
| `basic-rag-api-sg` | `basic-rag-dev-api-sg` | Terraform |
| `/ecs/basic-rag-api` | `/ecs/basic-rag-dev-api` | Terraform |
| `ecsTaskExecutionRole` | unchanged — shared by design | never |
| `github-actions-basic-rag-deploy` | unchanged while one environment exists | STAGING |

## Known gaps

From the audit, split by whether they block anything.

### Before DEV can be called reliable

These are the ones worth doing next, and none of them needs a second
environment.

- **No container health check.** The task definition declares no `healthCheck`,
  there is no target group, and `healthStatus` reads `UNKNOWN`. The deployment
  circuit breaker can therefore only catch a task that fails to *start* — a task
  that starts cleanly and cannot reach Qdrant is reported as a successful
  deploy. `/health` exists in the application and nothing calls it. **This is
  the most valuable single fix in this list**, because it converts the project's
  signature silent failure into a loud one.
- **No reproducible ingestion.** The strategy is decided — Option A, full
  rebuild, no `record_manager` — but nothing is built, and the source documents
  are still only on one machine. The blocker for everything downstream.
- **No IaC.** Covered below.
- **The three chunking settings are absent from the task definition**, so
  `collection_name` depends on defaults agreeing across two codebases forever.
  Make `EMBEDDING_MODEL`, `CHUNK_SIZE` and `CHUNK_OVERLAP` explicit.
- **Duplicate secret.** The OpenRouter key exists in both SSM and Secrets
  Manager; the task definition reads SSM, the Secrets Manager copy is orphaned
  from task definition revision `:1`, and `ecsTaskExecutionRole` still carries
  an inline policy granting access to it. Two places to rotate, one of which
  nothing reads. Delete the secret and the policy.
- **Stale security group rule.** `basic-rag-api-sg` admits port 8000 from
  `103.104.46.6/32`, a laptop IP that has already changed — the audit could not
  reach the running API. The task's public IP also changes on every deployment.
  Both are tolerable for DEV and both are friction every single session.
- **No log retention on `/ecs/basic-rag-api`.** Grows forever. `/ecs/basic-rag-qdrant`
  has 7 days; match it.
- **No backup of the vector data.** One EFS filesystem, no access point, and no
  backup plan was found. Given that the corpus cannot currently be regenerated,
  the only copy of the ingested `chunk`s is this filesystem.

### Later, and deliberately not now

- **`ALB` and HTTPS.** They belong to PROD. They also have real learning value
  on their own, which is addressed in the roadmap below rather than by building
  an environment to hold them.
- **A domain name.** No purchase yet. PROD cannot exist without one — ACM will
  not issue a public certificate for an `…elb.amazonaws.com` name.
- **Monitoring and alarms.** Container Insights is disabled; there are no
  alarms. Worth doing, cheap, and not blocking.
- **Autoscaling.** Meaningless at one user.
- **ECR hygiene.** `basic-rag-api` is `MUTABLE` with scan-on-push off and
  carries `latest`, `v1` and six untagged images with no lifecycle policy — while
  `qdrant` is `IMMUTABLE` with scanning on. The two were configured to opposite
  standards. Low urgency, trivial to fix, and `latest` contradicts `ci.yml`'s
  own stated principle.
- **No task role.** The containers have no AWS identity. Correct today: they
  call OpenRouter and Qdrant and nothing else. Needed when ingestion moves into
  AWS.
- **`enableExecuteCommand` is off**, so there is no way to shell into a task.
  Worth turning on for DEV; it needs a task role, so it waits for one.
- **Qdrant deploys are a full outage.** Correct for a single EFS writer,
  acceptable in DEV, would need revisiting for PROD.
- **Private subnets and VPC endpoints.** Everything runs in public subnets with
  public IPs, which is what lets tasks reach ECR and SSM without a NAT gateway.
  Moving to private subnets costs either ~$32/month for NAT or ~$7/month per
  endpoint. Good learning, real money, no urgency.
- **`ci.yml`'s comment disagrees with the live trust policy.** The comment
  documents the OIDC `sub` as `repo:jibz33on-lab/Agentic-Rag:ref:refs/heads/main`;
  the live policy uses GitHub's immutable owner/repo-ID form. Both work. One is
  wrong.

## The remaining roadmap

The point of dropping STAGING and PROD is to spend the same effort on things
that are actually unlearned. Ordered by what unblocks what:

1. **Container health check.** Cheapest, highest value, makes every later step
   verifiable.
2. **Reproducible ingestion.** Its own `grill-me` session. Unblocks backup,
   rebuild-from-scratch, and any second environment.
3. **Terraform for what exists.** Turns DEV into something that can be
   destroyed and recreated identically, which is the precondition for step 4.
4. **Stand up an `ALB` with HTTPS, learn it, tear it down.** This is the move
   that makes the roadmap affordable: with IaC in place, an `ALB` is an `apply`
   and a `destroy`. You learn target groups, listeners, TLS termination and
   health checks for a few dollars of uptime rather than $16/month forever —
   **and you do it without creating an environment to hold it.**
5. **Task role, then ECS Exec.** Least privilege, and the ability to get inside
   a running task.
6. **Alarms and log retention.** A few metric filters and an SNS topic.
7. **Private subnets and VPC endpoints**, if the budget allows it, as a
   deliberate exercise rather than a requirement.

**Steps 3 and 4 together are the argument of this whole document.** Ephemeral
infrastructure is only affordable if recreating it is reliable, and recreating it
is only reliable if it is code. That is a better reason for Terraform than
avoiding drift, and it is specific to a project with this budget.

## Infrastructure as code

**Not implemented here, and not a prerequisite for reading this document.**

Every resource in the audit was created by hand, and `ci.yml` deliberately reads
the live task definition rather than a copy in the repo — so the running
configuration exists only in AWS, where it cannot be diffed, reviewed, or
restored.

With one hand-built environment that is survivable. Two things make it stop
being survivable, and neither of them is a second environment:

- **Ephemeral infrastructure needs reproducible infrastructure.** The roadmap
  above depends on standing things up and tearing them down. That is only safe
  if `apply` produces the same result every time.
- **A second environment would be a hand-made copy of something with no
  written source.** Applying one module twice is the only thing that genuinely
  rehearses resource creation.

**Terraform is the likely tool**, for no more exciting reason than that it is
what the surrounding job market uses. CloudFormation and CDK would both work.
Choosing is its own session, and the choice does not change anything above.

A cheaper interim step, if Terraform slips: **commit both task definitions to
the repo** and have CI render from the committed file instead of calling
`describe-task-definition`. That alone makes the running configuration
reviewable, and it is perhaps an hour of work.

## When this design expires

Written down because the reasoning here is conditional and it will stop being
true.

**The moment this deployment has a user who is not you, PROD stops being
optional.** Not because the architecture changes, but because "there is no
environment where a change is proven before it reaches the one that matters"
goes from an accepted cost to an unacceptable one.

The specific trigger: **a link handed to someone else.** At that point PROD
needs a domain, an `ALB`, HTTPS and always-on compute, and the deploy role
splits so that AWS enforces an approval gate rather than trusting the workflow
YAML.

Everything in this document is arranged so that day is additive rather than a
rewrite: one ECR repository, SHA-tagged images, a naming convention already
agreed, and a promotion model that already works with one environment in it.

## Vocabulary

Two terms this design needs. Proposed here, **not yet added to
`DOMAIN_TERMS.md`** and not yet read back.

### `environment` — *proposed*

One complete running copy of the system — its ECS services, its Qdrant, its
EFS, its configuration and its secrets — identified by a name that appears in
every resource it owns. Today there is exactly one, DEV.

*Not:* a stage in a pipeline. DEV is a place that exists whether or not anything
is being deployed to it. *Not:* an `.env` file, which is host-side configuration
and shares only the word.

### `service` — *existing term, third meaning*

`DOMAIN_TERMS.md` already lists `service` under **Ambiguous words** with two
meanings: a Compose service, and "the thing the API is". AWS adds a third — an
**ECS service**, the thing that keeps *N* copies of a task definition running.

The three coincide nowhere and collide constantly: `basic-rag-api-service` is an
ECS service, `api` is a Compose service, and the API is a service in the loose
sense. **Say "ECS service" in full, every time**, and leave the bare word to
the Compose meaning as `DOMAIN_TERMS.md` already specifies.

## Decisions

1. **One environment, and it is DEV.** STAGING and PROD are documented as a
   target shape, not built. ~$150/month of compute buys no lesson this project
   has not already had.
2. **DEV scales to zero when not in use.** ~$7/month against ~$46. The largest
   single cost decision here.
3. **The current AWS deployment is DEV**, relabelled rather than recreated.
4. **DEV keeps its current resource names until Terraform lands**, because
   almost every name involved is immutable and renaming means recreating. The
   convention is `basic-rag-<env>-<component>` and DEV adopts it at that point.
5. **Build the `image` once, tag it with the commit SHA, promote that exact
   artifact.** True with one environment, and the reason a second one is cheap.
6. **One ECR repository, shared across all environments**, forced by (5).
7. **Stateful data is never shared.** Qdrant task and EFS filesystem per
   environment, because `index()` deletes and a mistake costs `chunk`s rather
   than adding junk.
8. **Configuration separates by SSM path**, `/basic-rag/<env>/*`, so an IAM
   policy can express least privilege as one wildcard.
9. **If STAGING and PROD are ever built:** one shared `ALB` across those two
   with host-based routing, DEV left on direct task access, and the deploy role
   split per environment with OIDC trust pinned to the `environment:` claim so
   AWS enforces the approval gate.
10. **AWS ingestion drops the `record_manager` and rebuilds the collection in
    full** — Option A, decided 2026-09-18. Postgres stays local, for
    development only. Qdrant remains the `vector_store` in every environment.
    The intended flow is S3 → one-off ECS task → chunk → embed → rebuild.
11. **The next work is the health check, then reproducible ingestion, then
    Terraform** — in that order.

## Open questions

Deliberately unresolved. None of these is decided by this document.

1. **Where do the AWS source documents live, and what carries `main.py` into
   AWS?** S3 is the intended source. Whether the ingest task uses an extended
   `image`, a second `image`, or something else is unsettled — and so is how a
   full rebuild replaces a live collection without a window where the API
   answers from an empty one. **Needs its own `grill-me` session.**
2. **Can the provenance of the four source documents be recovered?** They are
   third-party, git-ignored, and `data/README.md` records that their origins
   were never written down. Until they are, DEV is restorable only from this
   machine, and no ingestion design changes that. The alternative is replacing
   the corpus and re-cutting `01-basic-rag-benchmark`, whose verbatim quotes are
   tied to these exact `chunk`s.
3. **Is the AWS collection actually populated, and with what?** Inferred
   near-certain from the EFS size match, never directly observed — the security
   group blocks it and ECS Exec is disabled. Confirming needs a temporary rule
   or a task role, both of which are changes.
4. **Is 1 vCPU / 3 GB right for the API task?** Almost certainly oversized — the
   `image` carries no torch, and embeddings go out to OpenRouter over HTTP — but
   Container Insights is disabled and there are no per-task memory metrics.
   **Measure before changing.** Worth ~$17/month if it drops to 0.5 / 1 GB.
5. **Is the EFS filesystem backed up?** The audit found no backup plan but did
   not query AWS Backup exhaustively. Given (2), this is the only copy.
6. **Which domain, and when?** `aiinterview.com` or similar was mentioned. Not
   purchased. PROD cannot exist without one.
7. **Does the SSM parameter move to `/basic-rag/dev/…` now or with Terraform?**
   It is the one renameable-by-recreation item that does not need Terraform —
   create, repoint the task definition, delete. Cheap to do early, and it makes
   the convention real before the rest catches up.
8. **Should `environment` and the third sense of `service` be added to
   `DOMAIN_TERMS.md`?** Proposed above, not added.
