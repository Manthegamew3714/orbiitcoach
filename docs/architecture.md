# Architecture Deep Dive

> For a visual, interactive version of this document, see [orbiitcoach.com/architecture](https://orbiitcoach.com/architecture).

## System Overview

OrbiitCoach is a serverless, event-driven AI coaching platform. Every component is managed through AWS SAM (CloudFormation) — there are no manually provisioned resources.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND                                      │
│  React 18 SPA → CloudFront CDN → S3 Static Hosting                     │
│  Tailwind CSS · Framer Motion · React Query                             │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ HTTPS
┌──────────────────────────────▼──────────────────────────────────────────┐
│                        API GATEWAY (REST)                               │
│  Cognito JWT Authorizer · Rate Limiting · CORS                          │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Chat Lambda │    │  Onboarding      │    │  Planner Agent   │
│  (5.1K LoC)  │    │  Lambda          │    │  Lambda          │
│              │    │                  │    │                  │
│  13 AI Tools │    │  CV Upload +     │    │  Weekly Plan     │
│  3 Chat Modes│    │  AI Extraction   │    │  Pipeline        │
│  Memory Mgmt │    │  6-Step Flow     │    │  Gap Analysis    │
└──────┬───────┘    └────────┬─────────┘    └────────┬─────────┘
       │                     │                       │
       ▼                     ▼                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        AWS BEDROCK                                       │
│                                                                          │
│  Claude Haiku 4.5     Claude Sonnet 4.5      Claude Opus 4.6            │
│  ─────────────────    ─────────────────      ─────────────────          │
│  Fast classification  Core coaching          Deep reasoning              │
│  Fact extraction      Tool orchestration     Weekly plan generation      │
│  Structured parsing   Resource curation      Career strategy             │
│  ~200ms               ~2s                    ~45s                        │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│                         DYNAMODB (10 TABLES)                            │
│                                                                          │
│  Conversations · Messages · Profiles · Memory · Plans                    │
│  Resources · Goals · Cost Tracking · Admin · Features                    │
│                                                                          │
│  GSIs for access patterns · TTL for message cleanup                      │
└─────────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│                     STEP FUNCTIONS (2 STATE MACHINES)                    │
│                                                                          │
│  Weekly Plan Pipeline:                                                   │
│    CollectData → AnalyseGaps → ResearchMarket → GeneratePlan → Write    │
│                                                                          │
│  Pre-Weekly Check-in Pipeline:                                           │
│    LoadProfile → GenerateQuestions → WaitForAnswers → Analyse → Store    │
│                                                                          │
│  Triggered by: EventBridge schedule + manual API trigger                 │
└─────────────────────────────────────────────────────────────────────────┘
```

## Lambda Functions (14 total)

| Function | Purpose | Model | Lines of Code |
|----------|---------|-------|--------------|
| **Coach Chat** | Conversational coaching with 13 callable tools | Sonnet 4.5 | 5,100+ |
| **Career Planner Agent** | Weekly plan generation pipeline orchestration | Opus 4.6 | 1,400+ |
| **Coach Onboarding** | CV upload, AI profile extraction, 6-step flow | Sonnet 4.5 | 900+ |
| **Coach Plan Writer** | Persists generated plans to DynamoDB | — | 300+ |
| **Admin API** | User management, feature flags, system stats | — | 500+ |
| **Job Discovery Scanner** | Scans job boards (multi-country), AI scoring | Haiku 4.5 | 1,100+ |
| **Email Classifier** | Classifies job-related emails from Gmail | Haiku 4.5 | 500+ |
| **+ 7 supporting functions** | Auth, CRUD, scheduling, notifications | Various | — |

## Data Flow: Chat Interaction

```
User sends message
    │
    ▼
API Gateway → JWT validation (Cognito)
    │
    ▼
Chat Lambda receives message
    │
    ├─→ Load conversation history (DynamoDB)
    ├─→ Load user profile + memory (DynamoDB)
    ├─→ Build system prompt with context
    │
    ▼
Call Bedrock (Converse API) with tools
    │
    ├─ Model responds with text → Stream to user
    ├─ Model calls a tool → Execute action:
    │     ├─ search_web (Tavily API)
    │     ├─ complete_task (update planner)
    │     ├─ log_hours (track time)
    │     ├─ save_resource (curate content)
    │     ├─ update_profile (modify goals)
    │     └─ ... (13 tools total)
    │
    ▼
Post-response processing:
    ├─→ Extract facts → Store in memory (Haiku)
    ├─→ Update cost tracking (per-user)
    └─→ Save conversation (DynamoDB)
```

## Data Flow: Weekly Plan Generation

```
EventBridge trigger (or manual API call)
    │
    ▼
Step Function execution begins
    │
    ├─ Step 1: Collect User Data
    │     └─ Aggregate from 10+ DynamoDB sources
    │        (profile, planner, resources, memory, goals, done tasks)
    │
    ├─ Step 2: Analyse Gaps (Claude Haiku)
    │     └─ Compare skills vs market demands
    │        Identify missing competencies
    │
    ├─ Step 3: Research & Propose (Claude Sonnet)
    │     └─ Search for resources matching gaps
    │        Propose learning paths
    │
    ├─ Step 4: Generate Plan (Claude Opus)
    │     └─ Synthesise ALL previous outputs
    │        Create day-by-day schedule
    │        Balance learning / projects / job search
    │
    └─ Step 5: Write Plan
          └─ Persist to DynamoDB
             Notify user
```

## DynamoDB Table Design

| Table | Partition Key | Sort Key | Purpose |
|-------|-------------|----------|---------|
| Conversations | user_id | conversation_id | Chat session metadata |
| Messages | conversation_id | timestamp | Chat message history |
| Profiles | user_id | — | User career data, config |
| Memory | user_id | fact_id | Long-term memory facts |
| Plans | user_id | week_start | Weekly plans |
| Resources | user_id | resource_id | Learning materials |
| Goals | date | — | Daily goal tracking |
| Cost Tracking | user_id | month | Per-user Bedrock spend |
| Features | user_id | — | Feature flags |
| Admin | — | — | System configuration |

**Access patterns** are handled through Global Secondary Indexes (GSIs) — for example, querying all plans for a user ordered by week, or all resources filtered by completion status.

## Security Model

- **Authentication**: AWS Cognito User Pool with email/password + social login
- **Authorization**: JWT tokens validated at API Gateway (no Lambda-level auth code)
- **Data isolation**: Every DynamoDB query includes `user_id` partition key — users can only access their own data
- **Secrets**: All API keys stored in AWS Systems Manager Parameter Store (SecureString)
- **CORS**: Restricted to application domain
- **IAM**: Each Lambda has least-privilege IAM policies defined in SAM template
