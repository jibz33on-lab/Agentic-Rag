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

> **Scope is as it was written, and is not being revised.** It records what this
> session excluded, which stays true whatever happened afterwards. Three of the
> items above have since been built — IaC, reproducible ingestion, and the `ALB`
> — each as its own step with its own verification. **Known gaps** and **The
> remaining roadmap** carry the current state; this list carries the original
> boundary.

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

> **Terraform landed and the renames did not.** The estate was adopted by
> `import`, which by definition takes resources under the names they already
> have, and renaming any of them would mean destroying and recreating them —
> exactly what the table's own reasoning above rules out. So the trigger in the
> "When" column has passed without firing. The rename is now tied to the first
> thing that genuinely recreates a resource, which in practice means a second
> environment. The debt is unchanged in size and has lost its date.

## Known gaps

From the audit, split by whether they block anything.

### Closed

- **Container health check — done.** Task definition `basic-rag-api:5` declares
  a `healthCheck` on the `api` container, and `healthStatus` reads `HEALTHY`
  where it read `UNKNOWN`. The probe:

  ```
  CMD  /app/.venv/bin/python  -c
      import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(
          "http://localhost:8000/health", timeout=2).status==200 else 1)
  ```

  with `interval 30`, `timeout 5`, `retries 3`, `startPeriod 30`. Four things
  about it are deliberate.

  **Python, not `curl`.** The image is `python:3.12-slim` and contains neither
  `curl` nor `wget` — the two commands every health-check example uses. Adding
  one would put a package in the image solely to ask the image a question it can
  already answer. The probe uses the interpreter that is already there, by
  absolute path so it does not depend on `PATH`.

  **`CMD`, not `CMD-SHELL`.** `CMD` execs the argument vector directly. The
  probe carries both single and double quotes, and putting a shell in the middle
  means escaping that correctly in the task definition, in `jq`, and in whatever
  edits it next. `CMD` removes the shell, and the escaping with it.

  **In the task definition, not the `Dockerfile`.** This is the part that is
  easy to get wrong. The ECS agent reads *only* health checks declared in the
  container definition; it explicitly ignores a `HEALTHCHECK` baked into an
  image. A `HEALTHCHECK` line in our `Dockerfile` would work under
  `docker compose` and do nothing at all on Fargate.

  **No ALB.** The probe runs inside the task against `localhost`, so it never
  crosses the ENI and `basic-rag-api-sg` is never consulted — which is why this
  works today even though that group still admits only a laptop IP that has
  since changed. An unhealthy essential container in a *service* is stopped and
  replaced by the ECS scheduler itself; no load balancer is in that path. An ALB
  answers "which target gets this request", which has no meaning at
  `desiredCount: 1`. It stays with HTTPS and PROD, where it belongs.

  What this buys: the deployment circuit breaker — already enabled, already set
  to roll back — can now see a task that starts cleanly and then fails to serve.
  `ci.yml` needed no change, because it reads the live task definition and edits
  only the `image` field, so the block is carried into every future revision;
  but its `wait-for-service-stability` gate is now a smoke test rather than a
  liveness check.

  What this does **not** buy: this is liveness, not readiness. `/health` answers
  from the process and never touches Qdrant or OpenRouter, by design and by
  test — a dependency check would mark every instance unhealthy over one slow
  Qdrant and replace them all over something replacement cannot fix. A task
  whose Qdrant is unreachable still reports `HEALTHY`. Closing *that* gap means
  a separate `/ready` and an alarm, not a change to this probe.

  Verified 2026-09-21: `healthStatus` `UNKNOWN` → `HEALTHY`; CloudWatch shows
  `GET /health 200 OK` from `127.0.0.1` every 30s; and a throwaway standalone
  task pointed at a non-existent path was reported `UNHEALTHY` within ~30s.

- **Reproducible ingestion — done.** Roadmap step 2. S3 holds the documents and
  their manifest; a one-off ECS task fetches them, verifies every `sha256`
  before a `chunk` is embedded, and rebuilds the collection outright. The commit
  message on `5c2fa58` carries the reasoning; `designs/ingestion.md` carries the
  design. Its consequence for this document is that the corpus is no longer
  "only on one machine", which was the stated blocker for everything downstream.

- **Terraform for what exists — done.** Roadmap step 3. See **Infrastructure as
  code** below for what is managed and what deliberately is not.

- **`ALB` stood up, learned, and torn down — done, HTTP only.** Roadmap step 4,
  and the exercise the ephemeral-infrastructure argument was written for.

  An internet-facing `ALB` across all six subnets, one HTTP listener on `:80`
  forwarding to a target group on `:8000` with `target_type = ip` — required,
  not preferred, because a Fargate task under `awsvpc` owns an ENI and there is
  no instance to register. Health check `GET /health`, matcher `200`.

  Three things it demonstrated that are worth keeping:

  **Two health checks on one path, answering different questions.** One log
  stream carried probes from `127.0.0.1` (the ECS agent, inside the task) and
  from two `172.31.x.x` addresses (the `ALB`'s nodes, across the ENI). The
  container check asks *is this process alive*; the target group asks *should
  this target receive traffic*. The first replaces a task, the second drains it
  and leaves it running to be looked at.

  **The task was never exposed.** `basic-rag-api-sg` admitted `:8000` only from
  the `ALB`'s security group — by group reference, since `ALB` nodes hold
  private IPs that change as it scales. A direct request to the task's public
  address timed out while the same request through the `ALB` returned `200`.

  **A deploy through a load balancer needs nothing extra.** CI moved the service
  from `:6` to `:7` mid-exercise; ECS deregistered the old task's IP and
  registered the new one unprompted, and `ci.yml` needed no change, because
  `UpdateService` alters only what it is passed.

  **The teardown failed twice, and both failures were ours.** Recorded because
  neither is visible in a plan. A `dynamic "ingress"` block producing zero
  blocks is indistinguishable, to the AWS provider, from not configuring ingress
  at all — so the rule pointing at the `ALB`'s security group was silently kept,
  the plan looked clean, and the delete failed for fifteen minutes with
  `DependencyViolation`. An empty *list* assigned to the attribute is
  unambiguous. Then, with that fixed, Terraform attempted the delete before the
  revoke: with the `ALB` disabled the configuration no longer references the
  group at all, so there is no dependency edge to order them, and `-target` does
  not help because count-orphans are processed regardless. `var.keep_alb_sg`
  lets the group outlive the rest of the `ALB` by one `apply`.

  Detaching the load balancer also left the ECS service deadlocked at two
  running tasks against a desired count of one: `maximumPercent` 200 of 1 is a
  ceiling of two, two stale deployments held both slots, and the replacement
  could not start. `force-new-deployment` made it worse by adding a third
  deployment with nowhere to go. Stopping one stale task cleared it in three
  minutes. Worth knowing before the rebuild.

  Total cost, stood up to torn down: about three cents.

- **Stale security group rule — removed.** `basic-rag-api-sg` no longer admits
  `:8000` from `103.104.46.6/32`. The rule's own description said *"temporary:
  direct access from my laptop (no ALB yet)"*, and it had been broken for days
  anyway — the address had been reassigned, which is why the Issue #2 audit
  could not reach the running API.

### Before DEV can be called reliable

These are the ones worth doing next, and none of them needs a second
environment.

- **The three chunking settings are absent from the task definition**, so
  `collection_name` depends on defaults agreeing across two codebases forever.
  Make `EMBEDDING_MODEL`, `CHUNK_SIZE` and `CHUNK_OVERLAP` explicit.
- **Duplicate secret.** The OpenRouter key exists in both SSM and Secrets
  Manager; the task definition reads SSM, the Secrets Manager copy is orphaned
  from task definition revision `:1`, and `ecsTaskExecutionRole` still carries
  an inline policy granting access to it. Two places to rotate, one of which
  nothing reads. Delete the secret and the policy.
- **No log retention on `/ecs/basic-rag-api`.** Grows forever. `/ecs/basic-rag-qdrant`
  has 7 days; match it.
- **No backup of the vector data.** One EFS filesystem, no access point, and no
  backup plan. This is now the oldest untouched gap in the list, and ingestion
  being reproducible softens it without closing it: the `chunk`s can be rebuilt
  from S3, but only by a deliberate run, and an accidental deletion would still
  be a restore-from-nothing.
- **The API is currently unreachable.** `basic-rag-api-sg` has no ingress rules
  at all since the `ALB` came down, which is correct — the load balancer was the
  front door and there is deliberately no second one. It does mean `POST /query`
  cannot be exercised against DEV until an `ALB` exists again. ECS Exec, step 5,
  is the intended way back in for debugging; a hand-added CIDR rule is not.

### Later, and deliberately not now

- **`ALB` and HTTPS.** **Partly resolved.** The `ALB` half was built, verified
  and torn down as roadmap step 4 — see *Closed*. HTTPS was not, and is blocked
  below rather than deferred.
- **A domain name.** Still no purchase, and this has been promoted from a
  deferral to **the active blocker**. ACM refuses to issue a public certificate
  for an `…elb.amazonaws.com` name — not as a setting but as an ownership
  check, since AWS owns that domain and neither the DNS validation record nor
  the validation email can be produced for it. So HTTPS cannot be rehearsed at
  all, even temporarily, without a domain this account controls. Route 53's
  registrar is unavailable on this account — `ListDomains` returns
  `AccessDeniedException: Free Tier accounts are not supported` — so the
  purchase has to happen at an external registrar, after which DNS can either
  move to a Route 53 hosted zone (~$0.50/month, fully automatable) or stay at
  the registrar (free, one manual CNAME during issuance).
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

1. ~~**Container health check.**~~ **Done** — 2026-09-21. See *Closed*.
2. ~~**Reproducible ingestion.**~~ **Done** — 2026-09-21. See *Closed*.
3. ~~**Terraform for what exists.**~~ **Done** — 2026-09-21. See *Closed* and
   **Infrastructure as code** below.
4. **Stand up an `ALB` with HTTPS, learn it, tear it down.** **Half done.** The
   `ALB` went up, was verified end to end over HTTP, and came down again, for
   about three cents of uptime. **HTTPS is blocked on a domain** — see the
   domain entry under *Later*, which has stopped being a deferral and become
   the one thing this project now needs from outside itself.
5. **Task role, then ECS Exec.** Least privilege, and the ability to get inside
   a running task. **This is now the next step.**
6. **Alarms and log retention.** A few metric filters and an SNS topic.
7. **Private subnets and VPC endpoints**, if the budget allows it, as a
   deliberate exercise rather than a requirement.

**Steps 3 and 4 together are the argument of this whole document**, and the
argument held. Ephemeral infrastructure is only affordable if recreating it is
reliable, and recreating it is only reliable if it is code. The `ALB` was two
`apply`s against code that had already proved it matched reality, and the entire
exercise cost roughly three cents rather than $16 a month forever.

What the exercise actually taught, beyond the AWS concepts, was that a plan can
be clean and wrong. Both teardown failures came from this repository's own
Terraform, not from AWS — see *Closed* below.

## Infrastructure as code

**Implemented — 2026-09-21.** Terraform, in `infra/`. The estate was adopted by
`import`, not recreated: nothing was destroyed and nothing was rebuilt, and the
running API task kept the same id straight through the adoption.

Twenty-one resources are managed — the cluster, both services, the Qdrant task
definition, three security groups, the EFS filesystem and its six mount targets,
the Cloud Map namespace and its service, and three log groups.

**The bar was a second `plan` reporting no changes**, and that is the whole
point of the step rather than a nicety. Code that merely creates similar
resources is a description of an idea; code whose `plan` is empty against the
live estate is a description of the estate. Reaching it took four corrections,
each of them this repository being wrong about AWS rather than the reverse.

Four things sit outside Terraform, each for a reason worth keeping:

- **The default VPC and its subnets are data sources, never managed.** Owning
  them would put `destroy` one command away from deleting the VPC that
  everything else in the account also sits in.
- **The `basic-rag-api` task definition is not managed.** `ci.yml` registers a
  revision on every deploy; two owners of one resource means every `plan` shows
  drift and every `apply` fights the pipeline. The service carries
  `ignore_changes = [task_definition]` instead. That has since survived three CI
  deploys — `:6` to `:7` to `:8` — with `plan` still reporting no changes.
- **The SSM parameter is never read.** `data "aws_ssm_parameter"` decrypts by
  default, which would write the OpenRouter key into `terraform.tfstate`.
- **IAM roles and both ECR repositories are out.** Shared and never renamed; a
  `destroy` should not be able to reach them.

**State is local**, `infra/terraform.tfstate`, gitignored. Adequate for one
person on one machine and inadequate the moment there are two of either. An S3
backend with a lock is the next hardening step and it is small.

The cheaper interim step this section used to propose — committing both task
definitions and having CI render from the repo — was not taken. Qdrant's is now
Terraform; the API's is still live-only, so its container definition remains
unreviewable in the repo. That is the accepted price of not fighting the
pipeline, and it is a trade rather than an oversight.

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
