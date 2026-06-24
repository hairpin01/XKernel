# Writing XKernel Patches

← [Index](../README.md)

XKernel patches are plain Python files loaded from the `patches/` directory. A patch declares one or more target modules and exposes a callback that mutates or wraps the target after MCUB loads it.

Patches are not regular MCUB modules. They do not have their own command registration lifecycle and should not depend on module headers.

## Directory Layout

```text
patches/
  OpenApp__title.py
  SomeModule__fix_state.py
  group/
    OtherModule__compat.py
```

XKernel scans `patches/` recursively and imports every `.py` file except `__init__.py`.

## Minimal Patch

```python
PATCH_TARGET = "OpenApp"
PATCH_NAME = "OpenAppTitlePatch"


async def apply_patch(kernel, target):
    target.title = "patched"
```

The callback runs after the target module is available. If the target is not loaded yet, the patch is kept as pending and can be applied later when the module appears.

## Target Declaration

A patch can declare targets with any of these names:

```python
PATCH_TARGET = "OpenApp"
patch_target = "OpenApp"
target = "OpenApp"
```

For multiple targets:

```python
PATCH_TARGETS = ["OpenApp", "OtherModule"]
patch_targets = ["OpenApp", "OtherModule"]
targets = ["OpenApp", "OtherModule"]
```

If no target variable is declared, XKernel can use the file name fallback:

```text
OpenApp__anything.py
```

In this case the target is `OpenApp`.

## Target Resolution

XKernel matches targets against loaded MCUB modules and class-style module instances. The following names can match:

| Source | Example |
|--------|---------|
| Registry key | `OpenApp` from `kernel.loaded_modules` |
| Module `name` attribute | `name = "OpenApp"` |
| Python module name | `modules_loaded.OpenApp` |
| File stem | `OpenApp.py` |
| Class-style instance registry | Entries from `_class_module_instances` |

Names are normalized before matching, so simple case and separator differences are tolerated.

### Magic Targets

XKernel also supports magic target names for patches that are not bound to one regular module:

| Target | Callback target | When it becomes available | Use case |
|--------|-----------------|---------------------------|----------|
| `__kernel__` | Active kernel object | When `XPatchKernel.run()` starts | Kernel-level hooks and startup policy patches |
| `__full_load__` | Active kernel object | After user modules finish loading | Global patches that must inspect all loaded modules |

Example global patch:

```python
PATCH_TARGET = "__full_load__"


def apply_patch(kernel, target):
    # target is the active kernel; `kernel is target` for magic targets.
    for module in kernel.loaded_modules.values():
        ...
```

## Callback Names

XKernel uses the first callable found in this order:

| Callback | Description |
|----------|-------------|
| `apply_patch` | Preferred patch callback name |
| `patch` | Short compatibility name |
| `apply` | Short compatibility name |

If no callback is found, the patch is marked as failed.

## Callback Signatures

Sync and async callbacks are supported. Prefer the explicit two-argument form:

```python
async def apply_patch(kernel, target):
    ...
```

Supported forms:

```python
async def apply_patch(kernel, target): ...
async def apply_patch(k, module): ...
async def apply_patch(target): ...
async def apply_patch(kernel): ...
async def apply_patch(manager): ...
async def apply_patch(*args): ...
async def apply_patch(*, kernel, target): ...
async def apply_patch(*, patch_manager, module): ...
```

Parameter names are used for keyword-only callbacks:

| Name | Injected object |
|------|-----------------|
| `kernel`, `k` | Active MCUB kernel |
| `target`, `module`, `mod` | Target module or class-style instance |
| `manager`, `patch_manager` | `XPatchPatchManager` instance |

## Safe Wrapping Pattern

When patching a method, keep the original callable and avoid applying the same wrapper twice.

```python
PATCH_TARGET = "OpenApp"
PATCH_NAME = "OpenAppSafeWrapper"


async def apply_patch(kernel, target):
    if getattr(target, "_xpatch_openapp_wrapped", False):
        return

    original = target.render

    async def render_with_patch(*args, **kwargs):
        result = await original(*args, **kwargs)
        return result.replace("Old", "New")

    target.render = render_with_patch
    target._xpatch_openapp_wrapped = True
```

This pattern keeps the patch idempotent and reduces the risk of stacked wrappers after reloads.

## Patching Class-Style Modules

For class-style modules, the target passed to the callback is the module instance when available.

```python
PATCH_TARGET = "XPatchKernelManager"


def apply_patch(target):
    target.description["en"] = "Patched manager description"
```

Use instance attributes carefully. A patch runs in the active MCUB process and changes live objects.

## Reapplying Patches

From code, patches can be applied manually:

```python
await kernel.apply_patches()
await kernel.apply_patches(target_name="OpenApp", force=True)
await kernel.apply_patches_for_module("OpenApp")
```

`force=True` clears previous state for the selected target and allows the patch to run again. Patch code should still be idempotent because reloads and manual reapply operations can happen during development.

## Error Handling

If a patch import or callback fails, XKernel stores the error in `patch_manager.failed_patches` and logs it through the kernel logger when possible.

The manager patch page shows:

| Section | Meaning |
|---------|---------|
| `Applied` | Callback completed for the target |
| `Pending` | Target is not loaded yet |
| `Failed` | Import or callback failed |

Keep exception messages clear. Do not hide the original exception unless the patch adds better context.

## Patch Rules

- Keep patches small and targeted to one behavior.
- Prefer feature detection with `hasattr` over strict version checks.
- Preserve original callables when wrapping methods.
- Make patches idempotent with a private marker attribute.
- Do not perform blocking I/O in callbacks.
- Do not store secrets, session strings, tokens, or private keys in patch files.
- Do not register MCUB commands from a patch. Use a normal module for commands.
- Do not patch unrelated modules from one patch file unless they are part of the same fix.

## Recommended Patch Header

```python
PATCH_TARGET = "TargetModule"
PATCH_NAME = "ShortPatchName"
PATCH_VERSION = "1.0.0"
PATCH_DESCRIPTION = "Short description of the runtime change"
```

Only `PATCH_TARGET` or `PATCH_TARGETS` and a callback are required by XKernel. The extra fields are recommended for maintainability.
