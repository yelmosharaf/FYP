# CLAUDE.md

This file provides guidance for AI assistants (Claude Code and others) working in this repository.

## Project Overview

**FYP** — Final Year Project repository. This is currently in early/stub state with no source code committed yet. The project type and technology stack have not been defined.

## Repository State

- **Status**: Stub/initialization phase
- **Remote**: `http://local_proxy@127.0.0.1:40393/git/yelmosharaf/FYP`
- **Default branch**: Not yet established (currently working on `claude/add-claude-documentation-uRIoU`)
- **Content**: Only `README.md` and `CLAUDE.md` are present

## Git Conventions

- **Branch naming**: `claude/<short-description>` for AI-assisted work, `feature/<description>` for features, `fix/<description>` for bug fixes
- **Commits**: Write clear, descriptive commit messages in the imperative mood (e.g., "Add authentication module", not "Added auth")
- **Push**: Always use `git push -u origin <branch-name>`
- **Do not force-push** to shared branches without explicit user approval

## Development Workflow

Since no project structure exists yet, follow these steps when the project type is established:

1. Confirm the technology stack with the user before creating files
2. Set up appropriate configuration files (linting, formatting, testing)
3. Update this CLAUDE.md with stack-specific conventions once decided
4. Keep `README.md` updated with setup and run instructions

## General Conventions for AI Assistants

- **Read before editing**: Always read a file before modifying it
- **Minimal changes**: Only change what is necessary for the task; do not refactor unrelated code
- **No speculative abstractions**: Don't add helpers or utilities for hypothetical future use
- **Security**: Do not introduce command injection, SQL injection, XSS, or other OWASP vulnerabilities
- **No secrets in code**: Never commit API keys, passwords, or tokens; use environment variables
- **Ask before destructive actions**: Confirm before deleting files, force-pushing, or resetting branches

## TODO: Update When Project Is Defined

When the project stack and structure are established, update this file with:

- [ ] Technology stack and versions
- [ ] How to install dependencies
- [ ] How to run the project locally
- [ ] How to run tests
- [ ] Environment variable requirements (list names, not values)
- [ ] Build and deployment process
- [ ] Code style and linting tools in use
- [ ] Database setup instructions (if applicable)
