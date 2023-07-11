from functions import *
from urllib.request import urlretrieve


def config(de_name: str, distro_version: str, verbose: bool, kernel_version: str, shell: str) -> None:
    set_verbose(verbose)
    print_status("Configuring Pop!_OS")

    print_status("Removing casper debs")
    # List of packages to remove was taken from /cdrom/casper/filesystem.manifest-remove from the iso
    chroot("apt-get purge -y btrfs-progs casper cifs-utils distinst distinst-v2 dmraid expect f2fs-tools fatresize "
           "gettext gparted gparted-common grub-common grub2-common kpartx kpartx-boot libdistinst libdmraid1.0.0.rc16"
           " libinih1 libnss-mymachines localechooser-data os-prober pop-installer pop-installer-casper pop-shop-casper"
           " squashfs-tools systemd-container tcl-expect user-setup xfsprogs kernelstub efibootmgr")
    # Add eupnea repo
    mkdir("/mnt/depthboot/usr/local/share/keyrings", create_parents=True)
    # download public key
    urlretrieve("https://eupnea-linux.github.io/apt-repo/public.key",
                filename="/mnt/depthboot/usr/local/share/keyrings/eupnea.key")
    with open("/mnt/depthboot/etc/apt/sources.list.d/eupnea.list", "w") as file:
        file.write("deb [signed-by=/usr/local/share/keyrings/eupnea.key] https://eupnea-linux.github.io/"
                   "apt-repo/debian_ubuntu jammy main")
    # update apt
    print_status("Updating and upgrading all packages")
    chroot("apt-get update -y")
    # TODO: Remove this once the iso is updated
    # This file was updated in the remote package, but not on the iso. This results in apt prompting on what to do
    # -> just copy over the new file from the package
    cpfile("configs/pop-os/20apt-esm-hook.conf", "/mnt/depthboot/etc/apt/apt.conf.d/20apt-esm-hook.conf")
    chroot("apt-get upgrade -y")
    print_status("Installing eupnea packages")
    # Install eupnea packages
    chroot("apt-get install -y eupnea-utils eupnea-system keyd")

    # Install kernel
    chroot(f"apt-get install -y eupnea-{kernel_version}-kernel")

    # Replace input-synaptics with newer input-libinput, for better touchpad support
    print_status("Upgrading touchpad drivers")
    chroot("apt-get remove -y xserver-xorg-input-synaptics")
    chroot("apt-get install -y xserver-xorg-input-libinput")

    # Enable wayland
    print_status("Enabling Wayland")
    with open("/mnt/depthboot/etc/gdm3/custom.conf", "r") as file:
        gdm_config = file.read()
    with open("/mnt/depthboot/etc/gdm3/custom.conf", "w") as file:
        file.write(gdm_config.replace("WaylandEnable=false", "#WaylandEnable=false"))
    # TODO: Set wayland as default

    match shell:
        case "bash":
            pass # bash is preinstalled, no need to install anything
        case "fish":
            print_status("Installing fish")
            chroot("apt-get install -y fish")
        case "fish":
            print_status("Installing zsh")
            chroot("apt-get install -y zsh")

    print_status("Pop!_OS setup complete")
