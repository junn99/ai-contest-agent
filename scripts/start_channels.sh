#!/usr/bin/env bash
# Claude Code Channels 텔레그램 세션 시작
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"
cd /home/jun99/claude/infoke
exec claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions
