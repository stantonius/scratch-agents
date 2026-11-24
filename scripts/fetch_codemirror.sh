#!/usr/bin/env bash
# Fetch the CodeMirror 5 editor (MIT licence) and build the three files Polya serves from polya/static/vendor.
# Polya loads nothing from a CDN at run time, so these have to be on disk. Run once, from the project folder:
#     bash scripts/fetch_codemirror.sh
# Needs curl and tar. The package comes from the npm registry; set CODEMIRROR_TGZ to a local copy of
# codemirror-5.65.21.tgz to use that instead (for a machine with no route to registry.npmjs.org).
set -euo pipefail
VERSION=5.65.21
cd "$(dirname "$0")/.."
V=polya/static/vendor
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
if [ -n "${CODEMIRROR_TGZ:-}" ]; then cp "$CODEMIRROR_TGZ" "$TMP/cm.tgz"
else curl -fsSL "https://registry.npmjs.org/codemirror/-/codemirror-$VERSION.tgz" -o "$TMP/cm.tgz"; fi
tar -xzf "$TMP/cm.tgz" -C "$TMP"
C="$TMP/package"
mkdir -p "$V"
cp "$C/lib/codemirror.js" "$V/codemirror.js"
cp "$C/LICENSE" "$V/codemirror.LICENSE"
cat "$C/lib/codemirror.css" "$C/addon/hint/show-hint.css" > "$V/codemirror.css"
cat "$C/mode/python/python.js" "$C/mode/xml/xml.js" "$C/mode/markdown/markdown.js" "$C/addon/edit/closebrackets.js" \
    "$C/addon/edit/matchbrackets.js" "$C/addon/comment/comment.js" "$C/addon/hint/show-hint.js" > "$V/codemirror-extras.js"
echo "CodeMirror $VERSION installed in $V:"; ls -la "$V"
