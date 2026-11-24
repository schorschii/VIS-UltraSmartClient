# Debian package

Build from any working directory, without root:

```sh
./installer/debian/build.sh
# Optional:
./installer/debian/build.sh --version 0.1.0-2 --output-dir /tmp/packages
```

Build requirements: standard Debian shell utilities and `dpkg` (`dpkg-deb`).
Python 3.11+ is used only to read the default version from TOML; passing
`--version` avoids Python entirely. No pip, venv, network access, or application
dependencies are needed to build.
The default version comes from `pyproject.toml`, with Debian revision `-1`.
`SOURCE_DATE_EPOCH` can be set to normalize staged file timestamps.

The result is `dist/ultrasmartclient_VERSION_all.deb`. Install using apt so
runtime dependencies are resolved:

```sh
sudo apt install ./dist/ultrasmartclient_0.1.0-1_all.deb
ultrasmartclient
```

Files installed:

- `/usr/share/ultrasmartclient/ultrasmartclient/`: Python source and icon assets.
- `/usr/bin/ultrasmartclient`: launcher using `/usr/bin/python3` and the installed source.
- `/usr/share/applications/ultrasmartclient.desktop`: application menu entry.
- `/usr/share/pixmaps/ultrasmartclient.png`: desktop icon.
- `/usr/share/doc/ultrasmartclient/`: README and API documentation.

`CONTROL` is the checked-in template for the package's required `DEBIAN/control`
file. It declares all direct Python dependencies with the version bounds from
`pyproject.toml`, plus Qt SVG support. Their Debian packages supply transitive
libraries. Kerberos command-line tools and Qt translations are recommended.
Older distributions may not provide the required versions; apt will report
unsatisfied dependencies rather than installing packages through pip.

The package contains architecture-independent application code; native Qt and
GSSAPI libraries come from apt. It neither creates a venv nor bundles Python.
Existing personal and `/etc/ultrasmartclient/tenants.json` configurations are
not packaged or overwritten. A Kerberos ticket and tenant configuration are
still needed for server access.

Inspect without installing:

```sh
dpkg-deb --info dist/ultrasmartclient_0.1.0-1_all.deb
dpkg-deb --contents dist/ultrasmartclient_0.1.0-1_all.deb
```
