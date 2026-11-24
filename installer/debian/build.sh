#!/bin/sh
# Build without root, pip, venv, or installed application dependencies.
set -eu

packaging=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$packaging/../.." && pwd)
version=
output_dir="$root/dist"

usage() {
    echo "Usage: $0 [--version VERSION] [--output-dir DIRECTORY]"
    echo 'Defaults: project version plus -1; output in repository dist/.'
}
fail() {
    echo "$*" >&2
    exit 1
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version|--output-dir)
            [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1"
            case "$1" in
                --version) version=$2 ;;
                --output-dir) output_dir=$2 ;;
            esac
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown argument: $1" ;;
    esac
done
command -v dpkg-deb >/dev/null 2>&1 || fail 'dpkg-deb is required (install the dpkg package).'
if [ -z "$version" ]; then
    # Python is only needed to parse TOML, not to assemble the package.
    version=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"] + "-1")' "$root/pyproject.toml")
fi
case "$version" in
    [!0-9]*|*[!A-Za-z0-9.+~-]*) fail 'Invalid Debian version (epochs are not supported).' ;;
esac
dpkg --validate-version "$version"
mkdir -p -- "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)
output="$output_dir/ultrasmartclient_${version}_all.deb"
temporary=$(mktemp -d -t ultrasmartclient-deb-XXXXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
stage="$temporary/package"
app="$stage/usr/share/ultrasmartclient/ultrasmartclient"
mkdir -p -- "$app"

# Copy only source and image assets, excluding caches and local configuration.
cd -- "$root/ultrasmartclient"
find . -type d -name __pycache__ -prune -o -type f \
    \( -name '*.py' -o \( -path './assets/*' \( -name '*.svg' -o -name '*.png' \) \) \) \
    -exec sh -c '
        app=$1
        shift
        for source do
            install -D -m 644 -- "$source" "$app/$source"
        done
    ' sh "$app" {} +
install -D -m 755 "$packaging/ultrasmartclient" "$stage/usr/bin/ultrasmartclient"
install -D -m 644 "$packaging/ultrasmartclient.desktop" "$stage/usr/share/applications/ultrasmartclient.desktop"
install -D -m 644 assets/icons/app.png "$stage/usr/share/pixmaps/ultrasmartclient.png"
for name in README.md VAPI.md; do
    install -D -m 644 "$root/$name" "$stage/usr/share/doc/ultrasmartclient/$name"
done
size=$(du -sk "$stage" | cut -f1)
mkdir -p "$stage/DEBIAN"
sed -e "s/@VERSION@/$version/g" -e "s/@INSTALLED_SIZE@/$size/g" \
    "$packaging/CONTROL" > "$stage/DEBIAN/control"
chmod 644 "$stage/DEBIAN/control"
find "$stage" -type d -exec chmod 755 {} +
if [ "${SOURCE_DATE_EPOCH+x}" ]; then
    find "$stage" -exec touch -d "@$SOURCE_DATE_EPOCH" {} +
fi
dpkg-deb --root-owner-group --build "$stage" "$output"
echo "$output"
