# pj-plugin-registry

The **official extension registry** for the [PlotJuggler](https://github.com/PlotJuggler/PlotJuggler) Marketplace.

---

## What is this?

This repository is the central catalog that the PlotJuggler Marketplace reads to discover available extensions. It contains a single `registry.json` file listing all published extensions with their metadata, download URLs, and SHA256 checksums.

It plays the same role that a package index plays in systems like VS Code's extension marketplace or a Linux package manager: a well-known, static, version-controlled source of truth that clients can query to find, install, update, and uninstall extensions.

---

## How it fits into PlotJuggler

```
┌─────────────────────────────────────┐
│        PlotJuggler (client)         │
│   pj_marketplace — Marketplace UI   │
└──────────────┬──────────────────────┘
               │ fetches registry.json
               ▼
┌─────────────────────────────────────┐
│         pj-plugin-registry          │  ← this repo
│   registry.json — extension catalog │
└──────────────┬──────────────────────┘
               │ download URLs point to
               ▼
┌─────────────────────────────────────┐
│   Extension repos (e.g. GitHub      │
│   Releases, Nextcloud, CDN...)      │
│   ZIP artifacts per platform        │
└─────────────────────────────────────┘
```

The `pj_marketplace` module inside PlotJuggler Core (`RegistryManager`) fetches this registry at startup or on user request, parses it, and presents the available extensions in the Marketplace UI. When the user installs an extension, the client uses the download URL and SHA256 checksum from this registry to securely fetch and verify the correct artifact for the current platform.

---

## Repository structure

```
pj-plugin-registry/
├── README.md
└── registry.json          # Main catalog — lists all available extensions
```

### `registry.json`

The top-level catalog consumed by the PlotJuggler client. Contains the full metadata for every extension: name, description, author, category, version, supported platforms, download URLs, SHA256 checksums, and changelog.

---

## Contributing a new extension or version

This registry is **open to contributions** from any team or individual. New extensions and new versions of existing extensions are accepted through a pull request review process.

### Workflow

```
External developer                  PlotJuggler maintainer
──────────────────                  ──────────────────────
1. Fork this repo
2. Add/update entry in registry.json
3. Open a Pull Request
                                    4. Review the PR:
                                       - Valid JSON schema
                                       - Reachable download URLs
                                       - Correct SHA256 checksums
                                       - Appropriate metadata
                                    5. Approve and merge
                                       → extension goes live
```

### What to include in your PR

1. **A new entry** in the `extensions` array of `registry.json` (for a new extension), or **an updated `version` field** and new platform URLs/checksums (for a new version of an existing extension).
2. **Reachable, stable download URLs** — GitHub Releases are the recommended hosting. The URLs must serve the ZIP directly (not a redirect page).
3. **Correct SHA256 checksums** — one per platform artifact, in the format `sha256:<hex>`.
4. **A brief description** of what the extension does in the `description` field.

### Review criteria

A maintainer will verify that:

- The JSON is valid and conforms to the registry schema (see [Schema reference](#schema-reference)).
- The download URLs are accessible and serve the declared content.
- The checksums match the actual artifacts.
- The extension does not duplicate an existing entry under a different ID.
- The metadata is accurate and appropriate for public listing.

Maintainers may request changes before merging. Once merged, the new entry or version becomes immediately available to all PlotJuggler users.

---

## Supported platforms

Each extension entry in `registry.json` provides download artifacts for:

| Key | Platform |
|---|---|
| `linux-x86_64` | Linux, 64-bit Intel/AMD |
| `linux-arm64` | Linux, 64-bit ARM |
| `windows-x86_64` | Windows, 64-bit Intel/AMD |
| `windows-arm64` | Windows, 64-bit ARM |
| `macos-x86_64` | macOS, Intel |
| `macos-arm64` | macOS, Apple Silicon |

Not all platforms are required — only include the platforms for which you have built and tested the artifact.

---

## Extension categories

| Category | Description |
|---|---|
| `data_loader` | Loads data files into PlotJuggler (CSV, MCAP, ...) |
| `data_streamer` | Streams live data into PlotJuggler (ROS 2, ...) |
| `parser` | Parses raw data into time series (CAN bus, ...) |
| `toolbox` | Adds analysis tools to PlotJuggler (FFT, ...) |
| `bundle` | A single package containing multiple plugins |

---

## Schema reference

The full JSON schema for `registry.json` is defined in:

```
plotjuggler_core/pj_marketplace/documentation/REQUIREMENTS.md
  § 11.1 — Registry JSON Schema
```

---

## Related repositories

| Repository | Role |
|---|---|
| [`PlotJuggler/PlotJuggler`](https://github.com/PlotJuggler/PlotJuggler) | Main application |
| `plotjuggler_core/pj_marketplace` | Marketplace client (RegistryManager, DownloadManager, UI) |
| `pj-test-dummy-plugins` | Example/test plugins used during marketplace development |
