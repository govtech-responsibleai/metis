---
title: Installation
---

Install METIS and set up your model provider.

## 1. Install the tools

| Tool | Version | Use |
|---|---|---|
| [Git](https://git-scm.com/downloads) | Any | Clones the repository |
| [GNU Make](https://www.gnu.org/software/make/) | Any | Runs the `make` commands |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Latest | Installs the Python packages |
| [Python](https://www.python.org/downloads/) | 3.11 or later | Runs METIS |
| [Node.js and npm](https://nodejs.org/en/download) | Node.js 22 or later | Runs the Wizard web client |

npm comes with Node.js. If uv finds no Python 3.11 or later, it downloads one during
`make install`.

Each tool links to its own install page. The install command depends on your operating system
and terminal. Use the command on that page that matches your setup.

- **Windows:** You can use Command Prompt, PowerShell, or Git Bash. A command for one terminal
  does not always work in the others, so check that the command is for your terminal.
- **macOS and Linux:** Use the terminal and the package manager of your system, for example
  Homebrew on macOS or `apt` on Debian and Ubuntu.

After you install a tool, open a new terminal so that it reads the new `PATH`.

Check the tools:

```bash
git --version
make --version
uv --version
node --version
```

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

To see all the `make` commands, run `make help`.

## 3. Add the `metis` command to your `PATH` (optional)

The commands in this guide use `metis` with no `uv run` prefix. To run `metis` from any folder,
install it as a uv tool. From the clone, run:

```bash
uv tool install --editable .
uv tool update-shell
```

`--editable` links the tool to your clone, so changes to the source take effect with no new
install. `uv tool update-shell` adds the uv tool folder to your `PATH`. Open a new terminal,
then check the command:

```bash
metis --help
```

If you do not install the tool, put `uv run` before each `metis` command and run it in the
clone.

## 4. Set up the `.env` file

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

If you do not set `DEFAULT_MODEL` or the model of a role, that role uses `gpt-6-luna`. The
embeddings role is different. It uses `text-embedding-3-large`, and `DEFAULT_MODEL` does not
change it.

Every METIS command reads this one file. A value that you export in the shell wins. Each model
role can also have its own key and gateway. See `docs/guide/models.md` and `.env.example` in the
repository.

## 5. Install the browser tools (optional)

For browser simulation with Playwright, install Chromium and its dependencies.
From the clone, run:

```bash
make install-extras-playwright
```

## Troubleshooting

**A tool shows "command not found" or "is not recognized".** The terminal reads `PATH` when it
starts. Open a new terminal after you install a tool. If the error stays, make sure that the
install folder of the tool is on your `PATH`.

**`metis` is not found after `uv tool install`.** Run `uv tool update-shell`, then open a new
terminal. To see the folder that must be on your `PATH`, run `uv tool dir --bin`.

**`make install` cannot find a Python version.** Install one with uv, then run `make install`
again:

```bash
uv python install 3.12
```

**`make install` fails in `npm ci`.** Run `node --version`. If the version is older than 22,
install Node.js 22 or later.

**`make` is not found on Windows.** Install it with `winget install --id ezwinports.make -e`,
then open a new terminal.

## Next step

Prepare your application and Langfuse in [Pre-requisites](prerequisites.md).
