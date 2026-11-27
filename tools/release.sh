#!/usr/bin/env bash
# Publica uma versão nova para os usuários (o app mostra "Nova versão disponível").
#   1) edite my-gui/VERSION (ex.: 1.1.0), faça commit e merge na main
#   2) na main atualizada:  tools/release.sh ["notas da versão"]
# Cria a tag vX.Y.Z e a release no GitHub com my-gui-X.Y.Z.tar.gz + .sha256 (precisa do `gh` logado).
set -euo pipefail
cd "$(dirname "$0")/.."
ver="$(tr -d '[:space:]' < my-gui/VERSION)"
[[ $ver =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "my-gui/VERSION inválido: '$ver'"; exit 1; }
tag="v$ver"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "Rode na branch main."; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Há alterações não commitadas."; exit 1; }
git fetch -q origin main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "A main local difere de origin/main."; exit 1; }
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && { echo "A tag $tag já existe; aumente o VERSION."; exit 1; }

out="$(mktemp -d)"; trap 'rm -rf "$out"' EXIT
pkg="my-gui-$ver.tar.gz"
# só os arquivos que o app sabe instalar (a lista é a mesma de UPDATE_FILES no server.py)
git archive --format=tar.gz -o "$out/$pkg" HEAD bin/my my-gui/server.py my-gui/index.html my-gui/my-gui.svg my-gui/VERSION
(cd "$out" && sha256sum "$pkg" > "$pkg.sha256")
cat "$out/$pkg.sha256"

git tag -a "$tag" -m "my-gui $ver"
git push origin "$tag"
if [ $# -gt 0 ]; then notes=(--notes "$1"); else notes=(--generate-notes); fi
gh release create "$tag" "$out/$pkg" "$out/$pkg.sha256" --title "my-gui $ver" "${notes[@]}"
echo "Release $tag publicada."
