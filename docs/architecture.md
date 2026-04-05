# Architecture Deep Dive

> How OrbiitCoach works under the hood — the decisions, the trade-offs, and how the agents actually talk to each other.

---

## The Big Picture

OrbiitCoach is serverless, event-driven, and fully defined in code (AWS SAM). No manually provisioned resources. The entire platform deploys from a single `template.yaml`.

The core design idea: **different tasks need different AI models**. A quick classification doesn't need the same horsepower as generating a full weekly career plan. So the system uses three Claude models, each matched to what it does best:

| Model | Job | Latency | When it fires |
|-------|-----|---------|---------------|
| **Haiku 4.5** | Classification, fact extraction, structured parsing | ~200ms | During every chat turn (post-processing) |
| **Sonnet 4.5** | Real-time coaching, tool orchestration | ~2s | Every user message |
| **Opus 4.6** | Weekly plan generation, career strategy | ~45s | Once a week (automated pipeline) |

This matters for cost too — Haiku is ~60x cheaper than Opus per token. You don't want Opus running on every message.

---

## Layer by Layer

### Frontend & CDN

React 18 SPA with Tailwind CSS and Framer Motion for animations. Hosted on **S3** behind **CloudFront** (global CDN). The frontend never stores JWT tokens in localStorage — they live in memory only, which prevents XSS token theft. This means a page refresh logs you out, but that's the trade-off I chose for security.

**React Query** handles all server state — caching, refetching, optimistic updates. The chat interface streams responses in real-time.

### Auth & API Layer

**Amazon Cognito** handles signup, login, and token management. Every API request hits a Cognito JWT authorizer at the **API Gateway** level — no auth logic lives inside Lambda functions. This keeps auth concerns completely separate from business logic.

The API Gateway exposes **60+ REST endpoints** routing to different Lambda functions. Rate limiting and CORS are configured at this layer.

### Chat & Coaching Engine

This is the core. The **Chat Lambda** is the biggest function at **5,100+ lines of Python** — it handles all user-facing API routes with internal routing.

What makes it interesting is the tool system. The AI has access to **13 callable tools**:

| Tool | What it does |
|------|-------------|
| `complete_task` | Marks a planner task as done |
| `log_learning_hours` | Tracks time spent on resources |
| `web_search` | Searches the web via Tavily for salary data, job trends, courses |
| `find_resource` | Discovers learning resources matching your gaps |
| `save_resource` | Adds a resource to your library |
| `update_resource_progress` | Updates completion % on a resource |
| `complete_resource` | Marks a resource as finished |
| `get_user_resources` | Retrieves your resource library |
| `update_skill` | Modifies your skill profile |
| `add_learning` | Records a new learning activity |
| `complete_learning` | Marks learning as completed |
| `update_profile` | Changes career goals, preferences |
| `weekly_checkin` | Submits answers to weekly reflection questions |

The AI decides which tools to call and when — using Claude's native function calling (Converse API), not regex parsing. But here's the key: **every mutating action requires user confirmation**. When the AI wants to save a resource or complete a task, the frontend shows a Yes/No prompt first. No surprises.

**3 Chat Modes** control which tools are available:
- **Default** — Full coaching with all 13 tools
- **Insights & Preferences** — Pre-weekly reflection (no data mutations)
- **Urgent & Demands** — Mid-week schedule adjustments (planner-focused only)

### Memory System

After every conversation, **Haiku** extracts facts and stores them in a dedicated memory table. Things like "wants to move into Solutions Architecture" or "prefers morning study sessions" persist across conversations and are injected into the system prompt.

This is what makes it feel like it actually knows you. Without memory, every conversation starts from scratch. With it, the AI builds context over weeks.

### Onboarding

A 6-step guided flow:
1. **Upload your CV** (PDF → S3 with presigned URLs)
2. **AI reviews it** — Claude extracts structured data: experience, skills, education
3. **Set career goals** — target role, salary, timeline
4. **Preferences** — timezone, week structure
5. **Time budget** — how many hours per week, broken down by day
6. **Review & confirm**

Features unlock progressively — you can't access the planner until onboarding is 100%. This ensures the system has enough context to generate useful plans.

---

## The Automated Pipelines

This is where agents work autonomously, without user input.

### Pre-Weekly Pipeline (Fridays, 5pm UK)

A Step Functions state machine that prepares the ground for next week's plan:

```
Data Collector → Gap Analyzer → Context Builder → Research Analyzer → Question Finalizer
```

1. **Data Collector** — Pulls everything: profile, completed tasks, resources, memory, planner history
2. **Gap Analyzer** — Rule-based + Haiku analysis. Compares what you planned vs what you did. Spots incomplete tasks, stale resources, missing skills
3. **Context Builder** — Bundles everything into a research brief. Generates search queries (deterministic, no LLM)
4. **Research Analyzer** — Hits **Tavily** for live market data: salary benchmarks, trending skills, job market conditions relevant to your goals. Then Sonnet analyses the findings
5. **Question Finalizer** — Generates 3-5 targeted check-in questions. "You didn't finish the AWS certification module this week — was it too hard, or did priorities shift?"

The user answers these questions over the weekend (in chat or UI). Their answers feed directly into Sunday's plan generation.

### Weekly Planner Pipeline (Sundays, 9pm UK)

The main event — where the full weekly plan is generated:

```
Data Collector → Prompt Builder → Planner Agent → Plan Writer
```

1. **Data Collector** — Same aggregation, but now includes the check-in answers from Friday
2. **Prompt Builder** — Assembles the "Ultimate Prompt" (~4,000 tokens). This is pure data orchestration — no LLM call. It structures everything the planner needs: profile, time budget, last week's performance, gap analysis, market research, memory, and check-in responses
3. **Planner Agent** — Sends the Ultimate Prompt to **Claude Opus 4.6**. This is where the heavy reasoning happens. Opus generates a structured weekly plan: daily tasks with time allocations, resource recommendations, coaching notes, and priority ordering
4. **Plan Writer** — Persists the plan to DynamoDB. Proposes new resources. Archives expired questions. Logs the workflow

**Multi-tenant**: Both pipelines process all eligible users in parallel (Step Functions Map state, max concurrency 3). If one user's plan generation fails, others still complete.

---

## How the Agents Talk to Each Other

This is what ties everything together. No single agent works in isolation — they feed each other through a shared data layer.

```
             ┌─────────────────────────────────────────────────┐
             │              User Conversations                  │
             │              (Chat + Sonnet)                     │
             └──────┬──────────┬──────────┬────────────────────┘
                    │          │          │
            extracts      saves     completes
            memories    resources     tasks
                    │          │          │
                    ▼          ▼          ▼
             ┌─────────────────────────────────────────────────┐
             │           DynamoDB (Shared State)                │
             │   memory · resources · planner · profile         │
             └──────┬──────────────────────────┬───────────────┘
                    │                          │
                reads ALL                  reads ALL
                user data                  user data
                    │                          │
                    ▼                          ▼
         ┌──────────────────┐      ┌───────────────────────┐
         │  Pre-Weekly       │      │  Weekly Planner        │
         │  (Fri · Haiku)    │      │  (Sun · Opus)          │
         │                   │      │                        │
         │  Analyses gaps    │      │  Builds full plan      │
         │  Researches web   │──────│  from ALL inputs       │
         │  Asks questions   │ feeds│  (inc. Friday answers) │
         └──────────────────┘ into └────────┬──────────────┘
                                            │
                                    writes tasks,
                                   proposes resources
                                            │
                                            ▼
                                   User sees plan Monday
                                   → works on tasks
                                   → chats with AI coach
                                   → cycle repeats
```

**The compound effect**: Each week, the system has more data. More completed tasks, more conversations, more extracted memories. The plan gets better because it has more context. A plan from week 8 is meaningfully different from week 1.

---

## Data Layer

### DynamoDB — 12 Tables

| Table | PK | SK | What it stores |
|-------|----|----|----------------|
| `coach-users` | user_id | — | Account data, subscription tier |
| `coach-conversations` | user_id | conversation_id | Chat sessions with metadata |
| `coach-memory` | user_id | fact_id | Extracted long-term facts |
| `coach-profile` | user_id | — | Career goals, skills, preferences, time budget |
| `coach-planner` | user_id | week_start | Weekly plans with daily task breakdown |
| `coach-done-tasks` | user_id | task_id | Completed task history |
| `coach-resources` | user_id | resource_id | Learning materials with progress |
| `coach-weekly-questions` | user_id | question_id | Check-in questions + answers |
| `coach-usage` | user_id | month | Per-user API call metering |
| `coach-usage-daily` | user_id | date | Daily cost aggregation |
| `coach-workflow-logs` | run_id | step | Pipeline execution logs |
| `coach-invites` | code | — | Invite-only signup codes |

All tables use on-demand capacity — no provisioned throughput to manage. GSIs handle secondary access patterns (e.g. querying plans by week, resources by status).

### Why DynamoDB over Postgres?

Serverless-native. No connection pooling headaches in Lambda (RDS requires RDS Proxy or connection management). Pay-per-request pricing matches Lambda's per-invocation model. The data is inherently key-value — user_id partitioning gives perfect data isolation without row-level security.

---

## External Integrations

| Service | Purpose | How it's used |
|---------|---------|---------------|
| **AWS Bedrock** | AI inference | 3 Claude models via Converse API with native function calling |
| **Tavily API** | Web search | Real-time career intelligence — salary data, job trends, courses |
| **Amazon SES** | Email | Welcome emails, signup notifications |
| **S3** | Storage | CV uploads (presigned URLs), frontend static hosting |

---

## Security

- **Auth**: Cognito JWT validated at API Gateway — zero auth code in Lambdas
- **Data isolation**: Every DynamoDB query includes `user_id` partition key. Users can only access their own data. No admin override possible through the API
- **Secrets**: All API keys in AWS Systems Manager Parameter Store (SecureString)
- **Token handling**: JWTs stored in memory only (not localStorage) — prevents XSS token theft
- **IAM**: Least-privilege policies per Lambda, defined in SAM template
- **Invite-only**: Signup requires a valid invite code — controls growth during beta

---

## Design Decisions — What I'd Tell Another Builder

| Decision | What I chose | What I learned |
|----------|-------------|----------------|
| **Model per task** | Haiku / Sonnet / Opus split | The cost difference is massive. Using Opus for everything would cost 60x more and add latency to every chat message |
| **Action confirmations** | User approves AI actions before execution | Non-negotiable for trust. Without it, the AI could silently modify your profile or complete tasks you haven't done |
| **Step Functions over Lambda chains** | State machines for pipelines | Visual debugging alone is worth it. When a plan generation fails, I can see exactly which step failed and retry from there |
| **Single chat Lambda** | One big function with internal routing | Reduces cold starts. All business logic is co-located. Trade-off: the function is large (5K+ LoC), but deployment is simpler |
| **Memory extraction as post-processing** | Haiku runs after every chat turn | Async, cheap, and doesn't slow down the user experience. Worst case: a memory extraction fails silently and the fact is lost — not a critical failure |
| **Prompts as code** | Base class pattern with versioning | Prompts are the product logic. Treating them like config files is a mistake. They need to be versioned, tested, and reviewed like any other code |

---

## Infrastructure Summary

- **14 Lambda functions** (Python 3.11)
- **12 DynamoDB tables** (on-demand)
- **2 Step Functions state machines** with EventBridge schedules
- **1 Cognito User Pool** (email-based, invite-only)
- **1 API Gateway** (60+ REST endpoints)
- **1 S3 bucket** for CV uploads
- **1 CloudFront distribution**
- **2 Lambda Layers** (shared dependencies)
- **Full IaC** — single SAM template
- **Region**: eu-west-2 (London) backend, us-east-1 frontend CDN

---

*Built and shipped by [Adrien Gourier](https://adriengourier.com) — [LinkedIn](https://linkedin.com/in/adriengourier)*
