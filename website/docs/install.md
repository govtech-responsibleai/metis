---
title: Installation
---

Install METIS and set up your model provider.

## 1. Install the tools

Install Python 3.11 or later, Git, Make, Node.js 22 or later, and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

## 2. Install METIS

METIS is in beta. Clone the repository and run `make install`, which creates the virtual
environment and installs the exact dependency versions in the lockfile:

```bash
git clone https://github.com/govtech-responsibleai/metis.git
cd metis
make install
```

Check the installation:

```bash
uv run metis --help
```

<p className="code-caption">
  Plain <code>pip install</code> from the repository does not work, because the METIS packages
  depend on each other through a <code>uv</code> workspace that <code>pip</code> cannot resolve.
</p>

## 3. Set up the `.env` file

Create a `.env` file in the folder where you run METIS. In the clone, copy the example file
to the repository root:

```bash
cp .env.example .env
```

Then set the required values.

### Required

A model key. Every METIS command uses it:

```dotenv
OPENAI_API_KEY=your-model-provider-key
```

### Required to grade a run

`metis engine evaluate` reads the traces of the application you test from its Langfuse. It needs
these three values:

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://your-langfuse
```

`metis engine run` does the same grading after it simulates, so it needs them too. The wizard and
`metis engine simulate` do not read them, so you can add them later, before you grade.

### Optional

Everything else has a default. These are the settings you are most likely to change:

```dotenv
# Use a gateway or provider other than the default OpenAI endpoint.
OPENAI_BASE_URL=https://your-provider/v1

# Use one model for every role. Unset, the roles use gpt-6-luna.
DEFAULT_MODEL=your-model

# Or set the model of one role. It wins over DEFAULT_MODEL.
INTERVIEW_MODEL=your-interview-model
USER_AGENT_MODEL=your-simulation-model
JUDGE_MODEL=your-grading-model
```

Every METIS command reads this one file. A value that you export in the shell wins. Each model
role can also have its own key and gateway. See `docs/guide/models.md` and `.env.example` in the
repository.

## 4. Install the browser tools (optional)

For browser simulation with Playwright, install Chromium and its dependencies.
From the clone, run:

```bash
make install-extras-playwright
```

## Next step

Prepare your application and Langfuse in [Pre-requisites](prerequisites.md).
