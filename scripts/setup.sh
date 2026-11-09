#!/usr/bin/env bash
# DrPanda MCP deployment helper.
#
# Commands:
#   check                 Read-only environment/preflight checks (default)
#   install               Install from source (git + uv sync) or PyPI (uv tool)
#   service               Install/enable a systemd service (Linux, root)
#   start                 Start the service (or run in foreground if no service)
#   status                Show service/health status
#   upgrade               Upgrade the existing source/PyPI installation
#
# Examples:
#   ./scripts/setup.sh check
#   ./scripts/setup.sh install --method source --extras mysql,redis
#   ./scripts/setup.sh install --method pypi --version 1.7.0
#   sudo ./scripts/setup.sh service --dir /opt/dr-panda-mcp
#   ./scripts/setup.sh start
#
# Safety:
# - check never modifies files.
# - install is idempotent: it does not overwrite .env/data/keys.
# - the first installation must use a loopback listen address.
# - secrets are never printed.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_URL="${DR_PANDA_REPO_URL:-https://github.com/linyu19872008/dr-panda-mcp.git}"
DEFAULT_VERSION="${DR_PANDA_VERSION:-1.7.0}"
VERSION=""
DEFAULT_USER="${DR_PANDA_SERVICE_USER:-drpanda}"
DEFAULT_SERVICE_NAME="${DR_PANDA_SERVICE_NAME:-dr-panda-mcp}"
VALID_EXTRAS="mysql postgres mongo redis kafka cls"

COMMAND="check"
DIR=""
METHOD=""
EXTRAS=""
PYTHON_SPEC="auto"
DEV=0
INDEX_URL=""
PYTHON_MIRROR=""
PYTHON_BIN=""
SERVICE_USER="$DEFAULT_USER"
SERVICE_NAME="$DEFAULT_SERVICE_NAME"
REPO_URL_OVERRIDE=""
ASSUME_YES=0
NO_START=0

log()  { printf '%s\n' "$*"; }
info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
fail() { printf '[FAIL] %s\n' "$*" >&2; }
die()  { fail "$*"; exit 1; }

usage() {
  sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --dir PATH              Application directory (default: current repo for source,
                          /opt/dr-panda-mcp for pypi/service)
  --method source|pypi    Installation method (install/upgrade)
  --version VERSION       PyPI version (default 1.7.0)
  --python PYTHON         Python interpreter (default: auto; system >=3.11 first)
  --dev                   Install the dev dependency group (source only)
  --index-url URL         PyPI index (sets UV_DEFAULT_INDEX)
  --python-mirror URL     python-build-standalone mirror (sets UV_PYTHON_INSTALL_MIRROR)
  --extras LIST           Comma-separated extras: mysql,postgres,mongo,redis,kafka,cls
                          Use "all" for --all-extras (source) / all extras (pypi)
  --user USER             systemd service user (default drpanda)
  --service-name NAME     systemd unit name (default dr-panda-mcp)
  --repo URL              Git repository URL (source)
  --yes                   Do not prompt before installing uv
  --no-start              Install the systemd unit without starting it
EOF
}

have() { command -v "$1" >/dev/null 2>&1; }
is_root() { [[ "${EUID}" -eq 0 ]]; }
is_linux() { [[ "$(uname -s)" == "Linux" ]]; }
is_loopback() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    127.0.0.1|localhost|::1) return 0 ;;
    *) return 1 ;;
  esac
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "missing value for $1"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      check|install|service|start|status|upgrade)
        COMMAND="$1"; shift ;;
      --dir) need_value "$@"; DIR="$2"; shift 2 ;;
      --method) need_value "$@"; METHOD="$2"; shift 2 ;;
      --version) need_value "$@"; VERSION="$2"; shift 2 ;;
      --extras) need_value "$@"; EXTRAS="$2"; shift 2 ;;
      --user) need_value "$@"; SERVICE_USER="$2"; shift 2 ;;
      --service-name) need_value "$@"; SERVICE_NAME="$2"; shift 2 ;;
      --repo) need_value "$@"; REPO_URL_OVERRIDE="$2"; shift 2 ;;
      --yes|-y) ASSUME_YES=1; shift ;;
      --no-start) NO_START=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown argument: $1 (try --help)" ;;
    esac
  done
  [[ -n "$REPO_URL_OVERRIDE" ]] && REPO_URL="$REPO_URL_OVERRIDE"
  [[ -n "$INDEX_URL" ]] && export UV_DEFAULT_INDEX="$INDEX_URL"
  [[ -n "$PYTHON_MIRROR" ]] && export UV_PYTHON_INSTALL_MIRROR="$PYTHON_MIRROR"
  if [[ -z "$DIR" ]]; then
    case "$COMMAND" in
      service|start|status) DIR="/opt/dr-panda-mcp" ;;
      install)
        if [[ "${METHOD:-source}" == "pypi" ]]; then
          DIR="/opt/dr-panda-mcp"
        elif [[ -f "$REPO_ROOT/pyproject.toml" ]]; then
          DIR="$REPO_ROOT"
        else
          DIR="/opt/dr-panda-mcp"
        fi
        ;;
      *)
        if [[ -f "$REPO_ROOT/pyproject.toml" ]]; then DIR="$REPO_ROOT"; else DIR="/opt/dr-panda-mcp"; fi
        ;;
    esac
  fi
  if [[ "$DIR" != /* ]]; then DIR="$(pwd)/$DIR"; fi
  DIR="${DIR%/}"
  if [[ -n "$EXTRAS" ]]; then
    validate_extras "$EXTRAS"
  fi
}

validate_extras() {
  local raw="$1" item
  [[ "$raw" == "all" ]] && return 0
  IFS=',' read -r -a items <<< "$raw"
  [[ ${#items[@]} -gt 0 ]] || die "empty --extras"
  for item in "${items[@]}"; do
    [[ -n "$item" ]] || die "empty item in --extras"
    [[ " $VALID_EXTRAS " == *" $item "* ]] || die "unsupported extra: $item"
  done
}

extras_package_name() {
  local raw="$1"
  if [[ "$raw" == "all" ]]; then
    printf '%s[mysql,postgres,mongo,redis,kafka,cls]' "dr-panda-mcp"
  elif [[ -z "$raw" ]]; then
    printf '%s' "dr-panda-mcp"
  else
    printf 'dr-panda-mcp[%s]' "$raw"
  fi
}

source_dir() {
  if [[ -f "$DIR/pyproject.toml" && -d "$DIR/src/dr_panda_mcp" ]]; then
    return 0
  fi
  return 1
}

current_method() {
  [[ -f "$DIR/.drpanda-method" ]] && cat "$DIR/.drpanda-method" || true
}

save_method() {
  local method="$1"
  printf '%s\n' "$method" > "$DIR/.drpanda-method"
  chmod 600 "$DIR/.drpanda-method"
}

save_meta() {
  local extras="${1:-}" version="${2:-}"
  printf '%s\n' "$extras" > "$DIR/.drpanda-extras"
  printf '%s\n' "$version" > "$DIR/.drpanda-version"
  printf '%s\n' "$DEV" > "$DIR/.drpanda-dev"
  chmod 600 "$DIR/.drpanda-extras" "$DIR/.drpanda-version" "$DIR/.drpanda-dev"
}

file_mode() {
  if is_linux || [[ "$(uname -s)" == "Darwin" ]]; then
    stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null || true
  else
    printf ''
  fi
}

env_value() {
  local key="$1" file="$2"
  [[ -f "$file" ]] || return 0
  sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

configured_host() {
  local value="${DR_PANDA_HOST:-}"
  [[ -n "$value" ]] || value="$(env_value DR_PANDA_HOST "$DIR/.env")"
  printf '%s' "${value:-127.0.0.1}"
}

configured_port() {
  local value="${DR_PANDA_PORT:-}"
  [[ -n "$value" ]] || value="$(env_value DR_PANDA_PORT "$DIR/.env")"
  printf '%s' "${value:-8111}"
}

health_host() {
  local host
  host="$(configured_host)"
  if is_loopback "$host" || [[ "$host" == "0.0.0.0" || "$host" == "::" ]]; then
    printf '127.0.0.1'
  else
    printf '%s' "$host"
  fi
}

install_uv() {
  if have uv; then
    info "uv found: $(uv --version)"
    ensure_service_uv
    return 0
  fi
  warn "uv not found"
  if [[ "$ASSUME_YES" -ne 1 ]]; then
    printf 'Install uv from https://astral.sh/uv/install.sh? [y/N] ' >&2
    local answer
    read -r answer || true
    [[ "$answer" == "y" || "$answer" == "Y" ]] || die "uv is required; install it and re-run"
  fi
  have curl || die "curl is required to install uv"
  info "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  have uv || die "uv installation did not put uv on PATH; add ~/.local/bin to PATH"
  ensure_service_uv
}

ensure_service_uv() {
  # systemd does not inherit the root installer PATH; make uv reachable by the
  # dedicated service user without exposing /root.
  if [[ "$EUID" -ne 0 ]]; then
    return 0
  fi
  local uv_path target=/usr/local/bin/uv
  uv_path="$(command -v uv 2>/dev/null || true)"
  if [[ -z "$uv_path" && -x /root/.local/bin/uv ]]; then
    uv_path=/root/.local/bin/uv
  fi
  [[ -n "$uv_path" ]] || return 0
  [[ "$uv_path" == "$target" ]] && return 0
  install -m 0755 "$uv_path" "$target"
  info "uv available to service: $target"
}

ensure_git() {
  have git || die "git is required for --method source"
}

select_python() {
  local candidate version
  if [[ "$PYTHON_SPEC" != "auto" ]]; then
    [[ -x "$PYTHON_SPEC" ]] || die "Python interpreter is not executable: $PYTHON_SPEC"
    printf '%s' "$PYTHON_SPEC"
    return 0
  fi
  for candidate in /usr/bin/python3.12 /usr/bin/python3.11 "$(command -v python3 2>/dev/null || true)"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    version="$("$candidate" -c 'import sys; print("%d%02d" % sys.version_info[:2])' 2>/dev/null || true)"
    if [[ "$version" =~ ^[0-9]+$ ]] && (( version >= 311 )); then
      printf '%s' "$candidate"
      return 0
    fi
  done
  # No system Python >=3.11. Keep uv-managed Python outside /root when root,
  # otherwise the service user cannot execute the venv interpreter.
  if [[ "$EUID" -eq 0 ]]; then
    export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/uv-python}"
    mkdir -p "$UV_PYTHON_INSTALL_DIR"
    chmod 755 "$UV_PYTHON_INSTALL_DIR"
  fi
  info "No system Python >=3.11 found; installing uv-managed Python 3.11"
  uv python install 3.11
  version="$(uv python find 3.11 2>/dev/null || true)"
  [[ -n "$version" && -x "$version" ]] || die "could not locate uv-managed Python 3.11"
  if [[ "$EUID" -eq 0 && "$UV_PYTHON_INSTALL_DIR" == /opt/* ]]; then
    chmod -R a+rX "$UV_PYTHON_INSTALL_DIR"
  fi
  printf '%s' "$version"
}

ensure_dir() {
  mkdir -p "$DIR"
}

ensure_env_file() {
  if [[ -f "$DIR/.env" ]]; then
    info ".env already exists; not overwriting"
    return 0
  fi
  local example="$REPO_ROOT/.env.example"
  if [[ -f "$example" ]]; then
    cp "$example" "$DIR/.env"
  else
    cat > "$DIR/.env" <<'ENV'
# DrPanda MCP environment. The service loads ./.env automatically.
# Defaults: 127.0.0.1:8111, SQLite, data/ under this directory.
# DR_PANDA_HOST="0.0.0.0"
# DR_PANDA_PORT="8111"
# DR_PANDA_PUBLIC_URL="https://mcp.example.com"
# DR_PANDA_LOG_LEVEL="INFO"
# DR_PANDA_COOKIE_SECURE="auto"
# DR_PANDA_TRUSTED_HOSTS="mcp.example.com"
# DR_PANDA_SECRET_KEY=""
ENV
  fi
  chmod 600 "$DIR/.env"
  info "created .env (mode 600)"
}

ensure_data_dir() {
  mkdir -p "$DIR/data"
  chmod 700 "$DIR/data"
}

install_source() {
  ensure_git
  install_uv
  PYTHON_BIN="$(select_python)"
  ensure_dir
  if [[ -e "$DIR/.venv/bin/python" ]]; then
    local existing_python
    existing_python="$(readlink -f "$DIR/.venv/bin/python" 2>/dev/null || true)"
    if [[ "$existing_python" == /root/* ]]; then
      die "existing venv uses /root ($existing_python); remove $DIR/.venv and rerun (data is unaffected)"
    fi
  fi
  if ! source_dir; then
    if [[ -n "$(ls -A "$DIR" 2>/dev/null || true)" ]]; then
      die "$DIR is not empty and is not a DrPanda MCP source checkout"
    fi
    info "Cloning $REPO_URL -> $DIR"
    git clone "$REPO_URL" "$DIR"
  fi
  cd "$DIR"
  local args=(--python "$PYTHON_BIN")
  [[ "$DEV" -eq 1 ]] || args+=(--no-dev)
  if [[ "$EXTRAS" == "all" ]]; then
    args+=(--all-extras)
  elif [[ -n "$EXTRAS" ]]; then
    local item
    IFS=',' read -r -a items <<< "$EXTRAS"
    for item in "${items[@]}"; do args+=(--extra "$item"); done
  fi
  info "uv sync ${args[*]}"
  uv sync "${args[@]}"
  save_method source
  save_meta "$EXTRAS" "source"
  ensure_env_file
  ensure_data_dir
  info "Source installation ready: $DIR"
}

install_pypi() {
  install_uv
  PYTHON_BIN="$(select_python)"
  ensure_dir
  local spec
  spec="$(extras_package_name "$EXTRAS")==${VERSION:-$DEFAULT_VERSION}"
  info "Installing $spec into $DIR/tool (bin: $DIR/bin)"
  UV_TOOL_DIR="$DIR/tool" UV_TOOL_BIN_DIR="$DIR/bin" uv tool install --python "$PYTHON_BIN" --force "$spec"
  save_method pypi
  save_meta "$EXTRAS" "${VERSION:-$DEFAULT_VERSION}"
  ensure_env_file
  ensure_data_dir
  info "PyPI installation ready: $DIR"
}

binary_path() {
  case "$(current_method)" in
    source) printf '%s/.venv/bin/dr-panda-mcp' "$DIR" ;;
    pypi) printf '%s/bin/dr-panda-mcp' "$DIR" ;;
    *) printf '' ;;
  esac
}

check_http() {
  local url="$1"
  have curl || return 2
  curl -fsS --max-time 3 "$url" >/dev/null 2>&1
}

wait_health() {
  local host port url i
  host="$(health_host)"
  port="$(configured_port)"
  url="http://${host}:${port}/healthz"
  for i in $(seq 1 30); do
    if check_http "$url"; then
      info "healthz OK: $url"
      return 0
    fi
    sleep 1
  done
  warn "healthz did not pass: $url"
  return 1
}

first_install_guard() {
  [[ -f "$DIR/data/install.json" ]] && return 0
  if ! is_loopback "$(configured_host)"; then
    fail "first installation must use 127.0.0.1 / localhost; current DR_PANDA_HOST=$(configured_host)"
    return 1
  fi
  return 0
}

service_unit_path() { printf '/etc/systemd/system/%s.service' "$SERVICE_NAME"; }
unit_installed() { [[ -f "$(service_unit_path)" ]]; }

service_exec_start() {
  local binary
  binary="$(binary_path)"
  [[ -n "$binary" ]] || die "unknown installation method in $DIR; run install first"
  [[ -x "$binary" ]] || die "binary not executable: $binary"
  printf '%s' "$binary"
}

assert_service_exec() {
  local binary="$1" interpreter
  [[ -x "$binary" ]] || die "binary is not executable: $binary"
  if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    sudo -u "$SERVICE_USER" test -x "$binary" || die "service user $SERVICE_USER cannot execute $binary"
    if head -1 "$binary" | grep -q '^#!'; then
      interpreter="$(head -1 "$binary" | sed 's/^#!//' | awk '{print $1}')"
      if [[ -n "$interpreter" && "$interpreter" != "/usr/bin/env" ]]; then
        sudo -u "$SERVICE_USER" test -x "$interpreter" || die "service user $SERVICE_USER cannot execute interpreter: $interpreter"
      fi
    fi
  fi
  if [[ -f "$DIR/.venv/bin/python" ]]; then
    interpreter="$(readlink -f "$DIR/.venv/bin/python" 2>/dev/null || true)"
    if [[ "$interpreter" == /root/* ]]; then
      die "venv Python points into /root ($interpreter); rebuild the venv with a system or shared Python"
    fi
  fi
}

install_service() {
  is_linux || die "systemd service installation is only supported on Linux"
  have systemctl || die "systemctl not found"
  is_root || die "run this command as root (sudo ./scripts/setup.sh service --dir $DIR)"
  local method binary unit tmp_dir tmpfile service_group
  method="$(current_method)"
  [[ -n "$method" ]] || die "no DrPanda installation found in $DIR; run install first"
  binary="$(service_exec_start)"
  if [[ "$DIR" == *[[:space:]]* ]]; then
    die "service directory must not contain whitespace: $DIR"
  fi
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    info "creating system user $SERVICE_USER"
    useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  service_group="$(id -gn "$SERVICE_USER")"
  info "setting ownership: $DIR -> $SERVICE_USER:$service_group"
  chown -R "$SERVICE_USER:$service_group" "$DIR"
  [[ -f "$DIR/.env" ]] && chmod 600 "$DIR/.env"
  [[ -d "$DIR/data" ]] && chmod 700 "$DIR/data"
  assert_service_exec "$binary"
  ensure_service_uv
  local write_paths="$DIR/data"
  [[ -d "$DIR/.venv" ]] && write_paths+=" $DIR/.venv"
  [[ -f "$DIR/uv.lock" ]] && write_paths+=" $DIR/uv.lock"
  tmp_dir="$(mktemp -d)"
  tmpfile="$tmp_dir/unit"
  {
    cat <<EOF
[Unit]
Description=DrPanda MCP
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$service_group
WorkingDirectory=$DIR
ExecStart=$binary
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=UV_CACHE_DIR=$DIR/data/.uv-cache
ReadWritePaths=$write_paths
UMask=0077
EOF
    if [[ "$DIR" != /home/* ]]; then
      printf 'ProtectHome=true\n'
    fi
    cat <<EOF

[Install]
WantedBy=multi-user.target
EOF
  } > "$tmpfile"
  install -m 0644 "$tmpfile" "$(service_unit_path)"
  rm -rf "$tmp_dir"
  systemctl daemon-reload
  if have systemd-analyze; then
    systemd-analyze verify "$(service_unit_path)" || die "systemd unit verification failed"
  fi
  if [[ "$NO_START" -eq 1 ]]; then
    systemctl enable "$SERVICE_NAME"
    info "service enabled but not started (--no-start)"
    return 0
  fi
  if ! first_install_guard; then
    systemctl enable "$SERVICE_NAME"
    warn "service enabled but not started; complete first installation on loopback, then run: systemctl start $SERVICE_NAME"
    return 1
  fi
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME" || die "systemctl restart $SERVICE_NAME failed"
  sleep 1
  systemctl is-active --quiet "$SERVICE_NAME" || {
    systemctl status "$SERVICE_NAME" --no-pager -l || true
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
    die "service failed to start"
  }
  wait_health || {
    systemctl status "$SERVICE_NAME" --no-pager -l || true
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
    die "service failed health check"
  }
  info "service installed and healthy: $SERVICE_NAME"
}

start_app() {
  local binary url
  binary="$(binary_path)"
  [[ -n "$binary" ]] || die "no DrPanda installation found in $DIR"
  [[ -x "$binary" ]] || die "binary not executable: $binary"
  cd "$DIR"
  first_install_guard || exit 1
  url="http://$(health_host):$(configured_port)/"
  if unit_installed; then
    is_root || die "run as root to start the systemd service: sudo systemctl start $SERVICE_NAME"
    systemctl restart "$SERVICE_NAME" || die "systemctl restart $SERVICE_NAME failed"
    wait_health || {
      systemctl status "$SERVICE_NAME" --no-pager -l || true
      journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
      exit 1
    }
    info "service running: $SERVICE_NAME"
    return 0
  fi
  info "no systemd service found; starting in foreground"
  info "open: $url"
  if is_loopback "$(configured_host)"; then
    info "headless server: ssh -L $(configured_port):127.0.0.1:$(configured_port) <user>@<server>"
  fi
  exec "$binary"
}

status_app() {
  info "directory: $DIR"
  info "method: $(current_method || true)"
  info "binary: $(binary_path)"
  info "listen: $(configured_host):$(configured_port)"
  if unit_installed; then
    systemctl status "$SERVICE_NAME" --no-pager || true
  fi
  if check_http "http://$(health_host):$(configured_port)/healthz"; then
    info "healthz: OK"
  else
    warn "healthz: not reachable"
  fi
}

check_port() {
  local port="$1"
  if ! [[ "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    fail "invalid port: $port"; return
  fi
  if have nc; then
    if nc -z 127.0.0.1 "$port" >/dev/null 2>&1; then
      warn "port $port is already in use"
    fi
  elif (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1; then
    warn "port $port is already in use"
  fi
}

check_environment() {
  local failures=0 warnings=0 method host port mode env_mode key missing
  info "DrPanda MCP environment check"
  info "OS: $(uname -s) $(uname -m)"
  info "directory: $DIR"
  method="$(current_method)"
  if [[ -n "$method" ]]; then
    info "installation method: $method"
  else
    warn "no installation marker in $DIR"; warnings=$((warnings+1))
  fi
  for cmd in curl git; do
    if have "$cmd"; then info "$cmd: $(command -v "$cmd")"; else warn "$cmd not found"; warnings=$((warnings+1)); fi
  done
  if have uv; then info "uv: $(uv --version)"; else warn "uv not found (install requires it)"; warnings=$((warnings+1)); fi
  if is_linux; then
    if have systemctl; then info "systemd: available"; else warn "systemd not available"; warnings=$((warnings+1)); fi
  fi
  host="$(configured_host)"; port="$(configured_port)"
  info "listen: $host:$port"
  check_port "$port"
  if [[ -f "$DIR/.env" ]]; then
    env_mode="$(file_mode "$DIR/.env")"
    if [[ "$env_mode" =~ ^[0-7]*[0-7]$ && $((8#$env_mode & 8#077)) -ne 0 ]]; then
      fail ".env mode $env_mode is too open (chmod 600)"; failures=$((failures+1))
    else
      info ".env mode: $env_mode"
    fi
  else
    warn ".env not found (install creates it)"; warnings=$((warnings+1))
  fi
  if [[ -d "$DIR/data" ]]; then
    for key in install.json install.key session.key secret.key; do
      [[ -e "$DIR/data/$key" ]] || { warn "missing data/$key"; warnings=$((warnings+1)); }
    done
  else
    warn "data/ not found"; warnings=$((warnings+1))
  fi
  if [[ ! -f "$DIR/data/install.json" ]] && ! is_loopback "$host"; then
    fail "first installation requires loopback listen address, current: $host"; failures=$((failures+1))
  fi
  if [[ -n "$method" && ! -x "$(binary_path)" ]]; then
    fail "installed binary is missing/not executable: $(binary_path)"; failures=$((failures+1))
  elif [[ -n "$method" && -x "$(binary_path)" ]]; then
    local interp
    interp="$(head -1 "$(binary_path)" 2>/dev/null | sed 's/^#!//' | awk '{print $1}')"
    if [[ -n "$interp" && "$interp" != "/usr/bin/env" ]]; then
      if [[ "$interp" == /root/* ]]; then
        fail "binary interpreter points into /root ($interp)"; failures=$((failures+1))
      elif [[ "$(id -u "$SERVICE_USER" 2>/dev/null || echo 1)" != "1" ]] && ! sudo -u "$SERVICE_USER" test -x "$interp" 2>/dev/null; then
        fail "service user $SERVICE_USER cannot execute interpreter $interp"; failures=$((failures+1))
      fi
    fi
  fi
  if [[ -f "$DIR/.venv/bin/python" ]]; then
    local venv_python
    venv_python="$(readlink -f "$DIR/.venv/bin/python" 2>/dev/null || true)"
    if [[ "$venv_python" == /root/* ]]; then
      fail "venv Python points into /root ($venv_python); the service user cannot execute it"; failures=$((failures+1))
    else
      info "venv Python: $venv_python"
    fi
  fi
  if [[ -n "$method" && -e "$(binary_path)" && "$(id -u "$SERVICE_USER" 2>/dev/null || echo 1)" != "1" ]]; then
    if ! sudo -u "$SERVICE_USER" test -x "$(binary_path)" 2>/dev/null; then
      fail "service user $SERVICE_USER cannot execute $(binary_path)"; failures=$((failures+1))
    fi
  fi
  if unit_installed; then
    if have systemd-analyze; then
      if ! systemd-analyze verify "$(service_unit_path)" >/dev/null 2>&1; then
        fail "systemd unit verification failed: $(service_unit_path)"; failures=$((failures+1))
      else
        info "systemd unit: valid"
      fi
    fi
    if have systemctl; then
      if systemctl is-active --quiet "$SERVICE_NAME"; then info "service: active"; else warn "service: inactive"; warnings=$((warnings+1)); fi
    fi
  fi
  if [[ "$failures" -gt 0 ]]; then
    log ""
    fail "check finished with $failures failure(s), $warnings warning(s)"
    return 1
  fi
  log ""
  info "check finished with $warnings warning(s)"
}

upgrade_app() {
  local method extras version
  method="$(current_method)"
  [[ -n "$method" ]] || die "no DrPanda installation found in $DIR"
  extras="$(cat "$DIR/.drpanda-extras" 2>/dev/null || true)"
  version="${VERSION:-latest}"
  if [[ -d "$DIR/data" ]]; then
    warn "back up $DIR/data and the four key/install files before upgrading"
  fi
  case "$method" in
    source)
      ensure_git; install_uv
      git -C "$DIR" pull --ff-only
      cd "$DIR"
      local args=(--python "${PYTHON_BIN:-$(select_python)}")
      [[ "$(cat "$DIR/.drpanda-dev" 2>/dev/null || echo 0)" -eq 1 ]] || args+=(--no-dev)
      if [[ "$extras" == "all" ]]; then args+=(--all-extras)
      elif [[ -n "$extras" ]]; then local item; IFS=',' read -r -a items <<< "$extras"; for item in "${items[@]}"; do args+=(--extra "$item"); done; fi
      uv sync "${args[@]}"
      save_meta "$extras" source
      ;;
    pypi)
      install_uv
      PYTHON_BIN="$(select_python)"
      local spec
      if [[ -n "$VERSION" ]]; then
        spec="$(extras_package_name "$extras")==$VERSION"
      else
        spec="$(extras_package_name "$extras")"
      fi
      UV_TOOL_DIR="$DIR/tool" UV_TOOL_BIN_DIR="$DIR/bin" uv tool install --python "$PYTHON_BIN" --force "$spec"
      save_meta "$extras" "${VERSION:-latest}"
      ;;
    *) die "unknown installation method: $method" ;;
  esac
  if unit_installed; then
    is_root || die "run as root to restart the service: sudo systemctl restart $SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    wait_health || die "upgrade finished but health check failed"
  else
    info "upgrade finished; restart the process/foreground service as needed"
  fi
}

main() {
  parse_args "$@"
  case "$COMMAND" in
    check) check_environment ;;
    install)
      case "${METHOD:-source}" in
        source) install_source ;;
        pypi) install_pypi ;;
        *) die "--method must be source or pypi" ;;
      esac
      ;;
    service) install_service ;;
    start) start_app ;;
    status) status_app ;;
    upgrade) upgrade_app ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
