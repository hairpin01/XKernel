# XKernel

XKernel is an MCUB custom core that adds a runtime patch layer on top of the standard kernel. It keeps normal MCUB module loading intact and applies small patch files after target modules are available.

> [!IMPORTANT]
> XKernel is a custom MCUB core. Install it into `core/kernel/` and run MCUB with `--core XKernel`, or set it as the default core after checking compatibility with your modules.

## Documentation

| Document | Description |
|----------|-------------|
| [Core](doc/core.md) | XKernel core behavior, runtime markers, manager commands, and installation flow |
| [Patches](doc/patches.md) | Patch file format, target resolution, callback signatures, and safe patching rules |

## Install Kernel

```bash
wget https://raw.githubusercontent.com/hairpin01/XKernel/refs/heads/main/XKernel.py &&
mv XKernel.py core/kernel/
```

Run MCUB with XKernel:

```bash
python3 -m core --core XKernel
```

## Install Manager

Add the repository:

```MCUB
.addrepo https://raw.githubusercontent.com/hairpin01/XKernel/main/
```

Install the manager module:

```MCUB
.dlm XPatchKernelManager
```

Open the manager:

```MCUB
.xm
```

## CLI Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `.xm` | `.xmanager`, `.xkm` | Open the inline XKernel manager |
| `.xkinstall` | `.xki` | Install or update XKernel |
| `.xkinstall --default` | `.xki --default` | Install or update XKernel and set it as default core |
| `.xkernelrollback` | `.xkr` | Restore the latest XKernel backup |

> [!NOTE]
> Installing, updating, or rolling back the core requires an MCUB restart before the new core file is used.
