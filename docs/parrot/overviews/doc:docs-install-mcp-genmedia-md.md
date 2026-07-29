---
type: Wiki Overview
title: 'add repository:'
id: doc:docs-install-mcp-genmedia-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Remove old version:'
---

## Install Golang:
Remove old version:
sudo apt remove golang-1.18*

# add repository:
sudo add-apt-repository ppa:longsleep/golang-backports
sudo apt update

# install new version:
sudo apt install golang-1.24 golang-1.24-go


## starts a single MCP server:

export PROJECT_ID=navigator
export GOOGLE_APPLICATION_CREDENTIALS=env/google/navigator.json
mcp-imagen-go --transport stdio

// repeat the same for all servers.
