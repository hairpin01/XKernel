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
| `VERSION_XKERNEL` exists | `VERSION_XKERNEL` is removed |
| `ver` exists | `ver` is removed |

Use stealth mode only when a module or integration expects the standard core name or a clean version string.

## Patch Lifecycle

XKernel installs loader hooks so patches can be applied after normal MCUB modules are loaded. The patch manager tracks four states:

| State | Meaning |
|-------|---------|
| `applied` | Patch callback ran successfully for a target |
| `pending` | Patch was loaded, but the target module is not available yet |
| `failed` | Patch import or callback raised an exception |
| `skipped` | Patch was already applied and `force` was not requested |

Manual helpers are available from the kernel:

```python
await kernel.apply_patches()
await kernel.apply_patches(target_name="OpenApp", force=True)
await kernel.apply_patches_for_module("OpenApp")
```

## Manager Module

`XPatchKernelManager` is a normal MCUB module that installs and manages the core file.

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
