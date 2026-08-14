# 0001 - Language and framework: Python + FastAPI

## Decision
Build the application in Python using FastAPI.

## Context
This is a learning project. The stated goal is to understand backend/systems engineering
concepts (HTTP, APIs, webhooks, validation, authentication, databases, external
integrations, idempotency, retries, error handling, logging, monitoring, security,
testing, deployment) as clearly as possible — not to build language proficiency for its
own sake. The developer has no prior preference or proficiency in either Python or
Node.js/TypeScript, so the choice had to be made purely on teaching value.

## Options Considered
- **Python + FastAPI**: Pydantic-based validation, dependency-injection system for
  cross-cutting concerns (auth, webhook signature checks), no build/compile step,
  documentation organized around exactly the concepts in scope (Security, Dependencies,
  Testing, CORS, Middleware, Error Handling).
- **Node.js + TypeScript (Express/Fastify)**: async-by-default I/O model (harder to avoid
  the non-blocking-I/O lesson), Express middleware chain is a more universally
  transferable request-pipeline mental model (same pattern across many frameworks/languages),
  Zod for validation, but requires a TypeScript build step (tsconfig, compilation) that
  adds tooling overhead unrelated to the concepts being learned.

## Decision Made
Python + FastAPI.

## Why
FastAPI's own reference documentation is structured almost exactly as a syllabus for the
concept list this project cares about, and Pydantic gives the clearest hands-on lesson in
what request/response validation actually is (the schema *is* the validation logic). No
build-tooling layer competes for attention with the systems concepts. Node/Express's
async-by-default model and more universal middleware pattern were real, considered
advantages, but secondary to the project's stated learning objective.

## Trade-offs
- Async I/O in FastAPI is opt-in (`async def`), not forced — a muddier starting point than
  Node's default async model, though the risk of accidentally mixing blocking calls into
  an async app is itself a useful lesson about blocking I/O.
- `Depends()`-based dependency injection is a FastAPI-specific pattern, less transferable
  to other frameworks than Express-style middleware.

This decision is locked and should not be reopened without a concrete technical problem
that requires reconsideration.
