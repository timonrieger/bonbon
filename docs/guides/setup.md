# Setup

One-time setup, about 20 minutes. If something fails, paste the error into your AI agent along with "I'm following docs/guides/setup.md". If that doesn't solve it, ask in the team chat.

**Windows:** do everything inside WSL2 (Ubuntu) and open the repo with VS Code's "WSL" extension.

## 1. Install the basics

1. [VS Code](https://code.visualstudio.com/) and [Git](https://git-scm.com/downloads)
2. mise: follow [mise.jdx.dev/getting-started](https://mise.jdx.dev/getting-started.html), including the step that activates mise in your shell. Restart the terminal afterwards.
3. Clone the repo and open the folder in VS Code. Accept "Install recommended extensions".

## 2. Install the project

In the VS Code terminal, inside the repo:

```sh
mise trust
mise install      # Python, Node, pnpm, AWS CLI, SAM CLI: the exact versions for this project
mise run setup    # dependencies + git hooks
```

## 3. Connect your Learner Lab account

Do this at the start of every lab session (credentials expire after about 4 hours):

1. Open the Learner Lab: log in at <https://awsacademy.instructure.com> (your AWS Academy account from the course invitation, not an AWS login) → **Courses** → the Learner Lab course → **Modules** → **Launch AWS Academy Learner Lab**. Click **Start Lab** and wait for the green dot. Clicking **AWS** next to the dot opens the AWS console.
2. **AWS Details** → **AWS CLI: Show** → copy the whole block starting with `[default]`.
3. VS Code: `Terminal → Run Task… → AWS: paste Learner Lab credentials`, paste, then press Enter on an empty line.
4. Check: `aws sts get-caller-identity` prints your account.

## 4. Deploy your own dev stack

First time only (about 3 minutes):

```sh
mise run stack:up
```

This creates `bonbon-dev` in your account (API, login, database) and writes `packages/web/.env.local`.

## 5. Start developing

`Terminal → Run Build Task…` (⇧⌘B / Ctrl+Shift+B) runs **Dev: start**:

- The app runs at <http://localhost:5173>. Create an account; the verification code arrives by e-mail.
- Backend changes are pushed to your stack automatically while it runs.

Stop it with Ctrl+C in the terminal.

## Budget

Each account has 50 USD. Idle stacks cost close to nothing. Check the remaining budget weekly (shown in the Learner Lab). Never create EC2, RDS or NAT gateways.
