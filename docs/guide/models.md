# Choose the models

METIS uses an LLM in three steps of the flow. All roles can share one OpenAI-compatible gateway, so
a basic setup needs only `OPENAI_API_KEY` in `.env`. If you use your own gateway or model, add
`OPENAI_BASE_URL` and `DEFAULT_MODEL`, which makes three lines.

## Where METIS uses a model

| Step | Role | Recommended model | Effect on scores |
|---|---|---|---|
| Interview, including grader matching | Interview | A capable reasoning model. The quality of the test configuration depends on this model. | No |
| Simulation | User agent | A capable reasoning model. It must act like a realistic user. | Yes |
| Simulation, generic runners | Runner agent | A capable reasoning model. It chooses the calls or page actions that carry out each user action. | Yes |
| Grading | Judge | A fast, lightweight decision model by default, because it runs for each criterion and each conversation. Use a capable reasoning model if the budget allows it. | Yes |

## Choose models for the run

- **User agent:** use a model that is different from your target, and use a capable model. It
  acts as a real user who talks to your target.
- **Judge:** use a model from a different family than your target. A judge from the same family
  as your target can be biased in favour of its answers.

## Set up `.env`

Put these lines in a `.env` file at the project root:

```dotenv
OPENAI_API_KEY=your-gateway-key
OPENAI_BASE_URL=https://your-gateway/v1
DEFAULT_MODEL=your-model
```

`DEFAULT_MODEL` sets the model of every chat role: Interview, user agent, runner agent, and
judge. When it is not set, these roles use `gpt-6-luna`. To use another model, key, or gateway for
one role, set the variable of that role. It wins over `DEFAULT_MODEL`:

```dotenv
DEFAULT_MODEL=your-model
JUDGE_MODEL=your-judge-model   # the judge only
```

| Role | Model | API key | Base URL |
|---|---|---|---|
| Interview | `INTERVIEW_MODEL` | `INTERVIEW_API_KEY` | `INTERVIEW_BASE_URL` |
| User agent | `USER_AGENT_MODEL` | `USER_AGENT_API_KEY` | `USER_AGENT_BASE_URL` |
| Runner agent | `RUNNER_AGENT_MODEL` (default: the user agent model) | `RUNNER_AGENT_API_KEY` | `RUNNER_AGENT_BASE_URL` |
| Judge | `JUDGE_MODEL` | `JUDGE_API_KEY` | `JUDGE_BASE_URL` |

A role that has no key or URL of its own uses `OPENAI_API_KEY` and `OPENAI_BASE_URL`. For
example, to use another provider for the judge only:

```dotenv
JUDGE_API_KEY=your-judge-provider-key
JUDGE_BASE_URL=https://judge-provider/v1
JUDGE_MODEL=judge-model-from-another-family
```

The Interview model also matches each Criterion to a library grader. If that call fails, the
Interview still runs, and each new Criterion uses the criterion judge.

`metis wizard`, `metis engine`, and the API all read the same `.env`. They use the first `.env`
in the working directory or a directory above it, up to the project root. Set `METIS_ENV_FILE` to
use another file. A value that you export in the shell wins over `.env`. Keys and URLs go only in
`.env` or the environment, never in the Interview chat or the Specification.

## Record the models in `specification.yaml`

This step is optional. The user agent, runner agent, and judge models affect scores, so you can
record them in the Specification. Then other people can run it again with the same models.

If `specification.yaml` has no model, the run uses `.env`. If it has a model, that model wins,
and a change in `.env` has no effect.

```yaml
defaults:
  user_agent_model: your-user-agent-model
  runner_agent_model: your-runner-agent-model
  judge_model: your-judge-model
tasks:
  - id: TC-001
    scenario_ref: upload-report
    persona_ref: analyst
    user_agent_model: a-stronger-model   # this Test Case only
```

A Criterion can also set its own judge model in `grader_args.model`. In the web client, the run
settings step before the download writes the `defaults` models for you.

## Check which models a run uses

Each model comes from the first place that has a value: `specification.yaml`, then the role
variable (for example `JUDGE_MODEL`), then `DEFAULT_MODEL`, then the built-in default.

Before its first model call, each engine command prints the models that it uses and where each
one comes from:

```text
Models: User agent gpt-6-luna (DEFAULT_MODEL) · Judge gpt-6-luna (built-in default)
```

If a model is not the one that you expect, the name in brackets shows where it came from.

When a key is missing, the command stops and names the variables to set.
