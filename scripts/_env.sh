# Load the repository's local .env for the development runner, without executing it.
# Existing exported variables win. Supported syntax is KEY=VALUE, with optional
# single/double quotes and `export ` prefixes; no shell expansion is performed.

if [ -f "$ROOT/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue

    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[2]}"
      value="${BASH_REMATCH[3]}"
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"

      if [ "${#value}" -ge 2 ]; then
        if { [ "${value:0:1}" = '"' ] && [ "${value: -1}" = '"' ]; } || \
           { [ "${value:0:1}" = "'" ] && [ "${value: -1}" = "'" ]; }; then
          value="${value:1:${#value}-2}"
        fi
      fi

      # An explicitly exported shell value is more specific than the file.
      if printenv "$key" >/dev/null 2>&1; then continue; fi
      printf -v "$key" '%s' "$value"
      export "$key"
    else
      echo "warning: ignoring an invalid .env line (expected KEY=VALUE)" >&2
    fi
  done < "$ROOT/.env"
fi
