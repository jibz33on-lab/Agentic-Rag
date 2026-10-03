# 02 — AWS-native RAG with Bedrock Knowledge Bases

The same problem as project 01, solved by configuring managed AWS services
rather than by writing retrieval code.

Project 01 hand-builds the pipeline: split, embed, store, retrieve, rerank. Here
a Bedrock Knowledge Base owns all five, and the work moves into Terraform and
IAM instead. The point of building both is to find out what that trade actually
costs — in accuracy, in control, and in what you can still measure.

Retrieval is semantic only. S3 Vectors does not support hybrid search; that is
deliberate, and `infra/hybrid-spike/` exists to measure the alternative without
paying for it permanently. See **Cost** below.

## Status

Skeleton only. Nothing here runs yet.

## Designs

- the skeleton — [designs/skeleton.md](designs/skeleton.md)
- the `ingestion_job` and its verification — [designs/ingestion_job.md](designs/ingestion_job.md)

## Layout

```
infra/core/           S3, vector bucket, IAM, the KB, the data source
infra/hybrid-spike/   OpenSearch Serverless variant — apply, measure, destroy
src/                  config, KB client, answerer, query
tests/
```

`core` and `hybrid-spike` are separate Terraform root modules, so they hold
separate state. That is what makes `terraform destroy` on the spike safe: it
cannot reach the core stack, and it cannot reach project 01's infrastructure.

## Cost

This project runs on AWS credits, so the rule is: **per-use by default, and
anything always-on is provisioned for a session and destroyed afterwards.**

`core` has no always-on compute — S3 storage, S3 Vectors storage, and per-request
Bedrock calls. `hybrid-spike` provisions OpenSearch Serverless, which bills a
minimum capacity by the hour whether or not it is queried. Its normal state is
destroyed. Check before you walk away.

## The benchmark

Slice 3 runs project 01's 25-question benchmark against the same four PDFs, which
is the only configuration in which the two projects are comparable. The corpus
expands after that, and expanded-corpus numbers are recorded as their own rows —
changing the corpus changes the experiment.

## Running it

Nothing to run yet.
