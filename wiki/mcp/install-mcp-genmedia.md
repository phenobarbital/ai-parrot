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
