# XKernel Core

← [Index](../README.md)

XKernel is an MCUB kernel variant built on top of `core.kernel.standard.Kernel`. It does not replace the MCUB loader model. Instead, it adds a small patch manager that discovers Python patch files, waits for matching modules, and applies the patches at runtime.

## Core Contract

MCUB loads custom cores from `core/kernel/`. XKernel follows the standard custom core contract:

| Requirement | Value |
|-------------|-------|
| Core file | `core/kernel/XKernel.py` |
| Exported class | `Kernel` |
| Base class | `core.kernel.standard.Kernel` |
| Startup method | `async def run(self)` |

Activate it manually:

```bash
python3 -m core --core XKernel
```

Set it as the default core from the manager installer:

```MCUB
.xkinstall --default
```

## Runtime Additions

XKernel exposes the patch manager through several equivalent attributes:

| Attribute | Description |
|-----------|-------------|
| `kernel.patch_manager` | Main `XPatchPatchManager` instance |
| `kernel.xpatch` | Short alias for the patch manager |
| `kernel.patches` | Compatibility alias for the patch manager |

The default patch directory is:

```text
patches/
```

The directory is created during core setup if it does not exist.

## Version Markers

When XKernel is active, the core marks itself at runtime:

| Marker | Description |
|--------|-------------|
| `kernel.CORE_NAME` | Set to `XPatchKernel` during startup |
| `kernel.VERSION` | Standard MCUB version with `.XPatch` suffix |
| `kernel.ver` | Same visible version string |
| `kernel.VERSION_XKERNEL` | XKernel release tuple used by the manager update check |

These markers are used by the manager to detect the active core and compare installed and remote versions.

## Stealth Mode

The manager can enable stealth mode from its settings. Stealth mode keeps the patch hooks active but hides XKernel-specific runtime markers:

| Normal mode | Stealth mode |
|-------------|--------------|
| `CORE_NAME = "XPatchKernel"` | `CORE_NAME = "standard"` |
| `VERSION` has `.XPatch` suffix | `VERSION` is restored to the base version |
| `VERSION_XKERNEL` exists | `VERSION_XKERNEL` is removed/protected |
| `ver` exists | `ver` is removed/protected |
| XKernel patch API attrs are public | XKernel attrs raise `CallInsecure` on direct access |

In stealth mode, direct access to XKernel-specific attributes such as `patch_manager`,
`xpatch`, `patches`, `apply_patches`, `VERSION_XKERNEL`, `ver`, and internal
`_xpatch_*` state raises MCUB `CallInsecure`. The patch hooks keep working, and
the manager uses internal accessors for its own UI/actions.

Use stealth mode only when a module or integration expects the standard core name or a clean version string.


## ExteraProxy

ExteraProxy is an XKernel runtime feature that can disable selected MCUB safety proxies for chosen user modules, or for all user modules. It can bypass:

- `kernel` - raw kernel instead of `ModuleKernelProxy`;
- `client` - raw Telegram client instead of `ClientProxy` (needed for attributes such as `client.session`);
- `event` - raw event instead of `EventProxy`.

The manager shows the current state on the main page:

- `Принуждёный для всех` - raw kernel is forced for every user module.
- `Принуждёный только для N модулей` - raw kernel is forced only for the configured allowlist.

Use the manager settings page to open `ExteraProxy`, choose scopes, toggle global mode, or add/remove module names with input buttons.

> [!WARNING]
> ExteraProxy is dangerous for unknown or suspicious modules. Disabling safety proxies gives modules direct access to protected kernel/client/event internals. Enable it only for modules you trust and understand.

## Safe Boot Mode

Safe boot starts XKernel without applying patch callbacks. The manager and patch
metadata remain available, so a broken patch can be disabled or inspected before
normal patching is enabled again.

Enable it with an environment variable:

```bash
XKERNEL_SAFE_MODE=1 python3 -m core --core XKernel
```

Or with a startup flag:

```bash
python3 -m core --core XKernel --xpatch-safe
```

Accepted flags are `--xpatch-safe` and `--xkernel-safe`. Accepted environment
variables are `XKERNEL_SAFE_MODE` and `XPATCH_SAFE_MODE`.

## Patch Lifecycle

XKernel installs loader hooks so patches can be applied after normal MCUB modules are loaded. The patch manager tracks four states:

| State | Meaning |
|-------|---------|
| `applied` | Patch callback ran successfully for a target |
| `pending` | Patch was loaded, but the target module is not available yet |
| `failed` | Patch import or callback raised an exception |
| `skipped` | Patch was already applied and `force` was not requested |
| `disabled` | Patch is present but disabled by the manager |

Manual helpers are available from the kernel:

```python
await kernel.apply_patches()
await kernel.apply_patches(target_name="OpenApp", force=True)
await kernel.apply_patches_for_module("OpenApp")
```

The manager patch detail page can reload a patch, unapply it when an
`unapply_patch` callback exists, disable or enable it, and show full traceback
details for failed callbacks. It also shows XKernel compatibility information
when `PATCH_REQUIRES_XKERNEL` is declared.

## Removal Flow

The manager `Utils` page includes an XKernel removal flow. It lets you choose
what to remove before executing anything:

- XKernel core file;
- all XKernel core backups;
- the manager module;
- all patch files;
- reset the default core to `standard`;
- restart MCUB automatically.

The removal order is: core file, backups, patches, default core reset, manager
module uninstall, then restart.

## Manager Module

`XPatchKernelManager` is a normal MCUB module that installs and manages the core file.
It also checks the remote manager module version with a cached GitHub fetch. If
the installed manager is older than the repository version, the main menu warns
that the manager should be updated; otherwise new runtime features may be
unavailable from the UI.

| Command | Alias | Description |
|---------|-------|-------------|
| `.xm` | `.xmanager`, `.xkm` | Open the inline XKernel manager |
| `.xkinstall` | `.xki` | Download, validate, back up, and install XKernel |
| `.xkinstall --default` | `.xki --default` | Install XKernel and set it as default core |
| `.xkernelrollback` | `.xkr` | Restore the latest backup |

Manager settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `stealth_mode` | `False` | Hide XKernel runtime markers while keeping hooks active |
| `auto_update_kernel` | `False` | Install a newer remote XKernel automatically when detected |
| `update_notifications` | `True` | Send update notices to the log chat or admin target |
| `experimental_patch_events` | `False` | Emit best-effort `xpatch:*` lifecycle events |
| `experimental_patch_hot_reload` | `False` | Watch patch files and hot-reload changed patches |
| `extera_proxy_all` | `False` | Dangerous: disable `ModuleKernelProxy` for all user modules |
| `extera_proxy_modules` | `""` | Comma-separated allowlist of modules with selected proxies disabled |
| `extera_proxy_scopes` | `"kernel"` | Comma-separated ExteraProxy scopes: `kernel`, `client`, `event` |

## Install Flow

The manager install command follows this flow:

1. Download `XKernel.py` from the configured repository.
2. Validate that the source looks like an XKernel core.
3. Read the remote `VERSION_XKERNEL` value when available.
4. Back up the existing `core/kernel/XKernel.py` file.
5. Write the new file atomically.
6. Optionally set `XKernel` as the default core.
7. Ask for an MCUB restart.

Rollback restores the latest backup and also requires a restart.

## Compatibility Notes

- XKernel keeps the standard MCUB module loader and command registration model.
- Patches are plain Python files, not MCUB modules. They should not register commands directly.
- Patch code should be small, targeted, and reversible.
- Avoid changing public MCUB APIs from a patch unless the target module explicitly expects that behavior.
- Do not block the event loop from patch callbacks. Use async code for network or file operations.
