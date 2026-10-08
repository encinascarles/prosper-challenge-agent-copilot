# tools/wt/lib.sh: shared by tools/wt/* (sourced, never run). Sets $root (the main checkout, the folder that holds
# the shared .git) and $base (the branch PRs target: main), and defines fetch_base, copy_config, install_backend and
# install_frontend. Prints paths and counts only, never a value of a copied file.
common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
  || { echo "wt: run it inside this repo" >&2; exit 1; }
root="$(cd "$common/.." && pwd -P)"
base="main"

# fetch_base: refresh origin/main only. Parallel threads fetch at the same moment and git then fails with
# "cannot lock ref", so retry with a short backoff.
fetch_base() {
  _i=0
  until git -C "$root" fetch --quiet --no-write-fetch-head origin "$base" 2>/dev/null; do
    _i=$((_i + 1))
    [ "$_i" -lt 5 ] || { git -C "$root" fetch --quiet --no-write-fetch-head origin "$base"; return; }
    sleep "$_i"
  done
}

# copy_config <worktree>: copy the gitignored local files listed in .worktreeinclude (backend/.env) from the main
# checkout into <worktree>, only the ones it does not have yet (never overwrites). Prints how many it copied.
copy_config() {
  _wt="$1"; _n=0
  _list="$_wt/.worktreeinclude"; [ -f "$_list" ] || _list="$root/.worktreeinclude"
  [ -f "$_list" ] || { echo 0; return 0; }
  while IFS= read -r _pat; do
    case "$_pat" in ""|"#"*) continue ;; esac
    for _f in $(cd "$root" && ls -d $_pat 2>/dev/null); do
      [ -f "$root/$_f" ] || continue
      [ ! -e "$_wt/$_f" ] || continue
      git -C "$_wt" check-ignore -q "$_f" || { echo "wt: skipped $_f (not gitignored)" >&2; continue; }
      mkdir -p "$(dirname "$_wt/$_f")"
      cp -p "$root/$_f" "$_wt/$_f"
      _n=$((_n + 1))
    done
  done < "$_list"
  echo "$_n"
}

# install_backend <worktree>: backend/.venv from uv.lock. uv links from its cache, so it takes seconds.
install_backend() {
  _t0=$(date +%s)
  uv sync --quiet --frozen --directory "$1/backend" || { echo "wt: uv sync failed" >&2; return 1; }
  echo "deps     backend/.venv ready ($(( $(date +%s) - _t0 ))s)"
}

# install_frontend <worktree>: frontend/node_modules. Same package-lock.json as the main checkout: an APFS clone of
# its node_modules (cp -c: seconds, almost no disk). Otherwise, or when the clone is not possible (another disk),
# npm ci. The clone is built next to its final place and renamed in when complete, so two runs at once (T3's setup
# and the agent) never see half of one.
install_frontend() {
  _fe="$1/frontend"; _t0=$(date +%s)
  if [ -e "$_fe/node_modules" ]; then
    echo "deps     frontend/node_modules present"; return 0
  fi
  if [ "$1" != "$root" ] && [ -d "$root/frontend/node_modules" ] \
     && cmp -s "$root/frontend/package-lock.json" "$_fe/package-lock.json"; then
    _tmp="$_fe/.node_modules-clone-$$"
    rm -rf "$_tmp"
    if cp -cR "$root/frontend/node_modules" "$_tmp" 2>/dev/null \
       && python3 -c 'import os, sys; os.rename(sys.argv[1], sys.argv[2])' "$_tmp" "$_fe/node_modules" 2>/dev/null; then
      echo "deps     frontend/node_modules cloned from the main checkout ($(( $(date +%s) - _t0 ))s)"; return 0
    fi
    rm -rf "$_tmp"
    [ ! -d "$_fe/node_modules" ] || { echo "deps     frontend/node_modules present (another run finished first)"; return 0; }
    echo "deps     could not clone node_modules (another disk?): installing instead"
  fi
  (cd "$_fe" && npm ci --prefer-offline --no-audit --no-fund --loglevel=error >/dev/null) \
    || { echo "wt: npm ci failed" >&2; return 1; }
  echo "deps     npm ci in frontend/ ($(( $(date +%s) - _t0 ))s)"
}
