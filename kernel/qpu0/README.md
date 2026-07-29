# Building kernel modules for WSL2

Building out-of-tree kernel modules against Microsoft's stock WSL2 kernel
turned out to be impractical — even with source matching the exact running
version, modules failed with symbol-CRC mismatches and eventually a genuine
ELF relocation error (real build-environment differences from Microsoft's own
CI, not something fixable by config tweaking). The working approach: build a
full custom kernel from the same source and have WSL2 boot it, so there's no
external reference kernel to mismatch against.

## One-time setup

1. Install build dependencies:
   ```bash
   sudo apt install -y build-essential flex bison libssl-dev libelf-dev bc dwarves git
   ```

2. Find the kernel source tag matching your exact `uname -r` (the version
   before `-microsoft-standard-WSL2`):
   ```bash
   git ls-remote --tags https://github.com/microsoft/WSL2-Linux-Kernel.git | grep <your-version>
   ```

3. Clone it and configure:
   ```bash
   git clone --depth 1 --branch <tag> https://github.com/microsoft/WSL2-Linux-Kernel.git ~/WSL2-Linux-Kernel
   cd ~/WSL2-Linux-Kernel
   zcat /proc/config.gz > .config 2>/dev/null || cp Microsoft/config-wsl .config
   ./scripts/config --disable DEBUG_INFO_BTF        # pahole OOM-kills the build otherwise
   ./scripts/config --disable DEBUG_INFO_BTF_MODULES
   make olddefconfig
   ```

4. Fix the local version string. A shallow clone confuses
   `scripts/setlocalversion`'s tag-matching logic (it looks for an
   upstream-style `vX.Y.Z` tag, not Microsoft's `linux-msft-wsl-*` naming) and
   silently appends a stray `+` to the release string, which then fails every
   module's vermagic check:
   ```bash
   export LOCALVERSION=
   ```
   Keep this exported for every build below, in the same shell session (or
   add it to your shell profile).

5. Build a full bootable kernel image (this is the slow step — expect
   15-40+ minutes depending on CPU):
   ```bash
   make -j$(nproc) bzImage
   ```

6. Copy it to the Windows side (`.wslconfig`'s `kernel=` is read by the
   Windows-side launcher before the Linux VM boots, so it must be a Windows
   path):
   ```bash
   mkdir -p /mnt/c/Users/<you>/wsl-kernel
   cp arch/x86/boot/bzImage /mnt/c/Users/<you>/wsl-kernel/bzImage
   ```

7. On the Windows side, create/edit `C:\Users\<you>\.wslconfig`:
   ```ini
   [wsl2]
   kernel=C:\\Users\\<you>\\wsl-kernel\\bzImage
   ```

8. Restart WSL2 **from an actual Windows PowerShell/cmd window** — `wsl.exe`
   is Windows-native and has no equivalent inside the Linux shell itself
   (`apt install wsl` inside Ubuntu installs an unrelated package called
   "Wsman Shell" that happens to share the name):
   ```powershell
   wsl --shutdown
   ```
   Reopen your WSL terminal. `uptime` should show a few seconds, confirming a
   real reboot, and `uname -r` should now be backed by the kernel you built.

## Building this module

Once the custom kernel is running:

```bash
cd kernel/qpu0
cp ~/WSL2-Linux-Kernel/vmlinux.symvers Module.symvers   # or `make` in the kernel tree once first
make
sudo insmod qpu_driver.ko
```

No `--force` flags should ever be needed — since the running kernel and the
module were built from the same source tree, there's nothing to mismatch.
